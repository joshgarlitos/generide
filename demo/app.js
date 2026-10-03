// generide in the browser: pick a few settings, press go, watch a Mine Train
// evolve. The engine runs in worker.js; this file only shows what it sends.
// Every decision about the ride (validation, stats, warnings) is made in
// Python (rct2/demo.py, reusing rct2/webui.py's wording). Text always goes
// in through textContent, and the engine's SVG pictures are shown as images,
// never inserted as markup.
//
// States, as in the plan's state diagram: loading, unsupported, settings,
// running, result, error.

const REPO = "https://github.com/joshgarlitos/generide";
const LOCAL_SETUP = `${REPO}#use-the-web-ui`;

const state = {
  screen: "loading", // which view is showing
  worker: null,
  ready: false,
  view: null, // settings_view() from the engine, once loaded
  values: null, // the last values the visitor ran with, kept for the next run
  onReady: null, // the settings form's hook for enabling go
  showErrors: null, // the settings form's hook for showing field errors
  loadError: null, // a background engine load that failed while a result showed
  run: null, // the run in progress
  validateId: 0,
  urls: {}, // object URL per picture slot, revoked on replace
};

// ---------------------------------------------------------------------------
// Helpers, as in rct2/webui_static/app.js

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function kids(nodes) {
  return nodes.flat().filter((n) => n !== null && n !== undefined && n !== false);
}

function put(el, ...nodes) {
  el.replaceChildren(...kids(nodes));
}

function win({ colour = "grey", page = null, title, level = 2, wide = false }, ...body) {
  return h("section", { class: `win c-${colour}${wide ? " wide" : ""}` },
    h(`h${level}`, { class: "win-caption" }, title),
    h("div", { class: page ? `win-body win-page c-${page}` : "win-body" }, ...body));
}

const NOTICE = {
  warn: { colour: "yellow", glyph: "!" },
  bad: { colour: "bordeaux", glyph: "✕" },
  good: { colour: "darkgreen", glyph: "✓" },
};

function banner(kind, ...content) {
  const look = NOTICE[kind] || NOTICE.warn;
  return h("div", { class: `notice c-${look.colour}`, role: kind === "bad" ? "alert" : null },
    h("span", { class: "notice-glyph", "aria-hidden": "true" }, look.glyph),
    h("div", { class: "notice-body" }, ...content));
}

function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return mins ? `${mins}m ${String(secs).padStart(2, "0")}s` : `${secs}s`;
}

// A view replaces everything in <main> and moves focus to its heading, so a
// keyboard or screen-reader user lands on the new state.
function setView(screen, ...nodes) {
  state.screen = screen;
  const main = document.getElementById("view");
  put(main, ...nodes);
  const heading = main.querySelector("h1");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus();
  }
}

// Each picture slot (plan, profile, score chart, download) keeps one object
// URL; replacing a slot's picture releases the one it replaces, so a run
// that sends many updates does not hold every old picture in memory.
function slotUrl(slot, blob) {
  if (state.urls[slot]) URL.revokeObjectURL(state.urls[slot]);
  state.urls[slot] = URL.createObjectURL(blob);
  return state.urls[slot];
}

function releasePictures() {
  for (const url of Object.values(state.urls)) URL.revokeObjectURL(url);
  state.urls = {};
}

function picture(slot, svg, caption, alt) {
  const src = slotUrl(slot, new Blob([svg], { type: "image/svg+xml" }));
  return h("figure", { class: "well well-graph graph" },
    h("img", { src, alt }), caption && h("figcaption", {}, caption));
}

function repoLink(text) {
  return h("a", { href: REPO }, text || "generide on GitHub");
}

// ---------------------------------------------------------------------------
// The engine

function startWorker() {
  state.ready = false;
  const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
  worker.onmessage = (event) => onMessage(worker, event.data);
  worker.onerror = (event) => {
    event.preventDefault();
    onMessage(worker, { type: "error", where: "load", message: event.message || "The engine could not start." });
  };
  state.worker = worker;
}

function onMessage(worker, message) {
  if (worker !== state.worker) return; // a stopped run's worker, already replaced
  switch (message.type) {
    case "loading":
      if (!state.view) showLoading(message);
      break;
    case "ready":
      state.ready = true;
      state.view = message.view;
      // A replacement engine can finish loading while the visitor reads a
      // result; only the loading screen moves on by itself.
      if (state.screen === "loading") showSettings();
      else if (state.screen === "settings" && state.onReady) state.onReady();
      break;
    case "validation":
      if (state.showErrors && message.id === state.validateId) state.showErrors(message.errors);
      break;
    case "invalid":
      endRun();
      showSettings(message.errors);
      break;
    case "progress":
      if (state.run) state.run.progress(message.payload);
      break;
    case "best":
      if (state.run) state.run.best(message.payload);
      break;
    case "done":
      if (state.run) showResult(Object.assign({}, message.payload, { stopped_early: false }));
      break;
    case "error":
      // A replacement engine loading behind a result (after Stop) must not
      // wipe the ride the visitor is reading; the failure shows on New run.
      if (message.where === "load" && state.screen === "result") state.loadError = message;
      else showError(message);
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// Views

function showUnsupported() {
  setView("unsupported", win({ colour: "bordeaux", title: "This page needs a desktop browser", level: 1 },
    h("p", {}, "generide runs here by putting a Python runtime in your browser, which needs WebAssembly and background workers. This browser does not offer both."),
    h("p", {}, "Open this page in a current desktop browser such as Chrome, Firefox, Safari, or Edge, or run generide on your own machine from ", repoLink(), ".")));
}

function showLoading(message) {
  const steps = message.steps || 3;
  const step = message.step || 1;
  setView("loading", win({ colour: "grey", title: "Getting generide ready", level: 1 },
    h("p", {}, "generide runs entirely in your browser. The first visit downloads a Python runtime, which takes a few seconds."),
    h("div", { class: "progressbar", role: "progressbar", "aria-valuemin": "0",
      "aria-valuemax": String(steps), "aria-valuenow": String(step - 1), "aria-label": "Loading" },
    h("span", { style: `width:${Math.round((100 * (step - 1)) / steps)}%` })),
    h("p", { "aria-live": "polite" }, `Step ${step} of ${steps}: ${message.text}`)));
}

function endRun() {
  if (state.run) state.run.finish();
  state.run = null;
}

function showError(message) {
  const lastRide = state.run && state.run.last;
  endRun();
  const what = message.where === "load"
    ? "The demo could not start."
    : "The run stopped with an error.";
  const retry = h("button", { type: "button", class: "primary" }, "Try again");
  retry.addEventListener("click", () => {
    if (state.worker) state.worker.terminate();
    state.view = null;
    state.onReady = null;
    startWorker();
  });
  releasePictures();
  setView("error", win({ colour: "bordeaux", title: "Something went wrong", level: 1 },
    banner("bad", h("p", {}, what), h("p", { class: "small" }, message.message)),
    lastRide ? h("p", {}, "The run had found a ride before the error; it is not kept.") : null,
    h("div", { class: "actions" }, retry),
    h("p", {}, "If this keeps happening, generide also runs on your own machine. See ", repoLink(), ".")));
}

function makeField(setting, value, fields) {
  const id = `f-${setting.key}`;
  const error = h("p", { class: "error", id: `${id}-error`, "aria-live": "polite" });
  const described = `${id}-hint ${id}-error`;
  const unit = setting.unit ? ` ${setting.unit}` : "";
  let control;
  let read;
  let hint;
  if (setting.kind === "window") {
    const pair = value ? [value.min ?? value[0], value.max ?? value[1]] : ["", ""];
    const low = h("input", { type: "number", step: "any", id, "aria-label": `${setting.label} lowest`,
      "aria-describedby": described, placeholder: "lowest", value: pair[0] ?? "" });
    const high = h("input", { type: "number", step: "any", "aria-label": `${setting.label} highest`,
      "aria-describedby": described, placeholder: "highest", value: pair[1] ?? "" });
    control = h("div", { class: "pair" }, low, h("span", {}, "to"), high);
    read = () => ({ min: low.value, max: high.value });
    hint = `${setting.minimum} to ${setting.maximum}. Leave empty for any.`;
  } else {
    const isSeed = setting.key === "seed";
    control = h("input", { type: "number", id, "aria-describedby": described,
      step: "1", min: setting.minimum, max: setting.maximum,
      value: value === null || value === undefined ? "" : value,
      placeholder: isSeed ? "random" : null });
    read = () => control.value;
    hint = isSeed
      ? "The same seed and settings always give the same ride. Clear it for a random one."
      : `${setting.minimum} to ${setting.maximum}${unit}.`;
  }
  const more = h("div", { class: "more-info", id: `${id}-more`, hidden: true },
    h("p", {}, setting.help), setting.note ? h("p", {}, setting.note) : null);
  const info = h("button", { type: "button", class: "info", "aria-expanded": "false",
    "aria-controls": `${id}-more`, "aria-label": `About ${setting.label}` }, "?");
  info.addEventListener("click", () => {
    const open = more.hidden;
    more.hidden = !open;
    info.setAttribute("aria-expanded", String(open));
  });
  const box = h("div", { class: "field" },
    h("div", { class: "field-head" }, h("label", { for: id, class: "label" }, setting.label), info),
    control, h("p", { class: "hint", id: `${id}-hint` }, hint), more, error);
  fields[setting.key] = { box, read, error };
  return box;
}

function showSettings(errors) {
  releasePictures();
  const view = state.view;
  const values = state.values || {};
  const fields = {};
  const rows = view.settings.map((setting) =>
    makeField(setting, setting.key in values ? values[setting.key] : setting.default, fields));

  const readValues = () => {
    const out = {};
    for (const [key, field] of Object.entries(fields)) out[key] = field.read();
    return out;
  };
  const showErrors = (errs) => {
    for (const [key, field] of Object.entries(fields)) {
      const message = (errs || {})[key] || "";
      field.error.textContent = message;
      field.box.classList.toggle("has-error", !!message);
    }
  };
  state.showErrors = showErrors;

  const go = h("button", { type: "submit", class: "primary" }, "Go");
  const readyNote = h("p", { class: "muted small", "aria-live": "polite" });
  const syncReady = () => {
    go.disabled = !state.ready;
    readyNote.textContent = state.ready ? "" : "Getting the engine ready…";
  };
  state.onReady = syncReady;
  syncReady();

  let timer = null;
  const form = h("form", {
    class: "form-stack",
    novalidate: true,
    onchange: () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (!state.ready) return;
        state.validateId += 1;
        state.worker.postMessage({ type: "validate", id: state.validateId, values: readValues() });
      }, 300);
    },
    onsubmit: (event) => {
      event.preventDefault();
      if (!state.ready) return;
      state.values = readValues();
      startRun(state.values);
    },
  },
  h("div", { class: "form-grid" }, rows),
  h("div", { class: "actions" }, go, readyNote));

  setView("settings", win({ colour: "brown", title: "Evolve a Mine Train", level: 1 },
    h("p", {}, "generide breeds RollerCoaster Tycoon 2 Mine Train layouts with a genetic algorithm, scores each one with the game's own rating formulas, and keeps the best. Press Go to watch a ride take shape over ",
      `${view.generations} generations of ${view.population} tracks. It runs in your browser and takes about half a minute.`),
    h("p", { class: "muted small" }, "The defaults make a good first ride. Click ? next to a setting to read what it does."),
    form));
  if (errors) {
    showErrors(errors);
    const first = Object.keys(errors)[0];
    if (fields[first]) fields[first].box.querySelector("input").focus();
  }
}

function startRun(values) {
  releasePictures();
  state.onReady = null;
  const started = performance.now();
  const total = state.view.generations;
  const metricValue = (text) => h("div", { class: "value" }, text);
  const genValue = metricValue(`0 of ${total}`);
  const timeValue = metricValue("0s");
  const bar = h("span", { style: "width:0%" });
  const barBox = h("div", { class: "progressbar", role: "progressbar", "aria-valuemin": "0",
    "aria-valuemax": String(total), "aria-valuenow": "0", "aria-label": "Generations bred" }, bar);
  const live = h("p", { class: "visually-hidden", "aria-live": "polite" });
  const pictures = h("div", { class: "pictures" },
    h("p", {}, "The first ride appears after the first generation."));
  const fitness = h("div", { class: "score-chart" });
  const stop = h("button", { type: "button", class: "danger", disabled: true }, "Stop and keep the best ride");
  const stopNote = h("span", { class: "muted small" }, "Stop works once the first ride appears.");

  const tick = setInterval(() => {
    timeValue.textContent = duration((performance.now() - started) / 1000);
  }, 500);

  const run = {
    last: null,
    seed: null,
    progress(p) {
      run.seed = p.seed;
      const done = p.generation + 1;
      genValue.textContent = `${done} of ${p.generations}`;
      bar.style.width = `${Math.min(100, (100 * done) / p.generations)}%`;
      barBox.setAttribute("aria-valuenow", String(done));
      if (done % 5 === 0 || done === p.generations) live.textContent = `Generation ${done} of ${p.generations}`;
      put(fitness, picture("fitness", p.fitness_svg, "Best score by generation.", "Best score by generation"));
    },
    best(b) {
      run.last = b;
      put(pictures,
        picture("plan", b.plan_svg, "Best ride so far: top-down plan, lighter is higher.", "Top-down plan of the best ride so far"),
        picture("profile", b.profile_svg, "Best ride so far: side profile. Solid line is height, dashed is speed, drops are numbered.", "Side profile of the best ride so far"));
      stop.disabled = false;
      stopNote.textContent = "";
    },
    finish() {
      clearInterval(tick);
    },
  };
  state.run = run;

  stop.addEventListener("click", () => {
    if (!run.last) return;
    // Plan KTD3: end the run by ending its worker. The last "best" message is
    // a whole ride, so nothing is lost, and a fresh engine starts loading for
    // the next run straight away.
    state.worker.terminate();
    const last = run.last;
    startWorker();
    showResult(Object.assign({}, last, {
      seed: run.seed, values, generations_run: last.generation, stopped_early: true,
    }));
  });

  setView("running", win({ colour: "grey", title: "Evolving your ride", level: 1 },
    win({ colour: "darkgreen", title: "Run progress" },
      h("div", { class: "live" },
        h("div", { class: "metric" }, h("div", { class: "label" }, "Generation"), genValue),
        h("div", { class: "metric" }, h("div", { class: "label" }, "Elapsed"), timeValue)),
      barBox, live,
      h("div", { class: "actions" }, stop, stopNote)),
    pictures, fitness));
  state.worker.postMessage({ type: "run", values });
}

function statsTables(result) {
  const view = result.stats_view;
  if (!view || !view.simulated.length) return null;
  return h("div", { class: "two-col" },
    h("div", {},
      h("h2", {}, "Ratings ", h("span", { class: "tag estimate" }, "estimates")),
      h("div", { class: "well table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Rating"), h("th", { class: "num" }, "Estimate"))),
        h("tbody", {}, view.ratings.map((r) => h("tr", {},
          h("td", {}, r.label), h("td", { class: "num" }, r.estimate || "–"))))))),
    h("div", {},
      h("h2", {}, "From generide's simulation ", h("span", { class: "tag estimate" }, "estimates")),
      h("div", { class: "well table-wrap" }, h("table", {}, h("tbody", {},
        view.simulated.map((r) => h("tr", {}, h("th", { scope: "row" }, r.label), h("td", {}, r.value))))))));
}

function showResult(result) {
  endRun();
  releasePictures();
  const seed = result.seed ?? (result.values && result.values.seed);
  const hasSeed = seed !== null && seed !== undefined && seed !== "";
  const hasRide = result.td6 instanceof Uint8Array;

  const download = hasRide
    ? h("a", {
      class: "button primary",
      href: slotUrl("download", new Blob([result.td6], { type: "application/octet-stream" })),
      download: `generide-mine-train${hasSeed ? `-seed-${seed}` : ""}.td6`,
    }, "Download the .td6")
    : null;

  const again = h("button", { type: "button" }, "New run");
  again.addEventListener("click", () => {
    if (state.loadError) {
      const failed = state.loadError;
      state.loadError = null;
      showError(failed);
    } else {
      showSettings();
    }
  });

  const command = result.cli_args
    ? h("div", { class: "well" }, h("p", { class: "code-line" },
      ["python", "evolve_coaster.py", ...result.cli_args].join(" ")))
    : null;

  setView("result", win({ colour: "grey", title: result.stopped_early ? "Your ride (stopped early)" : "Your ride", level: 1 },
    (result.warnings || []).length
      ? banner("warn", h("p", {}, h("strong", {}, "Check this before using the ride:")),
        h("ul", {}, result.warnings.map((w) => h("li", {}, w))))
      : null,
    hasRide ? null : banner("bad", h("p", {}, "No buildable ride was found, so there is nothing to download. Try another seed or larger footprint.")),
    h("div", { class: "pictures" },
      picture("plan", result.plan_svg, "Top-down plan, lighter is higher.", "Top-down plan of the ride"),
      picture("profile", result.profile_svg, "Side profile. Solid line is height, dashed is speed, drops are numbered.", "Side profile of the ride")),
    statsTables(result),
    h("div", { class: "actions" }, download, again),
    hasSeed
      ? h("p", { class: "small" }, `Seed ${seed}. The same seed and settings give the same ride again.`)
      : null,
    win({ colour: "brown", title: "Take it further" },
      h("p", {}, "To put the ride in RollerCoaster Tycoon 2, copy the .td6 into OpenRCT2's track folder and pick it from the Mine Train track designs. Checking a ride in the real game and installing it from generide need the local tool and OpenRCT2: ",
        h("a", { href: LOCAL_SETUP }, "see how to run generide on your machine"), "."),
      command ? h("p", {}, "This command makes the same ride locally:") : null,
      command,
      h("p", {}, "The code, the design notes, and the devlog are on ", repoLink("GitHub"), "."))));
}

// ---------------------------------------------------------------------------
// Start

if (typeof WebAssembly !== "object" || typeof Worker !== "function") {
  showUnsupported();
} else {
  showLoading({ step: 1, steps: 3, text: "Downloading the Python runtime" });
  startWorker();
}
