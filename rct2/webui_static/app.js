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
    else if (page === "run" && parts[1]) await showRun(parts[1]);
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

async function showRun(runId) {
  const token = state.viewToken;
  const path = `/api/runs/${encodeURIComponent(runId)}`;
  let { run } = await api("GET", path);
  if (token !== state.viewToken) return;
  const config = await loadSettings();

  // Each slot holds one window (or none) and re-renders on its own; slots
  // take no space, so the windows tile in the page grid.
  const slot = () => h("div", { class: "slot" });
  const header = slot();
  const liveBox = slot();
  const warnings = slot();
  const pictures = h("div", { class: "pictures" });
  const picturesWin = win({ title: "Plan and side profile", wide: true }, pictures);
  const fitness = slot();
  const stats = slot();
  const checkBox = slot();
  const installBox = slot();
  const footer = slot();
  let pictureVersion = null;
  let installBuilt = false;

  const renderHeader = () => {
    const meta = h("div", { class: "meta" },
      h("span", {}, `Started ${when(run.created)}`),
      h("span", {}, `Seed ${run.seed}`),
      run.status !== "running" && run.generations_run !== null
        ? h("span", {}, `${run.generations_run} generations`) : null);
    const parentLine = run.parent ? h("p", { class: "small" }, "Rerun of ",
      h("a", { href: `#/run/${run.parent}` }, run.parent), ". ",
      h("a", { href: `#/compare?ids=${run.parent},${run.id}` }, "Compare with the source run")) : null;
    put(header, win({ title: [run.name, statusTag(run.status)], level: 1, wide: true }, meta, parentLine));
  };

  const renderLive = () => {
    put(liveBox);
    if (run.status !== "running") {
      const notes = [];
      if (run.stopped_early) {
        notes.push(banner("warn", h("p", {},
          `Stopped early after ${run.generations_run} of ${run.live.generations_planned} generations. The result is the best ride found by then.`)));
      }
      if (run.status === "interrupted") {
        notes.push(banner("bad", h("p", {},
          "This run ended without finishing: its process is gone, for example after a crash or a closed laptop. The best ride it logged is shown, but nothing was exported.")));
      }
      if (run.error) notes.push(banner("bad", h("p", {}, `The run ended with an error: ${run.error}`)));
      if (notes.length) add(liveBox, win({ title: "How this run ended", wide: true }, notes));
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
    add(liveBox, win({ colour: "darkgreen", title: "Run progress", wide: true },
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
    put(warnings);
    if (run.warnings.length) {
      add(warnings, win({ colour: "bordeaux", title: "Check this before installing", wide: true },
        h("ul", {}, run.warnings.map((w) => h("li", {}, w)))));
    }
  };

  const renderPictures = () => {
    const version = `${run.improvements}-${run.status}`;
    if (version === pictureVersion) return;
    pictureVersion = version;
    if (!run.improvements) {
      put(pictures, h("p", { class: "muted" }, "The first ride appears after the first generation."));
      return;
    }
    const label = run.status === "running" ? "Best ride so far" : "Result";
    put(pictures, 
      picture(`${path}/plan.svg?v=${version}`, `${label}: top-down plan, lighter is higher.`, "Top-down plan of the ride"),
      picture(`${path}/profile.svg?v=${version}`, `${label}: side profile. Solid line is height, dashed is speed, drops are numbered.`, "Side profile of the ride"));
  };

  const renderFitness = () => {
    const version = run.live.generation;
    put(fitness, win({ title: "Best score by generation" },
      h("figure", { class: "well well-graph graph" },
        h("img", { class: "chart", src: `${path}/fitness.svg?v=${version}-${run.status}`,
          alt: "Best score by generation" }))));
  };

  const renderStats = () => {
    const view = run.stats_view;
    put(stats);
    if (!view.simulated.length) return;
    const ratingsTable = h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "Rating"),
        h("th", { class: "num" }, "Our estimate ", h("span", { class: "tag estimate" }, "estimate")),
        h("th", { class: "num" }, "In the game ", h("span", { class: "tag game" }, "game-checked")))),
      h("tbody", {}, view.ratings.map((r) => h("tr", {},
        h("td", {}, r.label),
        h("td", { class: "num" }, r.estimate || "–"),
        h("td", { class: "num" }, r.game || "not checked")))));
    const simulatedTable = h("table", {}, h("tbody", {},
      view.simulated.map((r) => h("tr", {},
        h("th", { scope: "row" }, r.label),
        h("td", {}, r.value)))));
    // Grey frame, bordeaux page: the game's ride window.
    add(stats, win({ page: "bordeaux", title: run.status === "running" ? "Best ride so far" : "Ride stats", wide: true },
      h("div", { class: "two-col" },
        h("div", {},
          h("h3", {}, "Ratings"),
          h("div", { class: "well table-wrap" }, ratingsTable),
          h("p", { class: "small" }, config.estimate_note)),
        h("div", {},
          h("h3", {}, "From generide's simulation ", h("span", { class: "tag estimate" }, "estimates")),
          h("div", { class: "well table-wrap" }, simulatedTable)))));
  };

  const renderCheck = () => {
    put(checkBox);
    if (run.status === "running") return;
    const available = run.availability;
    const button = h("button", {
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
    }, run.checking ? "Checking in the game…" : "Check in the real game");
    const latest = run.checks[run.checks.length - 1];
    // Yellow marks numbers that came from the game itself.
    add(checkBox, win({ colour: "yellow", title: "Check in the real game" },
      h("p", { class: "small" },
        "Builds the ride in OpenRCT2 running in the background, runs a test lap, and reads back the game's own ratings. Takes a few seconds."),
      h("div", { class: "actions" }, button,
        !available.check ? h("span", { class: "muted small" }, available.check_reason) : null,
        !run.has_ride ? h("span", { class: "muted small" }, "There is no exported ride to check.") : null),
      latest ? banner(latest.status === "rated" ? "good" : "warn",
        h("p", {}, h("strong", {}, latest.status === "rated" ? "Game check: " : "Game check failed: "), latest.message),
        latest.detail && latest.status !== "rated" ? h("p", { class: "small" }, latest.detail) : null,
        h("p", { class: "small" }, `Checked ${when(latest.time)}.`)) : null));
  };

  const renderInstall = () => {
    if (run.status === "running") { put(installBox); return; }
    if (installBuilt) return;
    installBuilt = true;
    const available = run.availability;
    const templates = config.ui.name_templates || [];
    const nameInput = h("input", { type: "text", id: "install-name", maxlength: "200",
      value: run.installs.length ? run.installs[run.installs.length - 1].name : "", autocomplete: "off" });
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
        renderHeader();
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

    // Brown, like the game's track design placement window.
    put(installBox, win({ colour: "brown", title: "Install or download" },
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
      result));
    refreshPreview();
  };

  const renderFooter = () => {
    const prompt = h("div");
    put(footer, win({ title: "More" }, h("div", { class: "actions" },
      h("a", { class: "button", href: `#/new?rerun=${run.id}` }, "Rerun with changes"),
      run.parent ? h("a", { class: "button", href: `#/compare?ids=${run.parent},${run.id}` }, "Compare with the source run") : null,
      h("button", {
        class: "danger",
        disabled: run.status === "running",
        onclick: () => askFirst(prompt, "Delete run",
          `Delete “${run.name}” from the library? You can't undo this. A design already installed in OpenRCT2 stays installed.`,
          "Delete run", async () => {
            try {
              await api("DELETE", path);
              location.hash = "#/library";
            } catch (err) {
              put(prompt, errorBanner(err));
            }
          }),
      }, "Delete run")), prompt));
  };

  const renderAll = () => {
    renderHeader();
    renderLive();
    renderWarnings();
    renderPictures();
    renderFitness();
    renderStats();
    renderCheck();
    renderInstall();
    renderFooter();
  };

  renderAll();
  setView(h("div", { class: "windows" },
    header, liveBox, warnings, picturesWin, stats, checkBox, fitness, installBox, footer));

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

  const selected = new Set();
  const compareButton = h("a", { class: "button", "aria-disabled": "true" }, "Compare");
  const hint = h("span", { class: "small muted" });
  const syncCompare = () => {
    const ok = selected.size >= 2 && selected.size <= 3;
    hint.textContent = ok ? `${selected.size} runs selected.` : "Tick two or three runs to compare them.";
    if (ok) {
      compareButton.href = `#/compare?ids=${[...selected].join(",")}`;
      compareButton.removeAttribute("aria-disabled");
      compareButton.classList.add("primary");
    } else {
      compareButton.removeAttribute("href");
      compareButton.setAttribute("aria-disabled", "true");
      compareButton.classList.remove("primary");
    }
  };

  const windowText = (w) => (w ? `${w[0]}–${w[1]}` : "any");
  const cards = runs.map((r) => {
    const box = h("input", { type: "checkbox", "aria-label": `Select ${r.name} to compare`,
      disabled: r.status === "unreadable" });
    const card = h("article", { class: "run-card" });
    const prompt = h("div", { class: "slot-inline" });
    box.addEventListener("change", () => {
      if (box.checked) selected.add(r.id); else selected.delete(r.id);
      card.classList.toggle("selected", box.checked);
      syncCompare();
    });
    if (r.status === "unreadable") {
      add(card, box, h("div", { class: "title" }, h("strong", {}, r.id), statusTag(r.status)),
        h("div", { class: "facts" }, r.error || ""));
    } else {
      const hl = r.headline;
      const inputs = r.inputs;
      const checkText = r.checking ? "checking…" : r.check
        ? (r.check.status === "rated" ? `game ${num(hl.game_excitement, 2)} / ${num(hl.game_intensity, 2)} / ${num(hl.game_nausea, 2)}` : `check: ${r.check.status}`)
        : "not checked";
      add(card, box,
        h("div", { class: "title" }, h("a", { href: `#/run/${r.id}` }, r.name), statusTag(r.status),
          r.installed.length ? h("span", { class: "tag game" }, "installed") : null,
          r.warnings.length ? h("span", { class: "tag failed" }, "has problems") : null),
        h("div", { class: "facts" },
          h("span", {}, when(r.created)),
          h("span", {}, "Seed ", h("b", {}, r.seed)),
          h("span", {}, "Footprint ", h("b", {}, `${inputs.max_width ?? "?"} x ${inputs.max_depth ?? "?"}`)),
          h("span", {}, "E/I/N windows ", h("b", {}, `${windowText(inputs.target_excitement)}, ${windowText(inputs.target_intensity)}, ${windowText(inputs.target_nausea)}`)),
          h("span", {}, `${inputs.generations ?? "?"} gen x ${inputs.population ?? "?"}, ${inputs.fitness ?? "?"} scoring`)),
        h("div", { class: "facts" },
          h("span", {}, "Estimated E/I/N ", h("b", {}, hl.excitement === null ? "–" : `${num(hl.excitement, 2)} / ${num(hl.intensity, 2)} / ${num(hl.nausea, 2)}`)),
          h("span", {}, "Top speed ", h("b", {}, hl.max_speed_mph === null ? "–" : `${num(hl.max_speed_mph, 0)} mph`)),
          h("span", {}, "Drops ", h("b", {}, hl.drop_count ?? "–")),
          h("span", {}, checkText),
          r.installed.length ? h("span", {}, `installed as ${r.installed[r.installed.length - 1]}`) : null),
        h("div", { class: "actions" },
          h("a", { class: "button", href: `#/run/${r.id}` }, "Open"),
          h("a", { class: "button", href: `#/new?rerun=${r.id}` }, "Rerun"),
          h("button", {
            class: "danger",
            disabled: r.status === "running",
            onclick: () => askFirst(prompt, "Delete run",
              `Delete “${r.name}” from the library? You can't undo this. A design already installed in OpenRCT2 stays installed.`,
              "Delete run", async () => {
                try {
                  await api("DELETE", `/api/runs/${encodeURIComponent(r.id)}`);
                  await showLibrary();
                } catch (err) {
                  put(prompt, errorBanner(err));
                }
              }),
          }, "Delete")),
        prompt);
    }
    return card;
  });

  syncCompare();
  // Grey frame, bordeaux page: the game's ride list.
  setView(win({ page: "bordeaux", title: "Run library", level: 1 },
    h("div", { class: "header-row" },
      h("p", {}, "Every run, newest first, whether it was started here or from the terminal. Clearing this library never touches rides installed in OpenRCT2."),
      h("a", { class: "button", href: "#/new" }, "New run")),
    h("div", { class: "well runs" }, cards),
    h("div", { class: "compare-bar" }, hint, compareButton)));
}

// ---------------------------------------------------------------------------
// Compare

async function showCompare(ids) {
  const token = state.viewToken;
  const data = await api("GET", `/api/compare?ids=${ids.map(encodeURIComponent).join(",")}`);
  if (token !== state.viewToken) return;
  const cols = data.runs.length;

  const columns = h("div", { class: "compare-grid", style: `--cols:${cols}` },
    data.runs.map((r, i) => win({ title: [h("a", { href: `#/run/${r.id}` }, r.name), i === 0 ? h("span", { class: "tag" }, "baseline") : null], level: 3 },
      h("div", { class: "meta" }, statusTag(r.status), h("span", {}, `Seed ${r.seed}`)),
      r.warnings.length ? banner("bad", h("ul", {}, r.warnings.map((w) => h("li", {}, w)))) : null,
      h("figure", { class: "well well-graph graph" },
        h("img", { src: `/api/runs/${r.id}/plan.svg`, alt: `Plan of ${r.name}`, loading: "lazy" })),
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
