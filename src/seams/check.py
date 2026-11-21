#!/usr/bin/env python3
"""Check a repo's seams registry (seams.json) against the repo.

A seam is one piece of knowledge kept in two or more files that must agree.
A tie is an automated check that fails when those copies drift. seams.json
lists each seam, its copies and its ties.

This check fails when:
  - seams.json does not match the schema (SCHEMA below),
  - two seams share an id,
  - a seam that is not a single source lists fewer than two copies,
  - a partial tie does not say which copies it covers,
  - a path is absolute, leaves the repo, or matches no file,
  - a listed symbol or test name no longer appears in its file.

A pass proves that every listed copy and tie still exists. It cannot find a
copy that nobody listed, so a pass never means the registry is complete.

It also answers a second question for a change: which seams does it touch,
and which of their copies did it leave alone? That lookup reads only
seams.json and the list of changed files, never the whole tree, so it is fast
enough for a hook on every edit.

This file uses only the standard library and imports nothing from the seams
package. `seams init` copies it into a repo unchanged, and CI runs that copy:

    python3 scripts/seams_check.py                     # check ./seams.json
    python3 scripts/seams_check.py --changed a.py b.ts # seams these files touch
    python3 scripts/seams_check.py --diff origin/main  # seams this branch touches
    python3 scripts/seams_check.py --staged            # seams this commit touches
    python3 scripts/seams_check.py --about "status"    # seams about a topic, for planning
    python3 scripts/seams_check.py --notes             # write the notes agents read
    python3 scripts/seams_check.py --hook              # Claude Code PreToolUse hook (edits and Bash)
    python3 scripts/seams_check.py --stop-hook         # Claude Code Stop hook: a copy left behind
    python3 scripts/seams_check.py --mcp               # MCP server: the lookups, for any agent
    python3 scripts/seams_check.py --schema            # print the JSON Schema

Exit codes: 0 the registry is true, 1 it is not, 2 the check could not run.
For --changed, --diff and --staged: 0, or 1 with --fail-untied when the change leaves a
copy of an untied seam alone. --hook always exits 0 and never blocks an edit.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import json
import os
import re
import stat
import sys
from pathlib import Path

__version__ = "0.3.0"

REGISTRY = "seams.json"
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
             ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache"}

# --- the schema -----------------------------------------------------------
# SCHEMA is the single source for the registry format. `--schema` prints it,
# and schema/seams.schema.json in the seams repo is that output, held equal
# by a test. The validator below implements only the keywords in SUPPORTED,
# and a test fails if SCHEMA uses any other keyword.

# Where notes can go. Per-seam files come first, then blocks in instruction files.
NOTE_MODES = ("rules", "cursor", "copilot", "claude-md", "claude-md-high", "agents-md", "agents-md-high")

KINDS = ("mirror", "contract", "vocabulary", "copied-helper", "config", "schema", "convention")
RISKS = ("high", "medium", "low")  # most severe first

_TEXT = {"type": "string", "minLength": 1}

_COPY = {
    "type": "object",
    "required": ["path"],
    "additionalProperties": False,
    "properties": {
        "path": {**_TEXT, "description": "Repo-relative path with forward slashes. "
                 "May be a glob: * and ? stay inside one folder, ** spans folders."},
        "symbol": {"type": "string", "minLength": 3,
                   "description": "Text that must appear in the file: a function, "
                   "constant or section name. Prefer it to a line number, which goes stale."},
        "note": _TEXT,
    },
}

_TIE = {
    "type": "object",
    "required": ["path", "covers"],
    "additionalProperties": False,
    "properties": {
        "path": {**_TEXT, "description": "The test file, CI config or script that fails on drift."},
        "test": {**_TEXT, "description": "Test name or CI step name. It must appear in the file."},
        "covers": {"enum": ["all", "partial"]},
        "note": {**_TEXT, "description": "Required when covers is partial: which copies it checks."},
    },
}

_DRIFT = {
    "type": ["object", "null"],
    "required": ["text", "source"],
    "additionalProperties": False,
    "properties": {
        "text": {**_TEXT, "description": "What differs now, with path:line on each side."},
        "source": {"enum": ["reading", "confirmed"],
                   "description": "reading: found by reading the code. confirmed: "
                   "seen at runtime or checked by hand. Treat reading as a lead, not a bug."},
        "seen": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
    },
}

_SEAM = {
    "type": "object",
    "required": ["id", "title", "kind", "must_agree", "copies", "consequence", "risk"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": r"^[a-z0-9]+(-[a-z0-9]+)*$",
               "description": "Stable kebab-case slug. Do not rename it: other tools key on it."},
        "title": _TEXT,
        "kind": {"enum": list(KINDS)},
        "must_agree": {**_TEXT, "description": "One sentence: what must stay the same."},
        "copies": {"type": "array", "minItems": 1, "items": _COPY},
        "consequence": {**_TEXT, "description": "What goes wrong when one copy changes alone."},
        "intentional_differences": {"type": ["string", "null"],
                                    "description": "Deliberate differences, so nobody 'fixes' them."},
        "single_source": {"type": "boolean",
                          "description": "True when one shared module now holds the knowledge "
                          "and the copies listed are what remains outside it."},
        "ties": {"type": "array", "items": _TIE},
        "risk": {"enum": list(RISKS)},
        "suggested_tie": {"type": ["string", "null"],
                          "description": "The cheapest check that would catch drift. "
                          "Add it with the next fix to this seam."},
        "drift": _DRIFT,
        "sensitive": {"type": ["string", "null"],
                      "description": "Where private detail lives (a private issue, say). "
                      "Never the detail itself."},
    },
}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Seams registry",
    "description": "Pieces of knowledge kept in two or more files that must agree, "
                   "and the automated checks (ties) that fail when they drift.",
    "type": "object",
    "required": ["schema_version", "seams"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "notes": {"anyOf": [{"type": "string", "enum": list(NOTE_MODES)},
                            {"type": "array", "minItems": 1,
                             "items": {"type": "string", "enum": list(NOTE_MODES)}}],
                  "description": "Where `seams_check.py --notes` puts a note for each seam. One value, "
                  "or a list for a repo that more than one kind of agent works in. rules: one "
                  ".claude/rules/seams/<id>.md per seam, which Claude Code loads when an agent reads a "
                  "copy. cursor: one .cursor/rules/seams/<id>.mdc per seam, attached when a copy is in "
                  "context. copilot: one .github/instructions/seams-<id>.instructions.md per seam, "
                  "applied to its copies. claude-md and agents-md: a block in the nearest CLAUDE.md or "
                  "AGENTS.md, high and medium risk only. claude-md-high and agents-md-high: the same "
                  "block with high risk only. Leave it out for no notes."},
        "seams": {"type": "array", "items": _SEAM},
    },
}

# --- saved settings --------------------------------------------------------
# A team's saved preset lives in its own file, never in seams.json: a team's CI runs
# its own copy of this checker, and an older copy rejects any new field in seams.json.
# This file holds the names and allowed values. seams/presets.py holds what each
# preset runs; nothing else states a preset's values.

SETTINGS = "seams.settings.json"
PRESETS = ("standard", "all-in")
STEPS = ("review", "drift_check", "lead_check", "rerate")
MODELS = ("sonnet", "opus", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DIFF_LIMITS = (5, 10, 15, 20, 25, 30, 40, 50, 75, 100)  # percent of a full run on the same preset

_STEP_SETTINGS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "model": {"type": "string", "enum": list(MODELS)},
        "effort": {"type": "string", "enum": list(EFFORTS)},
    },
}

SETTINGS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Seams settings",
    "description": "The preset a team saved for paid seamreg runs, and only the settings it changed. "
                   "A newer seamreg's definition of the preset applies to everything not listed here.",
    "type": "object",
    "required": ["schema_version", "preset"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "preset": {"type": "string", "enum": list(PRESETS),
                   "description": "standard or all-in. `seams presets` shows what each one runs."},
        "changes": {"type": "object", "additionalProperties": False,
                    "properties": {step: _STEP_SETTINGS for step in STEPS},
                    "description": "Per step, the model or effort the team set by hand."},
        "diff_limit_percent": {"type": "integer", "enum": list(DIFF_LIMITS),
                               "description": "A diff scan runs without asking while its estimate stays "
                               "under this share of a full run on the same preset. Default 25."},
    },
}


def settings_errors(root):
    """Problems with <root>/seams.settings.json. No file means no problems."""
    path = Path(root) / SETTINGS
    if not path.is_file():
        return []
    try:
        data = load(path)
    except json.JSONDecodeError as e:
        return [f"{SETTINGS}: not valid JSON at line {e.lineno}, column {e.colno}: {e.msg}"]
    except DuplicateKey as e:
        return [f"{SETTINGS}: {e}"]
    except UnicodeDecodeError:
        return [f"{SETTINGS}: not UTF-8 text. Save it as UTF-8."]
    errors = []
    validate(data, SETTINGS_SCHEMA, SETTINGS, errors)
    return errors


SUPPORTED = {"$schema", "title", "description", "type", "required", "additionalProperties",
             "properties", "items", "enum", "const", "minLength", "minItems", "pattern", "anyOf"}

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def _type_name(v):
    for name, test in _TYPES.items():
        if test(v):
            return name
    return type(v).__name__


def _same(a, b):
    """JSON equality: true is not 1."""
    return type(a) is type(b) and a == b


def validate(node, schema, where, errors):
    """Append one message per schema violation found at or below `node`."""
    if "anyOf" in schema:
        tried = []
        for branch in schema["anyOf"]:
            errs = []
            validate(node, branch, where, errs)
            if not errs:
                break
            tried.append(errs)
        else:
            # Report the branch whose type fits the value: "must be one of ..." for a
            # string, the bad item for a list. Only when none fits, list every type.
            fits = [e for e in tried if not any(x.startswith(f"{where}: expected ") for x in e)]
            if fits:
                errors.extend(fits[0])
            else:
                types = [b.get("type") for b in schema["anyOf"]]
                errors.append(f"{where}: expected {' or '.join(map(str, types))}, got {_type_name(node)}")
    types = schema.get("type")
    if types is not None:
        types = types if isinstance(types, list) else [types]
        if not any(_TYPES[t](node) for t in types):
            errors.append(f"{where}: expected {' or '.join(types)}, got {_type_name(node)}")
            return
    if "const" in schema and not _same(node, schema["const"]):
        errors.append(f"{where}: must be {json.dumps(schema['const'])}, got {json.dumps(node)}")
    if "enum" in schema and not any(_same(node, e) for e in schema["enum"]):
        errors.append(f"{where}: must be one of {', '.join(map(str, schema['enum']))}, "
                      f"got {json.dumps(node)}")
    if isinstance(node, str):
        if len(node.strip()) < schema.get("minLength", 0):
            errors.append(f"{where}: needs at least {schema['minLength']} non-space characters")
        if "pattern" in schema and ("\n" in node or not re.search(schema["pattern"], node)):
            errors.append(f"{where}: {json.dumps(node)} does not match {schema['pattern']}")
    if isinstance(node, list):
        if len(node) < schema.get("minItems", 0):
            errors.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(node):
                validate(item, schema["items"], f"{where}[{i}]", errors)
    if isinstance(node, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in node:
                errors.append(f"{where}: missing required field '{key}'")
        for key, value in node.items():
            if key in props:
                validate(value, props[key], f"{where}.{key}", errors)
            elif schema.get("additionalProperties", True) is False:
                errors.append(f"{where}: unknown field '{key}'")


# --- the repo side --------------------------------------------------------

def path_problem(p):
    """Why `p` cannot name a file inside the repo, or None."""
    if not p.strip():
        return "is empty"
    if "\\" in p:
        return "uses a backslash; use forward slashes"
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        return "is absolute; use a path relative to the repo root"
    if any(c in p for c in "\n\r\t\0"):
        return "holds a control character"
    parts = p.split("/")
    if ".." in parts:
        return "leaves the repo ('..')"
    if any(s in ("", ".") for s in parts):
        return "is not in plain form: write it like 'dir/file.py', with no './', '//' or trailing '/'"
    return None


def _is_glob(p):
    # Brackets alone are literal, so a deleted app/[id]/page.tsx cannot fall back
    # to matching app/d/page.tsx. Inside a glob with * or ?, [...] is a class.
    return "*" in p or "?" in p


def _glob_match(parts, segs):
    if not parts:
        return not segs
    if parts[0] == "**":
        return any(_glob_match(parts[1:], segs[i:]) for i in range(len(segs) + 1))
    return bool(segs) and fnmatch.fnmatchcase(segs[0], parts[0]) and _glob_match(parts[1:], segs[1:])


class Repo:
    """Files under `root`, read lazily and at most once."""

    def __init__(self, root):
        self.root = Path(root)
        self._files = None
        self._text = {}

    @property
    def real_root(self):
        return Path(os.path.realpath(self.root))

    def inside(self, full):
        """True when `full`, after following every link, is inside the repo."""
        try:
            Path(os.path.realpath(full)).relative_to(self.real_root)
            return True
        except ValueError:
            return False

    def files(self):
        """Every regular file in the repo, by its path in the repo. A folder link is
        followed once when it stays inside the repo, so a cycle cannot loop. A link
        that leads outside the repo, a FIFO or a socket is left out."""
        if self._files is None:
            found, seen = [], set()
            for here, dirs, names in os.walk(self.root, followlinks=True):
                real = os.path.realpath(here)
                if real in seen or not self.inside(here):
                    dirs[:] = []
                    continue
                seen.add(real)
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                rel = Path(here).relative_to(self.root).as_posix()
                for n in sorted(names):
                    full = os.path.join(here, n)
                    try:
                        regular = stat.S_ISREG(os.stat(full).st_mode)
                    except OSError:
                        continue
                    if regular and self.inside(full):
                        found.append(n if rel == "." else f"{rel}/{n}")
            self._files = found
        return self._files

    def is_regular(self, rel):
        full = self.root / rel
        try:
            return stat.S_ISREG(os.stat(full).st_mode) and self.inside(full)
        except OSError:
            return False

    def resolve(self, p):
        """Repo-relative files that `p` names, or a reason it names none."""
        problem = path_problem(p)
        if problem:
            return [], problem
        full = self.root / p
        if full.exists() and not self.inside(full):
            return [], "leads outside the repo through a link"
        if self.is_regular(p):
            return [p], None
        if _is_glob(p):
            parts = [s for s in p.split("/") if s not in ("", ".")]
            hits = [f for f in self.files() if _glob_match(parts, f.split("/"))]
            return hits, (None if hits else "matches no file")
        if full.is_dir():
            return [], f"is a folder; name a file, or use a glob like '{p}/**/*'"
        if not full.is_file():
            return [], "does not exist"
        return [p], None

    def raw(self, rel):
        """The file's bytes, or None when it is not a regular file inside the repo."""
        if not self.is_regular(rel):
            return None  # never read a FIFO (it would block) or a file outside the repo.
            # files() already leaves both out; this guard is a second layer.
        try:
            return (self.root / rel).read_bytes()
        except OSError:
            return None

    def text(self, rel):
        """Text for searching: undecodable bytes become U+FFFD. Never write this back."""
        if rel not in self._text:
            raw = self.raw(rel)
            self._text[rel] = "" if raw is None else raw.decode("utf-8", "replace")
        return self._text[rel]

    def contains(self, files, needle):
        return any(needle in self.text(f) for f in files)

    def has_test(self, files, name):
        """A tie's test name is in the file. Class.method counts when the method is."""
        return self.contains(files, name) or ("." in name and self.contains(files, name.rsplit(".", 1)[-1]))


def check(data, root):
    """All problems with registry `data` for the repo at `root`. Empty means true."""
    errors = []
    validate(data, SCHEMA, "seams.json", errors)
    if errors:
        return errors  # the checks below assume the shape is right
    errors += [f"seams.json: notes: {e}" for e in note_conflicts(data)]

    repo = Repo(root)
    seen = {}
    for i, seam in enumerate(data["seams"]):
        sid = seam["id"]
        at = f"seam '{sid}'"
        if sid in seen:
            errors.append(f"{at}: id also used by seams[{seen[sid]}]")
        seen.setdefault(sid, i)

        if not seam.get("single_source", False) and len(seam["copies"]) < 2:
            errors.append(f"{at}: lists one copy. A seam needs two or more, "
                          "unless single_source is true")

        for j, copy in enumerate(seam["copies"]):
            files, problem = repo.resolve(copy["path"])
            if problem:
                errors.append(f"{at}: copies[{j}].path '{copy['path']}' {problem}")
            elif "symbol" in copy and not repo.contains(files, copy["symbol"]):
                errors.append(f"{at}: copies[{j}].symbol '{copy['symbol']}' "
                              f"no longer appears in '{copy['path']}'")

        for j, tie in enumerate(seam.get("ties", [])):
            if tie["covers"] == "partial" and "note" not in tie:
                errors.append(f"{at}: ties[{j}] covers partial, so its note must say which copies")
            files, problem = repo.resolve(tie["path"])
            if problem:
                errors.append(f"{at}: ties[{j}].path '{tie['path']}' {problem}")
            elif "test" in tie and not repo.has_test(files, tie["test"]):
                errors.append(f"{at}: ties[{j}].test '{tie['test']}' "
                              f"no longer appears in '{tie['path']}'")
    return errors


class DuplicateKey(ValueError):
    pass


def _no_duplicate_keys(pairs):
    # json.loads keeps the last of two equal keys and drops the first without a
    # word. In a registry that silently deletes a seam's copies or ties.
    out = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKey(f"key '{key}' appears twice in one object")
        out[key] = value
    return out


def load(path):
    """Parse a registry file, refusing duplicate keys. Accepts a UTF-8 byte-order mark.
    Raises UnicodeDecodeError for a file that is not UTF-8."""
    return json.loads(Path(path).read_bytes().decode("utf-8-sig"), object_pairs_hook=_no_duplicate_keys)


# --- the lookup: which seams a change touches ---------------------------

def copy_matches(pattern, path):
    """True when copy path `pattern` (a path or a glob) names repo file `path`.
    Matches on the text alone, so it works for deleted files and never walks the tree."""
    if pattern == path:
        return True  # a literal name wins: Next.js folders like [id] are not globs
    return _is_glob(pattern) and _glob_match([s for s in pattern.split("/") if s not in ("", ".")],
                                             path.split("/"))


def relative(path, root):
    """Repo-relative forward-slash form of `path`, or None when it is outside `root`."""
    p = Path(path.replace("\\", "/"))
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(Path(root).resolve())
        except ValueError:
            return None
    rel = p.as_posix()
    while rel.startswith("./"):
        rel = rel[2:]
    return None if path_problem(rel) else rel


def lookup(data, changed):
    """[(seam, copies changed, copies not changed)] for each seam a changed file is a copy in."""
    out = []
    for seam in data["seams"]:
        hit = [c["path"] for c in seam["copies"] if any(copy_matches(c["path"], f) for f in changed)]
        if hit:
            out.append((seam, hit, [c["path"] for c in seam["copies"] if c["path"] not in hit]))
    return out


def fully_tied(seam):
    return any(t["covers"] == "all" for t in seam.get("ties", []))


def describe(seam, hit, rest, editing=False, label=None):
    label = label or ("editing" if editing else "changed")
    lines = [f"seam '{seam['id']}' (risk {seam['risk']}): {seam['title']}",
             f"  must agree: {seam['must_agree']}",
             f"  {label}: {', '.join(hit)}"]
    if rest:
        lines.append(f"  {'other copies' if editing else 'not changed'}: {', '.join(rest)}")
    if seam.get("intentional_differences"):
        lines.append(f"  deliberate differences: {seam['intentional_differences']}")
    if seam.get("drift"):
        # The copies already differ. An agent about to edit one should know before it "fixes" the wrong side.
        d = seam["drift"]
        lines.append(f"  known drift ({d['source']}" + (f", {d['seen']}" if d.get("seen") else "")
                     + f"): {d['text']}")
    for tie in seam.get("ties", []):
        name = f" ({tie['test']})" if "test" in tie else ""
        lines.append(f"  tie: {tie['path']}{name}, covers {tie['covers']}")
    if not fully_tied(seam):
        lines.append("  no full tie: nothing fails if these copies drift. Update every copy. "
                     "A tie is welcome but never a reason to leave a copy stale.")
    return "\n".join(lines)


# --- the pull request comment ------------------------------------------------
# --markdown prints one comment body. The CI snippet posts it and, on the next push,
# edits the comment that starts with COMMENT_MARKER instead of adding a second one.
COMMENT_MARKER = "<!-- seams-pr-comment -->"
COMMENT_CLEAR = "<!-- seams-pr-comment: none -->"  # nothing to report: edit an old comment, post no new one
COMMENT_LIMIT = 60000  # GitHub refuses a comment over 65,536 characters


def _md_plain(s):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"@(?=\w)", "@&#8203;", s)


def _md_text(s):
    """Registry text, safe in a comment: no raw HTML, and no @mention that notifies anyone.
    A code span shows its text as it is (no HTML, no mentions), so it stays untouched:
    an entity there would show as "&lt;"."""
    out, pos = [], 0
    s = str(s)
    for m in re.finditer(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", s, re.S):
        out += [_md_plain(s[pos:m.start()]), m.group(0)]
        pos = m.end()
    return "".join(out + [_md_plain(s[pos:])])


def _md_path(p):
    # A code span that holds a backtick needs a longer fence (CommonMark).
    fence = "`" * (max((len(m) for m in re.findall(r"`+", p)), default=0) + 1)
    pad = " " if p.startswith("`") or p.endswith("`") else ""
    return f"{fence}{pad}{p}{pad}{fence}"


def _md_seam(seam, hit, rest):
    lines = [f"**{_md_path(seam['id'])}** (risk {seam['risk']}): {_md_text(seam['title'])}",
             f"- Must agree: {_md_text(seam['must_agree'])}",
             f"- Changed: {', '.join(_md_path(p) for p in hit)}",
             f"- **Not changed:** {', '.join(_md_path(p) for p in rest)}"]
    if seam.get("intentional_differences"):
        lines.append(f"- Deliberate differences: {_md_text(seam['intentional_differences'])}")
    if seam.get("drift"):
        lines.append(f"- Known drift ({_md_text(seam['drift']['source'])}): {_md_text(seam['drift']['text'])}")
    for tie in seam.get("ties", []):
        name = f" ({_md_path(tie['test'])})" if "test" in tie else ""
        lines.append(f"- Tie: {_md_path(tie['path'])}{name}, covers {tie['covers']}")
    if not fully_tied(seam):
        lines.append("- No full tie: nothing fails if these copies drift.")
    return "\n".join(lines)


def markdown_report(partial, n_changed, rerun):
    """The pull request comment for `partial` [(seam, hit, rest)], highest risk first."""
    if not partial:
        return "\n".join([COMMENT_MARKER, COMMENT_CLEAR, "### seams: no copy left behind", "",
                          f"This pull request changes {n_changed} file(s). "
                          "No seam has a copy left behind now.", ""])
    order = sorted(partial, key=lambda f: RISKS.index(f[0]["risk"]))
    untied = sum(not fully_tied(s) for s, _, _ in partial)
    head = [COMMENT_MARKER, f"### seams: {len(partial)} seam(s) with a copy not changed", "",
            "This pull request changes one copy of each seam below and not the others. "
            "Read each copy not changed. If it still agrees, no action is needed. "
            "If a copy is stale, fix it in this change. A tie (a test that fails when the copies disagree) is "
            "a good follow-up, not a condition for the fix. "
            f"{untied} of these seams have no full tie.", ""]
    body, shown = [], 0
    for f in order:
        part = _md_seam(*f)
        if len("\n".join(head + body)) + len(part) > COMMENT_LIMIT - 500:
            break
        body += [part, ""]
        shown += 1
    if shown < len(order):
        body += [f"{len(order) - shown} more seam(s) do not fit in one comment. "
                 f"Run `{rerun}` to see them all.", ""]
    return "\n".join(head + body)


def about(data, text):
    """Seams whose id, title, text, paths or symbols mention `text`, ignoring case."""
    needle = text.lower()
    found = []
    for seam in data["seams"]:
        hay = [seam["id"], seam["title"], seam["must_agree"], seam["consequence"]]
        hay += [c["path"] for c in seam["copies"]] + [c.get("symbol", "") for c in seam["copies"]]
        if any(needle in h.lower() for h in hay):
            found.append(seam)
    return found


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=60)


def _git_staged(root):
    # One list for the whole commit. pre-commit can split passed file names
    # across several runs, and each run would then miss the other copies.
    run = _git(root, "diff", "--cached", "--name-only", "--relative", "-z")
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or "git diff --cached failed")
    return [l for l in run.stdout.split("\0") if l]


def _git_changed(root, ref):
    def git(*a):
        return _git(root, *a)
    base = git("merge-base", ref, "HEAD")
    if base.returncode != 0:
        raise RuntimeError(base.stderr.strip() or f"git merge-base {ref} HEAD failed")
    # merge-base to working tree. --relative: paths from the seams root, which may be
    # a subfolder of the git repo. -z: names as they are, not quoted when non-ASCII.
    diff = git("diff", "--name-only", "--relative", "-z", base.stdout.strip())
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.strip() or "git diff failed")
    return [l for l in diff.stdout.split("\0") if l]


def _show(root, rev, rel):
    """A file's text at a git revision (rev "" means the index), or None."""
    run = _git(root, "show", f"{rev}:./{rel}")
    return run.stdout if run.returncode == 0 else None


def drop_note_only(root, changed, old_rev, new_from_index):
    """Leave out files whose only change is inside a generated seams block. Without
    this, refreshing the notes in a CLAUDE.md that is itself a copy looks like an
    edit to that copy."""
    out = []
    for rel in changed:
        full = Path(root) / rel
        try:
            new = _show(root, "", rel) if new_from_index else (
                full.read_bytes().decode("utf-8") if full.is_file() else None)
        except UnicodeDecodeError:
            new = None
        if new is None or BLOCK_START not in new:
            out.append(rel)
            continue
        old = _show(root, old_rev, rel)
        if old is None or strip_block(old) != strip_block(new):
            out.append(rel)
    return out


def _find_root(start):
    for d in [start, *start.parents]:
        if (d / REGISTRY).is_file():
            return d
    return None


_SHELL_WORD = re.compile(r"[A-Za-z0-9_@+~.,/\[\]-]+")


def bash_paths(command, cwd, root, limit=400):
    """The repo files a shell command names: what it reads with cat or sed, edits with sed -i,
    or writes with a redirection. A word counts only when it is a file in the repo."""
    out = []
    for word in _SHELL_WORD.findall(command or "")[:limit]:
        word = word.rstrip(",")
        if not word or word.startswith("-") or "/" not in word and "." not in word:
            continue
        p = Path(word)
        p = p if p.is_absolute() else Path(cwd) / p
        try:
            if p.is_file():
                rel = relative(str(p), root)
                if rel and rel not in out:
                    out.append(rel)
        except OSError:
            continue
    return out


def run_hook(stdin, root=None):
    """Claude Code PreToolUse hook. Returns the JSON to print, or None. Never raises.

    An edit tool names its file. A Bash command is read for the repo files it names: an agent
    that edits with sed or reads with cat never calls Edit or Read, and would otherwise get
    neither this hook nor the notes (seen in a replay run on 2026-11-16)."""
    try:
        payload = json.loads(stdin)
        ti = payload.get("tool_input") or {}
        if payload.get("tool_name") == "Bash":
            cwd = Path(payload.get("cwd") or ".")
            root = Path(root) if root else _find_root(cwd.resolve())
            if root is None:
                return None
            data = load(root / REGISTRY)
            if validate_errors(data):
                return None
            found = lookup(data, bash_paths(ti.get("command"), cwd, root))
            if not found:
                return None
            text = ["This command reads or changes a copy of a seam: knowledge kept in more than one file that "
                    "must agree. If you change it, keep the other copies in step in this same change, or say why not."]
            text += [describe(*f, editing=True) for f in found]
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                           "additionalContext": "\n\n".join(text)}}
        target = ti.get("file_path")
        if not target:
            return None
        target = Path(target)
        if not target.is_absolute():
            target = Path(payload.get("cwd") or ".") / target
        root = Path(root) if root else _find_root(target.parent)
        if root is None:
            return None
        rel = relative(str(target), root)
        data = load(root / REGISTRY)
        if rel is None or validate_errors(data):
            return None
        found = lookup(data, [rel])
    except Exception:
        return None  # a hook must never break an edit
    if not found:
        return None
    text = ["You are editing a copy of a seam: knowledge kept in more than one file that must agree. "
            "Keep the other copies in step in this same change, or say why not."]
    text += [describe(*f, editing=True) for f in found]
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": "\n\n".join(text)}}


def run_stop_hook(stdin, root=None):
    """Claude Code Stop hook: before the agent finishes, block once when its uncommitted changes
    leave a copy of a seam unchanged, and name the copies. Never blocks twice in a row
    (stop_hook_active), and never raises."""
    try:
        payload = json.loads(stdin)
        if payload.get("stop_hook_active"):
            return None
        cwd = Path(payload.get("cwd") or ".").resolve()
        root = Path(root) if root else _find_root(cwd)
        if root is None:
            return None
        data = load(root / REGISTRY)
        bad = validate_errors(data)
        if bad:  # an edit broke the registry: say so once, since every later lookup is now silent
            return {"decision": "block", "reason": "Before you finish: seams.json no longer passes its own check, so "
                    "the hooks and notes cannot read it. Fix these, run `python3 scripts/seams_check.py --notes`, then "
                    "`python3 scripts/seams_check.py` until it says ok:\n" + "\n".join(f"- {e}" for e in bad[:10])
                    + f"\nA seam's kind is one of: {', '.join(KINDS)}."}
        base, base_ref = _branch_base(root) or ("HEAD", "<base branch>")
        raw = drop_note_only(root, _worktree_changes(root, base), base, new_from_index=False)
        changed = sorted({r for r in (relative(f, root) for f in raw) if r})
        partial = [(s, h, r) for s, h, r in lookup(data, changed) if r]
    except Exception:
        return None
    own = [c for c in changed if c != REGISTRY and not c.startswith(NOTES_DIR + "/")]
    if not own:
        return None
    text = []
    if partial:
        text += ["Before you finish: your changes touch a copy of a seam (knowledge kept in more than one file that "
                 "must agree) and leave its other copies unchanged. For each seam below, read the copies not changed. "
                 "Update each one that no longer agrees. If one must differ, say which and why in your final reply."]
        text += [describe(*f) for f in partial]
    # The ref name can come from a remote (origin/HEAD) and goes into a command the agent may run.
    safe = base_ref if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", base_ref) else "<base branch>"
    text += [RECORD_REMINDER.format(base=safe)]
    errors = check(data, root)
    if errors:  # notes left stale by an edit to seams.json, or a copy that no longer exists
        text += ["seams.json or its notes are out of date: run `python3 scripts/seams_check.py --notes`, then "
                 "`python3 scripts/seams_check.py`, and fix what it reports:\n" + "\n".join(f"- {e}" for e in errors[:10])]
    return {"decision": "block", "reason": "\n\n".join(text)}


RECORD_REMINDER = (
    "Before you finish, record what this change taught you about copies. If you found knowledge that another "
    "file must match and no seam in seams.json lists it (a list, a schema, a route and its docs, a limit and the "
    "text that states it), add that seam to seams.json now, with every copy you know of. Do this whether you "
    "updated the other copy or left it: a copy you named and left is the one the next change will miss. "
    "After you edit seams.json, run `python3 scripts/seams_check.py --notes` and then `python3 scripts/seams_check.py`. "
    "If the `seams` command is installed and this change goes to a pull request, also run "
    "`seams scan --since {base} --new` and add the real seams among its leads. If you found nothing new, "
    "finish as you were.")


# --- notes: put each seam where an agent reads it ---------------------------
# The notes are generated from seams.json, and the plain check fails when they
# are stale, so the notes cannot become a second copy that drifts.

# Per-seam note files: (folder, name prefix, name suffix) for each mode.
NOTE_FILES = {
    "rules": (".claude/rules/seams", "", ".md"),          # Claude Code: loads when a copy is read
    "cursor": (".cursor/rules/seams", "", ".mdc"),        # Cursor: attached when a copy is in context
    "copilot": (".github/instructions", "seams-", ".instructions.md"),  # Copilot: applies to its copies
}
NOTES_DIR = NOTE_FILES["rules"][0]
# When a repo ignores .claude/, these lines share the rules and the step-1 hook file and keep the
# rest ignored, at any depth. Checked with git check-ignore on 2026-11-15.
RULES_IGNORE_LINES = (".claude/*", "!.claude/rules/", "!.claude/settings.json", "*/**/.claude/")
# Blocks in instruction files: the file name and the risks each mode keeps. These files
# load widely, so low risk never goes in, and the -high modes keep only high risk.
NOTE_BLOCKS = {"claude-md": ("CLAUDE.md", ("high", "medium")), "claude-md-high": ("CLAUDE.md", ("high",)),
               "agents-md": ("AGENTS.md", ("high", "medium")), "agents-md-high": ("AGENTS.md", ("high",))}
GENERATED = ("<!-- Generated from seams.json by seams_check.py --notes. "
             "Edit seams.json, not this text. -->")
BLOCK_START = "<!-- seams:start -->"
BLOCK_END = "<!-- seams:end -->"
BLOCK_WARN_LINES = 60


def note_modes(data):
    """The notes modes `data` asks for, each once, in NOTE_MODES order."""
    want = data.get("notes") or []
    want = [want] if isinstance(want, str) else want
    return [m for m in NOTE_MODES if m in want]


def note_conflicts(data):
    """Modes that cannot go together: two blocks for the same file."""
    modes = note_modes(data)
    out = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        same = [m for m in modes if m in NOTE_BLOCKS and NOTE_BLOCKS[m][0] == name]
        if len(same) > 1:
            out.append(f"{' and '.join(same)} both write the block in {name}. Keep one")
    return out


def _note_file(mode, sid):
    folder, prefix, suffix = NOTE_FILES[mode]
    return f"{folder}/{prefix}{sid}{suffix}"


def _owned_note_file(mode, rel):
    folder, prefix, suffix = NOTE_FILES[mode]
    return rel.startswith(f"{folder}/{prefix}") and rel.endswith(suffix)


def _yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _note_body(seam):
    body = describe(seam, [c["path"] for c in seam["copies"]], [], label="copies")
    return (f"{GENERATED}\n\n"
            "The file you opened holds a copy of knowledge that other files must match. "
            "When you plan or make a change here, include the other copies, or say why they must differ.\n\n"
            f"```\n{body}\n```\n")


def _rule_text(seam, globs):
    paths = "\n".join(f"  - {_yaml_str(g)}" for g in globs)
    return f"---\npaths:\n{paths}\n---\n" + _note_body(seam)


def _cursor_text(seam, globs):
    # Cursor's docs give globs as one comma-separated string, written without quotes.
    description = _yaml_str(f"Seam {seam['id']}: {seam['title']}")
    return (f"---\ndescription: {description}\nglobs: {','.join(globs)}\nalwaysApply: false\n---\n"
            + _note_body(seam))


def _copilot_text(seam, globs):
    # GitHub's docs give applyTo as one quoted string, patterns separated by commas.
    return f"---\napplyTo: {_yaml_str(','.join(globs))}\n---\n" + _note_body(seam)


NOTE_TEXT = {"rules": _rule_text, "cursor": _cursor_text, "copilot": _copilot_text}


def _nearest(path, existing, name):
    # A wildcard folder never matches a real instruction-file path, so the search
    # passes it by. A literal folder named like [id] still matches.
    dirs = path.split("/")[:-1]
    for i in range(len(dirs), -1, -1):
        cand = "/".join(dirs[:i] + [name])
        if cand in existing:
            return cand
    return name


def _block(entries):
    """One line per seam, naming its copies under this CLAUDE.md and the others elsewhere."""
    by_seam = {}
    for path, seam in entries:
        by_seam.setdefault(seam["id"], (seam, []))[1].append(path)
    lines = [BLOCK_START, "## Seams", "",
             "Files below this folder hold copies of knowledge that other files must match. When you "
             "plan or make a change to one, include the other copies, or say why they must differ. "
             "Full entries are in seams.json. " + GENERATED, ""]
    for sid in sorted(by_seam):
        seam, here = by_seam[sid]
        others = [c["path"] for c in seam["copies"] if c["path"] not in here]
        also = f" Elsewhere: {', '.join(f'`{o}`' for o in others)}." if others else ""
        lines.append(f"- **{sid}** ({seam['risk']}): {seam['must_agree']} "
                     f"Here: {', '.join(f'`{h}`' for h in sorted(here))}.{also}")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def _with_block(text, block):
    """`text` with its seams block replaced by `block` (None removes it). Raises ValueError on damaged markers."""
    starts, ends = text.count(BLOCK_START), text.count(BLOCK_END)
    if starts == ends == 0:
        if block is None:
            return text
        return (text.rstrip("\n") + "\n\n" if text.strip() else "") + block + "\n"
    if starts != 1 or ends != 1 or text.index(BLOCK_START) > text.index(BLOCK_END):
        raise ValueError(f"has {starts} '{BLOCK_START}' and {ends} '{BLOCK_END}' markers in the wrong "
                         "shape. Fix them by hand: the notes writer will not guess which text is safe to replace")
    head = text[:text.index(BLOCK_START)]
    tail = text[text.index(BLOCK_END) + len(BLOCK_END):]
    if block is not None:
        return head + block + tail
    head, tail = head.rstrip("\n"), tail.lstrip("\n")
    if head and tail:
        return head + "\n\n" + tail
    return head + "\n" if head else tail


def strip_block(text):
    """`text` without a well-formed seams block, line endings made LF. Used to tell a
    note-only change from a real one."""
    text = text.replace("\r\n", "\n")
    try:
        return _with_block(text, None)
    except ValueError:
        return text


def unsafe_target(repo, rel):
    """Why writing `rel` could escape the repo, or None. Refuses any link on the way."""
    full = repo.root
    for part in rel.split("/"):
        full = full / part
        if full.is_symlink():
            return f"goes through a link at '{full.relative_to(repo.root).as_posix()}'"
    if not repo.inside(full.parent if not full.exists() else full):
        return "leads outside the repo"
    return None


def _eol(old_raw):
    return "\r\n" if old_raw and b"\r\n" in old_raw else "\n"


def _ignored(root, rel):
    try:
        return _git(root, "check-ignore", "-q", rel).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def plan_notes(data, root):
    """({repo-relative path: text, or None to delete}, [errors], [warnings]) for the notes modes in `data`.

    Only files whose content must change are listed, with the line endings the file
    already uses. A file is never written through a link, never rewritten when it is
    not UTF-8, and a note file without the generated marker is never touched. Notes
    for a mode that is no longer asked for are removed."""
    modes = note_modes(data)
    repo = Repo(root)
    files = set(repo.files())
    want, errors, warnings = {}, [], []

    def current(rel):
        """(LF text, raw bytes) of a file, ("", None) when absent. Raises UnicodeDecodeError."""
        raw = repo.raw(rel)
        return ("", None) if raw is None else (raw.decode("utf-8").replace("\r\n", "\n"), raw)

    # Per-seam note files.
    notes, owner = {}, {}
    for mode in modes:
        if mode not in NOTE_FILES:
            continue
        folder = NOTE_FILES[mode][0]
        if _ignored(root, _note_file(mode, "x")):
            hint = (". Replace the .claude line in .gitignore with these: " + ", ".join(RULES_IGNORE_LINES)
                    if mode == "rules" else "")
            warnings.append(f"{folder}/ is ignored by git here, so the {mode} notes stay on this machine. "
                            f"Un-ignore it to share them{hint}")
        for seam in data["seams"]:
            globs = [c["path"] for c in seam["copies"]]
            if mode != "rules":
                # Cursor and Copilot take one comma-separated string, so a comma in a path cannot be said.
                bad = [g for g in globs if "," in g]
                if bad:
                    warnings.append(f"seam '{seam['id']}': {mode} cannot name a path with a comma "
                                    f"({', '.join(bad)}), so its {mode} note leaves it out")
                    globs = [g for g in globs if "," not in g]
                if not globs:
                    continue
            rel = _note_file(mode, seam["id"])
            notes[rel] = NOTE_TEXT[mode](seam, globs)
            owner[rel] = seam["id"]
    for f in sorted(files):
        if f not in notes and any(_owned_note_file(m, f) for m in NOTE_FILES) and GENERATED in repo.text(f):
            problem = unsafe_target(repo, f)
            if problem:
                errors.append(f"{f}: {problem}. The notes writer will not delete it")
            else:
                want[f] = None
    for f, text in notes.items():
        problem = unsafe_target(repo, f)
        if problem:
            errors.append(f"{f}: {problem}. The notes writer will not write it")
            continue
        try:
            now, raw = current(f)
        except UnicodeDecodeError:
            errors.append(f"{f}: is not UTF-8 text. The notes writer will not rewrite it")
            continue
        if raw is not None and GENERATED not in now:
            errors.append(f"{f}: was not written by seams, so the notes writer leaves it alone. "
                          f"Rename it, or rename the seam '{owner[f]}'")
            continue
        if raw is None or now != text:
            want[f] = text.replace("\n", _eol(raw))

    # Blocks in CLAUDE.md and AGENTS.md files.
    for name in ("CLAUDE.md", "AGENTS.md"):
        mode = next((m for m in modes if m in NOTE_BLOCKS and NOTE_BLOCKS[m][0] == name), None)
        risks = NOTE_BLOCKS[mode][1] if mode else ()
        existing = {f for f in files if f.rsplit("/", 1)[-1] == name}
        blocks = {}
        for seam in data["seams"]:
            if seam["risk"] in risks:
                for c in seam["copies"]:
                    blocks.setdefault(_nearest(c["path"], existing, name), []).append((c["path"], seam))
        for f in sorted(existing | set(blocks)):
            block = _block(blocks[f]) if f in blocks else None
            if f not in blocks and ((Path(root) / f).is_symlink() or BLOCK_START not in repo.text(f)):
                # No block to write here and none to remove. A link (CLAUDE.md pointing at
                # AGENTS.md, say) shows its target's block; that block belongs to the target.
                continue
            problem = unsafe_target(repo, f)
            if problem:
                errors.append(f"{f}: {problem}. The notes writer will not write it")
                continue
            try:
                now, raw = current(f)
            except UnicodeDecodeError:
                errors.append(f"{f}: is not UTF-8 text. The notes writer will not rewrite it")
                continue
            if block and block.count("\n") > BLOCK_WARN_LINES:
                warnings.append(f"{f}: the seams block is {block.count(chr(10))} lines. Consider "
                                f"\"{name[:-3].lower()}-md-high\", or per-seam note files, which cost "
                                "nothing until a copy is opened")
            try:
                new = _with_block(now, block)
            except ValueError as e:
                errors.append(f"{f} {e}")
                continue
            if new != now:
                want[f] = new.replace("\n", _eol(raw))
    return want, errors, warnings


def note_words(data, root):
    """Words in every note this registry asks for: per-seam files and the seams blocks."""
    repo = Repo(root)
    total = 0
    for rel in repo.files():
        if any(_owned_note_file(m, rel) for m in NOTE_FILES):
            text = repo.text(rel)
            if GENERATED in text:
                total += len(text.split())
        elif rel.rsplit("/", 1)[-1] in ("CLAUDE.md", "AGENTS.md"):
            text = repo.text(rel)
            if BLOCK_START in text and BLOCK_END in text:
                total += len(text[text.index(BLOCK_START):text.index(BLOCK_END)].split())
    return total


def write_notes(root, want):
    """Write the planned notes. Bytes go out exactly as planned: no newline translation."""
    repo = Repo(root)
    for rel, text in want.items():
        if unsafe_target(repo, rel):
            continue  # plan_notes reported it; never write through a link
        full = Path(root) / rel
        if text is None:
            full.unlink()
        else:
            full.parent.mkdir(parents=True, exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)


def _notes_mode_hint(root):
    root = Path(root)
    if (root / ".claude").is_dir() and not _ignored(root, ".claude/rules/seams/x.md"):
        pick = '"notes": "rules" (recommended here: .claude/ is committed)'
    elif (root / "AGENTS.md").is_file() and not (root / "CLAUDE.md").is_file():
        pick = '"notes": "agents-md" (recommended here: the repo has AGENTS.md and no CLAUDE.md)'
    else:
        pick = '"notes": "claude-md" (recommended here: no committed .claude/ folder)'
    return (pick + ". For more than one kind of agent, give a list, such as [\"rules\", \"cursor\", "
            "\"copilot\"]. The values are " + ", ".join(NOTE_MODES))


# --- MCP server: the lookups for any agent ------------------------------------
# `--mcp` speaks the Model Context Protocol over stdio (one JSON-RPC message per line),
# so an agent that is not Claude Code, or one with no hook, can ask the registry
# directly. It reads seams.json again on every call, never writes a file, and uses
# only the standard library, like the rest of this file.

MCP_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # newest first
_FILES = {"type": "array", "items": {"type": "string"}, "minItems": 1,
          "description": "Repo-relative paths, or absolute paths inside the repo."}
MCP_TOOLS = [
    {"name": "seams_for_files",
     "description": "Before you plan or edit: the seams these files hold a copy of, what must agree, "
                    "and the other copies to keep in step in the same change.",
     "inputSchema": {"type": "object", "properties": {"files": _FILES}, "required": ["files"]}},
    {"name": "seams_about",
     "description": "Seams whose id, title, text, paths or symbols mention a topic. Use it while planning, "
                    "before you know the files.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "minLength": 1}},
                     "required": ["text"]}},
    {"name": "seams_changed",
     "description": "Before you finish: the seams the current changes touch and the copies they left alone. "
                    "With base, every change since the merge base with that ref (a branch); without it, "
                    "uncommitted and untracked changes.",
     "inputSchema": {"type": "object", "properties": {"base": {"type": "string"}}}},
    {"name": "seams_get",
     "description": "One seam's full entry by id.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "seams_check",
     "description": "Whether seams.json still matches the repo: every listed copy, symbol and tie exists.",
     "inputSchema": {"type": "object", "properties": {}}},
]
for _t in MCP_TOOLS:
    _t["annotations"] = {"readOnlyHint": True, "openWorldHint": False}


def _mcp_registry(root):
    data = load(root / REGISTRY)
    errors = validate_errors(data)
    if errors:
        raise ValueError(f"{REGISTRY} does not match the schema: {'; '.join(errors[:3])}")
    return data


def _worktree_changes(root, since="HEAD"):
    tracked = _git(root, "diff", "--name-only", "--relative", "-z", since)
    if tracked.returncode != 0:
        raise RuntimeError(tracked.stderr.strip() or f"git diff {since} failed")
    new = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return [l for l in (tracked.stdout + new.stdout).split("\0") if l]


DEFAULT_BRANCHES = ("main", "master", "trunk", "develop", "dev")


def _branch_base(root):
    """Where this branch's own work starts: the merge-base with the default branch, when HEAD is ahead
    of it. An agent that commits before it finishes (a pull request) leaves no uncommitted change, so
    the Stop hook must also see the branch's commits. None on the default branch with nothing ahead."""
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        return None
    refs = []
    sym = _git(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if sym.returncode == 0 and sym.stdout.strip():
        refs.append(sym.stdout.strip())
    refs += [b for b in DEFAULT_BRANCHES] + [f"origin/{b}" for b in DEFAULT_BRANCHES]
    for ref in refs:
        if _git(root, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}").returncode != 0:
            continue
        mb = _git(root, "merge-base", ref, "HEAD")
        if mb.returncode == 0 and mb.stdout.strip() and mb.stdout.strip() != head.stdout.strip():
            return mb.stdout.strip(), ref
        return None  # HEAD is on (or behind) the default branch: no branch work beyond the worktree
    return None


def mcp_call(root, name, arguments):
    """The text answer of one tool call. Raises ValueError for a bad call."""
    arguments = arguments or {}
    if name == "seams_check":
        errors = check(load(root / REGISTRY), root)
        return ("seams: ok. Every listed copy, symbol and tie exists." if not errors else
                "\n".join(errors + [f"seams: {len(errors)} problem(s)."]))
    data = _mcp_registry(root)
    if name == "seams_for_files":
        files = arguments.get("files")
        if not isinstance(files, list) or not files or not all(isinstance(x, str) for x in files):
            raise ValueError("files must be a list of paths")
        rel = sorted({r for r in (relative(f, root) for f in files) if r})
        found = lookup(data, rel)
        if not found:
            return (f"No seam lists these {len(rel)} file(s) as a copy. A seam nobody listed will not show up "
                    "here, so a file can still hold a copy of something.")
        return "\n\n".join(describe(*f, editing=True) for f in found)
    if name == "seams_about":
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        found = about(data, text)
        body = [describe(s, [c["path"] for c in s["copies"]], [], label="copies") for s in found]
        return "\n\n".join(body + [f"{len(found)} seam(s) mention '{text}'. A seam nobody listed will not show up here."])
    if name == "seams_changed":
        base = arguments.get("base")
        if base is not None and (not isinstance(base, str) or not base or base.startswith("-")):
            raise ValueError("base must be a git ref")
        raw = _git_changed(root, base) if base else _worktree_changes(root)
        changed = sorted({r for r in (relative(f, root) for f in raw) if r})
        partial = [(s, h, r) for s, h, r in lookup(data, changed) if r]
        if not partial:
            return f"{len(changed)} changed file(s). No seam has a copy left behind."
        return "\n\n".join([describe(*f) for f in partial] +
                            [f"This change touches {len(partial)} seam(s) and leaves other copies alone. Update "
                             "each copy not changed, or say why it must differ."])
    if name == "seams_get":
        for s in data["seams"]:
            if s["id"] == arguments.get("id"):
                return json.dumps(s, indent=2)
        raise ValueError(f"no seam with the id {arguments.get('id')!r}")
    raise ValueError(f"unknown tool {name!r}")


def mcp_handle(msg, root):
    """The reply to one JSON-RPC message, or None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "invalid request"}}
    method, mid = msg["method"], msg.get("id")
    if "id" not in msg:
        return None  # notifications/initialized and the like need no answer
    params = msg.get("params") or {}
    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in MCP_VERSIONS else MCP_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "seams", "version": __version__},
                   "instructions": "This repo keeps a seams registry (seams.json): knowledge kept in two or more "
                                   "files that must agree. Call seams_for_files on the files you plan to change, "
                                   "and seams_changed before you finish."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": MCP_TOOLS})
    if method == "tools/call":
        try:
            text = mcp_call(root, params.get("name"), params.get("arguments"))
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            return ok({"content": [{"type": "text", "text": f"seams: {e}"}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def run_mcp(stdin, stdout, root):
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            try:
                reply = mcp_handle(msg, root)
            except Exception as e:  # one bad call must not end the session
                reply = {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                         "error": {"code": -32603, "message": str(e)}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def validate_errors(data):
    errors = []
    validate(data, SCHEMA, "seams.json", errors)
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="seams_check",
        description="Fail when seams.json no longer matches the repo, or list the seams a change touches.")
    ap.add_argument("--root", help="repo root (default: current folder; for --hook, the nearest "
                    f"folder above the edited file that holds {REGISTRY})")
    ap.add_argument("--registry", help=f"registry file (default: <root>/{REGISTRY})")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--schema", action="store_true", help="print the JSON Schema and exit")
    mode.add_argument("--changed", nargs="+", metavar="FILE", help="list the seams these files touch")
    mode.add_argument("--diff", metavar="REF", help="list the seams touched since the merge base with REF")
    mode.add_argument("--staged", action="store_true", help="list the seams the staged changes touch")
    mode.add_argument("--about", metavar="TEXT", help="list the seams that mention TEXT (for planning)")
    mode.add_argument("--notes", action="store_true",
                      help="write the notes seams.json asks for (its \"notes\" setting)")
    mode.add_argument("--hook", action="store_true", help="run as a Claude Code PreToolUse hook")
    mode.add_argument("--stop-hook", action="store_true",
                      help="run as a Claude Code Stop hook: block once when a change leaves a copy behind")
    mode.add_argument("--mcp", action="store_true",
                      help="run as an MCP server on stdio: the lookups, for any agent")
    ap.add_argument("--fail-untied", action="store_true",
                    help="with --changed, --diff or --staged: exit 1 when a change leaves a copy of a seam "
                    "with no full tie unchanged")
    ap.add_argument("--markdown", action="store_true",
                    help="with --changed, --diff or --staged: print a pull request comment in Markdown "
                    "(the CI snippet posts it)")
    ap.add_argument("--version", action="version", version=f"seams_check {__version__}")
    args = ap.parse_args(argv)

    if args.schema:
        print(json.dumps(SCHEMA, indent=2))
        return 0
    if args.mcp:
        start = Path(args.root or ".").resolve()
        root = start if (start / REGISTRY).is_file() else (_find_root(start) or start)
        run_mcp(sys.stdin, sys.stdout, root)
        return 0
    if args.stop_hook:
        out = run_stop_hook(sys.stdin.read(), args.root)
        if out:
            print(json.dumps(out))
        return 0
    if args.hook:
        out = run_hook(sys.stdin.read(), args.root)
        if out:
            print(json.dumps(out))
        return 0

    root = Path(args.root or ".")
    if not root.is_dir():
        print(f"seams: root '{root}' is not a folder", file=sys.stderr)
        return 2
    reg = Path(args.registry) if args.registry else root / REGISTRY
    try:
        data = load(reg)
    except FileNotFoundError:
        print(f"seams: no registry at {reg}. Create one with `seams init`, "
              'or write {"schema_version": 1, "seams": []} to it.', file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"{reg}: not valid JSON at line {e.lineno}, column {e.colno}: {e.msg}")
        return 1
    except DuplicateKey as e:
        print(f"{reg}: {e}")
        return 1
    except UnicodeDecodeError:
        print(f"seams: {reg} is not UTF-8 text. Save it as UTF-8.", file=sys.stderr)
        return 2

    if args.notes:
        errors = check(data, root)
        if errors:
            for e in errors:
                print(e)
            print("seams: fix the registry before writing notes from it.")
            return 1
        if not data.get("notes"):
            print(f"seams: seams.json has no \"notes\" setting. Add {_notes_mode_hint(root)}.",
                  file=sys.stderr)
            return 2
        want, errors, warnings = plan_notes(data, root)
        for w in warnings:
            print(f"seams: warning: {w}", file=sys.stderr)
        for e in errors:
            print(e)  # a file with damaged markers is left out of `want`, so it is never written
        write_notes(root, want)
        for rel, text in sorted(want.items()):
            print(f"{'deleted' if text is None else 'wrote'} {rel}")
        print(f"seams: notes ({', '.join(note_modes(data))}) written. {len(want)} file(s) changed."
              + (f" {len(errors)} file(s) skipped: fix them and run --notes again." if errors else ""))
        words = note_words(data, root)
        print(f"seams: the notes hold {words} words in all. A copy written as a broad glob "
              "(docs/**/*.md) makes most files load its note.")
        return 1 if errors else 0

    if args.about:
        if validate_errors(data):
            print(f"seams: {reg} does not match the schema. Run this check without --about to see why.",
                  file=sys.stderr)
            return 2
        found = about(data, args.about)
        for seam in found:
            print(describe(seam, [c["path"] for c in seam["copies"]], [], label="copies"))
            print()
        print(f"seams: {len(found)} seam(s) mention '{args.about}'. "
              "A seam nobody listed will not show up here.")
        return 0

    if args.changed or args.diff or args.staged:
        if validate_errors(data):
            print(f"seams: {reg} does not match the schema. Run this check without "
                  "--changed, --diff or --staged to see why.", file=sys.stderr)
            return 2
        if args.changed:
            raw = args.changed
        else:
            try:
                if args.diff:
                    raw = _git_changed(root, args.diff)
                    base = _git(root, "merge-base", args.diff, "HEAD").stdout.strip()
                    raw = drop_note_only(root, raw, base, new_from_index=False)
                else:
                    raw = drop_note_only(root, _git_staged(root), "HEAD", new_from_index=True)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
                print(f"seams: cannot list the changes: {e}", file=sys.stderr)
                return 2
        changed = sorted({r for r in (relative(f, root) for f in raw) if r})
        found = lookup(data, changed)
        partial = [(s, h, r) for s, h, r in found if r]
        if args.markdown:
            me = relative(__file__, Path.cwd()) or "scripts/seams_check.py"
            rerun = f"python3 {me} " + (f"--diff {args.diff}" if args.diff else
                                                         "--staged" if args.staged else "--changed ...")
            print(markdown_report(partial, len(changed), rerun))
            untied = [s for s, _, _ in partial if not fully_tied(s)]
            return 1 if args.fail_untied and untied else 0
        if not partial:
            print(f"seams: {len(changed)} changed file(s). No seam has a copy left behind.")
            return 0
        for f in partial:
            print(describe(*f))
            print()
        untied = [s for s, _, _ in partial if not fully_tied(s)]
        print(f"seams: this change touches {len(partial)} seam(s) and leaves other copies alone. "
              f"{len(untied)} of them have no full tie.")
        return 1 if args.fail_untied and untied else 0

    errors = check(data, root) + settings_errors(root)
    if not errors and data.get("notes"):
        want, note_errors, _ = plan_notes(data, root)
        errors += note_errors
        for mode in NOTE_FILES:  # notes in an ignored folder stay on one machine; CI never sees them
            if mode in note_modes(data) and _ignored(root, _note_file(mode, "x")):
                want = {k: v for k, v in want.items() if not _owned_note_file(mode, k)}
        errors += [f"{rel}: the note is {'missing' if not (root / rel).exists() else 'out of date'}. "
                   "Run python3 scripts/seams_check.py --notes" for rel in sorted(want)]
    for e in errors:
        print(e)
    if errors:
        print(f"seams: {len(errors)} problem(s). Fix the registry or the code. "
              "A tie for a drift you fix is welcome, not required.")
        return 1
    seams = data["seams"]
    copies = sum(len(s["copies"]) for s in seams)
    ties = sum(len(s.get("ties", [])) for s in seams)
    print(f"seams: ok. {len(seams)} seams, {copies} copies and {ties} ties still exist. "
          "This proves the listed copies exist, not that the list is complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
