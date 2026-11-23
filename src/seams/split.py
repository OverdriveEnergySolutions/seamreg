"""Group a scan's areas into review packets, one reviewer agent each.

    seams split [--out DIR] [--max-lines N] [--new-only] [--cross-area-only] [--gap]

Reads <out>/leads.json from `seams scan` and writes:

    <out>/brief.md                   the reviewer brief, the same for every packet
    <out>/packets/<packet>.md        one self-contained packet per reviewer
    <out>/reviews/                   where each reviewer writes seam-review-<packet>.json
    <out>/plan.md                    the packets, their size and a cost estimate

Areas joined by many cross-area leads go in the same packet, so one reviewer
sees both sides of a seam. A packet stays under --max-lines lines of non-test
code where it can. One area larger than that becomes its subfolders.

--new-only drops leads that seams.json already covers, and --cross-area-only
drops leads inside one area. Either one makes the review lead-only: packets
with no leads left are skipped, and each reviewer checks its leads instead of
sweeping its areas. That is the cheap way to re-scan a repo that already has
a registry.

--gap makes a second full pass after a first review: each reviewer gets the
seams seams.json already records in its areas and hunts for the ones that list
misses. One review finds about half of a repo's seams, and a second blind
review spends much of its effort finding the same ones again. A lead is left
out only when one recorded seam lists every one of its files; leads the first
reviewer saw and passed over stay in.
Gap packets are named gap-..., so they never overwrite the first pass's reviews.
"""
from __future__ import annotations

import collections
import datetime
import itertools
import json
import re
from pathlib import Path

from seams.scan import is_new

# One measured run: six reviewers used about 3.1M tokens over 441k lines of
# non-test code, about 7 tokens per line and 73k lines per reviewer. A single
# repo, so treat both as a rough guide.
DEFAULT_MAX_LINES = 75_000
LEAD_UNIT_LINES = 10_000  # a lead-only pass reviews the subfolders its leads touch, not whole areas
TOKENS_PER_LINE = 7.0
MAX_LEADS = 400  # per packet; cross-area leads go in first
# Measured on one 2,200-file repo, six packets each (2026-11-15): a reviewer cost
# about the same whatever its packet's size, so cost is per packet, not per line.
# Lead-only review cost is not measured at scale yet.
PER_PACKET = {"high": (320_000, 14), "max": (620_000, 37)}  # tokens, wall minutes
BRIEF = Path(__file__).with_name("brief.md")


def _units(doc, max_lines):
    """{unit: non-test lines}. A unit is an area, or a subfolder of an area too big for one packet."""
    files = doc.get("files", [])
    by_area = collections.defaultdict(list)
    for f in files:
        by_area[f["area"]].append(f)
    units = {}
    owner = {}
    for area, fs in by_area.items():
        groups = {area: fs}
        while True:
            big = [u for u, g in groups.items() if _code_lines(g) > max_lines and _can_split(u, g)]
            if not big:
                break
            for u in big:
                for f in groups.pop(u):
                    rest = f["path"][len(u) + 1:] if u != "(root)" else f["path"]
                    sub = f"{u}/{rest.split('/')[0]}" if "/" in rest else u + "/*"
                    groups.setdefault(sub, []).append(f)
        for u, g in groups.items():
            units[u] = _code_lines(g)
            for f in g:
                owner[f["path"]] = u
    return units, owner


DATA_EXT = (".json", ".jsonc")


def _code_lines(files):
    # Reviewers sweep code. Tests, docs and JSON data (translations, dashboards, fixtures) are
    # opened when a lead points at them. 46,000 lines of translation JSON once filled a packet
    # of their own, a reviewer with nothing to review.
    return sum(f["lines"] for f in files
               if not f["test"] and not f.get("doc") and not f["path"].endswith(DATA_EXT))


def _can_split(unit, files):
    if unit.endswith("/*"):
        return False
    prefix = "" if unit == "(root)" else unit + "/"
    return any("/" in f["path"][len(prefix):] for f in files)


def plan(doc, max_lines=DEFAULT_MAX_LINES, lead_units_only=False):
    """[{"name", "units", "lines", "leads"}] in order, largest first. A first review packs every
    unit. A lead-only pass (`lead_units_only`) packs only the units its leads touch, so a packet does
    not carry unrelated code into the review. Its units are cut finer (subfolders of any area over
    LEAD_UNIT_LINES), so one lead does not bring in a whole large area."""
    units, owner = _units(doc, min(max_lines, LEAD_UNIT_LINES) if lead_units_only else max_lines)

    def units_of(lead):
        # every lead file is a scanned file, so it has an owner; the fallback is defensive
        return [owner.get(f["path"], lead["areas"][0]) for f in lead["files"]]

    if lead_units_only:
        touched = {u for lead in doc["leads"] for u in units_of(lead)}
        units = {u: n for u, n in units.items() if u in touched}

    links = collections.Counter()
    for lead in doc["leads"]:
        for a, b in itertools.combinations(sorted(set(units_of(lead))), 2):
            links[(a, b)] += 1

    parent = {u: u for u in units}
    size = dict(units)

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for (a, b), _ in links.most_common():
        if a not in parent or b not in parent:
            continue
        ra, rb = find(a), find(b)
        if ra != rb and size[ra] + size[rb] <= max_lines:
            parent[rb] = ra
            size[ra] += size[rb]

    clusters = collections.defaultdict(list)
    for u in units:
        clusters[find(u)].append(u)
    bins = []
    for members in sorted(clusters.values(), key=lambda m: (-sum(units[u] for u in m), sorted(m))):
        lines = sum(units[u] for u in members)
        for b in bins:
            if b["lines"] + lines <= max_lines:
                b["units"] += members
                b["lines"] += lines
                break
        else:
            bins.append({"units": list(members), "lines": lines})

    for i, b in enumerate(bins, 1):
        b["units"].sort(key=lambda u: (-units[u], u))
        b["name"] = _packet_name(i, b)
        b["leads"] = []
    packet_of = {u: b for b in bins for u in b["units"]}
    for lead in doc["leads"]:
        owners = [packet_of[u] for u in units_of(lead) if u in packet_of]
        if owners:
            # the packet holding most of the lead's files; on a tie, the first file's
            counts = collections.Counter(id(b) for b in owners)
            best = max(counts.values())
            next(b for b in owners if counts[id(b)] == best)["leads"].append(lead)
    return bins


def filter_leads(doc, new_only=False, cross_area_only=False):
    """A copy of `doc` with only the leads the filters keep."""
    if new_only and not doc.get("registry") and not doc.get("baseline"):
        raise ValueError("--new-only needs a scan made with a seams.json or a seams.baseline.json "
                         "in the repo, so it can tell new leads from old ones.")
    leads = [l for l in doc["leads"]
             if not (new_only and not is_new(l)) and not (cross_area_only and not l["cross_area"])]
    return {**doc, "leads": leads}


def _packet_name(i, b):
    """p01-server, or p01-server-and-21-more: a packet named after one area must not look
    like it holds only that area."""
    more = len(b["units"]) - 1
    return f"p{i:02d}-{_slug(b['units'][0])}" + (f"-and-{more}-more" if more else "")


def _drop_empty(bins):
    kept = [b for b in bins if b["leads"]]
    for i, b in enumerate(kept, 1):
        b["name"] = _packet_name(i, b)
    return kept


MAX_TIE_LEADS = 40  # per packet: tie candidates help find existing ties, but rarely point at a seam
MIN_CONVENTION_LEADS = 60  # per packet, kept ahead of the rest: a family sits in one area, so the
# cross-area-first order cut every convention lead from umami's packets


def shown_leads(b):
    """The leads a packet shows its reviewer, at most MAX_LEADS, back in scan order.

    Up to MIN_CONVENTION_LEADS convention leads come first, then the other seam leads:
    cross-area, then the strongest. Tie candidates come last
    and at most MAX_TIE_LEADS of them. On one real repo 1,506 tie candidates pointed
    at 1 seam, and as cross-area leads they took the slots of leads that did."""
    rank = lambda l: (not l["cross_area"], -l["score"])
    conv = sorted((l for l in b["leads"] if l["kind"] == "convention"), key=rank)[:MIN_CONVENTION_LEADS]
    taken = {id(l) for l in conv}
    seam_leads = [l for l in b["leads"] if l["kind"] != "tie-candidate" and id(l) not in taken]
    tie_leads = [l for l in b["leads"] if l["kind"] == "tie-candidate"]
    top = conv + sorted(seam_leads, key=rank)[:MAX_LEADS - len(conv)]
    top += sorted(tie_leads, key=rank)[:max(0, min(MAX_TIE_LEADS, MAX_LEADS - len(top)))]
    keep = {id(l) for l in top}
    return [l for l in b["leads"] if id(l) in keep]


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "root"


def _loc(f):
    s = f["path"]
    if "line" in f:
        s += f":{f['line']}" + (f"-{f['end']}" if "end" in f else "")
    return s


GAP_TEXT = (
    "This is a second pass. A first review already recorded the seams listed below. "
    "One review finds about half of a repo's seams, so assume this list misses about half "
    "of yours. Your job is the half it missed.\n\n"
    "- Record only knowledge the list does not name. If you find a copy a listed seam "
    "misses, record that seam with the same id, the new copies and one copy it lists.\n"
    "- A file the list names can hold a second, different seam. Read each file for "
    "knowledge the list does not name, not only for the listed seams.\n"
    "- Look hardest where the list is thin: folders with few or no listed seams, and the "
    "kinds of seam the brief names that the list lacks.\n"
    "- Record drift in a listed seam only when you see it in passing. A drift check covers "
    "those seams.")


# Focused passes: one kind of seam, hunted across the whole repo by one reviewer. Each has the
# lead kinds its packet shows and the instructions its reviewer follows.
FOCUS = {
    "twins": {
        "title": "two implementations of one behavior",
        "kinds": {"twin", "dupblock", "date-format"},
        "method": "and tests each twin on edge cases",
        "cost": "Measured on five repos, one twins pass cost $21 to $29 at API prices for the whole session: "
                "about half a first review.",
        "text": (
            "This is a focused pass. It hunts one kind of seam across the whole repo: one behavior "
            "written twice, so that the two must give the same answer for the same input. A first review "
            "already recorded the seams listed below. Record the twins it missed, and drift in a twin it "
            "recorded (use the same id). Skip every other kind of seam: other passes cover them.\n\n"
            "Where twins hide:\n\n"
            "- a parser, validator or formatter on the server and its copy in the client, often in two languages,\n"
            "- two patterns for the same line, token or name: a regex in one file and another for the same input "
            "elsewhere,\n"
            "- a query, a rule or a file written once per database, platform or backend,\n"
            "- a helper copied into a second package, and a limit both the client and the server enforce,\n"
            "- two code paths that build the same value: a URL, an id, a slug, a key.\n\n"
            "For each twin:\n\n"
            "1. Read every implementation in full.\n"
            "2. Write the inputs a careful tester would try for it: empty, spaces only, leading and trailing "
            "space, the longest allowed value and one more, mixed case, letters outside ASCII, emoji and "
            "joining characters, digits, separators and punctuation, bulleted and numbered list markers, "
            "escape characters, NULL or a missing key, a duplicate.\n"
            "3. Decide what each implementation does with each input. For a pattern, copy it into a scratch "
            "script and run it on the inputs (node for a JavaScript pattern, python for most others). Copying "
            "a pattern is fine. Running the repo's own code is not.\n"
            "4. An input that the implementations treat differently is drift. Record it with the input and "
            "path:line on each side.\n\n"
            "Record one seam per behavior, with every implementation as a copy. When every file of a family "
            "holds one version per backend, record a convention seam over the family."),
    },
    "packaging": {
        "title": "what the image and the build ship against what the code and its manifests say",
        "kinds": {"packaging"},
        "method": "and checks each build file against the manifests and the files the app reads",
        "cost": "Its cost is not measured yet: report the reviewer's tokens when it is done.",
        "text": (
            "This is a focused pass. It hunts one kind of seam across the whole repo: the build and packaging "
            "files (Dockerfiles, CI workflows, release scripts, version files) against the code and the "
            "dependency manifests. A first review already recorded the seams listed below. Record the packaging "
            "seams it missed, and drift in one it recorded (use the same id). Skip every other kind of seam.\n\n"
            "Where they hide:\n\n"
            "- a package version written into an image or a script (an install line, a build ARG) and the same "
            "package in package.json, requirements or go.mod,\n"
            "- the final stage of a multi-stage image, which copies some files from the build stage: a config file "
            "the app or its tools read at run time (an ORM config, a server config, a locale folder) that is not "
            "copied,\n"
            "- one runtime version (node, python, go) in a base image, a CI setup step, a version file and the "
            "manifest's engines field,\n"
            "- an env var the code reads that the image, the compose file or the docs do not set or list.\n\n"
            "For each lead, open both sides and say what the image or the build actually gets. A file the final "
            "stage lacks is drift only if something in the image reads it: find the reader (a start script, a "
            "migrate command, a config loader) and name it with path:line."),
    },
    "open": {
        "title": "whatever kind of seam this repo has that no earlier pass looked for",
        "kinds": set(),
        "method": "and forms its own guesses about where copies hide, then tests each one",
        "cost": "Its cost is not measured yet: report the reviewer's tokens when it is done.",
        "text": (
            "This is an open pass. No rule says what to look for. Earlier passes ran with fixed methods, "
            "listed below with the seams they recorded and the parts of the repo their reviewers opened. "
            "Your job is to find the seams they missed by looking at this repo in ways they did not.\n\n"
            "1. Read enough of the repo to understand what it is: what it builds, what it stores, what "
            "it ships, what it generates, and who reads its docs.\n"
            "2. Write down five to ten guesses about where this repo keeps one piece of knowledge in "
            "more than one place. A guess names a shape (\"each plugin declares its settings in code and "
            "again in its docs page\") and where to check it. For each guess, say whether it is a new "
            "perspective, or a deeper look at an old one, and why it is worth the time. Favor new "
            "perspectives and the parts of the repo nobody opened, but a deeper look is fine when you "
            "can say what the earlier pass skipped.\n"
            "3. Test each guess across the whole repo, not on one example. A short read-only script that "
            "lists every member and checks each one is the right tool. Copy patterns into the script if "
            "you need to run them. Do not run the repo's own code.\n"
            "4. Record each seam you confirm, with path:line on each side. You may also extend a recorded "
            "seam (a copy it misses, a sharper must_agree, a rule that no longer matches the code): use "
            "its id. Do not record a seam that is already in the list.\n"
            "5. In your review file, add one entry {\"notes\": {\"guesses\": [...]}} with one object per guess: "
            "guess, perspective (new or deeper, and why), held (yes, no, or partly, with what you found), test (the "
            "script or search, so it can be rerun) and seam (the ids it produced). A later pass, or a maintainer "
            "building a new kind of pass, reads these."),
    },
    "siblings": {
        "title": "classes that share a base and must carry its fields into every layer",
        "kinds": {"sibling", "convention"},
        "method": "and compares each sibling's counterparts layer by layer",
        "cost": "Its cost is not measured yet: report the reviewer's tokens when it is done.",
        "text": (
            "This is a focused pass. It hunts one kind of seam across the whole repo: classes that share a base "
            "class or mixin, and the counterparts each one has in other layers. A first review already recorded "
            "the seams listed below. Record the sibling seams it missed, and drift in one it recorded (use the "
            "same id). Skip every other kind of seam: other passes cover them.\n\n"
            "The shape: Invoice and CreditNote both mix in BillingMixin, which declares currency and due_date. "
            "Each has a form, a serializer, a filter and a table named after it (InvoiceSerializer, "
            "CreditNoteSerializer). When BillingMixin gains a field, every sibling's counterpart in every layer "
            "should gain it too, unless a layer leaves it out on purpose. The usual drift: one sibling got the "
            "field in a layer and another did not, because whoever added it worked on one model.\n\n"
            "For each sibling lead, and for each base you find with two or more users:\n\n"
            "1. List the base's fields, from every class of that name (a model mixin, a form mixin and an API "
            "mixin often share one name).\n"
            "2. List the siblings and, for each, its counterpart in every layer.\n"
            "3. Build a table: layers down, siblings across, and for each cell which of the base's fields the "
            "counterpart carries, itself or through its own bases. A short read-only script that parses the files "
            "is fine.\n"
            "4. A cell that lacks a field the same layer carries for another sibling is drift, unless the code, a "
            "comment or the docs give a reason. Record it with path:line on each side.\n\n"
            "Record one seam per base and layer group, with each counterpart as a copy, kind convention. Also "
            "check the convention leads in this packet: a family member that lacks what the rest hold is the same "
            "drift, seen from the family instead of the base."),
    },
}


def _fully_covered(lead, known):
    """True when one recorded seam lists every file of `lead`. Sharing some files is not
    enough: a file can hold a second seam, and that is what a gap pass looks for. (The
    scan's covered_by is looser, at two shared files, which suits a re-scan.)

    Only a copy that names the file by its path counts. A glob copy (a convention seam's
    `app/*/search.py`) matches whole families, and on frigate it hid 813 leads that no recorded
    seam covered."""
    paths = [f["path"] for f in lead["files"]]
    return any(all(any(c["path"] == p for c in s["copies"]) for p in paths) for s in known)


def _in_units(path, units):
    return any(u in (".", "") or path == u or path.startswith(u.rstrip("/") + "/") for u in units)


def packet_md(b, bins, root, out, lead_only=False, known=None, focus=None):
    others = [o for o in bins if o is not b]
    lines = [
        f"# Seam review packet {b['name']}", "",
        f"Read the brief first: `{out / 'brief.md'}`.", "",
        f"- Repo root: `{root}`",
        f"- Output file: `{out / 'reviews' / ('seam-review-' + b['name'] + '.json')}`", "",
        "## Your areas", "",
    ]
    lines += [f"- `{u}`" for u in b["units"]]
    if lead_only:
        lines += ["", "## Lead-only review", "",
                  "This is a re-scan. seams.json already records the seams found earlier. Check each "
                  "lead below and record the new seams it shows, including new copies of a seam "
                  "seams.json already lists. Do not sweep your areas for other seams. You may open "
                  "any file a lead needs."]
    if known is not None:
        # A seam whose copies sit in no packet's areas (repo-root files such as .gitignore)
        # would be listed nowhere, and a reviewer could record it again: list it everywhere.
        homeless = [s for s in known if not any(_in_units(c["path"], o["units"]) for o in bins for c in s["copies"])]
        mine = [s for s in known if any(_in_units(c["path"], b["units"]) for c in s["copies"])] + homeless
        if focus:
            mine = list(known)  # a focused reviewer covers the whole repo
            lines += ["", f"## Focused pass: {FOCUS[focus]['title']}", "", FOCUS[focus]["text"], "",
                      f"## Seams already recorded ({len(known)} in seams.json)", ""]
        else:
            lines += ["", "## Gap pass", "", GAP_TEXT, "",
                      f"## Seams already recorded in your areas ({len(mine)} of {len(known)} in seams.json)", ""]
        for s in sorted(mine, key=lambda s: s["id"]):
            paths = list(dict.fromkeys(c["path"] for c in s["copies"]))
            lines.append(f"- **{s['id']}** ({s['risk']}): {s['must_agree']} Copies: "
                         + ", ".join(f"`{x}`" for x in paths))
        if not mine:
            lines.append("- none: the first review recorded no seam here")
        if focus == "open":
            lines += _open_context(out, known)
    lines += ["", "## Areas other reviewers own", "",
              "You may read any of these. Record a seam that crosses into them anyway: the merge joins duplicates.", ""]
    lines += [f"- {o['name']}: " + ", ".join(f"`{u}`" for u in o["units"][:8])
              + (f" and {len(o['units']) - 8} more" if len(o["units"]) > 8 else "") for o in others] or ["- none"]
    if focus == "open":
        return "\n".join(lines) + "\n"  # no leads: the reviewer forms its own guesses
    shown = shown_leads(b)
    omitted = len(b["leads"]) - len(shown)
    lines += ["", f"## Leads ({len(shown)} of {len(b['leads'])})", "",
              "Hints from a mechanical scan, grouped by kind, strongest first. Many are noise."]
    if omitted:
        lines.append(f"{omitted} weaker leads inside single areas are left out. "
                     f"All of them are in `{out / 'leads.json'}`.")
    lines.append("")
    for lead in shown:
        tag = " [cross-area]" if lead["cross_area"] else ""
        lines.append(f"- {lead['kind']}: {'  <->  '.join(_loc(f) for f in lead['files'])}{tag}  \n  {lead['detail']}")
    return "\n".join(lines) + "\n"


def _open_context(out, known):
    """For the open pass: the perspectives earlier passes used, and where their reviewers looked."""
    import collections
    from seams import lookedat, passes
    lines = ["", "## Perspectives already used", ""]
    kinds = [p["kind"] for p in passes.load_ledger(out)["passes"] if p["kind"] != "focus:open"]
    la = Path(out) / "looked-at.json"
    if not kinds and la.exists():
        kinds = json.loads(la.read_text(encoding="utf-8")).get("passes") or []
    lines.append("- Passes run: " + (", ".join(kinds) if kinds else
                 "no ledger (passes.json); at least a broad first review, maybe gap or focused passes"))
    by_kind = collections.Counter(s.get("kind", "?") for s in known)
    lines.append("- Recorded seams by kind: " + ", ".join(f"{k} {n}" for k, n in by_kind.most_common()))
    lines += ["", "## Where earlier reviewers looked", ""]
    if not la.exists():
        return lines + ["Not known: no looked-at.json (`seams looked-at` writes it from the earlier sessions' "
                        "transcripts). Assume the general passes read most code files and few docs or configs."]
    doc = json.loads(la.read_text(encoding="utf-8"))
    try:
        files = {f["path"]: f["lines"] for f in load_leads(out)["files"] if not f.get("test")}
    except (OSError, ValueError, KeyError):
        files = {}
    read = set(doc.get("read") or {})
    total = sum(files.values()) or 1
    seen = sum(n for p, n in files.items() if p in read)
    lines.append(f"Reviewers opened {len(read)} files, {seen / total:.0%} of the non-test lines the scan reads. "
                 "Folders by the share of their lines anyone opened, least first:")
    lines.append("")
    for r in lookedat.summary(doc, files, depth=2, top=30):
        lines.append(f"- `{r['folder']}`: {r['files_read']} of {r['files']} files opened, "
                     f"{r['share_read']:.0%} of {r['code_lines']} lines")
    return lines


def archive_earlier_passes(out):
    """Move earlier passes' review files and drift-check results into done/<stamp>/.

    Their seams are in seams.json already. Left in place, a gap packet's review would
    overwrite the last gap pass's file of the same name, and the merge would read the old
    reviews again and reopen duplicate decisions an earlier pass settled. Returns the count."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    moved = 0
    for folder, pattern in ((out / "reviews", "seam-review-*.json"), (out / "verify" / "results", "*.json")):
        old = sorted(folder.glob(pattern)) if folder.is_dir() else []
        if old:
            dest = folder / "done" / stamp
            dest.mkdir(parents=True, exist_ok=True)
            for f in old:
                f.rename(dest / f.name)
                moved += 1
    return moved


def pass_bins(doc, max_lines=DEFAULT_MAX_LINES, new_only=False, cross_area_only=False, known=None, focus=None):
    """The leads a pass works from, and its packets. `known` (the seams of seams.json) makes a gap
    pass, and `focus` (a FOCUS key, with `known`) a focused pass. `write` and the cost estimate both
    use this, so the estimate prices the packets `seams split` writes."""
    lead_only = new_only or cross_area_only
    if focus is not None and (known is None or focus not in FOCUS):
        raise ValueError(f"--focus takes one of {', '.join(FOCUS)} and needs a registry from a first review.")
    if known is not None:
        if lead_only:
            raise ValueError("--gap and --focus are full passes: they do not combine with --new-only or "
                             "--cross-area-only.")
        if focus:
            # Every lead of the pass's kinds stays in: a recorded twin may still hold drift no one tested.
            doc = {**doc, "leads": [l for l in doc["leads"] if l["kind"] in FOCUS[focus]["kinds"]]}
        else:
            doc = {**doc, "leads": [l for l in doc["leads"] if not _fully_covered(l, known)]}
    # A focused pass is one reviewer for the whole repo: it reads what its leads point at.
    bins = plan(filter_leads(doc, new_only, cross_area_only), 10 ** 12 if focus else max_lines,
                lead_units_only=lead_only)
    if lead_only:
        bins = _drop_empty(bins)
    if known is not None:
        for b in bins:
            b["name"] = f"focus-{focus}" if focus else "gap-" + b["name"]
    return doc, bins


def write(doc, root, out, max_lines=DEFAULT_MAX_LINES, new_only=False, cross_area_only=False, known=None,
          focus=None):
    """Write the packets and plan.md. `known` (the seams of seams.json) makes a gap pass, and
    `focus` (a FOCUS key, with `known`) a focused pass."""
    out = Path(out).resolve()
    root = Path(root).resolve()
    lead_only = new_only or cross_area_only
    doc, bins = pass_bins(doc, max_lines, new_only, cross_area_only, known, focus)
    if known is not None:
        archive_earlier_passes(out)
    (out / "packets").mkdir(parents=True, exist_ok=True)
    (out / "reviews").mkdir(exist_ok=True)
    for old in (out / "packets").glob("*.md"):
        old.unlink()
    (out / "brief.md").write_text(BRIEF.read_text(encoding="utf-8"), encoding="utf-8")
    shown = []
    for b in bins:
        (out / "packets" / f"{b['name']}.md").write_text(packet_md(b, bins, root, out, lead_only, known, focus),
                                                       encoding="utf-8")
        shown += [l["fingerprint"] for l in shown_leads(b) if "fingerprint" in l]
    # The leads a reviewer was shown. `seams baseline` records these, not every lead:
    # a lead cut by the per-packet cap was never reviewed.
    (out / "shown.json").write_text(json.dumps(sorted(set(shown))) + "\n", encoding="utf-8")

    total = sum(b["lines"] for b in bins)
    shown_n = sum(len(shown_leads(b)) for b in bins)
    all_n = sum(len(b["leads"]) for b in bins)
    mode = (f"Focused pass ({focus}): one reviewer hunts {FOCUS[focus]['title']} across the whole repo, "
            f"starting from the {all_n} leads of that kind, {FOCUS[focus]['method']}." if focus
            else "Lead-only review: each reviewer checks its leads, not its whole areas." if lead_only
            else f"Gap pass: each reviewer sweeps its areas for seams the {len(known)} recorded in seams.json miss. "
                 "A lead is left out only when one recorded seam lists all its files." if known is not None
            else "Full review: each reviewer sweeps its areas, with the leads as hints.")
    rows = ["# Seam review plan", "",
            f"{len(bins)} packets, one reviewer agent each. {total} lines of non-test code.", "",
            f"Leads: {shown_n} shown in packets, of {all_n} in all. A packet shows at most {MAX_LEADS}, "
            "cross-area leads first. The rest stay in leads.json, and no reviewer sees them. "
            f"`seams baseline` records the shown leads as {len(set(shown))} fingerprints: leads of the "
            "same kind in the same files count once.", "",
            mode, "",
            "| Packet | Areas | Code lines | Leads shown | Leads in all |", "|---|---|---|---|---|"]
    for b in bins:
        over = " (over the limit: one flat folder that cannot split)" if b["lines"] > max_lines else ""
        rows.append(f"| {b['name']} | {len(b['units'])} | {b['lines']}{over} | "
                    f"{min(len(b['leads']), MAX_LEADS)} | {len(b['leads'])} |")
    rows += ["", "## Cost", ""]
    if focus:
        rows += ["A focused pass reads only what its leads and its own searches point at. " + FOCUS[focus]["cost"]]
    elif lead_only:
        rows += ["The cost of a lead-only review is not measured at scale yet. Start one packet "
                 "first and read its token use before you start the rest."]
    else:
        for effort, (tokens, minutes) in PER_PACKET.items():
            rows.append(f"- At {effort} effort: about {_tokens_n(tokens * len(bins))} tokens "
                        f"({_tokens_n(tokens)} per packet), about {minutes} minutes with the reviewers in parallel.")
        rows += ["", "Cost tracks the number of packets more than their size. Both rates come from one "
                 "run each on one repo, so treat them as a guide, not a quote."]
    skipped = doc.get("skipped_types") or {}
    unread = doc.get("skipped_files") or {}
    generated = doc.get("generated_files") or []
    if skipped or unread or generated:
        rows += ["", "## Not scanned", ""]
    if skipped:
        rows += ["The scan reads code, config, JSON and Markdown docs. These file types got no leads, so a reviewer sees them "
                 "only by opening them: " + ", ".join(f"{n} `.{k}`" if not k.startswith("(") else f"{n} {k}"
                                                     for k, n in skipped.items()) + "."]
    if unread:
        rows += ["", f"{len(unread)} file(s) of a type the scan reads were left unread. A reviewer should know they exist:", ""]
        rows += [f"- `{p}`: {why}" for p, why in sorted(unread.items())[:30]]
        if len(unread) > 30:
            rows.append(f"- and {len(unread) - 30} more, listed in leads.json under skipped_files")
    if generated:
        rows += ["", f"{len(generated)} file(s) say they are generated, so the scan skipped them. A generated file and "
                 "its source are a seam unless a build step always rewrites it:", ""]
        rows += [f"- `{p}`" for p in sorted(generated)[:30]]
    (out / "plan.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return bins


def _tokens(lines):
    return _tokens_n(lines * TOKENS_PER_LINE)


def _tokens_n(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k"


def load_leads(out):
    path = Path(out) / "leads.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if "files" not in doc:
        raise ValueError(f"{path} is from an older scan. Run `seams scan` again.")
    return doc
