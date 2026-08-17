# Roadmap

## The vision

In **generide**, I am building a tool that generates roller coasters for RollerCoaster Tycoon to a request set at generation time, not to a fixed target baked into the code: the footprint the ride has to fit within, target ranges for excitement/intensity/nausea, and a target cost range. Each of those is a parameter I can set tighter, looser, or leave open, per request. The generated coaster should work in the game regardless of what was asked for.

The game scores rides for excitement, intensity, and nausea. The goal is not to create the biggest possible numbers, and it is not to hit one specific number either. It is to generate a ride inside whatever ranges that request specifies, such as exciting but not painfully intense, while keeping it inside whatever plot of land was given.

## What works today

The project can read and write the game's track-design files, reconstruct a coaster's shape in three dimensions, detect basic geometry problems, and export new files with valid checksums. A real 89-piece ride closes exactly when traced through the geometry code.

It can also build a coaster from a Python list and evolve new layouts with a genetic algorithm. The algorithm keeps a population of designs, combines and mutates them, and favors the ones that score better. Generated rides have been loaded and run in OpenRCT2.

That proves the full path works:

```text
Python track -> validated layout -> game file -> working ride in OpenRCT2
```

## Now: prove evolution is doing useful work

Construction rules live in one place. `rct2/construction.py` checks circuit closure, collisions, bounds, slope and bank transitions, chain lift, and estimated energy, and generation, fitness, and export all use the same answer about whether a ride can be built.

Evolution is now reproducible. Every run has a seed, which the CLI prints whether you provide one or not. Two runs with the same seed produce identical results, which means interesting tracks can be recreated and failures can be debugged. All random-using functions take an `rng: random.Random` parameter instead of calling the global `random` module.

Mutations no longer carry their own copy of the rules. They ask the validator what is legal at the chosen point and insert any segment that fits, so every offspring stays buildable and the whole piece vocabulary is reachable. Steep slope pieces used to be defined in the segment data with no way for a mutation to produce one, which meant the algorithm could never discover a steep drop. It can now.

The benchmark answered the question it was built for. Evolution and random search each got 1,000 fitness evaluations across 20 seeded trials, and evolution won clearly: mean fitness 143.3 against -4,423.8, valid closed circuits in 20 of 20 trials against 19 of 20, and a minimum score higher than random search's median. Crossover and selection are doing real work rather than elaborately filtering bad candidates.

The bigger answer came on 2026-08-15, at 25 seeds and 2,000 evaluations per method. A track is now stored as a list of parts rather than a flat list of pieces, so cutting and joining two designs can never slice a slope run or a lift hill in half, and the lift hill itself is a fixed part every design carries rather than a structure the search has to stumble on. A typical run went from 0.92 to 4.33 on our port of the game's rating formula, and 25 of 25 runs now clear the game's drop-height threshold against 3 of 25 before. The real Mine Train reads 4.63 on that same port. Representation, not the objective or the parameters, was what had been holding the results back.

Buildable and runnable are now separate questions, which they had to become. `validate_construction` answers only whether the game would accept the track. Whether a train can actually get around it belongs to the physics model, with a cheap energy screen standing in wherever the simulation is too expensive to run. Before that split, tracks evolved by the default fitness passed construction validation every time and completed their circuit about one time in ten.

Still to do here: a small track renderer. A top-down drawing of the occupied tiles, colored by elevation, plus a fitness curve per run, would let me see what a track looks like without loading the game and give every experiment a figure I can put in the devlog.

## Next: teach it what makes a ride good

The default fitness is still an educated guess based on track length, hills, turns, and variety. That helps produce coaster-like shapes, but it is not the same calculation the game uses.

Half of the answer is built. `rct2/physics.py` walks the track with an energy-method velocity model, collects the stats a test lap would produce (maximum speed, drops, g-forces, airtime), and maps them to excitement, intensity, and nausea. `PhysicsFitness` scores tracks on those numbers and can target requested ranges per rating.

The other half is missing, and it is the half that makes the numbers mean anything. The mapping from stats to ratings uses placeholder weights that no one has checked against the game. Ratings in RCT2 are not a function of the track layout alone; the game runs a test lap and derives them from what it observes, so reproducing them in Python means reproducing the physics too, and keeping it in sync with a game that is still being developed.

So the plan is a hybrid. The cheap physics approximation scores every track during evolution, and OpenRCT2 running headless acts as the source of truth for the best candidates. That is no longer a guess: the spike in [headless-oracle-spike.md](headless-oracle-spike.md) confirmed a plugin can build a ride and read the game's own ratings back with no UI automation, and measured the cost at roughly 4 seconds per evaluation. That price is what makes the split mandatory rather than merely convenient — 4 seconds is unaffordable for every individual in a run and trivial for the handful of finalists.

Once that works, a user will be able to hand generide a request shaped like this — one example of an unlimited range of them, not a spec the code targets:

```text
Fit inside 18 x 15 tiles
Excitement above 6
Intensity below 8
Nausea below 5
```

Change any number, drop a range entirely, shrink the footprint — the request is the input, not a constant. The algorithm evolves toward whatever that request says instead of a vague idea of "more coaster."

## How the game and our own models divide the work

Our own scoring takes about 15ms a track and the real game takes about 4 seconds, so an approximation has to exist. But the things worth approximating are not all the same kind of thing, and treating them alike is what let two rides pass every check we had and then fail in the game on 2026-08-16.

Rules come first and are never approximated. The game will hand over its own table of all 350 track pieces, with each one's height change, displacement, footprint, arc length, and the flags we kept guessing at, including whether a chain lift is allowed on it. Most of `segments.py` and much of `construction.py` is a hand copy of that table. Importing it removes a whole category of error for free.

Whether a train gets round the track is simulated, and it deserves game time earlier than ratings do. A ride that stalls is worthless no matter how it scores, and our simulation is currently the weakest part of the project: it reported a ride complete that the game stalls on brake pieces it does not model.

The rating itself is the expensive one that the cheap-then-confirm plan was built for, and it stays that way.

Two things make the split compound rather than merely filter. The game's own measured stats come back with every oracle call and feed straight into calibration, so the fast model improves each time the slow one runs. And a few rejected candidates get sent to the game periodically, because if the fast model alone decides what the game ever sees, a systematic error there quietly shrinks the search space instead of showing up as noise.

Detail in [research-plan.md](research-plan.md).

## Later: make the results richer

After validation and ratings are reliable, the project can explore better mutation strategies, more track pieces, additional coaster types, faster parallel evaluation, saved evolution runs, and visual tools for understanding why a design passed or failed.

Presentation can grow too: names, colors, scenery, and batches of different finalists from the same request. Those enhancements become worthwhile once the generator can consistently produce rides that are valid, fit the available land, and match the experience the user asked for.

## Current status

| Area | Status |
|---|---|
| Read and write OpenRCT2 track files | Complete |
| Reconstruct and validate track geometry | Complete |
| Generate and run a new coaster in OpenRCT2 | Complete |
| Evolve coasters using approximate fitness | Working prototype |
| Shared construction validation | Complete |
| Reproducible evolution with seeded RNG | Complete |
| Benchmark GA vs random search | Complete |
| Validator-driven mutation across the full piece vocabulary | Complete |
| Part-based genome, so crossover can't split a run | Complete |
| Lift hill as a guaranteed part with a tunable height | Complete |
| Approximate physics simulation and ride stats | Complete |
| Completability separated from buildability | Complete |
| Headless OpenRCT2 oracle feasibility spike | Complete |
| Finish the oracle: chain lift, stall detection, measured stats | Next |
| Import the game's own track piece table and check ours against it | Next |
| Score evolution finalists with the headless oracle | Planned |
| Feed oracle results back into calibration | Planned |
| Model brakes and train length in the physics | Planned |
| Calibrate ratings against headless OpenRCT2 | Next |
| Track renderer and per-run plots | Planned |
| Accept a request with footprint and rating targets | Complete |
