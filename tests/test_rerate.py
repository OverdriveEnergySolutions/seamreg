"""Risk re-rating: packets of recorded seams for a stronger model, and the collect step."""
from __future__ import annotations

import json

from seams import cli, rerate


def seam(i, risk="low"):
    return {"id": f"s{i}", "title": f"S{i}", "kind": "vocabulary", "must_agree": "Same.", "risk": risk,
            "consequence": "c", "copies": [{"path": "a.py"}, {"path": "b.py"}]}


def repo(tmp_path, n=3):
    for f in ("a.py", "b.py"):
        (tmp_path / f).write_text("x\n")
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [seam(i) for i in range(n)]}))
    return tmp_path


def test_packets_hold_every_seam_with_its_current_risk(tmp_path, capsys):
    root = repo(tmp_path, 35)
    assert cli.main(["rerate", "--root", str(root)]) == 0
    packets = sorted((root / ".seams-scan/rerate/packets").glob("*.md"))
    assert [p.name for p in packets] == ["rr-01.md", "rr-02.md"]
    text = packets[1].read_text()
    assert "Current risk: **low**" in text and "rerate/results/rr-02.json" in text and "brief.md" in text
    assert (root / ".seams-scan/rerate/brief.md").read_text().startswith("# Risk re-rating brief")


def test_collect_writes_new_risks_and_reports_each_change(tmp_path, capsys):
    root = repo(tmp_path)
    cli.main(["rerate", "--root", str(root)])
    (root / ".seams-scan/rerate/results/rr-01.json").write_text(json.dumps([
        {"id": "s0", "risk": "high", "reason": "Sign-in skips a check."},
        {"id": "s1", "risk": "low", "reason": "Cosmetic."},
        {"id": "nope", "risk": "high"}, {"id": "s2", "risk": "severe"}]))
    assert cli.main(["rerate", "--root", str(root), "--collect"]) == 0
    risks = {s["id"]: s["risk"] for s in json.loads((root / "seams.json").read_text())["seams"]}
    assert risks == {"s0": "high", "s1": "low", "s2": "low"}
    report = (root / ".seams-scan/rerate/rerate-report.md").read_text()
    assert "`s0`: low to **high**. Sign-in skips a check." in report and "unknown id or risk" in report
    assert "1 raised" in capsys.readouterr().out


def test_ids_limits_the_packets_to_the_named_seams(tmp_path, capsys):
    # A diff scan re-rates only the seams it added.
    root = repo(tmp_path, 5)
    assert cli.main(["rerate", "--root", str(root), "--ids", "s1,s3"]) == 0
    [packet] = (root / ".seams-scan/rerate/packets").glob("*.md")
    text = packet.read_text()
    assert "## Seams (2)" in text and "`s1`" in text and "`s3`" in text and "`s0`" not in text


def test_ids_naming_no_recorded_seam_is_an_error(tmp_path, capsys):
    root = repo(tmp_path, 2)
    assert cli.main(["rerate", "--root", str(root), "--ids", "nope"]) == 2
    assert "nope" in capsys.readouterr().err
