"""The agent files' effort floors match the standard preset, so a start that forgets to set an
effort runs at the measured value instead of the session's."""
from __future__ import annotations

import re
from pathlib import Path

from seams import presets

ROOT = Path(__file__).resolve().parents[1]


def frontmatter(agent):
    text = (ROOT / "agents" / f"{agent}.md").read_text()
    head = text.split("---", 2)[1]
    return dict(re.findall(r"^(\w+): (.+)$", head, re.M))


def test_agent_effort_floors_match_the_standard_preset():
    for step, agent in presets.AGENT.items():
        assert frontmatter(agent).get("effort") == presets.DEFINITIONS["standard"][step]["effort"], agent


def test_pinned_models_match_the_standard_preset():
    # seam-reviewer and seam-drift-checker inherit the session's model; the skill sets it on each start.
    for step, agent in presets.AGENT.items():
        model = frontmatter(agent)["model"]
        assert model in ("inherit", presets.DEFINITIONS["standard"][step]["model"]), agent
