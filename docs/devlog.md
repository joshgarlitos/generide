# generide devlog

A running record of decisions, surprises, and things I learned building this. Newest entries at the top.

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
