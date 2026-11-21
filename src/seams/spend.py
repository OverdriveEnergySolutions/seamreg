"""The run record and real spend for a paid seamreg run.

`seams run start` opens a run with its preset, settings and estimate. Two plugin hooks then watch it:

- Before each seamreg agent starts (PreToolUse on the Agent tool), the hook refuses the start unless
  the Agent call names the model and the effort the run's settings give its step. The refusal names
  both, so the session can start the agent again with them. An allowed start is marked as running.
- When a seamreg agent finishes (SubagentStop), its transcript gives what it really cost, with
  each message counted once, and the model and effort it ran at.

Spend is recorded and reported against the estimate, never capped: some repos need more than any
estimate, and a cap would stop a run half done.

A target repo can commit its own .seams-scan, run record included. So `seams run start` also writes
the run's id, preset and settings to a marker outside the repo, in this user's state folder. The hooks
act only on the run that marker names, check starts against the marker's own copy of the settings, and
stop checking once `finish` or `stop` closes the marker. A planted or edited record sets no model, no
effort and no text in a refusal.

Everything lives under .seams-scan/runs/. Each record is its own file, written to a temporary
name and renamed, so agents that finish together cannot overwrite each other. Only the parent
session's agents count: the first allowed start binds the run to that session.

The plugin's hooks run this file by its path, `python3 -I <plugin>/src/seams/spend.py <event>`: a hook
starts inside the target repo, and isolated mode keeps that repo's files off the import path. The hooks
never fail a session: any error leaves the call allowed and the record unchanged.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the plugin's own src, nothing else

from seams import check, presets

RUNS = "runs"
HEADER = "runs.json"
# The only run ids and agent ids that name a folder or a file. A record in the target repo is not
# trusted: an id like "../x" or "/x" would send the hooks' writes outside the record folder.
RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
AGENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
STEP_OF = {agent: step for step, agent in presets.AGENT.items()}


class OpenRun(Exception):
    def __init__(self, state):
        super().__init__("a run is still open")
        self.state = state


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _write(path, data):
    """Write JSON to a temporary name, then rename it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


try:
    import fcntl  # POSIX: the OS drops the lock when its holder dies, so no lock is ever broken by age
except ImportError:  # Windows
    fcntl = None


@contextlib.contextmanager
def _locked(folder, wait=8.0, stale=60.0):
    """One hook at a time per run. Agents started in one message get their hooks run side by side,
    and only the first may bind the run to its session. Raises TimeoutError after `wait` seconds."""
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / ".lock"
    deadline = time.monotonic() + wait
    if fcntl is not None:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise TimeoutError("the run record stayed locked")
                    time.sleep(0.02)
            yield
        finally:
            os.close(fd)  # closing releases the lock
        return
    # Without flock: a lock file holding its owner's token. A lock older than `stale` belongs to a hook
    # that died. It is moved aside under a unique name first, so two waiters cannot both break it.
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, token.encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    aside = lock.with_name(f".lock.stale-{uuid.uuid4().hex}")
                    os.replace(lock, aside)
                    aside.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError("the run record stayed locked")
            time.sleep(0.02)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            if lock.read_text() == token:
                lock.unlink()


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- what a transcript cost --------------------------------------------------

_PARTS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


def _parts(u):
    """Token counts in the price table's order. A cache write is 5-minute unless the usage
    splits out 1-hour writes, which cost more."""
    n = lambda v: int(v or 0)
    written = n(u.get("cache_creation_input_tokens"))
    split = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    hour = n(split.get("ephemeral_1h_input_tokens"))
    return (n(u.get("input_tokens")), n(u.get("output_tokens")), max(written - hour, 0), hour,
            n(u.get("cache_read_input_tokens")))


def transcript_cost(path):
    """Dollars, models and efforts of one agent's transcript. A response written as several lines
    repeats one usage under one message id, so each id counts once (its last line wins)."""
    usage, model_of, efforts = {}, {}, set()
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"dollars": None, "messages": 0, "models": [], "efforts": [], "unpriced": [], "tokens": {}}
    for line in lines:
        if '"usage"' not in line:  # most lines are tool results and prompts: skip them unparsed
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") if isinstance(d, dict) else None
        if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
            continue
        if not any(_parts(m["usage"])):  # Claude Code's own notices (model "<synthetic>") cost nothing
            continue
        key = m.get("id") or d.get("requestId") or f"line{len(usage)}"
        usage[key] = m["usage"]
        model_of[key] = m.get("model") or "unknown"
        if d.get("effort"):
            efforts.add(d["effort"])
    parts = {k: _parts(u) for k, u in usage.items()}
    tokens = {f: sum(p[i] for p in parts.values()) for i, f in enumerate(_PARTS)}
    unpriced = sorted({model_of[k] for k in usage if model_of[k] not in presets.PRICES})
    dollars = None
    if usage and not unpriced:
        dollars = sum(sum(n * price for n, price in zip(parts[k], presets.PRICES[model_of[k]])) / 1e6
                      for k in usage)
    return {"dollars": dollars, "messages": len(usage), "models": sorted(set(model_of.values())),
            "efforts": sorted(efforts), "unpriced": unpriced, "tokens": tokens}


# --- the record ----------------------------------------------------------

def _dir(out):
    return Path(out) / RUNS


def _header(out):
    """The header, or a fresh one. A damaged header is set aside, with a warning."""
    path = _dir(out) / HEADER
    if not path.exists():
        return {"runs": []}
    data = _read(path)
    if isinstance(data, dict) and isinstance(data.get("runs"), list):
        return data
    aside = path.with_name(f"{HEADER}.damaged-{datetime.datetime.now():%Y%m%d%H%M%S}")
    os.replace(path, aside)
    print(f"seams: the run record was damaged; set aside as {aside.name}", file=sys.stderr)
    return {"runs": []}


def _last(head):
    """The last run, when `start` wrote it. Any other record is ignored."""
    runs = head["runs"]
    run = runs[-1] if runs else None
    return run if isinstance(run, dict) and RUN_ID.fullmatch(str(run.get("id"))) else None


def _open_of(head):
    run = _last(head)
    return run if run and run.get("status") == "open" else None


def open_run(out):
    return _open_of(_header(out))


def last_finished(out):
    for run in reversed(_header(out)["runs"]):
        if run.get("status") in ("finished", "stopped"):
            return run
    return None


def _marker(out):
    """This user's marker for the record at `out`, outside any repo: the id of the run `start` opened."""
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    key = hashlib.sha256(str(Path(out).resolve()).encode()).hexdigest()[:32]
    return base / "seamreg" / "runs" / f"{key}.json"


def _trusted(out, run, open_only=True):
    """The run as this user's own `seams run start` opened it here, with the preset and settings taken
    from the marker, not from the record in the repo. None when the marker does not name this run, or
    (with open_only) when the run was closed."""
    if run is None:
        return None
    mark = _read(_marker(out))
    if not isinstance(mark, dict) or mark.get("run") != run.get("id"):
        return None
    if open_only and mark.get("status") != "open":
        return None
    return {**run, "preset": mark.get("preset"), "settings": mark.get("settings") or {}}


def start(out, settings, estimate, per_packet):
    """Open a run. Refuses while another is open, carrying that run's state."""
    head = _header(out)
    if _open_of(head):
        raise OpenRun(state(out))
    run = {"id": datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
           "status": "open", "started": _now(), "preset": settings["preset"],
           "fingerprint": settings["fingerprint"], "settings": presets.plain(settings),
           "sources": {s: {k: v["source"] for k, v in f.items()} for s, f in settings["steps"].items()},
           "estimate": estimate, "per_packet": per_packet}
    head["runs"].append(run)
    _write(_dir(out) / HEADER, head)
    _write(_marker(out), {"run": run["id"], "record": str(Path(out).resolve()), "started": run["started"],
                          "status": "open", "preset": run["preset"], "settings": run["settings"]})
    return run


def _update_open(out, **fields):
    head = _header(out)
    run = _open_of(head)
    if run is None:
        raise ValueError("no run is open. Start one with `seams run start`.")
    run.update(fields)
    _write(_dir(out) / HEADER, head)
    return run


def finish(out, status="finished"):
    """Close the run. A finish waits for every agent. A stop closes with agents still running, and
    each one's real cost is still recorded when it ends."""
    run = open_run(out)
    if run is None:
        raise ValueError("no run is open. Start one with `seams run start`.")
    st = state(out, run)
    running = len(_files(out, run, "start"))
    if running and status == "finished":
        raise ValueError(f"{running} agent(s) of run {run['id']} are still running. Wait for them to finish, "
                         "or close the run now with `seams run stop`.")
    closed = _update_open(out, status=status, ended=_now(), actual=st["recorded"], running=running)
    mark = _read(_marker(out))
    if isinstance(mark, dict) and mark.get("run") == run["id"]:
        _write(_marker(out), {**mark, "status": status})
    return state(out, closed)


def _files(out, run, prefix):
    folder = _dir(out) / run["id"]
    return [d for d in (_read(p) for p in sorted(folder.glob(f"{prefix}-*.json"))) if isinstance(d, dict)]


def state(out, run=None):
    """Recorded spend against the estimate, agents still running, each agent, and model and effort
    differences."""
    run = run or open_run(out)
    if run is None:
        return {"run": None}
    agents = _files(out, run, "agent")
    running = len(_files(out, run, "start"))
    recorded = sum(a["counted"] for a in agents)
    diffs = []
    for a in agents:
        want = run["settings"].get(a["step"], {})
        effort, model = want.get("effort"), presets.MODEL_IDS.get(want.get("model"))
        if effort and a["efforts"] and a["efforts"] != [effort]:
            diffs.append({"agent_id": a["agent_id"], "step": a["step"], "setting": "effort",
                          "expected": effort, "ran": a["efforts"]})
        if model and a["models"] and a["models"] != [model]:
            diffs.append({"agent_id": a["agent_id"], "step": a["step"], "setting": "model",
                          "expected": model, "ran": a["models"]})
    session = _read(_dir(out) / run["id"] / "session.json") or {}
    return {"run": run["id"], "preset": run["preset"], "status": run["status"], "session": session.get("id"),
            "estimate": run["estimate"], "recorded": round(recorded, 4), "running": running,
            "over_estimate": run["estimate"] is not None and recorded > run["estimate"],
            "agents": agents, "unknown": [a["agent_id"] for a in agents if a["dollars"] is None],
            "differences": diffs}


# --- the hooks -----------------------------------------------------------

def _step(agent_type):
    """seam-reviewer, or seams:seam-reviewer as a plugin names it, to its step."""
    return STEP_OF.get(str(agent_type or "").rsplit(":", 1)[-1])


def _out_for(payload):
    """The run record's folder: the nearest folder at or above the session's working folder that
    holds a run record or seams.json. A first review has a run record before it has seams.json."""
    start_dir = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    for d in (start_dir, *start_dir.parents):
        if (d / ".seams-scan" / RUNS / HEADER).is_file() or (d / check.REGISTRY).is_file():
            return d / ".seams-scan"
    return None


def _hook_folder(out, run):
    """The run's folder, for the hooks to write in, or None. A target repo can commit its own
    .seams-scan, so a symlink at any level of the record (or out of the repo) is refused: the
    hooks then write nothing."""
    folder = _dir(out) / run["id"]
    for level in (Path(out), _dir(out), folder):
        if level.is_symlink():
            return None
    real = Path(out).resolve()
    if folder.exists() and folder.resolve().parent != real / RUNS:
        return None
    return folder


def _bound(folder, session_id):
    """Bind the run to the session of its first allowed start. Called under the run's lock."""
    _write(folder / "session.json", {"id": session_id, "bound": _now()})


def _deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def on_pre_tool_use(payload):
    """Refuse a seamreg agent that does not name its step's model and effort. None means allow."""
    if payload.get("tool_name") not in ("Agent", "Task"):
        return None
    tool_input = payload.get("tool_input") or {}
    step = _step(tool_input.get("subagent_type"))
    if not step:
        return None
    out = _out_for(payload)
    run = _trusted(out, open_run(out)) if out else None
    folder = _hook_folder(out, run) if run else None
    if folder is None:
        return None
    session = (_read(folder / "session.json") or {}).get("id")
    if session is not None and session != payload.get("session_id"):
        return None
    wrong = mismatch(run, step, tool_input)
    if wrong:
        return _deny(wrong)
    try:
        with _locked(folder):
            if (_read(folder / "session.json") or {}).get("id") is None:
                _bound(folder, payload.get("session_id"))
            _write(folder / f"start-{uuid.uuid4().hex}.json", {"step": step, "at": _now()})
    except TimeoutError:
        return _deny("seams: the run record is busy, so this start cannot be recorded. "
                     "Wait a moment and start the agent again.")
    return None


def _model_names(alias):
    return {alias, presets.MODEL_IDS.get(alias)} - {None}


def mismatch(run, step, tool_input, env=None):
    """Why this Agent call does not run at its step's settings, or None when it does. The model may be
    named by its alias or its full id. CLAUDE_CODE_EFFORT_LEVEL would override the call's effort."""
    env = os.environ if env is None else env
    want = (run.get("settings") or {}).get(step) or {}
    model, effort = want.get("model"), want.get("effort")
    # Only known values reach the refusal text, so the record cannot put words in it.
    if model not in check.MODELS or effort not in check.EFFORTS or run.get("preset") not in check.PRESETS:
        return None
    got_model, got_effort = tool_input.get("model"), tool_input.get("effort")
    wrong = []
    if model and str(got_model or "") not in _model_names(model):
        wrong.append(f"model {got_model!r}" if got_model else "no model")
    if effort and str(got_effort or "") != effort:
        wrong.append(f"effort {got_effort!r}" if got_effort else "no effort")
    override = env.get("CLAUDE_CODE_EFFORT_LEVEL")
    if not wrong and effort and override and override != effort:
        return (f"seams: CLAUDE_CODE_EFFORT_LEVEL={override} overrides the effort on every agent, and this "
                f"run's {presets.STEP_TEXT[step]} needs effort {effort!r}. Tell the user. The run cannot keep its "
                "preset until Claude Code is restarted without that variable.")
    if not wrong:
        return None
    return (f"seams: this {presets.STEP_TEXT[step]} agent must start with model {model!r} and effort {effort!r}, "
            f"the {run['preset']} preset's settings for this step, but the call gave {' and '.join(wrong)}. "
            "Start it again with both set on the Agent call.")


def on_subagent_stop(payload):
    """Record a finished seamreg agent, and mark one of its step's starts as ended."""
    step = _step(payload.get("agent_type"))
    if not step:
        return None
    out = _out_for(payload)
    run = _trusted(out, _recording(out), open_only=False) if out else None
    folder = _hook_folder(out, run) if run else None
    if folder is None:
        return None
    session = (_read(folder / "session.json") or {}).get("id")
    if session is None or session != payload.get("session_id"):
        return None
    cost = transcript_cost(payload.get("agent_transcript_path") or "")
    try:
        with _locked(folder):
            _record(folder, run, step, payload, cost)
    except TimeoutError:
        # Keep the record. The start stays marked as running, so `seams run finish` asks for a stop.
        _record(folder, run, step, payload, cost, release=False)
    return None


def _recording(out):
    """The run a finishing agent belongs to: the open run, or a run stopped while agents still ran."""
    run = _last(_header(out))
    if run and (run.get("status") == "open" or (run.get("status") == "stopped" and run.get("running"))):
        return run
    return None


def _record(folder, run, step, payload, cost, release=True):
    per = float(run["per_packet"].get(step) or 0)
    aid = str(payload.get("agent_id") or "")
    aid = aid if AGENT_ID.fullmatch(aid) else uuid.uuid4().hex
    record = {"agent_id": aid, "step": step, "agent_type": payload.get("agent_type"), "at": _now(),
              "dollars": cost["dollars"], "counted": cost["dollars"] if cost["dollars"] is not None else per,
              "models": cost["models"], "efforts": cost["efforts"], "tokens": cost["tokens"],
              "unpriced": cost["unpriced"]}
    _write(folder / f"agent-{aid}.json", record)
    for res in sorted(folder.glob("start-*.json")) if release else ():
        r = _read(res)
        if isinstance(r, dict) and r.get("step") == step:
            try:
                res.unlink()
            except FileNotFoundError:
                continue
            break


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        handler = {"pre-tool-use": on_pre_tool_use, "subagent-stop": on_subagent_stop}[argv[0]]
        result = handler(payload)
        if result:
            print(json.dumps(result))
    except Exception as e:  # a hook must never fail the session
        print(f"seams spend hook: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
