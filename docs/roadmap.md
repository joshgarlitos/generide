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

One gap remains. The mutation operators still carry their own copies of the rules and only insert slopes and banked turns from a small list of pre-built sequences. Steep slope pieces are defined in the segment data but no mutation can ever produce them, so the algorithm cannot discover a steep drop. I want mutations to ask the validator what is legal at a given point in the track and insert any segment that fits, which keeps every offspring buildable and opens up the full piece vocabulary.

The benchmark (issue #4) is now unblocked. It will compare the genetic algorithm with random generation using the same amount of work and the same random sequence. This matters because "the score went up" is not enough; I want to know whether evolution is finding better rides than chance.

A small track renderer supports visualization. A top-down drawing of the occupied tiles, colored by elevation, plus a fitness curve per run, means I can see what a track looks like without loading the game, and every experiment produces figures I can use in the devlog.

## Next: teach it what makes a ride good

Today, fitness is an educated guess based on track length, hills, turns, and variety. That helps produce coaster-like shapes, but it is not the same calculation the game uses.

The next major capability is evaluating excitement, intensity, and nausea. There is a catch in how the game computes these. Ratings are not a function of the track layout alone. The game runs a test lap and derives the ratings from stats it gathers along the way, like maximum speed, g-forces, and drop count. Reproducing the ratings in Python therefore means reproducing the physics simulation too, and keeping it in sync with a game that is still being developed.

So the plan is a hybrid. A cheap physics approximation scores every track during evolution, and OpenRCT2 running headless acts as the source of truth for the best candidates. The game's headless mode and plugin API should make it possible to place a track, run the test, and read the ratings back without automating the UI. I can use known rides to check both against reality.

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
| Benchmark GA vs random search | Next |
| Optimize for actual game ratings | Planned |
