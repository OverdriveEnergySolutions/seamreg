"""Comments where a developer already said two places must agree."""
from __future__ import annotations

import re

from seams.scan.inventory import Lead, kind_of

PHRASE = re.compile(
    r"\b(mirror(?:s|ed|ing)?\b|keep (?:this |these |it |them |both )?in sync|kept in sync|"
    r"in sync with|out of sync|must (?:match|agree|stay (?:identical|in sync)|be kept)|"
    r"(?:has|have|needs?) to match|"
    r"same (?:list|map|set|table|shape|order|names?|values?|logic|rules?|format) as|"
    r"copy of|copied from|duplicated? (?:of|in|from)|parity\b|"
    r"both (?:sides|copies|places|files)|the other cop(?:y|ies)|identical (?:to|in)|"
    r"change (?:both|all (?:three|four|of them))|(?:also|too) update|"
    r"update (?:\S+ ){0,3}(?:too|as well)\b|"
    r"if you (?:change|edit|update|add|rename) (?:this|these|one|a |an )|"
    r"when (?:changing|editing|adding|renaming) (?:this|these)|must be updated)",
    re.I)
# Docs have no comment syntax, so any line counts, and only the strongest phrases do.
DOC_PHRASE = re.compile(
    r"\b(keeps? (?:this |these |it |them |both )?in sync|kept in sync|in sync with|must (?:match|agree)|"
    r"mirrors?\b|mirrored|same (?:list|names?|values?|order|set) as|copy of|copied from|"
    r"(?:also|too) update|if you (?:change|edit|update|add|rename) )", re.I)
COMMENT = re.compile(r"^\s*(#|//|/\*|\*|--|<!--|;|%|\{#|\{\{!--|')|\s(#|//)\s|/\*|<!--")
PATHLIKE = re.compile(r"[\w.\-/]+(?:/[\w.\-]+|\.[A-Za-z]{1,5})\b")


def find(inv):
    leads = []
    for path in inv.read:
        doc = kind_of(path) == "doc"
        for n, line in enumerate(inv.text(path).split("\n"), 1):
            if doc:
                if not DOC_PHRASE.search(line):
                    continue
            elif not COMMENT.search(line) or not PHRASE.search(line):
                continue
            locs = [(path, n, None)]
            for token in PATHLIKE.findall(line):
                for other in inv.resolve_mention(token, exclude=path):
                    if all(other != l[0] for l in locs):
                        locs.append((other, None, None))
            if doc and len(locs) < 2:
                continue  # a doc line counts only when it names the file that must match
            leads.append(Lead("marker", locs, line.strip()[:200], score=1 + len(locs) - 1))
    return leads
