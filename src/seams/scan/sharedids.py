"""Code or config in two folders that uses the same rare names: field, column, setting and function names.

Two places can hold one rule, one field set or one shape and share no copied text, no commit and no
file name: a web handler and an API handler that both check `site_limit`, or a writer and a reader of
the same columns. What they share is the rare names. A name used in two to four code files ties those
files; a pair that shares several such names, weighted by how rare each is, is a lead.

Measured offline on 7 repos with answer keys (2026-11-19): of 48 key seams no other lead linked, the top
300 pairs per repo linked 15. 300 random file pairs per repo linked 0 to 2. The settings were picked on
those keys, so the rate on a fresh repo is not known yet.
"""
from __future__ import annotations

import collections
import itertools
import math
import re

from seams.scan.inventory import Lead, is_test, kind_of

MAX_FILES = 4     # a name in more code files than this is too common to tie two of them
MIN_SHARED = 3    # a pair needs about this many rare names in common (weighted)
MAX_LEADS = 300   # the strongest pairs; the rest are mostly noise
SHOW = 6          # names listed in a lead's detail

_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{5,}\b")
_STOP = set("""return function public private protected static string number boolean import export default
require module class const unless include extends implements interface self this super params request
response render redirect controller service models model value values result string_value""".split())


def _names(text):
    out = set()
    for w in _IDENT.findall(text):
        if w.lower() in _STOP:
            continue
        if w.isupper() and not ("_" in w and len(w) > 7):  # a short all-caps word is a keyword or an acronym
            continue
        out.add(w)
    return out


def find(inv):
    # code and config (an env template and the config file that reads it), not docs or tests
    files = [p for p in inv.read if not is_test(p) and kind_of(p) != "doc"]
    names = {p: _names(inv.text(p)) for p in files}
    df = collections.Counter(w for s in names.values() for w in s)
    holders = collections.defaultdict(list)
    for p, s in names.items():
        for w in s:
            if 2 <= df[w] <= MAX_FILES:
                holders[w].append(p)
    weight = collections.Counter()
    shared = collections.defaultdict(list)
    total = max(len(files), MAX_FILES + 1)
    for w, ps in holders.items():
        idf = math.log(total / df[w])
        for a, b in itertools.combinations(sorted(ps), 2):
            if a.rpartition("/")[0] == b.rpartition("/")[0]:
                continue  # one folder: the scan's other leads and a reviewer's sweep already see these together
            weight[(a, b)] += idf
            shared[(a, b)].append((idf, w))
    floor = MIN_SHARED * math.log(total / MAX_FILES)
    pairs = [(w, ab) for ab, w in weight.items() if w >= floor]
    pairs.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for w, (a, b) in pairs[:MAX_LEADS]:
        top = [n for _, n in sorted(shared[(a, b)], reverse=True)[:SHOW]]
        out.append(Lead("shared-ids", [(a, None, None), (b, None, None)],
                        f"rare names in both: {', '.join(top)}", score=round(w, 2),
                        extra={"names": top}))
    return out
