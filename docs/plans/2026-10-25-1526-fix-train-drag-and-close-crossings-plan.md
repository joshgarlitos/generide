---
title: Train Drag in the Simulator - Plan
type: fix
date: 2026-10-25
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Train Drag in the Simulator - Plan

## Goal Capsule

- **Objective:** A ride that generide reports as complete also completes in the real game.
- **Means:** Model the game's own speed-based drag in the simulator (KTD1).
- **Authority:** The game's source and the game's own placement check outrank every constant in this repo. When a fit and the game disagree, the game wins.
- **Stop conditions:** Stop and ask if the game's drag cannot be reproduced on a track that builds within the tolerance in R3, or if the rating fits drift past the bound in R8. A refit of the rating weights is a separate plan.
- **Execution profile:** Test-first on U2, U4 and U5. Characterization first on U1.
- **Tail ownership:** The implementer commits per unit on branch `fix-train-drag-and-close-crossings`. Re-evolving rides (U7) is listed but not run.

---

## Product Contract

### Summary

The simulator (`rct2/physics.py`) will slow a train down the way the game does, using the game's linear and squared drag and a configurable train mass. The quick stall check, the tests pinned to it, and the rating fits are brought back into agreement with the new model. A time-boxed spike looks for a way to run saved designs in the oracle.

### Problem Frame

An evolved ride (seed 123, 120 pieces) was reported by `physics.simulate` as complete, with a 40 mph top speed and a 19 mph average. In the real game the train stalled. The cause is the simulator's single loss: a constant friction of about 0.07 m/s² at every speed. The game applies, every tick, a loss of `v/4096` plus `((v>>8)^2>>4)/totalMass` (`Vehicle.TrackMotion.cpp`, `UpdateTrackMotion`; `Vehicle.cpp`, `GetAccelerationDecrease2`; OpenRCT2 v0.5.3). On the seed circuit the game's logged deceleration of 357 units per tick at 783k units matched that formula exactly for a 7-car train of 3500 mass. At 18 m/s the game loses 0.41 m/s² and the simulator 0.07 m/s².

The search made this worse. Flat coasting was almost free in the simulator, and length earns rating points, so the search added about 100 coasting pieces after the one real drop. A replay with the game's drag stalls that ride between piece 66 (1 car) and piece 102 (7 cars).

The oracle could not confirm any of this. It builds a ride piece by piece, and the game refuses a piece that crosses within 3 height units of the ride's own track (piece 53 against piece 21, "in the way"). A saved design loaded the normal way skips that check (`rct2/oracle.py`, KNOWN LIMITATION; devlog 2026-08-29), and the seed 123 ride did build in the player's park. So the refusal is a limit of the oracle's build method, not a validator defect, and the validator must not reject such rides. Three saved evolved rides hit it (seeds 123, 1593382122, 1477292795), which leaves the oracle unable to measure most long rides.

### Key Decisions

- **Use the game's drag formula, not a refit friction constant.** (session-settled: user-directed — chosen over refitting `FRICTION_COEFF` to match game traces: the project rule is to look up what the game will state, and a fit cannot express speed-squared loss.) Governs R1, R2.
- **Fix the defect on a branch with tests first.** (session-settled: user-directed — chosen over diagnosis only and over a design rethink.) Governs R1 to R9.

### Requirements

**Speed loss**

- R1. The simulator applies, on every unpowered piece, a loss equal to the game's linear term plus its squared term divided by train mass.
- R2. Train mass is an input with one default, set by U3 from a measurement. The simulator, the exported ride and the oracle use the same train length.
- R3. On every track that builds in the game, the simulator's mean speed on each unpowered piece follows the game's. Recorded tolerances: under 2% mean error on the seed circuit, under 3% on the flat loop, under 8% on the 80-piece ride, with no piece off by more than 5%, 7% and 20% (the long train smooths hills that the simulator's single point does not).
- R4. The quick stall check (`energy_stall_index`) names the same stalling piece as `physics.simulate` for every track and train length.

**Oracle coverage**

- R5. The oracle can run a saved design that its piece-by-piece build refuses, or the limit is documented with the API evidence that rules a route out.

**Ratings and evidence**

- R7. The game's speed trace can be captured from the oracle by a supported tool, not a scratch script.
- R8. After the change, `physics.rate` against `data/calibration.csv` moves by no more than 0.3 points of mean absolute error per rating. A larger move is reported, not patched.
- R9. The game's lift speed is measured on the seed circuit and compared to `LIFT_SPEED_MS`. A difference is recorded, not fixed.

### Success Criteria

- The seed 123 ride is reported as stalling by `physics.simulate` at a piece within the range the game's replay gives for the chosen train length.
- A newly evolved ride that the simulator calls complete either builds and completes in the game, or the game's refusal names a rule the validator did not yet know.

### Scope Boundaries

- Not refitting `RATING_WEIGHTS` or changing `ratings.py` formulas. Drift is measured (R8) and reported.
- Not wiring the oracle into `evolve()`. That stays the open piece in `CLAUDE.md`.
- Not changing how the oracle places chain lifts.
- Not adding a clearance rule to the validator. The game accepts saved designs with tight self-crossings.

#### Deferred to Follow-Up Work

- A rating refit if R8 fails.
- Re-running benchmarks and re-evolving rides (steps in U7, run by the owner).
- Fixing the lift-speed difference if R9 finds one.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Drag in sim units.** Per-piece loss uses `a = 0.009766·v + 2.5·v²/M` in m/s², with `v` in m/s and `M` the total train mass. The constants come from the game's integer formula at 40 ticks per second and 65536 velocity units per m/s; U2 re-derives them from the source and checks them against U1's trace instead of trusting this plan. (session-settled: user-directed — chosen over a refit constant: see Key Decisions.) Governs R1.
- KTD2. **Drag distance is measured, not derived.** `TILE_M` stays at 4.36 for the ride-length statistic. The game moves a train along a flat tile in about 8 ticks, which is 2.4 to 2.75 m in the simulator's speed units. Drag therefore uses `DRAG_LENGTH_SCALE` = 0.6 of the piece length. It was fitted to the recorded traces (0.65 best for the seed circuit, 0.5 for the 80-piece ride). Why the game covers more track per tick than its source formula gives is open.
- KTD3. **Train mass comes from car count.** Mass is 500 per car, read from the game's `car.mass`. Riders are ignored because the oracle runs with none. The default is 2 cars, the train `evolve_coaster.py` exports. The oracle cannot set the car count and runs the game's default of 7, so a ride that the oracle completes can still stall in the player's park. This explains why the seed 123 ride stalled for the player and not in the simulator at 7 cars.
- KTD4. **The validator gets no clearance rule.** The game loads saved designs with self-crossings tighter than the piece-by-piece build allows (devlog 2026-08-29), so rejecting them would forbid rides that work. The oracle limit is handled in U5.
- KTD5. **The stall screen and the simulation share one coasting walk.** A flat charge per piece cannot stay conservative once drag grows with speed (measured: 16 of 657 stalling tracks still passed at a charge of 0.25 per piece). The walk and its constants move to `rct2/coasting.py`, which imports neither `construction.py` nor `physics.py`. `energy_stall_index` and `physics.trace` both call it, so they name the same piece by construction.
- KTD6. **Game traces are recorded, not run in CI.** `tests/test_oracle.py` mocks the game. U1 stores the game's trace as a JSON fixture and tests compare the simulator against it. The live probe runs by hand.

### High-Level Technical Design

Game deceleration at flat track, for a 7-car train (M = 3500):

| Speed | Linear term | Squared term | Game total | Simulator today |
|---|---|---|---|---|
| 4 m/s (9 mph) | 0.039 | 0.011 | 0.050 | 0.068 |
| 12 m/s (27 mph) | 0.117 | 0.103 | 0.219 | 0.068 |
| 18 m/s (40 mph) | 0.176 | 0.231 | 0.407 | 0.068 |

The units are m/s². At low speed the simulator over-charges, at high speed it under-charges by up to six times. A 1-car train (M = 500) has seven times the squared term.

### Assumptions

- The game's drag applies per tick to the whole train using total train mass, as the source shows. U1 confirms it on a second track before U2 relies on it.
- The 40 ticks per second and 65536 units per m/s conversions hold. They matched the seed circuit's flat decay (0.218 m/s² predicted, 0.219 observed).
- The scripting API may expose no way to load a saved design. U5 checks the available actions and stops with documented evidence if none exists.
- The 7-car train in the seed trace is one train. The fitted mass of about 3500 supports this (7 cars at 500 each).

### Open Questions

- **Deferred:** Which car count should exported rides use by default? U3 reads the Mine Train template's header and the game's default before choosing.

---

## Implementation Units

| Unit | Title | Files | Depends on |
|---|---|---|---|
| U1 | Capture the game's speed trace | `rct2/oracle.py`, `tests/data/game_traces/` | none |
| U2 | Game drag in the simulator | `rct2/physics.py` | U1 |
| U3 | Train car count as a setting | `rct2/settings.py`, `evolve_coaster.py`, `rct2/oracle.py` | U2 |
| U4 | Retune the stall screen | `rct2/construction.py` | U2, U3 |
| U5 | Spike: run saved designs in the oracle | `rct2/oracle.py`, `docs/headless-oracle-spike.md` | U1 |
| U6 | Check ratings drift and lift speed | `rct2/physics.py`, `data/calibration.csv` | U2 |
| U7 | Document and hand off re-evolution | `docs/devlog.md`, `CLAUDE.md`, `CONCEPTS.md` | U2 to U6 |

### U1. Capture the game's speed trace

- **Goal:** Make the game's per-tick car speed available from `rct2/oracle.py` and record baselines.
- **Requirements:** R3, R7.
- **Dependencies:** none.
- **Files:** `rct2/oracle.py`, `tests/test_oracle.py`, `tests/data/game_traces/seed_circuit.json`, `tests/data/stall_repro/evolved_s123_stalls_in_game.td6` (already added).
- **Approach:**
  1. Add an optional trace to `score_track` that logs the fastest car's velocity, acceleration, mass, track type and progress every N ticks, parsed into `OracleResult`.
  2. Record the seed circuit trace (`create_hill_circuit()`) as a JSON fixture: tick, velocity units, acceleration, mass.
  3. Record a second track that builds and has at least two hills. Find one among the saved runs, or build one from `generate`.
  4. Read the car count the game actually used, since it differs from the 2 requested (see U3).
  5. Map each sample to a piece index by cumulative track distance, since the game reports a track type and progress, not an index. The fixture stores the piece index so U2's tests do not redo the mapping.
- **Execution note:** Characterization first. Record what the game does before any model change.
- **Patterns to follow:** The existing `GENERIDE_STATS` and `GENERIDE_TRAINS` line parsing in `rct2/oracle.py`.
- **Test scenarios:**
  - Parse a `GENERIDE_TRACE` line into samples, with a mocked game output.
  - A trace line with a missing field is skipped, not a crash.
  - Fixture check: the recorded seed trace has the flat-coast deceleration of 357 units at 783k units velocity.
  - With tracing off, `score_track` output and the generated plugin source are unchanged.
- **Verification:** The fixture files exist, parse, and the two-hill track's trace shows a drop and a climb.

### U2. Game drag in the simulator

- **Goal:** Replace constant friction in `trace()` with the game's linear and squared drag, mass-parameterized.
- **Requirements:** R1, R2, R3.
- **Dependencies:** U1.
- **Files:** `rct2/physics.py`, `tests/test_physics.py`.
- **Approach:**
  1. Re-derive the two constants from the game source and a unit check, then state them with the source path as the comment's evidence.
  2. Integrate drag in sub-steps within a piece, since a piece spans a wide speed range.
  3. Remove `FRICTION_COEFF` and its scale-coupling test. Keep `TILE_M` coupling for the g-force coefficient only.
  4. Add train mass as an argument to `trace` and `simulate` with the default from U3.
- **Execution note:** Write the comparison test against U1's fixtures first and watch it fail on the constant-friction model.
- **Patterns to follow:** The existing explanatory constant comments in `rct2/physics.py`, and the Aug 16 devlog habit of citing the game source.
- **Test scenarios:**
  - Seed circuit: simulated speed at the end of each unpowered piece is within 10% of the fixture.
  - Second recorded track: same tolerance.
  - A flat piece at 27 mph for a 7-car train loses 0.219 m/s² within 2%.
  - A 1-car train loses more speed than a 7-car train over the same piece.
  - Seed 123 fixture: `simulate` returns `completed=False` with `stall_index` inside the 66 to 102 range.
  - The seed circuit still completes and the Manic Miner fixture still completes at its recorded car count.
  - Zero mass falls back to no squared term, matching `GetAccelerationDecrease2`.
- **Verification:** `tests/test_physics.py` passes with the comparison tests using recorded game data.

### U3. Train car count as a setting

- **Goal:** One car-count setting drives the simulator mass, the exported ride and the oracle request.
- **Requirements:** R2.
- **Dependencies:** U2.
- **Files:** `rct2/settings.py`, `evolve_coaster.py`, `rct2/oracle.py`, `rct2/evolution.py`, `tests/test_settings.py`, `tests/test_evolve_coaster.py`, `tests/test_oracle.py`.
- **Approach:**
  1. Read the Mine Train template header (`data/sample_rides/manic_miner_test.td6`) and the game's own default car count. Pick the default from those and record the choice as a KTD update.
  2. Add the setting next to the existing run settings, with the CLI flag and the web form field following the existing settings pattern.
  3. Pass the count to `physics.simulate` and to the oracle's `cars_per_train` and `num_trains`, and report the count the game actually used (the existing `ran_cars`).
  4. Save the count in the run record so a run can be reproduced.
- **Patterns to follow:** How `station_length` and `max_width` flow from `rct2/settings.py` to the CLI and run record.
- **Test scenarios:**
  - The default reaches `simulate` and the oracle call unchanged.
  - A non-default count changes the stall index of a marginal track.
  - A run record round-trips the count, and an old record without it loads with the default.
  - An invalid count (zero, negative) is rejected with a clear message.
- **Verification:** The same count is visible in the CLI help, the web form, the run record and the oracle result.

### U4. Share the coasting walk with the stall screen

- **Goal:** Make `energy_stall_index` and `physics.trace` stall on the same piece.
- **Requirements:** R4.
- **Dependencies:** U2, U3.
- **Files:** `rct2/coasting.py`, `rct2/construction.py`, `rct2/physics.py`, `tests/test_construction.py`.
- **Approach:**
  1. Move the drag constants, piece lengths and the per-piece coast into `rct2/coasting.py`. `physics.py` re-exports the names it used to define.
  2. Rewrite `energy_stall_index` as the same speed walk, with the train's car count as an argument. Remove the head constants.
  3. Replace the constants-pin test with a test that the two stall indices agree over a corpus at 1, 2 and 7 cars.
- **Test scenarios:**
  - Screen and simulation agree on the stalling piece for 150 random part-based tracks and the Manic Miner fixture, at 1, 2 and 7 cars.
  - A lighter train stalls sooner on a long flat loop.
  - The screen never passes a track the simulation stalls, over 600 random tracks from both generators.
- **Verification:** The full suite passes and the screen costs a few microseconds per piece.

### U5. Spike: run saved designs in the oracle

- **Goal:** Find out whether the oracle can load a saved design the way the game does, so rides with tight self-crossings can be measured.
- **Requirements:** R5.
- **Dependencies:** U1.
- **Files:** `rct2/oracle.py`, `tests/test_oracle.py`, `docs/headless-oracle-spike.md`, `tests/data/stall_repro/`.
- **Approach:**
  1. List the actions the installed game (v0.5.3) exposes for placing a track design, using the plugin API's action list and the game source for `TrackDesignAction`.
  2. If one takes a design file, write the `.td6` to the track folder and place it, then compare its result to the piece-by-piece build on a ride that builds both ways.
  3. If none exists, record the evidence in `docs/headless-oracle-spike.md` and stop. Do not build a workaround.
- **Execution note:** Time-boxed. A negative result is a complete outcome.
- **Test scenarios:**
  - If a route is found: the seed 123 fixture returns a rated or stalled result instead of `placement_failed`.
  - If a route is found: a ride that builds both ways gets the same rating from both.
  - If a route is found: a design the game rejects on load returns a clear status, not a timeout.
  - If no route is found: `Test expectation: none -- documentation of a negative result`.
- **Verification:** Either the seed 123 ride runs in the oracle, or the spike document names the evidence that rules each route out.

### U6. Check ratings drift and lift speed

- **Goal:** Measure what the new speeds do to the ratings and compare lift speed to the game.
- **Requirements:** R8, R9.
- **Dependencies:** U2.
- **Files:** `rct2/physics.py`, `rct2/calibration.py`, `tests/test_calibration.py`.
- **Approach:**
  1. Run the calibration comparison before and after U2 and record mean absolute error per rating.
  2. If drift exceeds R8, stop and report. Do not refit in this plan.
  3. From U1's seed trace, measure the lift's speed and duration and compare to `LIFT_SPEED_MS`. Record the result.
- **Test scenarios:**
  - The calibration comparison runs on the 204 designs and returns finite errors.
  - A regression test pins the post-change error values with a tolerance, so later drift shows.
- **Verification:** A short table of before and after errors is in the devlog entry (U7).

### U7. Document and hand off re-evolution

- **Goal:** Record what changed and give the owner the steps to re-run.
- **Requirements:** Success Criteria.
- **Dependencies:** U2 to U6.
- **Files:** `docs/devlog.md`, `CLAUDE.md`, `CONCEPTS.md`.
- **Approach:**
  1. Add a devlog entry: the formula, the evidence, what the old model hid, and the R8 and R9 results.
  2. Update the `physics.py` paragraph in `CLAUDE.md` to say the simulator uses the game's drag.
  3. Add "Train mass" to `CONCEPTS.md` if the term is used in the code.
  4. List the commands for the owner: the benchmark re-run and a fresh 150-generation evolve, with the game check on the result.
- **Test expectation:** none -- documentation only.
- **Verification:** The doc names the seed 123 ride and the new stall piece the simulator reports.

---

## Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Sub-step integration differs from the game's tick integration | Speed differs more than 10% on steep pieces | U2 compares piece by piece and adds sub-steps until it matches |
| Few tracks build in the game | R3 rests on two tracks | U1 requires a second, multi-hill track |
| The raised screen charge rejects too many tracks | Search loses good rides | U4 reports the rejection rate before merging |
| No API route to load a saved design | R5 ends as a documented limit; the drag fix is checked on tracks that build piece by piece | U5 stops with evidence |

---

## Verification Contract

| Check | Command | Applies to |
|---|---|---|
| Full suite | `.venv/bin/python -m pytest -q` | every unit |
| Physics | `.venv/bin/python -m pytest tests/test_physics.py -q` | U2, U3, U6 |
| Stall screen | `.venv/bin/python -m pytest tests/test_construction.py -q` | U4 |
| Oracle parsing | `.venv/bin/python -m pytest tests/test_oracle.py -q` | U1, U3 |
| Live game check | `PYTHONPATH=. .venv/bin/python -m rct2.oracle <td6>` | U1, U5 |

## Definition of Done

- All R-IDs are met and the full suite passes (888 tests before this plan, plus the new ones).
- The seed 123 ride is reported as stalling by the simulator; rides that complete in the simulator and build piece by piece are unchanged.
- No scratch probe code remains outside `rct2/oracle.py`; abandoned experiments are removed from the diff.
- The devlog entry and `CLAUDE.md` updates are in.
- Re-evolution is listed for the owner and not run.
