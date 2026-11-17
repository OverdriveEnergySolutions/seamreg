"""Most members of a family follow a pattern, and a few do not: a convention seam.

A family is a set of things the repo builds the same way:

- the Python classes that share a base class: every SearchIndex, every PrimaryModelForm,
- the code files in one folder, or under one folder, with one extension: every query in
  src/queries/sql/,
- the code files with one name in many folders: every app's search.py.

A pattern is a name or a string that most members hold: 'comments' in 20 of 22 forms,
joinSessionQuery in 35 of the 41 query files that call filterQuery. A member without it
has a reason, or it broke the rule when the rule changed. On netbox and umami, full
reviews missed this drift in every run, because no pair of files shows it. Only the
whole family does.

The pattern can be plain (most members hold B) or conditional (most members that hold A
also hold B). A file family's pattern must be its own vocabulary: a name that every kind
of file uses (useState, getLogger) says nothing about the family.
"""
from __future__ import annotations

import collections
import keyword
import os
import re

from seams.scan.inventory import Lead, is_test, kind_of

MIN_FAMILY = 6       # members a family needs
MIN_SUPPORT = 5      # members that must hold the pattern
MIN_SHARE = 0.8      # share of the family that holds a plain pattern
COND_SHARE = 0.85    # share of the A-holders that hold B, for a conditional pattern
OWN_VOCAB = 0.5      # a file family's pattern: at least this share of the folder files that use it are members
PER_FAMILY = 5       # leads per family with a plain pattern
PER_FAMILY_CONDITIONAL = 2  # and with only a conditional one
MAX_LEADS = 250
SHOW_MISSING = 8
SHOW_FEATURES = 4

STOP = set(keyword.kwlist) | {
    "self", "cls", "None", "True", "False", "super", "args", "kwargs", "this", "null", "undefined",
}
# A name is a camelCase, snake_case or PascalCase identifier, or a quoted string. Plain words
# (count, then, nested, required) are SQL, prose and keywords far more often than conventions.
_TOKEN = re.compile(r"""(['"])([A-Za-z_][\w.\-]{1,60})\1|\b([A-Za-z_]\w{2,60})\b""")
_NAMED = re.compile(r"[a-z0-9][A-Z]|_[A-Za-z]|^[A-Z][a-z]+[A-Z]")
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")  # CSS classes in UI files
_IMPORTS = re.compile(
    r"^\s*import\s*\{[^}]*\}\s*from\s*['\"][^'\"]+['\"];?|^\s*import\b[^\n]*"
    r"|^\s*export\s*\{[^}]*\}\s*from[^\n]*"
    r"|^\s*from\s+[\w.]+\s+import\s*\([^)]*\)|^\s*from\s+[\w.]+\s+import[^\n]*"
    r"|^[^\n]*=\s*require\([^)]*\)[^\n]*", re.M)
_VUE_NOISE = re.compile(r"<template\b.*?</template>|<style\b.*?</style>", re.S)
UI_EXT = {".vue", ".svelte", ".tsx", ".jsx", ".html"}
_PY_CLASS = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", re.M)
GENERIC_BASES = {"object", "Exception", "ABC", "Protocol", "Generic", "TypedDict", "NamedTuple"}
# Files that gather or re-export the others, rather than being one more of them.
_GATHER = re.compile(r"^(?:__init__\.py|index\.\w+|types?\.\w+|constants?\.\w+|utils?\.\w+)$")


def _features(text, ext):
    if ext in (".vue", ".svelte"):
        text = _VUE_NOISE.sub("", text)
    text = _IMPORTS.sub("", text)
    out = set()
    for m in _TOKEN.finditer(text):
        if m.group(2):
            if ext in UI_EXT and _KEBAB.match(m.group(2)):
                continue
            out.add("'" + m.group(2) + "'")
        elif m.group(3) not in STOP and _NAMED.search(m.group(3)):
            out.add(m.group(3))
    return out


def _py_classes(text):
    """(line, name, first base, body) for each top-level class with a base."""
    lines = text.split("\n")
    for m in _PY_CLASS.finditer(text):
        start = text.count("\n", 0, m.start())
        end = start + 1
        while end < len(lines) and (not lines[end].strip() or lines[end][:1] in " \t"
                                    or lines[end].startswith((")", "]", "}"))):
            end += 1
        bases = [b.strip().split(".")[-1].split("[")[0] for b in m.group(2).split(",")
                 if b.strip() and "=" not in b]
        if bases and bases[0] not in GENERIC_BASES:
            yield start + 1, m.group(1), bases[0], "\n".join(lines[start + 1:end])


def _families(inv):
    """{(kind, label): [(member label, path, line, features)]}, and the document frequency
    of each feature across folder families, for the own-vocabulary test."""
    fams = collections.defaultdict(list)
    for p in inv.read:
        if is_test(p) or kind_of(p) != "code" or "/migrations/" in "/" + p:
            continue
        text, ext = inv.text(p), os.path.splitext(p)[1]
        if ext == ".py":
            for line, name, base, body in _py_classes(text):
                fams[("class", base)].append((name, p, line, _features(body, ext) - {name}))
        name = p.rsplit("/", 1)[-1]
        if _GATHER.match(name):
            continue
        feats = _features(text, ext)
        folder = os.path.dirname(p)
        fams[("folder", f"{folder}/*{ext}" if folder else f"*{ext}")].append((p, p, None, feats))
        if folder:
            up = os.path.dirname(folder)
            fams[("tree", f"{up}/**/*{ext}" if up else f"**/*{ext}")].append((p, p, None, feats))
            fams[("name", name)].append((p, p, None, feats))
    df = collections.Counter(f for (k, _), ms in fams.items() if k == "folder" for *_, fs in ms for f in fs)
    out = {}
    for key, members in fams.items():
        if len(members) >= MIN_FAMILY and len({(m[1], m[2]) for m in members}) == len(members):
            out[key] = members
    return out, df


def _patterns(members, own_vocab=None):
    """{tuple of members that break it: [(feature, holders, out of, condition)]}."""
    n = len(members)
    feats = [m[3] for m in members]
    count = collections.Counter(f for fs in feats for f in fs)
    if own_vocab is not None:
        count = collections.Counter({f: c for f, c in count.items() if c / own_vocab[f] >= OWN_VOCAB})
        feats = [fs & count.keys() for fs in feats]
    out = collections.defaultdict(list)
    for f, s in count.items():
        if s >= MIN_SUPPORT and s / n >= MIN_SHARE and s < n:
            missing = tuple(i for i, fs in enumerate(feats) if f not in fs)
            if len(missing) <= max(2, n // 5):
                out[missing].append((f, s, n, None))
    floor = max(MIN_FAMILY, n / 2 if own_vocab is not None else 0)
    for a in [f for f, s in count.items() if floor <= s < n * MIN_SHARE]:
        holders = [i for i, fs in enumerate(feats) if a in fs]
        sub = collections.Counter(f for i in holders for f in feats[i])
        for b, s in sub.items():
            if b == a or count[b] >= n * MIN_SHARE:
                continue
            if s >= MIN_SUPPORT and s / len(holders) >= COND_SHARE and s < len(holders):
                missing = tuple(i for i in holders if b not in feats[i])
                if len(missing) <= max(2, len(holders) * 15 // 100):
                    out[missing].append((b, s, len(holders), a))
    return out


def _describe(kind, label, n):
    if kind == "class":
        return f"{n} classes based on {label}"
    if kind == "name":
        return f"{n} files named {label}"
    return f"{n} files matching {label}"


def _show(f):
    return f if f.startswith("'") else f"`{f}`"


def find(inv):
    fams, df = _families(inv)
    found = {}
    for (kind, label), members in fams.items():
        for missing, pats in _patterns(members, None if kind == "class" else df).items():
            key = frozenset((members[i][1], members[i][2]) for i in missing)
            if key in found and found[key][1] >= len(members):
                continue
            found[key] = ((kind, label), len(members), members, missing, pats)

    def score(item):
        # The classic drift is one name most members hold and a few lack. A conditional
        # pattern is weaker, and a member that lacks many names is usually another kind of
        # thing, not a member that missed a change.
        (kind, _), n, _, missing, pats = item
        plain = [f for f, _, _, cond in pats if cond is None]
        names = {f for f, *_ in pats}
        # One name that several conditions agree on (joinSessionQuery in the files that have
        # filterQuery, and in those that have cohortQuery, and ...) is nearly as strong as plain.
        agreed = max(collections.Counter(f for f, _, _, cond in pats if cond).values(), default=0) >= 3
        return (2 * bool(plain) + 1.5 * (agreed and not plain) + (kind == "class")
                + 0.3 * min(sum(f.startswith("'") for f in plain), 3)
                + min(n, 60) / 60 - 0.2 * len(missing) - 0.3 * max(0, len(names) - 3))

    leads, per, per_cond = [], collections.Counter(), collections.Counter()
    for item in sorted(found.values(), key=score, reverse=True):
        (kind, label), n, members, missing, pats = item
        conditional = all(p[3] is not None for p in pats)
        pool = per_cond if conditional else per
        if pool[(kind, label)] >= (PER_FAMILY_CONDITIONAL if conditional else PER_FAMILY):
            continue
        pool[(kind, label)] += 1
        breakers = [members[i] for i in missing]
        holders = [m for i, m in enumerate(members) if i not in missing]
        locs = [(m[1], m[2], None) for m in breakers[:SHOW_MISSING]]
        locs += [(m[1], m[2], None) for m in holders[:2] if all((m[1], m[2]) != l[:2] for l in locs)]
        pats = sorted(pats, key=lambda p: (p[3] is not None, -p[1]))
        pats = [p for i, p in enumerate(pats) if p[0] not in {q[0] for q in pats[:i]}]
        said = []
        for f, s, of, cond in pats[:SHOW_FEATURES]:
            said.append(f"{_show(f)} in {s} of {of}" + (f" that have {_show(cond)}" if cond else ""))
        names = ", ".join(m[0] if kind == "class" else m[1] for m in breakers[:SHOW_MISSING])
        more = f" and {len(breakers) - SHOW_MISSING} more" if len(breakers) > SHOW_MISSING else ""
        detail = (f"{_describe(kind, label, n)}. They follow a pattern: {'; '.join(said)}. "
                  f"These break it: {names}{more}. A member that breaks a family's pattern either has a "
                  "reason or missed a change the rest got. Check every member, not only these.")
        leads.append(Lead("convention", locs, detail[:900], score=round(score(item), 2),
                          extra={"family": label, "family_kind": kind, "members": n,
                                 "breakers": [m[0] if kind == "class" else m[1] for m in breakers],
                                 "pattern": [{"has": f, "holders": s, "of": of, "when": cond}
                                             for f, s, of, cond in pats[:SHOW_FEATURES]]}))
        if len(leads) >= MAX_LEADS:
            break
    return leads
