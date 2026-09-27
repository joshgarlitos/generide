"""Every setting the web page exposes, and the one validator for them.

The page builds its request form from `SETTINGS`: the label, the help text,
the default, the allowed range, and whether the setting sits up front or in
the advanced section. `validate()` checks what comes back and says which
field is wrong and why, and `cli_args()` turns a valid request into the
`evolve_coaster.py` arguments the run is started with.

The CLI keeps its own argparse definitions. tests/test_settings.py pins
every entry here to the matching flag and default there, so the two cannot
drift apart silently. The one deliberate difference is the scoring default:
the page starts from physics scoring, because rating windows only work with
it and it is what produces real drops, while the CLI keeps proxy.
"""

import argparse
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rct2.construction import DEFAULT_STATION_LENGTH, MIN_STATION_LENGTH

ESTIMATE_NOTE = (
    "Targets aim at generide's own rating estimates, not the game's real "
    "ratings. Use the game check on a result to see the real numbers."
)

SEED_MAX = 2**31 - 1


@dataclass(frozen=True)
class Setting:
    key: str  # form field name, and the CLI's argparse dest
    flag: str  # evolve_coaster.py flag
    kind: str  # "int" | "float" | "window" | "choice" | "bool" | "path"
    group: str  # "basic" (up front) | "advanced"
    label: str
    help: str
    default: Any  # what the page starts from
    cli_default: Any  # what evolve_coaster.py defaults to
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[str, ...] = ()
    unit: str = ""
    note: str = ""

    @property
    def dest(self) -> str:
        return self.flag.lstrip("-").replace("-", "_")


def _window(key: str, flag: str, name: str, meaning: str) -> Setting:
    return Setting(
        key=key, flag=flag, kind="window", group="basic",
        label=f"{name} window",
        help=(
            f"The {name.lower()} rating to aim for, as a lowest and highest "
            f"value. {meaning} Leave both empty to leave {name.lower()} free."
        ),
        default=None, cli_default=None, minimum=0, maximum=15,
        note=ESTIMATE_NOTE,
    )


SETTINGS: Tuple[Setting, ...] = (
    Setting(
        key="max_width", flag="--max-width", kind="int", group="basic",
        label="Footprint width",
        help=(
            "How wide the ride may be, in tiles. The ride may be turned to fit, "
            "so width and depth are interchangeable."
        ),
        default=30, cli_default=30, minimum=3, maximum=250, unit="tiles",
    ),
    Setting(
        key="max_depth", flag="--max-depth", kind="int", group="basic",
        label="Footprint depth",
        help="How deep the ride may be, in tiles.",
        default=30, cli_default=30, minimum=3, maximum=250, unit="tiles",
    ),
    _window(
        "target_excitement", "--target-excitement", "Excitement",
        "Higher excitement draws more guests.",
    ),
    _window(
        "target_intensity", "--target-intensity", "Intensity",
        "Too intense and guests refuse to ride.",
    ),
    _window(
        "target_nausea", "--target-nausea", "Nausea",
        "High nausea makes guests sick after riding.",
    ),
    Setting(
        key="station_length", flag="--station-length", kind="int", group="basic",
        label="Station length",
        help=(
            "How many tiles long the station platform is. Longer stations load "
            "more guests at once. Ignored when you start from your own seed track."
        ),
        default=DEFAULT_STATION_LENGTH, cli_default=DEFAULT_STATION_LENGTH,
        minimum=MIN_STATION_LENGTH, maximum=20, unit="tiles",
    ),
    Setting(
        key="generations", flag="--generations", kind="int", group="basic",
        label="Generations",
        help=(
            "How many rounds of breeding the run does. More rounds can find a "
            "better ride but take longer."
        ),
        default=100, cli_default=100, minimum=1, maximum=5000,
    ),
    Setting(
        key="population", flag="--population", kind="int", group="basic",
        label="Population",
        help=(
            "How many rides are kept and bred each round. A bigger population "
            "explores more but makes every round slower."
        ),
        default=50, cli_default=50, minimum=4, maximum=1000,
    ),
    Setting(
        key="seed", flag="--rng-seed", kind="int", group="basic",
        label="Seed",
        help=(
            "The number that fixes every random choice in the run. The same "
            "seed and settings always give the same ride. Leave it empty for a "
            "new random seed."
        ),
        default=None, cli_default=None, minimum=0, maximum=SEED_MAX,
    ),
    Setting(
        key="fitness", flag="--fitness", kind="choice", group="advanced",
        label="Scoring",
        help=(
            "How rides are judged. Physics simulates the train and estimates "
            "ratings, which rating windows need. Proxy is a faster shape-only "
            "score."
        ),
        default="physics", cli_default="proxy", choices=("proxy", "physics"),
    ),
    Setting(
        key="genome", flag="--genome", kind="choice", group="advanced",
        label="Track building blocks",
        help=(
            "Parts keeps slopes and turns together as whole runs and gives every "
            "ride a lift hill. Pieces is the older piece-by-piece method, kept "
            "for comparison."
        ),
        default="parts", cli_default="parts", choices=("parts", "pieces"),
    ),
    Setting(
        key="mutation_rate", flag="--mutation-rate", kind="float", group="advanced",
        label="Mutation rate",
        help=(
            "How much each new ride differs from its parents, from 0 to 1. "
            "Higher values explore more but lose good rides more often."
        ),
        default=0.1, cli_default=0.1, minimum=0.0, maximum=1.0,
    ),
    Setting(
        key="seed_track", flag="--seed", kind="path", group="advanced",
        label="Seed track",
        help=(
            "A saved design file to start from instead of a generated loop. "
            "Enter the full path of a file ending in .td6."
        ),
        default=None, cli_default=None,
    ),
    Setting(
        key="oracle_calibrate", flag="--oracle-calibrate", kind="bool", group="advanced",
        label="Calibrate against the game",
        help=(
            "Now and then, build the run's best ride in the real game to log how "
            "far our estimates are off. It never changes the result, but adds "
            "time and needs OpenRCT2."
        ),
        default=False, cli_default=False,
    ),
    Setting(
        key="oracle_interval", flag="--oracle-interval", kind="int", group="advanced",
        label="Calibration interval",
        help="How many generations pass between game checks during calibration.",
        default=10, cli_default=10, minimum=1, maximum=1000,
    ),
    Setting(
        key="oracle_max_calls", flag="--oracle-max-calls", kind="int", group="advanced",
        label="Calibration limit",
        help="The most game checks one calibrating run may make.",
        default=20, cli_default=20, minimum=1, maximum=500,
    ),
)

BY_KEY: Dict[str, Setting] = {s.key: s for s in SETTINGS}


def table() -> List[Dict[str, Any]]:
    """The settings as plain data, for the page to build its form from."""
    rows = []
    for s in SETTINGS:
        row = asdict(s)
        row["choices"] = list(s.choices)
        rows.append(row)
    return rows


@dataclass
class Validation:
    values: Dict[str, Any]  # normalized, complete (every key present)
    errors: Dict[str, str]  # field key -> plain-language problem

    @property
    def ok(self) -> bool:
        return not self.errors


def _blank(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip() == "")


def _fmt(n: Optional[float]) -> str:
    if n is None:
        return ""
    return str(int(n)) if float(n).is_integer() else str(n)


def _range_error(s: Setting) -> str:
    unit = f" {s.unit}" if s.unit else ""
    return f"{s.label} must be from {_fmt(s.minimum)} to {_fmt(s.maximum)}{unit}."


def _number(s: Setting, raw: Any, whole: bool) -> Tuple[Optional[float], Optional[str]]:
    if isinstance(raw, bool):
        return None, f"{s.label} must be a number."
    try:
        value = float(raw)
    except (TypeError, ValueError):
        kind = "a whole number" if whole else "a number"
        return None, f"{s.label} must be {kind}."
    if not math.isfinite(value):
        return None, f"{s.label} must be a number."
    if whole:
        if not value.is_integer():
            return None, f"{s.label} must be a whole number."
        value = int(value)
    if (s.minimum is not None and value < s.minimum) or (
        s.maximum is not None and value > s.maximum
    ):
        return None, _range_error(s)
    return value, None


def _window_value(s: Setting, raw: Any) -> Tuple[Optional[List[float]], Optional[str]]:
    if raw is None:
        return None, None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        low_raw, high_raw = raw
    elif isinstance(raw, dict):
        low_raw, high_raw = raw.get("min"), raw.get("max")
    else:
        return None, f"{s.label} needs a lowest and a highest value."
    if _blank(low_raw) and _blank(high_raw):
        return None, None
    if _blank(low_raw) or _blank(high_raw):
        return None, f"Enter both ends of the {s.label.lower()}, or leave both empty."
    low, err = _number(s, low_raw, whole=False)
    if err:
        return None, err
    high, err = _number(s, high_raw, whole=False)
    if err:
        return None, err
    if low > high:
        return None, (
            f"The lowest value ({_fmt(low)}) is above the highest ({_fmt(high)}). "
            f"Swap them."
        )
    return [low, high], None


def validate(raw_values: Dict[str, Any]) -> Validation:
    """Check form values. Blank fields take the page default.

    Returns every setting's normalized value and, per field, what is wrong.
    A blank seed stays None; the caller picks one before starting a run, so
    the record always holds the seed that was actually used.
    """
    values: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    for key in raw_values:
        if key not in BY_KEY:
            errors[key] = f"{key} is not a setting generide knows."

    for s in SETTINGS:
        raw = raw_values.get(s.key)
        if s.kind == "window":
            value, err = _window_value(s, raw)
        elif _blank(raw):
            value, err = s.default, None
        elif s.kind in ("int", "float"):
            value, err = _number(s, raw, whole=(s.kind == "int"))
        elif s.kind == "choice":
            value, err = raw, None
            if raw not in s.choices:
                err = f"{s.label} must be one of: {', '.join(s.choices)}."
        elif s.kind == "bool":
            value, err = raw, None
            if not isinstance(raw, bool):
                err = f"{s.label} must be on or off."
        elif s.kind == "path":
            value, err = str(raw).strip(), None
            path = Path(value).expanduser()
            if path.suffix.lower() != ".td6" or not path.is_file():
                err = f"{s.label} must be an existing .td6 file; {value} is not one."
        else:  # pragma: no cover - table entries are fixed above
            raise ValueError(f"unknown setting kind {s.kind}")
        if err:
            errors[s.key] = err
        values[s.key] = value

    if values.get("fitness") == "proxy":
        for key in ("target_excitement", "target_intensity", "target_nausea"):
            if values.get(key) is not None and key not in errors:
                errors[key] = (
                    "Rating windows need physics scoring. Set Scoring to physics "
                    "in the advanced settings, or clear this window."
                )
    if values.get("oracle_calibrate") is True and values.get("genome") == "pieces":
        errors.setdefault(
            "oracle_calibrate",
            "Calibration only works with the parts building blocks. Switch "
            "Track building blocks to parts, or turn calibration off.",
        )

    return Validation(values=values, errors=errors)


def cli_args(values: Dict[str, Any]) -> List[str]:
    """evolve_coaster.py arguments for validated values, in table order.

    Every setting is written out, defaults included, so a saved run says
    exactly what it ran with even if a default changes later. Unset optional
    settings (a window, the seed track, a blank seed) are left out.
    """
    args: List[str] = []
    for s in SETTINGS:
        value = values.get(s.key)
        if s.kind == "bool":
            if value:
                args.append(s.flag)
            continue
        if value is None:
            continue
        if s.kind == "window":
            args += [s.flag, f"{_fmt(value[0])}:{_fmt(value[1])}"]
        else:
            args += [s.flag, _fmt(value) if s.kind in ("int", "float") else str(value)]
    return args


def _parse_window(raw: Optional[str]) -> Optional[List[float]]:
    if raw is None:
        return None
    low, _, high = raw.partition(":")
    return [float(low), float(high)]


def request_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    """The request in form terms, from parsed evolve_coaster.py arguments.

    This is what a run record stores as its request, whichever way the run
    was started, so a rerun can pre-fill the form from any saved run.
    """
    request: Dict[str, Any] = {}
    for s in SETTINGS:
        value = getattr(args, s.dest, None)
        if s.kind == "window":
            value = _parse_window(value)
        elif s.kind == "path" and value is not None:
            # "simple" is the CLI's name for the generated loop, which is
            # what the page means by no seed track.
            value = None if value == "simple" else str(value)
        request[s.key] = value
    return request


def form_values(request: Dict[str, Any]) -> Dict[str, Any]:
    """Form values for a rerun: the stored request over the page defaults.

    The seed is carried over, so a rerun that changes one input differs from
    its source run by that input alone and not by random luck.
    """
    values = {s.key: s.default for s in SETTINGS}
    for key, value in request.items():
        if key in BY_KEY:
            if BY_KEY[key].kind == "window" and value is not None:
                value = {"min": value[0], "max": value[1]}
            values[key] = value
    return values
