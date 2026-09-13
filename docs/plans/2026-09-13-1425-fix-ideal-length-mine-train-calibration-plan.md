---
title: ideal_length Mine Train Calibration - Plan
type: fix
date: 2026-09-13
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# ideal_length Mine Train Calibration - Plan

## Goal Capsule

- **Objective:** Generide's evolved Mine Train tracks stop hitting a fitness penalty at a length shorter than real Mine Train rides run. The two shortest real designs (82 and 89 segments) get full credit for their length under the new setting; the two longest (104 and 142 segments) still ease into a penalty past the new ceiling, but a much smaller one than the old 80-segment ceiling gave them.
- **Means:** Raise `ProxyFitness`'s `ideal_length` and `generate_random_track_parts`'s `max_length` to values calibrated from this project's own Mine-Train-specific data (KTD1, KTD2).
- **Authority hierarchy:** This plan is authoritative on scope and the chosen values (KTD1, KTD2). The implementer resolves execution-time specifics this plan does not name.
- **Stop conditions:** Stop and flag if the before/after verification in U3 shows construction-validity regressing, or the tight-footprint run reopening the genome-length climb PR #58 fixed.
- **Execution profile:** Code change, single repo, no CLI surface change, no data migration.
- **Tail ownership:** Standard `ce-work` handoff — commit and PR per repo convention, then `ce-babysit-pr` through CI.

---

## Product Contract

### Summary

Raise `ProxyFitness`'s `ideal_length` (currently 80, below every real Mine Train design in this project's own calibration data) to 100, which fully covers the two shortest real designs and eases the penalty for the two longest, and raise `generate_random_track_parts`'s separate `max_length` (currently 30) so generation-0 individuals can reach further toward that new ceiling. Closes GitHub issue #43.

### Problem Frame

`ProxyFitness` rewards a track's length only up to `ideal_length`, then applies a much smaller `over_length_penalty` beyond it. The current value, 80, was set from the median element count (82) across all 204 shipped designs in `data/calibration.csv` — a mixed population of every ride type the game ships, not just Mine Trains. This project builds only Mine Train coasters today (`STRATEGY.md`). Filtering the same calibration data to Mine Train rides specifically (`ride_type == 17`, matching `rct2/oracle.py`'s `MINE_TRAIN_RIDE_TYPE`) gives four real shipped designs — Calamity Mine (142), Gold Rush (104), Manic Miner (89), Runaway Mine Train (82) — and every one of them exceeds the current default. `generate_random_track_parts`'s `max_length=30` was never revisited when `ideal_length` last moved (issue #43's other action item), so the initial population's random slice starts far short of even the old ceiling.

PR #58 (merged) recently fixed `WeightedProxyFitness.evaluate()` so elevation, turn-balance, and variety rewards are capped at `ideal_length` the same way the length reward already was — previously only length was capped, which let genome length grow unboundedly under a tight footprint (`docs/solutions/performance-issues/genome-bloat-from-uncapped-fitness-rewards.md`). Raising `ideal_length` now widens the reward-bearing window for all four terms at once, not one, so this plan verifies that widening the window doesn't reopen the pattern that fix closed.

### Requirements

**Fitness scoring**
- R1. `ProxyFitness` and `WeightedProxyFitness`'s `ideal_length` default moves from 80 to a value that sits above every real Mine Train design's element count in `data/calibration.csv`.
- R2. The new value is justified against `data/calibration.csv`'s Mine Train rows, not picked arbitrarily, per issue #43's acceptance criteria.

**Initial population**
- R3. `generate_random_track_parts`'s `max_length` default rises from 30, staying meaningfully below the new `ideal_length` so generation-0 individuals keep a fitness gradient across their full length range.

**Verification**
- R4. Evolution can produce tracks as long as the two shortest real Mine Train designs (82-89 segments) with no length penalty, and can still reach the two longest (104-142 segments) under a much smaller penalty than before, when the footprint allows it.
- R5. Construction-validity rates at the default footprint do not regress.
- R6. Per-generation runtime under a tight footprint does not reopen the genome-bloat pattern PR #58 fixed.
- R7. Per-generation runtime under `PhysicsFitness` does not regress, since `generate_random_track_parts` is the shared initial-population generator for both fitness paths and `max_length` reaches it either way.

### Key Decisions

- **`ideal_length` is sourced from Mine-Train-specific calibration data, not the broader all-ride-type distribution.** (session-settled: user-approved — chosen over reusing the all-204-design median of 82: this project builds only Mine Train coasters, and Mine Trains in the data run longer than the mixed population overall). Governs R1, R2.
- **`max_length` is raised only partway toward the new `ideal_length`, not matched to it.** (session-settled: user-approved — chosen over setting them equal: keeps a fitness gradient across the top of the randomly-generated initial population instead of starting some individuals at the reward ceiling with zero room to grow). Governs R3.
- **Only the parts-genome path (`generate_random_track_parts`) is in scope; the flat-genome `generate_random_track` is untouched.** (session-settled: user-approved — chosen over updating both: `evolve_parts()`, what the CLI defaults to, only calls the parts-genome function; the flat genome is a separate, lower-priority path). Governs R3.

### Scope Boundaries

- Not touching `repair_circuit`'s own repair budget (`max_repair_segments`) — a separate mechanism from reward capping.
- Not touching `PhysicsFitness` — it has no `ideal_length`-equivalent term.
- Not adding per-ride-type configurability or new CLI flags for either constant — a single global default, matching this project's current Mine-Train-only focus.
- Not touching `generate_random_track` (the flat, non-parts genome).

#### Deferred to Follow-Up Work

- If generide ever supports ride types beyond Mine Trains (explicitly out of scope today per `STRATEGY.md`), `ideal_length` and `max_length` would need to become per-ride-type rather than global defaults.
- `rct2/benchmark.py`'s GA methods are hardcoded to `PhysicsFitness`; a `ProxyFitness`-based benchmark path would give future proxy-fitness tuning a repeatable harness, but is not required to land this plan.
- Once a track has a real build-cost estimate (issue #44, `CoasterRequest.cost` is accepted but never scored), `ideal_length` stops being a fixed target calibrated from real ride lengths and becomes a tradeoff against that cost budget — a longer track costs more to build, and a cost-constrained request might prefer shorter over matching real-world length exactly. That rework depends on #44 landing first and is out of scope here.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Set `ideal_length` to 100.** (session-settled: user-approved — chosen over the all-ride-type median of 82: the four real Mine Train designs — 82, 89, 104, 142, excluding this project's own synthetic `generide-evolved-seed123` calibration row — have a median of 96.5 and a mean of 104.25; 100 sits between the two, above the two shortest real designs (82, 89) and below the two longest (104, 142)). Governs R1, R2.
- KTD2. **Set `generate_random_track_parts`'s `max_length` to 50.** (session-settled: user-approved — chosen over matching `ideal_length` exactly: leaves a 50-segment margin so no generation-0 individual starts at the reward ceiling). Governs R3.
- KTD3. Add a regression test pinning `max_length < ideal_length` as an explicit invariant. Nothing in the code today connects `rct2/fitness.py`'s `ideal_length` to `rct2/mutations.py`'s `max_length`; without a test, a future change to either constant could silently violate the margin KTD2 depends on.
- KTD4. Verify "validity rates do not regress" (R5) using `evolve_coaster.py`'s own printed valid-count ratio, run before and after at matched seeds — not `rct2/benchmark.py`'s `reliability()` harness. That harness's GA methods are hardcoded to `PhysicsFitness` and never construct a `ProxyFitness` or call `generate_random_track_parts` with a non-default `max_length`, so it cannot measure the thing this plan changes.
- KTD5. Re-run the exact tight-footprint reproduction from the genome-bloat fix (`--max-width 10 --max-depth 20 --genome parts --generations 250 --population 75 --rng-seed 7`) before and after this change, comparing population-average genome length and per-generation time against the numbers already recorded in `docs/solutions/performance-issues/genome-bloat-from-uncapped-fitness-rewards.md`. Raising `ideal_length` widens the reward headroom that fix was built to police, so this is the direct check that it still holds.
- KTD6. Also re-run `evolve_coaster.py --fitness physics --genome parts` before and after, at a matched seed, comparing per-generation wall-clock time (R7). `generate_random_track_parts` has no awareness of which fitness function is scoring its output, so raising `max_length` lengthens generation-0 individuals under `PhysicsFitness` exactly as it does under `ProxyFitness` — and `PhysicsFitness.evaluate()` runs a full ride simulation per individual, so longer tracks cost more there too. This is the exact runtime risk issue #43 named ("longer tracks cost more per physics evaluation"); KTD4 and KTD5 alone don't check it, since both use the proxy path.

### Sources / Research

- `rct2/fitness.py:143-168` (`WeightedProxyFitness.__init__`), `:190-288` (`evaluate()`, including the `reward_segments` cutoff PR #58 added at line 224), `:300-312` (`ProxyFitness.__init__`, which re-declares `ideal_length` rather than inheriting it).
- `rct2/mutations.py:684-736` (`generate_random_track_parts`), `:414-503` (`repair_circuit`, out of scope but load-bearing context).
- `rct2/evolution.py:378-403` (`_create_initial_population_parts`, which calls `generate_random_track_parts` with no `max_length` override).
- Precedent: the prior 50-to-80 change (`docs/devlog.md`, 2026-08-09 entry) touched `rct2/fitness.py`'s two defaults plus its docstring, and a one-line fixture update in `tests/test_fitness.py`, with no CLI change and a matching devlog entry. This plan follows the same shape.
- `docs/solutions/performance-issues/genome-bloat-from-uncapped-fitness-rewards.md` — the mechanism KTD5 verifies against.
- `data/calibration.csv`, filtered to `ride_type == 17` (Mine Train Coaster, per `rct2/oracle.py`'s `MINE_TRAIN_RIDE_TYPE`), excluding the project's own synthetic `generide-evolved-seed123` row.

---

## Implementation Units

### U1. Raise `ideal_length` in `rct2/fitness.py`

- **Goal:** Move `ideal_length`'s default from 80 to 100 in both fitness classes, update the docstring's calibration rationale, and keep the existing "past ideal_length" test fixture accurate.
- **Requirements:** R1, R2
- **Dependencies:** none
- **Files:**
  - `rct2/fitness.py`
  - `tests/test_fitness.py`
- **Approach:**
  1. Change `ideal_length: int = 80` to `100` in both `WeightedProxyFitness.__init__` and `ProxyFitness.__init__` — both must move together, since `ProxyFitness` re-declares the default rather than inheriting it.
  2. Rewrite the docstring rationale (currently citing the all-204-design median of 82) to cite the Mine-Train-specific data behind KTD1 instead.
  3. Extend the `_mixed_corpus()` "past ideal_length" fixture so its total segment count still exceeds 100, and update its comment to match.
- **Test scenarios:**
  - Happy path: `WeightedProxyFitness().ideal_length == 100` and `ProxyFitness().ideal_length == 100`.
  - Regression: `test_weighted_defaults_match_proxy_exactly` and `test_reward_weights_reach_the_score` (both consuming `_mixed_corpus()`) still pass after the fixture's padding is extended.
  - Edge case: a track exactly at the new `ideal_length` (100 segments) earns full length/elevation/turn/variety reward; a track one segment past it earns `over_length_penalty` on exactly the excess.
- **Verification:** `python3 -m pytest tests/test_fitness.py -q` passes.

### U2. Raise `max_length` in `rct2/mutations.py` and pin the invariant

- **Goal:** Move `generate_random_track_parts`'s `max_length` default from 30 to 50, and add a regression test pinning `max_length < ideal_length`.
- **Requirements:** R3
- **Dependencies:** U1 (the invariant test needs the new `ideal_length` value)
- **Files:**
  - `rct2/mutations.py`
  - `tests/test_mutations.py`
- **Approach:**
  1. Change `max_length: int = 30` to `50` in `generate_random_track_parts`'s signature.
  2. Add a test that imports `ProxyFitness().ideal_length` and `generate_random_track_parts`'s default `max_length`, asserting the former is strictly greater (KTD3), so a future change to either constant that violates the margin fails loudly.
- **Test scenarios:**
  - Happy path: `generate_random_track_parts(rng)` with default arguments can produce tracks up to 50 non-hill, non-station segments.
  - Invariant: `generate_random_track_parts`'s default `max_length` is strictly less than `ProxyFitness()`'s default `ideal_length`.
  - Regression: `test_generate_random_track_parts_respects_length_bounds` (explicit `min_length=5, max_length=10`) and the `TestHillIsAlwaysPresent` tests are unaffected, since they don't depend on the default.
- **Verification:** `python3 -m pytest tests/test_mutations.py -q` passes; the new invariant test fails if `max_length` is ever raised to or past `ideal_length`.

### U3. Verify validity and runtime don't regress

- **Goal:** Confirm issue #43's acceptance criteria — evolution reaches at least the shorter real Mine Train lengths without penalty (R4), construction-validity doesn't regress, and runtime doesn't regress under either fitness path.
- **Requirements:** R4, R5, R6, R7
- **Dependencies:** U1, U2
- **Files:** none (verification-only; no production files change)
- **Approach:**
  1. Run `evolve_coaster.py --genome parts --fitness proxy --verbose` at the default 30x30 footprint, at a matched `--rng-seed`, before and after U1/U2. Compare the printed `valid=X/Y` ratio and final best-track length against the pre-change baseline (KTD4).
  2. Re-run the tight-footprint reproduction from the genome-bloat fix (`--max-width 10 --max-depth 20 --genome parts --generations 250 --population 75 --rng-seed 7`) before and after. Compare population-average genome-length trajectory and per-generation time against the numbers recorded in `docs/solutions/performance-issues/genome-bloat-from-uncapped-fitness-rewards.md` (KTD5).
  3. Run `evolve_coaster.py --genome parts --fitness physics --verbose` at a matched `--rng-seed`, before and after U1/U2. Compare per-generation wall-clock time against the pre-change baseline (KTD6).
  4. Carry all three before/after results into U4's devlog entry.
- **Test scenarios:**
  - Test expectation: none — this unit is empirical verification of already-implemented code, not new production behavior.
- **Verification:** The default-footprint run's valid ratio and best-track length are not worse than the pre-change baseline. The tight-footprint run's genome-length trajectory still plateaus rather than climbing the way it did before PR #58, and per-generation time stays in the flat range that fix established. The physics-fitness run's per-generation time is not worse than its pre-change baseline.

### U4. Close the loop: docstrings, devlog, issue

- **Goal:** Bring project documentation in line with the new defaults and close GitHub issue #43.
- **Requirements:** R1, R2
- **Dependencies:** U1, U2, U3
- **Files:**
  - `docs/devlog.md`
  - `docs/research-plan.md`
- **Approach:**
  1. Add a `docs/devlog.md` entry recording the new `ideal_length`/`max_length` values, the Mine-Train-specific calibration numbers behind them, and U3's before/after results — matching the shape of the 2026-08-09 entry that recorded the 50-to-80 change.
  2. Update `docs/research-plan.md`'s reference to the old "80" value so it matches the new default.
  3. Close GitHub issue #43, referencing the shipping PR.
- **Test scenarios:**
  - Test expectation: none — documentation-only unit.
- **Verification:** `docs/devlog.md` and `docs/research-plan.md` no longer cite 80 as the current `ideal_length`; issue #43 is closed with a reference to the shipping PR.

---

## Verification Contract

| Command | Applies to | Gate |
|---|---|---|
| `python3 -m pytest -q` | All units | Full suite passes, no regressions |
| `python3 -m pytest tests/test_fitness.py -q` | U1 | Reward-capping tests pass at the new `ideal_length` |
| `python3 -m pytest tests/test_mutations.py -q` | U2 | `max_length < ideal_length` invariant test passes |
| `python3 evolve_coaster.py --genome parts --fitness proxy --verbose --rng-seed <seed>` (before/after) | U3 | Valid ratio and best-track length not worse than baseline |
| `python3 evolve_coaster.py --genome parts --max-width 10 --max-depth 20 --generations 250 --population 75 --rng-seed 7 --verbose` (before/after) | U3 | Genome-length trajectory plateaus; per-generation time stays flat |
| `python3 evolve_coaster.py --genome parts --fitness physics --verbose --rng-seed <seed>` (before/after) | U3 | Per-generation wall-clock time not worse than baseline |

---

## Definition of Done

- Full test suite passes with no regressions.
- `ideal_length` is 100 in both `WeightedProxyFitness` and `ProxyFitness`; `max_length` is 50 in `generate_random_track_parts`; the `max_length < ideal_length` invariant test passes.
- All three U3 before/after verification runs show no regression in validity rate, tight-footprint runtime, or physics-fitness runtime.
- `docs/devlog.md` and `docs/research-plan.md` reflect the new values; issue #43 is closed.
- No leftover dead-end code from approaches that didn't pan out during implementation.
