"""The review workflow problems two blind runs on a real repo reported, one test each."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from seams import check, cli, merge, scan, split

TOY = Path(__file__).parent / "fixtures" / "toy-repo"


def review(**over):
    base = {"id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
            "must_agree": "Same names.", "consequence": "A status vanishes.", "risk": "high",
            "copies": [{"path": "api/orders/status.py"}, {"path": "web/src/status.ts"}]}
    base.update(over)
    return base


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "toy"
    shutil.copytree(TOY, r)
    (r / "api/tests/test_cls.py").write_text("class TestStatus:\n    def test_same(self):\n        pass\n")
    return r


def put(repo, *entries, name="p01"):
    d = repo / ".seams-scan" / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"seam-review-{name}.json").write_text(json.dumps(list(entries)))


def run(repo, plan=None):
    return merge.merge(repo, repo / ".seams-scan", plan, today="2026-11-15")


# --- one bad field never costs a whole seam ----------------------------------------------

def test_drift_source_and_seen_from_a_reviewer_are_accepted_and_ignored(repo):
    # The skill told reviewers to set drift.source; the merge used to drop those entries whole.
    put(repo, review(drift={"text": "web lacks returned", "source": "confirmed", "seen": "2026-01-01"}))
    proposed, _, _, _ = run(repo)
    [e] = proposed["seams"]
    assert e["drift"] == {"text": "web lacks returned", "source": "reading", "seen": "2026-11-15"}


def test_an_unknown_or_bad_optional_field_is_dropped_not_the_entry(repo):
    put(repo, review(colour="red", risk_reason=7,
                     copies=[{"path": "api/orders/status.py", "lines": [1, 2]}, {"path": "web/src/status.ts"},
                             {"nope": True}]))
    proposed, report, _, _ = run(repo)
    [e] = proposed["seams"]
    assert [c["path"] for c in e["copies"]] == ["api/orders/status.py", "web/src/status.ts"]
    assert "not in the review format" in report and ".colour" in report and ".lines" in report
    assert "risk_reason" in report and "Copies dropped: wrong shape" in report


def test_a_bad_required_field_still_skips_the_entry(repo):
    put(repo, review(risk="severe"))
    proposed, report, _, _ = run(repo)
    assert proposed["seams"] == [] and "required field is wrong" in report


def test_a_folder_copy_becomes_a_glob(repo):
    put(repo, review(copies=[{"path": "api/orders"}, {"path": "web/src/status.ts"}]))
    proposed, report, _, errors = run(repo)
    assert proposed["seams"][0]["copies"][0]["path"] == "api/orders/**/*"
    assert errors == [] and "turned into globs" in report


def test_a_class_dot_method_tie_is_kept(repo):
    tie = {"path": "api/tests/test_cls.py", "test": "TestStatus.test_same", "covers": "all",
           "runs_in_ci": "yes: pytest"}
    put(repo, review(ties=[tie]))
    proposed, report, _, errors = run(repo)
    assert proposed["seams"][0]["ties"][0]["test"] == "TestStatus.test_same" and errors == []


# --- security, drift and the report ------------------------------------------------------

def test_drift_of_an_entry_with_a_security_finding_is_flagged(repo):
    put(repo, review(drift={"text": "the web check skips admin routes"}, sensitive_finding="detail"))
    _, report, private, _ = run(repo)
    assert "check this text holds no exploit detail" in report and "skips admin routes" in report
    assert "detail" in private


def test_high_risk_drift_is_printed_in_full(repo):
    long = "api/orders/status.py:2 lists returned " + "and more detail " * 20 + "web/src/status.ts:1570"
    put(repo, review(drift={"text": long}))
    assert long in run(repo)[1]


def test_confirm_marks_drift_confirmed(repo):
    put(repo, review(drift={"text": "differs"}))
    proposed, report, _, _ = run(repo, {"confirm": ["order-statuses", "ghost"], "absorbb": {}})
    assert proposed["seams"][0]["drift"]["source"] == "confirmed"
    assert "confirm `ghost`" in report and "unknown plan key `absorbb`" in report


def test_absorbing_the_same_finding_twice_does_not_repeat_it(repo):
    put(repo, review(drift={"text": "web lacks returned"}, suggested_tie="a parity test"),
        review(id="status-copy", drift={"text": "web lacks returned"}, suggested_tie="a parity test"))
    proposed, _, _, _ = run(repo, {"absorb": {"status-copy": "order-statuses"}})
    [e] = proposed["seams"]
    assert e["drift"]["text"] == "web lacks returned" and e["suggested_tie"] == "a parity test"


def test_absorbing_a_finding_another_already_holds_does_not_repeat_it(repo):
    put(repo, review(drift={"text": "web lacks returned and packed"}),
        review(id="status-copy", drift={"text": "web lacks returned"}))
    proposed, _, _, _ = run(repo, {"absorb": {"status-copy": "order-statuses"}})
    assert proposed["seams"][0]["drift"]["text"] == "web lacks returned and packed"


# --- duplicates ----------------------------------------------------------------------------

def test_duplicates_are_grouped_in_clusters_with_titles(repo):
    put(repo, review(), review(id="status-list", title="Status list"),
        review(id="status-third", title="Third view"))
    _, report, _, _ = run(repo)
    assert "cluster 1, 3 entries" in report and "`status-list`: Status list" in report


def test_a_chain_of_pairs_is_one_cluster(repo):
    # a and c share nothing, but each shares two files with b: one cluster of three.
    s, w, m1, m2 = "api/orders/status.py", "web/src/status.ts", "api/money.py", "worker/money.py"
    put(repo, review(id="a", title="A", copies=[{"path": s}, {"path": w}]),
        review(id="b", title="B", copies=[{"path": s}, {"path": w}, {"path": m1}, {"path": m2}]),
        review(id="c", title="C", copies=[{"path": m1}, {"path": m2}]))
    _, report, _, _ = run(repo)
    assert "cluster 1, 3 entries" in report and "cluster 2" not in report


def test_pairs_that_share_only_hub_files_need_no_decision(repo):
    # Every entry lists the same two files, so both are hubs and no pair needs a decision.
    put(repo, *[review(id=f"s{i}", title=f"S{i}") for i in range(merge.HUB_SEAMS)])
    _, report, _, _ = run(repo)
    assert "share only hub files" in report and "settle each cluster" not in report


def test_nearly_the_same_copy_list_is_a_duplicate_even_when_every_file_is_a_hub(repo):
    # Duplicates inflate their own files' counts, so the hub rule once hid three copies of one seam.
    files = [{"path": p} for p in ("api/orders/status.py", "web/src/status.ts", "api/money.py", "worker/money.py")]
    put(repo, *[review(id=f"s{i}", title=f"S{i}", copies=files) for i in range(merge.HUB_SEAMS)])
    _, report, _, _ = run(repo)
    assert "settle each cluster" in report and "nearly the same copy list" in report


def test_the_hub_section_names_every_hub_file(repo):
    put(repo, *[review(id=f"s{i}", title=f"S{i}") for i in range(merge.HUB_SEAMS)])
    _, report, _, _ = run(repo)
    line = next(l for l in report.splitlines() if "hub files:" in l)
    assert "The 2 hub files:" in line and "status.py` (6)" in line and "status.ts` (6)" in line


def test_the_report_says_none_for_each_section_with_nothing_in_it(repo):
    put(repo, review())
    _, report, _, _ = run(repo)
    checked = report.split("## Checked, none found", 1)[1]
    assert "- Possible duplicates" in checked and "- High-risk drift to confirm first" in checked


def test_every_section_the_skill_names_is_one_the_merge_writes():
    import re
    skill = (Path(merge.__file__).parents[2] / "skills/seams-review/SKILL.md").read_text()
    step5 = skill.split("run `seams merge`", 1)[1].split("\n6. ", 1)[0]
    named = {n.rstrip(":") for n in re.findall(r"\*\*([^*]+)\*\*", step5)}
    assert named == set(merge.SETTLE), named ^ set(merge.SETTLE)
    src = Path(merge.__file__).read_text()
    for s in merge.SETTLE:
        assert f'"{s}' in src, s


# --- apply keeps hand edits ------------------------------------------------------------------

def test_seams_apply_keeps_a_hand_edit_to_the_proposal(repo, capsys):
    put(repo, review())
    assert cli.main(["merge", "--root", str(repo)]) == 0
    prop = repo / ".seams-scan/seams.proposed.json"
    data = json.loads(prop.read_text())
    data["seams"][0]["title"] = "Order status names, edited by hand"
    prop.write_text(json.dumps(data))
    assert cli.main(["apply", "--root", str(repo)]) == 0
    assert check.load(repo / "seams.json")["seams"][0]["title"].endswith("edited by hand")


def test_seams_apply_refuses_a_proposal_that_fails_the_check(repo):
    put(repo, review())
    cli.main(["merge", "--root", str(repo)])
    prop = repo / ".seams-scan/seams.proposed.json"
    data = json.loads(prop.read_text())
    data["seams"][0]["copies"][0]["path"] = "gone.py"
    prop.write_text(json.dumps(data))
    assert cli.main(["apply", "--root", str(repo)]) == 1 and not (repo / "seams.json").exists()


# --- the baseline records only what reviewers saw --------------------------------------------

def test_baseline_records_only_the_leads_the_packets_showed(repo, monkeypatch):
    monkeypatch.setattr(split, "MAX_LEADS", 2)
    cli.main(["scan", "--root", str(repo)])
    cli.main(["split", "--root", str(repo)])
    shown = set(json.loads((repo / ".seams-scan/shown.json").read_text()))
    every = {l["fingerprint"] for l in json.loads((repo / ".seams-scan/leads.json").read_text())["leads"]}
    assert shown and shown < every
    cli.main(["baseline", "--root", str(repo)])
    assert scan.load_baseline(repo / scan.BASELINE) == shown


def test_a_new_scan_removes_a_stale_shown_list(repo):
    cli.main(["scan", "--root", str(repo)])
    cli.main(["split", "--root", str(repo)])
    assert (repo / ".seams-scan/shown.json").exists()
    cli.main(["scan", "--root", str(repo)])
    assert not (repo / ".seams-scan/shown.json").exists()


# --- plan.md says what it counts ----------------------------------------------------------------

def test_plan_shows_leads_shown_and_in_all_cost_per_effort_and_what_is_not_scanned(repo, monkeypatch):
    monkeypatch.setattr(split, "MAX_LEADS", 2)
    (repo / "assets").mkdir()
    (repo / "assets/logo.svg").write_text("x\n")
    cli.main(["scan", "--root", str(repo)])
    cli.main(["split", "--root", str(repo)])
    plan = (repo / ".seams-scan/plan.md").read_text()
    assert "shown in packets, of" in plan and "no reviewer sees them" in plan
    assert "At high effort" in plan and "At max effort" in plan
    assert "## Not scanned" in plan and "`.svg`" in plan


def test_apply_keeps_the_notes_setting_set_after_the_proposal(repo, capsys):
    put(repo, review())
    assert cli.main(["merge", "--root", str(repo), "--apply"]) == 0
    reg = json.loads((repo / "seams.json").read_text())
    reg["notes"] = "rules"
    (repo / "seams.json").write_text(json.dumps(reg))
    assert cli.main(["apply", "--root", str(repo)]) == 0
    assert json.loads((repo / "seams.json").read_text())["notes"] == "rules"


def test_merge_keeps_the_notes_setting(repo, capsys):
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "notes": "rules", "seams": []}))
    put(repo, review())
    assert cli.main(["merge", "--root", str(repo), "--apply"]) == 0
    assert json.loads((repo / "seams.json").read_text())["notes"] == "rules"


def test_review_skill_runs_presets_through_the_tool():
    # The skill shows the choice and links the page that explains it; the tool holds the values.
    text = (Path(merge.__file__).parents[2] / "skills/seams-review/SKILL.md").read_text()
    for cmd in ("seams presets", "seams run start", "seams run raise", "seams run finish", "seams spend"):
        assert cmd in text, cmd
    assert "docs/presets.md" in text
    assert "seams.settings.json" in text
