#!/usr/bin/env python3
"""Spike: see what changed structurally at a run's biggest fitness jumps.

This answers the other half of the pre-tooling question (see
docs/plans/2026-09-27-2229-feat-design-pattern-library-plan.md, R2): using
only the run library's existing improvements.jsonl -- no new per-mutation
logging -- can a structural diff between consecutive best-tracks show
anything recognizable at the point scores jumped, or does it just look like
noise?

Read-only: it never writes into the run library, and it does not touch the
genome or any part library. It only prints a diff per jump so a human can
read it directly.

Usage:
    python spike_mine_run_history.py <run_id>
    python spike_mine_run_history.py /path/to/improvements.jsonl
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

from rct2 import runrecord

TOP_N = 10


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def load_improvements(target: str) -> list[dict]:
    """Accept either a saved run id or a direct path to an improvements.jsonl."""
    path = Path(target)
    if path.is_file():
        return read_jsonl(path)
    return runrecord.load_run(target).improvements


def part_shape(part: list[int]) -> tuple[int, ...]:
    return tuple(part)


def diff_parts(before: list[list[int]], after: list[list[int]]) -> str:
    """A short description of how one parts list became the next."""
    before_shapes = [part_shape(p) for p in before]
    after_shapes = [part_shape(p) for p in after]
    matcher = difflib.SequenceMatcher(a=before_shapes, b=after_shapes, autojunk=False)
    lines = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        removed = before_shapes[i1:i2]
        added = after_shapes[j1:j2]
        if op == "replace":
            lines.append(f"    replaced parts {removed} -> {added}")
        elif op == "delete":
            lines.append(f"    removed parts {removed}")
        elif op == "insert":
            lines.append(f"    inserted parts {added}")
    return "\n".join(lines) if lines else "    (same part shapes, no structural change visible at this grain)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", help="A saved run id, or a direct path to its improvements.jsonl")
    args = parser.parse_args()

    try:
        improvements = load_improvements(args.target)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: could not load improvements for {args.target}: {exc}", file=sys.stderr)
        sys.exit(1)

    if len(improvements) < 2:
        print(f"Only {len(improvements)} improvement(s) recorded -- nothing to diff between.")
        return

    jumps = []
    for prev, cur in zip(improvements, improvements[1:]):
        delta = cur["fitness"] - prev["fitness"]
        jumps.append((delta, prev, cur))
    jumps.sort(key=lambda j: j[0], reverse=True)

    print(f"{len(improvements)} improvements, {len(jumps)} jump(s). Largest {TOP_N}:\n")
    for delta, prev, cur in jumps[:TOP_N]:
        print(f"gen {prev['generation']} -> {cur['generation']}: fitness {prev['fitness']:.3f} -> {cur['fitness']:.3f} (+{delta:.3f})")
        print(diff_parts(prev["parts"], cur["parts"]))
        print()


if __name__ == "__main__":
    main()
