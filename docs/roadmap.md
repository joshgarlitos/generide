# Roadmap

This page covers the roadmap for generide. It breaks the plan out into the key phases and the related success criteria for each phase.

## Goal

The goal is to generate coasters that behave well inside OpenRCT2's own mechanics and fit the constraints I hand the algorithm.

There are two key constraints:

1. A bounding volume. I give the generator a footprint and a height ceiling, and it builds a coaster that fits inside them without overhanging the plot or going over the height limit.
2. A target range for the ride ratings. The game scores every ride on excitement, intensity, and nausea, so I can tell the generator the envelope I want, like excitement above some floor and intensity and nausea under some ceiling, and it evolves toward that.

With both constraints in place, generide works as a generator I can configure for each run. I give it a space and a target rating range, and it hands back a valid `.td6` that the game loads and rates inside those bounds. The ratings are numbers the game computes on its own, so the algorithm has a concrete target to optimize against.

## Approach

I'm building bottom-up, one module at a time, each one testable on its own. The alternative is to generate a coaster first and then try to work out whether the bug is in the generator, the format encoder, or the geometry, which sounds like the worst week of my year. So the format comes first, then the geometry, then authoring a coaster by hand, then generation. Nothing higher up the stack gets built until the layer under it round-trips cleanly.

## Phases

### Phase 1: Format round-trip (in progress)

The goal here is to prove I understand the `.td6` format end to end. I decode a ride into Python, encode it back, and check that the bytes match. The RLE layer already round-trips an exported ride, and the TD6 decode/encode round-trips a Mine Train ride byte for byte, with 16 tests passing. What's left is closing out the remaining fields and running the whole fixture set instead of just the one ride.

Done when every sample ride in `data/sample_rides/` round-trips byte-identical through `rle.py` and `td6.py`, with the load-bearing fields asserted one by one so a silent corruption can't slip past a raw byte compare.

### Phase 2: Track geometry (complete)

Given a track piece, plus the track's current position and heading, work out where the next piece ends up. This is the layer that turns a flat array of bytes into a coaster with a shape in space.

Two of my references are unreliable. The community spec is mostly right but occasionally just wrong, and the Go implementation I'm cross-checking uses `Sin` where it means `Cos`, which rotates every coaster 90 degrees without ever failing loudly. So I'm deriving the geometry math from first principles and checking it against exported rides rather than porting it.

Done when I can walk an exported ride's track segments through `geometry.py` and the computed path closes its own circuit back at the station, within tolerance. If a coaster's geometry doesn't reconcile, I have it wrong.

All 89 segments in the exported Mine Train fixture return to the exact starting
position, elevation, and heading. Its 224 occupied cells have no exact 3D
overlaps, its calculated footprint matches the TD6 dimensions after rotation,
and the unified validator checks closure, known geometry, collisions, footprint,
height, and minimum elevation.

### Phase 3: Hand-authored coaster (not started)

Build a coaster in Python by hand, meaning I write the track out myself rather than generating it, then encode it and load it in OpenRCT2. This is the first time the whole stack runs forward instead of round-tripping, and the first thing worth showing anyone.

Done when the game opens the file as a valid ride, with no errors, and it stays on the map.

### Phase 4: Generator (not started)

This is where the constraints come in. A genetic algorithm evolves coasters against a fitness function built from the game's excitement, intensity, and nausea ratings, plus the two parameters I care about, the bounding volume the coaster has to fit inside and the target rating range it's aiming for. The game outputs the ratings, so the signal is computable. The work is shaping the fitness function and the genome so the search converges on valid, well-behaved rides.

Done when, given a space and a target rating range, the generator reliably returns valid, loadable coasters that fall inside both and beat a random baseline.

## Out of scope (for now)

Things I've parked so the current phase stays the current phase:

- Fitness tuning and genome design, which wait for Phase 4 (months out)
- Ride types beyond the first coaster type I get working
- A CLI or any UX wrapper, until there's something worth wrapping
- Visualizing coasters outside the game
- Speeding up RLE or geometry, unless a test is slow

## Status

| Phase | Goal | Status |
|------|------|--------|
| 1 | Round-trip a `.td6` through Python | In progress |
| 2 | Track segment geometry | Complete |
| 3 | Hand-author a coaster, load it in-game | Not started |
| 4 | Constraint-driven generator | Not started |
