---
title: Isometric Ride View - Plan
type: feat
date: 2026-10-04
topic: isometric-ride-view
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Isometric Ride View - Plan

## Goal Capsule

- **Objective:** Someone watching a ride evolve can tell by looking what the ride is, where the hills, drops, and turns are and how a train would run it, without loading the game.
- **Means:** An isometric picture of the best ride so far, with quarter-turn rotation and an animated train, replacing the top-down plan.
- **Product authority:** This Product Contract is authoritative on behavior and scope. Free orbiting, speed colouring, and the game's own artwork are not active scope.
- **Execution profile:** Code change in one repo. The engine stays standard library only and CI runs Python 3.9.
- **Open blockers:** None.

---

## Product Contract

### Summary

While a run generates, the best ride so far appears as an isometric picture of a coaster: rails, ties, and support columns, drawn back to front like the game's own view. The viewer can turn it a quarter turn at a time. A train runs a compressed lap around the track, slow on the lift and fast on the drops. The picture replaces the top-down plan in the web UI and the browser demo.

### Problem Frame

Today the plan view is a grid of squares shaded by height. It shows where the track goes but not what the ride is. A viewer cannot tell a hill from a turn or a drop at a glance, and height lives on a separate side-profile chart. The only way to see what a ride looks like is to load it into the game, which is a slow loop for a question as simple as "did the hill survive?".

`STRATEGY.md` names rendering and fit as a track of its own: a high-scoring ride is only worth anything if you can tell it fits your park and is worth placing. The same picture is also the first thing a visitor to the browser demo sees of a run, so it carries the impression of the project as well as the check on a ride.

### Key Decisions

- **The picture is a static isometric image with rotate controls, not a freely draggable 3D view.** (session-settled: user-directed; chosen over a drag-to-orbit canvas: a static picture with rotate buttons is enough.) Governs R1, R6.
- **It replaces the top-down plan rather than sitting beside it.** (session-settled: user-directed; chosen over keeping both: one picture of the ride is enough.) Governs R13.
- **A train animates on the track.** (session-settled: user-directed; chosen over a static picture alone: the train shows how the ride runs, not only its shape.) Governs R8, R9, R10, R11, R12.
- **The lap is compressed to about 20 seconds and keeps the simulation's speed ratios.** (session-settled: user-directed; chosen over real time, about 66 seconds for the Manic Miner reference ride, and over constant speed, which hides the speed information the physics already has.) Governs R9.
- **The size label, ground grid, and station marker carry over from the top-down plan.** (session-settled: user-approved; proposed because checking that a ride fits the park is part of why a ride is drawn at all.) Governs R4.
- **Replacement covers every place the app and demo show the plan today. The old plan drawing and the command-line plan file stay.** (session-settled: user-approved; proposed over removing them: scripts and devlog images still use them.) Governs R13.
- **The chosen angle stays put when a new best ride arrives, and the train restarts.** (session-settled: user-approved; proposed over resetting the angle on every new best, which would undo the viewer's choice every few seconds.) Governs R7, R11.
- **A ride that stalls shows the train stopping where it stalls, with a marker.** (session-settled: user-approved; proposed to match how the side profile already marks a stall.) Governs R10.
- **With reduced motion, the train sits still, a line says why, and a Play lap button runs one lap on demand.** (session-settled: user-directed; chosen over a still train with an explanatory line only.) Governs R12.
- **The picture shows generide's model of the ride, not the game's exact geometry.** Lap proportions inherit the ride length error tracked in joshgarlitos/generide#60 and shift when that is fixed. (session-settled: user-approved; proposed over waiting on #60 before starting.)
- **The look is not fixed in advance.** The first piece of work is a rough render of the Manic Miner reference ride that the user judges by eye. (session-settled: user-approved; proposed because style is cheaper to judge than to specify.)

### Requirements

**The picture**

- R1. The best ride so far is drawn as an isometric picture of a coaster: two rails, ties along the track, and support columns from the track down to the ground.
- R2. Pieces nearer the viewer are drawn in front, so where a track passes over itself, the upper piece is on top.
- R3. Turns are smooth curves, and each slope rises in proportion to its piece definition, so a steep slope visibly rises four times as much as a gentle one over the same distance.
- R4. The picture shows a ground grid, the ride's size in tiles, and a marker at the station.
- R5. The picture paints its own dark background and uses the design system's chart colours, like the other pictures.

**Turning the view**

- R6. Controls turn the view in quarter turns, giving four angles around the ride, and turning redraws the picture from the new angle.
- R7. The chosen angle stays when a new best ride arrives and when the run finishes.

**The train**

- R8. A train runs laps around the track, each starting at the station and repeating without end.
- R9. A lap takes about 20 seconds whatever the ride's length, and the train's speed along it follows the simulation's speed on each piece.
- R10. When the simulated train stalls, it runs to the stall point and stops there, and a marker shows where.
- R11. Each new best ride, and each turn of the view, restarts the lap from the station.
- R12. When the viewer's device asks for reduced motion, the train sits still at the station, a line beside the picture says that is why, and a Play lap button runs one lap on demand.

**Where it appears**

- R13. The picture replaces the top-down plan on the run screen, live and finished, on the run compare screen, and on the browser demo page.
- R14. The browser demo draws the same picture from the same engine, with no server.

### Key Flows

- F1. Watching a run generate
  - **Trigger:** The viewer starts a run, or opens one that is running.
  - **Steps:** Before the first ride, the screen keeps its current "first ride appears after the first generation" message. The first best ride appears with the train lapping. Each improvement replaces the picture, keeps the angle, and restarts the lap at the station. When the run ends, the final ride stays on screen.
  - **Outcome:** The viewer sees the ride take shape and how its train runs it.
  - **Covered by:** R1, R7, R8, R9, R11

- F2. Turning the view
  - **Trigger:** The viewer presses a turn control.
  - **Steps:** The picture is redrawn from the next quarter turn and the train starts a new lap at the station.
  - **Outcome:** A piece hidden behind a hill from one angle can be seen from another.
  - **Covered by:** R2, R6, R11

- F3. Viewing with reduced motion
  - **Trigger:** A ride appears on a device set to reduce motion.
  - **Steps:** The train sits at the station, a line explains why, and Play lap runs one lap when pressed and returns the train to the station.
  - **Outcome:** The viewer is not moved against their settings and can still watch a lap.
  - **Covered by:** R12

### Acceptance Examples

- AE1. **Covers R3.** Given a one-tile gentle slope piece and a one-tile steep slope piece, when drawn, the steep one rises four times as much as the gentle one.
- AE2. **Covers R2.** Given a track that passes over itself, when drawn from each of the four angles, the upper piece is in front of the lower one at the crossing.
- AE3. **Covers R7, R11.** Given a run in progress with the view turned a quarter turn, when a better ride arrives, it is drawn from the same quarter turn and the train starts at the station.
- AE4. **Covers R10.** Given a ride whose train runs out of speed on a hill, when its picture shows, the train stops at that hill with a marker and does not complete the lap.
- AE5. **Covers R12.** Given reduced motion is on, when the picture appears, the train is still at the station and a line explains why. When Play lap is pressed, the train runs one lap and returns to the station.
- AE6. **Covers R9.** Given the Manic Miner reference ride, whose simulated lap is about 66 seconds with 39 percent of it on the lift and station, when it plays, the lap takes about 20 seconds and the train spends the same 39 percent of the lap there.

### Success Criteria

- Looking at the Manic Miner reference ride, the user can say which parts are hills, drops, and turns without the side profile, and judges the picture good enough to ship after the first rough render.
- Drawing the picture adds no noticeable time to a run, including in the browser demo, where an engine run takes tens of seconds.

### Scope Boundaries

**Deferred for later**

- Dragging to spin the view freely.
- Colouring the track by speed, or marking the lift hill with its own colour.
- Using the game's own artwork.

**Not changing**

- The top-down plan drawing and the command-line plan file stay as they are.
- The side profile and the score chart are unchanged.
- Physics numbers and ride length calibration are separate work (joshgarlitos/generide#60).

### Dependencies / Assumptions

- The train's per-piece speed and time come from the same physics walk that feeds the ride stats, so the lap's proportions shift when #60 is fixed. The picture must not hard-code lap numbers.
- Slope steepness comes from the piece definitions: the gentle slope rises 2 height units over one tile and the steep slope 8. If a height unit is a quarter of a tile, these come out near 27 and 63 degrees, close to the pieces' 25 and 60 degree names. This is unverified and the first rough render confirms it against the Manic Miner reference ride.
- The engine stays standard library only, runs in the browser through Pyodide, and passes CI on Python 3.9, as the browser demo plan requires.
- The viewer's reduced-motion setting is readable by the page.

### Outstanding Questions

**Deferred to Planning**

- What form the turn controls take (two turn buttons or four angle buttons), and which angle is the default. The default is chosen by eye in the first rough render.
- How the demo gets the other three angles, drawing on demand or all four up front.
- How the train animation is delivered, given the app loads its pictures as images, and how reduced motion and Play lap work with that.
- How the path is drawn through pieces whose end position moves backward, such as the half-turn helix pieces.

### Sources / Research

- `rct2/render.py`: the top-down plan (`render_track`, `plan_track`), the side profile, and the shared palette and dark background.
- `rct2/geometry.py` and `rct2/segments.py`: piece poses, headings, and elevation per piece, which give the track's path and slopes.
- `rct2/physics.py`: `trace()` returns per-piece time, speed, lift flags, and the stall point. For the Manic Miner fixture it gives 89 pieces, a 65.7 second lap, 25.8 seconds on lift and station, speeds from 1.6 to 16.7 m/s, and a footprint of 15 by 18 tiles and 22 height units.
- `rct2/webui.py`, `rct2/webui_static/app.js`, `rct2/demo.py`, and `demo/app.js`: where the plan is served and shown today, including the compare screen. The picture is swapped only when the best ride changes.
- `STRATEGY.md`, "Rendering and fit": why seeing and judging fit matters.
- `docs/plans/2026-10-03-1617-feat-try-in-browser-plan.md`: the browser demo this picture must also work in.
