#!/usr/bin/env python3
"""Assemble generide's in-browser page into a static site.

Usage:
    npm ci --prefix demo          # once, for the pinned Pyodide runtime
    python tools/build_demo.py    # writes _site/
    python tools/build_demo.py --out /tmp/site

The site is three things side by side:

- the page itself, from demo/ (plus the local web UI's tokens.css, style.css,
  and iso-view.js, so both pages look and draw the ride the same way)
- the Pyodide runtime, copied from demo/node_modules/pyodide, so the page
  depends on no CDN (see the plan, KTD1)
- the engine: every rct2/*.py module, evolve_coaster.py, and the Mine Train
  template .td6, packed into one zip the worker unpacks into Pyodide's
  filesystem. engine.json names it by content hash, so a browser never runs
  a stale engine from its cache after a deploy.
"""

import argparse
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "demo"

PAGE_FILES = ("index.html", "app.js", "worker.js", "demo.css")
SHARED_CSS = ("tokens.css", "style.css")
# The isometric ride view, drawn by the same script as in the local web UI.
SHARED_JS = ("iso-view.js",)
PYODIDE_FILES = (
    "pyodide.mjs",
    "pyodide.asm.mjs",
    "pyodide.asm.wasm",
    "python_stdlib.zip",
    "pyodide-lock.json",
)
TEMPLATE = Path("data") / "sample_rides" / "manic_miner_test.td6"


def page_version(repo: Path = REPO) -> str:
    """A short hash of every file the page is made of, apart from the engine.

    The engine is named by its own hash, but the page's scripts keep their
    names, so a browser can hold an old copy of one while it fetches the new
    engine. The build writes this version into both the page script and the
    engine manifest, and the page compares them (see `showStale` in
    demo/app.js).
    """
    digest = hashlib.sha256()
    sources = [repo / "demo" / name for name in PAGE_FILES]
    sources += [repo / "rct2" / "webui_static" / name for name in SHARED_CSS + SHARED_JS]
    for path in sorted(sources, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def engine_files(repo: Path = REPO):
    """Repo-relative paths of everything a run needs, in a stable order."""
    files = sorted(p.relative_to(repo) for p in (repo / "rct2").glob("*.py"))
    files.append(Path("evolve_coaster.py"))
    files.append(TEMPLATE)
    return files


def engine_archive(repo: Path = REPO) -> bytes:
    """The engine as zip bytes. Fixed timestamps keep the hash reproducible."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in engine_files(repo):
            info = zipfile.ZipInfo(rel.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (repo / rel).read_bytes())
    return buffer.getvalue()


def build(out: Path, pyodide_dir: Path, repo: Path = REPO) -> Path:
    if not pyodide_dir.is_dir():
        raise SystemExit(
            f"Pyodide runtime not found at {pyodide_dir}. "
            "Run `npm ci --prefix demo` first."
        )
    missing = [name for name in PYODIDE_FILES if not (pyodide_dir / name).is_file()]
    if missing:
        raise SystemExit(f"Pyodide runtime at {pyodide_dir} is missing: {', '.join(missing)}")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in PAGE_FILES:
        shutil.copy2(repo / "demo" / name, out / name)
    for name in SHARED_CSS + SHARED_JS:
        shutil.copy2(repo / "rct2" / "webui_static" / name, out / name)
    version = page_version(repo)
    script = out / "app.js"
    script.write_text(script.read_text().replace("__PAGE_VERSION__", version))

    runtime = out / "pyodide"
    runtime.mkdir()
    for name in PYODIDE_FILES:
        shutil.copy2(pyodide_dir / name, runtime / name)

    data = engine_archive(repo)
    digest = hashlib.sha256(data).hexdigest()[:16]
    archive_name = f"engine-{digest}.zip"
    (out / archive_name).write_bytes(data)
    (out / "engine.json").write_text(
        json.dumps({"archive": archive_name, "sha256": digest, "page": version}) + "\n"
    )
    # GitHub Pages runs Jekyll unless told not to, and Jekyll drops files
    # whose names start with an underscore.
    (out / ".nojekyll").write_text("")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build generide's in-browser page")
    parser.add_argument("--out", type=Path, default=REPO / "_site", help="output folder (default: _site)")
    parser.add_argument(
        "--pyodide", type=Path, default=DEMO / "node_modules" / "pyodide",
        help="Pyodide runtime folder (default: demo/node_modules/pyodide)",
    )
    args = parser.parse_args(argv)
    out = build(args.out, args.pyodide)
    print(f"Built the page into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
