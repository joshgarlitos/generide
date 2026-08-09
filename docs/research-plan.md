# Research plan: generating much better coasters

This document covers where the project stands as a search problem, why the
current approach plateaus, and the plan for testing better methods. It is
written to be picked up cold.

## Where we are

The best tracks we generate score around 2 to 4.5 on our estimate of the
game's rating. A real Mine Train shipped with the game scores 6.2. Runs are
wildly inconsistent: with everything else held fixed, one random seed
produced a track with a 16-unit drop and another produced 2.

Success means matching 6.2 and then beating it, measured in the game itself
rather than by our own estimate.

## The core problem

A track is stored as a flat list of about 90 individual pieces. That is like
writing a sentence as a string of letters with no spaces. When the genetic
algorithm makes a new track, it cuts two existing tracks and joins halves
together. Those cuts land anywhere, including in the middle of a structure
that only works as a whole.

A lift hill is not something the code knows about. It is pieces 12 through 24
that happen to go upward. Nothing marks them as belonging together, so
nothing stops a cut landing inside one.

Two experiments on 2026-08-09 both failed for this reason:

- **Raising the repair budget** (how many pieces the code may add to reconnect
  a track after a change). Tried 8, 16, 24, 32. The default of 8 was best; every
  larger value was worse. Best guess is that a bigger budget lets more badly
  cut tracks get patched into something whole but shorter, instead of being
  discarded and the parent kept.
- **Seeding evolution from the real Manic Miner track.** Its 10-unit drop
  collapsed to 2 within 200 generations, across all three seeds. Drop count
  barely changed, but the height of the big drop did, which is what crosses
  the game's threshold. Starting from a good structure does not help when
  nothing protects that structure from being cut apart.

Two other changes did work and are committed: mutations can no longer dig
below ground, and `ideal_length` rose from 50 to 80 to match the shipped
designs' median of 82.

## Measurement comes first

None of the numbers produced on 2026-08-09 are trustworthy, for four reasons.
Fixing these matters more than trying another method.

**Too few runs.** Three seeds per setting, against between-seed variation
larger than any effect being measured. Twenty-five runs per setting is the
target. Each run is roughly 20 seconds, so 25 seeds across 5 methods is under
an hour.

**Confounded changes.** The repair budget sweep ran with the digging fix and
the length change already applied, so those effects cannot be separated now.

**Inconsistent budgets.** Runs used 120, 200, and 300 generations at different
points and were compared across those anyway. Budget should be counted in
track evaluations, not generations, because generations mean nothing across
methods that do not have them.

**Circular scoring.** We optimise our ported copy of the game's rating formula
and then report that same formula's opinion. This is how a configuration
scored 5.03 on tracks the game refuses to build.

### The measurement design

- **In-loop score:** the ported rating model in `rct2/ratings.py`. Fast enough
  to run on every candidate.
- **Final judge:** the real game, via headless OpenRCT2 (see
  `docs/headless-oracle-spike.md`). Roughly 4 seconds per ride, so it judges
  only the finalists of a run, never the whole population. This is what breaks
  the circularity.
- **Hard gate:** a track that is not construction-valid and does not complete
  its circuit gets no score at all. The run counts as failed. Reporting
  excitement on unbuildable tracks is the specific mistake that produced the
  5.03 result.
- **Budget:** equal number of track evaluations per method.
- **Seeds:** 25, reported as median and spread, never best-of-run. Best-of-run
  is what made weak results look real.

### Metrics to record

1. **Quality** — real game score of the best track.
2. **Reliability** — fraction of runs producing a track that clears all of the
   game's thresholds.
3. **Diversity** — are the outputs different rides or the same ride 25 times.
   Recorded from the start, because the goal is eventually many kinds of
   rides, and retrofitting this metric means re-running everything.

## Build order

**1. Benchmark harness.** Name a method, a seed list, and an evaluation
budget; get back a results file with the full metric set; re-analyse later
without redoing the compute. Every experiment so far has been a throwaway
script, which is why the results are hard to trust and impossible to
re-examine. Estimated two days.

Design it with the final judge as a swappable component, and put the
buildable-and-completable gate and the diversity metric in from day one.

**2. Headless oracle.** Issue #42. The harness needs a fast in-loop scorer
regardless, so starting with the ported model as the judge and swapping the
oracle in afterwards costs almost nothing, and re-running old comparisons is
cheap once automated.

**3. Methods, cheapest first.** Run the cheap rungs even though the expensive
ones are more interesting, because they are the baselines that show whether
the expensive ones earn their cost.

| Rung | Method | What it tests |
|---|---|---|
| 0 | Random legal tracks, keep the best | Whether any search beats none |
| 1 | Current genetic algorithm | The baseline to beat |
| 2 | Genetic algorithm over parts, not pieces | Whether representation is the problem |
| 3 | Build piece by piece with lookahead | Whether avoiding cut-and-join helps |
| 4 | Same, with a learned guide | Whether learning beats plain search |
| 5 | Full reinforcement learning | Whether a trained policy beats search |

## The two candidate redesigns

### Parts instead of pieces

Store a track as a list of parts — station, lift hill of a given height, drop,
turnaround, airtime hill, brake run — each of which knows how to build itself
out of pieces and what it can connect to. Cutting and joining then happens
between parts and never inside one, so a lift hill cannot be cut in half.
Mutation changes a part's settings or swaps one part for another.

This is the direct fix for the diagnosed problem, and it matches how real
coaster design works, in named elements rather than individual pieces. The
parts could be hand-defined or extracted from the 7 shipped designs we can
fully parse.

### Building piece by piece instead of editing

Start at the station and choose each next piece, rather than editing finished
tracks. Nothing gets cut apart because nothing is ever cut. Two things we
already have make this viable: `construction.py` lists legal next pieces at
any point, and the ported ratings score a finished track quickly.

Two hard problems:

- **Judging an unfinished track.** A rating needs a complete circuit, so a
  half-built track has no score. This needs partial credit for progress
  towards things we know matter (height gained, thresholds cleared), shaped so
  it provably does not change which final track is best.
- **Forcing the circuit to close.** Better to forbid moves that make closure
  impossible than to punish non-closure after the fact. At each step we can
  ask whether a legal path home still exists within the remaining budget,
  which turns an unlearnable sparse penalty into a shrinking menu of legal
  options.

Reinforcement learning is the heavier version of the same idea, where piece
choice is learned rather than searched. Our problem suits it unusually well
because we have a fast, exact simulator of the thing being optimised, which is
the condition that makes search-plus-learning work. It is still the last rung,
after the simpler version is exhausted.

### Keeping a shelf rather than a winner

Independent of the above. Instead of one population converging on one best
track, keep an archive of the best track in each category — tallest, longest,
most compact. Odd tracks survive long enough to be improved instead of being
killed off early for scoring badly today. This directly targets the run-to-run
inconsistency, and it produces the variety of rides the project wants
eventually while still identifying the best one.

## Open questions

- Whether the repair-budget result has a better explanation than the one
  guessed above. It was never verified.
- Whether lateral g being wrong on our own tracks (issue #41) distorts method
  comparison. Lateral g feeds the score directly, and we know it reads 0.76
  against the game's 1.37 on a real generated ride.
- Whether the 7 parseable designs are enough to extract a useful parts
  vocabulary, or whether that needs the segment vocabulary work in issue #25
  first.
