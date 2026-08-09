# generide devlog

A running record of decisions, surprises, and things I learned building this. Newest entries at the top.

---

## 2026-08-08 — The headless oracle works, and the flag in the game's own help is the wrong one

Ran the #6 spike. Verdict is go, and the full write-up is in [headless-oracle-spike.md](headless-oracle-spike.md). Two things are worth pulling out here.

### The documented way is the broken way

`openrct2 --help` suggests `host <park> --headless` for headless use, and it is the natural thing to reach for. It loads plugins fine. It also puts the game in network mode, where the park loads paused and `context.paused = false` throws `Game state is not mutable in this context.` The park sits frozen and `interval.tick` never fires once. Not a config problem — `pause_server_if_no_clients` was already false.

The `simulate` subcommand looked like the other obvious candidate, and it is genuinely fast: 500 ticks in 0.4 seconds, roughly 30x realtime. But a probe plugin under it printed nothing at all, and the source says why — `SimulateCommands.cpp` calls `gameStateUpdateLogic()` in a bare loop and never starts the scripting engine. It advances a park quickly and can tell you nothing about the result.

What works is the invocation with no subcommand at all: `openrct2 <park> --headless`. Plugins load, and a plugin can unpause itself. I would not have found that by reading the help text, only by testing all three and watching which one ticked.

### The cost is what decides the architecture

Speed 4 ("hyper") runs 318 ticks/sec against 40.7 at normal — 8x. Speed 8 is rejected outright rather than clamped, so 8x is the ceiling. Startup to plugin-running is 0.15s and amortizes across a batch, since one process can evaluate many candidates.

That puts a test lap on a ~30 in-game-second ride at about 4 seconds wall clock. A 50x100 run is 5,000 evaluations, so scoring every individual is 5.5 hours; scoring the top 10 of a run is 40 seconds. The roadmap already called for a hybrid of proxy-for-all and oracle-for-elites, and I had been treating that as a sensible design preference. It isn't — it's the only thing the measured number supports.

### Two traps for whoever implements this

Ratings come back x100 from the plugin API (652 is 6.52) and x10 from TD6 headers, where our own `RATING_PER_UNIT` is 0.1. Comparing the two without converting yields a clean 10x error that would read as a modeling failure rather than a units bug — the same shape as the `max_lateral_g` raw-byte mistake during #23, which is why it is called out in the doc.

And an unrated ride reports excitement `-1`, not 0. Feeding that into fitness unconverted would score an untested track as merely slightly bad rather than unmeasured.
## 2026-08-08 — First in-game reading of a CoasterRequest-targeted ride

Ran the new `CoasterRequest` path end to end and loaded the result in the actual game, not just through the simulator:

```
python evolve_coaster.py --fitness physics --max-width 15 --max-depth 15 \
  --target-excitement 5:7 --target-intensity 0:8 --target-nausea 0:5 \
  --generations 150 --population 60 --rng-seed 42 --output my_ride.td6
```

The physics-level stats held up well:

| Stat | Predicted | Game |
|---|---|---|
| Max speed | 17.5 mph | 18 mph |
| Drops | 2 | 2 |
| Airtime | 0.0s | 0.00s |
| Lateral g | 0.76 | 1.37g |

Drop count matching exactly is the #33 fix showing up in a real ride, not just a fixture test. Lateral g is off by more than the ~0.5g residual documented for #23's fit set, but that fit was tuned on 6 real designs, not a track this short and slow, so it's outside the range that fit was ever checked against.

The ratings were not close:

| Rating | Predicted | Game |
|---|---|---|
| Excitement | 3.91 | 0.25 |
| Intensity | 3.49 | 0.28 |
| Nausea | 2.77 | 0.19 |

This is not a new failure. It is the exact gap `RATING_WEIGHTS` already documents: the 204-design calibration set bottoms out at 0.3 excitement, this ride scored 0.25, and below the fitted range the model reads roughly 2-4 points high. It does here too, on all three ratings, within about half a point of that stated bound.

One reading is not enough to refit anything — the same section notes four prior in-game anchors barely moved a 204-row fit — but it is a second confirmation, on a target-range-driven ride rather than an open-ended one, that the actual gap is in `rate()`'s extrapolation below the shipped range, not in `simulate()`'s physics. That is the case #6 (headless OpenRCT2 as oracle) exists to close: enough of these readings to matter, gathered automatically instead of one manual load at a time.

---

## 2026-08-06 — A request is an object now, not scattered CLI flags

Issue #5 asked for a `CoasterRequest`: footprint, excitement/intensity/nausea ranges, cost range, all optional. Most of the scoring behind it already existed — `RatingTargets` and `PhysicsFitness`'s distance-from-window scoring landed earlier without anyone calling it that. What was missing was the object itself: one thing a caller builds that carries "what ride do I want" from the CLI into fitness, instead of five separate arguments that happened to line up.

`CoasterRequest` lives in `rct2/fitness.py` next to `RatingTargets`, and `PhysicsFitness.from_request()` builds a fitness function from one. `evolve_coaster.py` now constructs a `CoasterRequest` from its parsed args and hands it to `from_request` rather than assembling `RatingTargets` inline — the CLI is a caller of the same API a script would use, not a special case.

### The one field that doesn't do anything

`cost` is on the dataclass because the roadmap's vision names a cost range as part of the request. It is not scored. There is no per-piece price data anywhere in this codebase to score it against, and estimating one wasn't in scope here. `PhysicsFitness.from_request` silently ignores it rather than raising, which is worth being honest about: a caller who sets `request.cost` and expects it to shape evolution will not get that. Documented on the dataclass itself so it's visible at the point someone would reach for the field, not just here.

### What actually needed proving

The acceptance criteria wanted more than the dataclass compiling — "an evolution run constrained to a footprint produces a track that fits it" is a claim about selection pressure, not construction. `ProxyFitness` already penalizes out-of-bounds tracks per excess tile, but nothing before this checked that penalty was strong enough, over real generations of mutation and crossover, to actually hold a population inside a tight footprint rather than just discourage wandering past it. Ran it — 12x12 against a seed that starts well inside that box — across five RNG seeds before trusting it as a regression test, since one seed passing proves less than it feels like it does.

---

## 2026-08-06 — The drop counter wasn't wrong about height, it was wrong about what a drop is

Issue #23's g-force fix closed, but its sibling stayed open: on `generide-v6`, the game counts 2 drops and we counted 1, even though the drop height and speed we computed were both close to the game's numbers. That split — geometry right, count wrong — was the tell that this wasn't a threshold-tuning problem.

### Tracing the actual profile

The track's elevation, one point per segment: a climb from 0 to 10, then an unbroken-looking descent from 10 back to 0 with a flat stretch at 8 partway down. `count_drops` walked that as one continuous descent run and counted it once past `DROP_THRESHOLD_UNITS` (3 height units). Geometrically it is one drop. The game says two, which meant our definition of "drop" was wrong, not our arithmetic.

### What the game actually counts

Read `Vehicle.cpp` rather than guess from more samples, same as #23 and #32 before it. The real rule has no height minimum at all:

```cpp
else if (ted.flags.has(TrackElementFlag::down) && velocity >= 0)
{
    ...
    if (curRide->numDrops < Limits::kRideMaxDropsCount)
        curRide->numDrops++;
    ...
}
```

`numDrops` increments the instant the train enters a run of downward-sloped track elements — not when the run ends, and not gated on how tall it turns out to be. The run persists across consecutive downward elements and ends the moment a non-downward element interrupts it (`!ted.flags.has(TrackElementFlag::down)`). A flat plateau in the middle of a hill isn't a continuation of the same drop, it's a boundary between two.

Our own `DROP_THRESHOLD_UNITS = 3` was filtering out short runs entirely — on `generide-v6`, the first 2-unit descent before the plateau never cleared it, got silently reset to zero, and vanished from the count. The remaining 8-unit descent to the bottom was the only thing left to count, hence 1 instead of 2.

### The fix

`count_drops`'s logic in `simulate()` now increments on the transition into a downward run rather than accumulating height and checking it against a minimum at the end. No threshold, because the game has none. `highest_drop` and `total_drop_height` still accumulate per-run height for the rating features that use them — that part of the geometry was already correct, so it stayed.

### Confidence, and its limit

`generide-v6.td6` isn't a committed fixture (same situation as #23's fit designs), so the regression test reproduces the shape of the bug instead: a climb, a short descent below the old threshold, a flat plateau, then a longer descent, asserting 2 drops. That's real evidence the *rule* is now right, not evidence pinned against the exact game export. The next design that surfaces a drop-counting disagreement is worth turning into a committed fixture the way `manic_miner_test.td6` was for #23.

---

## 2026-08-02 — The g-force model was solving the wrong physics problem

Fixing the g-force overestimate turned out not to be a calibration problem. It was a modeling problem: we were computing real centripetal physics for a game that does not use real centripetal physics.

### What the old model did

Vertical g through a slope transition was `v²/(radius·g)`, with the radius derived from a single track piece's own tile length and its angle change. Standard mechanics. On a real ride it read two to four times too high, and not by a consistent ratio, which ruled out a simple scale-factor fix. The two designs closest to flat were nearly exact; the ones with real hills were the worst offenders.

### What the game actually does

I pulled OpenRCT2's real `Vehicle::GetGForces()` from source instead of continuing to guess at the shape of the error. It is:

```cpp
gForceVert += abs(velocity) * 98 / vertFactor;
```

Velocity to the first power, not the second. `vertFactor` is a lookup value that varies continuously through each track piece, baked into the game's original 1999 data per piece type. There is no radius anywhere in it.

So the old model wasn't a bad estimate of the right thing. It was a correct implementation of the wrong thing. RCT2's ride physics were built from measurement and hand-tuning, not from a coaster textbook, and no amount of scaling a `v²` term was ever going to fit a `v¹` game.

### The fix, and what it needed

We don't have the real `vertFactor` tables. Extracting them would mean pulling per-piece, per-progress values for dozens of track types, well past the scope of this fix. So the fix keeps our own geometric shape factor (angle change over arc length, doing the job `vertFactor` does in the real game) but corrects the exponent: linear in speed, with a constant fitted against real designs standing in for the game's own per-piece constant.

Fitting needs real segment lists, which narrows the calibration set hard: only 7 of the 204 shipped designs use exclusively pieces our segment table knows, and one of those seven had to come back out. Doubledrop's real export carries zero chain-lift indices, our simulation nearly stalls it climbing out of the station as a result, and a corrupted speed trace would have quietly bent the fit to explain an unrelated bug. Six designs and eighteen numbers (three g-axes each) is what the fit actually rests on.

I found the exclusion by generalization-checking rather than assuming it was safe. Before trusting the fitted constant, I ran it against `manic_miner_test.td6`, the one design that's actually committed to this repo and was not part of the fit at all. It landed within the same error band as the six it was tuned on, which is the evidence that mattered: a coefficient that only reproduces its own training data proves nothing.

### The bug the check caught

Partway through, the fixture check disagreed badly with the fit on lateral g — predicted three times the real value on a ride the coefficient should have handled well. Tracing it down, my fitting script read `Ride.max_lateral_g`, which is the *raw stored byte*, not `max_lateral_g_force`, the converted value. I had fit a coefficient against integers like 4 and 5 as though they were already g-forces. Checking against a second, independent source of truth is what surfaced it. Fitting against the seven designs alone would have looked internally consistent and been wrong in exactly the silent way a bad scale factor always is.

### Where it landed

Against the six real designs in the fit: positive vertical g within about 0.2g (was 2-4x high), lateral g within about 0.5g (was 3-4x high). Negative vertical g improved from being 2-6x too deep to about 0.3-0.4g too shallow, better, but the one axis still visibly off, and left that way rather than chased further on a six-design sample.

Checked against our own rides, which were no part of any fit: v6's positive g went from 2.94g predicted (37% high) to 1.92g (11% low) against a real 2.15g.

### What's still not fixed

Negative g's remaining gap, and the segment-vocabulary limit that held this fit to six designs. More of our own rides measured in-game is what would let this get tighter, same as every other calibration effort this week — the game doesn't ship rides in the range ours occupy, and it doesn't ship us a wider variety of track pieces than 46 of them either, at least not ones we can read yet.

---

## 2026-08-02 — Fitting the rating model, and finding out where the data runs out

The rating weights are now fitted against 204 real track designs instead of being nine numbers somebody typed once. The headline number: ranking correlation against the game's real ratings went from 0.45 to 0.87 for excitement. But the more useful finding is where the fit stops working, and why.

### What was actually broken

Two things, and only one of them was the weights.

The base constant was 2.9. Every ride started there before a single measurement was added, and plenty of real rides never reach 2.9 in total. So the formula could not express "this ride is bad."

The bigger problem was structural. The old `rate()` subtracted from excitement whenever intensity passed a cap of 10. Our intensity readings were wildly inflated, so on the real Manic Miner it returned 21.7 against the game's 6.5, the cap fired, and a genuinely good coaster came out at 0.10 excitement. Every hill and every bit of speed pushed intensity up, tripped the cap, and cost excitement. That is the mechanism that taught evolution to build flat, short, cautious tracks. It was not a tuning problem, it was a sign error in what the objective rewarded.

### Splitting prediction from preference

The fix that mattered most was not a number. `rate()` now predicts what the game would say and nothing else, with the three ratings computed independently the way the game computes them. Wanting to avoid punishing rides is a preference about which tracks we like, so it moved into `PhysicsFitness` where the other preferences live.

That separation is the same shape as the buildable-versus-runnable split from last week. Mixing "what is true" with "what I want" inside one function meant a bad estimate of the first silently corrupted the second, and there was no way to notice because both lived behind the same call.

### The fit

Least squares against `data/calibration.csv`, in the game's own units so each coefficient stays interpretable as points per mph rather than a compound of two conversions.

Inside the range the designs cover, it is decent: r-squared 0.73 for excitement, 0.85 intensity, 0.61 nausea. Given the game's own measured stats for Manic Miner it predicts 6.00 against an actual 6.10.

Ranking, which is what evolution actually consumes, improved more than absolute accuracy did:

| | fitted | old |
|---|---|---|
| excitement | 0.87 | 0.45 |
| intensity | 0.84 | 0.74 |
| nausea | 0.58 | 0.49 |

### Where the data runs out

This is the part worth remembering. Every ride generide has produced scores below 200 of the 204 shipped designs. Only one shipped design scores below 1.02. None score below 0.25.

So when the model is asked about our own output it is extrapolating past the edge of everything it learned from, and it reads two to four points high. I tried three model forms to fix that, including fitting through the origin and fitting in log space, and none of them extrapolated. Then I added our four in-game measured rides as training anchors and validated leave-one-out. That did not fix it either, which in hindsight is obvious arithmetic: four rows against 204 barely move a fit.

The honest conclusion is that the shipped designs cannot teach the model about bad rides, because the game does not ship bad rides. The only source of data in that region is our own tracks, measured in the game. Each one Josh tests is worth more than any modelling cleverness, because it covers territory nothing else does.

### What this does and does not fix

It does not make our predictions accurate. Feeding our simulated stats into the new weights still overestimates, because our g-forces read high, which is the same issue as #23 and is now cleanly separated from this one. The proof that the weights themselves are fine is that swapping in the game's own stats for the same ride lands within 0.1.

What it does fix is the direction of the objective. Evolution is no longer punished for speed and drops. On the same seed and settings that previously produced a 32-segment track topping out at 11.9 m/s, it now produces 78 segments at 18.9 m/s with more than double the drop height.

Whether that is actually a better ride is a question only the game can answer, which is the whole lesson of the last three days.

---

## 2026-08-02 — What the AI was good at, and what it couldn't do at all

This entry isn't about the coaster. It's about how I've been working, because the last two days made the division of labour clearer than anything else on this project has.

The short version is that the agent generated an enormous amount of verification and almost none of it found anything, while the three things that actually mattered all came from outside the code.

### The verification that didn't help

Over two days the agent ran the fitness function across 403 generated tracks to prove a refactor was score-identical, round-tripped all 204 track designs the game ships, built an 82-track corpus to check the stall screen against the physics model, and ran A/B tests across dozens of seeds. All of that was fast, careful, and correct. Almost none of it found a real problem.

It couldn't have. Every one of those checks was our code being compared against our code. The genetic algorithm was passing construction validation on 100% of runs while producing rides no train could finish. The fitness function was ranking coasters in exactly the reverse order the game does. The whole test suite was green the entire time, because the tests and the thing being tested shared the same wrong assumptions.

That's the part I want to remember. An agent can produce internal consistency in unlimited quantity, and internal consistency tells you nothing about whether your model matches reality.

### What did help

Three things moved the project, and all three were contact with something outside our own code.

I built a generated ride in OpenRCT2 and read the ratings window. That's what showed our excitement numbers were about 25 times too high and, worse, ranking rides backwards. It took two minutes.

I looked at the station and said the platform was too short. That turned out to be a track piece we had defined and never once emitted, and chasing it flushed out two more bugs that had been sitting there for weeks.

The agent read OpenRCT2's source instead of inferring the file format from samples. That fixed two byte offsets and a scale factor it had gotten wrong the day before while sounding certain.

### On how sure it sounds

The agent's confidence is least reliable exactly when it feels strongest, and the failure has a consistent shape: it does some inference, gets a tidy answer, and the tidiness reads as knowledge.

The clearest example was the g-force scale. It told me the value was "confirmed three independent ways." What it had actually done was compare the g-force the game displayed for *our* ride against the byte stored in *Manic Miner's* file. Two different rides. The numbers happened to land close together and it stopped looking.

So I've stopped reading confidence as a signal. What I read instead is whether it showed me a number that came from outside the code it was writing. A source citation, a screenshot from the game, a second derivation that doesn't share a code path with the first. When it says "verified" and the verification is its own code agreeing with its own code, that's not evidence.

The agent itself put the useful version of this well, when it graded its own checks by strength: two unrelated derivations landing on the same integer is strong, a physical floor that the wrong answer violates is strong, and a tight cluster of ratios is weaker than it looks because a wrong answer clusters too.

### Where it was genuinely good

Once I handed it a real data point, it was fast. From one screenshot it found the inversion, traced it back to the g-force model as the root cause, remembered the template file had stored ratings in it, found 204 more of them on my disk, and read the format spec to decode them. That's a lot of ground in one sitting, and it's exactly the kind of work where breadth and speed pay.

It was also good at things that are tedious enough that I'd have skipped them. Running the round trip against 204 files instead of the one fixture, which is how the element flag data loss surfaced. Tracing a station-handling assumption through three separate call sites. Re-deriving every number in a pull request description instead of taking them on trust.

So the split isn't the one I expected, where the machine does the boring parts and I do the clever ones. It's that the agent is quick inside a set of assumptions and structurally can't check the assumptions. Putting the thing in front of reality is the part I can't delegate.

### What I'd change

Front-load the reality check. Everything the agent built before I put a ride in the game was optimizing against a broken objective, and no amount of its testing would have caught that, because the objective and the tests agreed with each other. On this project that means a generated ride running in OpenRCT2 should gate further fitness work, not follow it.

The other thing worth naming is the category of decision where there's no fact to look up. Station length of 6 tiles was a judgment call and there's no derivation that produces it. Same with where the file belongs on disk, and with telling it that its explanations were hard to follow. It didn't push back on any of those, which was right. When there's no correct answer to find, it shouldn't be the one deciding.

---

## 2026-08-02 — Reading the format instead of guessing at it

The job was to decode the ride statistics stored in the TD6 header: speed, ride length, g-forces, drops, drop height, air time. The game writes all of that in when it saves a design, and we had been ignoring it.

The result matters less than the method, because I had already tried this the day before by inference and gotten two things wrong.

### What guessing produced

Yesterday I worked out the header layout by dumping six sample files and looking for byte patterns that moved sensibly. It felt convincing at the time. I found what looked like vertical g-force at 0x55 and 0x56, checked the values against two in-game screenshots, and told myself it was confirmed three ways.

Two of those conclusions were wrong.

Air time is at 0x4A, not in the 0x53 to 0x5A block where I had assumed the stats lived. And 0x57, which I had left as an unknown, is lateral g-force.

The g-force scale was wrong too, and the way it was wrong is worth writing down. I had compared the g-force the game displayed for *our* generated ride against the byte stored in *Manic Miner's* file. Different rides. The numbers happened to line up, so I called it confirmation. It was a coincidence dressed as evidence.

### What reading the source produced

OpenRCT2 defines the file layout as a C++ struct, `TD6Track` in `src/openrct2/rct2/RCT2.h`. Every field carries its offset as a comment and the struct ends with `static_assert(sizeof(TD6Track) == 0xA3)`, which is the same 163-byte header we have been round-tripping since Phase 1. Ten minutes of reading settled every offset, including the two I had wrong.

The scale factors were the other half. A stored byte of 62 means nothing until you know whether to divide by 10 or by 100. Those live in the T6 exporter and in `RCT12.h` as named constants: `kTD46RatingsMultiplier` is 10, `kTD46GForcesMultiplier` is 32, and the drop count is masked to its low six bits with `kRCT12RideNumDropsMask`.

### How to check a conversion when you have no ground truth

This is the part I want to remember, because it generalizes. A wrong scale factor produces numbers that look perfectly reasonable. There is no error, no exception, nothing to notice. So the question is how you check one without being able to see the right answer.

Three things worked, and they are not equally strong.

**Agreement between two unrelated derivations.** The shipped Manic Miner stores 70 in its drops byte. Masked the way the source says, that becomes 6. Our own physics model, which has never heard of the TD6 header, counts 6 drops walking that same track. Two routes to the same exact integer is the strongest check available, and it is the reason I believe the mask.

**A physical floor the wrong answer violates.** Under the correct scale, the gentlest shipped rides report 0.96g as their maximum vertical g. That is the 1g of sitting still, which is exactly what a flat ride should report. Under the scale I had guessed, the same rides report 0.75g, and no ride can have a *maximum* below the force you feel not moving. The wrong answer is not merely unlikely, it is impossible, which is what makes this check decisive.

**Ratio clustering, which is weaker than it looks.** Across five shipped designs we can simulate, our predicted top speed divided by the stored value times 2.25 mph lands between 1.05 and 1.10 every time. I was initially pleased with this. Then I noticed a wrong scale factor would also produce a tight cluster, just centred somewhere else. The clustering only tells me the relationship is linear and there are no outliers. What supports the scale is that the centre is near 1 rather than near 4. That is real evidence but it is softer than the other two, and the spec now says so.

The distinction matters for the calibration work coming next. When I start fitting rating weights against a few hundred real designs, "the numbers look plausible" is going to be the failure mode again.

### The one I did not finish

Air time has a conversion in the exporter, `(runtime * 123 + 512) / 1024`, but that converts into a runtime unit I could not pin down, so I do not know how many seconds a stored value represents. The community documentation says multiply by four, which would give our test ride 40 seconds of airtime on a Mine Train. Not believable.

So the field ships as a raw byte with no seconds conversion and a note explaining why. Shipping a number I could not defend would have been worse than shipping nothing, especially since the whole point of this exercise was to stop guessing.

### A bug that fell out of widening the test

Our round-trip test has always run against one fixture. Since I was touching the header, I ran it across all 204 designs the game ships instead. Only 139 came back byte-identical.

Every difference is in track element flag bytes, and every one is in bits 3, 4, or 5. Our element decoder reads four things out of that byte and ignores those three bits, so the encoder writes them back as zeros. We have been quietly losing data on any design that uses them.

I checked it was not mine by stashing the change and rerunning: 139 out of 204 before, 139 out of 204 after. Filed as issue #27 rather than folding it in.

The fixture round-trips cleanly, which is why this survived since Phase 1. A single test file told us the round trip worked, and it did work, for that file.

### The pattern, for the third time

Yesterday I told Josh the biggest lever on this project was not the model or the tooling, it was that I keep guessing at things I could read. Then this issue demonstrated it in the first ten minutes.

That is now three times. The header-gap trap in Phase 1, where the answer was in the file I already had. The completability split last week, where `create_simple_circuit` was sitting there as a counterexample the whole time. And now a format definition that is open source and searchable.

The failure is not laziness. Each time, inference produced an answer that looked right, and looking right is enough to stop looking. The rule I want is narrower than "read the source", because I do read things. It is: when the cost of being quietly wrong is high and an authoritative definition exists, go get it before writing code on top of a guess.

---

## 2026-08-01 — I put a ride in the game, and found out the fitness function was pointed backwards

I built a generated coaster in OpenRCT2 and read what the game thought of it. That is the first ground truth this project has ever had. It went badly, then worse, and then it turned into the clearest path forward I have had in months.

### The first real numbers

`generide-physics-7`, in the game:

| | our model | the game |
|---|---|---|
| Excitement | 5.88 | 0.24 |
| Intensity | 9.53 | 0.28 |
| Nausea | 6.78 | 0.19 |

About 25 times out.

The physics underneath held up much better. We predicted 11.6 m/s top speed against the game's 21 mph, which is 9.4, so roughly 23 percent high. Drop count and drop height were close. What was broken was the table that converts measured stats into ratings, which nothing had ever checked.

And the game was right. 616 feet of track, a 9 foot drop, no airtime. Excitement of 0.24 is an honest score for that.

### The station was never a platform

Two things looked wrong to me in the game. The boarding platform was only two tiles long, and there was a bare empty square beside it.

Both had the same cause. `MIDDLE_STATION` (0x03) has been defined in the segment data since the beginning and no code ever emitted it. Our station was `BEGIN` immediately followed by `END`, which is the shortest thing the format expresses and is degenerate: the game reserves station footprint with no middle piece to render on. The real Mine Train export uses `BEGIN, MIDDLE, MIDDLE, END`.

Default platform is now 6 tiles and settable with `--station-length`. Three separate places assumed exactly two pieces and would have chewed the middles back out. The one I would never have found by reading was in `evolution.py`: it checked whether element 1 was `END_STATION` and spliced one in when it was not, so on a track starting `BEGIN, MIDDLE` it inserted an END where a middle belonged. I only caught it because I regenerated a ride after fixing the other two and it still came out with a two tile station.

### Two bugs the longer station flushed out

Neither was caused by the station work. Lengthening the platform just made them visible.

**The physics fitness scored open circuits better than real ones.** `simulate()` walks the segment list once and reports `completed` when the train reaches the end without stalling. A short open stub does exactly that, because the station drives it the whole way. The only cost was one generic issue at `validity_weight`. So a station plus four flats scored -15.7 and a genuine closed circuit scored -53.2, and evolution converged on stubs.

A longer station made it worse by giving stubs more powered track, which is how it surfaced: physics-evolved tracks dropped to 2 of 5 construction-valid at mean length 20. `ProxyFitness` was unaffected the whole time, because its open circuit penalty is a flat 10000 rather than a graded weight. Giving `PhysicsFitness` the same took it back to 5 of 5 at mean length 37.6.

**The entrance and exit could be walled inside the track.** Placement was pinned one tile east of the platform no matter which way the loop ran, so any track curving east enclosed both structures and no guest could reach the ride. The seed circuit turns right, so it has been sealing in its own entrance since the day it was written. Placement now tries both sides and takes one that flood fills to open ground.

### The model was not just wrong, it was backwards

A second ride gave a second data point: the game said 1.02 excitement where we said 5.36.

Then I remembered something I should have checked in Phase 1. TD6 headers store the ratings the game assigned, and `data/sample_rides/manic_miner_test.td6` is a real export. The answer had been sitting in the repository the entire time.

| Ride | game excitement | ours |
|---|---|---|
| Manic Miner, real and hand built | 6.10 | 0.10 |
| generide-v3 | 1.02 | 5.36 |
| generide-physics-7 | 0.24 | 5.88 |

The game ranks those three in exactly the reverse order we do.

The mechanism is a chain. Our intensity reads about 3.3 times high, so on the real Mine Train it returns 21.7 against the game's 6.5. That blows past our `intensity_cap` of 10. The cap exists to slash excitement for punishing rides, so it fires, and a genuinely good coaster comes out at 0.10. Meanwhile a flat boring loop stays under the cap and scores 5.36.

So `PhysicsFitness` has been actively selecting against good coasters. Every drop and every bit of speed pushed intensity toward a threshold that destroyed the score, and over 150 generations the algorithm learned the lesson we accidentally taught it. The rides are not boring because the search got unlucky. They are boring because the objective was inverted and the search did its job well.

Worth recording that I got this wrong twice before getting it right. I first called the uncalibrated ratings a scaling problem, then a throttling problem. They were an inversion, which is a different and much worse thing.

### There are 204 answers sitting on the disk

The game ships 204 track designs inside the RCT Classic app bundle, and every one stores the ratings the game gave it.

We can simulate 7 of them. Our segment table knows 46 pieces; those designs use 193 we have never defined. I measured the payoff curve, and adding the 60 most common missing pieces still only reaches 49 of 204. It is a long tail.

### The header carries the stats too

The file stores more than the ratings. It stores what the game measured, which is the same set of numbers the in-game ratings window displays.

Bytes `0x55` and `0x56`, divided by 4, are the maximum positive and negative vertical g. Three independent checks agree: Manic Miner stores 8, giving 2.00g; the two in-game screenshots of our own rides showed 1.96g and 1.87g, which would store as 7 or 8; and across all 204 designs the values stay in a plausible range with the negative field always small and negative.

That matters twice over. It means the calibration data does not depend on simulating anything, so the segment vocabulary stops being a blocker. And it immediately explains the inversion:

| Design | game max +g | ours |
|---|---|---|
| Manic Miner | 2.00 | 5.01 |
| Penguin Paradise | 2.00 | 7.50 |
| Penguin Toboggan | 2.00 | 7.88 |
| Creaky Dips | 1.75 | 4.48 |

Our g-force model reads two to four times high. Inflated g produces inflated intensity, inflated intensity trips the cap, the cap destroys excitement. One bad number at the bottom of the stack inverted the whole objective.

### What changes

The roadmap said calibration waits on running OpenRCT2 headless. It does not. A few hundred real designs with real ratings and real measured stats are already on disk, and reading them is a parsing problem rather than an automation problem. Headless OpenRCT2 is still the right long term oracle for scoring new candidates, but it is no longer what stands between us and weights that mean something.

The immediate work, in order: finish decoding the header stat fields against the OpenRCT2 source rather than inferring offsets from six samples, fix the g-force model against real values, then fit the rating weights on the full set.

One lesson I keep paying for. This is the third time in this project that the answer was already inside an artifact I had, and I went looking for a way to generate the answer instead. The header gap trap in Phase 1, the completability split last week, and now a calibration dataset that shipped with the game. Read the file first.

---

## 2026-08-01 — Buildable is not runnable, and a fitness function that was lying

Two fitness bugs landed today. The first one had been quietly poisoning every evolution run. The second had never hurt anything, because nobody had used the broken code yet.

**The train that never finished.** Evolving with the default proxy fitness, population 30, 50 generations, produced tracks that passed construction validation every single time and completed their simulated circuit one time in ten. Ten seeds, one runnable coaster. The GA had been optimizing for something that looked like a coaster and could not be ridden.

The cause was a gap between two energy checks. `_energy_issues` flagged segments that climbed higher than the lift could carry the train, and nothing else. A train that ran out of speed on flat ground from accumulated friction was invisible to it, so `validate_construction` and `physics.simulate` disagreed about whether a ride could be completed, and fitness believed the wrong one.

**Why the obvious fix was wrong.** `_energy_issues` clamps its available-energy budget at zero, and that clamp looks exactly like the bug. Remove it and the flat-ground stall gets caught. It also fires on any flat track sitting at the datum, which flags `create_simple_circuit()`.

That seed is a flat, liftless eight-segment loop. OpenRCT2 builds it without complaint and no train can run it; the simulation stalls it at segment 5. It is also the GA seed and the fixture underneath most of the test suite. Folding a stall check into `.valid` would have made the project's own starting point illegal.

So the split I should have drawn months ago: `.valid` means the game would accept this track, and nothing more. Completability is a separate question owned by `physics.py`. For callers that have to stay physics-free, `construction.energy_stall_index()` carries the same energy accounting in height units as a cheap screen. It walks the train's kinetic energy as head with no floor, so friction death on the flat counts the same as failing to crest a hill.

**Calibration, and the thin margin I want on record.** Against the simulation over a corpus of evolved, random, and fixture tracks, the screen agreed 69 times out of 72, up from 51. More importantly it never passed a track that actually stalls. I re-ran that on a fresh 82-track corpus with different seeds and got the same shape: 76 agreements, zero unsafe passes, six tracks rejected that would have completed. Erring conservative is the right direction for a screen.

The part I do not love is how little room it has on real content. The real Mine Train clears the screen by 0.061 height units, which is about half a segment of coasting. The screen charges flat per-segment friction where the simulation charges per meter of arc length, so it overcharges straights and undercharges wide turns. A legitimate ride with a longer run-in to its lift hill could get falsely flagged. The clean fix is to share one arc-length model through `segments.py`. Writing it down here so I do not rediscover it by surprise.

Wired in as a graded penalty, the same shape the physics fitness already used for stalls, completion went from 1 of 10 to 10 of 10. Tracks also got shorter, 50.8 segments down to 28.8, because the proxy now trades length for runnability. That is a real change in what the fitness wants, and it means the proxy-versus-physics comparison I ran last week was measuring a fitness function that no longer exists.

**So I re-ran it, and the headline flipped.** Same ten trials, same settings:

| Metric | Proxy (before) | Proxy (now) | Physics |
|---|---|---|---|
| Completes circuit | 10% | 100% | 100% |
| Max speed (m/s) | 2.6 | 7.2 | 8.6 |
| Drops | 0.0 | 0.3 | 0.8 |
| Elevation changes | 4.4 | 7.3 | 11.2 |

The finding I called damning last week, that physics-evolved tracks beat proxy-evolved tracks on the proxy's own metric, is gone. Each fitness now wins on its own scale: proxy-evolved tracks score 123.5 under the proxy against 91.8 for physics-evolved ones, and physics-evolved tracks score 50.6 under physics against 45.7. That is what two genuinely different objectives should look like, and it is what the benchmark was built to detect.

The physics fitness still finds livelier rides, roughly twice the drops and half again the elevation changes. The difference is that it is no longer beating the proxy by exploiting a bug in it. It is winning on the axis it actually optimizes, which is a much less interesting result and a much healthier one.

Chasing this also turned up a small piece of waste. `ProxyFitness.evaluate` was resolving the chain lift set three separate times per call, once inside `validate_construction` and twice more afterward, when the first call already returns it. Fitness runs on every individual in every generation, so that class of thing compounds. Fixed by passing the resolved set through, verified behavior-neutral over 300 tracks.

**The second bug: a class that promised something it did not do.** `WeightedProxyFitness` is documented as proxy fitness with configurable weights for experimentation. It scored geometry only. No construction validation, no collisions, no slope or bank violations, no energy, no stalling. Tuning weights on it would have produced tracks the game rejects, and the results would not have transferred to the fitness the GA actually runs.

Nothing in the repo referenced it, which is exactly why it rotted. It was written as a convenience for experiments I never got around to running, and then `ProxyFitness` grew six penalties it never got.

The tempting fix was to copy the missing penalties across. That would have left two implementations of the same rules and guaranteed a repeat. Instead `WeightedProxyFitness` now holds the whole scoring implementation with every reward and penalty as a weight, and `ProxyFitness` is that class with the tuned defaults. One copy of the rules, nothing left to drift.

Before committing I checked the refactor against the old `evaluate()` body copied verbatim, over 403 valid and invalid tracks. Zero score differences. The test that matters most pins the two classes together so a term added to one and not the other fails the build, and I confirmed it is not vacuous by simulating that drift and watching it catch.

**Two things the tests taught me.** Writing a test that every weight actually reaches the score sounds like paperwork. It found two real things. Random track generation goes through the validator now, so it produces legal tracks and never exercises the slope or bank branches at all; those tests need hand-built broken tracks. And `missing_lift_penalty` can never fire. Scoring calls `estimate_energy_violations` with no lift set, so it falls back to `default_lift_indices`, which returns exactly the first hill's own indices, and then asks whether any of those indices is in that same set. Always true. It is dead code that has been sitting there looking like a safety net.

I left the behavior alone and wrote a test documenting it rather than pretending the branch was covered. It becomes reachable only if scoring starts accepting real per-segment lift flags.

**The lesson I keep relearning.** Both bugs are the same shape as the header-gap trap from Phase 1 and the `cosdeg` bug before it. Something is structurally correct and quietly incomplete, and the incompleteness is invisible until you check it against an independent source of truth. The round trip caught the first. The physics simulation caught this one. A fitness function with no second opinion will happily tell you it is doing great.

---

## 2026-07-26 — The benchmark that found a bug instead of an answer

`PhysicsFitness` worked, but nothing established whether it changed the search in a way that mattered. Maybe the physics model finds tracks the proxy would never reach. Maybe it finds the same tracks by a slower route. So I built `benchmark_fitness.py` to measure it.

**The design problem.** The two fitness functions score on incompatible scales, so comparing their raw numbers says nothing. What I wanted was cross-scoring: evolve a winner with each, then score every winner under both. If proxy-evolved tracks already score near the top under the physics fitness, the two are searching for the same thing. If they diverge, each is finding tracks the other misses. Both approaches get matched seeds so they start from the same random sequence and differ only in what they optimize.

**What it found was not what I was looking for.** Ten trials at 50 generations, population 30:

| Metric | Proxy | Physics |
|---|---|---|
| Completes circuit | 10% | 100% |
| Max speed (m/s) | 2.6 | 8.6 |
| Drops | 0.0 | 0.8 |
| Elevation changes | 4.4 | 11.2 |

Proxy-evolved tracks did not complete their circuit. One in ten. They passed `validate_construction` every time. The seed-42 winner was 56 segments spanning two height units, roughly a metre and a half of total elevation, stalling at segment 6 before the train ever reached its chain lift at segment 16. A flat oval with a bump in it. Max speed of 2.6 m/s is barely above the 2.2 m/s the lift pushes it out of the station at, and it never dropped at all.

I set out to compare two search strategies and instead found that the default one had been optimizing for unrideable track this whole time.

**Why the proxy settled there.** The penalty structure. An elevation change earns 5 points. An energy violation costs 50, and a missing first-hill chain lift costs 200. Hills are worth very little and risk a lot, so evolution found the safe local optimum: long, flat, twisty, and technically valid. The physics fitness rewards speed and drops directly, so it pushes into hills and collects the proxy's elevation points as a side effect.

That produced the result I found most damning at the time. Physics-evolved tracks beat proxy-evolved tracks **on the proxy's own metric**, 160.6 to 146.3. The proxy was losing at its own game because the thing it was avoiding was not actually the thing that makes a track bad.

**What I did not do.** I did not change either fitness function in this PR. It is a measurement script, and I wanted the measurement on record before touching the thing being measured. The obvious follow-up went in the notes: close the gap where `_energy_issues` calls a stalling track valid because it only checks climbs against the potential-energy budget and never a train that runs out of momentum on the flat.

Worth being honest about the limits of this. Everything here is measured by my own physics model, so it establishes that the proxy and the physics model disagree. It does not establish that the physics model is right. Building one of these flat proxy tracks in OpenRCT2 and watching whether the train actually stalls is what would confirm it, and that is still on the list.

---

## 2026-07-19 — A physics simulation replaces the geometric guesswork

The fitness function now simulates the ride instead of counting track pieces. A new `rct2/physics.py` walks the track with an energy-method velocity model, collects ride stats (max speed, drops, g-forces, airtime), and maps them to approximate excitement, intensity, and nausea ratings. A new `PhysicsFitness` class scores tracks on those ratings. This is the first half of the hybrid plan from the last Phase 4 entry: a cheap Python approximation during evolution, with headless OpenRCT2 as ground truth later.

**The model.** Segments carry integer RCT2 units, so the simulation converts once at the boundary and runs in meters and seconds: 3 meters per tile, 0.75 meters per height unit. The train leaves the station at chain lift speed (about 2.2 m/s). On lift segments the speed floor is the lift speed. Everywhere else the update is the energy equation: exit speed squared equals entry speed squared, plus twice gravity times the drop, minus a rolling friction term proportional to the segment's length. If speed falls below 1 m/s off-lift, the train stalls and the ride is marked incomplete, with the stall index recorded.

Segment lengths and turn radii don't exist in the segment data, so they're derived. Straight pieces get the hypotenuse of their run and rise. Turns get a radius from their displacement shape (5-tile quarter turns curve at about 2.5 tiles, 3-tile turns at 1.5), and unknown shapes fall back to a straight piece rather than raising, because the GA can propose anything. Lateral g is v squared over radius; banked turns absorb a fixed 0.67 g of it. Vertical g comes from slope angle changes between consecutive segments, approximated as an arc spanning the segment. That's the crudest part of the model, so it lives in one isolated helper that the calibration phase can replace without touching anything else.

**The ratings.** `rate()` maps stats to excitement, intensity, and nausea using a module-level `RATING_WEIGHTS` table shaped like OpenRCT2's per-ride-type contributions: base values plus weighted terms for speed, drops, g extremes, and airtime. The numbers are placeholders. The structure that matters is the penalties: intensity above 10 and lateral g above 2.8 slash excitement, which pushes the search away from rides that would rate as painful in the game. Calibration against the game is a data change, not a code change.

**The fitness.** `PhysicsFitness` implements the same protocol as `ProxyFitness`, which stays untouched and remains the default. It reuses `validate_construction` for penalties, then adds a graded stall penalty: stalling at segment 40 scores better than stalling at segment 5, so evolution has a gradient toward completing the circuit instead of a cliff. With no targets, it maximizes excitement minus overload penalties. With a `RatingTargets` argument, it scores linear distance outside requested (min, max) windows per rating, which is the interface the roadmap's "excitement above 6, intensity below 8" request will use. The CLI grew `--fitness physics` and `--target-excitement/--target-intensity/--target-nausea MIN:MAX` flags, and prints the winner's simulated stats and ratings.

**Lesson one: the fixture ride kept the model honest.** The first version stalled the real Manic Miner track three segments out of the station. Friction at 0.02 per meter ate the launch speed before the train reached the lift hill, because the model didn't know stations drive the train. Two fixes: station segments now act as powered pieces like the chain lift, and friction dropped to 0.01. This is exactly why the fixture test exists. A model that fails a ride the game runs fine is wrong, no matter how reasonable its constants look.

**Lesson two: the intensity cap bit my own test.** The rating monotonicity test asserted that a bigger hill always means more excitement. It doesn't. The bigger hill pushed intensity past 10, the cap kicked in, and excitement dropped below the smaller hill's. The model was behaving as designed and the test expectation was wrong. Good sign, actually: the penalty that's supposed to shape the search away from extreme rides demonstrably does.

**One performance note.** The first draft called `slope_state_at()` inside the simulation loop, which replays the track prefix every segment: quadratic in track length, multiplied by every fitness call in every generation. The state now steps incrementally through the loop. Fitness runs sit in evolution's hot path, so this class of mistake compounds fast.

**The numbers.** 147 tests pass, 13 of them new, covering energy limits (drop speed bounded by sqrt(2gh)), lateral g scaling with speed and shrinking with banking, drop counting, rating monotonicity below the caps, and the fixture ride completing with sane stats. A 30-generation run evolved a valid 38-segment track that completes its simulated circuit at 10.3 m/s max with approximate ratings of excitement 5.54, intensity 7.77, nausea 5.48.

**What's next.** Load an evolved track in OpenRCT2 and compare the game's ratings against the proxy's. That's the first calibration data point, and it will tell me how far the placeholder weights are from reality before any headless automation gets built.

---

## 2026-07-12 — Benchmark: evolution beats random search

The GA was producing better scores than the starting track, but that doesn't prove it's better than random generation at equal cost. I needed to know whether the complexity of crossover, mutation, and selection was earning its keep, or whether I could get the same results by generating a thousand random tracks and picking the best one.

**The setup.** Both approaches get the same evaluation budget: 1,000 fitness calls. Evolution uses a population of 50 over 19 generations (50 initial + 50×19 = 1,000 evaluations). Random search generates 1,000 tracks and keeps the best. Each approach runs 20 seeded trials, and the results get compared on mean fitness, median, range, and validity.

**The results.** Evolution wins decisively. Mean fitness is 143.3 for evolution versus -4,423.8 for random search. The random baseline is dragged down by open circuits, which get a -10,000 penalty. Evolution produces valid closed tracks 100% of the time (20/20 trials). Random search produces valid tracks 95% of the time (19/20 trials), and when it fails, it fails catastrophically.

Looking at just the valid tracks, evolution still wins. Its median is 137.5 versus 49.5 for random, and its minimum (109.0) is higher than random's median. The evolutionary process isn't just filtering out bad tracks. It's consistently finding better ones.

**Why evolution works here.** Random generation with repair can close a circuit, but it has no mechanism to improve beyond that. Evolution does. Crossover combines successful patterns from different tracks, and mutation explores variations on what already works. The repair operator helps both approaches, but only evolution uses the repair output as a building block for the next generation.

**What this means.** The GA is doing useful work. It's not just elaborately rejecting bad candidates. It's actively searching for better ones, and the tournament selection and elitism are preserving improvements across generations. That justifies the added complexity and makes further investment in the evolutionary approach worthwhile.

The benchmark script is committed at `benchmark_evolution.py`. Running it with different budgets, population sizes, or mutation rates will show where the tradeoffs sit, but the baseline comparison is clear: evolution earns its complexity.

---

## 2026-07-12 — Seeded RNG for reproducible evolution

The GA worked, but every run was a black box. If an interesting track evolved, I couldn't recreate it. If a bug appeared, I couldn't debug it. The backlog called for reproducible runs before investing in a benchmark, and that meant threading a seeded RNG through the entire pipeline.

**The change.** Every function that called `random.choice()`, `random.randint()`, or `random.sample()` now takes an `rng: random.Random` parameter. That covers `mutate()`, `crossover()`, `repair_circuit()`, `generate_random_track()` in `mutations.py`, and `_create_initial_population()`, `_tournament_select()`, `_create_offspring()`, `evolve()`, and `evolve_until()` in `evolution.py`. The CLI takes a `--rng-seed` argument. If you don't provide one, it generates a random seed and prints it, so any run can be recreated.

The pattern is mechanical. Add the parameter, replace `random.X()` with `rng.X()`, pass it down the call chain. The transformation took about an hour. The tests took longer.

**The tests.** Every test that called a random-using function broke. The fix was consistent: create `rng = random.Random(42)` at the top of each test and pass it to the function. The seed doesn't matter for individual tests; what matters is that the behavior is deterministic. I added a reproducibility test that runs `evolve()` twice with the same seed and asserts the `EvolutionStats` match exactly: same fitness, same history, same best individual.

**What it proves.** Two runs with `--rng-seed 123` produce identical output. Fitness, segment sequences, everything. That means debugging is now possible. If a track fails to place in OpenRCT2, I can recreate it. If a fitness score looks wrong, I can step through the exact same execution. The benchmark (issue #4) can now run fair trials where both the GA and random search see the same random sequence.

**What it doesn't solve.** Reproducibility across Python versions or platforms isn't guaranteed. Python's `random.Random` uses the Mersenne Twister, which is stable within a version but not contractually frozen across updates. For this project, that's fine. The goal is debugging and local comparison, not cryptographic determinism.

**The print.** The CLI prints the seed on every run, even when you don't ask for one. That line exists so you never lose an interesting result. If a track evolves with unexpectedly high fitness, the seed is right there in the terminal output. Copy it, rerun with `--rng-seed`, get the same track.

This unblocks the benchmark and makes evolution debuggable. Small change, high return.

---

## 2026-07-11 — Phase 4: The genetic algorithm learns to build real coasters

The GA is working. Tracks evolve, export to TD6, and load in OpenRCT2. Getting there required learning, the hard way, that RCT2's track system has rules the game enforces but never explains.

**The basic architecture.** Three new modules: `fitness.py` scores tracks without running the game, `mutations.py` handles insertions, deletions, replacements, and crossover, and `evolution.py` runs the loop with tournament selection and elitism. A CLI script, `evolve_coaster.py`, ties it together. The genome is just a list of segment IDs; the station segments stay fixed at the front, and the GA evolves everything after.

The first version worked on paper. Tracks closed, fitness improved over generations, the TD6 files saved correctly. Then I tried to place them in OpenRCT2.

**Lesson one: slope transitions.** The game rejected the track with "invalid height." Looking at the segment sequence, the problem was obvious once I knew to look: a `25_deg_up_to_flat` segment appeared right after a flat turn. That segment expects the track to already be climbing. You can't transition out of a slope you never entered.

RCT2 tracks have slope state. There are three: flat, up, and down. Certain segments require a specific state and produce a specific state. `flat_to_25_deg_up` requires flat and produces up. `25_deg_up` requires up and stays up. `25_deg_up_to_flat` requires up and produces flat. The GA was inserting slope pieces at random, which meant most combinations were illegal.

The fix was two parts. First, I added `count_slope_violations()` to the fitness function, which walks the track, maintains slope state, and counts every time a segment's requirement doesn't match. Heavy penalty per violation. Second, I changed the mutation operators to insert slope pieces only as complete valid sequences: `[flat_to_25_deg_up, 25_deg_up, 25_deg_up_to_flat]` as a unit, never the pieces individually. Delete and replace operations skip slope segments entirely to avoid breaking a sequence in the middle.

**Lesson two: the train needs to get up the first hill.** The next track placed successfully but the train rolled out of the station, lost momentum on the first climb, and rolled back. No chain lift.

In RCT2, chain lift is a per-segment flag, not a track-wide setting. The station segment can have it, but that only pulls the train through the station. The actual climb needs it too. I added logic to detect the first uphill sequence after the station and set `chain_lift=True` on every segment in that sequence.

**Lesson three: energy budget.** Even with chain lift on the first hill, some evolved tracks would valley: the train would drop into a low section and not have enough momentum to climb back out. The game doesn't calculate this for you. If your track goes down 10 units, across 50 segments, then back up 8 units, the friction losses might exceed what gravity gives back.

I added `estimate_energy_violations()`, which tracks elevation through the circuit. It records the highest point reached under chain lift, then checks every subsequent segment against the available energy budget, accounting for friction loss per segment. Any segment that climbs higher than the budget allows counts as a violation. The first hill having chain lift is checked separately; without it, the train has no energy to start with.

**Lesson four: bank transitions.** The last failure was subtler. The track placed, the train ran, but it looked wrong and the game complained about the layout. Banked turns were connecting directly to flat straights with no transition.

Banking works the same way as slopes. There's bank state: flat, left-banked, right-banked. A `banked_right_quarter_turn` requires right-bank state. A flat straight requires flat state. Going from one to the other without a `right_bank_to_flat` transition is illegal. The game lets you place it, but the track doesn't render correctly and the ride won't test properly.

I added `count_bank_violations()` using the same state-machine pattern as slopes, added `BANKED_SEQUENCES` to the mutation module (each one a complete flat-to-banked-turn-to-flat sequence), and updated mutations to only insert banked turns as full sequences. Same pattern, different state machine.

**Where the fitness function landed.** The proxy fitness now scores on track length (up to 50 segments), elevation changes, balanced left/right turns, and segment variety. It penalizes open circuits (-10,000), collisions (-50 per overlapping tile), going underground (-20 per unit below z=0), slope violations (-100 each), bank violations (-100 each), energy violations (-50 each), and missing chain lift on the first hill (-200). The penalties are heavy enough that no amount of positive scoring can overcome a fundamental physics violation.

The weights came from trial and error. Early versions penalized open circuits by only 1,000 points, and long tracks with lots of elevation changes would score higher despite not closing. Bumping it to 10,000 fixed that. The collision penalty needed to be high enough that self-intersecting tracks couldn't win on other merits but low enough that near-misses weren't catastrophic. 50 per tile ended up working.

**What I'd do differently.** The biggest time sink was the feedback loop: evolve, export, load in OpenRCT2, watch it fail, figure out why, fix the code, repeat. Each cycle took a few minutes and most of the failures weren't obvious from the error message alone. If I were starting over, I'd build a validation layer that catches all the game's constraints before evolution even starts, so the fitness function never sees an illegal track. Right now, the fitness function does double duty as both scorer and validator, which works but isn't clean.

**What's next.** The tracks are valid now, but they're not interesting. The fitness function rewards hills and turns but doesn't know what makes a coaster fun. The next step is either porting OpenRCT2's rating algorithm to Python (so fitness can target excitement/intensity/nausea directly) or automating the game to place tracks and read the ratings back. The second is harder but more accurate; the first is self-contained but might drift from what the game actually calculates.

For now, though: tracks evolve, tracks export, tracks run. Phase 4 is working.

---

## 2026-07-05 — Documentation, diagrams, and a design system

No code this session. I wrote down how the project works, for two audiences: myself, and whoever eventually reads about it on garlitos.com.

**The roadmap.** I wrote out the four phases and their done criteria in `docs/roadmap.md`. Nothing in there was new thinking, but putting it in one place made the shape of the project easier to hold. Phase 1 is done, Phase 2 is next, Phases 3 and 4 are still descriptions of what I want to get to.

**The RLE explainer.** I wrote `docs/rle.md` as a ground-up explanation of how RCT2's run-length encoding works, starting from what a bit is, building up through bytes and hexadecimal, and ending at the control byte mechanism. The format has two modes: a control byte below 128 means the next `c + 1` bytes are literal data; a control byte of 128 or above means the next byte repeats `257 - c` times.

Writing it out also gave us a chance to improve how the writing skill handles technical explainers. The first draft Claude produced opened with the mechanism. We caught that a reader who doesn't know what RLE is, what encoding means, or why RCT2 uses it at all gets no foothold from a control byte description. So we added a rule to the writing skill: technical explainers open with what the thing is and why it exists, then build down to the mechanics.

**The diagram.** I built an SVG of the two modes side by side using the Garlitos design system colors. It lives at `docs/assets/rle-diagram.svg` and is embedded in the RLE doc. The control byte is highlighted in olive, data bytes in warm grey, with an arrow showing what expands to what in output. I added dark mode support via CSS variables and a `prefers-color-scheme` media query inside the SVG. It only works when the SVG is inlined in HTML rather than referenced via `img`.

**Publishing structure.** I set up `docs/assets/` in this repo for source diagrams and `notes/assets/` in garlitos-site for anything that gets published. The workflow is manual. Write the doc here, copy the assets over when the note is ready to go live.

---

## 2026-06-27 — Design system

I built out a design system for the personal site using Claude Design, a separate tool from Claude Code. The process was to point it at the garlitos-site repo, let it read the codebase, and have it codify what was already there into a structured, reusable system.

The output is a set of CSS token files, reusable React components, foundation specimen cards, and a UI kit. The tokens capture the core of the brand: warm off-white paper background (`#fcfcfa`), deep olive for links and interactive elements (`#59670f`), chartreuse as a highlighter marker (`#d6f84a`), and system fonts throughout. No gradients, no shadows, no icons, no emoji. Square corners except for tag pills. Text sits on a 28px baseline grid.

The component set covers Link, Tag, Button, Breadcrumbs, ExperienceTimeline, and TopicCard. A Prose component was added to handle note body text, applying the site's type rhythm — 16px body, 1.7 line-height, hairline blockquote rule — consistently across any note. The UI kit is a click-through of the personal site: Home to Notes index to a note detail page and back.

The design system ships with a `SKILL.md` file, which makes it loadable as a skill in Claude Code sessions. The zip was extracted to `~/Projects/design-system/` so it's available across projects.

---

## 2026-06-26 — Phase 1 done. The round-trip is green.

`td6.py` is written and a real Mine Train ride decodes to a `Ride` object and re-encodes back to the same decompressed bytes. Sixteen tests passing. Phase 1 is closed.

The satisfying part: I didn't find the bug by running the code. I found it by *looking at the real file first*. Before writing a line of the decoder, I dumped the fixture's offsets in a REPL and confirmed everything the spec claimed — ride type 0x11, vehicle `AMT1`, 89 elements terminating at 0x155, 2698 bytes of remainder. All correct. But staring at it, I realized the spec's data model was quietly broken in a way that would have wasted an afternoon.

**The header-gap trap.** The spec's `Ride` dataclass names about 20 fields at specific offsets. But the header is 163 bytes (0x00–0xa2), and the bytes *between* the named fields — cost, the whole 0x08–0x4a stretch, G-forces — aren't stored anywhere. If `encode()` rebuilds the file from just the named fields, all those gap bytes vanish and the round-trip fails. The named fields are islands; the spec forgot the ocean.

The fix is the same move I already made for `remainder`: keep the raw 163-byte header blob on the `Ride`, parse named fields out of it for convenience, and on encode start from the raw header and overwrite only the named offsets. Opaque-by-default, parse what you need. As later phases understand more fields, bytes migrate from "covered by the blob" to "covered by a field" with no behavior change.

I'd internalized this lesson abstractly from the kevinburke `cosdeg` bug — "structure right, math wrong are separate questions." This was the same shape one level down: the spec's *structure* (which fields exist) was right, but its *completeness* (does it preserve every byte) was wrong, and that gap is invisible until a round-trip catches it. Verifying against the real artifact before coding is what surfaced it. That habit keeps paying for itself.

**On comparing decompressed bytes, not compressed.** Wrote that reasoning into the spec and the test comment last session; the test now leans on it for real. Our `compress()` packs runs differently than 1999-era RCT2 did, both correct, different bytes. Compare the data, not the encoding. Green.

Next is the interesting part: Phase 2, track segment geometry. Where the coaster stops being a byte array and starts being a shape in space.

---

## 2026-05-25 — Phase 1 halfway done, which is a weird place to be proud of

The RLE layer is done. Twelve tests passing, including a round-trip over a real exported ride file. I'm going to sit with that for a second, because "I wrote a decompressor" doesn't sound like much — but I had no official spec, just a community-maintained reference and a Go codebase to squint at, and the first time the round-trip test went green I felt like I'd cracked a safe.

Next is `td6.py`: the layer that turns decompressed bytes into a `Ride` dataclass and back. I already poked at the fixture in a Python REPL and confirmed the header fields parse where the spec says they should. The data's all there. Writing the actual decoder is the unglamorous mechanical work that makes everything else possible.

**What the file actually looks like**

`manic_miner_test.td6`: 3,110 bytes compressed. Decompress it and you get 3,040. Of those 3,040 bytes, only 342 are header and track elements — 89 of them, terminated cleanly at offset `0x155`. The other 2,698 bytes are entrance/exit geometry, scenery, and things I haven't figured out yet. Phase 1's answer to that is: store them as opaque bytes, write them back unchanged, don't touch them. A cowardly solution that happens to be correct for now.

The format has a very 1999 feel. `circuits_and_lift_speed` at offset `0xa2` packs the circuit count into the top 3 bits and the lift speed into the bottom 5. `control_flags` at `0x4b` is four booleans and a 3-bit load type in one byte. Every byte mattered back then. Parsing it is annoying. Understanding *why* it's packed that way is oddly clarifying — it tells you exactly what constraints the original engineers were solving for.

**The kevinburke bug**

The Go implementation I've been cross-referencing is kevinburke/rct. Its TD6 read/write structure is solid. Its geometry math has a bug that I almost missed: `cosdeg()` uses `math.Sin` instead of `math.Cos`. That's the kind of bug that compiles, runs, produces output, and makes every generated coaster geometrically wrong by exactly 90 degrees in every direction. No crash. No error. Just a coaster that is quietly, consistently incorrect.

I'm not porting that function. The segment data tables in the repo are fine — those I'll use. The math gets re-derived from scratch.

The rule I'm taking from this: when you're reading a reference implementation, "the structure is right" and "the math is right" are separate questions. They can come apart, and when they do, the bug is invisible until you already built something on top of it.

**Why round-trip before generating**

I could skip to generating coasters. It's the interesting part. But if I do and something's wrong, I have no idea whether the bug is in the generator, the encoder, or the geometry — and debugging all three at once sounds like the worst week of my year. So: prove the format layer works first, then build on top of something I trust.

This adds a phase that looks like delay. It isn't.

**The checksum I'm deliberately not solving yet**

The last 4 bytes of every `.td6` are a checksum. Phase 1 ignores them — strip on read, skip on write, compare decompressed bytes in the tests. OpenRCT2 will reject any file with a bad checksum, which means Phase 3 (loading a generated coaster in-game) doesn't work until I reverse-engineer the algorithm. The OpenRCT2 source is open. I'll find it when I need it. Solving it now would be solving it for no reason.

**Up next**

`rct2/td6.py` and `tests/test_td6.py`. Phase 1 done means one test passes: decode the fixture, re-encode it, assert the decompressed bytes match. Then Phase 2: track segment geometry, which is where things get actually interesting.

---

*This log is the raw record. The README is the polished "what and why." The portfolio page, when it exists, will tell the arc for a broader audience.*
