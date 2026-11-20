"""Check that a benchmark session stayed blind.

    python3 bench/blindscan.py WORKDIR NAME [--show]

Reads the transcripts of the session in WORKDIR/NAME (its main transcript and every subagent's) and
lists each tool call that touched a forbidden place, and each that may have used the network.
Forbidden: the full-history clone, the answer key and every other folder in WORKDIR except the blind
clone and the frozen tool's skills and agents; the tool's miss library; your seamreg checkout; your home
folder; other Claude Code transcripts. Exit code 0 when clean, 1 when anything needs a look.

A hit is not always a leak: read each one. --show prints each hit's call with the start of what it
returned, so you can see what the session saw. Writes its report to WORKDIR/NAME/blindscan.txt.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# A network tool used as a command: after whitespace, a quote, a backtick, {, ;, &, |, ( or $(, so
# wrapped calls (bash -c "curl ...", xargs curl, timeout 5 gh ...) still count. A name followed by =, :,
# (, , or ) is a variable or a key (const gh = ...), not a call, and is left out. False alarms cost a
# look; a missed call costs a leak.
NET = re.compile(r"(?:^|(?<=[\s'\"`{;&|(]))(curl|wget|gh|nc|ssh|scp)\s+(?![=:(,)])"
                 r"|git\s+(?:-[Cc]\s+\S+\s+)*(fetch|pull|clone|ls-remote|remote\s+add|submodule\s+update)"
                 r"|pip3? install|uv (add|pip install)|npm (install|view)|npx |yarn add|go get "
                 r"|urllib|requests\.(get|post|put|head)|http\.client|socket\.|\bfetch\(|https?://")
# A path that climbs out of where the session works, such as ../key/key.md or blind/../full. Every one
# needs a look, because the session starts in the blind clone, next to the folders it must not read.
CLIMB = re.compile(r"(?<![\w.~])\.\.(?![\w.])")
# Changing file modes, owners or attributes could undo the lock session.sh puts on the other folders.
# Matched as a whole word anywhere, so /usr/bin/chmod, os.chmod, fs.chownSync and perl chmod all count.
PERMS = re.compile(r"\b(chmod|chown|chgrp|lchown|fchmod|lchmod|fchown)(?:Sync)?\b|\b(setfacl|chattr|icacls|takeown)\b"
                   r"|\binstall\s+-m")
ALLOWED_IN_WORK = (r"blind(?:/|\b)", r"tool/skills", r"tool/agents", r"tool(?![/\w.-])")


def transcripts(session_id, home=None):
    base = Path(home or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    found = []
    for main in base.glob(f"*/{session_id}.jsonl"):
        found.append(main)
        found.extend(sorted((main.parent / session_id).glob("**/*.jsonl")))
    return found


def forbidden_pattern(work, checkout, name=None, home=None):
    work = re.escape(str(work).rstrip("/"))
    allowed = list(ALLOWED_IN_WORK) + ([re.escape(name) + r"/tmp(?:/|\b)"] if name else [])
    parts = [
        rf"{work}/(?!(?:{'|'.join(allowed)}))",         # anything in WORKDIR but the allowed places
        rf"{work}/?(?=$|[\s'\";|&)])",                       # WORKDIR itself, such as ls WORKDIR
        r"/catalog/", r"\.claude/projects/",           # the miss library, other transcripts
    ]
    if checkout:
        parts.append(re.escape(str(checkout).rstrip("/")) + r"(/|\b)")
    if home and not str(work).startswith(str(home).rstrip("/") + "/"):
        parts += [re.escape(str(home).rstrip("/")) + r"(/|\b)", r"(^|[\s\"'=(])~/", r"\$HOME\b"]
    return re.compile("|".join(parts))


def results_by_id(files):
    out = {}
    for f in files:
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                m = json.loads(line)
            except ValueError:
                continue
            for c in (m.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                    out[c.get("tool_use_id")] = str(body)
    return out


def scan(files, forbid, show=False):
    calls, hits, net = 0, [], []
    seen = results_by_id(files) if show else {}
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
                # Check the raw values too: in the JSON text a newline after .. reads as \n.
                raw = "\n".join(str(v) for v in (c.get("input") or {}).values() if isinstance(v, str))
                if forbid.search(text) or CLIMB.search(raw) or PERMS.search(raw):
                    hits.append((f"{c.get('name')}: {text[:200]}",
                                 seen.get(c.get("id"), "(no result)")[:400].replace("\n", " | ") if show else None))
                if c.get("name") in ("Bash", "PowerShell"):
                    cmd = (c.get("input") or {}).get("command", "")
                    mm = NET.search(cmd)  # one entry per command, however many forms it matches
                    if mm:
                        net.append(cmd[max(0, mm.start() - 60):mm.end() + 40])
    return calls, hits, net


def main(argv):
    show = "--show" in argv
    argv = [a for a in argv if a != "--show"]
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
    calls, hits, net = scan(files, forbidden_pattern(work, checkout, name, Path.home()), show)
    lines = [f"{name}: {len(files)} transcripts, {calls} tool calls, forbidden {len(hits)}, network {len(net)}"]
    lines += [f"  FORBIDDEN? {h}" for h, _ in hits] + [f"  NETWORK? {n!r}" for n in net]
    # The saved report holds the calls only. What a call returned can hold file contents, so --show
    # prints it to the screen and never into blindscan.txt, which is submitted.
    (work / name / "blindscan.txt").write_text("\n".join(lines) + "\n")
    print(lines[0])
    for (h, seen_text) in hits:
        print(f"  FORBIDDEN? {h}")
        if seen_text is not None:
            print(f"      returned: {seen_text}")
    for n in net:
        print(f"  NETWORK? {n!r}")
    print(f"Read {work / name / 'blindscan.txt'} before you submit it: it quotes the flagged commands.")
    return 1 if hits or net else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
