"""Ties for this repo's own seams. Each test is named in seams.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

from seams import check, cli

ROOT = Path(__file__).resolve().parents[1]


def test_own_registry_is_true():
    assert check.check(check.load(ROOT / "seams.json"), ROOT) == []


def test_committed_schema_matches_generated():
    committed = json.loads((ROOT / "schema/seams.schema.json").read_text())
    assert committed == check.SCHEMA, "run: seams schema --write schema/seams.schema.json"


def test_versions_agree():
    pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
    assert pyproject.group(1) == plugin == check.__version__


def test_documented_commands_exist():
    parser = cli.build_parser()
    real = set(parser._subparsers._group_actions[0].choices)
    for doc in ("README.md", "skills/seams/SKILL.md", "skills/seams-review/SKILL.md"):
        named = set(re.findall(r"`seams ([a-z]+(?:-[a-z]+)*)", (ROOT / doc).read_text()))  # looked-at
        assert named, f"{doc} names no command"
        assert named <= real, f"{doc} names commands that do not exist: {named - real}"
