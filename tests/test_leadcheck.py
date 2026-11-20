"""The lead check: strong leads no recorded seam covers, in small packets for a cheap checker."""
from __future__ import annotations

import json

from seams import cli, leadcheck

SEAM = {"id": "s", "title": "S", "kind": "vocabulary", "must_agree": "Same.", "risk": "low", "consequence": "c",
        "copies": [{"path": "api/a.py"}, {"path": "web/b.ts"}]}


def lead(kind, *paths, fp=None):
    return {"kind": kind, "files": [{"path": p, "line": 1} for p in paths], "touches_tests": any("test" in p for p in paths),
            "fingerprint": fp or kind + "|".join(paths), "detail": "d"}


def test_select_keeps_strong_uncovered_multi_file_leads_once():
    doc = {"leads": [lead("dupblock", "api/a.py", "web/b.ts"),          # covered by SEAM
                     lead("dupblock", "api/x.py", "web/y.ts"),
                     lead("dupblock", "web/y.ts", "api/x.py", fp="again"),  # same files: once
                     lead("co-change", "api/x.py", "web/z.ts"),         # not a strong kind
                     lead("same-name", "api/x.py"),                     # one file
                     lead("twin", "tests/test_a.py", "tests/test_b.py"),  # tests only
                     lead("shared-ids", "api/q.py", "web/r.ts")]}
    got = [(l["kind"], [f["path"] for f in l["files"]]) for l in leadcheck.select(doc, [SEAM])]
    assert got == [("shared-ids", ["api/q.py", "web/r.ts"]), ("dupblock", ["api/x.py", "web/y.ts"])]  # by path


def test_write_makes_small_packets_that_name_the_brief_and_a_review_file(tmp_path):
    doc = {"leads": [lead("dupblock", f"api/m{i}.py", f"web/m{i}.ts") for i in range(30)]}
    out = tmp_path / ".seams-scan"
    bins = leadcheck.write(doc, tmp_path, out, [], batch=25)
    assert [b["name"] for b in bins] == ["lc-01", "lc-02"] and [len(b["leads"]) for b in bins] == [25, 5]
    text = (out / "packets" / "lc-02.md").read_text()
    assert "lead-check-brief.md" in text and "seam-review-lc-02.json" in text and "5. dupblock: api/m9.py:1" in text
    assert (out / "lead-check-brief.md").read_text().startswith("# Lead check brief")
    assert "$" in (out / "plan.md").read_text() and len(json.loads((out / "shown.json").read_text())) == 30


def test_cli_needs_a_registry_and_records_the_pass(tmp_path, capsys):
    out = tmp_path / ".seams-scan"
    out.mkdir()
    (out / "leads.json").write_text(json.dumps({"leads_version": 2, "files": [], "areas": [], "leads": [
        lead("dupblock", "api/x.py", "web/y.ts")]}))
    assert cli.main(["split", "--root", str(tmp_path), "--lead-check"]) == 2
    assert "needs a seams.json" in capsys.readouterr().err
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [SEAM]}))
    for f in ("api/a.py", "web/b.ts"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x\n")
    assert cli.main(["split", "--root", str(tmp_path), "--lead-check"]) == 0
    assert "1 lead check packets" in capsys.readouterr().out
    assert json.loads((out / "passes.json").read_text())["passes"][-1]["kind"] == "lead-check"
    assert cli.main(["split", "--root", str(tmp_path), "--lead-check", "--gap"]) == 2


def test_the_brief_holds_no_benchmark_answers():
    text = leadcheck.BRIEF.read_text()
    for word in ("Trigger", "rule group", "always true", "export columns", "firefly", "dawarich", "plausible"):
        assert word not in text, word


def test_keep_agreeing_swaps_the_output_rule(tmp_path):
    doc = {"leads": [lead("dupblock", "api/m.py", "web/m.ts")]}
    leadcheck.write(doc, tmp_path, tmp_path / "a", [])
    leadcheck.write(doc, tmp_path, tmp_path / "b", [], keep_agreeing=True)
    only, keep = (tmp_path / "a/lead-check-brief.md").read_text(), (tmp_path / "b/lead-check-brief.md").read_text()
    assert "Put in it only:" in only and "keep if a seam" not in only
    assert "only from a lead marked `(keep if a seam)`" in keep and '"lead": <the lead' in keep


def test_keep_agreeing_marks_only_the_precise_lead_kinds(tmp_path):
    doc = {"leads": [lead("flow", "api/a.py", "web/b.ts"), lead("dupblock", "api/c.py", "web/d.ts")]}
    leadcheck.write(doc, tmp_path, tmp_path / "k", [], keep_agreeing=True)
    text = (tmp_path / "k/packets/lc-01.md").read_text()
    assert "flow: api/a.py:1, web/b.ts:1 (d) (keep if a seam)" in text and "web/d.ts:1 (d)\n" in text
    leadcheck.write(doc, tmp_path, tmp_path / "n", [])
    assert "keep if a seam" not in (tmp_path / "n/packets/lc-01.md").read_text()
