"""The local web UI's server: a JSON API over the run library, plus the page.

Everything the page shows is decided here, and the page's JavaScript only
fetches, places, and polls. That keeps the logic testable in pytest, since
the project has no JavaScript test setup.

`App.dispatch()` turns a `Request` into a `Response` with no sockets
involved, so tests call it directly. `serve()` wraps it in the standard
library's `ThreadingHTTPServer`.

Runs are not executed in this process. Starting one launches
`evolve_coaster.py` as a child in its own session, with a run id picked here,
and the page follows it through the run record the child writes, exactly as
it would a run started from a terminal. Stop is SIGTERM to that child, which
the CLI turns into a clean stop at the next generation. A run this server did
not start (a terminal run, or one left over from a previous server) can
still be stopped the same way, but only once `rct2.runrecord.can_signal`
positively confirms the recorded pid is still that run's own process --
see its docstring for why an alive pid alone is not proof of that.

Security, for a server that only ever talks to one person's own browser:
it binds 127.0.0.1 only; it refuses any Host header other than its own
address (which defeats DNS rebinding); it refuses state-changing requests
carrying another site's Origin or a non-JSON body (so another tab cannot
drive it); and it never takes a file path for run data from the browser, only
run ids, which are checked against a strict pattern before any file access.
"""

import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from rct2 import openrct2_paths, render, runrecord, settings
from rct2.physics import HEIGHT_UNIT_M, MPH_PER_MS

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "webui_static"
DEFAULT_COMMAND = (sys.executable, "-u", str(REPO_ROOT / "evolve_coaster.py"))

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/iso-view.js": ("iso-view.js", "text/javascript; charset=utf-8"),
    "/tokens.css": ("tokens.css", "text/css; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

CONSOLE_LOG = "console.log"
ORACLE_LOG = "oracle-log.jsonl"
START_TIMEOUT_S = 15.0

RESTART_NOTE = (
    "If OpenRCT2 is already open, restart it to see the new design under "
    "Mine Train in the Track Designs list."
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # Inline SVG carries its own <style> for dark mode, hence unsafe-inline
    # for styles only. Scripts come from this server alone.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
}

# Headline numbers shown in the library and compared side by side. Each is
# (key, label, dotted path into the ride summary, display format). Estimates
# and game-checked ratings are separate keys and labels, never merged.
HEADLINE_STATS: Tuple[Tuple[str, str, str, str], ...] = (
    ("excitement", "Excitement (estimate)", "estimated.excitement", "{:.2f}"),
    ("intensity", "Intensity (estimate)", "estimated.intensity", "{:.2f}"),
    ("nausea", "Nausea (estimate)", "estimated.nausea", "{:.2f}"),
    ("game_excitement", "Excitement (game)", "game.excitement", "{:.2f}"),
    ("game_intensity", "Intensity (game)", "game.intensity", "{:.2f}"),
    ("game_nausea", "Nausea (game)", "game.nausea", "{:.2f}"),
    ("max_speed_mph", "Top speed (mph)", "stats.max_speed_mph", "{:.0f}"),
    ("drop_count", "Drops", "stats.drop_count", "{:.0f}"),
    ("highest_drop_m", "Highest drop (m)", "stats.highest_drop_m", "{:.1f}"),
    ("airtime", "Airtime (s)", "stats.airtime", "{:.1f}"),
    ("max_positive_g", "Max vertical g", "stats.max_positive_g", "{:.2f}"),
    ("max_negative_g", "Min vertical g", "stats.max_negative_g", "{:.2f}"),
    ("max_lateral_g", "Max lateral g", "stats.max_lateral_g", "{:.2f}"),
    ("ride_length", "Length (m)", "stats.ride_length", "{:.0f}"),
    ("segments", "Pieces", "segments", "{:.0f}"),
    ("width", "Footprint width (tiles)", "footprint.width", "{:.0f}"),
    ("depth", "Footprint depth (tiles)", "footprint.depth", "{:.0f}"),
)


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


@dataclass
class Request:
    method: str
    path: str  # may include a query string
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str) -> Optional[str]:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return None


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"
    headers: Dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.body)


def _json_response(status: int, payload: Any) -> Response:
    return Response(status, json.dumps(payload).encode("utf-8"))


# ---------------------------------------------------------------------------
# Views: what the page shows, derived from saved runs
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def _summary(
    segments: Tuple[int, ...],
    max_width: Optional[int],
    max_depth: Optional[int],
    site_path: Optional[str] = None,
):
    site = runrecord.site_from_request({"site": site_path})
    return runrecord.ride_summary(list(segments), max_width, max_depth, site=site)


def _epoch(stamp: Optional[str]) -> Optional[float]:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def _dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _latest_game_check(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    checks = record.get("checks") or []
    return checks[-1] if checks else None


def _game_ratings(record: Dict[str, Any]) -> Dict[str, Any]:
    """The game's own ratings from the latest check, when the game rated it."""
    check = _latest_game_check(record)
    if not check or check.get("status") != "rated":
        return {}
    return {k: check.get(k) for k in ("excitement", "intensity", "nausea")}


def _final_result(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The finished run's ride summary, as the CLI saved it, if it has one."""
    result = record.get("result")
    if result and "stats" in result:
        return dict(result, generation=record.get("generations_run"))
    return None


def _best_summary(run: runrecord.Run) -> Optional[Dict[str, Any]]:
    """A summary of the latest improvement: a live or unfinished run's best."""
    if not run.improvements:
        return None
    request = run.record.get("request") or {}
    latest = run.improvements[-1]
    summary = dict(_summary(
        tuple(latest["segments"]), request.get("max_width"), request.get("max_depth"),
        request.get("site"),
    ))
    summary["fitness"] = latest.get("fitness")
    summary["generation"] = latest.get("generation")
    return summary


def _headline(best: Optional[Dict[str, Any]], record: Dict[str, Any]) -> Dict[str, Any]:
    """Flat headline numbers, estimates and game-checked kept apart by key."""
    source: Dict[str, Any] = {}
    if best:
        stats = dict(best.get("stats") or {})
        if "max_speed" in stats:
            stats["max_speed_mph"] = stats["max_speed"] * MPH_PER_MS
        if "highest_drop" in stats:
            stats["highest_drop_m"] = stats["highest_drop"] * HEIGHT_UNIT_M
        source = dict(best, stats=stats)
    game = _game_ratings(record)
    if game:
        source["game"] = game
    return {key: _dig(source, path) for key, _, path, _ in HEADLINE_STATS}


def _warnings(best: Optional[Dict[str, Any]], record: Dict[str, Any]) -> List[str]:
    """What must be obvious before anyone installs this ride (R15)."""
    out = []
    if record.get("status") == "failed":
        out.append("No buildable ride was found, so nothing was exported.")
    if best is None:
        return out
    if not best.get("valid", True):
        issues = "; ".join(i["message"] for i in best.get("issues") or [])
        out.append(f"This ride fails construction checks: {issues}.")
    site = best.get("site")
    if site and not site.get("fits"):
        out.append(
            f"This ride does not fit the site: {site['outside']} tiles outside it, "
            f"{site['blocked']} on blocked tiles, {site['below_ground']} under the ground."
        )
    if not best.get("completed", True):
        index = best.get("stall_index")
        where = f" on piece {index + 1}" if isinstance(index, int) else ""
        out.append(
            f"The train does not complete the circuit: it stalls{where} in "
            f"generide's simulation."
        )
    return out


def _stats_view(best: Optional[Dict[str, Any]], record: Dict[str, Any]) -> Dict[str, Any]:
    """The result view's numbers, formatted, with their source kept visible.

    Every number from generide's own simulation is an estimate. The game's
    ratings appear only in their own column, beside ours, never instead.
    """
    if not best or "stats" not in best:
        return {"simulated": [], "ratings": []}
    st = best["stats"]
    fp = best.get("footprint") or {}
    if st.get("completed"):
        circuit = "Yes"
    else:
        index = st.get("stall_index")
        circuit = f"No, it stalls on piece {index + 1}" if isinstance(index, int) else "No"
    footprint = f"{fp.get('width')} x {fp.get('depth')} tiles"
    site = best.get("site")
    if site is None and fp.get("max_width") is not None:
        footprint += f" (allowed {fp.get('max_width')} x {fp.get('max_depth')})"
    simulated = [
        ("Top speed", f"{st['max_speed'] * MPH_PER_MS:.0f} mph"),
        ("Average speed", f"{st['avg_speed'] * MPH_PER_MS:.0f} mph"),
        ("Drops", f"{st['drop_count']}"),
        ("Highest drop", f"{st['highest_drop'] * HEIGHT_UNIT_M:.1f} m"),
        ("Airtime", f"{st['airtime']:.1f} s"),
        ("Vertical g", f"{st['max_negative_g']:.2f} to {st['max_positive_g']:.2f}"),
        ("Lateral g", f"{st['max_lateral_g']:.2f}"),
        ("Ride length", f"{st['ride_length']:.0f} m"),
        ("Ride time", f"{st['ride_time']:.0f} s"),
        ("Completes the circuit", circuit),
        ("Footprint", footprint),
    ]
    if site is not None:
        left_out = ", ".join(site.get("not_checked") or [])
        simulated.append((
            "Fits the site",
            f"Yes (tiles only; not checked: {left_out})" if site["fits"]
            else f"No (not checked either way: {left_out})",
        ))
        if site.get("place_at"):
            simulated.append(("Place at", site["place_at"]["text"]))
    game = _game_ratings(record)
    estimated = best.get("estimated") or {}
    ratings = []
    for key in ("excitement", "intensity", "nausea"):
        est = estimated.get(key)
        got = game.get(key)
        ratings.append({
            "label": key.capitalize(),
            "estimate": None if est is None else f"{est:.2f}",
            "game": None if got is None else f"{got:.2f}",
        })
    return {
        "simulated": [{"label": label, "value": value} for label, value in simulated],
        "ratings": ratings,
    }


def _live(run: runrecord.Run, now: float) -> Dict[str, Any]:
    record = run.record
    planned = record.get("generations_planned") or 0
    created = _epoch(record.get("created")) or now
    ended = _epoch(record.get("finished"))
    generation = run.progress[-1]["generation"] if run.progress else None
    remaining = None
    if record.get("status") == "running":
        remaining = runrecord.time_remaining(run.progress, planned)
    return {
        "generation": generation,
        "generations_planned": planned,
        "elapsed": (ended or now) - created,
        "remaining": remaining,
        "estimating": record.get("status") == "running" and remaining is None,
        "stagnant_for": runrecord.stagnation(run.progress, planned),
        "last_progress": run.progress[-1]["time"] if run.progress else None,
    }


def _list_entry(record: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    run_id = record["id"]
    if record.get("status") == "unreadable":
        return {"id": run_id, "status": "unreadable", "name": run_id,
                "error": record.get("error"), "created": ""}
    best = _final_result(record)
    if best is None:
        try:
            best = _best_summary(runrecord.load_run(run_id))
        except (OSError, ValueError):
            best = None
    request = record.get("request") or {}
    check = _latest_game_check(record)
    installs = record.get("installs") or []
    return {
        "id": run_id,
        "name": name or runrecord.run_name(record),
        "created": record.get("created"),
        "status": record.get("status"),
        "parent": record.get("parent"),
        "seed": record.get("seed"),
        "inputs": {
            key: request.get(key)
            for key in ("max_width", "max_depth", "target_excitement", "target_intensity",
                        "target_nausea", "generations", "population", "fitness")
        },
        "headline": _headline(best, record),
        "check": None if check is None else {
            "status": check.get("status"), "message": check.get("message"),
        },
        "checking": record.get("check_status") == "checking",
        "installed": [i.get("name") for i in installs],
        "warnings": _warnings(best, record),
    }


def run_detail(run: runrecord.Run, now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    record = run.record
    result = record.get("result")
    best = _final_result(record) or _best_summary(run)
    directory = runrecord.run_dir(run.id)
    return {
        "id": run.id,
        "name": runrecord.run_name(record),
        "status": record.get("status"),
        "created": record.get("created"),
        "finished": record.get("finished"),
        "seed": record.get("seed"),
        "parent": record.get("parent"),
        "request": record.get("request"),
        "generations_run": record.get("generations_run"),
        "live": _live(run, now),
        "best": best,
        "headline": _headline(best, record),
        "stats_view": _stats_view(best, record),
        "warnings": _warnings(best, record),
        "stopped_early": record.get("status") == "stopped",
        "has_ride": (directory / runrecord.BEST_TD6).is_file(),
        "improvements": len(run.improvements),
        "checks": record.get("checks") or [],
        "checking": record.get("check_status") == "checking",
        "installs": record.get("installs") or [],
        "error": (result or {}).get("error"),
    }


def _input_display(setting: settings.Setting, value: Any) -> str:
    if value is None:
        return "random" if setting.key == "seed" else "not set"
    if setting.kind == "window":
        return f"{value[0]:g} to {value[1]:g}"
    if setting.kind == "bool":
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def compare(runs: Sequence[runrecord.Run]) -> Dict[str, Any]:
    """Two or three runs side by side: which inputs differ, how stats moved."""
    details = [run_detail(r) for r in runs]
    inputs = []
    for s in settings.SETTINGS:
        values = [(r.record.get("request") or {}).get(s.key) for r in runs]
        if s.key == "seed":
            values = [r.record.get("seed") for r in runs]
        inputs.append({
            "key": s.key, "label": s.label, "values": values,
            "display": [_input_display(s, v) for v in values],
            "changed": any(v != values[0] for v in values[1:]),
        })
    stats = []
    for key, label, _, fmt in HEADLINE_STATS:
        values = [d["headline"].get(key) for d in details]
        base = values[0]
        deltas = [
            None if (v is None or base is None) else v - base
            for v in values
        ]
        stats.append({
            "key": key, "label": label, "values": values, "deltas": deltas,
            "display": ["" if v is None else fmt.format(v) for v in values],
            "delta_display": [
                "" if d is None or i == 0 else ("+" if d > 0 else "") + fmt.format(d)
                for i, d in enumerate(deltas)
            ],
            "changed": any(d not in (None, 0) and fmt.format(abs(d)) != fmt.format(0)
                           for d in deltas[1:]),
        })
    return {
        "runs": [
            {k: d[k] for k in ("id", "name", "status", "created", "seed", "parent",
                               "warnings", "has_ride")}
            for d in details
        ],
        "inputs": inputs,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# The run supervisor
# ---------------------------------------------------------------------------


class Supervisor:
    """Starts page runs as child processes and stops them. One at a time."""

    def __init__(self, command: Sequence[str] = DEFAULT_COMMAND,
                 popen: Callable[..., Any] = subprocess.Popen):
        self.command = list(command)
        self.popen = popen
        self._lock = threading.Lock()
        self._children: Dict[str, Any] = {}

    def _reap(self) -> None:
        for run_id, child in list(self._children.items()):
            if child.poll() is not None:
                del self._children[run_id]

    def owns(self, run_id: str) -> bool:
        with self._lock:
            self._reap()
            return run_id in self._children

    def start(self, run_id: str, args: List[str]) -> None:
        directory = runrecord.run_dir(run_id)
        directory.mkdir(parents=True, exist_ok=False)
        with (directory / CONSOLE_LOG).open("wb") as log:
            child = self.popen(
                self.command + args,
                cwd=str(directory),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                # Its own session, so Ctrl-C on the server leaves the run going.
                start_new_session=True,
            )
        with self._lock:
            self._children[run_id] = child
        # Reap it as soon as it exits, so it never lingers as a zombie that
        # still looks alive to the run record's pid check.
        threading.Thread(target=child.wait, daemon=True).start()

        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if (directory / runrecord.RUN_FILE).exists():
                return
            if child.poll() is not None:
                break
            time.sleep(0.05)
        # It never wrote its record: say why, and leave nothing half-made.
        if child.poll() is None:
            child.kill()
            child.wait()
        console = (directory / CONSOLE_LOG).read_text(errors="replace")[-2000:]
        for name in os.listdir(directory):
            (directory / name).unlink()
        directory.rmdir()
        raise ApiError(500, "The run did not start.", console=console)

    def stop(self, run_id: str) -> None:
        with self._lock:
            self._reap()
            child = self._children.get(run_id)
        if child is None:
            raise ApiError(
                409,
                "This run was not started from this page. Stop it from the "
                "terminal it is running in, with Ctrl-C.",
            )
        child.send_signal(signal.SIGTERM)


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------


Route = Tuple[str, str]  # (method, pattern) where {id} marks a run id


def _quarter_turns(raw: Optional[str]) -> int:
    """The view angle a request asks for: a whole number, else the default view."""
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


class App:
    def __init__(
        self,
        port: int = 0,
        command: Sequence[str] = DEFAULT_COMMAND,
        popen: Callable[..., Any] = subprocess.Popen,
        check_scorer: Optional[Callable[..., Any]] = None,
    ):
        self.port = port
        self.supervisor = Supervisor(command, popen)
        self.check_scorer = check_scorer
        self._check_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._clear_stale_checks()

    # -- plumbing ----------------------------------------------------------

    def _clear_stale_checks(self) -> None:
        """A check flagged in progress when the server starts died with the
        previous server; clear it so the page does not wait forever."""
        for record in runrecord.list_runs():
            if record.get("check_status") == "checking":
                try:
                    runrecord.set_check_status(record["id"], None)
                except (OSError, ValueError):
                    pass

    def _allowed_hosts(self) -> Tuple[str, ...]:
        return (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def _guard(self, request: Request) -> None:
        host = (request.header("Host") or "").strip().lower()
        if host not in self._allowed_hosts():
            raise ApiError(403, "Requests must come from this machine's own page.")
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.header("Origin")
            if origin is not None and origin.lower() not in (
                f"http://{h}" for h in self._allowed_hosts()
            ):
                raise ApiError(403, "Requests from other sites are refused.")
            content_type = (request.header("Content-Type") or "").split(";")[0].strip()
            if content_type.lower() != "application/json":
                raise ApiError(403, "Changes must be sent as JSON.")

    def dispatch(self, request: Request) -> Response:
        try:
            self._guard(request)
            response = self._route(request)
        except ApiError as exc:
            response = _json_response(exc.status, dict(error=exc.message, **exc.extra))
        except runrecord.InvalidRunId:
            response = _json_response(404, {"error": "No such run."})
        except FileNotFoundError:
            response = _json_response(404, {"error": "No such run."})
        except runrecord.UnsupportedSchema as exc:
            response = _json_response(409, {"error": str(exc)})
        except Exception as exc:  # the page gets an answer, never a dropped connection
            traceback.print_exc()
            response = _json_response(500, {"error": f"Something went wrong: {exc}"})
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    def _body(self, request: Request) -> Dict[str, Any]:
        if not request.body:
            return {}
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "The request body is not valid JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "The request body must be a JSON object.")
        return data

    def _route(self, request: Request) -> Response:
        parts = urlsplit(request.path)
        path = parts.path
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        method = request.method

        if method == "GET" and path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            return Response(200, (STATIC_DIR / name).read_bytes(), content_type)

        segments = [p for p in path.split("/") if p]
        if len(segments) < 2 or segments[0] != "api":
            raise ApiError(404, "Not found.")
        rest = segments[1:]

        if rest == ["settings"] and method == "GET":
            return self.get_settings()
        if rest == ["ui-settings"] and method == "POST":
            return self.save_ui_settings(self._body(request))
        if rest == ["validate"] and method == "POST":
            return self.validate(self._body(request))
        if rest == ["active"] and method == "GET":
            return self.get_active()
        if rest == ["compare"] and method == "GET":
            return self.get_compare(query.get("ids", ""))
        if rest == ["runs"]:
            if method == "GET":
                return self.list_runs()
            if method == "POST":
                return self.start_run(self._body(request))
        if len(rest) >= 2 and rest[0] == "runs":
            run_id = runrecord.validate_run_id(rest[1])
            action = rest[2:] or [""]
            if len(action) == 1:
                handler = {
                    ("GET", ""): lambda: self.get_run(run_id),
                    ("DELETE", ""): lambda: self.delete_run(run_id),
                    ("POST", "stop"): lambda: self.stop_run(run_id),
                    ("GET", "rerun"): lambda: self.get_rerun(run_id),
                    ("POST", "check"): lambda: self.start_check(run_id),
                    ("POST", "install"): lambda: self.install(run_id, self._body(request)),
                    ("POST", "rename"): lambda: self.rename(run_id, self._body(request)),
                    ("GET", "name"): lambda: self.preview_name(run_id, query),
                    ("GET", "download"): lambda: self.download(run_id),
                    ("GET", "plan.svg"): lambda: self.svg(run_id, "plan"),
                    ("GET", "iso.svg"): lambda: self.svg(run_id, "iso", query),
                    ("GET", "profile.svg"): lambda: self.svg(run_id, "profile"),
                    ("GET", "fitness.svg"): lambda: self.svg(run_id, "fitness"),
                }.get((method, action[0]))
                if handler is not None:
                    return handler()
        raise ApiError(404, "Not found.")

    # -- settings ----------------------------------------------------------

    def get_settings(self) -> Response:
        return _json_response(200, {
            "settings": settings.table(),
            "estimate_note": settings.ESTIMATE_NOTE,
            "availability": openrct2_paths.availability().to_dict(),
            "ui": openrct2_paths.load_ui_settings(),
            "restart_note": RESTART_NOTE,
            "template_fields": list(openrct2_paths.TEMPLATE_FIELDS),
        })

    def save_ui_settings(self, body: Dict[str, Any]) -> Response:
        try:
            saved = openrct2_paths.save_ui_settings(body)
        except openrct2_paths.InvalidName as exc:
            raise ApiError(400, str(exc))
        return _json_response(200, {"ui": saved})

    def validate(self, body: Dict[str, Any]) -> Response:
        result = settings.validate(body.get("values") or {})
        return _json_response(200, {"ok": result.ok, "errors": result.errors})

    # -- runs --------------------------------------------------------------

    def _running(self) -> List[Dict[str, Any]]:
        return [r for r in runrecord.list_runs() if r.get("status") == "running"]

    def _stoppable(self, run_id: str, record: Dict[str, Any]) -> bool:
        return self.supervisor.owns(run_id) or runrecord.can_signal(record)

    def get_active(self) -> Response:
        running = self._running()
        if not running:
            return _json_response(200, {"active": None})
        run = runrecord.load_run(running[0]["id"])
        detail = run_detail(run)
        detail["stoppable"] = self._stoppable(run.id, run.record)
        return _json_response(200, {"active": detail})

    def list_runs(self) -> Response:
        records = runrecord.list_runs()
        names = runrecord.name_unnamed_runs(records)
        return _json_response(200, {"runs": [_list_entry(r, names.get(r["id"])) for r in records]})

    def _ensure_named(self, run_id: str) -> None:
        """Name a run opened before the library was ever listed."""
        if runrecord.saved_name(run_id) is None:
            runrecord.name_unnamed_runs()

    def get_run(self, run_id: str) -> Response:
        self._ensure_named(run_id)
        run = runrecord.load_run(run_id)
        detail = run_detail(run)
        detail["stoppable"] = self._stoppable(run_id, run.record)
        detail["availability"] = openrct2_paths.availability().to_dict()
        return _json_response(200, {"run": detail})

    def get_rerun(self, run_id: str) -> Response:
        record = runrecord.load_record(run_id)
        values = settings.form_values(record.get("request") or {})
        if values.get("seed") is None:
            values["seed"] = record.get("seed")
        return _json_response(200, {"values": values, "parent": run_id})

    def start_run(self, body: Dict[str, Any]) -> Response:
        values = body.get("values")
        if not isinstance(values, dict):
            raise ApiError(400, "Send the form values to start a run.")
        parent = body.get("parent")
        if parent is not None:
            runrecord.load_record(parent)  # must be a real saved run

        result = settings.validate(values)
        if not result.ok:
            return _json_response(400, {"error": "Some settings need fixing.",
                                        "errors": result.errors})

        chosen = dict(result.values)
        if chosen.get("seed") is None:
            chosen["seed"] = random.SystemRandom().randint(0, settings.SEED_MAX)

        # Held from the one-at-a-time check until the child has written its
        # record, so two quick clicks cannot both start a run.
        with self._start_lock:
            running = self._running()
            if running:
                raise ApiError(409, "A run is already going. Only one run can be "
                                    "active at a time.", active=running[0]["id"])
            run_id = self._new_id(chosen["seed"])
            directory = runrecord.run_dir(run_id)
            args = settings.cli_args(chosen) + [
                "--run-id", run_id,
                "--output", str(directory / runrecord.BEST_TD6),
                "--oracle-log", str(directory / ORACLE_LOG),
            ]
            if parent is not None:
                args += ["--parent-run", parent]
            self.supervisor.start(run_id, args)
        return _json_response(201, {"id": run_id})

    def _new_id(self, seed: int) -> str:
        base = runrecord.new_run_id(seed)
        run_id, suffix = base, 1
        while runrecord.run_dir(run_id).exists():
            suffix += 1
            run_id = f"{base}-{suffix}"
        return run_id

    def stop_run(self, run_id: str) -> Response:
        if self.supervisor.owns(run_id):
            record = runrecord.load_record(run_id)
            if record.get("status") != "running":
                raise ApiError(409, "This run is not running.")
            self.supervisor.stop(run_id)
            return _json_response(202, {"stopping": run_id})
        # Not started by this server: only signal it directly when generide
        # can positively confirm the recorded pid is still the process that
        # started this run -- see runrecord.can_signal.
        try:
            runrecord.signal_stop(run_id)
        except runrecord.RunNotRunning:
            raise ApiError(409, "This run is not running.")
        except runrecord.CannotVerifyProcess:
            raise ApiError(
                409,
                "This run was not started from this page, and generide "
                "cannot confirm its process is still the one that started "
                "it. Stop it from the terminal it is running in, with "
                "Ctrl-C.",
            )
        return _json_response(202, {"stopping": run_id})

    def delete_run(self, run_id: str) -> Response:
        try:
            runrecord.delete_run(run_id)
        except runrecord.RunIsActive:
            raise ApiError(409, "This run is still going. Stop it before deleting it.")
        return _json_response(200, {"deleted": run_id})

    def get_compare(self, ids: str) -> Response:
        run_ids = [i for i in ids.split(",") if i]
        if not 2 <= len(run_ids) <= 3:
            raise ApiError(400, "Pick two or three runs to compare.")
        runs = [runrecord.load_run(runrecord.validate_run_id(i)) for i in run_ids]
        return _json_response(200, compare(runs))

    # -- check, install, download -------------------------------------------

    def _require_finished(self, record: Dict[str, Any]) -> None:
        # The CLI writes best.td6 a moment before it finishes the record;
        # touching the record in that window could lose one of the writes.
        if record.get("status") == "running":
            raise ApiError(409, "This run is still going. Wait for it to finish.")

    def start_check(self, run_id: str) -> Response:
        self._require_finished(runrecord.load_record(run_id))
        if not (runrecord.run_dir(run_id) / runrecord.BEST_TD6).is_file():
            raise ApiError(409, "This run has no exported ride to check.")
        state = openrct2_paths.availability()
        if not state.check:
            raise ApiError(409, state.check_reason)
        with self._check_lock:
            record = runrecord.load_record(run_id)
            if record.get("check_status") == "checking":
                raise ApiError(409, "This ride is already being checked.")
            calibrating = [
                r["id"] for r in self._running()
                if (r.get("request") or {}).get("oracle_calibrate")
            ]
            if calibrating:
                raise ApiError(
                    409,
                    "A run that calibrates against the game is going, and it uses "
                    "the game the same way a check does. Check once it finishes.",
                    active=calibrating[0],
                )
            runrecord.set_check_status(run_id, "checking")
            threading.Thread(
                target=openrct2_paths.run_check, args=(run_id,),
                kwargs={"scorer": self.check_scorer}, daemon=True,
            ).start()
        return _json_response(202, {"checking": run_id})

    def _final_name(self, record: Dict[str, Any], name: Any, template: Any) -> str:
        if not isinstance(name, str):
            raise ApiError(400, "Enter a name for the ride.", field="name")
        try:
            if template:
                if not isinstance(template, str):
                    raise openrct2_paths.InvalidName("The template must be text.")
                return openrct2_paths.apply_template(
                    template, name=name.strip(), seed=record.get("seed"),
                )
            return openrct2_paths.sanitize_name(name)
        except openrct2_paths.InvalidName as exc:
            raise ApiError(400, str(exc), field="name")

    def rename(self, run_id: str, body: Dict[str, Any]) -> Response:
        runrecord.load_record(run_id)  # a 404 for a run that is not there
        try:
            name = runrecord.set_run_name(run_id, body.get("name"))
        except runrecord.InvalidRunName as exc:
            raise ApiError(400, str(exc), field="name")
        return _json_response(200, {"name": name})

    def preview_name(self, run_id: str, query: Dict[str, str]) -> Response:
        record = runrecord.load_record(run_id)
        final = self._final_name(record, query.get("name", ""), query.get("template"))
        exists = (openrct2_paths.track_dir() / f"{final}.td6").exists()
        return _json_response(200, {"name": final, "exists": exists})

    def install(self, run_id: str, body: Dict[str, Any]) -> Response:
        run = runrecord.load_run(run_id)
        self._require_finished(run.record)
        final = self._final_name(run.record, body.get("name"), body.get("template"))
        warnings = _warnings(run_detail(run)["best"], run.record)
        if warnings and body.get("confirm") is not True:
            raise ApiError(409, "This ride has problems. Install it anyway?",
                           needs_confirmation=True, warnings=warnings, name=final)
        try:
            entry = openrct2_paths.install(run_id, final, replace=body.get("replace") is True)
        except openrct2_paths.InstallConflict as exc:
            raise ApiError(409, f"A design named {exc.name} is already installed.",
                           conflict=True, name=exc.name)
        except openrct2_paths.GameUnavailable as exc:
            raise ApiError(409, str(exc))
        except FileNotFoundError:
            raise ApiError(409, "This run has no exported ride to install.")
        return _json_response(200, {"install": entry, "restart_note": RESTART_NOTE})

    def download(self, run_id: str) -> Response:
        path = runrecord.run_dir(run_id) / runrecord.BEST_TD6
        if not path.is_file():
            raise ApiError(404, "This run has no exported ride.")
        record = runrecord.load_record(run_id)
        try:
            filename = openrct2_paths.sanitize_name(runrecord.run_name(record))
        except openrct2_paths.InvalidName:
            filename = run_id
        filename = filename.encode("ascii", "replace").decode().replace('"', "'")
        return Response(200, path.read_bytes(), "application/octet-stream", {
            "Content-Disposition": f'attachment; filename="{filename}.td6"',
        })

    def svg(self, run_id: str, kind: str, query: Optional[Dict[str, str]] = None) -> Response:
        run = runrecord.load_run(run_id)
        if kind == "fitness":
            body = render.render_fitness_history(
                [p["best_fitness"] for p in run.progress], title="Best score by generation",
            )
        else:
            segments = run.improvements[-1]["segments"] if run.improvements else []
            if kind == "plan":
                body = render.render_track(segments, title="Top-down plan")
            elif kind == "iso":
                body = render.render_isometric(
                    segments, angle=_quarter_turns((query or {}).get("angle")), title="Ride view",
                )
            else:
                body = render.render_profile(segments, title="Side profile")
        return Response(200, body.encode("utf-8"), "image/svg+xml; charset=utf-8")


# ---------------------------------------------------------------------------
# HTTP adapter
# ---------------------------------------------------------------------------

MAX_BODY = 1_000_000


def _handler_for(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "generide"
        sys_version = ""

        def _serve(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0:
                self.send_error(400)
                return
            if length > MAX_BODY:
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else b""
            response = app.dispatch(Request(
                method=self.command, path=self.path,
                headers={k: v for k, v in self.headers.items()}, body=body,
            ))
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response.body)

        do_GET = do_POST = do_DELETE = _serve

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # the page polls every second; logging each poll is noise

    return Handler


def make_server(port: int = 0, **app_kwargs: Any) -> Tuple[ThreadingHTTPServer, App]:
    """Bind 127.0.0.1 (never any other interface) and wire up the app."""
    app = App(port=port, **app_kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler_for(app))
    server.daemon_threads = True
    app.port = server.server_address[1]
    return server, app
