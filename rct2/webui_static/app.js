// generide's page. Every decision (validation, what changed, estimates,
// warnings, time remaining) is made by the server in rct2/webui.py; this
// file fetches, places what comes back, and polls. Text always goes in via
// textContent, never as markup.
"use strict";

const POLL_MS = 1000;
const STALE_AFTER_S = 30;

const state = {
  settings: null, // GET /api/settings, loaded once
  active: null, // the running run, from GET /api/active
  refresh: null, // the current view's poll function, if it has one
  polling: false,
  viewToken: 0, // bumped on every navigation so late responses are dropped
  isoAngle: 0, // the isometric view's quarter turn, kept as best rides arrive
};

// ---------------------------------------------------------------------------
// Helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

class ApiError extends Error {
  constructor(status, body) {
    super((body && body.error) || `Request failed (${status})`);
    this.status = status;
    this.body = body || {};
  }
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (method !== "GET") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body || {});
  }
  const response = await fetch(path, options);
  let data = null;
  try {
    data = await response.json();
  } catch (_) {
    data = null;
  }
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

function duration(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const s = Math.max(0, Math.round(seconds));
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = s % 60;
  if (hrs) return `${hrs}h ${mins}m`;
  if (mins) return `${mins}m ${String(secs).padStart(2, "0")}s`;
  return `${secs}s`;
}

function when(stamp) {
  if (!stamp) return "";
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return stamp;
  return date.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function num(value, digits) {
  return value === null || value === undefined ? "" : Number(value).toFixed(digits);
}

function statusTag(status) {
  const words = {
    running: "running", completed: "completed", stopped: "stopped early",
    failed: "failed", interrupted: "interrupted", unreadable: "unreadable",
  };
  return h("span", { class: `tag ${status}` }, words[status] || status);
}

// A window, as docs/design/README.md defines it: a raised frame in one colour
// with a title bar, and optionally a page in a second colour, like the
// game's ride window (grey frame, bordeaux page). The colour says what kind
// of window it is; see the window roles table in the design doc.
function win({ colour = "grey", page = null, title, level = 2, wide = false, extra = "" }, ...body) {
  return h("section", { class: `win c-${colour}${wide ? " wide" : ""}${extra ? " " + extra : ""}` },
    h(`h${level}`, { class: "win-caption" }, title),
    h("div", { class: page ? `win-body win-page c-${page}` : "win-body" }, ...body));
}

// A notice inside a window. The glyph repeats what the colour says, so the
// meaning never rests on colour alone.
const NOTICE = {
  warn: { colour: "yellow", glyph: "!", label: "Warning" },
  bad: { colour: "bordeaux", glyph: "\u2715", label: "Problem" },
  good: { colour: "darkgreen", glyph: "\u2713", label: "Done" },
};

function banner(kind, ...content) {
  const look = NOTICE[kind] || NOTICE.warn;
  return h("div", { class: `notice c-${look.colour}`, role: kind === "bad" ? "alert" : null },
    h("span", { class: "notice-glyph", "aria-hidden": "true" }, look.glyph),
    h("div", { class: "notice-body" }, ...content));
}

// Asks before a destructive action, in the page rather than a browser
// dialog: a bordeaux prompt, as the game asks before demolishing a ride.
// Cancel takes the focus, so Enter never destroys anything by accident.
function askFirst(slot, title, message, yesLabel, onYes) {
  const yes = h("button", { type: "button" }, yesLabel);
  const no = h("button", { type: "button", onclick: () => put(slot) }, "Cancel");
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    no.disabled = true;
    await onYes();
  });
  put(slot, h("section", { class: "win c-bordeaux prompt", role: "alertdialog", "aria-label": title },
    h("h2", { class: "win-caption" }, title),
    h("div", { class: "win-body" }, h("p", {}, message), h("div", { class: "actions" }, yes, no))));
  no.focus();
}

function errorBanner(err) {
  return banner("bad", h("p", {}, err.message || String(err)));
}

// replaceChildren/append turn null into the text "null"; these drop empties.
function kids(nodes) {
  return nodes.flat().filter((n) => n !== null && n !== undefined && n !== false);
}

function put(el, ...nodes) {
  el.replaceChildren(...kids(nodes));
}

function add(el, ...nodes) {
  el.append(...kids(nodes));
}

function setView(...nodes) {
  put(document.getElementById("view"), ...nodes);
}

// Charts are drawn by rct2/render.py with their own dark background, and sit
// in a dark graph well like the game's ride graphs.
function picture(src, caption, alt) {
  return h("figure", { class: "well well-graph graph" },
    h("img", { src, alt, loading: "lazy" }), caption && h("figcaption", {}, caption));
}

// The isometric ride picture is inline SVG that iso-view.js draws and turns.
async function fetchSvg(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`The picture could not be loaded (${response.status}).`);
  return response.text();
}

function isoGroup() {
  return IsoView.createGroup(h, { angle: state.isoAngle, onAngle: (angle) => { state.isoAngle = angle; } });
}

// ---------------------------------------------------------------------------
// Routing

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  return { parts, params: new URLSearchParams(query || "") };
}

async function route() {
  state.viewToken += 1;
  document.title = "generide";
  state.refresh = null;
  const { parts, params } = parseHash();
  const page = parts[0] || "";
  for (const link of document.querySelectorAll("[data-nav]")) {
    if (link.dataset.nav === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  try {
    if (page === "new") await showNewRun(params.get("rerun"));
    else if (page === "library") await showLibrary();
    else if (page === "run" && parts[1]) await showRun(parts[1], params.get("tab"));
    else if (page === "compare") await showCompare((params.get("ids") || "").split(",").filter(Boolean));
    else {
      const { runs } = await api("GET", "/api/runs");
      location.replace(runs.length ? "#/library" : "#/new");
    }
  } catch (err) {
    setView(win({ colour: "bordeaux", title: "Something went wrong", level: 1, extra: "prompt" },
      h("p", {}, err.message || String(err))));
  }
  document.getElementById("view").focus({ preventScroll: true });
}

// ---------------------------------------------------------------------------
// Polling: the active-run chip, and the current view's own refresh

async function poll() {
  if (state.polling) return;
  state.polling = true;
  try {
    const { active } = await api("GET", "/api/active");
    state.active = active;
    const chip = document.getElementById("active-chip");
    document.getElementById("idle-text").hidden = !!active;
    if (active) {
      const live = active.live;
      chip.hidden = false;
      chip.href = `#/run/${active.id}`;
      document.getElementById("active-chip-text").textContent =
        `Running: generation ${live.generation ?? 0} of ${live.generations_planned}`;
    } else {
      chip.hidden = true;
    }
    if (state.refresh) await state.refresh();
  } catch (_) {
    // The server may be restarting; the next tick tries again.
  } finally {
    state.polling = false;
  }
}

async function loadSettings() {
  if (!state.settings) state.settings = await api("GET", "/api/settings");
  return state.settings;
}

// ---------------------------------------------------------------------------
// New run

async function showNewRun(rerunId) {
  const token = state.viewToken;
  const config = await loadSettings();
  let values = {};
  let parent = null;
  let source = null;
  if (rerunId) {
    const rerun = await api("GET", `/api/runs/${encodeURIComponent(rerunId)}/rerun`);
    values = rerun.values;
    parent = rerun.parent;
    source = (await api("GET", `/api/runs/${encodeURIComponent(rerunId)}`)).run;
  }
  const { active } = await api("GET", "/api/active");
  state.active = active;
  if (token !== state.viewToken) return;

  const fields = {};
  // Each field shows its label, its control, and one short hint (the unit
  // and range). The full explanation sits behind a "?" button, so the form
  // stays short until someone asks.
  const makeField = (setting) => {
    const id = `f-${setting.key}`;
    const value = setting.key in values ? values[setting.key] : setting.default;
    const error = h("p", { class: "error", id: `${id}-error`, "aria-live": "polite" });
    const described = `${id}-hint ${id}-error`;
    const unit = setting.unit ? ` ${setting.unit}` : "";
    const hasRange = setting.minimum !== null && setting.maximum !== null;
    let control;
    let read;
    let hint = null;
    let defaultText = null;

    if (setting.kind === "window") {
      const low = h("input", { type: "number", step: "any", id, "aria-label": `${setting.label} lowest`,
        "aria-describedby": described, placeholder: "lowest", value: value ? value.min ?? value[0] : "" });
      const high = h("input", { type: "number", step: "any", "aria-label": `${setting.label} highest`,
        "aria-describedby": described, placeholder: "highest", value: value ? value.max ?? value[1] : "" });
      control = h("div", { class: "pair" }, low, h("span", {}, "to"), high);
      read = () => ({ min: low.value, max: high.value });
      hint = `${setting.minimum} to ${setting.maximum}. Leave empty for any.`;
      defaultText = "Default: not set.";
    } else if (setting.kind === "choice") {
      control = h("select", { id, "aria-describedby": described },
        setting.choices.map((c) => h("option", { value: c, selected: c === value }, c)));
      read = () => control.value;
      defaultText = `Default: ${setting.default}.`;
    } else if (setting.kind === "bool") {
      control = h("input", { type: "checkbox", id, "aria-describedby": described, checked: !!value });
      read = () => control.checked;
    } else if (setting.kind === "path") {
      control = h("input", { type: "text", id, "aria-describedby": described, value: value || "",
        placeholder: "/path/to/design.td6", autocomplete: "off", spellcheck: "false" });
      read = () => control.value;
      hint = "Leave empty for a generated loop.";
    } else {
      const isSeed = setting.key === "seed";
      control = h("input", { type: "number", id, "aria-describedby": described,
        step: setting.kind === "int" ? "1" : "any",
        min: setting.minimum, max: setting.maximum,
        value: value === null || value === undefined ? "" : value,
        placeholder: isSeed ? "random" : null });
      read = () => control.value;
      if (isSeed) {
        hint = "Leave empty for a random seed.";
      } else {
        hint = hasRange ? `${setting.minimum} to ${setting.maximum}${unit}.` : null;
        defaultText = `Default: ${setting.default}${unit}.`;
      }
    }

    const more = h("div", { class: "more-info", id: `${id}-more`, hidden: true },
      h("p", {}, setting.help),
      setting.note ? h("p", {}, setting.note) : null,
      defaultText ? h("p", {}, defaultText) : null);
    const info = h("button", { type: "button", class: "info", "aria-expanded": "false",
      "aria-controls": `${id}-more`, "aria-label": `About ${setting.label}` }, "?");
    info.addEventListener("click", () => {
      const open = more.hidden;
      more.hidden = !open;
      info.setAttribute("aria-expanded", String(open));
    });
    const hintEl = h("p", { class: "hint", id: `${id}-hint` }, hint);

    const box = setting.kind === "bool"
      ? h("div", { class: "field check" },
        h("div", { class: "field-head" }, h("span", { class: "check-label" }, control, h("label", { for: id }, setting.label)), info),
        more, error)
      : h("div", { class: "field" },
        h("div", { class: "field-head" }, h("label", { for: id, class: "label" }, setting.label), info),
        control, hint ? hintEl : null, more, error);
    fields[setting.key] = { box, read, error };
    return box;
  };

  const basic = config.settings.filter((s) => s.group === "basic");
  const advanced = config.settings.filter((s) => s.group === "advanced");

  const readValues = () => {
    const out = {};
    for (const [key, field] of Object.entries(fields)) out[key] = field.read();
    return out;
  };
  const showErrors = (errors) => {
    for (const [key, field] of Object.entries(fields)) {
      const message = (errors || {})[key] || "";
      field.error.textContent = message;
      field.box.classList.toggle("has-error", !!message);
    }
  };

  const formMessage = h("div", { "aria-live": "polite" });
  const startButton = h("button", { type: "submit", class: "primary" }, "Start run");
  const activeNote = h("p", { class: "muted small" });
  const syncActive = () => {
    startButton.disabled = !!state.active;
    put(activeNote);
    if (state.active) {
      add(activeNote, "A run is already going, and only one can run at a time. ",
        h("a", { href: `#/run/${state.active.id}` }, "Watch the active run"), ".");
    }
  };
  syncActive();

  let validateTimer = null;
  const validateSoon = () => {
    clearTimeout(validateTimer);
    validateTimer = setTimeout(async () => {
      try {
        const result = await api("POST", "/api/validate", { values: readValues() });
        if (token === state.viewToken) showErrors(result.errors);
      } catch (_) { /* shown on submit */ }
    }, 400);
  };

  const form = h("form", {
    class: "form-stack",
    novalidate: true,
    onchange: validateSoon,
    onsubmit: async (event) => {
      event.preventDefault();
      put(formMessage);
      startButton.disabled = true;
      try {
        const { id } = await api("POST", "/api/runs", { values: readValues(), parent });
        location.hash = `#/run/${id}`;
      } catch (err) {
        if (err.body && err.body.errors) {
          showErrors(err.body.errors);
          add(formMessage, banner("bad", h("p", {}, err.message)));
          const first = Object.keys(err.body.errors)[0];
          if (fields[first]) {
            const details = form.querySelector("details.advanced");
            if (details && details.contains(fields[first].box)) details.open = true;
            fields[first].box.querySelector("input, select").focus();
          }
        } else if (err.body && err.body.active) {
          add(formMessage, banner("warn", h("p", {}, err.message, " ",
            h("a", { href: `#/run/${err.body.active}` }, "Go to the active run"), ".")));
        } else {
          add(formMessage, banner("bad", h("p", {}, err.message),
            err.body && err.body.console ? h("pre", { class: "small" }, err.body.console) : null));
        }
        syncActive();
      }
    },
  },
  h("div", { class: "form-grid" }, basic.map(makeField)),
  h("details", { class: "advanced", open: advanced.some((s) => s.key in values && values[s.key] !== s.default) || null },
    h("summary", {}, "Advanced settings"),
    h("div", { class: "groupbox" }, h("div", { class: "form-grid" }, advanced.map(makeField)))),
  formMessage,
  h("div", { class: "actions" }, startButton, activeNote));

  state.refresh = async () => { syncActive(); };

  // Brown, like the game's ride construction window: you are building something.
  setView(win({ colour: "brown", title: source ? "Rerun" : "New run", level: 1 },
    source
      ? banner("good", h("p", {}, "Starting from ",
        h("a", { href: `#/run/${source.id}` }, source.name),
        ". Every setting, including the seed, matches it, so whatever you change is the only difference between the two."))
      : h("p", {}, "Set up a Mine Train request. The defaults make a reasonable first ride. Click ? next to a setting to read what it does."),
    form,
  ));
}

// ---------------------------------------------------------------------------
// One run: live view while running, result view after

// One run, as the game's ride window: the name and status in the title bar,
// what was asked for and what you can do with it under that, then tabs for
// the rest. The tab is kept in the address, so a reload or a shared link
// comes back to it.
const RUN_TABS = [
  ["overview", "Overview"],
  ["graphs", "Graphs"],
  ["check", "Game check"],
  ["install", "Install"],
];

async function showRun(runId, tabParam) {
  const token = state.viewToken;
  const path = `/api/runs/${encodeURIComponent(runId)}`;
  let { run } = await api("GET", path);
  if (token !== state.viewToken) return;
  const config = await loadSettings();

  const caption = h("h1", { class: "win-caption" });
  const meta = h("div", { class: "meta" });
  const actions = h("div", { class: "actions" });
  const headSlot = h("div", { class: "panel-stack" });
  const liveBox = h("div", { class: "panel-stack" });
  const warnings = [h("div", { class: "panel-stack" }), h("div", { class: "panel-stack" })]; // on Overview and Install
  const pictures = h("div", { class: "pictures" });
  const fitness = h("div", { class: "score-chart" });
  const stats = h("div", { class: "panel-stack" });
  const checkBox = h("div", { class: "panel-stack" });
  const installBox = h("div", { class: "panel-stack" });
  let pictureVersion = null;
  let installBuilt = false;
  // The isometric view keeps its buttons across new best rides, so keyboard
  // focus stays where the viewer put it; only the pictures are replaced.
  let iso = null;
  let isoVersion = null;
  const profileSlot = h("div", { class: "profile-slot" });

  // ---- tabs ----
  let current = RUN_TABS.some(([key]) => key === tabParam) ? tabParam : "overview";
  const panelContent = {
    overview: [liveBox, warnings[0], stats],
    graphs: [pictures, fitness],
    check: [checkBox],
    install: [warnings[1], installBox],
  };
  const tabButtons = {};
  const panels = {};
  for (const [key, label] of RUN_TABS) {
    tabButtons[key] = h("button", { type: "button", class: "tab", role: "tab", id: `tab-${key}`,
      "aria-controls": `panel-${key}` }, label);
    panels[key] = h("div", { class: "panel-stack", role: "tabpanel", id: `panel-${key}`,
      "aria-labelledby": `tab-${key}` }, panelContent[key]);
  }
  const selectTab = (key, focus) => {
    current = key;
    for (const [k] of RUN_TABS) {
      const on = k === key;
      tabButtons[k].setAttribute("aria-selected", String(on));
      tabButtons[k].tabIndex = on ? 0 : -1;
      panels[k].hidden = !on;
    }
    if (focus) tabButtons[key].focus();
    history.replaceState(null, "", `#/run/${run.id}${key === "overview" ? "" : `?tab=${key}`}`);
  };
  const tablist = h("div", { class: "tabs", role: "tablist", "aria-label": "Run" },
    RUN_TABS.map(([key]) => tabButtons[key]));
  tablist.addEventListener("click", (event) => {
    const button = event.target.closest("[role=tab]");
    if (button) selectTab(button.id.slice(4), false);
  });
  tablist.addEventListener("keydown", (event) => {
    const keys = RUN_TABS.map(([k]) => k);
    const i = keys.indexOf(current);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: keys.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    selectTab(keys[(next + keys.length) % keys.length], true);
  });

  // ---- title bar, facts, and actions ----
  const renderHeader = () => {
    put(caption, run.name, statusTag(run.status));
    document.title = `${run.name} - generide`;
    renderLibraryFacts();
  };

  const renderLibraryFacts = () => {
    const installed = run.installs.length ? run.installs[run.installs.length - 1].name : null;
    put(meta,
      h("span", {}, `Started ${when(run.created)}`),
      h("span", {}, `Seed ${run.seed}`),
      run.status !== "running" && run.generations_run !== null
        ? h("span", {}, `${run.generations_run} generations`) : null,
      installed ? h("span", {}, "Installed as ", h("b", {}, installed)) : null,
      run.parent ? h("span", {}, "Rerun of ", h("a", { href: `#/run/${run.parent}` }, "its source run")) : null);
  };

  const renameForm = () => {
    const input = h("input", { type: "text", id: "rename", value: run.name, maxlength: "60",
      autocomplete: "off", "aria-describedby": "rename-error" });
    const error = h("p", { class: "error", id: "rename-error", "aria-live": "polite" });
    const form = h("form", { class: "rename", novalidate: true },
      h("label", { for: "rename", class: "label" }, "Name"),
      h("div", { class: "actions" }, input,
        h("button", { type: "submit", class: "primary" }, "Save"),
        h("button", { type: "button", onclick: () => { put(headSlot); renameButton.focus(); } }, "Cancel")),
      error);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const out = await api("POST", `${path}/rename`, { name: input.value });
        run.name = out.name;
        put(headSlot);
        renderHeader();
        renameButton.focus();
      } catch (err) {
        error.textContent = err.message;
        input.focus();
      }
    });
    put(headSlot, form);
    input.focus();
    input.select();
  };
  const renameButton = h("button", { type: "button", onclick: renameForm }, "Rename");

  const renderActions = () => {
    const deleteButton = h("button", {
      type: "button",
      class: "danger",
      disabled: run.status === "running",
      onclick: () => askFirst(headSlot, "Delete run",
        `Delete “${run.name}” from the library? You can't undo this. A design already installed in OpenRCT2 stays installed.`,
        "Delete run", async () => {
          try {
            await api("DELETE", path);
            location.hash = "#/library";
          } catch (err) {
            put(headSlot, errorBanner(err));
          }
        }),
    }, "Delete");
    put(actions, renameButton,
      h("a", { class: "button", href: `#/new?rerun=${run.id}` }, "Rerun with changes"),
      run.parent ? h("a", { class: "button", href: `#/compare?ids=${run.parent},${run.id}` }, "Compare with source") : null,
      deleteButton);
  };

  // ---- Overview ----
  const renderLive = () => {
    put(liveBox);
    if (run.status !== "running") {
      if (run.stopped_early) {
        add(liveBox, banner("warn", h("p", {},
          `Stopped early after ${run.generations_run} of ${run.live.generations_planned} generations. The result is the best ride found by then.`)));
      }
      if (run.status === "interrupted") {
        add(liveBox, banner("bad", h("p", {},
          "This run ended without finishing: its process is gone, for example after a crash or a closed laptop. The best ride it logged is shown, but nothing was exported.")));
      }
      if (run.error) add(liveBox, banner("bad", h("p", {}, `The run ended with an error: ${run.error}`)));
      return;
    }
    const live = run.live;
    const age = live.last_progress ? Date.now() / 1000 - live.last_progress : null;
    const stale = age !== null && age > STALE_AFTER_S;
    const planned = live.generations_planned || 1;
    const done = live.generation === null ? 0 : live.generation;
    const metric = (label, value) => h("div", { class: "metric" },
      h("div", { class: "label" }, label), h("div", { class: "value" }, value));
    const stopButton = h("button", {
      class: "danger",
      disabled: !run.stoppable,
      onclick: async () => {
        stopButton.disabled = true;
        stopButton.textContent = "Stopping…";
        try { await api("POST", `${path}/stop`); } catch (err) { add(liveBox, errorBanner(err)); }
      },
    }, "Stop and keep the best ride");
    add(liveBox, win({ colour: "darkgreen", title: "Run progress" },
      h("div", { class: "live" },
        metric("Generation", `${done} of ${planned}`),
        metric("Elapsed", duration(live.elapsed)),
        metric("Time left", live.estimating ? "estimating…" : `about ${duration(live.remaining)}`),
        h("div", { class: "metric" }, h("div", { class: "label" }, "Status"),
          h("div", { class: "value status" },
            h("span", { class: stale ? "pulse stale" : "pulse", "aria-hidden": "true" }),
            stale ? `no update for ${duration(age)}` : "working"))),
      h("div", { class: "progressbar", role: "progressbar", "aria-valuemin": "0",
        "aria-valuemax": String(planned), "aria-valuenow": String(done) },
      h("span", { style: `width:${Math.min(100, (100 * done) / planned)}%` })),
      live.stagnant_for ? banner("warn", h("p", {},
        `The best score has not improved for ${live.stagnant_for} generations. You can stop now and keep this ride, or let the run keep looking.`)) : null,
      h("div", { class: "actions" }, stopButton,
        run.stoppable ? null : h("span", { class: "muted small" },
          "This run was started from a terminal. Stop it there with Ctrl-C."))));
  };

  const renderWarnings = () => {
    for (const box of warnings) {
      put(box);
      if (run.warnings.length) {
        add(box, banner("warn", h("p", {}, h("strong", {}, "Check this before installing:")),
          h("ul", {}, run.warnings.map((w) => h("li", {}, w)))));
      }
    }
  };

  const renderStats = () => {
    const view = run.stats_view;
    put(stats);
    if (!view.simulated.length) {
      add(stats, h("p", {}, "The first ride appears after the first generation."));
      return;
    }
    const ratingsTable = h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "Rating"),
        h("th", { class: "num" }, "Estimate"),
        h("th", { class: "num" }, "In the game"))),
      h("tbody", {}, view.ratings.map((r) => h("tr", {},
        h("td", {}, r.label),
        h("td", { class: "num" }, r.estimate || "–"),
        h("td", { class: "num" }, r.game || "not checked")))));
    const simulatedTable = h("table", {}, h("tbody", {},
      view.simulated.map((r) => h("tr", {},
        h("th", { scope: "row" }, r.label),
        h("td", {}, r.value)))));
    add(stats,
      h("div", { class: "two-col" },
        h("div", {},
          h("h2", {}, run.status === "running" ? "Ratings of the best ride so far" : "Ratings"),
          h("div", { class: "well table-wrap" }, ratingsTable)),
        h("div", {},
          h("h2", {}, "From generide's simulation ", h("span", { class: "tag estimate" }, "estimates")),
          h("div", { class: "well table-wrap" }, simulatedTable))));
  };

  // ---- Graphs ----
  const renderPictures = () => {
    const version = `${run.improvements}-${run.status}`;
    if (version === pictureVersion) return;
    pictureVersion = version;
    if (!run.improvements) {
      iso = null;
      put(pictures, h("p", {}, "The first ride appears after the first generation."));
      return;
    }
    const label = run.status === "running" ? "Best ride so far" : "Result";
    isoVersion = version;
    const profile = picture(`${path}/profile.svg?v=${version}`, `${label}: side profile. Solid line is height, dashed is speed, drops are numbered.`, "Side profile of the ride");
    put(profileSlot, profile);
    if (iso) {
      iso.caption.textContent = `${label}: isometric view. The train runs a compressed lap.`;
      iso.group.refresh();
      return;
    }
    const group = isoGroup();
    const figure = group.picture((angle) => fetchSvg(`${path}/iso.svg?angle=${angle}&v=${isoVersion}`), "Isometric view of the ride");
    const caption = h("figcaption", {}, `${label}: isometric view. The train runs a compressed lap.`);
    figure.append(caption);
    iso = { group, caption };
    put(pictures, h("div", { class: "iso-cell" }, group.element, figure), profileSlot);
  };

  const renderFitness = () => {
    const version = run.live.generation;
    put(fitness, picture(`${path}/fitness.svg?v=${version}-${run.status}`,
      "Best score by generation.", "Best score by generation"));
  };

  // ---- Game check ----
  const renderCheck = () => {
    put(checkBox);
    if (run.status === "running") {
      add(checkBox, h("p", {}, "You can check the ride in the game once the run finishes."));
      return;
    }
    const available = run.availability;
    const button = h("button", {
      class: "primary",
      disabled: !run.has_ride || !available.check || run.checking,
      onclick: async () => {
        button.disabled = true;
        try {
          await api("POST", `${path}/check`);
          run.checking = true;
          renderCheck();
        } catch (err) {
          add(checkBox, errorBanner(err));
          button.disabled = false;
        }
      },
    }, run.checking ? "Checking in the game…" : "Check in the game");
    const latest = run.checks[run.checks.length - 1];
    add(checkBox,
      h("p", {},
        "Builds the ride in OpenRCT2 running in the background, runs a test lap, and reads back the game's own ratings. Takes a few seconds."),
      h("div", { class: "actions" }, button,
        !available.check ? h("span", { class: "muted small" }, available.check_reason) : null,
        !run.has_ride ? h("span", { class: "muted small" }, "There is no exported ride to check.") : null),
      latest ? banner(latest.status === "rated" ? "good" : "warn",
        h("p", {}, h("strong", {}, latest.status === "rated" ? "Game check: " : "Game check failed: "), latest.message),
        latest.detail && latest.status !== "rated" ? h("p", { class: "small" }, latest.detail) : null,
        h("p", { class: "small" }, `Checked ${when(latest.time)}.`)) : null);
  };

  // ---- Install ----
  const renderInstall = () => {
    if (run.status === "running") {
      put(installBox, h("p", {}, "You can install or download the ride once the run finishes."));
      return;
    }
    if (installBuilt) return;
    installBuilt = true;
    const available = run.availability;
    const templates = config.ui.name_templates || [];
    const nameInput = h("input", { type: "text", id: "install-name", maxlength: "200",
      value: run.installs.length ? run.installs[run.installs.length - 1].name : run.name, autocomplete: "off" });
    const templateSelect = h("select", { id: "install-template" },
      h("option", { value: "" }, "Just the name"),
      templates.map((t) => h("option", { value: t }, t)));
    const preview = h("p", { class: "preview", "aria-live": "polite" });
    const result = h("div", { "aria-live": "polite" });
    const installButton = h("button", { class: "primary", disabled: !run.has_ride || !available.install }, "Install");

    let previewTimer = null;
    const refreshPreview = () => {
      clearTimeout(previewTimer);
      previewTimer = setTimeout(async () => {
        if (!nameInput.value.trim()) { put(preview, "Enter a name."); return; }
        const q = new URLSearchParams({ name: nameInput.value, template: templateSelect.value });
        try {
          const p = await api("GET", `${path}/name?${q}`);
          put(preview, "Will be saved as ", h("b", {}, `${p.name}.td6`),
            p.exists ? " (a design with this name is already installed)" : "");
        } catch (err) {
          put(preview, err.message);
        }
      }, 250);
    };
    nameInput.addEventListener("input", refreshPreview);
    templateSelect.addEventListener("change", refreshPreview);

    const doInstall = async (extra) => {
      put(result);
      installButton.disabled = true;
      try {
        const out = await api("POST", `${path}/install`, Object.assign({
          name: nameInput.value, template: templateSelect.value || null,
        }, extra));
        add(result, banner("good",
          h("p", {}, "Installed as ", h("b", {}, out.install.name), ". It is in the Track Designs list under Mine Train."),
          h("p", {}, out.restart_note)));
        const fresh = await api("GET", path);
        run = fresh.run;
        renderLibraryFacts();
        refreshPreview();
      } catch (err) {
        const body = err.body || {};
        if (body.conflict) {
          add(result, banner("warn", h("p", {}, `A design named “${body.name}” is already in the track folder.`),
            h("div", { class: "actions" },
              h("button", { onclick: () => doInstall(Object.assign({}, extra, { replace: true })) }, "Replace it"),
              h("button", { onclick: () => { put(result); nameInput.focus(); nameInput.select(); } }, "Pick another name"))));
        } else if (body.needs_confirmation) {
          add(result, banner("bad", h("p", {}, h("strong", {}, err.message)),
            h("ul", {}, body.warnings.map((w) => h("li", {}, w))),
            h("div", { class: "actions" },
              h("button", { class: "danger", onclick: () => doInstall(Object.assign({}, extra, { confirm: true })) }, "Install anyway"),
              h("button", { onclick: () => put(result) }, "Cancel"))));
        } else {
          add(result, errorBanner(err));
        }
      } finally {
        installButton.disabled = !run.has_ride || !available.install;
      }
    };
    installButton.addEventListener("click", () => doInstall({}));

    const customTemplate = h("input", { type: "text", placeholder: "{name} {date} {time}", "aria-label": "New naming template" });
    const saveTemplate = h("button", {
      onclick: async () => {
        const t = customTemplate.value.trim();
        if (!t) return;
        try {
          const out = await api("POST", "/api/ui-settings", { name_templates: templates.concat([t]) });
          config.ui = out.ui;
          add(templateSelect, h("option", { value: t }, t));
          templateSelect.value = t;
          templates.push(t);
          customTemplate.value = "";
          refreshPreview();
        } catch (err) {
          put(result, errorBanner(err));
        }
      },
    }, "Save template");

    put(installBox,
      h("div", { class: "install" },
        h("div", { class: "field" }, h("label", { for: "install-name", class: "label" }, "Ride name"), nameInput),
        h("div", { class: "field" }, h("label", { for: "install-template", class: "label" }, "Naming template"), templateSelect),
        h("div", { class: "actions" }, installButton,
          h("a", { class: "button", href: run.has_ride ? `${path}/download` : null,
            "aria-disabled": run.has_ride ? null : "true" }, "Download .td6"))),
      preview,
      !available.install ? h("p", { class: "muted small" }, available.install_reason) : null,
      h("p", { class: "muted small" }, config.restart_note),
      h("details", { class: "more" }, h("summary", { class: "small" }, "Add a naming template"),
        h("div", { class: "more-body" },
          h("p", { class: "small" }, `Use ${config.template_fields.map((f) => `{${f}}`).join(", ")}. Times are written with a dash, like 14-05.`),
          h("div", { class: "actions" }, customTemplate, saveTemplate))),
      result);
    refreshPreview();
  };

  const renderAll = () => {
    renderHeader();
    renderActions();
    renderLive();
    renderWarnings();
    renderPictures();
    renderFitness();
    renderStats();
    renderCheck();
    renderInstall();
  };

  renderAll();
  // Grey frame, bordeaux page: the game's ride window.
  setView(h("section", { class: "win c-grey" },
    caption,
    h("div", { class: "win-body" }, meta, actions, headSlot),
    tablist,
    h("div", { class: "win-body win-page c-bordeaux" }, RUN_TABS.map(([key]) => panels[key]))));
  selectTab(current, false);

  state.refresh = async () => {
    if (run.status !== "running" && !run.checking) return;
    const wasRunning = run.status === "running";
    const fresh = await api("GET", path);
    if (token !== state.viewToken) return;
    run = fresh.run;
    if (wasRunning && run.status !== "running") {
      installBuilt = false;
      renderAll();
      return;
    }
    renderHeader();
    renderLive();
    renderWarnings();
    renderPictures();
    renderFitness();
    renderStats();
    renderCheck();
  };
}

// ---------------------------------------------------------------------------
// Library

// The library is the game's ride list: one row per run, columns you can sort
// by clicking their headers, and actions that work on the ticked rows.
const LIBRARY_COLUMNS = [
  { key: "name", label: "Name", value: (r) => r.name.toLowerCase() },
  { key: "status", label: "Status", value: (r) => r.status },
  { key: "excitement", label: "Excitement", num: true, value: (r) => r.headline && r.headline.excitement },
  { key: "intensity", label: "Intensity", num: true, value: (r) => r.headline && r.headline.intensity },
  { key: "nausea", label: "Nausea", num: true, value: (r) => r.headline && r.headline.nausea },
  { key: "speed", label: "Top speed", num: true, value: (r) => r.headline && r.headline.max_speed_mph },
  { key: "drops", label: "Drops", num: true, value: (r) => r.headline && r.headline.drop_count },
  { key: "game", label: "Game check", value: (r) => (r.check ? r.check.status : "") },
  { key: "created", label: "Started", value: (r) => r.created || "" },
];

function librarySort() {
  try {
    const saved = JSON.parse(localStorage.getItem("generide.librarySort"));
    if (saved && LIBRARY_COLUMNS.some((c) => c.key === saved.key)) return saved;
  } catch (_) { /* fall back to newest first */ }
  return { key: "created", dir: "desc" };
}

async function showLibrary() {
  const token = state.viewToken;
  const { runs } = await api("GET", "/api/runs");
  if (token !== state.viewToken) return;
  if (!runs.length) {
    setView(win({ page: "bordeaux", title: "Run library", level: 1, extra: "empty" },
      h("p", {}, "No runs yet. Runs started here or with evolve_coaster.py show up in this list."),
      h("a", { class: "button primary", href: "#/new" }, "Start a run")));
    return;
  }

  let sort = librarySort();
  const selected = new Set();
  const byId = new Map(runs.map((r) => [r.id, r]));
  const tbody = h("tbody");
  const headRow = h("tr");
  const prompt = h("div");
  const count = h("span", { class: "small", "aria-live": "polite" });
  const openButton = h("a", { class: "button" }, "Open");
  const compareButton = h("a", { class: "button primary" }, "Compare");
  const rerunButton = h("a", { class: "button" }, "Rerun");
  const deleteButton = h("button", { type: "button", class: "danger" }, "Delete");

  const setLink = (link, href) => {
    if (href) { link.href = href; link.removeAttribute("aria-disabled"); }
    else { link.removeAttribute("href"); link.setAttribute("aria-disabled", "true"); }
  };
  const syncToolbar = () => {
    const ids = [...selected];
    const one = ids.length === 1 ? byId.get(ids[0]) : null;
    count.textContent = ids.length
      ? `${ids.length} selected.` : "Tick runs to compare, rerun, or delete them.";
    setLink(openButton, one ? `#/run/${one.id}` : null);
    setLink(rerunButton, one && one.status !== "unreadable" ? `#/new?rerun=${one.id}` : null);
    setLink(compareButton, ids.length >= 2 && ids.length <= 3 ? `#/compare?ids=${ids.join(",")}` : null);
    deleteButton.disabled = !ids.length || ids.some((id) => byId.get(id).status === "running");
  };

  const ratings = (r, key, digits) => (r.headline && r.headline[key] !== null && r.headline[key] !== undefined
    ? num(r.headline[key], digits) : "–");
  const gameCell = (r) => {
    if (r.checking) return "checking…";
    if (!r.check) return "not checked";
    const hl = r.headline;
    return r.check.status === "rated"
      ? h("span", { class: "tag game" }, `${num(hl.game_excitement, 2)} / ${num(hl.game_intensity, 2)} / ${num(hl.game_nausea, 2)}`)
      : `failed`;
  };

  const row = (r) => {
    const box = h("input", { type: "checkbox", "aria-label": `Select ${r.name}`, checked: selected.has(r.id) });
    const tr = h("tr", { "aria-selected": selected.has(r.id) ? "true" : null, class: "run-row" },
      h("td", { class: "pick" }, box),
      h("th", { scope: "row" },
        h("a", { href: `#/run/${r.id}` }, r.name), " ",
        r.installed && r.installed.length ? h("span", { class: "tag game" }, "installed") : null,
        r.warnings && r.warnings.length ? h("span", { class: "tag failed" }, "has problems") : null),
      h("td", {}, statusTag(r.status)),
      h("td", { class: "num" }, ratings(r, "excitement", 2)),
      h("td", { class: "num" }, ratings(r, "intensity", 2)),
      h("td", { class: "num" }, ratings(r, "nausea", 2)),
      h("td", { class: "num" }, r.headline && r.headline.max_speed_mph !== null && r.headline.max_speed_mph !== undefined
        ? `${num(r.headline.max_speed_mph, 0)} mph` : "–"),
      h("td", { class: "num" }, r.headline && r.headline.drop_count !== null && r.headline.drop_count !== undefined
        ? String(r.headline.drop_count) : "–"),
      h("td", {}, r.status === "unreadable" ? r.error || "" : gameCell(r)),
      h("td", { class: "nowrap" }, when(r.created)));
    box.addEventListener("change", () => {
      if (box.checked) selected.add(r.id); else selected.delete(r.id);
      tr.setAttribute("aria-selected", String(box.checked));
      syncToolbar();
    });
    // Clicking anywhere on a row opens the run, except on its own controls.
    tr.addEventListener("click", (event) => {
      if (event.target.closest("a, input, button, label")) return;
      location.hash = `#/run/${r.id}`;
    });
    return tr;
  };

  const render = () => {
    const column = LIBRARY_COLUMNS.find((c) => c.key === sort.key);
    const sign = sort.dir === "asc" ? 1 : -1;
    const sorted = [...runs].sort((a, b) => {
      const x = column.value(a);
      const y = column.value(b);
      const missingX = x === null || x === undefined || x === "";
      const missingY = y === null || y === undefined || y === "";
      if (missingX || missingY) return missingX === missingY ? 0 : missingX ? 1 : -1; // blanks last
      return (x < y ? -1 : x > y ? 1 : 0) * sign;
    });
    put(headRow, h("th", { class: "pick" }, h("span", { class: "visually-hidden" }, "Select")),
      LIBRARY_COLUMNS.map((c) => {
        const active = c.key === sort.key;
        return h("th", { class: c.num ? "num" : null, "aria-sort": active ? (sort.dir === "asc" ? "ascending" : "descending") : null },
          h("button", { type: "button", class: "sort", onclick: () => {
            sort = { key: c.key, dir: active && sort.dir === "desc" ? "asc" : active ? "desc" : c.num || c.key === "created" ? "desc" : "asc" };
            try { localStorage.setItem("generide.librarySort", JSON.stringify(sort)); } catch (_) { /* fine */ }
            render();
            headRow.querySelector(`[aria-sort] button`).focus();
          } }, c.label, h("span", { class: "sort-mark", "aria-hidden": "true" }, active ? (sort.dir === "asc" ? "\u25B2" : "\u25BC") : "")));
      }));
    put(tbody, sorted.map(row));
  };

  deleteButton.addEventListener("click", () => {
    const ids = [...selected];
    const what = ids.length === 1 ? `“${byId.get(ids[0]).name}”` : `these ${ids.length} runs`;
    askFirst(prompt, ids.length === 1 ? "Delete run" : "Delete runs",
      `Delete ${what} from the library? You can't undo this. Designs already installed in OpenRCT2 stay installed.`,
      ids.length === 1 ? "Delete run" : `Delete ${ids.length} runs`, async () => {
        try {
          for (const id of ids) await api("DELETE", `/api/runs/${encodeURIComponent(id)}`);
          await showLibrary();
        } catch (err) {
          put(prompt, errorBanner(err));
        }
      });
  });

  render();
  syncToolbar();
  // Grey frame, bordeaux page: the game's ride list.
  setView(win({ page: "bordeaux", title: "Run library", level: 1 },
    h("div", { class: "toolbar-row" },
      h("div", { class: "actions" }, openButton, compareButton, rerunButton, deleteButton, count),
      h("a", { class: "button", href: "#/new" }, "New run")),
    prompt,
    h("div", { class: "well table-wrap" }, h("table", { class: "library" }, h("thead", {}, headRow), tbody)),
    h("p", { class: "small" }, "Ratings are generide's estimates. Click a column header to sort, and a row to open it. Deleting a run never touches rides installed in OpenRCT2.")));
}

// ---------------------------------------------------------------------------
// Compare

async function showCompare(ids) {
  const token = state.viewToken;
  const data = await api("GET", `/api/compare?ids=${ids.map(encodeURIComponent).join(",")}`);
  if (token !== state.viewToken) return;
  const cols = data.runs.length;
  // One pair of turn buttons drives every picture, so the rides are always
  // compared from the same side.
  const compareIso = isoGroup();

  const columns = h("div", { class: "compare-grid", style: `--cols:${cols}` },
    data.runs.map((r, i) => win({ title: [h("a", { href: `#/run/${r.id}` }, r.name), i === 0 ? h("span", { class: "tag" }, "baseline") : null], level: 3 },
      h("div", { class: "meta" }, statusTag(r.status), h("span", {}, `Seed ${r.seed}`)),
      r.warnings.length ? banner("bad", h("ul", {}, r.warnings.map((w) => h("li", {}, w)))) : null,
      compareIso.picture((angle) => fetchSvg(`/api/runs/${r.id}/iso.svg?angle=${angle}`), `Isometric view of ${r.name}`),
      h("figure", { class: "well well-graph graph" },
        h("img", { src: `/api/runs/${r.id}/profile.svg`, alt: `Side profile of ${r.name}`, loading: "lazy" })))));

  const header = h("tr", {}, h("th", {}, ""), data.runs.map((r) => h("th", {}, r.name)));
  const changedCount = data.inputs.filter((row) => row.changed).length;
  const inputsTable = h("div", { class: "well table-wrap" }, h("table", {},
    h("thead", {}, header.cloneNode(true)),
    h("tbody", {}, data.inputs.map((row) => h("tr", { class: row.changed ? "changed" : null },
      h("th", { scope: "row" }, row.label, row.changed ? [" ", h("span", { class: "tag game" }, "changed")] : null),
      row.display.map((v) => h("td", {}, v)))))));

  const statsTable = h("div", { class: "well table-wrap" }, h("table", {},
    h("thead", {}, header.cloneNode(true)),
    h("tbody", {}, data.stats.map((row) => h("tr", { class: row.changed ? "changed" : null },
      h("th", { scope: "row" }, row.label),
      row.display.map((v, i) => {
        const delta = row.delta_display[i];
        return h("td", { class: "num" }, v || "–", delta && row.changed ? h("span", { class: "delta" }, ` (${delta})`) : null);
      }))))));

  setView(h("div", { class: "windows" },
    win({ page: "bordeaux", title: "Compare runs", level: 1, wide: true },
      h("p", {},
        changedCount ? `${changedCount} input${changedCount === 1 ? "" : "s"} differ, highlighted below. Changes in the stats are measured against the first run.`
          : "These runs have the same inputs."),
      compareIso.element,
      columns),
    win({ page: "bordeaux", title: "Inputs", wide: true }, inputsTable),
    win({ page: "bordeaux", title: "Stats", wide: true },
      h("p", { class: "small" }, "Estimates come from generide's own model. Game rows fill in once a run has been checked in the real game."),
      statsTable)));
}

// ---------------------------------------------------------------------------

window.addEventListener("hashchange", route);
route().then(poll);
setInterval(poll, POLL_MS);
