#!/usr/bin/env python3
"""Generate a simple coaster TD6 file.

Usage:
    python generate_coaster.py [output.td6]

If no output path is specified, generates 'simple_coaster.td6' in the
current directory.
"""

import sys
from pathlib import Path

from rct2.generate import create_simple_circuit, generate_simple_coaster
from rct2.geometry import Position, track_bounds


def main():
    if len(sys.argv) > 1:
        output_path = Path(sys.argv[1])
    else:
        output_path = Path("simple_coaster.td6")

    # Show what we're generating
    segments = create_simple_circuit()
    bounds = track_bounds(Position(), segments)

    print(f"Generating coaster with {len(segments)} segments")
    print(f"  Bounds: {bounds.width}x{bounds.depth} tiles")
    print(f"  Output: {output_path}")

    generate_simple_coaster(output_path)

    print(f"Generated: {output_path}")
    print()
    print("To use in OpenRCT2:")
    print("  1. Copy to: ~/Documents/OpenRCT2/track/")
    print("  2. Open OpenRCT2, build a Mine Train ride")
    print("  3. Select 'Track Designs' and choose the design")


if __name__ == "__main__":
    main()
