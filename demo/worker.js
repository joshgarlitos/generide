// Runs generide's engine for the page, off the main thread (plan KTD2).
//
// Loads the vendored Pyodide runtime, unpacks the engine archive the build
// named in engine.json, and imports rct2.demo. Every payload the engine
// emits goes straight to the page as a message; the page owns what is shown.
// Stopping a run is the page terminating this worker (plan KTD3), which is
// why every "best" message already carries a whole ride.
import { loadPyodide } from "./pyodide/pyodide.mjs";

const ENGINE_DIR = "/home/pyodide/generide";
let demo = null;
let py = null;

const toJs = (value) =>
  value && typeof value.toJs === "function"
    ? value.toJs({ dict_converter: Object.fromEntries, create_pyproxies: false })
    : value;

function post(message) {
  const transfer = [];
  const td6 = message.payload && message.payload.td6;
  if (td6 instanceof Uint8Array) transfer.push(td6.buffer);
  self.postMessage(message, transfer);
}

async function fetchEngine() {
  const manifest = await (await fetch(new URL("./engine.json", import.meta.url), { cache: "no-cache" })).json();
  const response = await fetch(new URL(`./${manifest.archive}`, import.meta.url));
  if (!response.ok) throw new Error(`The engine download failed (${response.status}).`);
  return { archive: await response.arrayBuffer(), page: manifest.page };
}

async function boot() {
  post({ type: "loading", step: 1, steps: 3, text: "Downloading the Python runtime (about 10 MB, once)" });
  // The engine downloads while the runtime does.
  const engine = fetchEngine();
  engine.catch(() => {}); // awaited below; this only stops an early unhandled rejection
  py = await loadPyodide({ indexURL: new URL("./pyodide/", import.meta.url).href });

  post({ type: "loading", step: 2, steps: 3, text: "Downloading generide" });
  const { archive, page } = await engine;
  py.unpackArchive(archive, "zip", { extractDir: ENGINE_DIR });

  post({ type: "loading", step: 3, steps: 3, text: "Starting generide" });
  py.runPython(`import sys\nsys.path.insert(0, "${ENGINE_DIR}")`);
  demo = py.pyimport("rct2.demo");
  const view = demo.settings_view();
  // The page version the build stamped into the manifest; the page checks it
  // against its own.
  post({ type: "ready", view: toJs(view), page });
  view.destroy();
}

function emit(kind, payload) {
  // Pyodide releases the proxies it passes to a JavaScript callback once
  // the call returns, so copy the payload out now.
  const data = toJs(payload);
  post({ type: kind, payload: data });
}

self.onmessage = (event) => {
  const message = event.data;
  try {
    if (message.type === "validate") {
      const result = demo.validate(py.toPy(message.values));
      post({ type: "validation", id: message.id, errors: toJs(result).errors || {} });
      result.destroy();
    } else if (message.type === "run") {
      const result = demo.run(py.toPy(message.values), emit);
      const data = toJs(result);
      result.destroy();
      if (data.errors) post({ type: "invalid", errors: data.errors });
      else post({ type: "done", payload: data });
    }
  } catch (err) {
    post({ type: "error", where: message.type, message: String(err && err.message ? err.message : err) });
  }
};

boot().catch((err) => {
  post({ type: "error", where: "load", message: String(err && err.message ? err.message : err) });
});
