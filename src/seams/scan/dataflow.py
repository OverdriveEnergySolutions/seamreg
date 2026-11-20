"""Producer and consumer: a rare key one file writes and another file reads. And access: two files that
decide who may do what and share rare names on those lines.

Both come from a prevention measure (2026-11-19): for 32 real commits that changed some files and missed
a copy, each repo scanned at the commit's parent, how many tasks a lead kind links (a changed file and
its missed copy in one lead). Flow leads linked 9, access leads 3, random pairs 0. The copy-based leads
linked 0 to 4. The settings were picked while looking at those repos, so treat the rates as a guide.
"""
from __future__ import annotations

import collections
import itertools
import math
import re

from seams.scan.inventory import Lead, is_test, kind_of

MAX_FILES = 6
MAX_LEADS = 300
_KEY = r"[A-Za-z_][A-Za-z0-9_]{3,40}"
_WRITE = [re.compile(p, re.M) for p in (
    rf"""['"]({_KEY})['"]\s*=>""",
    rf"""\[\s*['"]({_KEY})['"]\s*\]\s*=(?!=)""",
    rf"""(?:^|[{{,(\s])({_KEY}):\s+[^:\s]""",
    rf"""->({_KEY})\s*=(?!=)""",
    rf"""\.\s*set\(\s*['"]({_KEY})['"]""",
)]
_READ = [re.compile(p) for p in (
    rf"""\[\s*['"]({_KEY})['"]\s*\](?!\s*=[^=])""",
    rf"""\[\s*:({_KEY})\s*\]""",
    rf"""(?:get|fetch|has|input|query|string|integer|boolean|date)\(\s*['":]({_KEY})['"]?""",
    rf"""->({_KEY})\b(?!\s*[=(])""",
    rf"""\.({_KEY})\b(?!\s*[=(])""",
)]
_ACCESS = re.compile(r"authori[sz]e|authenticat|middleware|policy|policies|permission|is_?admin|isAdmin|owner|"
                     r"role|guard|can\?|cannot\?|Gate::|before_action|login_required|require_(?:user|login|auth)|"
                     r"current_user|abort\(403|forbidden|unauthori[sz]ed|access_denied", re.I)
_NAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{4,}\b")
_COMMON = set("""data type name value values result items label title text status message error errors path
url id key keys user users date time count total amount page limit offset order sort query params options
config default description created_at updated_at""".split())


def _files(inv):
    # code, config and templates: a key a template or a config file reads counts as much as code
    return [p for p in inv.read if not is_test(p) and kind_of(p) != "doc"]


def _pairs(holders, df, n, by_dir=True):
    weight = collections.Counter()
    shared = collections.defaultdict(list)
    for k, (left, right) in holders.items():
        idf = math.log(n / df[k])
        for a in left:
            for b in right:
                if a == b or (by_dir and a.rpartition("/")[0] == b.rpartition("/")[0]):
                    continue
                pair = tuple(sorted((a, b)))
                weight[pair] += idf
                shared[pair].append(k)
    return weight, shared


def find(inv):
    files = _files(inv)
    texts = {p: inv.text(p) for p in files}
    out = []

    # producer -> consumer
    writes = {p: {m for rx in _WRITE for m in rx.findall(t)} - _COMMON for p, t in texts.items()}
    reads = {p: {m for rx in _READ for m in rx.findall(t)} - _COMMON for p, t in texts.items()}
    df = collections.Counter(k for p in files for k in writes[p] | reads[p])
    holders = collections.defaultdict(lambda: ([], []))
    for p in files:
        for k in writes[p]:
            if 2 <= df[k] <= MAX_FILES:
                holders[k][0].append(p)
        for k in reads[p]:
            if 2 <= df[k] <= MAX_FILES:
                holders[k][1].append(p)
    weight, shared = _pairs(holders, df, max(len(files), MAX_FILES + 1))
    for (a, b), w in sorted(weight.items(), key=lambda x: (-x[1], x[0]))[:MAX_LEADS]:
        keys = sorted(set(shared[(a, b)]))[:6]
        out.append(Lead("flow", [(a, None, None), (b, None, None)],
                        f"one writes and the other reads: {', '.join(keys)}", score=round(w, 2), extra={"keys": keys}))

    # access decisions
    names = {}
    for p, t in texts.items():
        lines = [l for l in t.splitlines() if _ACCESS.search(l)]
        if len(lines) >= 2:
            names[p] = {w for l in lines for w in _NAME.findall(l)} - _COMMON
    adf = collections.Counter(w for s in names.values() for w in s)
    aholders = collections.defaultdict(list)
    for p, s in names.items():
        for w in s:
            if 2 <= adf[w] <= MAX_FILES:
                aholders[w].append(p)
    aw = collections.Counter()
    ashared = collections.defaultdict(list)
    an = max(len(names), MAX_FILES + 1)
    for w, ps in aholders.items():
        for a, b in itertools.combinations(sorted(ps), 2):
            if a.rpartition("/")[0] != b.rpartition("/")[0]:
                aw[(a, b)] += math.log(an / adf[w])
                ashared[(a, b)].append(w)
    for (a, b), w in sorted(aw.items(), key=lambda x: (-x[1], x[0]))[:MAX_LEADS]:
        keys = sorted(set(ashared[(a, b)]))[:6]
        out.append(Lead("access", [(a, None, None), (b, None, None)],
                        f"both decide access with: {', '.join(keys)}", score=round(w, 2), extra={"names": keys}))
    return out
