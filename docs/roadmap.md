# Roadmap

## The vision

In **generide**, I am building a tool that generates roller coasters for RollerCoaster Tycoon based on parameters such as the space the ride needs to fit within, the ride ratings I want it to hit (such as its level of excitement), and a target cost range. The generated coaster should work in the game.

The game scores rides for excitement, intensity, and nausea. The goal is not to create the biggest possible numbers. It is to generate a ride within a requested range, such as exciting but not painfully intense, while keeping it inside a specific plot of land.

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

Buildable and runnable are now separate questions, which they had to become. `validate_construction` answers only whether the game would accept the track. Whether a train can actually get around it belongs to the physics model, with a cheap energy screen standing in wherever the simulation is too expensive to run. Before that split, tracks evolved by the default fitness passed construction validation every time and completed their circuit about one time in ten.

Still to do here: a small track renderer. A top-down drawing of the occupied tiles, colored by elevation, plus a fitness curve per run, would let me see what a track looks like without loading the game and give every experiment a figure I can put in the devlog.

## Next: teach it what makes a ride good

The default fitness is still an educated guess based on track length, hills, turns, and variety. That helps produce coaster-like shapes, but it is not the same calculation the game uses.

Half of the answer is built. `rct2/physics.py` walks the track with an energy-method velocity model, collects the stats a test lap would produce (maximum speed, drops, g-forces, airtime), and maps them to excitement, intensity, and nausea. `PhysicsFitness` scores tracks on those numbers and can target requested ranges per rating.

The other half is missing, and it is the half that makes the numbers mean anything. The mapping from stats to ratings uses placeholder weights that no one has checked against the game. Ratings in RCT2 are not a function of the track layout alone; the game runs a test lap and derives them from what it observes, so reproducing them in Python means reproducing the physics too, and keeping it in sync with a game that is still being developed.

So the plan is a hybrid. The cheap physics approximation scores every track during evolution, and OpenRCT2 running headless acts as the source of truth for the best candidates. That is no longer a guess: the spike in [headless-oracle-spike.md](headless-oracle-spike.md) confirmed a plugin can build a ride and read the game's own ratings back with no UI automation, and measured the cost at roughly 4 seconds per evaluation. That price is what makes the split mandatory rather than merely convenient — 4 seconds is unaffordable for every individual in a run and trivial for the handful of finalists.

Once that works, a user will be able to request something like:

```text
Fit inside 18 x 15 tiles
Excitement above 6
Intensity below 8
Nausea below 5
```

The algorithm can then evolve toward a specific kind of ride instead of a vague idea of "more coaster."

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
| Approximate physics simulation and ride stats | Complete |
| Completability separated from buildability | Complete |
| Headless OpenRCT2 oracle feasibility spike | Complete |
| Calibrate ratings against headless OpenRCT2 | Next |
| Track renderer and per-run plots | Planned |
| Accept a request with footprint and rating targets | Planned |
