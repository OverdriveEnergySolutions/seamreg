"""The note generator: rules files or CLAUDE.md blocks, and the check that keeps them current."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from seams import check, cli

HIGH = {"id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
        "must_agree": "Both lists hold the same names.",
        "copies": [{"path": "api/status.py"}, {"path": "web/src/status.ts"}],
        "consequence": "x", "risk": "high"}
LOW = {"id": "log-format", "title": "Log line format", "kind": "contract",
       "must_agree": "Both sides use the same log fields.",
       "copies": [{"path": "api/log.py"}, {"path": "web/src/*.ts"}], "consequence": "x", "risk": "low"}


@pytest.fixture
def repo(tmp_path):
    for f in ["api/status.py", "api/log.py", "web/src/status.ts", "web/src/log.ts"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x\n")
    return tmp_path


def registry(repo, notes, *seams):
    data = {"schema_version": 1, "seams": list(seams)}
    if notes:
        data["notes"] = notes
    (repo / "seams.json").write_text(json.dumps(data))
    return data


def notes(repo, capsys):
    code = check.main(["--root", str(repo), "--notes"])
    out = capsys.readouterr()
    return code, out.out + out.err


def plain(repo, capsys):
    code = check.main(["--root", str(repo)])
    out = capsys.readouterr()
    return code, out.out + out.err


# --- rules mode ------------------------------------------------------------------

def test_rules_mode_writes_one_rule_per_seam_scoped_to_its_copies(repo, capsys):
    registry(repo, "rules", HIGH, LOW)
    assert notes(repo, capsys)[0] == 0
    text = (repo / ".claude/rules/seams/order-statuses.md").read_text()
    assert text.startswith('---\npaths:\n  - "api/status.py"\n  - "web/src/status.ts"\n---\n')
    assert "other copies" in text and check.GENERATED in text
    assert (repo / ".claude/rules/seams/log-format.md").exists()  # every risk: a rule costs nothing until read


def test_rules_mode_deletes_generated_rules_it_no_longer_needs_but_never_hand_written_ones(repo, capsys):
    registry(repo, "rules", HIGH, LOW)
    notes(repo, capsys)
    own = repo / ".claude/rules/seams/mine.md"
    own.write_text("---\npaths:\n  - \"api/**\"\n---\nmy own rule\n")
    registry(repo, "rules", HIGH)
    notes(repo, capsys)
    assert not (repo / ".claude/rules/seams/log-format.md").exists()
    assert own.exists()


def test_plain_check_fails_when_notes_fall_behind(repo, capsys):
    registry(repo, "rules", HIGH)
    notes(repo, capsys)
    assert plain(repo, capsys)[0] == 0
    changed = dict(HIGH, must_agree="Both lists hold the same names, in the same order.")
    registry(repo, "rules", changed)
    code, out = plain(repo, capsys)
    assert code == 1 and "out of date" in out and "--notes" in out


def test_writing_notes_twice_changes_nothing(repo, capsys):
    registry(repo, "rules", HIGH, LOW)
    notes(repo, capsys)
    assert "0 file(s) changed" in notes(repo, capsys)[1]


def test_rules_path_with_a_quote_stays_valid_yaml():
    seam = dict(HIGH, copies=[{"path": 'a/b"c.py'}, {"path": "d.py"}])
    assert '  - "a/b\\"c.py"' in check._rule_text(seam, [c["path"] for c in seam["copies"]])


def test_ignored_rules_folder_warns_and_the_check_skips_it(repo, capsys):
    if not shutil.which("git"):
        pytest.skip("needs git")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text(".claude/\n")
    registry(repo, "rules", HIGH)
    code, out = notes(repo, capsys)
    assert code == 0 and "ignored by git" in out
    shutil.rmtree(repo / ".claude")  # a CI clone does not have ignored files
    assert plain(repo, capsys)[0] == 0


# --- claude-md mode ----------------------------------------------------------------

def test_claude_md_mode_uses_the_nearest_claude_md_and_skips_low_risk(repo, capsys):
    (repo / "api/CLAUDE.md").write_text("# API notes\n\nHand-written text.\n")
    registry(repo, "claude-md", HIGH, LOW)
    assert notes(repo, capsys)[0] == 0
    api = (repo / "api/CLAUDE.md").read_text()
    assert api.startswith("# API notes\n\nHand-written text.\n\n" + check.BLOCK_START)
    assert "**order-statuses** (high)" in api and "Here: `api/status.py`" in api
    assert "Elsewhere: `web/src/status.ts`" in api
    assert "log-format" not in api
    root = (repo / "CLAUDE.md").read_text()  # web has no CLAUDE.md, so its copy goes to the root one
    assert "**order-statuses**" in root and "Here: `web/src/status.ts`" in root


def test_claude_md_block_is_replaced_in_place(repo, capsys):
    (repo / "CLAUDE.md").write_text("top\n\n" + check.BLOCK_START + "\nSTALE-BLOCK-TEXT\n" + check.BLOCK_END + "\n\nbottom\n")
    registry(repo, "claude-md", HIGH)
    notes(repo, capsys)
    text = (repo / "CLAUDE.md").read_text()
    assert text.startswith("top\n\n" + check.BLOCK_START) and text.endswith(check.BLOCK_END + "\n\nbottom\n")
    assert "STALE-BLOCK-TEXT" not in text


@pytest.mark.parametrize("damaged", [
    "a\n" + check.BLOCK_START + "\nb\n",                                       # no end
    "a\n" + check.BLOCK_END + "\nb\n" + check.BLOCK_START + "\n",                # wrong order
    check.BLOCK_START + "\n" + check.BLOCK_START + "\n" + check.BLOCK_END + "\n",  # two starts
])
def test_damaged_markers_are_refused_and_the_file_is_untouched(repo, capsys, damaged):
    (repo / "CLAUDE.md").write_text(damaged)
    registry(repo, "claude-md", HIGH)
    code, out = notes(repo, capsys)
    assert code == 1 and "markers" in out
    assert (repo / "CLAUDE.md").read_text() == damaged


def test_a_block_with_no_seams_left_is_removed_and_the_text_around_it_kept(repo, capsys):
    (repo / "CLAUDE.md").write_text("top\n")
    registry(repo, "claude-md", HIGH)
    notes(repo, capsys)
    registry(repo, "claude-md", LOW)  # low risk: no CLAUDE.md entry
    notes(repo, capsys)
    assert (repo / "CLAUDE.md").read_text() == "top\n"


def test_removing_a_block_keeps_the_text_on_both_sides(repo, capsys):
    (repo / "CLAUDE.md").write_text("top\n\n" + check.BLOCK_START + "\nx\n" + check.BLOCK_END + "\n\nbottom\n")
    registry(repo, "claude-md", LOW)
    notes(repo, capsys)
    assert (repo / "CLAUDE.md").read_text() == "top\n\nbottom\n"


def test_bracket_folder_gets_its_own_claude_md(repo, capsys):
    (repo / "web/app/[id]").mkdir(parents=True)
    (repo / "web/app/[id]/page.tsx").write_text("x\n")
    (repo / "web/app/[id]/CLAUDE.md").write_text("route\n")
    registry(repo, "claude-md", dict(HIGH, copies=[{"path": "api/status.py"}, {"path": "web/app/[id]/page.tsx"}]))
    notes(repo, capsys)
    assert "`web/app/[id]/page.tsx`" in (repo / "web/app/[id]/CLAUDE.md").read_text()


def test_glob_copy_goes_to_the_claude_md_above_its_wildcard(repo, capsys):
    (repo / "web/CLAUDE.md").write_text("web\n")
    registry(repo, "claude-md", dict(LOW, risk="medium"))
    notes(repo, capsys)
    assert "`web/src/*.ts`" in (repo / "web/CLAUDE.md").read_text()


# --- switching and setup -------------------------------------------------------------

def test_switching_modes_cleans_up_the_old_notes(repo, capsys):
    (repo / "CLAUDE.md").write_text("top\n")
    registry(repo, "claude-md", HIGH)
    notes(repo, capsys)
    registry(repo, "rules", HIGH)
    notes(repo, capsys)
    assert (repo / "CLAUDE.md").read_text() == "top\n"
    assert (repo / ".claude/rules/seams/order-statuses.md").exists()


def test_notes_without_a_setting_explain_what_to_add(repo, capsys):
    registry(repo, None, HIGH)
    code, out = notes(repo, capsys)
    assert code == 2 and '"notes": "claude-md"' in out


def test_notes_refuse_a_registry_that_fails_the_check(repo, capsys):
    registry(repo, "rules", dict(HIGH, copies=[{"path": "api/status.py"}, {"path": "gone.py"}]))
    code, _ = notes(repo, capsys)
    assert code == 1 and not (repo / ".claude").exists()


def test_cli_notes_runs_the_checker(repo, capsys):
    registry(repo, "rules", HIGH)
    assert cli.main(["notes", "--root", str(repo)]) == 0
    assert (repo / ".claude/rules/seams/order-statuses.md").exists()


def test_the_copied_checker_writes_notes_alone(repo):
    registry(repo, "rules", HIGH)
    cli.main(["init", "--root", str(repo)])
    r = subprocess.run(["python3", "-I", cli.DEFAULT_CHECKER, "--notes"], cwd=repo,
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / ".claude/rules/seams/order-statuses.md").exists()


# --- other agents: Cursor, Copilot, AGENTS.md ------------------------------------------

def test_cursor_mode_writes_an_auto_attached_rule_per_seam(repo, capsys):
    registry(repo, "cursor", HIGH, LOW)
    assert notes(repo, capsys)[0] == 0
    text = (repo / ".cursor/rules/seams/order-statuses.mdc").read_text()
    # Cursor attaches a rule with globs and alwaysApply false when a matching file is in context.
    assert text.startswith('---\ndescription: "Seam order-statuses: Order status names"\n'
                           "globs: api/status.py,web/src/status.ts\nalwaysApply: false\n---\n")
    assert check.GENERATED in text
    assert (repo / ".cursor/rules/seams/log-format.mdc").exists()  # every risk, like rules


def test_copilot_mode_writes_a_path_specific_instruction_per_seam(repo, capsys):
    registry(repo, "copilot", HIGH)
    assert notes(repo, capsys)[0] == 0
    text = (repo / ".github/instructions/seams-order-statuses.instructions.md").read_text()
    assert text.startswith('---\napplyTo: "api/status.py,web/src/status.ts"\n---\n')


def test_copilot_cleanup_leaves_hand_written_instructions_alone(repo, capsys):
    mine = repo / ".github/instructions/seams-style.instructions.md"
    mine.parent.mkdir(parents=True)
    mine.write_text('---\napplyTo: "**"\n---\nDana wrote this.\n')
    registry(repo, "copilot", HIGH)
    notes(repo, capsys)
    registry(repo, "copilot", LOW)
    notes(repo, capsys)
    assert not (repo / ".github/instructions/seams-order-statuses.instructions.md").exists()
    assert mine.read_text().endswith("Dana wrote this.\n")


def test_a_path_with_a_comma_is_left_out_with_a_warning(repo, capsys):
    (repo / "api/a,b.py").write_text("x\n")
    registry(repo, ["rules", "cursor"], dict(HIGH, copies=[{"path": "api/a,b.py"}, {"path": "api/status.py"}]))
    code, out = notes(repo, capsys)
    assert code == 0 and "cannot name a path with a comma" in out
    assert "globs: api/status.py\n" in (repo / ".cursor/rules/seams/order-statuses.mdc").read_text()
    assert '"api/a,b.py"' in (repo / ".claude/rules/seams/order-statuses.md").read_text()  # rules take a list


def test_agents_md_mode_writes_blocks_like_claude_md(repo, capsys):
    (repo / "api/AGENTS.md").write_text("# API\n")
    registry(repo, "agents-md", HIGH, LOW)
    assert notes(repo, capsys)[0] == 0
    api = (repo / "api/AGENTS.md").read_text()
    assert api.startswith("# API\n\n" + check.BLOCK_START) and "order-statuses" in api
    assert "log-format" not in api  # low risk stays in the registry only
    assert "`web/src/status.ts`" in (repo / "AGENTS.md").read_text()  # no nearer AGENTS.md: the root
    assert not (repo / "CLAUDE.md").exists()


def test_a_list_writes_every_mode_and_dropping_one_removes_its_notes(repo, capsys):
    (repo / "CLAUDE.md").write_text("top\n")
    registry(repo, ["rules", "cursor", "copilot", "agents-md"], HIGH)
    assert notes(repo, capsys)[0] == 0
    for f in [".claude/rules/seams/order-statuses.md", ".cursor/rules/seams/order-statuses.mdc",
              ".github/instructions/seams-order-statuses.instructions.md", "AGENTS.md"]:
        assert (repo / f).exists(), f
    assert plain(repo, capsys)[0] == 0
    registry(repo, ["rules"], HIGH)
    assert plain(repo, capsys)[0] == 1  # the other notes are now stale
    notes(repo, capsys)
    assert not (repo / ".cursor/rules/seams/order-statuses.mdc").exists()
    assert not (repo / ".github/instructions/seams-order-statuses.instructions.md").exists()
    assert check.BLOCK_START not in (repo / "AGENTS.md").read_text()
    assert (repo / "CLAUDE.md").read_text() == "top\n"
    assert plain(repo, capsys)[0] == 0


def test_two_blocks_for_one_file_are_refused(repo, capsys):
    registry(repo, ["claude-md", "claude-md-high"], HIGH)
    code, out = plain(repo, capsys)
    assert code == 1 and "claude-md and claude-md-high both write the block in CLAUDE.md" in out


def test_an_unknown_mode_in_a_list_names_the_item(repo, capsys):
    registry(repo, ["rules", "windsurf"], HIGH)
    code, out = plain(repo, capsys)
    assert code == 1 and "seams.json.notes[1]: must be one of" in out


def test_a_claude_md_link_to_agents_md_is_left_alone(repo, capsys):
    (repo / "AGENTS.md").write_text("# Shared\n")
    (repo / "CLAUDE.md").symlink_to("AGENTS.md")
    registry(repo, "agents-md", HIGH)
    code, out = notes(repo, capsys)
    assert code == 0, out
    assert check.BLOCK_START in (repo / "AGENTS.md").read_text()
    assert (repo / "CLAUDE.md").is_symlink()
    assert plain(repo, capsys)[0] == 0


def test_the_copied_checker_writes_every_mode_alone(repo):
    registry(repo, ["rules", "cursor", "copilot", "agents-md"], HIGH)
    cli.main(["init", "--root", str(repo)])
    r = subprocess.run(["python3", "-I", cli.DEFAULT_CHECKER, "--notes"], cwd=repo,
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / ".cursor/rules/seams/order-statuses.mdc").exists()


def test_a_note_and_a_lookup_say_when_the_copies_already_differ(repo, capsys):
    drifted = dict(HIGH, drift={"text": "web lacks 'returned'.", "source": "confirmed", "seen": "2026-11-15"})
    registry(repo, "rules", drifted)
    notes(repo, capsys)
    line = "known drift (confirmed, 2026-11-15): web lacks 'returned'."
    assert line in (repo / ".claude/rules/seams/order-statuses.md").read_text()
    check.main(["--root", str(repo), "--about", "status"])
    assert line in capsys.readouterr().out


def test_a_note_never_written_is_missing_not_out_of_date(repo, capsys):
    registry(repo, "rules", HIGH)
    code, out = plain(repo, capsys)
    assert code == 1 and "the note is missing" in out and "out of date" not in out


def test_notes_report_their_word_count(repo, capsys):
    registry(repo, ["rules", "agents-md"], HIGH)
    _, out = notes(repo, capsys)
    words = len((repo / ".claude/rules/seams/order-statuses.md").read_text().split())
    block = (repo / "AGENTS.md").read_text()
    words += len(block[block.index(check.BLOCK_START):block.index(check.BLOCK_END)].split())
    assert f"the notes hold {words} words in all" in out


def test_the_ignore_lines_share_rules_and_the_hook_file_and_nothing_else(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("\n".join(check.RULES_IGNORE_LINES) + "\n")
    def ignored(p):
        return subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "-q", p]).returncode == 0
    assert not ignored(".claude/rules/seams/x.md") and not ignored(".claude/settings.json")
    assert ignored(".claude/settings.local.json") and ignored("sub/.claude/settings.json")
