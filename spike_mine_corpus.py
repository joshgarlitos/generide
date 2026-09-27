#!/usr/bin/env python3
"""Spike: look for repeated multi-part design patterns in real Mine Train designs.

This answers one question before any pattern-library tooling gets built (see
docs/plans/2026-09-27-2229-feat-design-pattern-library-plan.md, R1): does the
shipped-design corpus actually contain recognizable, repeated structure above
the level of a single part, or is there too little data for that to mean
anything?

Read-only, like rct2/calibration.py: it never writes into the directory of
.td6 files, and it does not touch the genome or any part library. It only
prints what it finds so a human can look at the output directly.

A "part" here is exactly what rct2.mutations.segments_to_parts already
groups a flat segment list into (a maximal slope/bank run, or one bare
segment). A "window" is a short run of consecutive parts, described only by
each part's sequence of segment-type ids (never its absolute position), so
the same shape at a different height or offset still counts as the same
pattern. Windows of size 2 and 3 are what a pattern like "two lift-hill runs
separated by a turn" would show up as -- that pattern spans several parts,
not one.

Usage:
    python spike_mine_corpus.py /path/to/track/designs
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from rct2 import td6
from rct2.mutations import segments_to_parts

MINE_TRAIN_RIDE_TYPE = 0x11
WINDOW_SIZES = (2, 3)
TOP_N = 15


def part_shape(part: list[int]) -> tuple[int, ...]:
    """A part's sequence of segment-type ids -- the position-independent shape."""
    return tuple(part)


def windows(parts: list[list[int]], size: int):
    """Every consecutive run of `size` parts, skipping the station (part 0)."""
    body = parts[1:]  # part 0 is always the station; never part of a pattern
    for i in range(len(body) - size + 1):
        yield tuple(part_shape(p) for p in body[i : i + size])


def mine_design(path: Path) -> list[list[int]] | None:
    """Load one .td6 and return its parts, or None if it isn't a Mine Train."""
    ride = td6.load(path)
    if ride.ride_type != MINE_TRAIN_RIDE_TYPE:
        return None
    segments = [element.segment_type for element in ride.elements]
    return segments_to_parts(segments)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="Directory of .td6 files to scan (searched recursively)")
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    designs: list[tuple[Path, list[list[int]]]] = []
    failures: list[tuple[Path, Exception]] = []
    for path in sorted(args.directory.rglob("*.td6")):
        try:
            parts = mine_design(path)
        except Exception as exc:  # noqa: BLE001 -- corpus quality is unknown, log and continue
            failures.append((path, exc))
            continue
        if parts is not None:
            designs.append((path, parts))

    print(f"{len(designs)} Mine Train design(s) found under {args.directory}")
    if failures:
        print(f"{len(failures)} file(s) failed to parse and were skipped:", file=sys.stderr)
        for path, exc in failures:
            print(f"  {path.name}: {exc}", file=sys.stderr)
    if not designs:
        print("Nothing to mine -- no Mine Train designs parsed.")
        return

    for size in WINDOW_SIZES:
        counts: Counter[tuple[tuple[int, ...], ...]] = Counter()
        design_counts: dict[tuple[tuple[int, ...], ...], set[str]] = {}
        for path, parts in designs:
            for window in windows(parts, size):
                counts[window] += 1
                design_counts.setdefault(window, set()).add(path.stem)

        repeated = {w: c for w, c in counts.items() if c > 1 or len(design_counts[w]) > 1}
        print(f"\n=== {size}-part windows: {len(counts)} distinct, {len(repeated)} seen more than once ===")
        for window, count in counts.most_common(TOP_N):
            names = sorted(design_counts[window])
            print(f"  x{count} across {len(names)} design(s) {names[:5]}{'...' if len(names) > 5 else ''}: {window}")


if __name__ == "__main__":
    main()
