"""The gap pass: a second full review that gets the recorded seams and hunts for the ones they miss."""
from __future__ import annotations

import json

from seams import cli, split


def make(tmp_path, seams):
    files = {"api/status.py": 'STATUSES = ["open", "held", "closed"]\n',
             "web/status.ts": 'export const STATUSES = ["open", "held", "closed"];\n',
             "web/labels.ts": 'export const STATUSES = ["open", "held", "closed"];\n',
             "lib/other.py": "x = 1\n"}
    for p, text in files.items():
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text(text)
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": seams}))
    assert cli.main(["scan", "--root", str(tmp_path)]) == 0
    return tmp_path / ".seams-scan"


SEAM = {"id": "status-names", "title": "Status names", "kind": "vocabulary", "must_agree": "Same names.",
        "copies": [{"path": "api/status.py"}, {"path": "web/status.ts"}], "consequence": "x", "risk": "high"}


def test_gap_packets_list_the_recorded_seams_and_say_what_to_hunt(tmp_path, capsys):
    out = make(tmp_path, [SEAM])
    assert cli.main(["split", "--gap", "--root", str(tmp_path)]) == 0
    [packet] = list((out / "packets").glob("gap-*.md"))
    text = packet.read_text()
    assert "## Gap pass" in text and "assume this list misses about half" in text
    assert "**status-names** (high): Same names. Copies: `api/status.py`, `web/status.ts`" in text
    assert "Gap pass:" in (out / "plan.md").read_text()


def test_a_lead_is_dropped_only_when_one_seam_lists_all_its_files():
    lead = {"files": [{"path": "src/util.js"}, {"path": "src/util.ts"}, {"path": "server/maintenance.js"}]}
    compiled = dict(SEAM, id="util-compiled", copies=[{"path": "src/util.ts"}, {"path": "src/util.js"}])
    # Two shared files are enough for the scan's covered_by, but maintenance.js may hold a
    # second seam, so the gap pass keeps the lead. (uptime-kuma: the date lead was hidden this way.)
    assert not split._fully_covered(lead, [compiled])
    every_file = dict(compiled, copies=compiled["copies"] + [{"path": "server/maintenance.js"}])
    assert split._fully_covered(lead, [every_file])
    # A glob matches a whole family and says nothing about a second seam there (frigate: 813 leads hidden).
    family = dict(compiled, copies=compiled["copies"] + [{"path": "server/*.js"}])
    assert not split._fully_covered(lead, [family])


def test_gap_needs_a_registry_with_seams(tmp_path, capsys):
    make(tmp_path, [])
    assert cli.main(["split", "--gap", "--root", str(tmp_path)]) == 2
    assert "records no seams yet" in capsys.readouterr().err


def test_gap_does_not_combine_with_a_lead_only_review(tmp_path, capsys):
    make(tmp_path, [SEAM])
    assert cli.main(["split", "--gap", "--new-only", "--root", str(tmp_path)]) == 2


def test_a_seam_with_only_root_file_copies_is_listed_in_every_gap_packet(tmp_path, capsys):
    (tmp_path / ".gitignore").write_text("node_modules\n")
    (tmp_path / ".dockerignore").write_text("node_modules\n")
    root_seam = dict(SEAM, id="ignore-mirror", copies=[{"path": ".gitignore"}, {"path": ".dockerignore"}])
    out = make(tmp_path, [SEAM, root_seam])
    cli.main(["split", "--gap", "--root", str(tmp_path)])
    for packet in (out / "packets").glob("gap-*.md"):
        assert "**ignore-mirror**" in packet.read_text()


def test_a_gap_pass_moves_earlier_reviews_and_results_aside(tmp_path, capsys):
    out = make(tmp_path, [SEAM])
    (out / "reviews").mkdir(parents=True, exist_ok=True)
    (out / "reviews" / "seam-review-gap-p01-x.json").write_text("[]")
    (out / "verify" / "results").mkdir(parents=True)
    (out / "verify" / "results" / "status-names.json").write_text("{}")
    cli.main(["split", "--gap", "--root", str(tmp_path)])
    assert not list((out / "reviews").glob("seam-review-*.json"))
    assert len(list((out / "reviews" / "done").glob("*/seam-review-gap-p01-x.json"))) == 1
    assert not list((out / "verify" / "results").glob("*.json"))
