"""Shared fixtures.

Every test runs with `GENERIDE_HOME` pointed at its own temp folder. The CLI
now saves a run record for every run, and the web UI keeps its settings next
to the library, so without this a test run would write into the developer's
real home folder, or the CI runner's.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_generide_home(tmp_path, monkeypatch):
    home = tmp_path / "generide-home"
    monkeypatch.setenv("GENERIDE_HOME", str(home))
    return home
