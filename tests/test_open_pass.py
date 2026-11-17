"""The open pass: no fixed rule, told what earlier passes did and where their reviewers looked."""
from __future__ import annotations

import json

from seams import cli, lookedat

SEAM = {"id": "s", "title": "S", "kind": "vocabulary", "must_agree": "Both lists agree.", "risk": "low",
        "consequence": "c", "copies": [{"path": "api/s.py"}, {"path": "web/s.ts"}]}


def repo(tmp_path):
    for f, t in {"api/s.py": "S = ['a', 'b']\n", "web/s.ts": "export const S = ['a', 'b']\n",
                 "docs/guide.md": "# Guide\n\nlist a, b\n"}.items():
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text(t)
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [SEAM]}))
    return tmp_path


def transcript(path, root, calls):
    lines = [json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": n, "input": i} for n, i in calls]}})]
    path.write_text("\n".join(lines) + "\n")


def test_looked_at_reads_read_calls_bash_commands_and_other_roots(tmp_path):
    root = repo(tmp_path / "r")
    t = tmp_path / "t"
    t.mkdir()
    transcript(t / "a.jsonl", root, [("Read", {"file_path": str(root / "api/s.py")}),
                                     ("Bash", {"command": "cat /old/copy/web/s.ts | head"}),
                                     ("Read", {"file_path": "/etc/passwd"}), ("Grep", {"path": str(root / "docs")})])
    (t / "sub").mkdir()
    transcript(t / "sub" / "b.jsonl", root, [("Read", {"file_path": str(root / "api/s.py")})])
    doc = lookedat.collect(root, [t], ["/old/copy"], ["first"])
    assert doc["read"] == {"api/s.py": 2, "web/s.ts": 1} and doc["searched"] == {"docs": 1}
    assert doc["transcripts"] == 2 and doc["passes"] == ["first"]


def test_summary_puts_unread_folders_first():
    rows = lookedat.summary({"read": {"api/s.py": 1}}, {"api/s.py": 10, "web/s.ts": 30, "README.md": 5})
    assert rows[0]["folder"] == "web" and rows[0]["share_read"] == 0
    assert {r["folder"] for r in rows} == {"web", "api", "(root files)"}


def test_open_packet_lists_perspectives_and_looked_at_and_no_leads(tmp_path, capsys):
    root = repo(tmp_path)
    t = tmp_path / "t.jsonl"
    transcript(t, root, [("Read", {"file_path": str(root / "api/s.py")})])
    assert cli.main(["scan", "--root", str(root)]) == 0
    assert cli.main(["looked-at", "--root", str(root), str(t), "--pass", "first", "--pass", "focus:twins"]) == 0
    assert cli.main(["split", "--root", str(root), "--focus", "open"]) == 0
    text = (root / ".seams-scan/packets/focus-open.md").read_text()
    assert "## Focused pass: whatever kind of seam" in text and "**s** (low)" in text
    assert "Passes run: first, focus:twins" in text and "Recorded seams by kind: vocabulary 1" in text
    assert "`web`: 0 of 1 files opened" in text and "## Leads" not in text


def test_open_packet_without_a_map_says_so(tmp_path):
    root = repo(tmp_path)
    assert cli.main(["scan", "--root", str(root)]) == 0
    assert cli.main(["split", "--root", str(root), "--focus", "open"]) == 0
    assert "Not known: no looked-at.json" in (root / ".seams-scan/packets/focus-open.md").read_text()


def test_the_open_brief_names_no_benchmark():
    from seams import split
    text = split.FOCUS["open"]["text"].lower()
    for word in ("netbox", "umami", "memos", "kuma", "frigate", "pocock", "mixin", "dockerfile"):
        assert word not in text
