#!/usr/bin/env python3
"""Extract a rating-calibration dataset from real .td6 track designs.

Real designs carry the ratings and measured stats the game itself assigned.
This walks a directory of them (read-only — never writes into it) and writes
a CSV of the extracted numbers, which is what gets committed, not the .td6
files themselves.

Usage:
    python extract_calibration_data.py /path/to/track/designs -o calibration.csv
"""

import argparse
import sys
from pathlib import Path

from rct2.calibration import extract_directory, write_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory of .td6 files to scan (searched recursively)")
    parser.add_argument("--output", "-o", type=Path, default=Path("data/calibration.csv"))
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    rows, failures = extract_directory(args.directory)

    if not rows:
        print(f"Error: no rated designs found under {args.directory}", file=sys.stderr)
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(rows, args.output)

    print(f"Extracted {len(rows)} rated designs to {args.output}")
    if failures:
        print(f"{len(failures)} files failed to parse and were skipped:", file=sys.stderr)
        for path, exc in failures:
            print(f"  {path.name}: {exc}", file=sys.stderr)

    ride_types = sorted({row.ride_type for row in rows})
    print(f"{len(ride_types)} distinct ride types")
    mine_train = [row for row in rows if row.ride_type == 0x11]
    if mine_train:
        print(f"{len(mine_train)} Mine Train designs (0x11) — held out for validation, not fitting")


if __name__ == "__main__":
    main()
