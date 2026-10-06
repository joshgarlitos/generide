// generide's isometric ride view: the picture, its turn buttons, and the
// train. The local web UI and the in-browser page both load this file before
// their own script, and it exposes one global, IsoView.
//
// The picture is inline SVG, not an <img>, because the page has to pause,
// restart, and replay its animated train, and a picture loaded as an image
// cannot be told to stop. Text goes in via textContent, never as markup, and
// the SVG comes from rct2/render.py, which escapes everything it writes.
"use strict";

(function (root) {
  const ANGLES = 4;
  const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

  function readSvg(text) {
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    const el = doc.documentElement;
    if (!el || el.localName !== "svg" || doc.querySelector("parsererror")) {
      throw new Error("The ride picture could not be read.");
    }
    return document.importNode(el, true);
  }

  // The lap length the picture was drawn with, in milliseconds.
  function lapMs(svg) {
    const motion = svg.querySelector("animateMotion");
    const seconds = motion ? parseFloat(motion.getAttribute("dur")) : 0;
    return (Number.isFinite(seconds) && seconds > 0 ? seconds : 20) * 1000;
  }

  // One group is one set of turn buttons driving every picture added to it:
  // one picture on the run screen, a row of them on the compare screen.
  // `h` is the page's element builder. `angle` is the view to start on, and
  // `onAngle` hears each view the viewer settles on, so the page can keep it
  // when a new best ride arrives.
  function createGroup(h, { angle = 0, onAngle = null } = {}) {
    const reduced = Boolean(root.matchMedia && root.matchMedia(REDUCED_MOTION).matches);
    const pictures = [];
    let current = ((angle % ANGLES) + ANGLES) % ANGLES;
    let turns = 0;
    let lapTimer = null;

    const label = h("span", { class: "iso-label small", "aria-live": "polite" });
    const setLabel = () => { label.textContent = `View ${current + 1} of ${ANGLES}`; };
    setLabel();

    // Turning left moves the viewpoint counter-clockwise, so the ride appears
    // to turn clockwise.
    const left = h("button", { type: "button", onclick: () => turn(1) }, "Turn left");
    const right = h("button", { type: "button", onclick: () => turn(-1) }, "Turn right");
    const play = reduced ? h("button", { type: "button", onclick: playLap }, "Play lap") : null;
    const note = reduced
      ? h("span", { class: "muted small" },
        "Your device is set to reduce motion, so the train waits at the station until you play a lap.")
      : null;
    const element = h("div", { class: "iso-controls actions" }, left, right, label, play, note);

    function stopLap() {
      if (lapTimer !== null) clearTimeout(lapTimer);
      lapTimer = null;
      if (play) play.disabled = false;
    }

    function rest(svg) {
      // Still, at the station. Never starts motion.
      svg.pauseAnimations();
      svg.setCurrentTime(0);
    }

    // A picture that was only just inserted does not start its train until
    // it has been laid out and then restarted this way, so every start goes
    // through here.
    function run(svg) {
      svg.pauseAnimations();
      svg.setCurrentTime(0);
      svg.unpauseAnimations();
    }

    // Start the train once the picture is actually on screen, which also
    // covers a picture drawn on a tab that is not showing yet.
    function runWhenVisible(entry) {
      if (typeof IntersectionObserver !== "function") {
        run(entry.svg);
        return;
      }
      entry.watch = new IntersectionObserver((seen) => {
        if (!seen.some((item) => item.isIntersecting)) return;
        entry.watch.disconnect();
        entry.watch = null;
        run(entry.svg);
      });
      entry.watch.observe(entry.svg);
    }

    function playLap() {
      stopLap();
      play.disabled = true;
      let longest = 0;
      for (const picture of pictures) {
        const svg = picture.svg;
        if (!svg) continue;
        run(svg);
        longest = Math.max(longest, lapMs(svg));
      }
      lapTimer = setTimeout(() => {
        lapTimer = null;
        for (const picture of pictures) {
          // A train that stalled stays at the stall until the next lap.
          if (picture.svg && !picture.svg.querySelector("[data-stall]")) rest(picture.svg);
        }
        play.disabled = false;
      }, longest + 100);
    }

    async function turn(step) {
      const previous = current;
      const token = ++turns;
      current = (current + step + ANGLES) % ANGLES;
      setLabel();
      try {
        await Promise.all(pictures.map((picture) => picture.show(current)));
        if (token === turns && onAngle) onAngle(current);
      } catch (_) {
        // The old pictures are still on screen, so put the label back to match.
        if (token === turns) {
          current = previous;
          setLabel();
        }
      }
    }

    // `load(angle)` resolves to the SVG text for that view.
    function picture(load, alt) {
      const frame = h("div", { class: "iso-frame" });
      const figure = h("figure", { class: "well well-graph graph iso" }, frame);
      let request = 0;
      const entry = {
        svg: null,
        watch: null,
        async show(view) {
          const mine = ++request;
          const text = await load(view);
          // A newer request has started, so this answer is out of date.
          if (mine !== request) return;
          const svg = readSvg(text);
          if (alt) svg.setAttribute("aria-label", alt);
          if (entry.watch) entry.watch.disconnect();
          frame.replaceChildren(svg);
          entry.svg = svg;
          if (reduced) rest(svg);
          else runWhenVisible(entry);
        },
      };
      pictures.push(entry);
      entry.show(current).catch(() => {
        frame.replaceChildren(h("p", { class: "muted small" }, "The ride picture could not be loaded."));
      });
      return figure;
    }

    // A new best ride arrived: redraw every picture on the view the viewer
    // chose, which also restarts the train at the station.
    function refresh() {
      stopLap();
      for (const entry of pictures) entry.show(current).catch(() => {});
    }

    return { element, picture, refresh, angle: () => current };
  }

  root.IsoView = { createGroup, ANGLES };
})(window);
