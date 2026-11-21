"""The drift check pass: packets per seam, and collecting what the checkers found."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seams import check, cli, verify


def seam(sid, risk="high", **over):
    s = {"id": sid, "title": sid.title(), "kind": "vocabulary", "must_agree": "Same names.",
         "consequence": "A status vanishes.", "risk": risk,
         "copies": [{"path": "a.py", "symbol": "NAMES"}, {"path": "b.py"}]}
    s.update(over)
    return s


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "a.py").write_text("NAMES = []\n")
    (tmp_path / "b.py").write_text("x\n")
    reg = {"schema_version": 1, "seams": [
        seam("open-high"), seam("open-medium", risk="medium"),
        seam("has-drift", drift={"text": "differs", "source": "reading"}),
        seam("deliberate", intentional_differences="b sorts them")]}
    (tmp_path / "seams.json").write_text(json.dumps(reg))
    return tmp_path


def result(repo, **res):
    d = repo / ".seams-scan" / "verify" / "results"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{res['id']}.json").write_text(json.dumps(res))


def test_default_checks_high_and_medium_seams_with_no_drift(repo):
    chosen = verify.write_packets(repo / "seams.json", repo, repo / ".seams-scan")
    assert [s["id"] for s in chosen] == ["open-high", "open-medium", "deliberate"]
    packet = (repo / ".seams-scan/verify/packets/deliberate.md").read_text()
    assert "Deliberate differences, ignore these:** b sorts them" in packet
    assert "`a.py` (`NAMES`)" in packet and "results/deliberate.json" in packet


def test_a_packet_lists_the_ties_to_check(repo):
    reg = {"schema_version": 1, "seams": [seam("tied", ties=[{"path": "a.py", "test": "NAMES", "covers": "all"}])]}
    (repo / "seams.json").write_text(json.dumps(reg))
    verify.write_packets(repo / "seams.json", repo, repo / ".seams-scan")
    assert "- `a.py` (`NAMES`), covers all" in (repo / ".seams-scan/verify/packets/tied.md").read_text()


def test_ids_narrow_the_default_and_all_takes_every_one(repo):
    data = check.load(repo / "seams.json")
    assert [s["id"] for s in verify.select(data, ids={"open-medium"})] == ["open-medium"]
    assert len(verify.select(data, every=True)) == 4


def test_ids_keep_the_default_selection_among_them(repo):
    # A diff scan names its new seams. One that already has drift recorded needs no drift check.
    data = check.load(repo / "seams.json")
    assert [s["id"] for s in verify.select(data, ids={"open-high", "has-drift"})] == ["open-high"]
    assert sorted(s["id"] for s in verify.select(data, ids={"open-high", "has-drift"}, every=True)) == \
        ["has-drift", "open-high"]


def test_collect_writes_new_drift_as_reading(repo):
    result(repo, id="open-high", agree=False, drift="a.py:1 has x; b.py:1 lacks it", checked="Listed both.")
    lines, _, errors, counts = verify.collect(repo / "seams.json", repo / ".seams-scan", today="2026-11-15")
    s = {x["id"]: x for x in check.load(repo / "seams.json")["seams"]}
    assert s["open-high"]["drift"] == {"text": "a.py:1 has x; b.py:1 lacks it", "source": "reading", "seen": "2026-11-15"}
    assert errors == [] and any("drift found" in l for l in lines) and counts["drift"] == 1


def test_collect_never_overwrites_drift_already_recorded(repo):
    result(repo, id="has-drift", agree=False, drift="something else", checked="Listed both.")
    lines, _, _, _ = verify.collect(repo / "seams.json", repo / ".seams-scan")
    s = {x["id"]: x for x in check.load(repo / "seams.json")["seams"]}
    assert s["has-drift"]["drift"]["text"] == "differs" and "saw a difference too" in lines[0]


def test_collect_reports_agreement_and_bad_results(repo):
    result(repo, id="open-high", agree=True, checked="Listed 4 names on each side.")
    result(repo, id="ghost", agree=False, drift="x", checked="y")
    (repo / ".seams-scan/verify/results/bad.json").write_text('{"id": "x"}')
    lines, _, _, _ = verify.collect(repo / "seams.json", repo / ".seams-scan")
    text = "\n".join(lines)
    assert "copies agree" in text and "no such seam" in text and "wrong shape" in text


def test_collect_keeps_security_detail_out_of_the_registry(repo):
    result(repo, id="open-high", agree=False, drift="b skips a check", checked="c",
           sensitive_finding="how to bypass it")
    _, private, _, _ = verify.collect(repo / "seams.json", repo / ".seams-scan")
    reg = (repo / "seams.json").read_text()
    assert "how to bypass it" not in reg and any("how to bypass it" in p for p in private)
    assert "kept out of this repo" in reg
    # The checker's drift text for a security hole stays private too: it often says how to use it.
    assert "b skips a check" not in reg and any("b skips a check" in p for p in private)
    assert verify.SENSITIVE_DRIFT in reg


def test_cli_verify_writes_packets_then_collects(repo, capsys):
    assert cli.main(["verify", "--root", str(repo)]) == 0
    assert (repo / ".seams-scan/verify/brief.md").read_text() == verify.BRIEF.read_text()
    assert (repo / ".seams-scan/verify/packets/open-medium.md").exists()  # the command's default too
    result(repo, id="open-high", agree=False, drift="differs now", checked="Listed both.")
    assert cli.main(["verify", "--root", str(repo), "--collect"]) == 0
    assert "drift found" in (repo / ".seams-scan/verify/verify-report.md").read_text()
    assert check.check(check.load(repo / "seams.json"), repo) == []


def test_brief_example_matches_what_collect_accepts():
    brief = Path(verify.__file__).with_name("verify-brief.md").read_text()
    example = json.loads(brief.split("```json", 1)[1].split("```", 1)[0])
    errors = []
    check.validate(example, verify.RESULT, "brief example", errors)
    assert errors == [] and set(example) == set(verify.RESULT["properties"])


def test_a_registry_that_fails_the_schema_is_refused_before_any_write(tmp_path):
    # An id like ../../x would otherwise name a packet path outside the packets folder.
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / "b.py").write_text("x\n")
    reg = {"schema_version": 1, "seams": [seam("../../escape")]}
    (tmp_path / "seams.json").write_text(json.dumps(reg))
    assert cli.main(["verify", "--root", str(tmp_path), "--all"]) == 2
    assert not list(tmp_path.parent.glob("escape*"))
    assert cli.main(["verify", "--root", str(tmp_path), "--collect"]) == 2


def test_packet_paths_stay_inside_their_folder(tmp_path):
    with pytest.raises(ValueError):
        verify._inside(tmp_path / "packets", "../../x.md")


def test_collect_keeps_a_security_finding_when_the_copies_agree(repo):
    # A checker can see a security gap that is not drift. It must still reach the private file.
    result(repo, id="open-high", agree=True, checked="Listed both.", sensitive_finding="one copy skips a check")
    lines, private, _, counts = verify.collect(repo / "seams.json", repo / ".seams-scan")
    reg = check.load(repo / "seams.json")
    s = {x["id"]: x for x in reg["seams"]}["open-high"]
    assert "one copy skips a check" in private[0] and "one copy skips a check" not in json.dumps(reg)
    assert "kept out of this repo" in s["sensitive"] and not s.get("drift") and counts["sensitive"] == 1


def test_collect_keeps_a_pointer_the_user_already_filed(repo):
    reg = check.load(repo / "seams.json")
    reg["seams"][0]["sensitive"] = "See ticket SEC-12."
    (repo / "seams.json").write_text(json.dumps(reg))
    result(repo, id="open-high", agree=True, checked="c", sensitive_finding="detail")
    _, private, _, _ = verify.collect(repo / "seams.json", repo / ".seams-scan")
    assert private and check.load(repo / "seams.json")["seams"][0]["sensitive"] == "See ticket SEC-12."


def test_collect_counts_result_files_not_report_lines(repo, capsys):
    result(repo, id="open-high", agree=False, drift="differs", checked="c", sensitive_finding="detail")
    result(repo, id="deliberate", agree=True, checked="c")
    assert cli.main(["verify", "--root", str(repo), "--collect"]) == 0
    assert "2 result file(s), 1 with new drift" in capsys.readouterr().out


def test_sample_picks_a_repeatable_random_subset(repo):
    reg = {"schema_version": 1, "seams": [seam(f"s{i:02d}") for i in range(20)]}
    (repo / "seams.json").write_text(json.dumps(reg))
    a = [s["id"] for s in verify.select(check.load(repo / "seams.json"), sample=5, seed=3)]
    b = [s["id"] for s in verify.select(check.load(repo / "seams.json"), sample=5, seed=3)]
    c = [s["id"] for s in verify.select(check.load(repo / "seams.json"), sample=5, seed=4)]
    assert len(a) == 5 and a == b and a != c
    assert len(verify.select(check.load(repo / "seams.json"), sample=50)) == 20


def test_cli_sample_writes_only_the_picked_packets_and_names_them(repo, capsys):
    reg = {"schema_version": 1, "seams": [seam(f"s{i:02d}") for i in range(20)]}
    (repo / "seams.json").write_text(json.dumps(reg))
    assert cli.main(["verify", "--root", str(repo)]) == 0
    assert cli.main(["verify", "--root", str(repo), "--sample", "4", "--seed", "1"]) == 0
    out = capsys.readouterr().out
    packets = sorted(p.stem for p in (repo / ".seams-scan/verify/packets").glob("*.md"))
    assert len(packets) == 4 and "picked at random: " + ", ".join(packets) in out


def test_a_sample_takes_high_risk_seams_first(repo):
    reg = {"schema_version": 1, "seams": [seam(f"m{i:02d}", risk="medium") for i in range(10)]
           + [seam(f"h{i}") for i in range(3)]}
    (repo / "seams.json").write_text(json.dumps(reg))
    picked = verify.select(check.load(repo / "seams.json"), sample=5, seed=2)
    assert len(picked) == 5 and {s["id"] for s in picked} >= {"h0", "h1", "h2"}
    assert sum(s["risk"] == "medium" for s in picked) == 2


def test_both_briefs_and_agents_keep_the_agent_inside_the_repo():
    # A drift checker once ran `find` across the home folder and read the npm cache.
    root = Path(verify.__file__).parents[2]
    for f in ("src/seams/brief.md", "src/seams/verify-brief.md"):
        assert "**Stay inside the repo.**" in (root / f).read_text(), f
    assert "## Stay inside the repo" in (root / "src/seams/tie-brief.md").read_text()
    for f in ("agents/seam-reviewer.md", "agents/seam-drift-checker.md", "agents/seam-tie-writer.md"):
        assert "Stay inside the repo root" in (root / f).read_text(), f


def test_verify_prints_a_cost(repo, capsys):
    assert cli.main(["verify", "--root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "3 drift-check packet(s)" in out and "Cost at default effort: about 192k tokens" in out


def test_reading_picks_drift_found_by_reading_and_collect_only_reports(repo):
    chosen = verify.write_packets(repo / "seams.json", repo, repo / ".seams-scan", reading=True)
    assert [s["id"] for s in chosen] == ["has-drift"]
    assert "differs" not in (repo / ".seams-scan/verify/packets/has-drift.md").read_text()
    result(repo, id="has-drift", agree=True, checked="Listed both.")
    lines, _, _, _ = verify.collect(repo / "seams.json", repo / ".seams-scan")
    assert "found none" in "\n".join(lines)
    assert check.load(repo / "seams.json")["seams"][2]["drift"]["text"] == "differs"


def test_collect_names_another_seam_with_drift_at_the_same_place(repo):
    reg = check.load(repo / "seams.json")
    reg["seams"][2]["drift"]["text"] = "docs/research.md:29 links to-prd."
    (repo / "seams.json").write_text(json.dumps(reg))
    result(repo, id="open-high", agree=False, drift="docs/research.md:29 links to-prd.", checked="x")
    lines, _, _, _ = verify.collect(repo / "seams.json", repo / ".seams-scan")
    assert "seam `has-drift` records drift at the same place: `docs/research.md:29`" in "\n".join(lines)


def test_a_low_risk_convention_seam_is_checked_by_default():
    # A convention rule covers many members; on netbox the low-risk ones held real drift.
    data = {"seams": [seam("low-mirror", risk="low"), seam("low-rule", risk="low", kind="convention"),
                      seam("low-rule-drifted", risk="low", kind="convention", drift={"text": "x", "source": "reading"})]}
    assert [s["id"] for s in verify.select(data)] == ["low-rule"]


def test_ids_not_in_the_registry_stop_before_old_packets_go(repo):
    verify.write_packets(repo / "seams.json", repo, repo / ".seams-scan")
    before = sorted(p.name for p in (repo / ".seams-scan/verify/packets").glob("*.md"))
    with pytest.raises(ValueError, match="no seam with the id brand-new.*--registry"):
        verify.write_packets(repo / "seams.json", repo, repo / ".seams-scan", ids={"open-high", "brand-new"})
    assert sorted(p.name for p in (repo / ".seams-scan/verify/packets").glob("*.md")) == before and before
