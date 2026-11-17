"""The pass ledger, `seams next` and `seams triage`."""
from __future__ import annotations

import json
import os
import time

import pytest

from seams import cli, passes


def seam(sid, risk="high", drift=None, **kw):
    s = {"id": sid, "title": f"t {sid}", "kind": "vocabulary", "must_agree": "agree",
         "copies": [{"path": "a.py"}, {"path": "b.py"}], "consequence": "c", "risk": risk}
    if drift:
        s["drift"] = {"text": drift[1], "source": drift[0]}
    s.update(kw)
    return s


def reg(*seams):
    return {"schema_version": 1, "seams": list(seams)}


@pytest.fixture
def repo(tmp_path):
    for f in ("a.py", "b.py"):
        (tmp_path / f).write_text("x\n")
    (tmp_path / ".seams-scan").mkdir()
    return tmp_path


def write_reg(repo, data, proposal=False):
    path = repo / (".seams-scan/seams.proposed.json" if proposal else "seams.json")
    path.write_text(json.dumps(data))
    return path


def merged(repo, data):
    """A merge after the last pass: the proposal is newer than the pass's start."""
    time.sleep(0.01)
    p = write_reg(repo, data, proposal=True)
    future = time.time() + 2
    os.utime(p, (future, future))


# --- the ledger ---------------------------------------------------------------------

def test_yields_come_from_the_pictures(repo):
    out = repo / ".seams-scan"
    passes.record_pass(out, "first", 3, 40, None)
    passes.record_pass(out, "gap", 3, 30, reg(seam("a"), seam("b", "low", ("reading", "x"))))
    ys = passes.yields(passes.load_ledger(out), reg(seam("a"), seam("b", "low", ("reading", "x")),
                                                    seam("c", "medium", ("reading", "y")), seam("a2", drift=("reading", "z"))))
    assert ys[0]["new"] == {"high": 1, "medium": 0, "low": 1} and ys[0]["new_drift"] == 1
    assert ys[1]["new"] == {"high": 1, "medium": 1, "low": 0} and ys[1]["new_drift"] == 2


def test_a_damaged_ledger_reads_as_empty(repo):
    (repo / ".seams-scan" / "passes.json").write_text("not json")
    assert passes.load_ledger(repo / ".seams-scan") == {"passes": []}


def test_split_records_each_pass(repo, capsys):
    (repo / ".seams-scan" / "leads.json").write_text(json.dumps({"files": {}, "leads": [], "units": []}))
    cli.main(["scan", "--root", str(repo)])
    capsys.readouterr()
    cli.main(["split", "--root", str(repo)])
    doc = passes.load_ledger(repo / ".seams-scan")
    assert [p["kind"] for p in doc["passes"]] == ["first"]
    assert doc["passes"][0]["before"] == {"seams": {}, "drift": []}


# --- seams next ------------------------------------------------------------------------

def commands(repo):
    return [c for c, _, _ in passes.candidates(repo, repo / ".seams-scan")]


def test_no_registry_starts_with_a_scan_and_a_first_review(repo):
    cmds = commands(repo)
    assert cmds[0] == "`seams scan`" and "first review" in cmds[1]


def test_an_unmerged_pass_is_finished_first(repo):
    write_reg(repo, reg(seam("a")))
    passes.record_pass(repo / ".seams-scan", "gap", 2, 9, reg(seam("a")))
    assert len(commands(repo)) == 1 and "finish the gap pass" in commands(repo)[0]


def test_two_gap_passes_are_planned_then_the_stop_rule_decides(repo):
    out = repo / ".seams-scan"
    write_reg(repo, reg(seam("a")))
    passes.record_pass(out, "first", 2, 9, None)
    merged(repo, reg(seam("a")))
    assert any("gap pass 1" in c for c in commands(repo))
    passes.record_pass(out, "gap", 2, 9, reg(seam("a")))
    merged(repo, reg(seam("a"), seam("b")))         # gap 1 added a high seam
    assert any("gap pass 2" in c and "optional" not in c for c in commands(repo))
    passes.record_pass(out, "gap", 2, 9, reg(seam("a"), seam("b")))
    merged(repo, reg(seam("a"), seam("b"), seam("c", "low")))  # gap 2 added only a low seam
    assert "no more gap passes" in commands(repo)


def test_a_third_gap_pass_is_optional_while_passes_still_add(repo):
    out = repo / ".seams-scan"
    passes.record_pass(out, "first", 2, 9, None)
    passes.record_pass(out, "gap", 2, 9, reg(seam("a")))
    passes.record_pass(out, "gap", 2, 9, reg(seam("a"), seam("b")))
    merged(repo, reg(seam("a"), seam("b"), seam("c")))
    assert any("gap pass 3, optional" in c for c in commands(repo))


def test_drift_check_and_ties_are_offered(repo):
    write_reg(repo, reg(seam("a"), seam("b", drift=("reading", "differs"))))
    cmds = commands(repo)
    assert "`seams verify` (1 seams)" in cmds
    assert any(c.startswith("`seams verify --reading") for c in cmds)
    assert "`seams triage`" in cmds and "`seams tie --untied` (2 seams)" in cmds


def test_checked_seams_are_not_offered_again(repo):
    write_reg(repo, reg(seam("a")))
    d = repo / ".seams-scan" / "verify" / "results" / "done" / "x"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({"id": "a", "agree": True, "checked": "x"}))
    assert not any(c.startswith("`seams verify` (") for c in commands(repo))


def test_focused_pass_offered_when_its_leads_exist(repo):
    write_reg(repo, reg(seam("a")))
    lead = {"kind": "twin", "files": [{"path": "a.py"}, {"path": "c.py"}]}
    (repo / ".seams-scan" / "leads.json").write_text(json.dumps({"files": {}, "leads": [lead]}))
    rows = passes.candidates(repo, repo / ".seams-scan")
    [(cmd, why, _)] = [r for r in rows if "--focus twins" in r[0]]
    assert "1 leads of its kinds" in why and "1 that no recorded seam covers" in why


def test_next_text_shows_the_ledger(repo):
    out = repo / ".seams-scan"
    passes.record_pass(out, "first", 2, 9, None)
    merged(repo, reg(seam("a")))
    text = passes.next_text(repo, out)
    assert "1. first," in text and "1 new seams (1 high, 0 medium, 0 low)" in text
    assert "Cost: Cost" not in text


# --- triage ----------------------------------------------------------------------------

def test_triage_puts_confirmed_drift_first_then_risk():
    data = reg(seam("r-high", "high", ("reading", "x")), seam("c-low", "low", ("confirmed", "y")),
               seam("c-high", "high", ("confirmed", "z")), seam("clean"))
    confirmed, reading, n_conf, n_read = passes.triage(data, top=3)
    assert [s["id"] for s in confirmed] == ["c-high", "c-low"] and [s["id"] for s in reading] == ["r-high"]
    assert (n_conf, n_read) == (2, 1)


def test_triage_clips_long_drift_text():
    text = passes.triage_text(reg(seam("a", drift=("confirmed", "word " * 500))))
    assert "full text in seams.json" in text and len(text) < 2000


def test_triage_short_after_a_merge():
    assert passes.triage_short(reg(seam("a"))) == ""
    short = passes.triage_short(reg(seam("a", drift=("reading", "a.py:1 says 3, b.py:2 says 4"))))
    assert "1 found by reading" in short and "a.py:1 says 3" in short and "seams triage" in short


def test_triage_command_writes_the_file(repo, capsys):
    write_reg(repo, reg(seam("a", drift=("confirmed", "differs"))))
    assert cli.main(["triage", "--root", str(repo)]) == 0
    assert "## Confirmed" in (repo / ".seams-scan" / "triage.md").read_text()
