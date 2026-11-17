"""Re-scans: leads the registry already covers, leads a branch added, lead-only review."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from seams import cli, merge, scan, split

TOY = Path(__file__).parent / "fixtures" / "toy-repo"

STATUSES = {"id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
            "must_agree": "Same names.", "consequence": "x", "risk": "high",
            "copies": [{"path": "api/orders/status.py"}, {"path": "web/src/status.ts"}]}
GONE = {"id": "never-scanned", "title": "Something the scan cannot see", "kind": "contract",
        "must_agree": "x", "consequence": "x", "risk": "low",
        "copies": [{"path": "api/money.py"}, {"path": "deploy/compose.yml"}]}


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "toy"
    shutil.copytree(TOY, r)
    (r / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [STATUSES, GONE]}))
    return r


def doc_for(repo, **kw):
    return scan.scan(repo, registry=json.loads((repo / "seams.json").read_text()), **kw)


# --- coverage -------------------------------------------------------------------

def test_leads_inside_a_registered_seam_are_covered(repo):
    doc = doc_for(repo)
    code_only = [l for l in doc["leads"] if not any(f["path"].endswith(".md") for f in l["files"])]
    lit = next(l for l in code_only if l["kind"] == "literal-set")
    assert lit["covered_by"] == ["order-statuses"]
    dup = next(l for l in code_only if l["kind"] == "dupblock")
    assert dup["covered_by"] == []  # billing is not in the registry


def test_a_one_file_lead_in_a_registered_copy_is_covered(repo):
    tie = next(l for l in doc_for(repo)["leads"]
               if l["kind"] == "tie-candidate" and len(l["files"]) == 1)
    assert tie["covered_by"] == []  # the test file is no copy of any seam
    marker = next(l for l in doc_for(repo)["leads"] if l["kind"] == "marker"
                  and not any(f["path"].endswith(".md") for f in l["files"]))
    assert marker["covered_by"] == ["order-statuses"]


def test_a_registered_tie_counts_as_cover(repo):
    # The test that reads web/src/status.ts is already this seam's tie: not a new lead.
    tied = dict(STATUSES, ties=[{"path": "api/tests/test_status.py", "covers": "partial", "note": "web only"}])
    doc = scan.scan(repo, registry={"schema_version": 1, "seams": [tied]})
    xread = next(l for l in doc["leads"] if l["kind"] == "tie-candidate" and len(l["files"]) == 2)
    assert xread["covered_by"] == ["order-statuses"]


def test_report_says_which_registered_seams_the_scan_found(repo):
    reg = doc_for(repo)["registry"]
    assert reg == {"seams": 2, "found_by_scan": ["order-statuses"], "missed_by_scan": ["never-scanned"]}


def test_counts_include_new_leads(repo):
    doc = doc_for(repo)
    for kind, c in doc["counts"].items():
        rows = [l for l in doc["leads"] if l["kind"] == kind]
        assert c["new"] == sum(1 for l in rows if not l["covered_by"])


def test_new_markdown_lists_only_uncovered_leads(repo, tmp_path):
    doc = doc_for(repo)
    md = scan.render_md(doc, only_new=True)
    assert "api/orders/billing.py" in md  # an uncovered copied block
    assert "[covered:" not in md
    assert "No lead points at: `never-scanned`" in md


def test_without_a_registry_nothing_is_marked():
    doc = scan.scan(TOY)
    assert doc["registry"] is None and all("covered_by" not in l for l in doc["leads"])


# --- --since ---------------------------------------------------------------------

def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   check=True, capture_output=True)


def test_since_keeps_only_leads_touching_changed_files(repo):
    if not shutil.which("git"):
        pytest.skip("needs git")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "feature")
    (repo / "worker/money.py").write_text("def cents(x):\n    return int(x * 100)\n# changed\n")
    doc = doc_for(repo, since="main")
    assert doc["since"]["changed_files"] == 1
    assert doc["leads"] and all(any(f["path"] == "worker/money.py" for f in l["files"]) for l in doc["leads"])


# --- cli -----------------------------------------------------------------------------

def test_cli_new_without_a_registry_exits_2(tmp_path):
    shutil.copytree(TOY, tmp_path / "toy")
    assert cli.main(["scan", "--root", str(tmp_path / "toy"), "--new"]) == 2


def test_cli_scan_ignores_an_invalid_registry_with_a_warning(repo, capsys):
    (repo / "seams.json").write_text('{"schema_version": 1, "seams": [{"id": "x"}]}')
    assert cli.main(["scan", "--root", str(repo)]) == 0
    assert "ignoring seams.json" in capsys.readouterr().err


def test_cli_scan_reports_registry_recall(repo, capsys):
    assert cli.main(["scan", "--root", str(repo), "--new"]) == 0
    assert "lead for 1 of the 2 seams" in capsys.readouterr().out


# --- lead-only split ------------------------------------------------------------------

def test_new_only_needs_coverage_information():
    with pytest.raises(ValueError):
        split.filter_leads(scan.scan(TOY), new_only=True)


def test_filters_drop_covered_and_single_area_leads(repo):
    doc = doc_for(repo)
    new = split.filter_leads(doc, new_only=True)["leads"]
    assert new and not any(l["covered_by"] for l in new)
    cross = split.filter_leads(doc, cross_area_only=True)["leads"]
    assert cross and all(l["cross_area"] for l in cross)


def test_lead_only_split_skips_empty_packets_and_says_lead_only(repo, tmp_path):
    out = tmp_path / "out"
    doc = doc_for(repo)
    doc["leads"] = [l for l in doc["leads"] if l["kind"] == "dupblock"]  # only billing: api and worker
    bins = split.write(doc, repo, out, max_lines=40, new_only=True)
    assert [b["name"][:4] for b in bins] == [f"p{i:02d}-" for i in range(1, len(bins) + 1)]  # renumbered
    assert bins and all(b["leads"] for b in bins)
    assert len(bins) < len(split.plan(doc, max_lines=40))  # packets with no leads are gone
    packet = next((out / "packets").glob("*.md")).read_text()
    assert "## Lead-only review" in packet
    assert "not measured" in (out / "plan.md").read_text()


def test_full_split_has_no_lead_only_section(repo, tmp_path):
    out = tmp_path / "out"
    split.write(doc_for(repo), repo, out)
    assert "Lead-only" not in next((out / "packets").glob("*.md")).read_text()


def test_cli_split_with_nothing_left_says_so(repo, capsys):
    reg = {"schema_version": 1, "seams": [STATUSES]}
    (repo / "seams.json").write_text(json.dumps(reg))
    cli.main(["scan", "--root", str(repo)])
    doc = json.loads((repo / ".seams-scan/leads.json").read_text())
    for l in doc["leads"]:
        l["covered_by"] = ["order-statuses"]
    (repo / ".seams-scan/leads.json").write_text(json.dumps(doc))
    capsys.readouterr()
    assert cli.main(["split", "--root", str(repo), "--new-only"]) == 0
    assert "Nothing to review" in capsys.readouterr().out


# --- merge against an existing registry ----------------------------------------------

def review(**over):
    base = {"id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
            "must_agree": "Same names.", "consequence": "x", "risk": "high",
            "copies": [{"path": "api/orders/status.py"}, {"path": "api/orders/generated_client.py"}]}
    base.update(over)
    return base


def put(repo, entries):
    d = repo / ".seams-scan" / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    (d / "seam-review-p01.json").write_text(json.dumps(entries))


def test_new_copies_of_an_existing_seam_are_reported_not_added(repo):
    put(repo, [review()])
    proposed, report, _, _ = merge.merge(repo, repo / ".seams-scan")
    entry = next(s for s in proposed["seams"] if s["id"] == "order-statuses")
    assert entry == STATUSES
    assert "copies they do not list" in report and "api/orders/generated_client.py" in report


def test_extend_adds_the_new_copies(repo):
    put(repo, [review()])
    proposed, report, _, errors = merge.merge(repo, repo / ".seams-scan", {"extend": ["order-statuses"]})
    entry = next(s for s in proposed["seams"] if s["id"] == "order-statuses")
    assert [c["path"] for c in entry["copies"]] == [
        "api/orders/status.py", "web/src/status.ts", "api/orders/generated_client.py"]
    assert errors == [] and "extended by the plan" in report


def test_a_new_seam_that_duplicates_an_existing_one_is_reported(repo):
    put(repo, [review(id="status-list", copies=[{"path": "api/orders/status.py"}, {"path": "web/src/status.ts"}])])
    _, report, _, _ = merge.merge(repo, repo / ".seams-scan")
    assert "duplicates of seams already in seams.json" in report and "existing `order-statuses`" in report
    _, report, _, _ = merge.merge(repo, repo / ".seams-scan", {"distinct": [["status-list", "order-statuses"]]})
    assert "duplicates of seams already" not in report


# --- the reviewed-leads baseline ------------------------------------------------------

def test_fingerprint_survives_line_shifts_but_not_new_files(repo):
    before = {scan.fingerprint(l) for l in scan.scan(repo)["leads"]}
    status = repo / "api/orders/status.py"
    status.write_text("# a new first line\n" + status.read_text())
    after = scan.scan(repo)["leads"]
    assert {scan.fingerprint(l) for l in after} == before
    (repo / "worker/status_copy.py").write_text(status.read_text())
    assert {scan.fingerprint(l) for l in scan.scan(repo)["leads"]} - before


def test_seen_leads_are_not_new(repo):
    base = {l["fingerprint"] for l in scan.scan(repo)["leads"]}
    doc = scan.scan(repo, baseline=base)
    assert all(l["seen"] for l in doc["leads"]) and all(c["new"] == 0 for c in doc["counts"].values())


def test_cli_baseline_then_rescan_shows_only_what_changed(repo, capsys):
    (repo / "seams.json").unlink()
    cli.main(["scan", "--root", str(repo)])
    assert cli.main(["baseline", "--root", str(repo)]) == 0
    assert (repo / scan.BASELINE).exists()
    (repo / "worker/status_copy.py").write_text((repo / "api/orders/status.py").read_text())
    capsys.readouterr()
    assert cli.main(["scan", "--root", str(repo), "--new"]) == 0
    md = (repo / ".seams-scan/leads.md").read_text()
    assert "worker/status_copy.py" in md and "api/orders/billing.py" not in md
    assert cli.main(["split", "--root", str(repo), "--new-only"]) == 0  # a baseline alone is enough
    packets = list((repo / ".seams-scan/packets").glob("*.md"))
    assert packets and all("status_copy" in p.read_text() for p in packets)


def test_baseline_grows_and_never_forgets(repo):
    path = repo / scan.BASELINE
    scan.write_baseline(path, {"aaaa"})
    cli.main(["scan", "--root", str(repo)])
    cli.main(["baseline", "--root", str(repo)])
    assert "aaaa" in scan.load_baseline(path)


def test_cli_baseline_refuses_a_since_filtered_scan(repo):
    out = repo / ".seams-scan"
    out.mkdir()
    (out / "leads.json").write_text(json.dumps({"files": [], "leads": [], "since": {"ref": "main"}}))
    assert cli.main(["baseline", "--root", str(repo)]) == 2


@pytest.mark.parametrize("bad", ["[]", '{"baseline_version": 2, "leads": []}', '{"baseline_version": 1, "leads": [1]}'])
def test_a_bad_baseline_is_refused(tmp_path, bad):
    (tmp_path / "b.json").write_text(bad)
    with pytest.raises(ValueError):
        scan.load_baseline(tmp_path / "b.json")


def test_cli_scan_ignores_a_bad_baseline_with_a_warning(repo, capsys):
    (repo / scan.BASELINE).write_text("[]")
    assert cli.main(["scan", "--root", str(repo)]) == 0
    assert "ignoring it" in capsys.readouterr().err


def test_merge_apply_records_the_reviewed_leads(repo, capsys):
    cli.main(["scan", "--root", str(repo)])
    put(repo, [review(id="billing", copies=[{"path": "api/orders/billing.py"}, {"path": "worker/billing_copy.py"}])])
    assert cli.main(["merge", "--root", str(repo), "--apply"]) == 0
    leads = json.loads((repo / ".seams-scan/leads.json").read_text())["leads"]
    assert scan.load_baseline(repo / scan.BASELINE) == {l["fingerprint"] for l in leads}
