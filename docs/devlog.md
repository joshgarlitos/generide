# generide devlog

A running record of decisions, surprises, and things I learned building this. Newest entries at the top.

---

## 2026-07-05 — Documentation, diagrams, and a design system

No code this session. I wrote down how the project works, for two audiences: myself, and whoever eventually reads about it on garlitos.com.

**The roadmap.** I wrote out the four phases and their done criteria in `docs/roadmap.md`. Nothing in there was new thinking, but putting it in one place made the shape of the project easier to hold. Phase 1 is done, Phase 2 is next, Phases 3 and 4 are still descriptions of what I want to get to.

**The RLE explainer.** I wrote `docs/rle.md` as a ground-up explanation of how RCT2's run-length encoding works, starting from what a bit is, building up through bytes and hexadecimal, and ending at the control byte mechanism. The format has two modes: a control byte below 128 means the next `c + 1` bytes are literal data; a control byte of 128 or above means the next byte repeats `257 - c` times.

Writing it out also gave us a chance to improve how the writing skill handles technical explainers. The first draft Claude produced opened with the mechanism. We caught that a reader who doesn't know what RLE is, what encoding means, or why RCT2 uses it at all gets no foothold from a control byte description. So we added a rule to the writing skill: technical explainers open with what the thing is and why it exists, then build down to the mechanics.

**The diagram.** I built an SVG of the two modes side by side using the Garlitos design system colors. It lives at `docs/assets/rle-diagram.svg` and is embedded in the RLE doc. The control byte is highlighted in olive, data bytes in warm grey, with an arrow showing what expands to what in output. I added dark mode support via CSS variables and a `prefers-color-scheme` media query inside the SVG. It only works when the SVG is inlined in HTML rather than referenced via `img`.

**Publishing structure.** I set up `docs/assets/` in this repo for source diagrams and `notes/assets/` in garlitos-site for anything that gets published. The workflow is manual. Write the doc here, copy the assets over when the note is ready to go live.

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
