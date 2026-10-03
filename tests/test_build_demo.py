"""Tests for tools/build_demo.py, which assembles the in-browser page.

The build needs the Pyodide runtime from npm, which CI's Python job does not
install, so these tests point it at a stand-in folder with the right file
names. Whether the real runtime runs the engine is the browser tests' job
(demo/tests/).
"""

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_demo  # noqa: E402


@pytest.fixture
def fake_pyodide(tmp_path):
    folder = tmp_path / "pyodide"
    folder.mkdir()
    for name in build_demo.PYODIDE_FILES:
        (folder / name).write_text("stand-in")
    return folder


def test_build_writes_the_page_runtime_and_engine(tmp_path, fake_pyodide):
    out = build_demo.build(tmp_path / "site", fake_pyodide)
    for name in build_demo.PAGE_FILES + build_demo.SHARED_CSS:
        assert (out / name).is_file(), name
    for name in build_demo.PYODIDE_FILES:
        assert (out / "pyodide" / name).is_file(), name
    manifest = json.loads((out / "engine.json").read_text())
    assert (out / manifest["archive"]).is_file()
    assert manifest["archive"] == f"engine-{manifest['sha256']}.zip"
    assert (out / ".nojekyll").is_file()


def test_engine_archive_holds_the_run_module_its_imports_and_the_template():
    names = set(zipfile.ZipFile(io.BytesIO(build_demo.engine_archive())).namelist())
    assert "rct2/demo.py" in names
    assert "evolve_coaster.py" in names
    assert "data/sample_rides/manic_miner_test.td6" in names


def test_the_unpacked_engine_runs_on_its_own(tmp_path):
    # Imports rct2.demo from nothing but the archive and runs a tiny ride, so
    # a module the run needs but the archive leaves out fails here, not in a
    # visitor's browser.
    with zipfile.ZipFile(io.BytesIO(build_demo.engine_archive())) as archive:
        archive.extractall(tmp_path / "engine")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from rct2 import demo;"
        "r = demo.run({'seed': 5}, lambda k, p: None, generations=2, population=6);"
        "assert r['td6'] is not None or not r['summary']['valid'];"
        "assert demo.__file__.startswith(sys.argv[1])"
    )
    subprocess.run(
        [sys.executable, "-I", "-c", code, str(tmp_path / "engine")],
        cwd=tmp_path, check=True, capture_output=True,
    )


def test_archive_hash_is_stable_between_builds():
    assert build_demo.engine_archive() == build_demo.engine_archive()


def test_missing_runtime_names_the_folder(tmp_path):
    missing = tmp_path / "nowhere"
    with pytest.raises(SystemExit) as error:
        build_demo.build(tmp_path / "site", missing)
    assert str(missing) in str(error.value)
