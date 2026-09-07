---
title: Oracle Calibration Sampling - Plan
type: feat
date: 2026-09-07
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Oracle Calibration Sampling - Plan

## Goal Capsule

- **Objective:** an `evolve_parts()` run can be periodically checked against the real game's own rating, on request, without changing the result of any run that doesn't ask for it.
- **Means:** a per-generation hook inside `evolve_parts()` that samples the current best individual (and, less often, the worst construction-valid one) through the existing `rct2.oracle.score_track()`, gated behind new opt-in CLI flags (KTD1, KTD7).
- **Authority hierarchy:** this plan's Key Decisions and KTDs govern the implementation; an implementer who finds one unworkable stops and flags it rather than silently reinterpreting it.
- **Stop conditions:** stop and ask if satisfying R3 (bit-identical output with calibration on vs. off) turns out to require touching `evolve_parts()`'s existing selection or mutation logic, or if the fix requires changes to `rct2/oracle.py` or `rct2/physics.py` beyond calling `score_track()` as it exists today — both are out of scope (Scope Boundaries).
- **Execution profile:** single-session implementation work, no autonomous rollout.
- **Tail ownership:** the implementer; no separate rollout or on-call handoff.

---

## Product Contract

### Summary

Add an opt-in way to periodically check `evolve_parts()`'s output against the real game, so the project's "Oracle-confirmed rating" metric (STRATEGY.md) starts collecting real data instead of reading "not yet wired into a run." Calibration sampling never influences the genetic algorithm itself — it only logs what the real game says about tracks the algorithm already produced.

### Problem Frame

STRATEGY.md's Score calibration track calls for the proxy fitness, the physics checks, and the oracle's real ratings to agree with each other, and its "Oracle-confirmed rating" metric is currently unmeasured. `rct2/oracle.py` can already build a track in a real, headless OpenRCT2 and read back the game's own rating (`score_track()`), and `rct2/benchmark.py` already uses it to judge saved results after a run finishes — but nothing calls it *during* an `evolve_parts()` run, so no evolved track has ever been checked against the game except by hand.

A same-session `ce-debug` investigation confirmed the one known blocker — the oracle's piece-by-piece build rejects some self-crossing tracks the real game accepts (`rct2/oracle.py:65-83`) — is already diagnosed and documented, not an open bug, and doesn't need fixing before this can proceed: a rejected track is simply unjudgeable, not evidence the calibration data is wrong.

### Requirements

**Sampling behavior**

- R1. When explicitly enabled, `evolve_parts()` samples the current generation's best individual every N generations and passes its segment list to `oracle.score_track()`, logging the result.
- R2. Less often than the best, the worst construction-valid individual in the current generation is also sampled and logged the same way.
- R3. Enabling or disabling sampling never changes `evolve_parts()`'s own output: `best_individual.segments`, `fitness_history`, and `valid_ratio_history` are bit-identical for the same seed whether or not calibration is on.
- R4. A `placement_failed` oracle result is logged as "unjudgeable, skip" — never as a bad score or as evidence the track itself is broken.
- R5. Total oracle calls in a run are capped; reaching the cap stops sampling for the rest of that run.

**CLI and operator experience**

- R6. Sampling is off by default. An operator opts in with new flags on `evolve_coaster.py`.
- R7. Passing the calibration flags together with `--genome pieces` (which has no sampling hook) is a hard error, not a silent no-op.
- R8. When calibration is enabled, the CLI prints the worst-case added wall-clock time before the run starts.

### Key Decisions

- **KD1. Sampling is opt-in and off by default** (session-settled: user-approved — chosen over always-on: keeps an ordinary run from ever paying the oracle's per-call cost). Governs R6.
- **KD2. Results write to a new, dedicated log file, not the existing `calibration.csv`** (session-settled: user-approved — chosen over merging into that file: `calibration.csv` holds real shipped designs' own header stats, a different shape of data from a synthetic evolved track's oracle read). Governs R1, R2.
- **KD3. The "worst" sample is the worst-scoring individual in the current generation, not a tournament-selection loser** (session-settled: user-approved). Governs R2.
- **KD4. A `placement_failed` result means "can't judge this track," never "bad track"** (session-settled: user-approved, following this session's `ce-debug` finding that this is a known, already-documented oracle limitation for self-crossing tracks, not an open defect). Governs R4.

### Scope Boundaries

- Fixing `physics.py`'s known ~1.43-1.45x distance underestimate is out of scope (separate, already-diagnosed issue).
- Redesigning `oracle.py`'s construction method (building via track-design loading instead of piece-by-piece placement) to accept self-crossing tracks is out of scope — a research spike on its own, since it isn't confirmed the scripting API can do this at all.
- Oracle results influencing fitness, selection, or survival is explicitly out of scope now and for the foreseeable future of this plan; R3 exists specifically to guard against it happening by accident.

#### Deferred to Follow-Up Work

- Batching multiple tracks through one running game process (noted as "worth doing" in docs/research-plan.md).
- Using accumulated calibration log data to actually recalibrate `physics.py` or `ratings.py`.

---

## Planning Contract

### Key Technical Decisions

- **KTD1.** The hook is a private function (e.g. `_maybe_sample_oracle_calibration`) called from `evolve_parts()`'s generation loop (`rct2/evolution.py:483-509`) immediately after the existing `progress_callback(gen, population)` call, where `population.best()` is already computed as `best`. It only reads `population` and never mutates it, `next_gen`, or any `Individual.fitness` — this is what makes R3 hold by construction rather than by a test alone.
- **KTD2.** `rct2.oracle` is imported lazily inside the hook function, and the hook accepts an injectable scorer callable (default `oracle.score_track`), mirroring `rct2/benchmark.py`'s `_oracle_scorer` pattern. This keeps `rct2/evolution.py` importable with no OpenRCT2 install, and keeps tests independent of a real game.
- **KTD3.** All four `OracleResult.status` values (`rated`, `stalled`, `timeout`, `placement_failed`) are written to the log uniformly, one record each. The writer never special-cases `placement_failed` into a different code path than the other three; "unjudgeable, skip" (R4) is a label on the record, decided when the log is later read, not a different write path.
- **KTD4.** Reaching `--oracle-max-calls` stops sampling for the rest of the run. The interval is never widened to spread remaining budget across remaining generations.
- **KTD5.** The worst individual is sampled on every 3rd interval tick that also samples the best, counted against the same call budget. The worst candidate is drawn from construction-valid individuals only (`ind.is_valid()`), via `min(...)` over that filtered set — sampling a construction-invalid track would almost always just return `placement_failed` and waste a call, and it isn't the "fast model might be wrong about an uncertain track" case docs/research-plan.md's rejected-candidate sampling is actually about.
- **KTD6.** The log format is JSON Lines: one JSON object per oracle call, appended to disk as it happens, never batched into a single JSON array at the end — a crash mid-run then loses nothing already collected. Each record carries the run's `rng_seed` and a UTC timestamp, so multiple runs appending to the same default log path stay distinguishable.
- **KTD7.** New `evolve_coaster.py` flags, following its existing argparse style (short forms, inline defaults in `help=`): `--oracle-calibrate` (`action="store_true"`), `--oracle-interval` (`type=int`), `--oracle-max-calls` (`type=int`), `--oracle-log` (`type=Path`, defaulting off `args.output.with_suffix(...)` the way `--render`'s outputs already do). Passing `--oracle-calibrate` with `--genome pieces` raises a clear error, matching the existing `--station-length` validation style (`evolve_coaster.py:232-235`).
- **KTD8.** Before the generation loop starts, when calibration is enabled, the CLI prints one line stating the worst-case added time (`max_calls * 90s`, from `score_track`'s `process_timeout_s` default), alongside the existing pre-run lines (`RNG seed:`, generation/population settings).

### Assumptions

- No CLI-level test file exists yet for `evolve_coaster.py` (confirmed: no `tests/test_evolve_coaster.py`). U3 introduces one, following `tests/test_evolution.py`'s class-based style rather than an existing CLI test convention, since none exists to follow.

---

## Implementation Units

### U1. Calibration hook in `evolve_parts()`

**Goal:** add the per-generation sampling hook so a calibration-enabled run logs oracle results without changing the GA's own output.

**Requirements:** R1, R2, R3, R4, R5. Governs KD1-KD4 via KTD1, KTD3, KTD5.

**Dependencies:** none.

**Files:**
- `rct2/evolution.py` (modify — add the hook function and its call site in `evolve_parts()`)
- `tests/test_evolution.py` (modify — new test class)

**Approach:**
- Add `_maybe_sample_oracle_calibration(gen, population, interval, max_calls, calls_so_far, worst_every, scorer, log_writer)` per KTD1, called from the seam KTD1 names.
- On a best-sample tick: read `population.best()` (already computed), pass `.segments` to `scorer`.
- On a worst-sample tick (every 3rd best-tick, KTD5): compute the worst construction-valid individual inline (`ind.is_valid()` filter, `min` by fitness); skip the worst sample entirely if no individual in the generation is valid.
- Track and enforce `max_calls` across both best and worst samples combined (KTD4); once reached, no further calls occur for the rest of the run.
- Never touch `population`, `next_gen`, elitism, or tournament selection — the function's only side effect is calling `scorer` and `log_writer`.
- `evolve_parts()`'s new parameters default to values that disable the hook entirely (KD1), so existing callers and existing tests are unaffected.

**Patterns to follow:** the existing `progress_callback` parameter already threaded through `evolve_parts()`'s loop is the shape to mirror for a per-generation, read-only observer hook.

**Test scenarios:**
- Sampling disabled (default): `evolve_parts()`'s output is identical to before this change, for a fixed seed.
- Sampling enabled with a fake scorer: the scorer is called on the expected generations (e.g. interval 5 over 20 generations calls on gen 0, 5, 10, 15), with the best individual's exact segments.
- Worst-sample cadence: over enough generations, the fake scorer receives a worst-individual call on every 3rd best-tick and no others.
- Worst-sample selection: given a population where the lowest-fitness individual is construction-invalid, the worst sample sent to the scorer is the lowest-fitness *valid* individual instead.
- No valid individuals in a generation: the worst-sample call is skipped for that tick, not sent with an invalid track.
- Max-calls cap: with `max_calls` set below the number of ticks that would otherwise fire, sampling stops after the cap and no further scorer calls happen for the rest of the run, even though the interval would otherwise call again.
- Reproducibility (covers R3): two runs with the same `rng_seed`, one with calibration enabled and one without, produce bit-identical `best_individual.segments`, `fitness_history`, and `valid_ratio_history`.
- `placement_failed` from the scorer is passed to `log_writer` unchanged (not swallowed, not converted to a score) — proves R4 at the hook level; U2 proves the writer's actual label.

**Verification:** the new test class in `tests/test_evolution.py` passes, and the existing `TestEvolveParts`/`TestReproducibility` classes still pass unmodified.

---

### U2. Calibration log writer

**Goal:** a small, dataclass-backed JSON-lines writer that turns an `OracleResult` into one appended log record.

**Requirements:** R4, R5 (the record format that lets a reader treat `placement_failed` as unjudgeable). Governs KD4 via KTD3, KTD6.

**Dependencies:** none (can be built independently of U1, wired together at U1's `log_writer` parameter).

**Files:**
- `rct2/calibration_log.py` (new)
- `tests/test_calibration_log.py` (new)

**Approach:**
- Define a small dataclass capturing: the sampled role (`"best"` or `"worst"`), generation number, `rng_seed`, a UTC timestamp, and the `OracleResult` fields (`status`, `excitement`, `intensity`, `nausea`, `detail`, `stalled_at_index`, `stalled_at_type`, `measurements`) plus the segment list, following `RunResult`'s precedent in `rct2/benchmark.py` of storing the full segment list on every record.
- A single append function writes one JSON line per call, opening the file in append mode each time (or keeping it open for the run's duration — implementer's choice, either satisfies KTD6's crash-safety intent).
- All four `status` values write through the same path (KTD3) — no branching that treats `placement_failed` differently at write time.

**Patterns to follow:** `rct2/benchmark.py`'s `RunResult.to_dict()`/`from_dict()` `dataclasses.asdict`-based JSON pattern.

**Test scenarios:**
- A `rated` result writes one JSON line with all rating fields populated.
- A `stalled` result writes one line with `status="stalled"` and no rating fields.
- A `placement_failed` result writes one line with `status="placement_failed"`, distinguishable by a downstream reader from a `rated` or `stalled` line by status alone.
- Two calls append two lines to the same file, in order, without corrupting the first line.
- Each line round-trips: written then re-read, its fields match what was passed in.

**Verification:** `tests/test_calibration_log.py` passes; a manually inspected sample log file is valid JSON on every line.

---

### U3. CLI flags on `evolve_coaster.py`

**Goal:** expose opt-in calibration sampling from the command line, with validation and an upfront cost estimate.

**Requirements:** R6, R7, R8. Governs KD1 via KTD7, KTD8.

**Dependencies:** U1 (the `evolve_parts()` parameters this wires up), U2 (the log writer this points `--oracle-log` at).

**Files:**
- `evolve_coaster.py` (modify)
- `tests/test_evolve_coaster.py` (new — see Assumptions)

**Approach:**
- Add `--oracle-calibrate`, `--oracle-interval`, `--oracle-max-calls`, `--oracle-log` per KTD7, in the existing flag block (`evolve_coaster.py:87-198`).
- Validate `--oracle-calibrate` requires `--genome parts`; raise the same style of clear, immediate error as the existing `--station-length` check (`evolve_coaster.py:232-235`) rather than proceeding.
- Default `--oracle-log` off `args.output.with_suffix(...)`, mirroring `--render`'s derived sibling paths (`evolve_coaster.py:357-358`).
- When enabled, print the KTD8 estimate line before calling `run(...)` (the existing `evolve_parts`/`evolve` dispatch at `evolve_coaster.py:301`), alongside the existing `RNG seed:` and settings lines.
- Thread the new flags through to `evolve_parts(...)` only when `args.genome == "parts"`.

**Patterns to follow:** existing argparse flags in `evolve_coaster.py` (short forms, `type=`, `default=`, inline-default `help=` text); the existing `--station-length` validation block for the hard-error style.

**Test scenarios:**
- `--oracle-calibrate --genome parts` with valid interval/cap values parses and threads through to `evolve_parts()` with sampling enabled.
- `--oracle-calibrate --genome pieces` raises the documented error and does not start a run.
- No `--oracle-calibrate` flag: behavior is unchanged from before this plan (default off, per R6).
- `--oracle-log` omitted: the log path defaults off `args.output`'s stem, following the `--render` sibling-path precedent.
- The upfront estimate line prints when calibration is enabled and is absent when it isn't.

**Verification:** `tests/test_evolve_coaster.py` passes; a manual run with `--oracle-calibrate --genome parts --generations 5` (no real OpenRCT2 required if a fake scorer is exposed for manual testing, otherwise a short real run) produces a log file at the expected path.

---

## Verification Contract

| Command | Applicability |
|---|---|
| `pytest tests/test_evolution.py` | U1 — confirms the hook and R3's reproducibility guarantee |
| `pytest tests/test_calibration_log.py` | U2 — confirms the log writer |
| `pytest tests/test_evolve_coaster.py` | U3 — confirms CLI flags and validation |
| `pytest` | Full suite — confirms no regression elsewhere |

No behavioral-skill evaluation or `release:validate` gate applies; this is a local Python project with a `pytest`-only test suite.

## Definition of Done

- All three new/modified test files pass, and the full `pytest` suite has no regressions.
- R3 is proven by an explicit test (not just asserted in prose): identical `rng_seed` produces identical `evolve_parts()` output with calibration on and off.
- A real (or fake-scorer) run with `--oracle-calibrate --genome parts` produces a readable JSON-lines log file at the expected path.
- No leftover debug prints, commented-out code, or abandoned approaches from exploring the hook's placement remain in the diff.
