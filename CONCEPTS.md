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
