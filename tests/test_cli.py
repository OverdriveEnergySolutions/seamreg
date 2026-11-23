from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from seams import check, cli


def test_init_copies_the_checker_unchanged_and_starts_an_empty_registry(tmp_path, capsys):
    assert cli.main(["init", "--root", str(tmp_path)]) == 0
    copy = tmp_path / cli.DEFAULT_CHECKER
    assert copy.read_bytes() == Path(check.__file__).read_bytes()
    assert json.loads((tmp_path / "seams.json").read_text()) == cli.EMPTY_REGISTRY
    out = capsys.readouterr().out
    assert "run: python3 scripts/seams_check.py" in out
    # Planning comes before the first review: measured on 23 replayed commits, the planning text alone
    # helps as much as the registry does where the registry does not yet hold the copy.
    assert out.index("Add these now") < out.index("Planning") < out.index("After the first review")


def test_the_copied_checker_runs_alone(tmp_path):
    # The copy must not import the seams package: run it with no package on the path.
    cli.main(["init", "--root", str(tmp_path)])
    run = subprocess.run([sys.executable, "-I", cli.DEFAULT_CHECKER],
                         cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stdout + run.stderr


def test_init_keeps_an_existing_registry(tmp_path):
    (tmp_path / "seams.json").write_text('{"schema_version": 1, "seams": [], "x": 1}\n')
    cli.main(["init", "--root", str(tmp_path)])
    assert '"x": 1' in (tmp_path / "seams.json").read_text()


def test_init_refuses_to_overwrite_an_edited_copy_without_upgrade(tmp_path):
    copy = tmp_path / cli.DEFAULT_CHECKER
    copy.parent.mkdir()
    copy.write_text('__version__ = "0.0.1"\n')
    assert cli.main(["init", "--root", str(tmp_path)]) == 1
    assert copy.read_text() == '__version__ = "0.0.1"\n'
    assert cli.main(["init", "--root", str(tmp_path), "--upgrade"]) == 0
    assert copy.read_bytes() == Path(check.__file__).read_bytes()


def test_init_refuses_a_checker_path_outside_the_repo(tmp_path):
    assert cli.main(["init", "--root", str(tmp_path), "--checker", "../x.py"]) == 2
    assert not (tmp_path.parent / "x.py").exists()


def test_check_warns_when_the_copy_is_a_different_version(tmp_path, capsys):
    cli.main(["init", "--root", str(tmp_path)])
    copy = tmp_path / cli.DEFAULT_CHECKER
    copy.write_text(copy.read_text().replace(check.__version__, "0.0.1", 1))
    capsys.readouterr()
    assert cli.main(["check", "--root", str(tmp_path)]) == 0
    assert "is checker 0.0.1" in capsys.readouterr().err


def test_init_printout_carries_the_hardened_snippets(tmp_path, capsys):
    cli.main(["init", "--root", str(tmp_path), "--checker", "tools/seams_check.py"])
    out = capsys.readouterr().out
    assert "scripts/seams_check.py" not in out and "python3 tools/seams_check.py" in out
    assert 'BASE_REF: ${{ github.base_ref }}' in out
    assert 'python3 tools/seams_check.py --diff "origin/${BASE_REF}" --markdown >' in out
    assert "--fail-untied --markdown" not in out and '--markdown --fail-untied' not in out  # warn-only by default
    assert "github-actions-forks.yml" in out  # where the fork setup lives
    assert "verbose: true" in out
    assert "grep -v" in out                      # the plain git hook form
    assert "When you plan a change:" in out      # the planning text, inline
    assert "exec python3 tools/seams_check.py --mcp" in out  # the MCP config, at this repo's checker


def test_snippets_ship_inside_the_package():
    names = {p.name for p in cli.SNIPPETS.iterdir()}
    assert {"github-actions.yml", "pre-commit.yaml", "git-hook.sh", "claude-code-settings.json",
            "agent-instructions.md"} <= names


def test_the_ci_snippet_is_a_whole_workflow_that_runs_on_pull_requests():
    text = (cli.SNIPPETS / "github-actions.yml").read_text()
    assert "\non:\n  push:\n  pull_request:\n" in text and "\npermissions:\n  contents: read\n" in text


@pytest.mark.parametrize("setup, says", [
    (None, "no commit-hook setup that git tracks"),
    (".pre-commit-config.yaml", "uses the pre-commit framework"),
    (".husky", "uses husky"),
])
def test_init_says_where_the_commit_check_goes(tmp_path, capsys, setup, says):
    if setup == ".husky":
        (tmp_path / ".husky").mkdir()
    elif setup:
        (tmp_path / setup).write_text("repos: []\n")
    cli.main(["init", "--root", str(tmp_path)])
    assert says in capsys.readouterr().out
