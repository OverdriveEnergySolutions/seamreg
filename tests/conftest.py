# fixtures/ holds sample repos for the scan. Their test files are data, not tests.
collect_ignore_glob = ["fixtures/*"]

import pytest


@pytest.fixture(autouse=True)
def _own_state_folder(tmp_path_factory, monkeypatch):
    """`seams run start` writes a marker in the user's state folder. Keep tests out of the real one."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("state")))
