"""The hook on Bash commands, and the Stop hook. An agent that edits with sed never calls Edit."""
from __future__ import annotations

import io
import json
import shutil
import subprocess

import pytest

from seams import check, cli

SEAM = {"id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
        "must_agree": "Both lists hold the same names.",
        "copies": [{"path": "api/status.py"}, {"path": "web/status.ts"}],
        "consequence": "The web app drops a status.", "risk": "high"}


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("needs git")
    for f in ("api/status.py", "web/status.ts", "README.md", "web/app/[id]/page.tsx"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x\n")
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [SEAM]}))
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def bash(repo, command, cwd=None):
    return check.run_hook(json.dumps({"tool_name": "Bash", "cwd": str(cwd or repo),
                                      "tool_input": {"command": command}}))


# --- the hook on Bash ---------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "sed -i 's/new/new lost/' api/status.py",
    "cat api/status.py | head",
    "python3 - <<'EOF'\nopen('api/status.py','a').write('x')\nEOF",
    "printf 'x' > ./api/status.py",
])
def test_a_command_that_names_a_copy_gets_the_other_copies(repo, command):
    out = bash(repo, command)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "This command reads or changes a copy of a seam" in ctx and "other copies: web/status.ts" in ctx


def test_a_command_from_a_subfolder_and_an_absolute_path(repo):
    assert bash(repo, "cat status.ts", cwd=repo / "web")
    assert bash(repo, f"cat {repo / 'web/status.ts'}", cwd=repo.parent) is None  # no registry above that cwd
    assert check.run_hook(json.dumps({"tool_name": "Bash", "cwd": str(repo.parent),
                                      "tool_input": {"command": f"cat {repo / 'web/status.ts'}"}}), root=repo)


@pytest.mark.parametrize("command", ["ls api", "git status", "cat README.md", "grep -r status .", "cat nope/status.py", ""])
def test_a_command_that_names_no_copy_is_quiet(repo, command):
    assert bash(repo, command) is None


def test_bash_paths_reads_bracket_folders_and_flag_values(repo):
    # A path given as a flag's value (--file=path) is still a file the command reads.
    assert check.bash_paths("cat 'web/app/[id]/page.tsx' -n --x=api/status.py", repo, repo) == \
        ["web/app/[id]/page.tsx", "api/status.py"]


def test_the_edit_hook_still_works(repo):
    out = check.run_hook(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(repo / "web/status.ts")}}))
    assert "other copies: api/status.py" in out["hookSpecificOutput"]["additionalContext"]


# --- the Stop hook ----------------------------------------------------------------------

def stop(repo, active=False):
    return check.run_stop_hook(json.dumps({"hook_event_name": "Stop", "cwd": str(repo), "stop_hook_active": active}))


def test_stop_blocks_once_when_a_copy_is_left_behind(repo):
    (repo / "api/status.py").write_text("y\n")
    out = stop(repo)
    assert out["decision"] == "block"
    assert "not changed: web/status.ts" in out["reason"] and "say which and why" in out["reason"]
    assert "add that seam to seams.json now" in out["reason"]
    assert stop(repo, active=True) is None  # the second stop goes through: no loop


def test_stop_is_quiet_when_nothing_changed_or_only_the_registry_did(repo):
    assert stop(repo) is None
    data = json.loads((repo / "seams.json").read_text())
    data["seams"][0]["title"] = "renamed"
    (repo / "seams.json").write_text(json.dumps(data))
    assert stop(repo) is None


def test_stop_reminds_once_to_record_copies_when_every_listed_copy_changed(repo):
    # No copy left behind, but the change may have met an unlisted copy: one reminder, no seam list.
    (repo / "api/status.py").write_text("y\n")
    (repo / "web/status.ts").write_text("y\n")
    out = stop(repo)
    assert out["decision"] == "block" and "not changed" not in out["reason"]
    assert "add that seam to seams.json now" in out["reason"] and "whether you updated the other copy or left it" in out["reason"]
    assert stop(repo, active=True) is None


def test_stop_sees_committed_work_on_a_branch(repo):
    # An agent that commits before it stops (a pull request) leaves a clean tree.
    git(repo, "branch", "-M", "main")
    git(repo, "checkout", "-qb", "feature")
    (repo / "api/status.py").write_text("y\n")
    git(repo, "commit", "-qam", "change one copy")
    out = stop(repo)
    assert "not changed: web/status.ts" in out["reason"]
    assert "seams scan --since main --new" in out["reason"]


def test_stop_on_the_default_branch_ignores_old_commits(repo):
    git(repo, "branch", "-M", "main")
    (repo / "api/status.py").write_text("y\n")
    git(repo, "commit", "-qam", "an old commit on main")
    assert stop(repo) is None


def test_stop_counts_untracked_files(repo):
    data = json.loads((repo / "seams.json").read_text())
    data["seams"][0]["copies"].append({"path": "web/*.ts"})
    (repo / "seams.json").write_text(json.dumps(data))
    git(repo, "commit", "-qam", "glob copy")
    (repo / "web/new.ts").write_text("x\n")
    assert stop(repo)["decision"] == "block"


@pytest.mark.parametrize("payload", ["not json", "[]", json.dumps({"cwd": "/nowhere"})])
def test_stop_never_raises(payload, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no registry here or above
    assert check.run_stop_hook(payload) is None


def test_stop_hook_flag_prints_the_block(repo, monkeypatch, capsys):
    (repo / "api/status.py").write_text("y\n")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo)})))
    assert check.main(["--stop-hook"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


def test_the_settings_snippet_wires_both_hooks():
    cfg = json.loads((cli.SNIPPETS / "claude-code-settings.json").read_text())
    pre = cfg["hooks"]["PreToolUse"][0]
    assert "Bash" in pre["matcher"].split("|") and "Edit" in pre["matcher"].split("|")
    assert "--stop-hook" in cfg["hooks"]["Stop"][0]["hooks"][0]["command"]


def test_stop_never_puts_an_odd_ref_name_in_a_command(repo):
    git(repo, "branch", "-M", "main")
    git(repo, "update-ref", "refs/remotes/origin/x$(touch_pwned)", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/x$(touch_pwned)")
    git(repo, "checkout", "-qb", "feature")
    (repo / "api/status.py").write_text("y\n")
    git(repo, "commit", "-qam", "change")
    out = stop(repo)
    assert "pwned" not in out["reason"] and "seams scan --since <base branch> --new" in out["reason"]


def test_stop_speaks_up_when_an_edit_broke_the_registry(repo):
    data = json.loads((repo / "seams.json").read_text())
    data["seams"][0]["kind"] = "rule"
    (repo / "seams.json").write_text(json.dumps(data))
    out = stop(repo)
    assert out["decision"] == "block" and "no longer passes its own check" in out["reason"] and "convention" in out["reason"]
    assert stop(repo, active=True) is None


def test_stop_names_stale_notes(repo):
    data = json.loads((repo / "seams.json").read_text())
    data["notes"] = ["rules"]
    (repo / "seams.json").write_text(json.dumps(data))
    (repo / "api/status.py").write_text("y\n")
    out = stop(repo)
    assert "--notes" in out["reason"]
