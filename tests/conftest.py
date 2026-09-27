"""Shared fixtures.

Every test runs with generide's own folder and every OpenRCT2 location
pointed into its own temp folder. The CLI now saves a run record for every
run, the web UI keeps its settings next to the library, and check and
install write into the game's folders, so without this a test run would
write into the developer's real home folder or game install, or the CI
runner's. The game paths point at things that do not exist, so the game
reads as unavailable unless a test sets it up on purpose.
"""

import pytest

from rct2 import oracle


@pytest.fixture(autouse=True)
def isolated_generide_home(tmp_path, monkeypatch):
    home = tmp_path / "generide-home"
    monkeypatch.setenv("GENERIDE_HOME", str(home))
    monkeypatch.setenv("GENERIDE_OPENRCT2_BINARY", str(tmp_path / "no-openrct2" / "OpenRCT2"))
    monkeypatch.setenv("GENERIDE_TRACK_DIR", str(tmp_path / "no-openrct2" / "track"))
    monkeypatch.setattr(oracle, "PLUGIN_DIR", tmp_path / "no-openrct2" / "plugin")
    return home
