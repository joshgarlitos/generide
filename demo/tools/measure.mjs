// Times the page's runs in Pyodide, the runtime the browser uses, and checks
// that a Pyodide run makes the same .td6 as CPython (plan U4).
//
// Usage, from demo/ after `python ../tools/build_demo.py`:
//   node tools/measure.mjs --sizes 20x20,25x25 --seeds 1,2,3
//
// Runs under Node's V8, the same WebAssembly engine as Chrome; other
// browsers may differ. Ride quality across many seeds is ride_bar.py's job.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const site = resolve(repo, "_site");

function arg(name, fallback) {
  const at = process.argv.indexOf(`--${name}`);
  return at === -1 ? fallback : process.argv[at + 1];
}

const sizes = arg("sizes", "30x30").split(",").map((s) => s.split("x").map(Number));
const seeds = arg("seeds", "1,2,3").split(",").map(Number);

// The settings corners a visitor can reach. "slow" is the largest footprint
// and longest station the page allows, which grows the longest tracks.
const maximums = JSON.parse(execFileSync("python3", ["-c",
  "import json; from rct2 import demo; print(json.dumps(demo.MAXIMUMS))"], { cwd: repo }));
const corners = {
  default: {},
  slow: {
    station_length: maximums.station_length,
    max_width: maximums.max_width,
    max_depth: maximums.max_depth,
  },
  small: { station_length: 2, max_width: 12, max_depth: 12 },
};

const loadStart = performance.now();
const py = await loadPyodide();
const manifest = JSON.parse(readFileSync(resolve(site, "engine.json"), "utf8"));
py.unpackArchive(new Uint8Array(readFileSync(resolve(site, manifest.archive))), "zip",
  { extractDir: "/home/pyodide/generide" });
py.runPython("import sys; sys.path.insert(0, '/home/pyodide/generide')");
const demo = py.pyimport("rct2.demo");
console.log(`Pyodide ${py.version}: loaded and imported in ${((performance.now() - loadStart) / 1000).toFixed(1)}s`);

function runOnce(values, generations, population) {
  const start = performance.now();
  const result = demo.run(py.toPy(values), () => {}, generations, population);
  const seconds = (performance.now() - start) / 1000;
  const data = result.toJs({ dict_converter: Object.fromEntries, create_pyproxies: false });
  result.destroy();
  return { seconds, data };
}

// Same bytes as CPython?
{
  const { data } = runOnce({ seed: 123, station_length: 6 }, 4, 8);
  const mine = createHash("sha256").update(data.td6).digest("hex");
  const theirs = execFileSync("python3", ["-c",
    "import hashlib; from rct2 import demo;"
    + "r = demo.run({'seed': 123, 'station_length': 6}, lambda k, p: None, generations=4, population=8);"
    + "print(hashlib.sha256(r['td6']).hexdigest())"], { cwd: repo, encoding: "utf8" }).trim();
  console.log(`Pyodide vs CPython .td6 (seed 123, 4x8): ${mine === theirs ? "identical" : "DIFFERENT"} (${mine.slice(0, 16)})`);
}

const rows = [];
for (const [generations, population] of sizes) {
  for (const [corner, values] of Object.entries(corners)) {
    const times = [];
    let bar = 0;
    for (const seed of seeds) {
      const { seconds, data } = runOnce(Object.assign({ seed }, values), generations, population);
      times.push(seconds);
      if (data.meets_ride_bar) bar += 1;
    }
    times.sort((a, b) => a - b);
    const row = {
      size: `${generations}x${population}`, corner,
      median: times[Math.floor(times.length / 2)], worst: times[times.length - 1], bar: `${bar}/${seeds.length}`,
    };
    rows.push(row);
    console.log(`${row.size} ${corner.padEnd(7)} median ${row.median.toFixed(1)}s worst ${row.worst.toFixed(1)}s ride bar ${row.bar}`);
  }
}
console.log(JSON.stringify(rows));
