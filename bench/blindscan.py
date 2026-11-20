"""Check that a benchmark session stayed blind.

    python3 bench/blindscan.py WORKDIR NAME

Reads the transcripts of the session in WORKDIR/NAME (its main transcript and every subagent's) and
lists each tool call that touched a forbidden place, and each that may have used the network.
Forbidden: the full-history clone, the answer key and every other folder in WORKDIR except the blind
clone and the frozen tool's skills and agents; the tool's miss library; your seamreg checkout; other
Claude Code transcripts. Exit code 0 when clean, 1 when anything needs a look.

A hit is not always a leak: read each one. Writes its report to WORKDIR/NAME/blindscan.txt.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

NET = re.compile(r"(^|[;&|(\s])(curl|wget|gh|nc|ssh|scp)\s|git\s+(fetch|pull|clone|ls-remote|remote\s+add)"
                 r"|pip3? install|uv (add|pip install)|npm (install|view)|npx |yarn add|go get ")
# In WORKDIR a session may touch: the blind clone, the frozen tool's skills and agents, the tool folder
# itself as a command argument (uvx --from WORKDIR/tool seams), and its own temp folder.
ALLOWED_IN_WORK = (r"blind(?:/|\b)", r"tool/skills", r"tool/agents", r"tool(?![/\w.-])")


def transcripts(session_id, home=None):
    base = Path(home or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    found = []
    for main in base.glob(f"*/{session_id}.jsonl"):
        found.append(main)
        found.extend(sorted((main.parent / session_id).glob("**/*.jsonl")))
    return found


def forbidden_pattern(work, checkout, name=None):
    work = re.escape(str(work).rstrip("/"))
    allowed = list(ALLOWED_IN_WORK) + ([re.escape(name) + r"/tmp(?:/|\b)"] if name else [])
    parts = [
        rf"{work}/(?!(?:{'|'.join(allowed)}))",         # anything in WORKDIR but the allowed places
        r"/catalog/", r"\.claude/projects/",           # the miss library, other transcripts
    ]
    if checkout:
        parts.append(re.escape(str(checkout).rstrip("/")) + r"(/|\b)")
    return re.compile("|".join(parts))


def scan(files, forbid):
    calls, hits, net = 0, [], []
    for f in files:
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                m = json.loads(line)
            except ValueError:
                continue
            msg = m.get("message") or {}
            if m.get("type") != "assistant" or not isinstance(msg.get("content"), list):
                continue
            for c in msg["content"]:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                calls += 1
                text = json.dumps(c.get("input"))
                if c.get("name") in ("WebFetch", "WebSearch"):
                    net.append(f"{c['name']}: {text[:160]}")
                if forbid.search(text):
                    hits.append(f"{c.get('name')}: {text[:200]}")
                if c.get("name") == "Bash":
                    cmd = (c.get("input") or {}).get("command", "")
                    for mm in NET.finditer(cmd):
                        net.append(cmd[max(0, mm.start() - 60):mm.end() + 40])
    return calls, hits, net


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    work, name = Path(argv[1]).resolve(), argv[2]
    sid = (work / name / "session-id").read_text().strip()
    files = transcripts(sid)
    if not files:
        print(f"blindscan: no transcript for session {sid}", file=sys.stderr)
        return 2
    checkout = Path(__file__).resolve().parent.parent
    calls, hits, net = scan(files, forbidden_pattern(work, checkout, name))
    lines = [f"{name}: {len(files)} transcripts, {calls} tool calls, forbidden {len(hits)}, network {len(net)}"]
    lines += [f"  FORBIDDEN? {h}" for h in hits] + [f"  NETWORK? {n!r}" for n in net]
    report = "\n".join(lines) + "\n"
    (work / name / "blindscan.txt").write_text(report)
    print(report, end="")
    return 1 if hits or net else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
