"""The same list of names written out in two files: statuses, types, permissions, columns."""
from __future__ import annotations

import collections
import re

from seams.scan.inventory import Lead, is_test, kind_of

MIN_ITEMS = 4      # a list needs this many strings to count
MIN_SHARED = 4     # two lists must share this many
MIN_JACCARD = 0.6  # and this share of their union
MAX_SETS_PER_ITEM = 40  # a string in more lists than this ("id", "name") is too common to index

_STR = r"""['"`]((?:\.{1,2}/)?[A-Za-z_][\w.\-/:]{1,60})['"`]"""
_LIST = re.compile(r"[\[\(\{]\s*((?:" + _STR + r"""\s*(?::[^,\]\)\}]{0,80})?,\s*(?:(?:#|//)[^\n]*\n\s*)?){3,}"""
                   + _STR + r"\s*(?::[^,\]\)\}]{0,80})?,?)\s*[\]\)\}]", re.S)
_ITEM = re.compile(_STR)
_TICK = re.compile(r"`([A-Za-z_][\w.\-/:]{1,60})`")
_DOC_TICK = re.compile(r"`/?([A-Za-z_][\w.\-]{1,60})/?`")  # `/tdd` (a command) and `engineering/` (a folder)


def _name(item):
    """A relative path in a list ("./skills/tdd") is compared by its last name ("tdd"),
    the way a README or a doc names the same thing."""
    if item.startswith(("./", "../")):
        return item.rstrip("/").rsplit("/", 1)[-1]
    return item


_LINK = re.compile(r"\[`?([A-Za-z_][\w.\-]{1,60})`?\]\((?!https?:|mailto:|#)[^)\s]+\)")
MAX_WHOLE_DOC = 120  # a doc naming more than this many things is a catalog of everything, not a list


def _doc_items(text):
    return set(_DOC_TICK.findall(text)) | set(_LINK.findall(text))


def _doc_sets(text, inv, path):
    """A doc's paragraphs, bullet lists and tables that name four or more things, in
    backticks or as local links, and the whole doc's names as one more list. A doc that
    lists the column names, metric names or skills the code or another doc lists is a
    copy of that list. The whole-doc list catches one list split under several headings."""
    out, para, start, every = [], [], 1, set()
    for n, line in enumerate(text.split("\n") + [""], 1):
        if line.strip():
            if not para:
                start = n
            para.append(line)
            continue
        if para:
            items = frozenset(_doc_items("\n".join(para)))
            every |= items
            if len(items) >= MIN_ITEMS:
                out.append((path, start, items))
            para = []
    if MIN_ITEMS <= len(every) <= MAX_WHOLE_DOC and every not in {s for _, _, s in out}:
        out.append((path, 1, frozenset(every)))
    return out


def _pairs(sets, lo, hi, against=None):
    """Count shared items for pairs of sets in [lo, hi), or between them and [0, against)."""
    index = collections.defaultdict(list)
    for i in (range(0, against) if against is not None else range(lo, hi)):
        for item in sets[i][2]:
            index[item].append(i)
    shared = collections.Counter()
    if against is None:
        for ids in index.values():
            if len(ids) > MAX_SETS_PER_ITEM:
                continue
            for x in range(len(ids)):
                for y in range(x + 1, len(ids)):
                    shared[(ids[x], ids[y])] += 1
    else:
        for d in range(lo, hi):
            for item in sets[d][2]:
                ids = index.get(item, ())
                if len(ids) <= MAX_SETS_PER_ITEM:
                    for i in ids:
                        shared[(i, d)] += 1
    return shared


def find(inv):
    sets, doc_sets = [], []
    for path in inv.read:
        if is_test(path):
            continue
        text = inv.text(path)
        if kind_of(path) == "doc":
            doc_sets += _doc_sets(text, inv, path)
            continue
        for m in _LIST.finditer(text):
            items = frozenset(_name(x) for x in _ITEM.findall(m.group(1)))
            if len(items) >= MIN_ITEMS:
                sets.append((path, inv.line_at(path, m.start()), items))

    # Code lists are indexed on their own, so doc lists cannot push a code name over the
    # "too common" cap and hide a code-to-code match. Doc lists are matched against code
    # lists, and against each other through an index of their own.
    n_code = len(sets)
    sets += doc_sets
    shared = _pairs(sets, 0, n_code)
    shared.update(_pairs(sets, n_code, len(sets), against=n_code))
    shared.update(_pairs(sets, n_code, len(sets)))

    leads, seen = [], set()
    for (i, j), n in shared.items():
        (pa, la, sa), (pb, lb, sb) = sets[i], sets[j]
        if pa == pb or n < MIN_SHARED:
            continue
        both = sa & sb
        jac = len(both) / len(sa | sb)
        if len(both) < MIN_SHARED or jac < MIN_JACCARD or (pa, la, pb, lb) in seen:
            continue
        seen.add((pa, la, pb, lb))
        only_a, only_b = sorted(sa - sb), sorted(sb - sa)
        detail = f"{len(both)} shared ({', '.join(sorted(both)[:6])}{', ...' if len(both) > 6 else ''})"
        if only_a or only_b:
            detail += f". Only in first: {only_a[:4]}. Only in second: {only_b[:4]}"
        leads.append(Lead("literal-set", [(pa, la, None), (pb, lb, None)], detail,
                          score=round(len(both) * jac, 2),
                          extra={"only_first": only_a, "only_second": only_b}))
    return leads
