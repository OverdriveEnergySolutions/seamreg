"""The pull request comment: the --markdown report, and the CI scripts that post it."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from seams import check

SNIPPETS = Path(check.__file__).with_name("snippets")


def seam(sid, risk="high", tied=False, **kw):
    s = {"id": sid, "title": f"title of {sid}", "kind": "vocabulary", "must_agree": "Both lists agree.",
         "copies": [{"path": "a.py"}, {"path": "b.ts"}], "consequence": "c", "risk": risk}
    if tied:
        s["ties"] = [{"path": "t.py", "covers": "all"}]
    s.update(kw)
    return s


# --- the report ------------------------------------------------------------------

def test_nothing_left_behind_is_a_clear_report():
    out = check.markdown_report([], 3, "x")
    assert out.startswith(check.COMMENT_MARKER + "\n")
    assert check.COMMENT_CLEAR in out and "changes 3 file(s)" in out


def test_report_lists_highest_risk_first_and_names_the_copies_not_changed():
    low, high = seam("low-one", "low"), seam("high-one", "high", tied=True)
    out = check.markdown_report([(low, ["a.py"], ["b.ts"]), (high, ["b.ts"], ["a.py"])], 2, "x")
    assert out.startswith(check.COMMENT_MARKER + "\n") and check.COMMENT_CLEAR not in out
    assert out.index("high-one") < out.index("low-one")
    assert "**Not changed:** `a.py`" in out and "- Tie: `t.py`, covers all" in out
    assert "1 of these seams have no full tie" in out


def test_report_text_cannot_mention_anyone_or_inject_html():
    s = seam("s", must_agree="Ask @alice. <img src=x onerror=1> <!-- seams-pr-comment -->")
    out = check.markdown_report([(s, ["a.py"], ["b.ts"])], 1, "x")
    assert "@alice" not in out and "@&#8203;alice" in out
    assert "<img" not in out and out.count(check.COMMENT_MARKER) == 1


def test_code_spans_keep_their_text():
    assert check._md_text("Every `seams <command>` and <b>") == "Every `seams <command>` and &lt;b&gt;"
    assert check._md_text("an `unclosed <span") == "an `unclosed &lt;span"
    assert check._md_text("``a ` b`` @x") == "``a ` b`` @&#8203;x"


def test_report_fences_a_path_that_holds_a_backtick():
    assert check._md_path("a`b.py") == "``a`b.py``"
    assert check._md_path("`x") == "`` `x ``"


def test_a_long_report_stays_under_the_comment_limit():
    big = [(seam(f"s{i}", must_agree="w" * 2000), ["a.py"], ["b.ts"]) for i in range(60)]
    out = check.markdown_report(big, 1, "python3 c.py --diff origin/main")
    assert len(out) < 65536 and "do not fit in one comment" in out
    assert "python3 c.py --diff origin/main" in out


def test_markdown_flag_keeps_the_fail_untied_exit_code(tmp_path, capsys):
    for f in ["a.py", "b.ts", "t.py"]:
        (tmp_path / f).write_text("x\n")
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [seam("s")]}))
    root = ["--root", str(tmp_path)]
    assert check.main(root + ["--changed", "a.py", "--markdown"]) == 0
    assert "**Not changed:** `b.ts`" in capsys.readouterr().out
    assert check.main(root + ["--changed", "a.py", "--markdown", "--fail-untied"]) == 1
    capsys.readouterr()
    assert check.main(root + ["--changed", "a.py", "b.ts", "--markdown", "--fail-untied"]) == 0
    assert check.COMMENT_CLEAR in capsys.readouterr().out


# --- the CI scripts, against a stand-in for gh ----------------------------------------

STUB_GH = r'''
import json, subprocess, sys
state_file = sys.argv[1]; args = sys.argv[2:]
st = json.load(open(state_file))
st["calls"].append(args)
def save(): json.dump(st, open(state_file, "w"))
assert args[0] == "api", args
method = args[args.index("-X") + 1] if "-X" in args else ("POST" if "--input" in args else "GET")
path = [a for a in args[1:] if a.startswith("repos/")][0]
if method == "GET" and "/pulls/" in path:
    print(st["head_sha"]); save(); sys.exit(0)
if method == "GET":
    if st.get("fail_list"):
        save(); sys.exit(1)
    expr = args[args.index("--jq") + 1]
    out = subprocess.run(["jq", "-r", expr], input=json.dumps(st["comments"]), capture_output=True, text=True)
    sys.stdout.write(out.stdout); save(); sys.exit(out.returncode)
if st.get("read_only"):
    sys.stderr.write("HTTP 403: Resource not accessible by integration\n"); save(); sys.exit(1)
body = json.load(sys.stdin)["body"]
if method == "PATCH":
    cid = int(path.rsplit("/", 1)[1])
    [c for c in st["comments"] if c["id"] == cid][0]["body"] = body
else:
    st["comments"].append({"id": 100 + len(st["comments"]), "user": {"type": "Bot"}, "body": body})
save()
'''


def run_block(snippet, step):
    """The `run: |` script of the step named `step` in a snippet, and its shell."""
    lines = (SNIPPETS / snippet).read_text().splitlines()
    i = next(n for n, l in enumerate(lines) if l.strip() == f"- name: {step}")
    shell = None
    for j in range(i + 1, len(lines)):
        s = lines[j].strip()
        if s.startswith("shell:"):
            shell = s.split(":", 1)[1].strip()
        if s == "run: |":
            ind = len(lines[j]) - len(lines[j].lstrip()) + 2
            body = []
            for l in lines[j + 1:]:
                if l.strip() and len(l) - len(l.lstrip()) < ind:
                    break
                body.append(l[ind:] if l.strip() else "")
            return "\n".join(body) + "\n", shell
    raise AssertionError(f"no run block in {step}")


@pytest.fixture
def gh(tmp_path):
    if not (shutil.which("jq") and shutil.which("bash")):
        pytest.skip("needs jq and bash")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (tmp_path / "gh.py").write_text(STUB_GH)
    state = tmp_path / "state.json"
    (bin_ / "gh").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{tmp_path / "gh.py"}" "{state}" "$@"\n')
    (bin_ / "gh").chmod(0o755)

    def run(snippet, report, comments=(), head_sha="abc", pr="7", same_repo="true", **flags):
        state.write_text(json.dumps({"comments": list(comments), "calls": [], "head_sha": head_sha, **flags}))
        temp = tmp_path / "runner"
        shutil.rmtree(temp, ignore_errors=True)
        (temp / "seams").mkdir(parents=True)
        for f in [temp / "seams.md", temp / "seams" / "seams.md"]:
            f.write_text(report)
        (temp / "seams" / "pr.txt").write_text(pr + "\n")
        script, shell = run_block(snippet, "seams comment")
        assert shell == "bash"  # GitHub runs `shell: bash` as bash -eo pipefail
        env = dict(os.environ, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", GH_TOKEN="t", PR=pr,
                   SAME_REPO=same_repo, GITHUB_REPOSITORY="o/r", RUNNER_TEMP=str(temp), HEAD_SHA="abc")
        p = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                           env=env, capture_output=True, text=True)
        st = json.loads(state.read_text())
        return p, st

    return run


REPORT = check.markdown_report([(seam("s"), ["a.py"], ["b.ts"])], 1, "x")
CLEAR = check.markdown_report([], 1, "x")
SNIPS = ["github-actions.yml", "github-actions-forks-comment.yml"]


@pytest.mark.parametrize("snip", SNIPS)
def test_first_report_posts_one_comment(gh, snip):
    p, st = gh(snip, REPORT)
    assert p.returncode == 0, p.stderr
    assert [c["body"] for c in st["comments"]] == [REPORT]


@pytest.mark.parametrize("snip", SNIPS)
def test_a_later_push_edits_the_comment_and_leaves_people_alone(gh, snip):
    human = {"id": 1, "user": {"type": "User"}, "body": check.COMMENT_MARKER + " quoted by a person"}
    ours = {"id": 2, "user": {"type": "Bot"}, "body": check.COMMENT_MARKER + "\nold"}
    p, st = gh(snip, REPORT, comments=[human, ours])
    assert p.returncode == 0, p.stderr
    assert len(st["comments"]) == 2
    assert st["comments"][0]["body"] == human["body"] and st["comments"][1]["body"] == REPORT


@pytest.mark.parametrize("snip", SNIPS)
def test_a_clear_report_posts_nothing_new(gh, snip):
    p, st = gh(snip, CLEAR)
    assert p.returncode == 0, p.stderr
    assert st["comments"] == []


@pytest.mark.parametrize("snip", SNIPS)
def test_a_clear_report_replaces_an_old_warning(gh, snip):
    p, st = gh(snip, CLEAR, comments=[{"id": 2, "user": {"type": "Bot"}, "body": REPORT}])
    assert p.returncode == 0, p.stderr
    assert st["comments"][0]["body"] == CLEAR


@pytest.mark.parametrize("snip", SNIPS)
def test_a_read_only_token_warns_and_does_not_fail(gh, snip):
    p, st = gh(snip, REPORT, read_only=True)
    assert p.returncode == 0 and "::warning::" in p.stdout


@pytest.mark.parametrize("snip", SNIPS)
def test_a_failed_comment_listing_still_posts(gh, snip):
    p, st = gh(snip, REPORT, fail_list=True)
    assert p.returncode == 0, p.stderr
    assert len(st["comments"]) == 1


def test_same_repo_workflow_skips_a_fork(gh):
    p, st = gh("github-actions.yml", REPORT, same_repo="false")
    assert p.returncode == 0 and st["calls"] == []


def test_fork_comment_posts_only_to_the_pull_request_at_that_commit(gh):
    p, st = gh("github-actions-forks-comment.yml", REPORT, head_sha="other")
    assert p.returncode == 0 and st["comments"] == [] and "Not posting" in p.stdout


@pytest.mark.parametrize("pr", ["", "7; rm -rf /", "../1"])
def test_fork_comment_refuses_a_bad_pull_request_number(gh, pr):
    p, st = gh("github-actions-forks-comment.yml", REPORT, pr=pr)
    assert p.returncode == 1 and st["calls"] == []


def test_the_fork_check_workflow_saves_what_the_comment_workflow_reads():
    check_wf = (SNIPPETS / "github-actions-forks.yml").read_text()
    comment_wf = (SNIPPETS / "github-actions-forks-comment.yml").read_text()
    assert "name: seams\n" in check_wf and "workflows: [seams]" in comment_wf
    assert "name: seams-comment" in check_wf and "name: seams-comment" in comment_wf
    assert "seams/seams.md" in check_wf and "pr.txt" in check_wf
    assert "actions/checkout" not in comment_wf  # never runs the pull request's code with a write token


@pytest.mark.parametrize("snip", ["github-actions.yml", "github-actions-forks.yml"])
def test_the_checker_step_records_its_exit_code_for_the_last_step(snip):
    script, _ = run_block(snip, "seams this pull request touches")
    assert "--markdown" in script and 'echo "code=' in script
