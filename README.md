# generide

**Procedurally generating roller coasters for OpenRCT2.**

I grew up sinking weekends into RollerCoaster Tycoon 2. Twenty-some years later, OpenRCT2 keeps the lights on. Same game, modern OS, no crashes when you accidentally summon 400 guests. What it doesn't have is an AI that builds coasters for you. So I'm writing one.

generide is a Python tool that emits `.td6` files — the format OpenRCT2 uses to save and share individual ride designs. The long-term plan is a genetic algorithm that evolves coasters players actually want to ride. The short-term plan is more humbling: convince the game that the file I just wrote is a real coaster.

## Where this stands today

Phase 1 was about reading and writing the binary format itself. Before I can generate a coaster, I have to prove I understand the format end-to-end. The cleanest proof is a round-trip — take a real `.td6` file, decode it into Python, encode it back, check the bytes match. If they match, I'm right. If they don't, I'm lying to myself. They match.

As of right now:
- RLE compression layer: **done**, round-trip tested over a real exported ride
- TD6 decode/encode: **done**, a real Mine Train ride round-trips byte-for-byte (16 tests passing)
- Geometry (Phase 2): done; the 89-piece Mine Train fixture passes unified validation
- Generation: not yet

## How it works

A `.td6` file is a Russian doll. Outer layer: a custom run-length encoding scheme RCT2 has used since 1999. Inner layer: a flat array of bytes at specific offsets — ride type at 0x00, train count at 0x4c, lift hill speed packed into the bottom 5 bits of 0xa2. Some fields are bit-packed because in 1999, every byte mattered. (In 2026, every byte still kinda matters, actually.)

The stack:

```
compressed .td6 file
       ↕  rle.py       ← custom RLE compress/decompress
decompressed bytes
       ↕  td6.py       ← byte offsets ↔ Ride dataclass
Ride object
       ↕  geometry.py  ← Phase 2: where does each track piece land?
Validated coaster
       ↕  generator    ← Phase 4: genetic algorithm
A coaster that doesn't fall off the map
```

Each layer is its own module, testable in isolation. I'm building bottom-up because the alternative — generate a coaster, then debug whether the bug is in the generator, the format encoder, or the geometry — sounds like the worst week of my year.

## What's interesting under the hood

**Reverse-engineering a binary format with no spec.** OpenRCT2 is open source, but the TD6 format itself was never officially documented. The reference I'm working from is community-maintained, mostly accurate, and occasionally just wrong. I'm cross-checking against a Go implementation (kevinburke/rct) that — and this is real — uses `math.Sin` where it means `math.Cos`. That kind of bug doesn't fail loudly. It just makes every generated coaster geometrically wrong by 90 degrees of rotation. I'm not porting that code.

**Custom RLE.** RCT2 has its own run-length encoding flavor: one control byte tells you whether the next chunk is literal data (up to 128 bytes) or a single byte repeated (2 to 129 times). Twenty lines of Python. Easy to write, easy to get off-by-one on, easy to verify with a round-trip test.

**A real GA problem buried in Phase 4.** What does "fun coaster" mean as a fitness function? The game itself outputs excitement, intensity, and nausea ratings, so there's a computable signal. But optimizing the GA against the game's own ratings is a different problem than optimizing for "would a human pay to ride this." That gap is the actual research question. Phase 4 is months away. I'm already excited.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

That's it. You don't need OpenRCT2 installed to develop — the test fixtures are real `.td6` files exported from the game and checked in under `data/sample_rides/`.

## Roadmap

| Phase | Goal | Status |
|-------|------|--------|
| 1 | Round-trip a real `.td6` file through Python | RLE done; TD6 in progress |
| 2 | Track segment geometry — given a piece, where does the next one land? | Done |
| 3 | Hand-author a coaster in Python, load it in-game | Not started |
| 4 | Genetic algorithm | Not started |

Each phase is gated on the previous one passing real tests, not on me feeling good about it.

## References

- [TD6 format notes](https://github.com/UnknownShadow200/RCTTechDepot-Archive/blob/master/td4.html) — community-maintained spec, mostly accurate
- [kevinburke/rct](https://github.com/kevinburke/rct) — Go implementation. Useful for file format scaffolding. Don't port the geometry math.
- [OpenRCT2](https://openrct2.io) — the open-source game this targets
- [docs/architecture.md](docs/architecture.md) — module-by-module breakdown for contributors
- [docs/phase1-spec.md](docs/phase1-spec.md) — the working spec for the current phase
