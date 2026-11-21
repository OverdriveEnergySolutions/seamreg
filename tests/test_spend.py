"""The run record and real spend: what a paid run costs, counted from the agents' own transcripts,
and the dispatch check that holds a run under its ceiling."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seams import cli, presets, spend

FIX = Path(__file__).parent / "fixtures" / "transcripts"
# Round test prices, dollars per million tokens: input, output, cache write (5 minutes), cache write
# (1 hour), cache read.
PRICES = {"claude-sonnet-5-5": (3.0, 15.0, 3.75, 6.0, 0.30), "claude-opus-5-5": (15.0, 75.0, 18.75, 30.0, 1.50)}


@pytest.fixture(autouse=True)
def prices(monkeypatch):
    monkeypatch.setattr(presets, "PRICES", PRICES)


def dollars(u, p):
    return (u["input_tokens"] * p[0] + u["output_tokens"] * p[1] + u["cache_creation_input_tokens"] * p[2]
            + u["cache_read_input_tokens"] * p[4]) / 1e6


U1 = {"input_tokens": 10, "output_tokens": 1000, "cache_creation_input_tokens": 20000, "cache_read_input_tokens": 0}
U2 = {"input_tokens": 5, "output_tokens": 2000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100000}


def test_a_response_split_across_lines_is_counted_once():
    got = spend.transcript_cost(FIX / "split-message.jsonl")
    want = dollars(U1, PRICES["claude-sonnet-5-5"]) + dollars(U2, PRICES["claude-sonnet-5-5"])
    assert got["dollars"] == pytest.approx(want)
    assert got["messages"] == 2
    assert got["models"] == ["claude-sonnet-5-5"] and got["efforts"] == ["high"]


def test_each_model_is_priced_at_its_own_rate():
    got = spend.transcript_cost(FIX / "two-models-at-max.jsonl")
    want = dollars(U1, PRICES["claude-opus-5-5"]) + dollars(U1, PRICES["claude-sonnet-5-5"])
    assert got["dollars"] == pytest.approx(want)
    assert got["efforts"] == ["max"]


def test_a_model_missing_from_the_price_table_is_cost_unknown():
    got = spend.transcript_cost(FIX / "unknown-model.jsonl")
    assert got["dollars"] is None and got["unpriced"] == ["claude-sonnet-9-9"]


def test_a_missing_transcript_is_cost_unknown(tmp_path):
    got = spend.transcript_cost(tmp_path / "gone.jsonl")
    assert got["dollars"] is None


# --- the run record ------------------------------------------------------

def settings(name="standard"):
    return presets.resolve(name)


def start(out, ceiling=10.0, per_packet=None, name="standard"):
    per = per_packet or {s: 1.0 for s in presets.STEPS}
    return spend.start(out, settings(name), estimate=ceiling, per_packet=per)


def stop_payload(tmp_path, agent="seam-lead-checker", fixture="split-message.jsonl", session="sess-A", aid="a1"):
    return {"hook_event_name": "SubagentStop", "session_id": session, "cwd": str(tmp_path), "agent_id": aid,
            "agent_type": agent, "agent_transcript_path": str(FIX / fixture)}


def pre_payload(tmp_path, agent="seam-lead-checker", session="sess-A"):
    return {"hook_event_name": "PreToolUse", "session_id": session, "cwd": str(tmp_path), "tool_name": "Agent",
            "tool_input": {"subagent_type": agent, "description": "d", "prompt": "p"}}


def repo(tmp_path):
    (tmp_path / "seams.json").write_text(json.dumps({"schema_version": 1, "seams": []}))
    return tmp_path, tmp_path / ".seams-scan"


def subrepo(tmp_path, name):
    """A repo in its own folder, so files a test writes beside it stay outside it."""
    (tmp_path / name).mkdir()
    return repo(tmp_path / name)


def denied(out):
    return bool(out) and out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_start_refuses_while_a_run_is_open_and_shows_its_spend(tmp_path):
    root, out = repo(tmp_path)
    start(out)
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root))
    with pytest.raises(spend.OpenRun) as e:
        start(out)
    assert e.value.state["recorded"] > 0


def test_a_finished_agent_adds_its_cost_model_and_effort(tmp_path):
    root, out = repo(tmp_path)
    start(out)
    assert not denied(spend.on_pre_tool_use(pre_payload(root)))
    spend.on_subagent_stop(stop_payload(root))
    st = spend.state(out)
    [a] = st["agents"]
    assert a["step"] == "lead_check" and a["efforts"] == ["high"] and a["dollars"] > 0
    assert st["reserved"] == 0 and st["differences"] == []


def test_an_agent_at_another_effort_is_reported_as_a_difference(tmp_path):
    root, out = repo(tmp_path)
    start(out)
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root, fixture="two-models-at-max.jsonl"))
    [d] = [d for d in spend.state(out)["differences"] if d["setting"] == "effort"]
    assert d["step"] == "lead_check" and d["expected"] == "high" and d["ran"] == ["max"]


def test_unknown_cost_counts_at_its_steps_per_packet_estimate(tmp_path):
    root, out = repo(tmp_path)
    start(out, per_packet={s: 2.5 for s in presets.STEPS})
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root, fixture="unknown-model.jsonl"))
    st = spend.state(out)
    assert st["recorded"] == pytest.approx(2.5) and st["unknown"] == ["a1"]


def test_other_agent_types_and_unbound_sessions_add_nothing(tmp_path):
    root, out = repo(tmp_path)
    start(out)
    assert spend.on_pre_tool_use(pre_payload(root, agent="Explore")) is None
    spend.on_pre_tool_use(pre_payload(root))  # binds the run to sess-A
    spend.on_subagent_stop(stop_payload(root, agent="general-purpose", aid="x"))
    spend.on_subagent_stop(stop_payload(root, session="sess-B", aid="y"))
    assert spend.state(out)["agents"] == []


def test_with_no_open_run_the_hooks_do_nothing(tmp_path):
    root, out = repo(tmp_path)
    assert spend.on_pre_tool_use(pre_payload(root)) is None
    assert spend.on_subagent_stop(stop_payload(root)) is None
    assert not (out / "runs").exists()


def test_records_written_together_both_survive(tmp_path):
    root, out = repo(tmp_path)
    start(out, ceiling=100)
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root, aid="a1"))
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root, aid="a2"))
    spend.on_subagent_stop(stop_payload(root, aid="a3"))
    assert sorted(a["agent_id"] for a in spend.state(out)["agents"]) == ["a1", "a2", "a3"]


def test_a_damaged_header_is_set_aside(tmp_path):
    root, out = repo(tmp_path)
    (out / "runs").mkdir(parents=True)
    (out / "runs" / "runs.json").write_text("{broken")
    run = start(out)
    assert run["status"] == "open"
    assert list((out / "runs").glob("runs.json.damaged*"))


# --- the dispatch check -------------------------------------------------------

def test_dispatch_past_the_ceiling_is_refused_and_names_it(tmp_path):
    root, out = repo(tmp_path)
    start(out, ceiling=1.6, per_packet={s: 1.5 for s in presets.STEPS})
    assert not denied(spend.on_pre_tool_use(pre_payload(root)))
    spend.on_subagent_stop(stop_payload(root))  # $0.15 spent: 0.15 + 1.50 passes 1.60
    got = spend.on_pre_tool_use(pre_payload(root))
    assert denied(got) and "$1.60" in got["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_raise_lets_the_next_dispatch_through(tmp_path):
    root, out = repo(tmp_path)
    start(out, ceiling=1.6, per_packet={s: 1.5 for s in presets.STEPS})
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root))
    assert denied(spend.on_pre_tool_use(pre_payload(root)))
    spend.raise_ceiling(out, 10.0)
    assert not denied(spend.on_pre_tool_use(pre_payload(root)))


def test_reservations_fill_the_room_with_no_agent_finished(tmp_path):
    root, out = repo(tmp_path)
    start(out, ceiling=5.0, per_packet={s: 1.0 for s in presets.STEPS})
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root, aid="first"))  # the step's first packet is done
    results = [denied(spend.on_pre_tool_use(pre_payload(root))) for _ in range(10)]
    assert results.count(False) >= 1 and results[-1] is True
    spend.on_subagent_stop(stop_payload(root, aid="second"))
    assert spend.state(out)["reserved"] < sum(1 for r in results if not r)


def test_a_steps_second_agent_waits_for_the_first_record(tmp_path):
    root, out = repo(tmp_path)
    start(out, ceiling=100)
    assert not denied(spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer")))
    got = spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer"))
    assert denied(got) and "first" in got["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_plugin_prefixed_agent_type_counts(tmp_path):
    root, out = repo(tmp_path)
    start(out, ceiling=100)
    spend.on_pre_tool_use(pre_payload(root, agent="seams:seam-reviewer"))
    assert spend.state(out)["reserved"] > 0


# --- the commands --------------------------------------------------------

def test_run_and_spend_commands_print_json(tmp_path, capsys):
    root, out = repo(tmp_path)
    start(out, ceiling=7.5)
    capsys.readouterr()
    assert cli.main(["spend", "--root", str(root), "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["ceiling"] == 7.5 and st["over"] is False
    assert cli.main(["run", "raise", "--root", str(root), "--to", "12"]) == 0
    assert cli.main(["run", "finish", "--root", str(root)]) == 0
    assert spend.last_finished(out)["fingerprint"] == presets.fingerprint("standard")


# --- the plugin's hook commands, run as Claude Code runs them -------------------

ROOT = Path(__file__).resolve().parents[1]


def _hook_command(event):
    doc = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    return doc["hooks"][event][0]["hooks"][0]["command"]


def _run_hook(event, payload, plugin_root=ROOT):
    import os
    import subprocess
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)}
    env.pop("PYTHONPATH", None)
    return subprocess.run(["bash", "-c", _hook_command(event)], input=json.dumps(payload), env=env,
                          capture_output=True, text=True, timeout=30)


def test_the_hook_commands_record_and_refuse_from_the_plugins_own_code(tmp_path):
    root, out = repo(tmp_path)
    start(out, ceiling=0.45, per_packet={s: 0.4 for s in presets.STEPS})
    first = _run_hook("PreToolUse", pre_payload(root))
    assert first.returncode == 0 and first.stdout == ""
    stop = _run_hook("SubagentStop", stop_payload(root))
    assert stop.returncode == 0
    # The child process prices the agent with the real table: $0.09, so 0.40 more passes 0.45.
    refused = _run_hook("PreToolUse", pre_payload(root))
    assert json.loads(refused.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert len(spend.state(out)["agents"]) == 1


def test_a_hook_with_no_plugin_code_exits_quietly(tmp_path):
    got = _run_hook("SubagentStop", stop_payload(tmp_path), plugin_root=tmp_path / "nowhere")
    assert got.returncode == 0 and got.stdout == ""


def test_a_one_hour_cache_write_costs_more_than_a_five_minute_one(tmp_path):
    def line(split):
        return json.dumps({"type": "assistant", "effort": "high", "message": {
            "id": "m", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 0, "cache_creation": split}}})
    five, hour = tmp_path / "5m.jsonl", tmp_path / "1h.jsonl"
    five.write_text(line({"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 0}))
    hour.write_text(line({"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1_000_000}))
    assert spend.transcript_cost(five)["dollars"] == pytest.approx(3.75)
    assert spend.transcript_cost(hour)["dollars"] == pytest.approx(6.0)


@pytest.mark.parametrize("flock", [True, False], ids=["flock", "lock-file"])
def test_starts_at_the_same_moment_still_let_only_the_first_through(tmp_path, monkeypatch, flock):
    # Agents started in one message get their hooks run side by side. A pause between reading the
    # record and writing the reservation makes the race certain without a lock.
    import threading
    import time
    if not flock:  # Windows has no flock: the lock is a file made with O_EXCL
        monkeypatch.setattr(spend, "fcntl", None)
    root, out = repo(tmp_path)
    start(out, ceiling=100)
    real_bound = spend._bound
    monkeypatch.setattr(spend, "_bound", lambda *a, **k: (time.sleep(0.05), real_bound(*a, **k))[1])
    results, gate = [], threading.Barrier(8)

    def go():
        gate.wait()
        results.append(denied(spend.on_pre_tool_use(pre_payload(root))))

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(False) == 1


def test_the_hook_ignores_a_seams_package_in_the_repo(tmp_path):
    # A hook runs from inside the target repo. A seams/ folder there must not be imported.
    root, out = repo(tmp_path)
    (root / "seams").mkdir()
    (root / "seams" / "__init__.py").write_text("")
    (root / "seams" / "spend.py").write_text("import pathlib; pathlib.Path('HIJACKED').write_text('x')\n")
    (root / "json.py").write_text("import pathlib; pathlib.Path('HIJACKED').write_text('x')\n")
    start(out)
    import os
    import subprocess
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    got = subprocess.run(["bash", "-c", _hook_command("PreToolUse")], input=json.dumps(pre_payload(root)),
                         env=env, cwd=root, capture_output=True, text=True, timeout=30)
    assert got.returncode == 0 and not (root / "HIJACKED").exists()
    assert spend.state(out)["reserved"] > 0


def test_an_unmeasured_step_reserves_a_share_of_the_ceiling(tmp_path, capsys):
    import shutil
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "tests" / "fixtures" / "toy-repo", root)
    (root / "seams.json").unlink(missing_ok=True)
    assert cli.main(["scan", "--root", str(root)]) == 0
    capsys.readouterr()
    assert cli.main(["run", "start", "--root", str(root), "--preset", "standard", "--set", "lead_check.model=haiku",
                     "--ceiling", "20", "--json"]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["per_packet"]["lead_check"] > 0


def test_a_start_is_refused_when_the_record_stays_locked(tmp_path, monkeypatch):
    # Failing open here would let a start through unchecked.
    import contextlib
    root, out = repo(tmp_path)
    start(out)

    @contextlib.contextmanager
    def stuck(folder, **k):
        raise TimeoutError("the run record stayed locked")
        yield

    monkeypatch.setattr(spend, "_locked", stuck)
    assert denied(spend.on_pre_tool_use(pre_payload(root)))


def test_a_finished_agent_is_recorded_even_when_the_record_stays_locked(tmp_path, monkeypatch):
    import contextlib
    root, out = repo(tmp_path)
    start(out)
    spend.on_pre_tool_use(pre_payload(root))

    @contextlib.contextmanager
    def stuck(folder, **k):
        raise TimeoutError("the run record stayed locked")
        yield

    monkeypatch.setattr(spend, "_locked", stuck)
    spend.on_subagent_stop(stop_payload(root))
    st = spend.state(out)
    assert len(st["agents"]) == 1 and st["reserved"] > 0  # the reservation stays: stop early, not late


def test_a_lock_held_by_another_process_waits_and_is_never_broken(tmp_path):
    import subprocess
    import sys
    folder = tmp_path / "run"
    folder.mkdir()
    holder = subprocess.Popen([sys.executable, "-c", (
        "import sys, time; sys.path.insert(0, sys.argv[1]); from seams import spend; from pathlib import Path\n"
        "with spend._locked(Path(sys.argv[2])):\n    print('held', flush=True); time.sleep(1.5)"),
        str(ROOT / "src"), str(folder)], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    with pytest.raises(TimeoutError):
        with spend._locked(folder, wait=0.3):
            pass
    holder.wait(timeout=10)
    with spend._locked(folder, wait=2):  # free once the holder is gone
        pass


def test_a_lock_file_left_by_a_dead_hook_is_taken_over(tmp_path, monkeypatch):
    import os
    import time
    monkeypatch.setattr(spend, "fcntl", None)
    folder = tmp_path / "run"
    folder.mkdir()
    (folder / ".lock").write_text("dead-hook")
    old = time.time() - 120
    os.utime(folder / ".lock", (old, old))
    with spend._locked(folder, wait=1):
        assert (folder / ".lock").read_text() != "dead-hook"
    assert not (folder / ".lock").exists()


# --- review fixes: each one a way a run could pass its ceiling unseen -----------------

def _transcript(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(x) for x in lines))
    return path


def _line(mid, model, out_tokens, effort="high"):
    return {"type": "assistant", "effort": effort, "message": {"id": mid, "model": model, "usage": {
        "input_tokens": 0, "output_tokens": out_tokens, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}


def test_a_claude_code_notice_in_a_transcript_keeps_the_real_cost(tmp_path):
    # A "Login expired" or API error notice is written as model "<synthetic>" with no usage.
    path = _transcript(tmp_path, "t.jsonl", [_line("m1", "claude-sonnet-5-5", 200_000),
                                             _line("m2", "<synthetic>", 0)])
    got = spend.transcript_cost(path)
    assert got["dollars"] == pytest.approx(3.0) and got["unpriced"] == [] and got["models"] == ["claude-sonnet-5-5"]


def _stop_with(tmp_path, root, aid, dollars_out, agent="seam-reviewer", model="claude-sonnet-5-5"):
    path = _transcript(tmp_path, f"{aid}.jsonl", [_line(aid, model, dollars_out, effort="max")])
    payload = stop_payload(root, agent=agent, aid=aid)
    payload["agent_transcript_path"] = str(path)
    spend.on_subagent_stop(payload)


def test_an_over_cost_first_packet_raises_the_rest_of_the_steps_reservations(tmp_path):
    root, out = subrepo(tmp_path, "r")
    start(out, ceiling=10.0, per_packet={s: 1.0 for s in presets.STEPS})
    assert not denied(spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer")))
    _stop_with(tmp_path, root, "first", 200_000)  # $3.00 at the test price, against a $1.00 estimate
    got = [denied(spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer"))) for _ in range(5)]
    assert got == [False, False, True, True, True]  # 3 spent + 3 + 3 = 9; one more would pass 10
    assert spend.state(out)["reserved"] == pytest.approx(6.0)


def test_a_step_with_a_zero_estimate_reserves_its_first_agents_real_cost(tmp_path):
    root, out = subrepo(tmp_path, "r")
    start(out, ceiling=10.0, per_packet={**{s: 1.0 for s in presets.STEPS}, "drift_check": 0.0})
    spend.on_pre_tool_use(pre_payload(root, agent="seam-drift-checker"))
    _stop_with(tmp_path, root, "first", 200_000, agent="seam-drift-checker")
    got = [denied(spend.on_pre_tool_use(pre_payload(root, agent="seam-drift-checker"))) for _ in range(4)]
    assert got == [False, False, True, True]


def test_an_agent_on_another_model_is_reported_as_a_difference(tmp_path):
    root, out = subrepo(tmp_path, "r")
    start(out, ceiling=100)
    spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer"))
    _stop_with(tmp_path, root, "a1", 1000, model="claude-opus-5-5")  # standard reviews on Sonnet
    [d] = spend.state(out)["differences"]
    assert d["setting"] == "model" and d["expected"] == "claude-sonnet-5-5" and d["ran"] == ["claude-opus-5-5"]


def test_finish_waits_for_running_agents(tmp_path):
    root, out = repo(tmp_path)
    start(out)
    spend.on_pre_tool_use(pre_payload(root))
    with pytest.raises(ValueError, match="still running"):
        spend.finish(out)
    assert spend.open_run(out) is not None


def test_a_stop_counts_running_agents_and_still_records_them(tmp_path):
    root, out = subrepo(tmp_path, "r")
    start(out, per_packet={s: 1.0 for s in presets.STEPS})
    spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer"))
    st = spend.finish(out, "stopped")
    assert st["status"] == "stopped" and spend.last_finished(out)["actual"] == pytest.approx(1.0)
    _stop_with(tmp_path, root, "late", 200_000)  # it ends after the stop, at $3.00
    run = spend.last_finished(out)
    st = spend.state(out, run)
    assert [a["agent_id"] for a in st["agents"]] == ["late"] and st["recorded"] == pytest.approx(3.0)
    assert st["reserved"] == 0


def test_the_stop_command_closes_the_run_as_stopped(tmp_path, capsys):
    root, out = repo(tmp_path)
    start(out)
    spend.on_pre_tool_use(pre_payload(root))
    assert cli.main(["run", "finish", "--root", str(root)]) == 2
    assert cli.main(["run", "stop", "--root", str(root)]) == 0
    assert "stopped" in capsys.readouterr().out and spend.last_finished(out)["status"] == "stopped"


def test_a_start_from_another_session_is_not_charged_to_the_run(tmp_path):
    root, out = repo(tmp_path)
    start(out)
    spend.on_pre_tool_use(pre_payload(root, session="sess-A"))  # binds the run
    assert spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer", session="sess-B")) is None
    assert spend.state(out)["reserved"] == pytest.approx(1.0)


@pytest.mark.parametrize("bad_id", ["ABSOLUTE", "../../../outside"])
def test_a_planted_run_record_cannot_send_the_hooks_outside_the_record(tmp_path, bad_id):
    # A target repo can commit its own .seams-scan/runs/runs.json. Only an id `start` writes names a folder.
    root, out = subrepo(tmp_path, "repo")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "session.json").write_text('{"keep": "me"}')
    run_id = str(victim) if bad_id == "ABSOLUTE" else bad_id
    (out / "runs").mkdir(parents=True)
    (out / "runs" / "runs.json").write_text(json.dumps({"runs": [
        {"id": run_id, "status": "open", "ceiling": 1e6, "per_packet": {"review": 0.01}, "settings": {}}]}))
    assert spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer")) is None
    assert spend.on_subagent_stop(stop_payload(root, agent="seam-reviewer")) is None
    assert sorted(p.name for p in victim.iterdir()) == ["session.json"]
    assert (victim / "session.json").read_text() == '{"keep": "me"}'
    assert not (tmp_path / "outside").exists()


def test_an_agent_id_that_is_not_a_plain_name_does_not_name_the_file(tmp_path):
    root, out = repo(tmp_path)
    start(out)
    spend.on_pre_tool_use(pre_payload(root))
    spend.on_subagent_stop(stop_payload(root, aid="../../escape"))
    [a] = spend.state(out)["agents"]
    assert "/" not in a["agent_id"] and not (tmp_path / "escape.json").exists()


@pytest.mark.parametrize("level", ["run folder", "runs", ".seams-scan"])
def test_a_symlinked_run_record_cannot_send_the_hooks_outside_the_record(tmp_path, level):
    # A valid run id, but the repo committed a symlink at one level of the record.
    root, out = subrepo(tmp_path, "repo")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "session.json").write_text('{"keep": "me"}')
    run_id = "20261120-000000-abcdef"
    record = json.dumps({"runs": [{"id": run_id, "status": "open", "ceiling": 1e6,
                                   "per_packet": {"review": 0.01}, "settings": {}}]})
    if level == "run folder":
        (out / "runs").mkdir(parents=True)
        (out / "runs" / "runs.json").write_text(record)
        (out / "runs" / run_id).symlink_to(victim)
    elif level == "runs":
        (victim / "runs.json").write_text(record)
        out.mkdir()
        (out / "runs").symlink_to(victim)
        (victim / run_id).mkdir()
    else:
        (victim / "runs").mkdir()
        (victim / "runs" / "runs.json").write_text(record)
        out.symlink_to(victim)
    before = sorted(str(p.relative_to(victim)) for p in victim.rglob("*"))
    assert spend.on_pre_tool_use(pre_payload(root, agent="seam-reviewer")) is None
    assert spend.on_subagent_stop(stop_payload(root, agent="seam-reviewer")) is None
    assert sorted(str(p.relative_to(victim)) for p in victim.rglob("*")) == before
    assert (victim / "session.json").read_text() == '{"keep": "me"}'


def test_a_first_review_with_no_registry_yet_is_still_held_and_recorded(tmp_path):
    # A first review starts its agents before seams.json exists. The run record alone finds the run.
    root, out = tmp_path, tmp_path / ".seams-scan"
    start(out, ceiling=1.6, per_packet={s: 1.5 for s in presets.STEPS})
    sub = root / "src"
    sub.mkdir()
    assert not denied(spend.on_pre_tool_use(pre_payload(sub)))  # the session may work in a subfolder
    spend.on_subagent_stop(stop_payload(sub))
    assert len(spend.state(out)["agents"]) == 1
    assert denied(spend.on_pre_tool_use(pre_payload(root)))
