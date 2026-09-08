---
title: Genome bloat from uncapped fitness rewards under a tight footprint
date: 2026-09-07
category: performance-issues
module: rct2/fitness.py
problem_type: performance_issue
component: fitness_scoring
symptoms:
  - "Genetic algorithm run with --max-width 10 --max-depth 20 (a footprint much tighter than the 30x30 default) ran 96+ CPU-minutes without finishing, versus a couple of minutes for a normal run"
  - "Process memory grew from 54MB to 288MB over the course of the run"
  - "Population-average genome length climbed every generation instead of stabilizing, from 38.6 to 97.3 segments by generation 68, still accelerating"
  - "Per-generation runtime kept rising instead of staying flat, since fitness evaluation cost scales with segment count"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [genetic-algorithm, fitness-function, genome-bloat, performance, footprint-constraint, repair-circuit]
related_components: [rct2/mutations.py, rct2/evolution.py]
---

# Genome bloat from uncapped fitness rewards under a tight footprint

## Problem

Under a tight build footprint (`--max-width 10 --max-depth 20`), the genetic algorithm in `evolve_coaster.py --genome parts` never converged: track genomes grew without bound generation after generation instead of settling near the target length, so runs that normally finish in under a minute instead ran 96+ CPU-minutes and kept consuming more memory. Fixed in PR #58 (`fix-genome-bloat-under-tight-footprint`; open against `main` with CI green as of this writing, not yet merged).

## Symptoms

Running `python evolve_coaster.py --genome parts --max-width 10 --max-depth 20 --generations 250 --population 75 --rng-seed 7 --verbose --output <path>` consumed 96+ CPU-minutes and grew from 54MB to 288MB RSS without finishing. The same command with the library's default footprint, `--max-width 30 --max-depth 30`, finishes in well under a minute at the same generation and population count. Nothing crashed and no error was printed; the process simply kept running and kept growing.

## What Didn't Work

The first hypothesis was that the process had hung before the generation loop even started. Piping its stdout through `tail` and killing it with a plain `kill` (SIGTERM) showed zero output, including none of the `Gen N: ...` progress lines the loop prints every generation. That looked exactly like a process stuck before its first iteration. It wasn't: running the same command with `python3 -u` (the `-u` flag disables Python's output buffering) and redirecting to a real file rather than a pipe showed generation-loop progress from generation 0 onward, immediately. Python fully buffers stdout when it isn't attached to a terminal, and `kill` doesn't flush that buffer before the process dies, so the "zero output" was an artifact of the buffering and the kill method, not evidence the loop hadn't started. The process had been working the whole time.

Three functions were considered as the possible source of the runaway growth and ruled out by reading their code, since each one is provably bounded regardless of footprint:

- `_create_initial_population_parts()` in `rct2/evolution.py` (lines 378-403) builds the starting population one individual per while-loop iteration and always makes progress toward `population_size` -- nothing here can loop or grow without bound.
- `generate_random_track_parts()` in `rct2/mutations.py` (lines 684-736) picks `target_length = rng.randint(min_length, max_length)` at line 703, capping generated length at `max_length` (default 30) regardless of footprint; the function has no awareness of `max_width` or `max_depth` at all.
- `repair_circuit()` in `rct2/mutations.py` (lines 414-503) is bounded to at most `max_repair_segments * 2` (16) loop iterations (line 441) before giving up and returning `None` (line 503) if it still hasn't closed the circuit.

None of these three could explain unbounded growth across generations on their own. The actual mechanism was in how their bounded outputs interacted with fitness scoring over many generations, not in any one function running away by itself.

## Solution

The fix is in `WeightedProxyFitness.evaluate()` in `rct2/fitness.py`. Before the fix, the length reward was already capped at `ideal_length`, but the elevation, turn-balance, and variety rewards scored the entire segment list regardless of length. The current code, read at `rct2/fitness.py:190-237`, shows the fix as a single local variable introduced at line 224:

```python
# Elevation, turn, and variety rewards only count up to ideal_length,
# same as the length reward above. Padding segments beyond that point
# (e.g. from repair_circuit closing a loop) still contain hills and
# turns, so counting them here would keep rewarding a track for
# growing past ideal_length just as strongly as before it -- which
# made over_length_penalty too weak to ever outweigh them, and let
# genome length ratchet upward with no ceiling under a tight
# footprint, where more repair is needed to close the loop.
reward_segments = segments[: self.ideal_length]

# Elevation changes: reward hills
elevation_changes = count_elevation_changes(reward_segments)
score += elevation_changes * self.elevation_weight

# Turns: reward balanced turns (both directions)
left_turns = count_turns(reward_segments, direction="left")
right_turns = count_turns(reward_segments, direction="right")
score += min(left_turns, right_turns) * self.turn_balance_weight

# Variety: unique segment types used
unique_segments = count_segment_variety(reward_segments)
score += unique_segments * self.variety_weight
```

(`rct2/fitness.py:216-237`)

`reward_segments` is the same slicing pattern the length reward directly above it already used (lines 209-214): score the first `self.ideal_length` segments in full, and let anything past that point earn nothing from these three reward terms. `ideal_length` defaults to 80, per the class docstring at `rct2/fitness.py:124-128`, matching the median element count (82) across the 204 shipped designs in `data/calibration.csv`. Before this fix, a segment at position 200 in an oversized track earned exactly as much elevation/turn/variety reward as a segment at position 20; after it, that segment earns none, and only `over_length_penalty` (0.5 per segment past `ideal_length`, by default) responds to the track being that long.

## Why This Works

`repair_circuit()` is append-only by design: it copies the input list once (`result = segments.copy()`, `rct2/mutations.py:437`) and only ever `.append()`s or `.extend()`s corrective segments to close an open loop. It never removes anything from the original list. The comment at `rct2/mutations.py:726` states this directly: "repair_circuit only ever appends, never touches the existing prefix."

Every generation runs crossover and mutation on the population, and any offspring whose circuit doesn't close gets passed through `repair_circuit()`. Because repair can only grow a genome, never shrink it, track length across the population has a one-way ratchet: it can go up from repair, but nothing in the pipeline brings it back down.

A tight footprint makes that ratchet turn faster in two ways at once. With less room to maneuver, more offspring fail to close their loop on the first try and need repair at all, and each repair that does run needs more corrective segments to route the track back around a smaller available space.

Before this fix, that would have been survivable if fitness scoring pushed back against it, but it didn't. `WeightedProxyFitness.evaluate()` already capped its length reward at `ideal_length` with a small `over_length_penalty` beyond that (0.5 per segment by default). But the padding segments `repair_circuit()` appends still contain hills and turns, since the repair logic reaches for slope and turn pieces to close the gap. Those padding segments kept earning `elevation_weight`, `turn_balance_weight`, and `variety_weight` reward for every segment added, uncapped, which in practice outweighed the much smaller `over_length_penalty` by a wide margin. Nothing in fitness selected against runaway length, so the ratchet from repair never met resistance.

`WeightedProxyFitness.evaluate()` also calls geometry functions -- `track_bounds`, `occupied_tiles`, `overlapping_tiles` from `rct2/geometry.py` -- whose cost scales with segment count. So a genome that keeps growing directly explains both symptoms at once: more segments per individual means more geometry work per fitness evaluation (the growing per-generation time), and longer segment lists held by up to 75 individuals across up to 250 generations means more memory (the growing RSS).

This was measured directly with an instrumented reproduction at the exact failing parameters (seed 7, population 75, `ProxyFitness(max_width=10, max_depth=20)`). Before the fix, population-average segment-list length climbed from 38.6 at generation 0 to 97.3 by generation 68 and was still accelerating, with the largest individual passing 300+ segments; per-generation time rose from 0.875s to 2.65s over the same span, tracking the length growth almost exactly.

## Prevention

A new regression test, `test_padding_past_ideal_length_earns_no_elevation_turn_or_variety_reward` in `tests/test_fitness.py` (lines 265-295), guards directly against this recurring. It builds a `WeightedProxyFitness` with `ideal_length=5` and every penalty weight zeroed out except the three reward terms in question, then asserts that a track made of a 5-segment prefix plus 5 flat, featureless padding segments scores identically to the same prefix plus 5 segments of hilly, turning padding. If elevation, turn, or variety reward ever leaks past `ideal_length` again, this test fails.

Beyond that specific test, the general lesson: any reward term added to `WeightedProxyFitness` in the future that scales with segment count, the way elevation/turn/variety scoring did, should be capped at `ideal_length` from the start, or have an explicit, written reason why it shouldn't be. An uncapped reward that scales with length can silently defeat `over_length_penalty` no matter how large that penalty is tuned, because the uncapped reward grows with every added segment while the penalty is the only term working the other way.

Verification after the fix: the full test suite passes (400/400 via `python3 -m pytest -q`, confirmed in the current tree). Re-running the same instrumented reproduction (same seed, same tight footprint, population 75) after the fix showed population-average segment length plateauing around 50-58 across the tracked generations, oscillating rather than climbing, with per-generation time staying flat at roughly 1.4-1.6s instead of rising. The full 250-generation evolution at the original failing parameters, which previously never finished, completed and produced a valid 56-segment track (final fitness 292, well under the 80-segment `ideal_length` and nowhere near the 300+ segment runaway the bug used to produce), which exported to a `.td6` file and loaded successfully in the game.

## Related Issues

- [#58](https://github.com/joshgarlitos/generide/pull/58) -- the fix documented here (open, CI green, not yet merged as of this writing).
- [#43](https://github.com/joshgarlitos/generide/issues/43) -- the earlier issue that established `ideal_length`'s cap/penalty mechanism on the length reward alone (`ProxyFitness.ideal_length caps tracks at 50 segments; real coasters run to 89`). Still open; relevant to any future `ideal_length` tuning discussion.
- [#48](https://github.com/joshgarlitos/generide/pull/48) -- raised `ideal_length` from 50 to 80, the exact cutoff this fix now applies uniformly across all four length-correlated rewards.
- `docs/research-plan.md:52` and `docs/devlog.md:649` -- background on why `ideal_length` is 80.
- `docs/architecture.md:162` -- background on `repair_circuit`'s 8-segment budget (its append-only behavior, the other root-cause component here, isn't documented in architecture.md; see this doc's own "Why This Works" section instead).
