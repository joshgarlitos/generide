"""Saved run records: the library the CLI and the web UI share.

Every run, started from a terminal or from the page, gets a directory under
the library root holding:

    run.json            what was asked for and what came of it (rewritten
                        whole, atomically, when its status changes)
    progress.jsonl      one line per generation, appended as the run goes
    improvements.jsonl  the full track every time the best ride improves
    best.td6            the exported ride, when there is one

The two logs are append-only JSON lines, following `rct2.calibration_log`,
so a crash or a closed laptop loses nothing already written. The improvements
log keeps complete tracks rather than just scores so later work (a replay of
how a ride evolved, learning from past runs) needs no new data collection.

The library lives in generide's own folder, `~/.generide/runs/` or
`$GENERIDE_HOME/runs/`, never in the game's folders: clearing it, or deleting
a run from it, cannot touch a ride already installed in OpenRCT2.

Run ids come from outside (the browser, a command line), so every function
that builds a path from one checks it against `RUN_ID_PATTERN` first.
"""

import json
import os
import re
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

RUN_FILE = "run.json"
PROGRESS_FILE = "progress.jsonl"
IMPROVEMENTS_FILE = "improvements.jsonl"
BEST_TD6 = "best.td6"

# UTC date-time, then the seed (which can be negative), then an optional
# numeric suffix when two runs would otherwise share an id.
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-s-?[0-9]{1,20}(-[0-9]{1,4})?$")

# How remaining time and stagnation are judged; see time_remaining() and
# stagnation(). Kept here so tuning them is one edit.
ETA_WINDOW = 10
ETA_MIN_DURATIONS = 3
STAGNANT_MIN_GENERATIONS = 20
STAGNANT_MIN_SHARE = 0.25

TERMINAL_STATUSES = ("completed", "stopped", "failed", "interrupted")

# Read-modify-write of run.json from more than one thread in the web server
# (a background check finishing while an install lands) must not interleave.
_write_lock = threading.RLock()


class InvalidRunId(ValueError):
    """A run id that does not match RUN_ID_PATTERN."""


class UnsupportedSchema(ValueError):
    """A run record written by a newer generide than this one."""


class RunIsActive(RuntimeError):
    """The run is still going, so it cannot be deleted."""


@dataclass
class Run:
    record: Dict[str, Any]
    progress: List[Dict[str, Any]] = field(default_factory=list)
    improvements: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.record["id"]

    @property
    def directory(self) -> Path:
        return run_dir(self.id)


def generide_home() -> Path:
    """generide's own folder: `$GENERIDE_HOME`, or `~/.generide`."""
    override = os.environ.get("GENERIDE_HOME")
    if override:
        return Path(override)
    return Path(os.path.expanduser("~")) / ".generide"


def library_root() -> Path:
    return generide_home() / "runs"


def validate_run_id(run_id: Any) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise InvalidRunId(f"not a run id: {run_id!r}")
    return run_id


def run_dir(run_id: str) -> Path:
    run_id = validate_run_id(run_id)  # before any path exists to misuse
    return library_root() / run_id


def new_run_id(seed: int, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-s{seed}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_record(directory: Path, record: Dict[str, Any]) -> None:
    """Replace run.json in one step, so a reader never sees half a file."""
    tmp = directory / (RUN_FILE + ".tmp")
    tmp.write_text(json.dumps(record, indent=1) + "\n")
    os.replace(tmp, directory / RUN_FILE)


def _read_record(directory: Path) -> Dict[str, Any]:
    record = json.loads((directory / RUN_FILE).read_text())
    version = record.get("schema_version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise UnsupportedSchema(
            f"run {directory.name} was saved by a newer version of generide "
            f"(schema {version}, this one reads up to {SCHEMA_VERSION})"
        )
    return record


def _read_lines(path: Path) -> List[Dict[str, Any]]:
    """Every complete JSON line. A crash can leave the last line cut short;
    that line, and only that line, is dropped."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append_line(path: Path, entry: Dict[str, Any]) -> None:
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def create_run(
    *,
    seed: int,
    request: Dict[str, Any],
    settings: List[str],
    generations: int,
    run_id: Optional[str] = None,
    parent: Optional[str] = None,
    pid: Optional[int] = None,
    now: Optional[datetime] = None,
) -> str:
    """Create a run directory and its run.json, and return the run's id.

    `request` is the ride request in form terms (what the page shows);
    `settings` is the CLI argument list the run was started with, so a run
    can always be repeated exactly. With `run_id` given (the web server picks
    one so it knows the directory before the process starts), no run may
    already be saved under that id. Without one, an id is made from the time and seed, with a numeric
    suffix when another run already has it.
    """
    now = now or datetime.now(timezone.utc)
    root = library_root()
    root.mkdir(parents=True, exist_ok=True)

    if run_id is not None:
        # The web server may already have made the directory (it starts the
        # run's console log there); the id is taken once a run file exists.
        directory = run_dir(run_id)
        directory.mkdir(exist_ok=True)
        if (directory / RUN_FILE).exists():
            raise FileExistsError(f"run {run_id} already exists")
    else:
        base = new_run_id(seed, now)
        suffix = 1
        while True:
            run_id = base if suffix == 1 else f"{base}-{suffix}"
            directory = run_dir(run_id)
            try:
                directory.mkdir()
                break
            except FileExistsError:
                suffix += 1

    if parent is not None:
        validate_run_id(parent)

    record = {
        "schema_version": SCHEMA_VERSION,
        "id": run_id,
        "created": now.isoformat(),
        "seed": seed,
        "request": request,
        "settings": list(settings),
        "parent": parent,
        "status": "running",
        "pid": pid if pid is not None else os.getpid(),
        "generations_planned": generations,
        "generations_run": None,
        "finished": None,
        "result": None,
        "check_status": None,
        "checks": [],
        "installs": [],
    }
    _write_record(directory, record)
    (directory / PROGRESS_FILE).touch()
    (directory / IMPROVEMENTS_FILE).touch()
    return run_id


def append_progress(run_id: str, entry: Dict[str, Any]) -> None:
    _append_line(run_dir(run_id) / PROGRESS_FILE, entry)


def append_improvement(run_id: str, entry: Dict[str, Any]) -> None:
    _append_line(run_dir(run_id) / IMPROVEMENTS_FILE, entry)


def update_record(run_id: str, change) -> Dict[str, Any]:
    """Apply `change(record)` to run.json under the write lock and save it."""
    directory = run_dir(run_id)
    with _write_lock:
        record = _read_record(directory)
        change(record)
        _write_record(directory, record)
        return record


def finish_run(
    run_id: str,
    status: str,
    *,
    generations_run: Optional[int] = None,
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"not a finishing status: {status!r}")

    def change(record):
        record["status"] = status
        record["finished"] = _utc_now()
        record["generations_run"] = generations_run
        record["result"] = result

    return update_record(run_id, change)


def set_check_status(run_id: str, status: Optional[str]) -> Dict[str, Any]:
    return update_record(run_id, lambda r: r.__setitem__("check_status", status))


def record_check(run_id: str, check: Dict[str, Any]) -> Dict[str, Any]:
    """Append a finished check and clear the in-progress flag."""
    entry = dict(check)
    entry.setdefault("time", _utc_now())

    def change(record):
        record["checks"].append(entry)
        record["check_status"] = None

    return update_record(run_id, change)


def record_install(run_id: str, install: Dict[str, Any]) -> Dict[str, Any]:
    entry = dict(install)
    entry.setdefault("time", _utc_now())
    return update_record(run_id, lambda r: r["installs"].append(entry))


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def _repair(directory: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    """A run still marked running whose process is gone was interrupted."""
    if record.get("status") == "running" and not _pid_alive(record.get("pid")):
        with _write_lock:
            record = _read_record(directory)
            if record.get("status") == "running" and not _pid_alive(record.get("pid")):
                record["status"] = "interrupted"
                record["finished"] = record.get("finished") or _utc_now()
                _write_record(directory, record)
    return record


def load_record(run_id: str) -> Dict[str, Any]:
    directory = run_dir(run_id)
    return _repair(directory, _read_record(directory))


def load_run(run_id: str) -> Run:
    directory = run_dir(run_id)
    record = _repair(directory, _read_record(directory))
    return Run(
        record=record,
        progress=_read_lines(directory / PROGRESS_FILE),
        improvements=_read_lines(directory / IMPROVEMENTS_FILE),
    )


def list_runs() -> List[Dict[str, Any]]:
    """Every saved run's record, newest first.

    A run whose record cannot be read is listed with status "unreadable"
    rather than hidden, so it can still be seen and deleted.
    """
    root = library_root()
    if not root.is_dir():
        return []
    records = []
    for directory in root.iterdir():
        if not directory.is_dir() or not RUN_ID_PATTERN.fullmatch(directory.name):
            continue
        if not (directory / RUN_FILE).exists():
            continue  # a run the web server is still starting
        try:
            records.append(_repair(directory, _read_record(directory)))
        except (OSError, ValueError) as exc:
            records.append({
                "id": directory.name, "status": "unreadable", "error": str(exc),
                "created": "", "installs": [], "checks": [],
            })
    records.sort(key=lambda r: (r.get("created") or "", r["id"]), reverse=True)
    return records


def delete_run(run_id: str) -> None:
    """Remove a run's directory. Refused while the run is still going.

    Deliberately touches nothing but the run's own directory: a ride installed
    from it lives in the game's track folder and stays there.
    """
    directory = run_dir(run_id)
    if not directory.is_dir():
        raise FileNotFoundError(run_id)
    try:
        record = load_record(run_id)
    except (OSError, ValueError):
        record = {}
    if record.get("status") == "running":
        raise RunIsActive(f"run {run_id} is still running; stop it first")
    shutil.rmtree(directory)


def display_name(record: Dict[str, Any]) -> str:
    """The latest install name, or the run's date and seed if never installed."""
    installs = record.get("installs") or []
    if installs and installs[-1].get("name"):
        return installs[-1]["name"]
    created = record.get("created") or ""
    try:
        when = datetime.fromisoformat(created).astimezone(timezone.utc)
        stamp = f"{when:%Y-%m-%d %H:%M}"
    except ValueError:
        stamp = record.get("id", "")
    return f"{stamp}, seed {record.get('seed')}"


def ride_summary(
    segments: List[int],
    max_width: Optional[int] = None,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    """What the result view shows for a track: validity, stats, estimates.

    Everything here is generide's own model, which is not calibrated against
    the game, so every rating lands under "estimated" and never beside a
    game-checked number without that label.
    """
    from rct2 import construction, physics, render

    validation = construction.validate_construction(
        segments, max_width=max_width, max_depth=max_depth,
    )
    lifts = set(validation.lift_indices)
    stats = physics.simulate(segments, lift_indices=lifts)
    ratings = physics.rate(stats)
    plan = render.plan_track(segments)
    return {
        "segments": len(segments),
        "valid": validation.valid,
        "issues": [{"code": i.code, "message": i.message} for i in validation.issues],
        "completed": stats.completed,
        "stall_index": stats.stall_index,
        "lift_indices": sorted(lifts),
        "stats": asdict(stats),
        "estimated": asdict(ratings),
        "footprint": {
            "width": plan.width_tiles if plan.tiles else 0,
            "depth": plan.depth_tiles if plan.tiles else 0,
            "max_width": max_width,
            "max_depth": max_depth,
        },
    }


def time_remaining(progress: List[Dict[str, Any]], generations_planned: int) -> Optional[float]:
    """Seconds left, from the last few generations' pace. None while estimating.

    A whole-run average would underestimate: genomes grow as a run goes on,
    so late generations are slower than early ones (see
    docs/solutions/performance-issues/genome-bloat-from-uncapped-fitness-rewards.md).
    The mean of the last ETA_WINDOW generation durations follows that drift.
    """
    if len(progress) < ETA_MIN_DURATIONS + 1:
        return None
    times = [p["time"] for p in progress]
    durations = [b - a for a, b in zip(times, times[1:])][-ETA_WINDOW:]
    left = max(0, generations_planned - progress[-1]["generation"])
    return left * (sum(durations) / len(durations))


def stagnation(progress: List[Dict[str, Any]], generations_planned: int) -> Optional[int]:
    """Generations since the best score last changed, once that is worth saying.

    Reported only when the best has held for at least
    STAGNANT_MIN_GENERATIONS generations and at least STAGNANT_MIN_SHARE of
    the planned run, so a long run is not flagged for a pause that is normal
    at its scale. None otherwise.
    """
    if not progress:
        return None
    latest = progress[-1]
    best = latest["best_fitness"]
    since = latest["generation"]
    for entry in reversed(progress):
        if entry["best_fitness"] != best:
            break
        since = entry["generation"]
    flat = latest["generation"] - since
    if flat >= STAGNANT_MIN_GENERATIONS and flat >= STAGNANT_MIN_SHARE * generations_planned:
        return flat
    return None
