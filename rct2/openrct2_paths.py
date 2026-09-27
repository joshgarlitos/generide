"""Where OpenRCT2 is, and the two things the web UI does with it.

Check builds a finished ride in the headless game (through `rct2.oracle`)
and records the game's own ratings next to ours. Install copies a ride into
the player's track folder under a name they choose, so it shows up in the
game's Track Designs list.

Both default to macOS locations, the only platform generide is played on
today, and both can be pointed elsewhere:

    GENERIDE_OPENRCT2_BINARY  the game executable (see rct2.oracle)
    GENERIDE_TRACK_DIR        the folder the game reads track designs from

Each is available only when its path exists, so the page can say why a
button is off instead of failing when it is pressed.
"""

import json
import os
import re
import string
import threading
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rct2 import oracle, runrecord, td6
from rct2.calibration_log import _measurements_to_dict

TRACK_DIR_ENV = "GENERIDE_TRACK_DIR"
NAME_MAX = 60
TEMPLATE_FIELDS = ("name", "date", "time", "seed")
DEFAULT_TEMPLATES = ["{name} {date} {time}", "{name} seed {seed}", "{name}"]
UI_SETTINGS_FILE = "settings.json"

# The oracle installs its plugin into the game's one real plugin folder, so
# two checks at once would overwrite each other (see rct2.oracle.score_track).
_check_lock = threading.Lock()


class InvalidName(ValueError):
    """A ride name or naming template that cannot become a file name."""


class InstallConflict(Exception):
    """A design with this name is already in the track folder."""

    def __init__(self, name: str, path: Path):
        super().__init__(f"a design named {name!r} is already installed")
        self.name = name
        self.path = path


class GameUnavailable(RuntimeError):
    """The game, or its track folder, is not where generide expects it."""


def binary_path() -> Path:
    return Path(oracle.resolve_binary())


def track_dir() -> Path:
    override = os.environ.get(TRACK_DIR_ENV)
    if override:
        return Path(override)
    return (
        Path(os.path.expanduser("~")) / "Library" / "Application Support" / "OpenRCT2" / "track"
    )


@dataclass(frozen=True)
class Availability:
    check: bool
    install: bool
    check_reason: str
    install_reason: str
    binary: str
    track_dir: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def availability() -> Availability:
    binary = binary_path()
    tracks = track_dir()
    check_ok = binary.is_file()
    install_ok = tracks.is_dir()
    return Availability(
        check=check_ok,
        install=install_ok,
        check_reason="" if check_ok else (
            f"OpenRCT2 was not found at {binary}. Install it there, or set "
            f"{oracle.BINARY_ENV} to where it is."
        ),
        install_reason="" if install_ok else (
            f"The OpenRCT2 track folder was not found at {tracks}. Open the game "
            f"once to create it, or set {TRACK_DIR_ENV} to where it is."
        ),
        binary=str(binary),
        track_dir=str(tracks),
    )


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

_UNSAFE = re.compile(r'[/\\:*?"<>|]')


def sanitize_name(raw: str) -> str:
    """Make a name safe to use as a file name in the track folder.

    Path separators, characters macOS or the game dislike in file names, and
    control characters are removed; runs of spaces collapse; leading dots go
    (no hidden files, no `..`); the result is trimmed and capped at NAME_MAX.
    """
    text = "".join(
        " " if unicodedata.category(c).startswith("C") else c for c in str(raw)
    )
    text = _UNSAFE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().lstrip(". ")
    text = text[:NAME_MAX].rstrip()
    if not text:
        raise InvalidName("Enter a name with at least one letter or number.")
    return text


def _check_template(template: str) -> None:
    try:
        parts = [p for p in string.Formatter().parse(template) if p[1] is not None]
    except ValueError as exc:
        raise InvalidName(f"The template {template!r} has an unmatched brace.") from exc
    allowed = ", ".join("{" + x + "}" for x in TEMPLATE_FIELDS)
    for _, field_name, format_spec, conversion in parts:
        if field_name not in TEMPLATE_FIELDS:
            raise InvalidName(
                f"The template uses {{{field_name}}}, which is not one of {allowed}."
            )
        # Plain fields only: a format spec such as {name:>999999999} would
        # build an enormous string.
        if format_spec or conversion:
            raise InvalidName(
                f"Write template fields plainly, as one of {allowed}."
            )


def apply_template(template: str, *, name: str, seed: Any, now: Optional[datetime] = None) -> str:
    """Fill a naming template such as "{name} {date} {time}".

    Times use a dash rather than a colon, since the name becomes a file name.
    """
    _check_template(template)
    now = now or datetime.now().astimezone()
    return sanitize_name(template.format(
        name=name, date=f"{now:%Y-%m-%d}", time=f"{now:%H-%M}", seed=seed,
    ))


def load_ui_settings() -> Dict[str, Any]:
    """The page's saved preferences, currently its naming templates."""
    path = runrecord.generide_home() / UI_SETTINGS_FILE
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    templates = data.get("name_templates")
    if not isinstance(templates, list) or not all(isinstance(t, str) for t in templates):
        data["name_templates"] = list(DEFAULT_TEMPLATES)
    return data


def save_ui_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    templates = data.get("name_templates")
    if not isinstance(templates, list) or not all(isinstance(t, str) for t in templates):
        raise InvalidName("Naming templates must be a list of text templates.")
    for template in templates:
        _check_template(template)
    current = load_ui_settings()
    current["name_templates"] = templates
    home = runrecord.generide_home()
    home.mkdir(parents=True, exist_ok=True)
    tmp = home / (UI_SETTINGS_FILE + ".tmp")
    tmp.write_text(json.dumps(current, indent=1) + "\n")
    os.replace(tmp, home / UI_SETTINGS_FILE)
    return current


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def install(run_id: str, name: str, replace: bool = False) -> Dict[str, Any]:
    """Copy a run's exported ride into the track folder as `<name>.td6`.

    An existing design with that name is never overwritten unless `replace`
    is set; without it this raises InstallConflict and changes nothing.
    """
    source = runrecord.run_dir(run_id) / runrecord.BEST_TD6
    final = sanitize_name(name)
    state = availability()
    if not state.install:
        raise GameUnavailable(state.install_reason)
    if not source.is_file():
        raise FileNotFoundError(f"run {run_id} has no exported ride to install")

    dest = Path(state.track_dir) / f"{final}.td6"
    data = source.read_bytes()
    existed = dest.exists()
    if replace:
        tmp = dest.with_name(f".{final}.generide-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    else:
        # Create-only, so a design that appears after the check above is
        # still never overwritten.
        try:
            with dest.open("xb") as f:
                f.write(data)
        except FileExistsError:
            raise InstallConflict(final, dest) from None

    entry = {"name": final, "file": str(dest), "replaced": existed}
    runrecord.record_install(run_id, entry)
    return entry


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------


def check_message(check: Dict[str, Any]) -> str:
    """Say what a check found, in words a player can act on."""
    status = check.get("status")
    detail = check.get("detail") or ""
    if status == "rated":
        return "The game built the ride, ran a test lap, and rated it."
    if status == "stalled":
        index = check.get("stalled_at_index")
        where = f" on piece {index + 1}" if isinstance(index, int) else ""
        return (
            f"The train stalled{where} in the game and never finished its test "
            f"lap, so the game gave no ratings."
        )
    if status == "timeout":
        return (
            "The game ran out of time before the test lap finished, so it gave "
            "no ratings. The ride may be very long, or the game may have hung."
        )
    if status == "placement_failed":
        piece = re.match(r"piece_(\d+)", detail)
        where = f" at piece {int(piece.group(1)) + 1}" if piece else ""
        return (
            f"The game would not build the ride{where}. Its piece-by-piece build "
            f"is stricter than loading a saved design about tracks crossing "
            f"close over themselves, so the design may still load in the game."
        )
    return f"generide could not run the game check: {detail or 'unknown error'}."


def _exported_track(run_id: str):
    ride = td6.load(runrecord.run_dir(run_id) / runrecord.BEST_TD6)
    segments = [e.segment_type for e in ride.elements]
    lifts = {i for i, e in enumerate(ride.elements) if e.chain_lift}
    return segments, lifts


def run_check(
    run_id: str,
    scorer: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Build a run's exported ride in the headless game and record the result.

    One check runs at a time across the whole process. Whatever happens,
    including the scorer raising, a result is recorded and the run's
    in-progress check flag is cleared, so the page never waits forever.
    """
    scorer = scorer or oracle.score_track
    with _check_lock:
        try:
            segments, lifts = _exported_track(run_id)
            result = scorer(segments, lift_indices=lifts)
            measurements = getattr(result, "measurements", None)
            check: Dict[str, Any] = {
                "status": result.status,
                "excitement": result.excitement,
                "intensity": result.intensity,
                "nausea": result.nausea,
                "detail": result.detail,
                "stalled_at_index": result.stalled_at_index,
                "stalled_at_type": result.stalled_at_type,
                "measurements": (
                    _measurements_to_dict(measurements) if measurements is not None else None
                ),
            }
        except Exception as exc:
            check = {
                "status": "oracle_error", "excitement": None, "intensity": None,
                "nausea": None, "detail": str(exc) or type(exc).__name__,
                "stalled_at_index": None, "stalled_at_type": None, "measurements": None,
            }
        check["message"] = check_message(check)
        runrecord.record_check(run_id, check)
        return check
