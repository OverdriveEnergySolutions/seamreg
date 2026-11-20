"""Every file that writes the same key: they must build the same shape.

A response field, a payload key or a column can be written by many code paths: an enrichment, a
transformer, a job, a controller. When one writer builds the value another way (a different shape, a
different currency, a missing part), every reader of the others is wrong for that path. A key written by
3 to 25 files in more than one folder makes one lead holding every writer, so a checker can compare them.

Measured offline on 7 repos with answer keys (2026-11-19): of 33 key seams no other lead linked, these
leads (smallest families first, top 300) linked 8; random groups of the same sizes linked 1. The settings
were picked while looking at those repos' misses, so the rate on a fresh repo is not known yet.
"""
from __future__ import annotations

import collections
import re

from seams.scan.inventory import Lead, is_test, kind_of

MIN_WRITERS = 3
MAX_WRITERS = 25
MAX_LEADS = 300
_KEY = r"[A-Za-z_][A-Za-z0-9_]{3,40}"
_WRITE = [re.compile(p, re.M) for p in (
    rf"""['"]({_KEY})['"]\s*=>""",                 # 'key' => value (PHP, Ruby)
    rf"""\[\s*['"]({_KEY})['"]\s*\]\s*=(?!=)""",   # x['key'] = value
    rf"""(?:^|[{{,(\s])({_KEY}):\s+[^:\s]""",       # key: value (Ruby, JS, Elixir)
    rf"""->({_KEY})\s*=(?!=)""",                   # $obj->key = value
    rf"""\.\s*set\(\s*['"]({_KEY})['"]""",           # ->set('key', value)
)]
_COMMON = set("""data type name value values result items label title text status message error errors path
url id key keys user users date time count total amount page limit offset order sort query params options
config default description created_at updated_at""".split())


def find(inv):
    writers = collections.defaultdict(list)
    for p in inv.read:
        if is_test(p) or kind_of(p) != "code":
            continue
        text = inv.text(p)
        seen = set()
        for rx in _WRITE:
            for m in rx.finditer(text):
                k = m.group(1)
                if k in _COMMON or k in seen:
                    continue
                seen.add(k)
                writers[k].append((p, inv.line_at(p, m.start())))
    families = [(k, locs) for k, locs in writers.items()
                if MIN_WRITERS <= len(locs) <= MAX_WRITERS and len({p.rpartition("/")[0] for p, _ in locs}) > 1]
    families.sort(key=lambda f: (len(f[1]), f[0]))  # smaller families are more specific
    return [Lead("key-writers", [(p, line, None) for p, line in locs], f"{len(locs)} files write `{k}`",
                 score=round(1 + 10 / len(locs), 2), extra={"key": k})
            for k, locs in families[:MAX_LEADS]]
