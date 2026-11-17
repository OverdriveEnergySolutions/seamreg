from __future__ import annotations

import json
from pathlib import Path

import pytest

from seams import check, cli, merge


def review(**over):
    base = {
        "id": "Order Status Names", "title": "Order status names", "kind": "vocabulary",
        "must_agree": "Both lists hold the same names.",
        "copies": [{"path": "api/status.py", "symbol": "STATUSES", "line": 1},
                   {"path": "web/status.ts", "symbol": "STATUSES", "line": 1}],
        "consequence": "The web app shows a status the API never sends.", "risk": "medium",
        "ties": [{"path": "tests/test_parity.py", "test": "test_parity", "covers": "all",
                  "assert_line": "assert a == b", "runs_in_ci": "yes: pytest job"}],
        "drift": None,
    }
    base.update(over)
    return base


@pytest.fixture
def repo(tmp_path):
    files = {"api/status.py": "STATUSES = []\n", "web/status.ts": "export const STATUSES = []\n",
             "tests/test_parity.py": "def test_parity():\n    assert a == b\n",
             "worker/status.py": "STATUSES = []\n"}
    for p, text in files.items():
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text(text)
    (tmp_path / ".seams-scan" / "reviews").mkdir(parents=True)
    return tmp_path


def put(repo, name, entries):
    (repo / ".seams-scan" / "reviews" / f"seam-review-{name}.json").write_text(json.dumps(entries))


def run(repo, plan=None):
    return merge.merge(repo, repo / ".seams-scan", plan, today="2026-11-14")


def test_a_good_review_becomes_a_valid_registry_entry(repo):
    put(repo, "p01", [review()])
    proposed, report, private, errors = run(repo)
    assert errors == [] and private == ""
    [e] = proposed["seams"]
    assert e["id"] == "order-status-names"
    assert e["copies"] == [{"path": "api/status.py", "symbol": "STATUSES"},
                           {"path": "web/status.ts", "symbol": "STATUSES"}]  # line numbers dropped
    assert e["ties"] == [{"path": "tests/test_parity.py", "covers": "all", "test": "test_parity"}]


def test_missing_path_and_symbol_are_dropped_and_reported(repo):
    copies = [{"path": "api/status.py", "symbol": "NOPE"}, {"path": "web/status.ts"}, {"path": "gone.py"}]
    put(repo, "p01", [review(copies=copies)])
    proposed, report, _, errors = run(repo)
    assert errors == []
    assert proposed["seams"][0]["copies"] == [{"path": "api/status.py"}, {"path": "web/status.ts"}]
    assert "`NOPE` in `api/status.py`" in report and "`gone.py` does not exist" in report


def test_a_seam_left_with_one_copy_is_dropped(repo):
    put(repo, "p01", [review(copies=[{"path": "api/status.py"}, {"path": "gone.py"}])])
    proposed, report, _, _ = run(repo)
    assert proposed["seams"] == [] and "too few copies" in report


@pytest.mark.parametrize("tie, reason", [
    ({"path": "tests/gone.py", "covers": "all"}, "file not found"),
    ({"path": "tests/test_parity.py", "test": "test_other", "covers": "all"}, "test name not in the file"),
    ({"path": "tests/test_parity.py", "covers": "all", "runs_in_ci": "no: not in any workflow"}, "CI does not run them"),
    ({"path": "tests/test_parity.py", "covers": "all", "runs_in_ci": "CI never runs this test"}, "CI does not run them"),
    ({"path": "tests/test_parity.py", "covers": "partial"}, "partial with no note"),
])
def test_bad_ties_are_dropped_with_a_reason(repo, tie, reason):
    put(repo, "p01", [review(ties=[tie])])
    proposed, report, _, _ = run(repo)
    assert "ties" not in proposed["seams"][0] and reason in report


@pytest.mark.parametrize("ci", [None, "unknown: no CI config found", "probably, via the test job"])
def test_a_tie_without_a_clear_yes_is_kept_but_flagged(repo, ci):
    tie = {"path": "tests/test_parity.py", "covers": "all", "runs_in_ci": ci}
    put(repo, "p01", [review(ties=[tie])])
    proposed, report, _, _ = run(repo)
    assert proposed["seams"][0]["ties"] and "without CI evidence" in report


def test_a_tie_with_a_clear_yes_is_not_flagged(repo):
    put(repo, "p01", [review()])
    assert "## Ties kept without CI evidence" not in run(repo)[1]


def test_drift_is_always_a_lead_from_reading(repo):
    put(repo, "p01", [review(risk="high", drift={"text": "api has 'returned'; web does not"})])
    proposed, report, _, _ = run(repo)
    assert proposed["seams"][0]["drift"] == {"text": "api has 'returned'; web does not",
                                             "source": "reading", "seen": "2026-11-14"}
    assert "High-risk drift to confirm first" in report


def test_security_detail_never_reaches_the_registry(repo):
    secret = "the token check skips admin routes"
    put(repo, "p01", [review(sensitive_finding=secret)])
    proposed, _, private, _ = run(repo)
    assert secret not in json.dumps(proposed) and secret in private
    assert "kept out of this repo" in proposed["seams"][0]["sensitive"]


def test_agent_voice_is_flagged(repo):
    put(repo, "p01", [review(consequence="I checked the web app and it shows a stale status.")])
    _, report, _, _ = run(repo)
    assert "neutral voice" in report


def test_same_id_from_two_reviewers_is_joined(repo):
    put(repo, "p01", [review(risk="low")])
    put(repo, "p02", [review(copies=[{"path": "api/status.py"}, {"path": "worker/status.py"}], risk="high")])
    proposed, report, _, _ = run(repo)
    [e] = proposed["seams"]
    assert [c["path"] for c in e["copies"]] == ["api/status.py", "web/status.ts", "worker/status.py"]
    assert e["risk"] == "high" and "same id from two reviewers" in report


def test_shared_copies_are_reported_and_joined_only_by_a_plan(repo):
    put(repo, "p01", [review(), review(id="status-list", title="Status list")])
    proposed, report, _, _ = run(repo)
    assert len(proposed["seams"]) == 2 and "Possible duplicates" in report
    proposed, report, _, _ = run(repo, {"absorb": {"status-list": "order-status-names"}})
    assert [e["id"] for e in proposed["seams"]] == ["order-status-names"]


def test_plan_distinct_stops_the_duplicate_question(repo):
    put(repo, "p01", [review(), review(id="order-line-parsing", title="Order line parsing")])
    proposed, report, _, _ = run(repo, {"distinct": [["order-line-parsing", "order-status-names"]]})
    assert len(proposed["seams"]) == 2 and "## Possible duplicates" not in report


def test_plan_drop_and_rename(repo):
    put(repo, "p01", [review(), review(id="other", copies=[{"path": "api/status.py"}, {"path": "worker/status.py"}])])
    proposed, _, _, _ = run(repo, {"drop": ["other"], "rename": {"order-status-names": "statuses"}})
    assert [e["id"] for e in proposed["seams"]] == ["statuses"]


def test_existing_entries_are_never_changed(repo):
    existing = {"id": "order-status-names", "title": "Kept", "kind": "vocabulary", "must_agree": "x",
                "copies": [{"path": "api/status.py"}, {"path": "web/status.ts"}],
                "consequence": "x", "risk": "low"}
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [existing]}))
    put(repo, "p01", [review()])
    proposed, report, _, _ = run(repo)
    assert proposed["seams"] == [existing] and "kept the existing entry" in report


def test_wrong_shape_and_unreadable_files_are_reported(repo):
    put(repo, "p01", [{"id": "x"}])
    (repo / ".seams-scan" / "reviews" / "seam-review-p02.json").write_text("{not json")
    proposed, report, _, _ = run(repo)
    assert proposed["seams"] == []
    assert "required field is wrong" in report and "could not be read" in report


def test_cli_merge_apply_writes_seams_json_only_when_it_passes(repo, capsys):
    put(repo, "p01", [review()])
    assert cli.main(["merge", "--root", str(repo), "--apply"]) == 0
    assert check.check(check.load(repo / "seams.json"), repo) == []


def test_cli_merge_apply_refuses_a_proposal_that_fails_the_check(repo, capsys):
    # An existing entry whose copy was deleted makes the whole proposal fail.
    broken = {"id": "old", "title": "Old", "kind": "config", "must_agree": "x", "consequence": "x",
              "risk": "low", "copies": [{"path": "api/status.py"}, {"path": "deleted.py"}]}
    before = json.dumps({"schema_version": 1, "seams": [broken]})
    (repo / "seams.json").write_text(before)
    put(repo, "p01", [review()])
    assert cli.main(["merge", "--root", str(repo), "--apply"]) == 1
    assert (repo / "seams.json").read_text() == before


def test_cli_merge_without_reviews_exits_2(tmp_path):
    assert cli.main(["merge", "--root", str(tmp_path)]) == 2


def test_merge_and_checker_agree_on_kinds_and_risks():
    item = merge.REVIEW_ENTRY["properties"]
    seam = check.SCHEMA["properties"]["seams"]["items"]["properties"]
    assert item["kind"]["enum"] == seam["kind"]["enum"] == list(check.KINDS)
    assert item["risk"]["enum"] == seam["risk"]["enum"] == list(check.RISKS)
    assert list(merge.RISK_ORDER) == list(check.RISKS)


def test_brief_example_matches_what_merge_accepts():
    # The brief tells reviewers what to write; REVIEW_ENTRY is what merge accepts.
    brief = merge.Path(merge.__file__).with_name("brief.md").read_text()
    example = json.loads(brief.split("```json", 1)[1].split("```", 1)[0])
    errors = []
    check.validate(example, merge.REVIEW_ENTRY, "brief example", errors)
    assert errors == []
    assert set(example) == set(merge.REVIEW_ENTRY["properties"]), "the brief must show every field"


# --- feedback from the v2, Pocock and uptime-kuma runs ---------------------------------

def test_confirmed_drift_leaves_the_to_confirm_list_and_the_summary_splits_the_count(repo):
    put(repo, "p01", [review(risk="high", drift={"text": "web lacks 'returned'"})])
    _, report, _, _ = run(repo)
    assert "High-risk drift to confirm first" in report.split("Checked, none found")[0]
    _, report, _, _ = run(repo, {"confirm": ["order-status-names"]})
    assert "1 carry drift: 0 found by reading, 1 confirmed by the plan" in report
    assert "High-risk drift to confirm first" in report.split("Checked, none found")[1]


def test_a_join_narrows_a_covers_all_tie_and_lists_the_absorbed_must_agree(repo):
    keep = review(id="statuses", copies=[{"path": "api/status.py"}, {"path": "web/status.ts"}])
    dupe = review(id="worker-statuses", must_agree="The worker uses the API's names.", ties=[],
                  copies=[{"path": "api/status.py"}, {"path": "worker/status.py"}])
    put(repo, "p01", [keep, dupe])
    proposed, report, _, errors = run(repo, {"absorb": {"worker-statuses": "statuses"}})
    [e] = proposed["seams"]
    assert errors == [] and e["ties"][0]["covers"] == "partial"
    assert "`worker/status.py`" in e["ties"][0]["note"]
    assert "now covers partial" in report and "The worker uses the API's names." in report


def test_a_tie_that_already_covers_every_copy_stays_all_after_a_join(repo):
    put(repo, "p01", [review(id="a"), review(id="b", ties=[])])
    proposed, _, _, _ = run(repo, {"absorb": {"b": "a"}})
    assert proposed["seams"][0]["ties"][0]["covers"] == "all"


def test_distinct_takes_a_whole_cluster(repo):
    copies = [{"path": "api/status.py"}, {"path": "web/status.ts"}, {"path": "worker/status.py"}]
    put(repo, "p01", [review(id=x, copies=copies, ties=[]) for x in ("a", "b", "c")])
    _, report, _, _ = run(repo)
    assert '"distinct": [["a", "b", "c"]]' in report and "(3 of 3 and 3 of 3 copies)" in report
    _, report, _, _ = run(repo, {"distinct": [["a", "b", "c"]]})
    assert "Possible duplicates" in report.split("Checked, none found")[1]


def test_drift_the_entry_also_calls_deliberate_is_flagged(repo):
    put(repo, "p01", [review(drift={"text": "web/status.ts:3 adds 'held'."},
                             intentional_differences="web/status.ts keeps 'held' for the UI only.")])
    _, report, _, _ = run(repo)
    assert "## Drift the entry also calls deliberate" in report and "`web/status.ts`" in report


def test_the_security_check_shows_every_text_field(repo):
    put(repo, "p01", [review(sensitive_finding="detail", suggested_tie="test flag-order variants")])
    _, report, _, _ = run(repo)
    assert ".suggested_tie: test flag-order variants" in report and ".must_agree:" in report


def test_the_voice_check_names_what_it_matched(repo):
    put(repo, "p01", [review(title="Ping packet size limits")])
    _, report, _, _ = run(repo)
    assert 'flagged for "packet"' in report


def test_apply_confirm_marks_drift_and_refuses_an_id_without_drift(repo, capsys):
    put(repo, "p01", [review(drift={"text": "web lacks 'returned'"})])
    merge.write(repo, repo / ".seams-scan", None, False)
    assert cli.main(["apply", "--root", str(repo), "--confirm", "nope"]) == 1
    assert not (repo / "seams.json").exists()
    assert cli.main(["apply", "--root", str(repo), "--confirm", "order-status-names"]) == 0
    assert check.load(repo / "seams.json")["seams"][0]["drift"]["source"] == "confirmed"


def test_extend_keeps_the_reviewers_drift_and_reports_its_text(repo):
    existing = {"id": "order-status-names", "title": "Order status names", "kind": "vocabulary",
                "must_agree": "Both lists hold the same names.",
                "copies": [{"path": "api/status.py"}, {"path": "web/status.ts"}], "consequence": "x", "risk": "medium"}
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [existing]}))
    put(repo, "p01", [review(must_agree="The API, the web app and the worker list the same names.",
                             copies=[{"path": "api/status.py"}, {"path": "worker/status.py"}],
                             drift={"text": "worker/status.py lacks 'held'."})])
    proposed, report, _, errors = run(repo, {"extend": ["order-status-names"]})
    [e] = proposed["seams"]
    assert errors == [] and e["drift"]["text"] == "worker/status.py lacks 'held'."
    assert "The API, the web app and the worker list the same names." in report


# --- bugs outside the seam format ------------------------------------------------------------

def test_a_bug_entry_reaches_the_report_and_not_the_registry(repo):
    bug = {"bug": "api/status.py:1 compares with 'refund', the status is 'refunded'.",
           "path": "api/status.py", "line": 1, "risk": "high"}
    put(repo, "p01", [review(), bug])
    proposed, report, private, errors = run(repo)
    assert errors == [] and private == ""
    assert [s["id"] for s in proposed["seams"]] == ["order-status-names"]
    section = report.split("## Bugs outside the seam format", 1)[1].split("\n## ", 1)[0]
    assert "`api/status.py:1` (high): api/status.py:1 compares with 'refund'" in section
    assert "## Entries skipped" not in report


def test_a_sensitive_bug_stays_out_of_the_report(repo):
    secret = "the admin check reads the wrong header"
    put(repo, "p01", [{"bug": secret, "path": "api/status.py", "sensitive": True}])
    _, report, private, _ = run(repo)
    assert secret not in report and secret in private
    assert "`api/status.py` (unranked): security detail, in private-findings.md" in report


def test_a_bug_entry_of_the_wrong_shape_is_skipped(repo):
    put(repo, "p01", [{"bug": "something", "risk": "high"}])  # no path
    _, report, _, _ = run(repo)
    assert "Entries skipped: wrong shape" in report
    assert "- Bugs outside the seam format" in report.split("## Checked, none found", 1)[1]


def test_a_convention_seam_is_a_valid_kind(repo):
    put(repo, "p01", [review(kind="convention", copies=[{"path": "api/*.py"}, {"path": "web/status.ts"}])])
    proposed, _, _, errors = run(repo)
    assert errors == [] and proposed["seams"][0]["kind"] == "convention"


def test_private_findings_from_an_earlier_pass_survive_a_later_merge(repo):
    put(repo, "p01", [review(sensitive_finding="first pass detail")])
    merge.write(repo, repo / ".seams-scan")
    priv = repo / ".seams-scan/private-findings.md"
    assert "first pass detail" in priv.read_text()
    # A gap pass moves the first reviews aside; its own review has a different finding, then none.
    (repo / ".seams-scan/reviews/seam-review-p01.json").unlink()
    put(repo, "gap-p01", [review(id="Other Seam", sensitive_finding="gap pass detail")])
    merge.write(repo, repo / ".seams-scan")
    text = priv.read_text()
    assert "first pass detail" in text and "gap pass detail" in text
    (repo / ".seams-scan/reviews/seam-review-gap-p01.json").unlink()
    put(repo, "gap-p02", [review(id="Third Seam")])
    merge.write(repo, repo / ".seams-scan")
    assert "first pass detail" in priv.read_text() and "gap pass detail" in priv.read_text()


def _existing(repo, **over):
    s = {"id": "order-status-names", "title": "Order status names", "kind": "vocabulary",
         "must_agree": "Both lists hold the same names.",
         "copies": [{"path": "api/status.py"}, {"path": "web/status.ts"}], "consequence": "x", "risk": "medium"}
    s.update(over)
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [s]}))


def test_drift_on_a_recorded_seam_with_no_new_copy_is_reported_not_dropped(repo):
    _existing(repo)
    put(repo, "p01", [review(drift={"text": "web/status.ts lacks 'held'."})])
    proposed, report, _, _ = run(repo)
    assert "Drift found on seams already in seams.json" in report and "web/status.ts lacks 'held'." in report
    assert "nothing new" not in report and not proposed["seams"][0].get("drift")
    proposed, _, _, errors = run(repo, {"extend": ["order-status-names"]})
    assert errors == [] and proposed["seams"][0]["drift"]["text"] == "web/status.ts lacks 'held'."


def test_extend_appends_new_drift_to_recorded_drift(repo):
    _existing(repo, drift={"text": "api/status.py has 'returned'.", "source": "confirmed", "seen": "2026-11-01"})
    put(repo, "p01", [review(drift={"text": "web/status.ts lacks 'held'."})])
    proposed, report, _, errors = run(repo, {"extend": ["order-status-names"]})
    d = proposed["seams"][0]["drift"]
    assert errors == [] and d["source"] == "confirmed"
    assert d["text"] == ("api/status.py has 'returned'. A later review also found (found by reading, "
                         "not confirmed): web/status.ts lacks 'held'.")
    assert "appended the reviewer's drift" in report
