"""The lookup: which seams a change touches, and which copies it leaves alone."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from seams import check, cli

CHECKER = Path(check.__file__)

TIED = {
    "id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
    "must_agree": "Both lists hold the same names.",
    "copies": [{"path": "api/status.py"}, {"path": "web/status.ts"}],
    "consequence": "The web app shows a status the API never sends.", "risk": "high",
    "ties": [{"path": "tests/test_parity.py", "covers": "all"}],
}
UNTIED = {
    "id": "queue-url", "title": "Queue env var", "kind": "config",
    "must_agree": "Code and compose use the same name.",
    "copies": [{"path": "api/settings.py"}, {"path": "deploy/*.yml"}],
    "consequence": "The worker starts with no queue.", "risk": "medium",
    "intentional_differences": "compose sets a default; code does not",
}


@pytest.fixture
def repo(tmp_path):
    for f in ["api/status.py", "web/status.ts", "tests/test_parity.py", "api/settings.py",
              "deploy/compose.yml", "README.md"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x\n")
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [TIED, UNTIED]}))
    return tmp_path


def run(repo, capsys, *argv):
    code = check.main(["--root", str(repo), *argv])
    out = capsys.readouterr()
    return code, out.out + out.err


# --- matching ----------------------------------------------------------------

def test_copy_matches_paths_and_globs():
    assert check.copy_matches("api/status.py", "api/status.py")
    assert not check.copy_matches("api/status.py", "api/status.pyc")
    assert check.copy_matches("deploy/*.yml", "deploy/compose.yml")
    assert not check.copy_matches("deploy/*.yml", "deploy/x/compose.yml")
    assert check.copy_matches("deploy/**/*.yml", "deploy/x/compose.yml")


def test_copy_matches_a_literal_bracket_path():
    assert check.copy_matches("web/app/[id]/page.tsx", "web/app/[id]/page.tsx")


def test_lookup_reports_changed_and_unchanged_copies():
    data = {"schema_version": 1, "seams": [TIED, UNTIED]}
    [(seam, hit, rest)] = check.lookup(data, ["web/status.ts"])
    assert seam["id"] == "order-statuses" and hit == ["web/status.ts"] and rest == ["api/status.py"]


def test_lookup_matches_a_deleted_file_by_name(tmp_path):
    # Matching is on text alone: a copy deleted in this change still counts.
    data = {"schema_version": 1, "seams": [TIED]}
    assert check.lookup(data, ["api/status.py"])


@pytest.mark.parametrize("given, expected", [
    ("api/status.py", "api/status.py"), ("./api/status.py", "api/status.py"),
    ("api\\status.py", "api/status.py"), ("../elsewhere.py", None),
])
def test_relative(repo, given, expected):
    assert check.relative(given, repo) == expected


def test_relative_turns_an_absolute_path_inside_the_repo_relative(repo):
    assert check.relative(str(repo / "api/status.py"), repo) == "api/status.py"
    assert check.relative("/etc/passwd", repo) is None


# --- --changed ----------------------------------------------------------------

def test_changing_one_copy_names_the_others(repo, capsys):
    code, out = run(repo, capsys, "--changed", "api/status.py")
    assert code == 0
    assert "seam 'order-statuses'" in out and "not changed: web/status.ts" in out
    assert "tie: tests/test_parity.py, covers all" in out


def test_changing_every_copy_is_quiet(repo, capsys):
    code, out = run(repo, capsys, "--changed", "api/status.py", "web/status.ts")
    assert code == 0 and "No seam has a copy left behind" in out


def test_unrelated_change_is_quiet(repo, capsys):
    code, out = run(repo, capsys, "--changed", "README.md")
    assert code == 0 and "No seam has a copy left behind" in out


def test_untied_seam_says_so_and_shows_deliberate_differences(repo, capsys):
    code, out = run(repo, capsys, "--changed", "deploy/compose.yml")
    assert "no full tie" in out
    assert "deliberate differences: compose sets a default" in out


def test_fail_untied_fails_only_for_untied_seams(repo, capsys):
    assert run(repo, capsys, "--changed", "api/status.py", "--fail-untied")[0] == 0
    assert run(repo, capsys, "--changed", "api/settings.py", "--fail-untied")[0] == 1
    assert run(repo, capsys, "--changed", "api/settings.py")[0] == 0  # warn only by default


def test_partial_tie_is_not_a_full_tie(repo, capsys):
    seam = dict(UNTIED, ties=[{"path": "tests/test_parity.py", "covers": "partial", "note": "api only"}])
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [seam]}))
    assert run(repo, capsys, "--changed", "api/settings.py", "--fail-untied")[0] == 1


def test_lookup_refuses_an_invalid_registry(repo, capsys):
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [{"id": "x"}]}))
    code, out = run(repo, capsys, "--changed", "api/status.py")
    assert code == 2 and "does not match the schema" in out


# --- --diff and --staged --------------------------------------------------------

def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   check=True, capture_output=True)


@pytest.fixture
def git_repo(repo):
    if not shutil.which("git"):
        pytest.skip("needs git")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "feature")
    return repo


def test_diff_sees_committed_and_uncommitted_changes(git_repo, capsys):
    (git_repo / "api/status.py").write_text("y\n")
    git(git_repo, "commit", "-qam", "change one copy")
    (git_repo / "api/settings.py").write_text("y\n")  # not committed
    code, out = run(git_repo, capsys, "--diff", "main")
    assert "seam 'order-statuses'" in out and "seam 'queue-url'" in out


def test_diff_with_an_unknown_ref_exits_2(git_repo, capsys):
    code, out = run(git_repo, capsys, "--diff", "no-such-branch")
    assert code == 2 and "cannot list the changes" in out


def test_staged_reads_the_index_not_the_working_tree(git_repo, capsys):
    (git_repo / "api/status.py").write_text("y\n")
    (git_repo / "api/settings.py").write_text("y\n")
    git(git_repo, "add", "api/status.py")
    code, out = run(git_repo, capsys, "--staged")
    assert "seam 'order-statuses'" in out and "queue-url" not in out


# --- --hook -----------------------------------------------------------------------

def hook(repo, monkeypatch, capsys, payload, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO(payload if isinstance(payload, str) else json.dumps(payload)))
    code = check.main(["--hook", *argv])
    return code, capsys.readouterr().out


def test_hook_adds_context_before_an_edit_to_a_copy(repo, monkeypatch, capsys):
    code, out = hook(repo, monkeypatch, capsys,
                     {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "web/status.ts")}})
    assert code == 0
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PreToolUse"
    assert "other copies: api/status.py" in ctx["additionalContext"]


def test_hook_finds_the_registry_above_the_edited_file(repo, monkeypatch, capsys, tmp_path):
    # No --root: the hook walks up from the file to the nearest seams.json.
    monkeypatch.chdir(tmp_path.parent)
    _, out = hook(repo, monkeypatch, capsys, {"tool_input": {"file_path": str(repo / "api/status.py")}})
    assert "order-statuses" in out


def test_hook_resolves_a_relative_path_against_cwd(repo, monkeypatch, capsys):
    _, out = hook(repo, monkeypatch, capsys, {"cwd": str(repo), "tool_input": {"file_path": "api/status.py"}})
    assert "order-statuses" in out


@pytest.mark.parametrize("payload", [
    "not json", {}, {"tool_input": {}}, {"tool_input": {"file_path": "/nowhere/x.py"}},
])
def test_hook_stays_silent_and_exits_0_on_anything_odd(repo, monkeypatch, capsys, payload):
    assert hook(repo, monkeypatch, capsys, payload) == (0, "")


def test_hook_stays_silent_for_a_file_that_is_no_copy(repo, monkeypatch, capsys):
    assert hook(repo, monkeypatch, capsys, {"tool_input": {"file_path": str(repo / "README.md")}}) == (0, "")


def test_hook_stays_silent_on_a_broken_registry(repo, monkeypatch, capsys):
    (repo / "seams.json").write_text("{broken")
    payload = {"tool_input": {"file_path": str(repo / "api/status.py")}}
    assert hook(repo, monkeypatch, capsys, payload) == (0, "")


def test_hook_runs_from_the_copied_checker_alone(repo):
    # The real hook command: the copy, no package on the path, payload on stdin.
    cli.main(["init", "--root", str(repo)])
    payload = json.dumps({"tool_input": {"file_path": str(repo / "api/status.py")}})
    r = subprocess.run(["python3", "-I", str(repo / cli.DEFAULT_CHECKER), "--hook"],
                       input=payload, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0 and "order-statuses" in r.stdout


def _hook_command():
    return json.loads(cli.snippet("claude-code-settings.json"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_the_hook_snippet_runs_the_checker_in_a_repo_that_has_it(repo):
    cli.main(["init", "--root", str(repo)])
    payload = json.dumps({"tool_input": {"file_path": str(repo / "api/status.py")}})
    r = subprocess.run(["sh", "-c", _hook_command()], input=payload, capture_output=True, text=True,
                       timeout=10, env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})
    assert r.returncode == 0 and "order-statuses" in r.stdout


def test_the_hook_snippet_never_blocks_a_repo_without_the_checker(tmp_path):
    # Exit 2 from a PreToolUse hook blocks the edit. python3 on a missing file exits 2.
    r = subprocess.run(["sh", "-c", _hook_command()], input="{}", capture_output=True, text=True,
                       timeout=10, env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert r.returncode == 0 and r.stdout == ""


def test_cli_check_passes_lookup_options_through(repo, capsys):
    assert cli.main(["check", "--root", str(repo), "--changed", "api/settings.py", "--fail-untied"]) == 1
    assert "queue-url" in capsys.readouterr().out


# --- --about ------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["STATUS", "web/status.ts", "queue env", "order-statuses"])
def test_about_finds_seams_by_title_path_or_id(repo, capsys, text):
    code, out = run(repo, capsys, "--about", text)
    assert code == 0 and "seam '" in out and "copies:" in out


def test_about_lists_every_copy(repo, capsys):
    _, out = run(repo, capsys, "--about", "order status")
    assert "copies: api/status.py, web/status.ts" in out


def test_about_with_no_match_says_the_list_may_be_incomplete(repo, capsys):
    code, out = run(repo, capsys, "--about", "billing")
    assert code == 0 and "0 seam(s)" in out and "will not show up" in out


def test_about_refuses_an_invalid_registry(repo, capsys):
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [{"id": "x"}]}))
    assert run(repo, capsys, "--about", "x")[0] == 2
