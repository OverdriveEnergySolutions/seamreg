"""seams tie: packets for the tie writer, and collect, which adds only proven ties."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seams import check, cli, tie

SEAM = {
    "id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
    "must_agree": "Both lists hold the same names.",
    "copies": [{"path": "api/status.py", "symbol": "STATUSES"}, {"path": "web/status.ts"}],
    "consequence": "The web app drops a status.", "risk": "high",
    "suggested_tie": "compare the two lists",
}
LOW = dict(SEAM, id="low-one", risk="low", suggested_tie=None)
TIED = dict(SEAM, id="tied-one", ties=[{"path": "tests/test_status.py", "covers": "all"}])


@pytest.fixture
def repo(tmp_path):
    files = {"api/status.py": "STATUSES = ['new']\n", "web/status.ts": "export const S = ['new']\n",
             "tests/test_status.py": "def test_status_names_match():\n    pass\n",
             "api/tests/test_api.py": "", "web/status.test.ts": "", "pyproject.toml": "[tool.pytest.ini_options]\n",
             "web/package.json": json.dumps({"devDependencies": {"vitest": "1"}, "scripts": {"test": "vitest"}})}
    for f, text in files.items():
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text(text)
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [LOW, SEAM, TIED]}))
    return tmp_path


def result(repo, **kw):
    res = {"id": "order-statuses", "path": "tests/test_status.py", "test": "test_status_names_match",
           "covers": "all", "note": None, "command": "pytest tests/test_status.py", "passes": True,
           "expected_failure": False,
           "mutations": [{"copy": "api/status.py", "change": "added 'lost'", "failed": True},
                         {"copy": "web/status.ts", "change": "removed 'new'", "failed": True}],
           "files_written": ["tests/test_status.py"], "reason": None}
    res.update(kw)
    d = repo / ".seams-scan" / "tie" / "results"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{res['id']}.json").write_text(json.dumps(res))
    return res


def collect(repo):
    lines, errors, counts = tie.collect(repo / "seams.json", repo, repo / ".seams-scan")
    seam = [s for s in json.loads((repo / "seams.json").read_text())["seams"] if s["id"] == "order-statuses"][0]
    return "\n".join(lines), seam, counts


# --- what the agent is given ---------------------------------------------------------

def test_frameworks_found_from_config(repo):
    (repo / "go.mod").write_text("module x\n")
    names = [f["name"] for f in tie.frameworks(repo)]
    assert names[:1] == ["pytest"] and "vitest" in names and "go test" in names
    vit = [f for f in tie.frameworks(repo) if f["name"] == "vitest"][0]
    assert vit["evidence"] == "web/package.json" and "npm test in web" in vit["run"]


def test_no_framework_found(tmp_path):
    assert tie.frameworks(tmp_path) == []


def test_nearby_tests_come_first(repo):
    near = tie.nearby_tests(repo, [{"path": "web/status.ts"}])
    assert near[0] == "web/status.test.ts"
    assert set(near) == {"web/status.test.ts", "tests/test_status.py", "api/tests/test_api.py"}


def test_packet_names_copies_frameworks_and_the_output(repo):
    chosen, fws = tie.write_packets(repo / "seams.json", repo, repo / ".seams-scan", ["order-statuses"])
    text = (repo / ".seams-scan/tie/packets/order-statuses.md").read_text()
    assert "`api/status.py` (`STATUSES`)" in text and "`web/status.ts`" in text
    assert "pytest (python), seen in `pyproject.toml`" in text
    assert "results/order-statuses.json" in text and "compare the two lists" in text
    assert "expected failure" not in text  # no drift recorded
    assert (repo / ".seams-scan/tie/brief.md").read_text() == tie.BRIEF.read_text()


def test_packet_for_a_drifted_seam_asks_for_an_expected_failure(repo):
    data = json.loads((repo / "seams.json").read_text())
    data["seams"][1]["drift"] = {"text": "web lacks 'lost'", "source": "reading"}
    (repo / "seams.json").write_text(json.dumps(data))
    tie.write_packets(repo / "seams.json", repo, repo / ".seams-scan", ["order-statuses"])
    text = (repo / ".seams-scan/tie/packets/order-statuses.md").read_text()
    assert "web lacks 'lost'" in text and "expected failure" in text and "Do not fix the drift" in text


def test_unknown_id_is_refused_before_old_packets_go(repo):
    tie.write_packets(repo / "seams.json", repo, repo / ".seams-scan", ["order-statuses"])
    with pytest.raises(ValueError, match="no-such"):
        tie.write_packets(repo / "seams.json", repo, repo / ".seams-scan", ["no-such"])
    assert (repo / ".seams-scan/tie/packets/order-statuses.md").exists()


def test_untied_picks_untied_seams_highest_risk_first(repo):
    data = json.loads((repo / "seams.json").read_text())
    assert tie.untied(data) == ["order-statuses"]
    assert tie.untied(data, ("high", "low")) == ["order-statuses", "low-one"]


def test_brief_examples_are_invented():
    # Benchmark content in reviewer-visible text hands a later run its answers.
    text = tie.BRIEF.read_text()
    for word in ("umami", "netbox", "frigate", "kuma", "memos", "pocock"):
        assert word not in text.lower()


# --- collect -------------------------------------------------------------------------

def test_a_proven_tie_is_added_and_clears_the_suggestion(repo):
    result(repo)
    out, seam, counts = collect(repo)
    assert counts == {"files": 1, "added": 1, "refused": 0}
    assert seam["ties"] == [{"path": "tests/test_status.py", "test": "test_status_names_match", "covers": "all"}]
    assert seam["suggested_tie"] is None and "tie added" in out
    assert check.check(json.loads((repo / "seams.json").read_text()), repo) == []


def test_collect_twice_adds_the_tie_once(repo):
    result(repo)
    collect(repo)
    out, seam, counts = collect(repo)
    assert len(seam["ties"]) == 1 and "already" in out


@pytest.mark.parametrize("kw, says", [
    ({"path": None, "reason": "needs a live database"}, "needs a live database"),
    ({"covers": None}, "does not say what the tie covers"),
    ({"covers": "partial"}, "must say which copies"),
    ({"passes": False}, "does not pass"),
    ({"expected_failure": True, "passes": False}, "records no drift"),
    ({"mutations": []}, "no mutation was run"),
    ({"mutations": [{"copy": "api/status.py", "change": "x", "failed": True},
                    {"copy": "web/status.ts", "change": "y", "failed": False}]}, "still passed"),
    ({"covers": "partial", "note": "n", "mutations": [{"copy": "web/status.ts", "change": "y", "failed": False}]},
     "passed after every mutation"),
    ({"mutations": [{"copy": "api/status.py", "change": "x", "failed": True}]}, "fewer than two"),
    ({"test": "test_missing"}, "does not appear"),
    ({"path": "tests/nope.py"}, "does not exist"),
])
def test_unproven_ties_are_not_added(repo, kw, says):
    result(repo, **kw)
    out, seam, counts = collect(repo)
    assert counts["added"] == 0 and counts["refused"] == 1
    assert "ties" not in seam and says in out


def test_partial_tie_with_a_note_and_one_mutation_is_added(repo):
    result(repo, covers="partial", note="reads api/status.py only",
           mutations=[{"copy": "api/status.py", "change": "x", "failed": True}])
    _, seam, counts = collect(repo)
    assert counts["added"] == 1 and seam["ties"][0]["note"] == "reads api/status.py only"
    assert seam["suggested_tie"] == "compare the two lists"  # a partial tie leaves the suggestion


def test_a_partial_tie_may_miss_a_copy_it_does_not_read(repo):
    result(repo, covers="partial", note="reads api only",
           mutations=[{"copy": "api/status.py", "change": "x", "failed": True},
                      {"copy": "web/status.ts", "change": "y", "failed": False}])
    out, seam, counts = collect(repo)
    assert counts["added"] == 1 and "Still passed when changed (not covered): web/status.ts (y)" in out


def test_an_expected_failure_on_a_drifted_seam_is_added(repo):
    data = json.loads((repo / "seams.json").read_text())
    data["seams"][1]["drift"] = {"text": "web lacks 'lost'", "source": "reading"}
    (repo / "seams.json").write_text(json.dumps(data))
    result(repo, passes=False, expected_failure=True)
    out, seam, counts = collect(repo)
    assert counts["added"] == 1 and "remove the marker" in out


def test_a_glob_copy_counts_each_matching_mutation(repo):
    data = json.loads((repo / "seams.json").read_text())
    data["seams"][1]["copies"] = [{"path": "api/*.py"}, {"path": "web/*.ts"}]
    (repo / "seams.json").write_text(json.dumps(data))
    result(repo)
    assert collect(repo)[2]["added"] == 1


def test_a_malformed_result_is_reported(repo):
    d = repo / ".seams-scan/tie/results"
    d.mkdir(parents=True)
    (d / "x.json").write_text('{"id": "order-statuses"}')
    (d / "y.json").write_text("not json")
    out, seam, counts = collect(repo)
    assert counts["refused"] == 2 and "wrong shape" in out and "could not be read" in out


# --- the command ---------------------------------------------------------------------

def test_cli_writes_packets_and_collects(repo, capsys):
    assert cli.main(["tie", "--root", str(repo), "--untied"]) == 0
    out = capsys.readouterr().out
    assert "1 tie packet(s)" in out and "pytest (pyproject.toml)" in out
    result(repo)
    assert cli.main(["tie", "--root", str(repo), "--collect"]) == 0
    assert "1 tie(s) added" in capsys.readouterr().out
    assert (repo / ".seams-scan/tie/tie-report.md").exists()


def test_cli_with_no_ids_says_what_to_pass(repo, capsys):
    assert cli.main(["tie", "--root", str(repo)]) == 2
    assert "--untied" in capsys.readouterr().err


def test_the_agent_file_points_at_the_command():
    agent = (Path(tie.__file__).parents[2] / "agents" / "seam-tie-writer.md").read_text()
    assert "name: seam-tie-writer" in agent and "`seams tie`" in agent
