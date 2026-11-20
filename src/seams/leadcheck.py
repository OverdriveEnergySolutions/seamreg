"""The lead check: after a first review, a cheap agent judges every strong lead no recorded seam covers.

A full reviewer gets hundreds of leads with its areas and acts on few: on one repo a lead that named the
exact two files of a known bug sat 248th of 400 in a packet, and no seam recorded it. The lead check
hands those leads out in small batches, each with one question: do these places hold one piece of
knowledge, and do the copies agree? It records a seam only when the copies differ or share a mistake.
Its bare "this is a seam" verdicts were mostly look-alike code (30 to 40% real in a graded sample), so
they stay out of the registry.

Measured 2026-11-19 on three public repos with answer keys, Sonnet 5.5 at high effort: 1,670 leads for
$27.37 (about $0.016 a lead). It found 3 known drifts the first reviews had missed, and none of 30 graded
drift and bug claims was wholly false.
"""
from __future__ import annotations

import json
from pathlib import Path

from seams import split
from seams.scan.inventory import is_test

STRONG = ("dupblock", "twin", "same-file", "literal-set", "same-name", "shared-ids", "key-writers", "flow", "access")
BATCH = 25
COST_PER_LEAD = 0.016  # US dollars, Sonnet 5.5 at high effort, measured on 1,670 leads
BRIEF = Path(__file__).with_name("lead-check-brief.md")
PREFIX = "lc-"
# Lead kinds whose agreeing seams are worth keeping. A grader read 38 agreeing seams the lead check
# recorded on two repos (2026-11-19): real in 5 of 5 for flow, key-writers, twin and access, 4 of 5 for
# shared-ids, 1 of 5 for dupblock, 0 of 3 for literal-set. A registry of drift seams plus agreeing seams
# from these kinds raised Sonnet's prevention rate from 16 to 25 of 41 runs; every seam gave only 19.
KEEP_KINDS = ("flow", "key-writers", "twin", "access", "shared-ids")
# The default output rule keeps only seams whose copies differ or share a mistake. --keep-agreeing swaps
# it for this one: every real seam goes in, so a registry can warn about copies that agree today and the
# next change will break. Each element names its lead, so the result can be judged per lead kind.
_ONLY = """Write a JSON array to your output file. Put in it only:
- **a seam whose copies differ** (`drift` set), or **a seam whose copies share a mistake** (`drift`
  null, plus a separate bug element for the mistake). Leave out a seam whose copies agree and hold no
  mistake: those are mostly look-alike code, and the registry should not hold them.
- **a bug element** for each shared mistake, and for any other bug you find on the way."""
_KEEP = """Write a JSON array to your output file. Put in it:
- **a seam whose copies differ** (`drift` set), or **a seam whose copies share a mistake** (`drift`
  null, plus a separate bug element for the mistake), from any lead.
- **a seam whose copies agree today**, only from a lead marked `(keep if a seam)` in your packet: a seam
  whose copies agree is the one the next change can break, so the registry should hold it. Leave
  `drift` null. From an unmarked lead, leave out a seam whose copies agree: those kinds are mostly
  look-alike code. Never put in a lead you judged "not".
- **a bug element** for each shared mistake, and for any other bug you find on the way.
- In every seam element, also give `"lead": <the lead's number in your packet>`."""


def select(doc, known):
    """The leads worth a check: strong kinds, two or more files, not all tests, and not fully covered
    by one recorded seam. A lead a reviewer was shown but did not act on stays in: that is the point."""
    seen, out = set(), []
    for lead in doc["leads"]:
        paths = sorted({f["path"] for f in lead["files"]})
        if lead["kind"] not in STRONG or len(paths) < 2 or split._fully_covered(lead, known):
            continue
        if lead.get("touches_tests") and all(is_test(p) for p in paths):
            continue
        key = (lead["kind"], tuple(paths))
        if key in seen:
            continue
        seen.add(key)
        out.append(lead)
    out.sort(key=lambda l: (sorted(f["path"] for f in l["files"]), l["kind"]))
    return out


def _where(lead):
    parts = []
    for f in lead["files"]:
        loc = f["path"]
        if f.get("line"):
            loc += f":{f['line']}" + (f"-{f['end']}" if f.get("end") else "")
        parts.append(loc)
    return ", ".join(parts)


def packet_md(n, leads, root, out, keep_agreeing=False):
    rel = Path(out).resolve()
    rows = [f"# Lead check packet {PREFIX}{n:02d}", "",
            f"Repo root: `{Path(root).resolve()}`",
            f"Brief: `{rel / 'lead-check-brief.md'}`. Read it first and follow it exactly.",
            f"Output file: `{rel / 'reviews' / f'seam-review-{PREFIX}{n:02d}.json'}`", "",
            f"## Leads ({len(leads)})", ""]
    for i, lead in enumerate(leads, 1):
        detail = f" ({lead['detail']})" if lead.get("detail") else ""
        mark = " (keep if a seam)" if keep_agreeing and lead["kind"] in KEEP_KINDS else ""
        rows.append(f"{i}. {lead['kind']}: {_where(lead)}{detail}{mark}")
    return "\n".join(rows) + "\n"


def write(doc, root, out, known, batch=BATCH, keep_agreeing=False):
    """Write the lead check packets and plan.md. Returns [{"name", "leads"}]."""
    out = Path(out).resolve()
    leads = select(doc, known)
    if not leads:
        return []
    split.archive_earlier_passes(out)
    (out / "packets").mkdir(parents=True, exist_ok=True)
    (out / "reviews").mkdir(exist_ok=True)
    for old in (out / "packets").glob("*.md"):
        old.unlink()
    brief = BRIEF.read_text(encoding="utf-8")
    if keep_agreeing:
        if _ONLY not in brief:
            raise ValueError("the lead check brief's output rule changed; update leadcheck._ONLY")
        brief = brief.replace(_ONLY, _KEEP)
    (out / "lead-check-brief.md").write_text(brief, encoding="utf-8")
    bins = []
    for i in range(0, len(leads), batch):
        n = i // batch + 1
        chunk = leads[i:i + batch]
        name = f"{PREFIX}{n:02d}"
        (out / "packets" / f"{name}.md").write_text(packet_md(n, chunk, root, out, keep_agreeing), encoding="utf-8")
        bins.append({"name": name, "leads": chunk, "lines": 0, "units": []})
    shown = sorted({l["fingerprint"] for l in leads if "fingerprint" in l})
    (out / "shown.json").write_text(json.dumps(shown) + "\n", encoding="utf-8")
    kinds = {}
    for l in leads:
        kinds[l["kind"]] = kinds.get(l["kind"], 0) + 1
    rows = ["# Lead check plan", "",
            f"{len(bins)} packets of up to {batch} leads, one `seam-lead-checker` agent each: {len(leads)} strong leads "
            f"that no seam in seams.json fully covers ({', '.join(f'{n} {k}' for k, n in sorted(kinds.items()))}).", "",
            "Each checker decides, lead by lead, whether the places hold one piece of knowledge, and records a seam "
            "only when its copies differ or share a mistake.", "",
            "## Cost", "",
            f"About ${COST_PER_LEAD * len(leads):.0f} at ${COST_PER_LEAD} a lead, measured with Sonnet 5.5 at high effort "
            "on 1,670 leads in three repos. A larger model costs several times more. Start one packet first and "
            "read its cost before you start the rest."]
    (out / "plan.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return bins
