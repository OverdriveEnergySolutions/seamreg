"""The twin lead: two implementations of one behavior."""
from __future__ import annotations

import json

from seams import cli
from seams.scan import twins
from seams.scan.inventory import Inventory


def write(root, files):
    for path, text in files.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def signals(root, signal):
    return [sorted(p for p, _, _ in l.locs) for l in twins.find(Inventory(root)) if l.extra["signal"] == signal]


def test_two_alike_patterns_in_two_files_are_twins(tmp_path):
    write(tmp_path, {
        "web/toggle.ts": "const taskPattern = /^(\\s*[-*+]\\s+)\\[([ xX])\\](\\s+.*)$/;\n",
        "web/actions.ts": "const TASK_LINE = /^(\\s*)((?:[-*+])|(?:\\d+[.)]))(\\s+)\\[([ xX])\\]/;\n",
        # Unrelated patterns, as any repo has: they make the shared checkbox pieces rare.
        "web/other.ts": ("const EMAIL = /^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$/;\n"
                         "const HEX = /^#(?:[0-9a-fA-F]{3}){1,2}$/;\n"
                         "const SEMVER = /^v?(\\d+)\\.(\\d+)\\.(\\d+)(?:-[\\w.]+)?$/;\n"
                         "const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;\n"
                         "const ISO = /^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}/;\n"),
    })
    assert signals(tmp_path, "pattern") == [["web/actions.ts", "web/toggle.ts"]]


def test_files_in_two_languages_that_share_rare_words_are_twins(tmp_path):
    words = "func isMentionBoundary(r rune) bool { return maxMentionLength > 0 }\n"
    write(tmp_path, {
        "server/parser/mention.go": words,
        "web/utils/remark-mention.ts": "export function isMentionBoundary(c) { return MAX_MENTION_LENGTH > 0; }\n",
        # Named alike but sharing no rare word: a component that shows a mention, not a second parser.
        "web/components/Mention.tsx": "export const Mention = () => <span>@</span>;\n",
    })
    assert signals(tmp_path, "language") == [["server/parser/mention.go", "web/utils/remark-mention.ts"]]


def test_one_file_per_backend_is_a_twin(tmp_path):
    write(tmp_path, {f"store/db/{b}/memo.go": "package db\n" for b in ("sqlite", "mysql", "postgres")})
    assert signals(tmp_path, "backend") == [["store/db/mysql/memo.go", "store/db/postgres/memo.go",
                                             "store/db/sqlite/memo.go"]]


def test_per_backend_functions_across_a_family_are_one_lead(tmp_path):
    body = "async function relationalQuery(a) {}\nasync function clickhouseQuery(a) {}\n"
    write(tmp_path, {f"src/queries/q{i}.ts": body for i in range(5)})
    found = [l for l in twins.find(Inventory(tmp_path)) if l.extra["signal"] == "branch"]
    assert len(found) == 1 and found[0].extra["files"] == 5 and "convention seam" in found[0].detail


def test_split_focus_twins_makes_one_packet_of_twin_leads(tmp_path, capsys):
    write(tmp_path, {
        "web/toggle.ts": "const taskPattern = /^(\\s*[-*+]\\s+)\\[([ xX])\\](\\s+.*)$/;\n",
        "web/actions.ts": "const TASK_LINE = /^(\\s*)((?:[-*+])|(?:\\d+[.)]))(\\s+)\\[([ xX])\\]/;\n",
        "api/status.py": "STATUSES = ['open', 'held', 'closed', 'void']\n",
        "web/status.ts": "export const STATUSES = ['open', 'held', 'closed', 'void'];\n",
    })
    seam = {"id": "status-names", "title": "Status names", "kind": "vocabulary", "must_agree": "Same names.",
            "copies": [{"path": "api/status.py"}, {"path": "web/status.ts"}], "consequence": "x", "risk": "low"}
    assert cli.main(["split", "--root", str(tmp_path), "--focus", "twins"]) == 2  # needs a scan and a registry
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [seam]}))
    assert cli.main(["scan", "--root", str(tmp_path)]) == 0
    assert cli.main(["split", "--root", str(tmp_path), "--gap", "--focus", "twins"]) == 2
    assert cli.main(["split", "--root", str(tmp_path), "--focus", "twins"]) == 0
    packets = list((tmp_path / ".seams-scan/packets").glob("*.md"))
    assert [p.name for p in packets] == ["focus-twins.md"]
    text = packets[0].read_text()
    assert "## Focused pass: two implementations of one behavior" in text and "**status-names**" in text
    assert "- twin:" in text and "- literal-set:" not in text
    assert "Focused pass (twins)" in (tmp_path / ".seams-scan/plan.md").read_text()


def test_a_crafted_unterminated_pattern_does_not_hang_the_scan(tmp_path):
    # 40 backslashes and no closing quote took the old pattern about 15 seconds, doubling every few more.
    # A short line, so the scan does not skip the file as minified.
    import time
    write(tmp_path, {"web/evil.ts": "x = new RegExp('" + "\\\\" * 20 + "\n",
                     "web/ok.ts": "x = new RegExp('^[a-z]+-[0-9]{2,}$');\n"})
    inv = Inventory(tmp_path)
    assert "web/evil.ts" in inv.read
    started = time.time()
    twins.find(inv)
    assert time.time() - started < 1
    assert twins._patterns(inv, ["web/ok.ts"])[0][2] == "^[a-z]+-[0-9]{2,}$"


def test_a_block_comment_is_not_a_pattern(tmp_path):
    write(tmp_path, {f"src/a{i}.ts": "/* eslint-disable no-console */\nexport const x = 1;\n" for i in range(3)})
    assert twins._patterns(Inventory(tmp_path), [f"src/a{i}.ts" for i in range(3)]) == []
