"""Which repo files earlier reviewers actually opened, from Claude Code session transcripts.

    seams looked-at --root . TRANSCRIPT_DIR_OR_FILE ...    writes <out>/looked-at.json

A pass is assigned areas, but a reviewer reads selectively. The open pass is told where nobody
looked, and this is how it knows. Each transcript line holds the agent's tool calls; a file
counts as read when a Read call names it or a Bash command names it (cat, sed, head and the
like, found the way the Bash hook finds them), and as searched when a Grep or Glob call points
at it or at its folder. Subagent transcripts (a reviewer started by the session) are read too.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from seams import check


def _jsonl_files(sources):
    for s in sources:
        p = Path(s)
        if p.is_dir():
            yield from sorted(p.rglob("*.jsonl"))
        elif p.suffix == ".jsonl":
            yield p


def _rel(path, root, prefixes):
    """Repo-relative form of a path an agent used, or None when it is outside the repo."""
    if not path:
        return None
    for pre in prefixes:
        if path.startswith(pre.rstrip("/") + "/"):
            path = path[len(pre.rstrip("/")) + 1:]
            break
    return check.relative(path, root)


def collect(root, sources, prefixes=(), passes=()):
    """{"read": {path: count}, "searched": {folder or path: count}, "transcripts": n, "passes": [...]}.
    `passes` names the passes those sessions ran, for a repo whose passes predate the ledger."""
    root = Path(root).resolve()
    prefixes = [str(root)] + list(prefixes)
    read, searched, n = collections.Counter(), collections.Counter(), 0
    for f in _jsonl_files(sources):
        n += 1
        for line in f.open(encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            for c in (d.get("message") or {}).get("content") or []:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                name, inp = c.get("name"), c.get("input") or {}
                if name == "Read":
                    r = _rel(inp.get("file_path"), root, prefixes)
                    if r and (root / r).is_file():
                        read[r] += 1
                elif name in ("Grep", "Glob"):
                    r = _rel(inp.get("path") or "", root, prefixes)
                    if r:
                        searched[r] += 1
                elif name == "Bash":
                    cmd = inp.get("command") or ""
                    for pre in prefixes:  # absolute paths in a command: make them relative first
                        cmd = cmd.replace(pre.rstrip("/") + "/", "")
                    for r in check.bash_paths(cmd, root, root):
                        read[r] += 1
    return {"read": dict(read), "searched": dict(searched), "transcripts": n, "passes": list(passes)}


def summary(doc, code_lines, depth=2, top=25):
    """Folders (to `depth`) by code lines, with the share of their files anyone read: the
    biggest folders nobody opened first. `code_lines` is {path: lines} for the repo's code."""
    read = set(doc.get("read") or {})
    folders = collections.defaultdict(lambda: [0, 0, 0, 0])  # lines, files, read files, read lines
    for p, n in code_lines.items():
        parts = p.split("/")
        key = "/".join(parts[:min(depth, len(parts) - 1)]) or "(root files)"
        f = folders[key]
        f[0] += n
        f[1] += 1
        if p in read:
            f[2] += 1
            f[3] += n
    rows = sorted(folders.items(), key=lambda kv: (kv[1][3] / kv[1][0] if kv[1][0] else 1, -kv[1][0]))
    return [{"folder": k, "code_lines": v[0], "files": v[1], "files_read": v[2],
             "share_read": round(v[3] / v[0], 2) if v[0] else 0} for k, v in rows[:top]]
