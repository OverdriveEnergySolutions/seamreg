"""The same name in two or more areas: functions, constants, env vars and file names.

A name match across areas is the weakest lead on its own. It matters most when it
crosses languages (parse_order in Python, parseOrder in TypeScript), because
nothing but a person keeps those two in step.
"""
from __future__ import annotations

import collections
import re

from seams.scan.inventory import Lead, is_test, kind_of

COMMON = set("""
main run get set setup teardown init start stop close open load save update delete create
handle handler parse read write render build helper wrapper log logger app router health
index default config fetch post put now to_dict from_dict validate format apply reset clear
refresh check status list items keys values copy client connect execute process request
response callback middleware constructor toString toJSON equals hashCode serialize
deserialize""".split())
MAX_AREAS = 8  # a name in more areas than this is a framework convention

_DEFS = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.M),                       # python, ruby
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)"),                                   # js, ts, php
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
    re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", re.M),                     # go
    re.compile(r"\bfn\s+([A-Za-z_]\w*)"),                                             # rust
    re.compile(r"\b(?:fun|func)\s+([A-Za-z_]\w*)"),                                   # kotlin, swift
    re.compile(r"^\s*(?:function\s+)?([A-Za-z_]\w*)\s*\(\)\s*\{", re.M),              # shell
]
_CONST = re.compile(
    r"^\s*(?:export\s+)?(?:(?:const|let|var|final|static|public|private|readonly|val)\s+)*"
    r"([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{4,})\s*(?::[^=\n]{1,60})?=(?![=>])", re.M)
_ENV_READ = re.compile(
    r"(?:environ(?:\.get)?\s*[\[(]\s*|getenv\s*\(\s*|env::var\s*\(\s*|ENV\s*\[\s*|"
    r"process\.env\[\s*)['\"]([A-Z][A-Z0-9_]{2,})['\"]|process\.env\.([A-Z][A-Z0-9_]{2,})")
_ENV_CONFIG = re.compile(
    r"\$\{([A-Z][A-Z0-9_]{2,})(?::?[-=?][^}]*)?\}|^\s*(?:export\s+|ENV\s+|-\s+)?([A-Z][A-Z0-9_]{2,})\s*[=:]",
    re.M)
COMMON_FILES = {"__init__.py", "README.md", "CLAUDE.md", "AGENTS.md", "Dockerfile", "Makefile",
                "package.json", "pyproject.toml", "conftest.py", "index.ts", "index.js",
                "index.tsx", "index.html", "main.py", "main.go", "main.rs", "main.ts", "app.py",
                "App.tsx", "utils.py", "utils.ts", "types.ts", "constants.py", "settings.py",
                "config.py", "requirements.txt", "tsconfig.json", "vite.config.ts", ".gitignore",
                "go.mod", "Cargo.toml", "lib.rs", "mod.rs", "models.py", "routes.py", "views.py",
                "compose.yml", "docker-compose.yml", ".env.example", "setup.py", "setup.cfg"}


def _norm(name):
    return name.lower().replace("_", "")


def _group(kind, found, inv, detail, min_len=0):
    """found: {key: {(path, line, spelling)}} -> leads for keys in 2..MAX_AREAS areas."""
    leads = []
    for key, hits in found.items():
        areas = {inv.area(p) for p, _, _ in hits}
        if not 2 <= len(areas) <= MAX_AREAS or len(key) < min_len:
            continue
        spellings = sorted({s for _, _, s in hits})
        first = {}
        for p, n, _ in sorted(hits):
            first.setdefault(p, n)
        locs = [(p, n, None) for p, n in sorted(first.items())]
        langs = {p.rsplit(".", 1)[-1] for p in first}
        leads.append(Lead(kind, locs, detail.format(" / ".join(spellings)),
                          score=len(areas) + (1 if len(langs) > 1 else 0)))
    return leads


def find(inv):
    defs, consts, envs = (collections.defaultdict(set) for _ in range(3))
    for path in inv.read:
        text = inv.text(path)
        kind = kind_of(path)

        def line_of(m, path=path):
            # The name's own position: a leading ^\s* can match across blank lines.
            return inv.line_at(path, m.start(m.lastindex) if m.lastindex else m.start())

        if kind == "code" and not is_test(path):
            for rx in _DEFS:
                for m in rx.finditer(text):
                    name = m.group(1)
                    if name in COMMON or name.lower().startswith("test") or len(name) < 6:
                        continue
                    defs[_norm(name)].add((path, line_of(m), name))
            for m in _CONST.finditer(text):
                consts[m.group(1)].add((path, line_of(m), m.group(1)))
        if kind == "doc":
            continue  # docs feed the marker and list detectors, not the name ones
        for m in _ENV_READ.finditer(text):
            name = m.group(1) or m.group(2)
            envs[name].add((path, line_of(m), name))
        if kind == "config" or path.endswith((".sh", ".bash")):
            for m in _ENV_CONFIG.finditer(text):
                name = m.group(1) or m.group(2)
                envs[name].add((path, line_of(m), name))

    leads = _group("same-name", defs, inv, "defined in each area: {}")
    leads += _group("same-constant", consts, inv, "constant {} in each area")
    # an env name counts only when code reads it somewhere
    read_somewhere = {k for k, hits in envs.items() if any(kind_of(p) == "code" for p, _, _ in hits)}
    leads += _group("env-name", {k: v for k, v in envs.items() if k in read_somewhere}, inv,
                    "env var {} used in each area")

    by_name = collections.defaultdict(list)
    for p in inv.read:
        name = p.rsplit("/", 1)[-1]
        if name not in COMMON_FILES and not is_test(p) and kind_of(p) != "doc":
            by_name[name].append(p)
    for name, paths in sorted(by_name.items()):
        areas = {inv.area(p) for p in paths}
        if 2 <= len(areas) <= MAX_AREAS:
            leads.append(Lead("same-file", [(p, None, None) for p in paths],
                              f"file name {name} in {len(areas)} areas", score=len(areas)))
    return leads
