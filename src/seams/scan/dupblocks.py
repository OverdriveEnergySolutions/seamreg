"""Code copied between files: runs of WINDOW lines that match after normalizing."""
from __future__ import annotations

import collections
import hashlib
import itertools
import re

from seams.scan.inventory import Lead

WINDOW = 6
MAX_FILES = 6     # a window found in more files than this is boilerplate
MIN_WINDOWS = 2   # a pair needs this many shared windows to count
_SPACE = re.compile(r"\s+")
_SKIP_START = ("#", "//", "/*", "*", "--", "<!--", "import ", "from ", "use ", "require(",
               "#include", "using ", "package ", "export *", "export {")
_TRIVIAL = {"} else {", "else:", "try:", "finally:", "return None", "return nil", "pass",
            "return", "});", "},", "]);", "end", "fi", "done", "})", "};", "</div>"}


def _lines(text):
    out = []
    for n, raw in enumerate(text.split("\n"), 1):
        s = _SPACE.sub(" ", raw.strip())
        if len(s) < 12 or s.startswith(_SKIP_START) or s in _TRIVIAL:
            continue
        out.append((n, s))
    return out


def find(inv):
    windows = collections.defaultdict(list)
    for path in inv.code():
        lines = _lines(inv.text(path))
        for k in range(len(lines) - WINDOW + 1):
            chunk = lines[k:k + WINDOW]
            h = hashlib.sha1("\n".join(s for _, s in chunk).encode()).digest()
            windows[h].append((path, chunk[0][0], chunk[-1][0]))

    pairs = collections.defaultdict(lambda: [0, [], []])
    for locs in windows.values():
        files = sorted({l[0] for l in locs})
        if not 2 <= len(files) <= MAX_FILES:
            continue
        for a, b in itertools.combinations(files, 2):
            p = pairs[(a, b)]
            p[0] += 1
            p[1] += [(s, e) for f, s, e in locs if f == a]
            p[2] += [(s, e) for f, s, e in locs if f == b]

    leads = []
    for (a, b), (count, ra, rb) in pairs.items():
        if count < MIN_WINDOWS:
            continue
        a1, a2 = min(s for s, _ in ra), max(e for _, e in ra)
        b1, b2 = min(s for s, _ in rb), max(e for _, e in rb)
        leads.append(Lead("dupblock", [(a, a1, a2), (b, b1, b2)],
                          f"{count} matching {WINDOW}-line windows", score=count))
    return leads
