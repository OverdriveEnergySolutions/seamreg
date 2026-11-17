"""One test per guard in the checker. Remove or weaken a guard and its test fails."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from seams import check

CHECKER = Path(check.__file__)


def seam(**over):
    base = {
        "id": "status-list",
        "title": "Order status names",
        "kind": "vocabulary",
        "must_agree": "Both files list the same status names.",
        "copies": [{"path": "api/status.py", "symbol": "STATUSES"},
                   {"path": "web/status.ts", "symbol": "STATUSES"}],
        "consequence": "The web app shows a status the API never sends.",
        "risk": "medium",
    }
    base.update(over)
    return base


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "api/status.py").write_text('STATUSES = ["open", "shipped"]\n')
    (tmp_path / "web/status.ts").write_text('export const STATUSES = ["open", "shipped"];\n')
    (tmp_path / "tests/test_status.py").write_text("def test_status_parity():\n    pass\n")
    return tmp_path


def errors(root, *seams, **top):
    data = {"schema_version": 1, "seams": list(seams)}
    data.update(top)
    return check.check(data, root)


def one(errs, fragment):
    assert len(errs) == 1, errs
    assert fragment in errs[0], errs[0]


# --- a true registry passes ------------------------------------------------

def test_a_true_registry_passes(repo):
    tie = {"path": "tests/test_status.py", "test": "test_status_parity", "covers": "all"}
    assert errors(repo, seam(ties=[tie])) == []


def test_an_empty_registry_passes(repo):
    assert errors(repo) == []


# --- schema guards -----------------------------------------------------------

def test_wrong_schema_version_fails(repo):
    one(errors(repo, schema_version=2), "schema_version: must be 1")


def test_true_is_not_schema_version_1(repo):
    # In Python True == 1, so a plain == check would accept it.
    one(errors(repo, schema_version=True), "schema_version")


def test_unknown_top_level_field_fails(repo):
    one(errors(repo, extra=1), "unknown field 'extra'")


def test_unknown_seam_field_fails(repo):
    one(errors(repo, seam(colour="red")), "unknown field 'colour'")


def test_missing_required_field_fails(repo):
    s = seam()
    del s["consequence"]
    one(errors(repo, s), "missing required field 'consequence'")


def test_bad_enum_fails(repo):
    one(errors(repo, seam(kind="vibe")), "must be one of")


def test_wrong_type_fails(repo):
    one(errors(repo, seam(copies="api/status.py")), "expected array")


def test_blank_text_fails(repo):
    one(errors(repo, seam(title="   ")), "non-space")


def test_bad_id_fails(repo):
    one(errors(repo, seam(id="Status_List")), "does not match")


def test_bad_drift_source_fails(repo):
    one(errors(repo, seam(drift={"text": "differs", "source": "vibes"})), "must be one of")


def test_drift_null_passes(repo):
    assert errors(repo, seam(drift=None)) == []


def test_schema_errors_stop_before_repo_checks(repo):
    # A broken shape would make the repo checks crash or report nonsense.
    errs = errors(repo, seam(copies=[{"path": 7}]))
    assert errs and all("expected string" in e for e in errs)


# --- registry rules beyond the schema ----------------------------------------

def test_duplicate_id_fails(repo):
    one(errors(repo, seam(), seam()), "id also used by seams[0]")


def test_one_copy_fails_unless_single_source(repo):
    copies = [{"path": "api/status.py"}]
    one(errors(repo, seam(copies=copies)), "lists one copy")
    assert errors(repo, seam(copies=copies, single_source=True)) == []


def test_no_copies_fails_even_for_a_single_source(repo):
    # The one-copy rule does not cover this case, so the schema's minItems must.
    one(errors(repo, seam(copies=[], single_source=True)), "needs at least 1 item")


def test_partial_tie_needs_a_note(repo):
    tie = {"path": "tests/test_status.py", "covers": "partial"}
    one(errors(repo, seam(ties=[tie])), "its note must say which copies")
    tie["note"] = "api and web only"
    assert errors(repo, seam(ties=[tie])) == []


# --- paths --------------------------------------------------------------------

@pytest.mark.parametrize("path, fragment", [
    ("/etc/passwd", "is absolute"),
    ("C:/x.py", "is absolute"),
    ("../outside.py", "leaves the repo"),
    ("api/../../outside.py", "leaves the repo"),
    ("api\\status.py", "backslash"),
])
def test_unsafe_paths_fail(repo, path, fragment):
    copies = [{"path": path}, {"path": "web/status.ts"}]
    one(errors(repo, seam(copies=copies)), fragment)


def test_missing_file_fails(repo):
    copies = [{"path": "api/gone.py"}, {"path": "web/status.ts"}]
    one(errors(repo, seam(copies=copies)), "does not exist")


def test_folder_as_copy_fails(repo):
    copies = [{"path": "api"}, {"path": "web/status.ts"}]
    one(errors(repo, seam(copies=copies)), "is a folder")


def test_missing_symbol_fails(repo):
    copies = [{"path": "api/status.py", "symbol": "STATES"}, {"path": "web/status.ts"}]
    one(errors(repo, seam(copies=copies)), "'STATES' no longer appears")


def test_missing_tie_file_fails(repo):
    tie = {"path": "tests/test_gone.py", "covers": "all"}
    one(errors(repo, seam(ties=[tie])), "ties[0].path")


def test_missing_tie_test_name_fails(repo):
    tie = {"path": "tests/test_status.py", "test": "test_renamed", "covers": "all"}
    one(errors(repo, seam(ties=[tie])), "'test_renamed' no longer appears")


# --- globs ---------------------------------------------------------------------

def test_glob_star_stays_in_one_folder(repo):
    (repo / "api/v2").mkdir()
    (repo / "api/v2/status.py").write_text("STATUSES = []\n")
    files, problem = check.Repo(repo).resolve("api/*.py")
    assert problem is None and files == ["api/status.py"]


def test_glob_double_star_spans_zero_or_more_folders(repo):
    (repo / "api/v2").mkdir()
    (repo / "api/v2/status.py").write_text("STATUSES = []\n")
    files, _ = check.Repo(repo).resolve("api/**/status.py")
    assert files == ["api/status.py", "api/v2/status.py"]


def test_literal_bracket_path_is_a_file_not_a_glob(repo):
    # Next.js routes live in folders like [id]. As a glob, [id] means "i or d".
    (repo / "web/[id]").mkdir()
    (repo / "web/[id]/page.tsx").write_text("STATUSES\n")
    copies = [{"path": "api/status.py"}, {"path": "web/[id]/page.tsx", "symbol": "STATUSES"}]
    assert errors(repo, seam(copies=copies)) == []


def test_glob_that_matches_nothing_fails(repo):
    copies = [{"path": "api/*.go"}, {"path": "web/status.ts"}]
    one(errors(repo, seam(copies=copies)), "matches no file")


def test_symbol_in_any_glob_match_passes(repo):
    copies = [{"path": "*/status.*", "symbol": "export const"}, {"path": "api/status.py"}]
    assert errors(repo, seam(copies=copies)) == []


def test_glob_skips_dependency_folders(repo):
    (repo / "node_modules/pkg").mkdir(parents=True)
    (repo / "node_modules/pkg/status.ts").write_text("x\n")
    files, _ = check.Repo(repo).resolve("**/status.ts")
    assert files == ["web/status.ts"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_symlink_loop_does_not_hang(repo):
    os.symlink(repo, repo / "api/loop")
    reg = {"schema_version": 1,
           "seams": [seam(copies=[{"path": "**/status.py"}, {"path": "web/status.ts"}])]}
    (repo / "seams.json").write_text(json.dumps(reg))
    run = subprocess.run([sys.executable, str(CHECKER), "--root", str(repo)],
                         capture_output=True, text=True, timeout=5)
    assert run.returncode == 0, run.stdout + run.stderr


# --- the command ----------------------------------------------------------------

def run_main(repo, capsys, *argv):
    code = check.main(["--root", str(repo), *argv])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_main_passes_and_says_it_cannot_prove_completeness(repo, capsys):
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [seam()]}))
    code, out = run_main(repo, capsys)
    assert code == 0
    assert "not that the list is complete" in out


def test_main_fails_on_a_problem(repo, capsys):
    bad = seam(copies=[{"path": "api/gone.py"}, {"path": "web/status.ts"}])
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [bad]}))
    code, out = run_main(repo, capsys)
    assert code == 1 and "does not exist" in out


def test_main_without_registry_exits_2(repo, capsys):
    code, out = run_main(repo, capsys)
    assert code == 2 and "no registry" in out


def test_main_on_bad_json_exits_1(repo, capsys):
    (repo / "seams.json").write_text('{"schema_version": 1,')
    code, out = run_main(repo, capsys)
    assert code == 1 and "not valid JSON" in out


def test_duplicate_key_fails_instead_of_dropping_data(repo, capsys):
    # Without the guard, the second "copies" silently replaces the first.
    text = ('{"schema_version": 1, "seams": [{"id": "a", "copies": [], "copies": []}]}')
    (repo / "seams.json").write_text(text)
    code, out = run_main(repo, capsys)
    assert code == 1 and "'copies' appears twice" in out


def test_main_on_missing_root_exits_2(tmp_path, capsys):
    code = check.main(["--root", str(tmp_path / "nope")])
    assert code == 2


# --- the validator covers the schema ---------------------------------------------

def _walk(schema):
    yield schema
    for sub in schema.get("properties", {}).values():
        yield from _walk(sub)
    if "items" in schema:
        yield from _walk(schema["items"])


def test_validator_implements_every_keyword_the_schema_uses():
    # A keyword the validator ignores would be printed in the schema but never enforced.
    for node in _walk(check.SCHEMA):
        assert set(node) <= check.SUPPORTED, set(node) - check.SUPPORTED
        types = node.get("type", [])
        for t in types if isinstance(types, list) else [types]:
            assert t in check._TYPES, t
