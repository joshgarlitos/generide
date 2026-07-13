# generide devlog

A running record of decisions, surprises, and things I learned building this. Newest entries at the top.

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
