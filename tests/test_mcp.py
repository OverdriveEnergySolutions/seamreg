"""The MCP server: seams_check.py --mcp, spoken to over stdio like an agent would."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from seams import check, cli

CHECKER = Path(check.__file__)
SEAM = {"id": "order-statuses", "title": "Order status names", "kind": "vocabulary",
        "must_agree": "Both lists hold the same names.",
        "copies": [{"path": "api/status.py", "symbol": "STATUSES"}, {"path": "web/status.ts"}],
        "consequence": "The web app drops a status.", "risk": "high"}


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("needs git")
    for f, text in {"api/status.py": "STATUSES = ['new']\n", "web/status.ts": "x\n", "README.md": "x\n"}.items():
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text(text)
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [SEAM]}))
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def session(repo, *messages, cwd=None):
    """Send each message as one line; return the replies by id (and the raw lines)."""
    lines = "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)
    p = subprocess.run([sys.executable, str(CHECKER), "--mcp"], input=lines, capture_output=True, text=True,
                       cwd=cwd or repo, timeout=60)
    assert p.returncode == 0, p.stderr
    replies = [json.loads(l) for l in p.stdout.splitlines()]
    return {r.get("id"): r for r in replies}, replies


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def call(i, name, **arguments):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def text(reply):
    return reply["result"]["content"][0]["text"]


def test_handshake_and_tool_list(repo):
    by_id, replies = session(repo, INIT, INITIALIZED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(replies) == 2  # the notification gets no reply
    init = by_id[1]["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["serverInfo"]["name"] == "seams"
    assert "tools" in init["capabilities"]
    names = [t["name"] for t in by_id[2]["result"]["tools"]]
    assert names == ["seams_for_files", "seams_about", "seams_changed", "seams_get", "seams_check"]
    assert all(t["annotations"]["readOnlyHint"] for t in by_id[2]["result"]["tools"])


def test_an_unknown_protocol_version_gets_the_newest(repo):
    msg = dict(INIT, params=dict(INIT["params"], protocolVersion="1999-01-01"))
    by_id, _ = session(repo, msg)
    assert by_id[1]["result"]["protocolVersion"] == check.MCP_VERSIONS[0]


def test_for_files_names_the_other_copies(repo):
    by_id, _ = session(repo, INIT, call(2, "seams_for_files", files=["web/status.ts"]),
                       call(3, "seams_for_files", files=[str(repo / "README.md")]))
    assert "other copies: api/status.py" in text(by_id[2]) and not by_id[2]["result"]["isError"]
    assert "No seam lists these 1 file(s)" in text(by_id[3])


def test_about_get_and_check(repo):
    by_id, _ = session(repo, call(1, "seams_about", text="status"), call(2, "seams_get", id="order-statuses"),
                       call(3, "seams_check"), call(4, "seams_get", id="nope"))
    assert "1 seam(s) mention 'status'" in text(by_id[1])
    assert json.loads(text(by_id[2]))["id"] == "order-statuses"
    assert text(by_id[3]).startswith("seams: ok")
    assert by_id[4]["result"]["isError"] and "no seam with the id" in text(by_id[4])


def test_changed_sees_uncommitted_and_untracked_files(repo):
    (repo / "api/status.py").write_text("STATUSES = ['new', 'lost']\n")
    by_id, _ = session(repo, call(1, "seams_changed"))
    assert "not changed: web/status.ts" in text(by_id[1])
    git(repo, "checkout", "-q", "api/status.py")
    (repo / "web/new.ts").write_text("x\n")
    by_id, _ = session(repo, call(1, "seams_changed"))
    assert "No seam has a copy left behind" in text(by_id[1])


def test_changed_against_a_base_branch(repo):
    git(repo, "checkout", "-qb", "feature")
    (repo / "web/status.ts").write_text("y\n")
    git(repo, "commit", "-qam", "one copy")
    by_id, _ = session(repo, call(1, "seams_changed", base="main"), call(2, "seams_changed", base="--output=x"))
    assert "not changed: api/status.py" in text(by_id[1])
    assert by_id[2]["result"]["isError"]  # never an option for git


def test_the_registry_is_read_again_on_each_call(repo):
    data = json.loads((repo / "seams.json").read_text())
    data["seams"][0]["title"] = "Renamed"
    msgs = [call(1, "seams_get", id="order-statuses")]
    (repo / "seams.json").write_text(json.dumps(data))
    by_id, _ = session(repo, *msgs)
    assert json.loads(text(by_id[1]))["title"] == "Renamed"


def test_bad_input_never_ends_the_session(repo):
    by_id, replies = session(repo, "not json", {"jsonrpc": "2.0", "id": 2, "method": "nope"},
                             call(3, "seams_for_files", files="api/status.py"), call(4, "no_such_tool"),
                             {"id": 5}, {"jsonrpc": "2.0", "id": 6, "method": "ping"})
    assert replies[0]["error"]["code"] == -32700
    assert by_id[2]["error"]["code"] == -32601
    assert by_id[3]["result"]["isError"] and by_id[4]["result"]["isError"]
    assert by_id[5]["error"]["code"] == -32600 and by_id[6]["result"] == {}


def test_it_finds_the_registry_from_a_subfolder(repo):
    by_id, _ = session(repo, call(1, "seams_get", id="order-statuses"), cwd=repo / "web")
    assert not by_id[1]["result"]["isError"]


def test_a_broken_registry_is_an_error_not_a_crash(repo):
    (repo / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": [{"id": "x"}]}))
    by_id, _ = session(repo, call(1, "seams_about", text="x"), call(2, "seams_check"))
    assert by_id[1]["result"]["isError"] and "does not match the schema" in text(by_id[1])
    assert "problem(s)" in text(by_id[2])


def test_the_mcp_snippet_is_valid_json():
    cfg = json.loads((Path(cli.SNIPPETS) / "mcp.json").read_text())
    assert "scripts/seams_check.py --mcp" in " ".join(cfg["mcpServers"]["seams"]["args"])


def test_the_cli_runs_the_server(repo, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(INIT) + "\n"))
    assert cli.main(["mcp", "--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["serverInfo"]["name"] == "seams"
