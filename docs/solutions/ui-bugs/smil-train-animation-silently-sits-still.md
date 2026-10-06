---
title: An SVG train animation that sits still with no error, two ways
date: 2026-10-06
category: ui-bugs
module: rct2/render.py
problem_type: ui_bug
component: frontend
symptoms:
  - "The train in the isometric ride view never moved, and nothing in the console said why"
  - "svg.getCurrentTime() advanced and svg.animationsPaused() returned false, yet the picture did not change"
root_cause: wrong_api
resolution_type: code_fix
severity: medium
tags: [svg, smil, animatemotion, inline-svg, intersectionobserver, headless-chromium, testing]
---

# An SVG train animation that sits still with no error, two ways

## Problem

The isometric ride view (pull request #74, still open) animates a train around the track with an SVG `animateMotion` element. The train needs to run at the simulation's speed on each piece, and the page needs to pause it, restart it, and replay a lap. Two separate mistakes each left the train sitting still, and neither raised an error.

## Symptoms

- The picture rendered, the timeline reported time passing, and the train did not move.
- Starting the animation by hand later worked, which made the first failure look intermittent.

## What Didn't Work

- **Restarting the animation right after inserting the picture.** `svg.pauseAnimations(); svg.setCurrentTime(0); svg.unpauseAnimations()` called immediately after `replaceChildren` did nothing. The same three calls made later, once the picture had been laid out, worked.

## Solution

1. **Set `calcMode="linear"` on the `animateMotion` element** in `render_isometric`. The default is `paced`, which ignores `keyPoints` and `keyTimes` and runs the train at one speed along the path, so the per-piece timing from `physics.trace` is thrown away. `tests/test_render.py` asserts the attribute, because nothing else fails when it is missing.
2. **Start the train when the picture becomes visible, not when it is inserted.** `rct2/webui_static/iso-view.js` watches the inserted SVG with an `IntersectionObserver` and runs the pause, set-time, unpause sequence the first time it intersects. This works for a picture drawn on a tab that is not showing yet, a picture restarted while visible, and a picture inserted by a turn while visible. It was checked in all three cases.
3. **Check movement independently of the animation clock.** `getCurrentTime()` advanced while the train was stuck, so a clock is not evidence of motion. Comparing a hash of `locator.screenshot()` of the SVG a second or two apart, or the train group's `getBoundingClientRect()`, both showed it stuck, and both showed it moving once fixed.

## Why This Works

SMIL timing in an SVG inserted by script depends on layout having happened, and a picture inside a `display: none` panel never gets one until the panel shows. The timeline can advance while the animation instance has not started, which is why the clock looked fine and the picture did not. Starting from an observer ties the start to the moment the picture can actually draw. The `paced` default is a separate cause: the attributes the plan relied on are accepted and then ignored.

## Prevention

- When an animation carries timing in `keyTimes` or `keyPoints`, set `calcMode="linear"` and assert it in a test.
- For any script-inserted SVG with SMIL, test movement over time in a visible and in a hidden container, and never accept the animation clock as proof the picture is moving.
- A button that starts something and then disables itself takes keyboard focus away from a keyboard user. In the same work, Play lap uses `aria-disabled` and an early return in place of the `disabled` property, and the demo's browser test presses it with the keyboard and checks it keeps focus.

## Related

- `docs/plans/2026-10-04-1519-feat-isometric-ride-view-plan.md`, KTD1 (inline SVG) and KTD6 (the train's timing).
- Not part of this note: the quarter-turn radius is `forward_delta + 0.5` tiles because pieces run from entry edge midpoint to entry edge midpoint. It is recorded in KTD5 of the plan and pinned by `tests/test_trackpath.py`.
