"""A named date format, and code beside its users that writes dates another way.

A repo that defines SQL_DATETIME_FORMAT = "YYYY-MM-DD HH:mm:ss" says how its dates
must look. A file in the same folder as one of its users that writes dates with
toISOString() is a second writer of the same format: the seam reviewers missed on
uptime-kuma twice, because no name and no copied text links the two. Dates and
times only: other format constants are left to the name finders, to keep the noise
down.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from seams.scan.inventory import Lead, is_test, kind_of

# NAME = "literal", in the common declaration forms: const/let/var, export const,
# exports.NAME, a typed TS const, Python and Go assignments.
DEFINE = re.compile(
    r"(?:\b(?:const|let|var|final|static)\s+|\bexports\.|^\s*)"
    r"([A-Z][A-Z0-9_]*(?:FORMAT|FMT|PATTERN)[A-Z0-9_]*)\s*(?::\s*[\w.<>\[\]]+\s*)?=\s*"
    r"""(["'`])([^"'`\n]{2,60})\2""", re.M)
# A format string holds date or time parts in one of the usual notations.
DATE_PARTS = re.compile(r"YYYY|yyyy|%Y|%y|%d|%H|%m|\bHH\b|HH:mm|MM-DD|dd/MM|2006-01-02|15:04")
# Ways to write a date that ignore a named format.
OTHER_WRITERS = re.compile(
    r"\.toISOString\(\)|\.toUTCString\(\)|\.isoformat\(\)|\bstrftime\(\s*[\"']|"
    r"\.Format\(\s*time\.RFC\d+|\btime\.RFC3339\b|\bDateTimeFormatter\.ISO_")
MAX_USERS = 6
MAX_OTHERS = 12


def find(inv):
    code = [p for p in inv.read if kind_of(p) == "code" and not is_test(p)]
    formats = {}  # name -> (defining path, line, literal)
    for path in code:
        text = inv.text(path)
        for m in DEFINE.finditer(text):
            name, literal = m.group(1), m.group(3)
            if DATE_PARTS.search(literal) and name not in formats:
                formats[name] = (path, text.count("\n", 0, m.start()) + 1, literal)
    if not formats:
        return []

    leads = []
    for name, (def_path, def_line, literal) in sorted(formats.items()):
        word = re.compile(rf"\b{re.escape(name)}\b")
        users = [p for p in code if p != def_path and word.search(inv.text(p))]
        folders = {str(PurePosixPath(p).parent) for p in users + [def_path]}
        others = []
        for p in code:
            if str(PurePosixPath(p).parent) not in folders:
                continue
            text = inv.text(p)
            hits = OTHER_WRITERS.findall(text)
            if hits:
                first = text.count("\n", 0, OTHER_WRITERS.search(text).start()) + 1
                others.append((p, first, len(hits), sorted(set(h.strip("(\"' ") for h in hits))))
        # The defining file, and a twin of it (util.ts beside its compiled util.js), only
        # convert dates for others: their own writes say nothing about a second writer.
        twin = str(PurePosixPath(def_path).with_suffix(""))
        others = [o for o in others if str(PurePosixPath(o[0]).with_suffix("")) != twin]
        if not others:
            continue
        others.sort(key=lambda o: -o[2])
        locs = [(def_path, def_line, None)]
        for p, line in [(p, line) for p, line, _, _ in others[:MAX_OTHERS]] + [(p, None) for p in users[:MAX_USERS]]:
            if all(p != l[0] for l in locs):
                locs.append((p, line, None))
        said = "; ".join(f"{p} ({', '.join(kinds)}, {n}x)" for p, _, n, kinds in others[:MAX_OTHERS])
        detail = (f'{name} = "{literal}" names a date format, used in {len(users)} other file(s). '
                  f"Beside its users, these files write dates another way: {said}. "
                  "If both reach the same column, field or file, the writers must agree.")
        leads.append(Lead("date-format", locs, detail[:600], score=2 + len(others)))
    return leads
