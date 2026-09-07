"""JSON-lines calibration log for oracle-sampled tracks.

Written by rct2.evolution's periodic oracle-calibration hook (see
docs/plans/2026-09-07-1611-feat-oracle-calibration-sampling-plan.md). Each
appended line is one oracle call's result -- or a synthetic `oracle_error`
record when the call itself raised -- so a crash mid-run loses nothing
already collected.

Deliberately independent of rct2.oracle: this module never imports it, and
accepts any object shaped like OracleResult (status/excitement/intensity/
nausea/detail/stalled_at_index/stalled_at_type/measurements) rather than its
type, so rct2.evolution's own lazy-import boundary around the oracle isn't
undone by importing this module.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class CalibrationRecord:
    """One oracle-calibration sample, one line in the log.

    Stores the full segment list, following rct2.benchmark.RunResult's
    precedent, so a saved record can be understood or re-checked without
    re-running the evolution that produced it.
    """

    role: str  # "best" | "worst"
    generation: int
    rng_seed: int
    timestamp: str  # UTC, ISO 8601
    segments: list[int]
    status: str  # "rated" | "stalled" | "timeout" | "placement_failed" | "oracle_error"
    excitement: Optional[float] = None
    intensity: Optional[float] = None
    nausea: Optional[float] = None
    detail: str = ""
    stalled_at_index: Optional[int] = None
    stalled_at_type: Optional[int] = None
    measurements: Optional[dict] = None
    error: Optional[str] = None  # set only for status == "oracle_error"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationRecord":
        return cls(**d)

    @classmethod
    def from_oracle_result(
        cls,
        role: str,
        generation: int,
        rng_seed: int,
        segments: list[int],
        result: Any,
    ) -> "CalibrationRecord":
        """Build a record from an `OracleResult`-shaped object.

        Accepts anything carrying the same attributes as
        `rct2.oracle.OracleResult` rather than that type itself -- see the
        module docstring.
        """
        measurements = (
            asdict(result.measurements) if result.measurements is not None else None
        )
        return cls(
            role=role,
            generation=generation,
            rng_seed=rng_seed,
            timestamp=_utc_now(),
            segments=list(segments),
            status=result.status,
            excitement=result.excitement,
            intensity=result.intensity,
            nausea=result.nausea,
            detail=result.detail,
            stalled_at_index=result.stalled_at_index,
            stalled_at_type=result.stalled_at_type,
            measurements=measurements,
        )

    @classmethod
    def oracle_error(
        cls,
        role: str,
        generation: int,
        rng_seed: int,
        segments: list[int],
        error: BaseException,
    ) -> "CalibrationRecord":
        """Build a synthetic record for a scorer/log_writer call that raised (KTD9)."""
        return cls(
            role=role,
            generation=generation,
            rng_seed=rng_seed,
            timestamp=_utc_now(),
            segments=list(segments),
            status="oracle_error",
            error=str(error),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_record(path: Path, record: CalibrationRecord) -> None:
    """Append one record as a JSON line, creating the file/parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record.to_dict()) + "\n")


def read_records(path: Path) -> list[CalibrationRecord]:
    """Read every record from a calibration log, in append order."""
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(CalibrationRecord.from_dict(json.loads(line)))
    return records
