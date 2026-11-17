from __future__ import annotations

from pathlib import Path

from seams import cli, scan, split

TOY = Path(__file__).parent / "fixtures" / "toy-repo"


def doc_with(files, leads):
    return {"files": [{"path": p, "area": a, "lines": n, "test": False} for p, a, n in files],
            "leads": [{"kind": "marker", "files": [{"path": p} for p in ps], "areas": sorted(set(a)),
                       "cross_area": len(set(a)) > 1, "score": 1, "detail": "x"} for ps, a in leads],
            "areas": []}


def test_linked_areas_share_a_packet_and_unlinked_ones_pack_by_size():
    # Packing by size alone would pair api with web (name order). The link pairs api with worker.
    doc = doc_with(
        [("api/a.py", "api", 40), ("web/a.ts", "web", 40), ("worker/a.py", "worker", 40)],
        [(["api/a.py", "worker/a.py"], ["api", "worker"])])
    bins = split.plan(doc, max_lines=80)
    assert [sorted(b["units"]) for b in bins] == [["api", "worker"], ["web"]]


def test_a_link_never_overfills_a_packet():
    doc = doc_with([("api/a.py", "api", 60), ("web/a.ts", "web", 60)],
                   [(["api/a.py", "web/a.ts"], ["api", "web"])])
    assert len(split.plan(doc, max_lines=100)) == 2


def test_an_oversized_area_splits_into_subfolders():
    doc = doc_with([("api/x/a.py", "api", 60), ("api/y/b.py", "api", 60), ("api/c.py", "api", 10)], [])
    units = sorted(u for b in split.plan(doc, max_lines=100) for u in b["units"])
    assert units == ["api/*", "api/x", "api/y"]


def test_a_flat_oversized_area_stays_whole():
    doc = doc_with([("api/a.py", "api", 60), ("api/b.py", "api", 60)], [])
    [b] = split.plan(doc, max_lines=100)
    assert b["units"] == ["api"] and b["lines"] == 120


def test_test_lines_do_not_count_toward_size():
    doc = doc_with([("api/a.py", "api", 60)], [])
    doc["files"].append({"path": "api/test_a.py", "area": "api", "lines": 500, "test": True})
    assert split.plan(doc, max_lines=100)[0]["lines"] == 60


def test_each_lead_goes_to_exactly_one_packet():
    doc = doc_with(
        [("api/a.py", "api", 60), ("web/a.ts", "web", 60), ("web/b.ts", "web", 1)],
        [(["api/a.py", "web/a.ts", "web/b.ts"], ["api", "web", "web"]), (["api/a.py"], ["api"])])
    bins = split.plan(doc, max_lines=100)
    assert sum(len(b["leads"]) for b in bins) == 2
    web = next(b for b in bins if "web" in b["units"])
    assert len(web["leads"]) == 1  # two of the three files are in web


def test_cli_split_writes_brief_packets_and_plan(tmp_path, capsys):
    out = tmp_path / "out"
    cli.main(["scan", "--root", str(TOY), "--out", str(out)])
    assert cli.main(["split", "--root", str(TOY), "--out", str(out)]) == 0
    assert (out / "brief.md").read_text() == split.BRIEF.read_text()
    packets = list((out / "packets").glob("*.md"))
    assert packets and (out / "reviews").is_dir() and (out / "plan.md").exists()
    text = packets[0].read_text()
    assert str(out / "brief.md") in text and "seam-review-" in text and str(TOY.resolve()) in text


def test_cli_split_without_a_scan_exits_2(tmp_path):
    assert cli.main(["split", "--root", str(tmp_path)]) == 2


def test_cli_split_refuses_a_scan_from_before_file_lines(tmp_path):
    (tmp_path / ".seams-scan").mkdir()
    (tmp_path / ".seams-scan" / "leads.json").write_text('{"leads": [], "areas": []}')
    assert cli.main(["split", "--root", str(tmp_path)]) == 2


def test_packet_caps_leads_and_keeps_cross_area_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(split, "MAX_LEADS", 1)
    doc = doc_with([("api/a.py", "api", 10), ("web/a.ts", "web", 10)],
                   [(["api/a.py"], ["api"]), (["api/a.py", "web/a.ts"], ["api", "web"])])
    [b] = split.plan(doc)
    text = split.packet_md(b, [b], tmp_path, tmp_path)
    assert "[cross-area]" in text and "1 weaker leads" in text


def test_a_real_lead_beats_a_cross_area_tie_candidate_for_a_slot(tmp_path, monkeypatch):
    # Tie candidates are cross-area, so they used to win slots over real seam leads.
    monkeypatch.setattr(split, "MAX_LEADS", 1)
    doc = doc_with([("api/a.py", "api", 10), ("web/a.ts", "web", 10)], [])
    doc["leads"] = [
        {"kind": "tie-candidate", "files": [{"path": "api/a.py"}, {"path": "web/a.ts"}], "areas": ["api", "web"],
         "cross_area": True, "score": 5, "detail": "test reads web/a.ts"},
        {"kind": "literal-set", "files": [{"path": "api/a.py"}], "areas": ["api"],
         "cross_area": False, "score": 1, "detail": "names"}]
    [b] = split.plan(doc)
    assert [l["kind"] for l in split.shown_leads(b)] == ["literal-set"]


def test_json_data_does_not_count_toward_packet_size():
    # A folder of translation files once filled a packet of its own, with no code to review.
    doc = doc_with([("server/a.js", "server", 50), ("src/a.vue", "src", 50),
                    ("src/lang/en.json", "src/lang", 5000), ("src/lang/de.json", "src/lang", 5000)], [])
    bins = split.plan(doc, max_lines=100)
    assert len(bins) == 1 and bins[0]["lines"] == 100


def test_convention_leads_keep_their_slots_in_a_full_packet():
    # A family sits in one area, so cross-area leads used to take every slot.
    cross = [{"kind": "literal-set", "cross_area": True, "score": 9.0, "files": [], "n": i}
             for i in range(split.MAX_LEADS)]
    conv = [{"kind": "convention", "cross_area": False, "score": 1.0, "files": [], "n": i} for i in range(3)]
    shown = split.shown_leads({"leads": cross + conv})
    assert len(shown) == split.MAX_LEADS
    assert sum(l["kind"] == "convention" for l in shown) == 3
