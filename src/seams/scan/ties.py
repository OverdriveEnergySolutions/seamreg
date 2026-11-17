"""Checks that may already tie copies together.

Two signals: a test whose name says parity or sync, and a test that reads a file
from another area (a test that opens both copies is usually a tie). A candidate
is not a tie until someone confirms CI runs it and it fails on drift.
"""
from __future__ import annotations

import re

from seams.scan.inventory import Lead, is_test

_WORDS = r"(parity|sync|match|drift|mirror|same|identical|consistent|agree|in_step|both)"
_TEST_DEF = re.compile(
    r"(?:\bdef\s+(test\w*)|\bfunc\s+(Test\w*)|\bfn\s+(test\w*)|\b(?:it|test|describe)\s*\(\s*['\"`]([^'\"`\n]{3,120}))")
_HAS_WORD = re.compile(_WORDS, re.I)
_PATH_LIT = re.compile(r"""['"`]((?:\.{1,2}/)*[\w\-]+(?:/[\w.\-]+)+\.\w{1,6})['"`]""")


def find(inv):
    leads = []
    for path in inv.read:
        if not is_test(path):
            continue
        text = inv.text(path)
        here = inv.area(path)
        for m in _TEST_DEF.finditer(text):
            name = next(g for g in m.groups() if g)
            if _HAS_WORD.search(name):
                line = inv.line_at(path, m.start())
                leads.append(Lead("tie-candidate", [(path, line, None)], f"test named '{name}'", score=2))
        for m in _PATH_LIT.finditer(text):
            for other in inv.resolve_mention(m.group(1), exclude=path):
                if inv.area(other) != here:
                    line = inv.line_at(path, m.start())
                    leads.append(Lead("tie-candidate", [(path, line, None), (other, None, None)],
                                      f"test reads {other} from another area", score=1))
    return leads
