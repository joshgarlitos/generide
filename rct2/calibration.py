"""Extract a calibration dataset from real .td6 track designs.

Real designs carry the ratings and measured stats the game itself assigned,
which makes them ground truth for calibrating our proxy rating model against
(see docs/devlog.md, 2026-08-01). This module is read-only: it never writes
into wherever the .td6 files came from, and the files themselves are not
committed to this repo (they belong to whoever owns the game). Only the
extracted numbers, as a CSV, are meant to be checked in.

A design is skipped, not included with zeros, when it has no ratings — an
excitement of 0 means the game never rated it, not that it rated 0.
"""

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterator, Optional

from rct2 import td6


@dataclass
class CalibrationRow:
    """One rated real design: its measured stats and the ratings the game gave it."""

    name: str
    ride_type: int
    element_count: int
    max_speed_mph: float
    average_speed_mph: float
    ride_length_m: int
    max_positive_vertical_g: float
    max_negative_vertical_g: float
    max_lateral_g: float
    inversion_count: int
    drop_count: int
    highest_drop_height_m: float
    total_air_time_raw: int  # unconverted; see docs/phase1-spec.md
    excitement: float
    intensity: float
    nausea: float


def extract_row(path: Path) -> Optional[CalibrationRow]:
    """Extract one CalibrationRow from a .td6 file, or None if it has no ratings.

    Raises whatever td6.load raises on a corrupt or unreadable file; callers
    that are walking a large directory of designs of unknown quality should
    catch broadly around this call.
    """
    ride = td6.load(path)
    if ride.excitement == 0:
        return None
    return CalibrationRow(
        name=path.stem,
        ride_type=ride.ride_type,
        element_count=len(ride.elements),
        max_speed_mph=ride.max_speed_mph,
        average_speed_mph=ride.average_speed_mph,
        ride_length_m=ride.ride_length,
        max_positive_vertical_g=ride.max_positive_vertical_g_force,
        max_negative_vertical_g=ride.max_negative_vertical_g_force,
        max_lateral_g=ride.max_lateral_g_force,
        inversion_count=ride.inversion_count,
        drop_count=ride.drop_count,
        highest_drop_height_m=ride.highest_drop_height_m,
        total_air_time_raw=ride.total_air_time,
        excitement=ride.excitement_rating,
        intensity=ride.intensity_rating,
        nausea=ride.nausea_rating,
    )


def extract_directory(directory: Path) -> tuple[list[CalibrationRow], list[tuple[Path, Exception]]]:
    """Extract every ratable design under `directory` (recursive).

    Returns (rows, failures). A failure is a file that raised while loading —
    reported rather than silently dropped, since a directory of real game
    files can contain formats this parser doesn't handle (other TD versions,
    truncated files) and that is worth knowing about, not hiding.
    """
    rows: list[CalibrationRow] = []
    failures: list[tuple[Path, Exception]] = []
    for path in sorted(directory.rglob("*.td6")):
        try:
            row = extract_row(path)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            failures.append((path, exc))
            continue
        if row is not None:
            rows.append(row)
    return rows, failures


def write_csv(rows: list[CalibrationRow], out_path: Path) -> None:
    """Write rows to CSV, rounding floats to 4 places.

    The underlying values are exact multiples of small fractions (0.1, 0.32,
    0.75, ...), so the unrounded floats print as noise like 7.1000000000000005
    without carrying any real precision. Rounding makes the file readable
    without losing anything the source data actually had.
    """
    fieldnames = [f.name for f in fields(CalibrationRow)]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            record = asdict(row)
            for key, value in record.items():
                if isinstance(value, float):
                    record[key] = round(value, 4)
            writer.writerow(record)


def read_csv(path: Path) -> Iterator[CalibrationRow]:
    """Read a calibration CSV back into CalibrationRow objects."""
    field_types = {f.name: f.type for f in fields(CalibrationRow)}
    with open(path, newline="") as f:
        for raw in csv.DictReader(f):
            converted = {}
            for name, value in raw.items():
                declared = field_types[name]
                if declared is int:
                    converted[name] = int(value)
                elif declared is float:
                    converted[name] = float(value)
                else:
                    converted[name] = value
            yield CalibrationRow(**converted)
