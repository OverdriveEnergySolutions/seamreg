"""The benchmark harness: the blindness scan, the result file and the statistics table."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(BENCH))

import blindscan  # noqa: E402
import result  # noqa: E402
import table  # noqa: E402


def test_the_scan_allows_the_blind_clone_and_the_tool_and_flags_the_rest():
    pat = blindscan.forbidden_pattern(Path("/w/ws"), Path("/home/u/seamreg"), "detection")
    allowed = ["/w/ws/blind/app.py", "uvx --from /w/ws/tool seams scan", "/w/ws/tool/skills/seams/SKILL.md",
               "/w/ws/tool/agents/seam-reviewer.md", "/w/ws/detection/tmp/x"]
    flagged = ["/w/ws/full/app.py", "/w/ws/key/key.md", "/w/ws/blindfold/x", "/w/ws/tool/src/seams/check.py",
               "/w/ws/tool/src/seams/catalog/misses/a.json", "/home/u/seamreg/docs/benchmarks.md",
               "/home/u/.claude/projects/p/s.jsonl"]
    assert not [t for t in allowed if pat.search(t)]
    assert [t for t in flagged if not pat.search(t)] == []


def test_the_scan_reads_subagent_transcripts_and_finds_network_calls(tmp_path):
    proj = tmp_path / "projects" / "-w-ws-blind"
    sub = proj / "sid1" / "subagents"
    sub.mkdir(parents=True)

    def call(name, inp):
        return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})

    (proj / "sid1.jsonl").write_text(call("Read", {"file_path": "/w/ws/blind/a.py"}) + "\n")
    (sub / "agent-1.jsonl").write_text(call("Read", {"file_path": "/w/ws/key/key.md"}) + "\n"
                                       + call("Bash", {"command": "curl https://example.com"}) + "\n")
    files = blindscan.transcripts("sid1", home=tmp_path)
    assert len(files) == 2
    calls, hits, net = blindscan.scan(files, blindscan.forbidden_pattern(Path("/w/ws"), None, "detection"))
    assert calls == 3 and len(hits) == 1 and "key.md" in hits[0][0] and len(net) == 1


def make_workspace(tmp_path, measures):
    (tmp_path / "bench.json").write_text(json.dumps({
        "repo_url": "https://github.com/o/r", "snapshot": "a" * 40, "snapshot_date": "2026-01-01",
        "window_end": "b" * 40, "window_end_date": "2026-06-01", "later_commits": 400, "files": 900}))
    s = tmp_path / "detection"
    (s / "grade").mkdir(parents=True)
    (s / "summary.json").write_text(json.dumps({
        "model": "claude-sonnet-5-5", "effort": "max", "tool_commit": "c" * 40, "session_id": "x", "turns": 3,
        "complete": True, "cost_usd_api_equivalent": 41.5, "seams": 50, "risk": {"high": 5, "medium": 20, "low": 25},
        "drift_claims": 12}))
    (s / "blindscan.txt").write_text("detection: 3 transcripts, 812 tool calls, forbidden 0, network 0\n")
    (s / "grade" / "measures.json").write_text(json.dumps(measures))


def test_a_result_holds_the_envelope_and_the_kinds_own_measures(tmp_path):
    measures = {"key_drifts": {"total": 9, "caught": 3, "partial": 1}, "anything_new": 7}
    make_workspace(tmp_path, measures)
    out = result.build(tmp_path, "detection", "detection")
    assert out["kind"] == "detection" and out["measures"] == measures
    assert out["blindscan"] == {"tool_calls": 812, "forbidden": 0, "network": 0}
    assert out["cost_usd_api_equivalent"] == 41.5 and out["registry"]["seams"] == 50
    assert out["costs_usd_api_equivalent"] == {"detection": 41.5, "total": 41.5} and out["resumes"] == 0


def test_a_result_adds_the_key_and_grading_costs(tmp_path):
    make_workspace(tmp_path, {})
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "key.json").write_text(json.dumps({"total_cost_usd": 3.684}))
    (tmp_path / "sessions" / "grade.json").write_text(json.dumps({"total_cost_usd": 1.71}))
    costs = result.build(tmp_path, "detection", "detection")["costs_usd_api_equivalent"]
    assert costs == {"detection": 41.5, "grade": 1.71, "key": 3.68, "total": 46.89}


def test_the_scan_flags_the_home_folder_and_network_commands_only_in_command_position():
    pat = blindscan.forbidden_pattern(Path("/var/tmp/b/ws"), None, "detection", Path("/home/u"))
    assert pat.search("ls ~/.cargo") and pat.search("cat /home/u/.ssh/id") and not pat.search("/var/tmp/b/ws/blind/x")
    assert blindscan.NET.search("cd a && gh pr list") and not blindscan.NET.search("const gh = (sha) => 1;")
    for wrapped in ('bash -c "curl x"', "xargs curl -s", "timeout 5 gh api x", "`wget x`", "env A=1 nc -l 1"):
        assert blindscan.NET.search(wrapped), wrapped


def test_the_table_shows_any_kinds_measures_without_changes(tmp_path):
    make_workspace(tmp_path, {"key_drifts": {"total": 9, "caught": 3, "partial": 1}})
    one = tmp_path / "results" / "r-aaaaaaaaaa-detection"
    one.mkdir(parents=True)
    (one / "result.json").write_text(json.dumps(result.build(tmp_path, "detection", "detection")))
    other = tmp_path / "results" / "r-aaaaaaaaaa-newkind"
    other.mkdir()
    (other / "result.json").write_text(json.dumps(dict(result.build(tmp_path, "detection", "newkind"),
                                                       measures={"tasks": {"total": 10, "updated": 6}})))
    text = table.render(table.load(tmp_path / "results"))
    assert "## detection" in text and "caught 3/9, partial 1/9" in text
    assert "## newkind" in text and "updated 6/10" in text


def test_the_scan_flags_paths_that_climb_out_of_the_blind_clone():
    for t in ("cat ../key/key.md", "ls ..", "git -C .. log", "/w/ws/blind/../full/x"):
        assert blindscan.CLIMB.search(t), t
    for t in ("git log HEAD~1..HEAD", "range 1..5"):
        assert not blindscan.CLIMB.search(t), t


def test_a_result_refuses_an_unfinished_run(tmp_path):
    import pytest
    make_workspace(tmp_path, {})
    summary = tmp_path / "detection" / "summary.json"
    summary.write_text(json.dumps(dict(json.loads(summary.read_text()), complete=False)))
    with pytest.raises(ValueError, match="did not finish"):
        result.build(tmp_path, "detection", "detection")


def test_the_scan_flags_the_workspace_itself_and_a_climb_before_a_newline(tmp_path):
    pat = blindscan.forbidden_pattern(Path("/w/ws"), None, "detection")
    assert pat.search("ls /w/ws") and pat.search('ls "/w/ws/"') and not pat.search("/w/ws/blind/a.py")
    proj = tmp_path / "projects" / "p"
    proj.mkdir(parents=True)
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "cd ..\nls"}}]}})
    (proj / "s2.jsonl").write_text(line + "\n")
    _, hits, _ = blindscan.scan(blindscan.transcripts("s2", home=tmp_path), pat)
    assert len(hits) == 1
