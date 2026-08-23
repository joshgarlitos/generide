# Research plan: generating much better coasters

This document covers where the project stands as a search problem, why the
current approach plateaus, and the plan for testing better methods. It is
written to be picked up cold.

## Where we are

**Updated 2026-08-15.** A typical run now scores 4.33 on our port of the game's
rating formula, with the best at 4.60 and 23 of 25 runs above 4.19. The real
Mine Train shipped with the game reads 4.63 on that same port. Run-to-run
consistency, which used to be the biggest single loss, is largely fixed: every
one of 25 runs closes, completes, and clears the game's drop-height threshold.

One caveat sits over all of those numbers. The game itself scores that real
Mine Train 6.2, not 4.63, because three excitement-weighted bonuses are not
ported and they read the surrounding park rather than the track. Our numbers and
the reference are on the same ruler, so comparing them is fair, but the ruler is
short and it is our own. Nothing here has been checked against the game.

Success still means matching and then beating a real shipped coaster, measured
in the game itself rather than by our own estimate. What has changed is that the
in-loop estimate now says we are essentially there, which makes actually
measuring it the next thing that matters.

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

## How the game and our own models divide the work

Scoring a track with our own code takes about 15ms; scoring it in the real game
takes about 4 seconds. That 250x gap is why an approximation exists at all. But
"approximate everything cheaply, confirm the winners in the game" is too blunt,
because the things we could approximate are not all the same kind of thing.
Three tiers, and only the bottom two are worth approximating.

### Tier 1: rules. Import exactly, never model.

`context.getAllTrackSegments()` hands over the game's own table for all 350
pieces: each one's height change (`beginZ`, `endZ`), displacement (`endX`,
`endY`), slope and bank states, arc length, footprint, and flags including
`startsHalfHeightUp`, `allowsChainLift`, `isInversion` and `isBanked`. It also
gives `nextSuggestedSegment`, the game's own view of what naturally follows
what.

Not every rule is in that table, and assuming one was is how this section first
got written wrong. `allowsChainLift` is `true` for the 60-degree pieces, so it
does not encode the "Too steep for lift hill" rule at all; it distinguishes
pieces that can carry a lift in principle (slopes) from those that never can
(turns, brakes, stations). The steepness limit is applied when the piece is
actually placed, and it depends on the ride type.

The lesson is the same either way, and it points at a better tool than the
table. `context.queryAction` runs the game's full placement validation and
returns its exact error without building anything:

    25_to_60 with lift    -> error=2 "Too steep for lift hill"
    60_up    with lift    -> error=2 "Too steep for lift hill"
    60_up    without lift -> error=1 "Invalid height!"

So the authoritative way to know whether we may build something is to ask the
game to check it, not to replicate its rulebook. Derive per-piece legality by
querying once and caching, rather than transcribing.

Nearly all of `segments.py` and much of `construction.py` is a hand
transcription of rules the game will either state or check for us. Both of the
failures on 2026-08-16 were rules we had transcribed wrong or never known, and
both were free to ask about. Predicting an answer the game will give you is the
mistake, not the cost of asking.

This tier costs nothing at runtime once imported, so there is no reason to
approximate any of it, ever.

### Tier 2: does a train get round. Simulate, but check it far more often.

This needs a real test run, so it cannot be imported. It is also the weakest
part of the project: `physics.py` reported that a ride completes when the real
game stalled it three times on brake pieces it does not model at all.

Two properties make this tier deserve game time earlier than ratings do. It is
binary, so a track that stalls is worthless regardless of how it scores. And it
is not something a rating can compensate for. Spend oracle calls here before
spending them on excitement.

### Tier 3: the rating. Approximate, confirm on finalists.

This is the genuinely expensive one and the one the cheap-then-confirm pattern
was designed for. `ratings.py` scores every candidate during a run and the
oracle scores the handful that survive.

## Two additions that make the hybrid work

### Feed the game's answers back into the fast model

A hybrid that only reads the game's verdict at the end is a filter. A hybrid
that learns from it compounds. Every track the oracle scores is a calibration
point, and the oracle also returns the game's own `highestDropHeight`,
`maxSpeed`, `totalAirTime` and g-force maxima, which are exactly the quantities
`physics.py` estimates.

`calibration.py` currently learns only from 204 designs that shipped with the
game. Those are all good rides, built by people, and they are unlike anything
evolution produces. Our own failures are the more informative training data.

### Sample the rejected candidates, not only the winners

The failure mode a hybrid actually dies of: the fast model decides what the game
ever sees, so anything the fast model dislikes becomes invisible. A systematic
error there does not show up as noise, it silently shrinks the search space.

The insurance is cheap. Periodically send the oracle a few tracks the fast model
rejected. If the game likes what we threw away, the fast model needs work, and
we find out in an hour rather than after a month of runs converging on the wrong
thing.

### Cache game scores against the piece list

`benchmark.py` already saves the full segment list of every result rather than
just its score, so a saved run can be re-scored without redoing the search.
Keeping that property means every oracle call is paid for once. Re-running an
old comparison against a new model is then free.

## Build order

**1. Benchmark harness. Done, 2026-08-10.** `rct2/benchmark.py` and
`run_benchmark.py`. Name a method, a seed list, and an evaluation budget;
get back a results file with the full metric set; re-analyse later without
redoing the compute.

The buildable-and-completable gate and the diversity metric are in from the
start, as planned. Three methods are registered: `random` (rung 0), `ga`
(rung 1) and `ga_parts` (rung 2). Rungs 3 through 5 register the same way
once they exist.

The final judge became swappable on 2026-08-22. `judge_results` fills each
run's `real_*` columns from the headless oracle, `rescore` does it to a saved
results file without re-running the search, and the summary prints the game's
columns beside the ported model's. `run_benchmark.py --oracle` judges a fresh
run and `--rescore <file>` judges an old one. Both need a machine with
OpenRCT2 installed. Every number in this document still comes from the ported
model, because no comparison has actually been judged that way yet.

Run at the scale this plan calls for on 2026-08-15: 25 seeds, 2,000
evaluations, all three methods. Results in the rung table below and the
reasoning in docs/devlog.md.

**2. Headless oracle. Driver built and proven end to end 2026-08-15, callable
from the harness as of 2026-08-22.** Issue #42. `rct2/oracle.py` builds a
track piece by piece in a real headless game and reads the rating back (see
also `docs/headless-oracle-spike.md`), and `judge_results` points it at a
benchmark run.

Running it is the open piece, and it is what breaks the circularity the whole
plan is built around. It matters most right now because the part-based method
below scores within 0.03 of a real shipped coaster on the ported model, and
whether that holds up in the game is exactly the question the ported model
cannot answer about itself.

Three things are still unsettled. The oracle reads 3.12 for Manic Miner
against the 6.2 the game stored, and that gap is not explained. Batching many
tracks through one game process is worth doing and belongs behind
`score_track`'s interface. Determinism across repeat runs is unanswered from
the spike.

**3. Methods, cheapest first.** Run the cheap rungs even though the expensive
ones are more interesting, because they are the baselines that show whether
the expensive ones earn their cost.

| Rung | Method | What it tests | Result |
|---|---|---|---|
| 0 | Random legal tracks, keep the best | Whether any search beats none | 12% reliability, median E 0.44 |
| 1 | Current genetic algorithm | The baseline to beat | 100% reliability, median E 0.92 |
| 2 | Genetic algorithm over parts, not pieces | Whether representation is the problem | **Yes.** median E 4.33 |
| 3 | Build piece by piece with lookahead | Whether avoiding cut-and-join helps | not run |
| 4 | Same, with a learned guide | Whether learning beats plain search | not run |
| 5 | Full reinforcement learning | Whether a trained policy beats search | not run |

Rung 2 answered the question this plan was written to ask, at 25 seeds and
2,000 evaluations. Representation was the problem. Parts alone took the median
from 0.92 to 1.87; making the lift hill a mandatory part rather than something
the search had to stumble on took it to 4.33, with 25 of 25 runs clearing the
game's drop-height threshold against 3 of 25 before. See docs/devlog.md
(2026-08-15).

Rungs 3 through 5 are worth less than they were before this result, since the
cheap rung is now within 0.03 of a real shipped coaster on the in-loop scorer.
Verifying that against the game (step 2 above) comes first: there is no point
paying for a better search until we know what the current one is really worth.

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

Built on 2026-08-15 as rung 2 (`ga_parts`), using hand-defined parts: one
piece, or one whole pre-built slope run or banked turn. Parts alone took the
median from 0.92 to 1.87 against rung 1 at the same budget and fitness
function. Making the lift hill a mandatory part rather than something the
search had to stumble on took it to 4.33. Every one of those numbers comes
from the ported model, so the game has confirmed none of it yet.

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
