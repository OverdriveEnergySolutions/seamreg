"""Change coupling: files in different folders that keep changing in the same commits."""
from __future__ import annotations

import subprocess

from seams import scan
from seams.scan import cochange


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"})


def commit(repo, files, n=[0]):
    for p in files:
        n[0] += 1
        (repo / p).parent.mkdir(parents=True, exist_ok=True)
        (repo / p).write_text(f"edit {n[0]}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "c")


def pairs(doc):
    return [sorted(f["path"] for f in l["files"]) for l in doc["leads"] if l["kind"] == "co-change"]


def repo_with_history(tmp_path):
    git(tmp_path, "init", "-q")
    for _ in range(3):
        commit(tmp_path, ["api/status.py", "docs/statuses.md"])             # a seam: different folders
        commit(tmp_path, ["api/a.py", "api/b.py"])                          # one folder: a feature
        commit(tmp_path, ["api/status.py", "tests/test_status.py"])        # a test with its code
    commit(tmp_path, ["web/lonely.ts"])
    return tmp_path


def test_files_in_different_folders_that_change_together_are_a_lead(tmp_path):
    doc = scan.scan(repo_with_history(tmp_path))
    assert ["api/status.py", "docs/statuses.md"] in pairs(doc)
    lead = next(l for l in doc["leads"] if l["kind"] == "co-change")
    assert "changed together in 3 commits" in lead["detail"]


def test_same_folder_pairs_and_tests_are_left_out(tmp_path):
    found = pairs(scan.scan(repo_with_history(tmp_path)))
    assert ["api/a.py", "api/b.py"] not in found
    assert not any("tests/test_status.py" in p for p in found)


def test_a_bulk_commit_does_not_couple_everything(tmp_path):
    git(tmp_path, "init", "-q")
    files = [f"d{i}/f.py" for i in range(cochange.MAX_FILES + 1)]
    for _ in range(3):
        commit(tmp_path, files)
    assert pairs(scan.scan(tmp_path)) == []


def test_two_shared_commits_are_not_enough(tmp_path):
    git(tmp_path, "init", "-q")
    for _ in range(cochange.MIN_SHARED - 1):
        commit(tmp_path, ["a/x.py", "b/y.py"])
    assert pairs(scan.scan(tmp_path)) == []


def test_a_file_that_changes_far_more_often_is_weakly_coupled(tmp_path):
    git(tmp_path, "init", "-q")
    for _ in range(3):
        commit(tmp_path, ["a/x.py", "b/hub.py"])
    for _ in range(30):
        commit(tmp_path, ["b/hub.py"])
    assert pairs(scan.scan(tmp_path)) == []   # 3 shared / avg(3, 33) = 17%, under MIN_DEGREE


def test_no_history_gives_no_leads(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    assert pairs(scan.scan(tmp_path)) == []
