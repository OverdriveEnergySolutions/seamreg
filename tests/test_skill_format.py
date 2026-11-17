"""The skill follows the Agent Skills format (https://agentskills.io/specification), so agents
other than Claude Code can load it from ~/.agents/skills or a project's .agents/skills.

The rules below are the spec's, as read on 2026-11-15. The reference validator
(`skills-ref validate`, agentskills commit 83021e2) also passed skills/seams that day.
This test needs no download."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter between --- lines"
    fields = {}
    for line in m.group(1).split("\n"):
        if line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, text[m.end():]


def test_there_is_a_skill():
    assert SKILLS


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_meets_the_agent_skills_spec(path):
    fields, body = frontmatter(path.read_text(encoding="utf-8"))
    assert set(fields) <= FIELDS, f"fields the spec does not define: {set(fields) - FIELDS}"
    name = fields.get("name", "")
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64, \
        "name: 1 to 64 lowercase letters, digits and single hyphens, not at either end"
    assert name == path.parent.name, "name must match the skill's folder name"
    assert 1 <= len(fields.get("description", "")) <= 1024, "description: 1 to 1024 characters"
    if "compatibility" in fields:
        assert 1 <= len(fields["compatibility"]) <= 500
    assert body.count("\n") < 500, "the spec asks for a SKILL.md under 500 lines"
