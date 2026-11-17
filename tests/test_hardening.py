"""Inputs real repos produce. Each test reproduces a defect an independent review or a
blind run found, so removing its fix fails the test."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from seams import check

CHECKER = Path(check.__file__)
SEAM = {"id": "x", "title": "T", "kind": "config", "must_agree": "Both match.", "consequence": "c",
        "risk": "high", "copies": [{"path": "a.py"}, {"path": "b.py"}]}
needs_git = pytest.mark.skipif(not shutil.which("git"), reason="needs git")
needs_links = pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")


def write(root, rel, text="x\n", mode="w"):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        f.write_bytes(text)
    else:
        f.write_text(text)
    return f


def registry(root, *seams, notes=None):
    data = {"schema_version": 1, "seams": list(seams) or [SEAM]}
    if notes:
        data["notes"] = notes
    write(root, "seams.json", json.dumps(data))


def run(root, *argv):
    r = subprocess.run([sys.executable, "-I", str(CHECKER), "--root", str(root), *argv],
                       capture_output=True, text=True, timeout=20)
    return r.returncode, r.stdout + r.stderr


def git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    write(r, "a.py")
    write(r, "b.py")
    return r


# --- line endings and encodings -------------------------------------------------------

@pytest.mark.parametrize("mode", ["rules", "claude-md"])
def test_crlf_checkout_of_the_notes_still_passes(repo, mode):
    # git with eol=crlf or autocrlf turns the notes into CRLF on checkout.
    write(repo, "CLAUDE.md", "top\n")
    registry(repo, notes=mode)
    assert run(repo, "--notes")[0] == 0
    for f in list(repo.rglob("*.md")):
        f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    code, out = run(repo)
    assert code == 0, out


def test_notes_keep_a_crlf_files_line_endings(repo):
    write(repo, "CLAUDE.md", b"top\r\nline two\r\n")
    registry(repo, notes="claude-md")
    run(repo, "--notes")
    raw = (repo / "CLAUDE.md").read_bytes()
    assert raw.startswith(b"top\r\nline two\r\n\r\n") and b"\n" not in raw.replace(b"\r\n", b"")


def test_a_claude_md_that_is_not_utf8_is_left_alone(repo):
    before = b"Caf\xe9 notes\n"
    write(repo, "CLAUDE.md", before)
    registry(repo, notes="claude-md")
    code, out = run(repo, "--notes")
    assert code == 1 and "not UTF-8" in out
    assert (repo / "CLAUDE.md").read_bytes() == before


def test_registry_with_a_byte_order_mark_loads(repo):
    registry(repo)
    f = repo / "seams.json"
    f.write_bytes(b"\xef\xbb\xbf" + f.read_bytes())
    assert run(repo)[0] == 0


def test_registry_that_is_not_utf8_exits_2(repo):
    write(repo, "seams.json", b'{"schema_version": 1, "seams": [], "x": "\xe9"}')
    code, out = run(repo)
    assert code == 2 and "not UTF-8" in out


def test_an_id_with_a_trailing_newline_is_refused(repo):
    registry(repo, dict(SEAM, id="x\n"))
    code, out = run(repo)
    assert code == 1 and "does not match" in out


# --- hand-written files and links -------------------------------------------------------

def test_a_hand_written_rule_with_a_seams_id_is_never_overwritten(repo):
    mine = write(repo, ".claude/rules/seams/x.md", '---\npaths:\n  - "a.py"\n---\nDana wrote this.\n')
    registry(repo, notes="rules")
    code, out = run(repo, "--notes")
    assert code == 1 and "was not written by seams" in out
    assert "Dana wrote this." in mine.read_text()


@needs_links
def test_notes_never_write_through_a_linked_claude_md(repo, tmp_path):
    victim = write(tmp_path, "outside/victim.md", "precious\n")
    os.symlink(victim, repo / "CLAUDE.md")
    registry(repo, notes="claude-md")
    code, out = run(repo, "--notes")
    assert code == 1 and "link" in out
    assert victim.read_text() == "precious\n"


@needs_links
def test_notes_never_write_into_a_linked_rules_folder(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".claude/rules").mkdir(parents=True)
    os.symlink(outside, repo / ".claude/rules/seams")
    registry(repo, notes="rules")
    code, out = run(repo, "--notes")
    assert code == 1 and "link" in out
    assert list(outside.iterdir()) == []


@needs_links
def test_a_copy_that_links_outside_the_repo_is_refused(repo, tmp_path):
    write(tmp_path, "secret.py", "TOKEN\n")
    (repo / "b.py").unlink()
    os.symlink(tmp_path / "secret.py", repo / "b.py")
    registry(repo)
    code, out = run(repo)
    assert code == 1 and "outside the repo" in out


@needs_links
def test_a_glob_never_matches_a_link_that_leads_outside_the_repo(repo, tmp_path):
    write(tmp_path, "secret.py", "TOKEN\n")
    (repo / "lib").mkdir()
    os.symlink(tmp_path / "secret.py", repo / "lib/secret.py")
    registry(repo, dict(SEAM, copies=[{"path": "a.py"}, {"path": "lib/*.py"}]))
    code, out = run(repo)
    assert code == 1 and "matches no file" in out


@needs_links
def test_a_glob_sees_files_under_a_folder_link_inside_the_repo(repo):
    write(repo, "real/c.py")
    os.symlink(repo / "real", repo / "lib")
    registry(repo, dict(SEAM, copies=[{"path": "a.py"}, {"path": "lib/*.py"}]))
    assert run(repo)[0] == 0


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs mkfifo")
def test_a_fifo_matched_by_a_glob_does_not_hang(repo):
    (repo / "run").mkdir()
    write(repo, "run/a.cfg", "KEY\n")
    os.mkfifo(repo / "run/b.cfg")
    registry(repo, dict(SEAM, copies=[{"path": "a.py"}, {"path": "run/*.cfg", "symbol": "KEY"}]))
    code, out = run(repo)  # the helper's 20 s timeout fails the test on a hang
    assert code == 0, out


# --- paths -------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["./a.py", "x//a.py", "a.py/", "a\n.py"])
def test_a_path_not_in_plain_form_is_refused(repo, path):
    registry(repo, dict(SEAM, copies=[{"path": path}, {"path": "b.py"}]))
    code, out = run(repo)
    assert code == 1 and ("plain form" in out or "control character" in out)


def test_a_deleted_bracket_path_does_not_fall_back_to_a_glob(repo):
    write(repo, "app/d/page.tsx")  # [id] as a glob class would match the d folder
    registry(repo, dict(SEAM, copies=[{"path": "a.py"}, {"path": "app/[id]/page.tsx"}]))
    code, out = run(repo)
    assert code == 1 and "does not exist" in out
    assert not check.copy_matches("app/[id]/page.tsx", "app/d/page.tsx")


def test_a_folder_copy_says_how_to_glob_it(repo):
    (repo / "dash").mkdir()
    registry(repo, dict(SEAM, copies=[{"path": "a.py"}, {"path": "dash"}]))
    assert "dash/**/*" in run(repo)[1]


def test_a_class_dot_method_tie_counts_when_the_method_is_in_the_file(repo):
    write(repo, "tests/test_x.py", "class TestX:\n    def test_same(self):\n        pass\n")
    registry(repo, dict(SEAM, ties=[{"path": "tests/test_x.py", "test": "TestX.test_same", "covers": "all"}]))
    assert run(repo)[0] == 0


# --- git listings ------------------------------------------------------------------------

@needs_git
def test_staged_and_diff_work_when_the_seams_root_is_a_subfolder(tmp_path):
    top = tmp_path / "mono"
    pkg = top / "pkg"
    write(pkg, "a.py")
    write(pkg, "b.py")
    registry(pkg)
    git(top, "init", "-q", "-b", "main")
    git(top, "add", "-A")
    git(top, "commit", "-qm", "base")
    git(top, "checkout", "-qb", "feature")
    write(pkg, "a.py", "y\n")
    git(top, "add", "pkg/a.py")
    code, out = run(pkg, "--staged", "--fail-untied")
    assert code == 1 and "not changed: b.py" in out
    code, out = run(pkg, "--diff", "main", "--fail-untied")
    assert code == 1 and "not changed: b.py" in out


@needs_git
def test_a_non_ascii_file_name_is_seen_by_staged(repo):
    write(repo, "café.py")
    registry(repo, dict(SEAM, copies=[{"path": "café.py"}, {"path": "b.py"}]))
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    write(repo, "café.py", "y\n")
    git(repo, "add", "-A")
    code, out = run(repo, "--staged")
    assert "seam 'x'" in out, out


@needs_git
def test_a_note_only_change_to_a_claude_md_copy_is_not_a_change(repo):
    # docs/CLAUDE.md is itself a copy. Refreshing its notes must not trip --fail-untied.
    write(repo, "docs/CLAUDE.md", "Use STATUSES.\n")
    seam = dict(SEAM, copies=[{"path": "a.py"}, {"path": "docs/CLAUDE.md"}])
    registry(repo, seam, notes="claude-md")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "feature")
    assert run(repo, "--notes")[0] == 0
    git(repo, "add", "-A")
    assert run(repo, "--staged", "--fail-untied")[0] == 0
    assert run(repo, "--diff", "main", "--fail-untied")[0] == 0
    write(repo, "docs/CLAUDE.md", "Use STATUSES and NEW.\n" + (repo / "docs/CLAUDE.md").read_text().split("\n", 1)[1])
    git(repo, "add", "-A")
    code, out = run(repo, "--staged", "--fail-untied")
    assert code == 1 and "not changed: a.py" in out  # a real edit outside the block still counts


# --- notes size ---------------------------------------------------------------------------

def test_claude_md_lists_each_seam_once_with_its_local_copies(repo):
    write(repo, "c.py")
    registry(repo, dict(SEAM, copies=[{"path": "a.py"}, {"path": "b.py"}, {"path": "c.py"}]), notes="claude-md")
    run(repo, "--notes")
    block = (repo / "CLAUDE.md").read_text()
    assert block.count("**x**") == 1 and "Here: `a.py`, `b.py`, `c.py`" in block


def test_claude_md_high_leaves_out_medium_risk(repo):
    medium = dict(SEAM, id="m", risk="medium")
    registry(repo, SEAM, medium, notes="claude-md-high")
    run(repo, "--notes")
    block = (repo / "CLAUDE.md").read_text()
    assert "**x**" in block and "**m**" not in block
