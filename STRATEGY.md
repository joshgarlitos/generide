---
name: generide
last_updated: 2026-09-07
---

# generide Strategy

## Purpose

An RCT2 ride's quality is set by the game's own scoring function, subject to hard constraints: footprint, buildability, what earns a high rating. No single source documents these rules — they're scattered across the game's source code and player knowledge, and some are specific to the player's own park. Building a good ride means understanding the game's scoring function, the constraints on the ride and the park, and the player's own preferences for what the ride should be.

## Positioning

Iterate quickly using the cheaper approximate score. When a number looks uncertain, verify it within the game so that time isn't spent building further on a wrong assumption.

## Users

**Primary:** RCT2 player (Josh, today) - hiring generide to build a ride that fits within the space and other constraints of their park, while maximizing the ride's "goodness."

<!-- Secondary: other RCT2 players, eventually. -->

## Boundaries

- Not building rides live, inside the game, right now - that's a different generation method than the genetic algorithm this runs today, worth exploring later.
- Not supporting ride types beyond mine trains right now - mine trains need to be nailed first.

_Resist a change when:_ it adds a new ride type or a new way of generating rides before mine train calibration and rendering are solid.

## Key metrics

- **Playable rate** - percent of generated tracks that are construction-valid and complete the circuit. Leading indicator of whether the pipeline can produce a ride at all; computed via construction.py and physics.py, not yet tracked as a running number.
- **Oracle-confirmed rating** - the real excitement/intensity/nausea rating the actual game gives the best generated track, via oracle.py. The real bar for "is this ride good"; not yet wired into a run, no measurement in place yet.
- **Rides played in a real park** - whether a generated ride actually gets placed and ridden in your own park. The final outcome metric; currently a manual gut-check, not tracked anywhere.

## Tracks

### Score calibration

Getting the proxy fitness, the physics checks, and the oracle's real ratings to agree with each other, so a high proxy score can actually be trusted without going to the game every time.

_Why it serves the approach:_ this is the direct engine of the approach - iterate cheap, verify in-game only when something looks uncertain.

### Rendering and fit

Turning a generated track into something you can actually see, confirm is well suited to your use case, and get into a real park - today that's render.py and the .td6 export, with an easier way to describe what you want as a future step inside this same track.

_Why it serves the approach:_ a high-scoring ride is only worth anything if you can tell it fits your park and actually place it.
