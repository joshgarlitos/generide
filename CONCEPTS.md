# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Genetic Algorithm

### Genome
The sequence of track pieces encoding one candidate coaster design. Two representations exist: a *flat* genome is a plain list of piece IDs; a *parts* genome groups those same pieces into parts so that crossover always cuts between parts and never inside one. Every genome flattens back to the same canonical piece list before fitness scoring, construction validation, or export ever sees it.

### Part
One atomic unit of a parts genome: a run of same-kind pieces (a slope run, a bank run) or a fixed structural piece (the station, the mandatory lift hill) that crossover and mutation always treat as a whole, never splitting it.

### Individual
One candidate in the population: a genome plus the fitness score last computed for it.

### Population
The full set of individuals evaluated and evolved together within one generation.

## Fitness

### Proxy fitness
The fast, geometry-only scoring function used to rank every individual during search. It rewards properties like genome length, elevation changes, turns, and variety, and penalizes construction violations, without ever running the actual game. It stands in for a real in-game rating, which is too slow to compute for every individual in every generation.

### Genome bloat
The failure mode where genome length grows without bound across generations instead of settling near a target length. It happens when an operator that can only lengthen a genome, never shorten it, runs regularly, while fitness scoring puts no matching downward pressure on genomes past that target length — so nothing in selection favors a shorter genome over a longer one, and length ratchets upward generation after generation.

## Runs

### Run record
The saved account of one evolution run: the request that started it (constraints, seed, settings), one progress line per generation, the full track every time the best ride improved, the final track and its stats, and what happened to the result afterwards (real-game checks, installs). A rerun is a new run record that points back to the run it was copied from, so the two can be compared. Runs started from the CLI and from the web UI produce the same kind of record, one folder each in the run library (`~/.generide/runs/`), which is generide's own folder and separate from the game's. A record's status is running, completed, stopped (stopped early, best ride kept), failed (no buildable ride found), or interrupted (its process went away without finishing). Each run also has a name, numbered the way the game numbers a new ride ("Mine Train 3") until someone renames it.

## Ride views

### Isometric view
The picture of a ride drawn the way the game draws it: from a tilted angle, back to front, with rails, ties, and a support column under the track. It shows generide's own model of the ride, so a piece's slope follows the piece's name (a 25 degree piece draws at about 27 degrees), not the physics model's meters or the game's exact geometry. Every piece of a station is drawn in the station colour. It is a picture of one ride, not a view the viewer can move through freely.

### View angle
Which of four quarter turns the isometric view is drawn from. A turn rotates the whole ride about its centre, so turning four times returns to the first angle. Changing the angle changes only the picture, never the ride.

### Train
The row of cars drawn lapping the track in the isometric view. Its speed on each piece is the speed the physics trace gives, so it crawls up the lift and races down the drops. One lap always takes 20 seconds of picture time, whatever the ride's length, so the lap shows relative speeds and not real lap time. A train that cannot finish the circuit runs to the piece where it stalls and stops there, and the picture marks that spot.

### Track path
The line down the middle of the track, one per piece, running from the middle of the piece's entry edge to the middle of the next piece's entry edge. The isometric view draws its rails along it and the train rides on it, so the train is always on the track it is drawn on.

## Browser demo

### Page version
The stamp the browser demo's build puts on the page's own files and on the engine they run. When a visitor's browser holds an old copy of one while the other is new, the two stamps differ, and the page asks for a reload instead of starting a run that mixes the two.

### Ride bar
The minimum the browser demo's default ride has to meet: the track is buildable, its train finishes the circuit, and it has at least one drop.
