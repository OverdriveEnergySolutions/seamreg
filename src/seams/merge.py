"""Turn the reviewers' output into registry entries, checking every claim.

    seams merge [--out DIR] [--plan merge.json] [--apply]
    seams apply [--out DIR] [--confirm id,id]

Reads <out>/reviews/seam-review-*.json and the repo's seams.json. Writes:

    <out>/seams.proposed.json   seams.json plus the new entries, never changing an existing one
    <out>/merge-report.md       what was dropped or flagged, and why
    <out>/private-findings.md   security detail the reviewers flagged; never goes in the registry

With --apply it also copies the proposal into seams.json, but only when the
proposal passes the check. `seams merge` rebuilds the proposal from the review
files every time, so a hand edit to seams.proposed.json does not survive it. To
keep hand edits, run `seams apply`: it copies seams.proposed.json as it stands.

A merge plan (JSON) settles what the merge cannot decide alone:

    {"absorb": {"dupe-id": "keep-id"}, "drop": ["id"], "rename": {"old-id": "new-id"},
     "distinct": [["id-a", "id-b"]], "extend": ["existing-id"], "confirm": ["id"]}

"confirm" marks an entry's drift as confirmed: someone checked that the copies
differ as stated. Drift found only by reading stays "reading".

Two entries with the same id are joined automatically. Two entries that share
two or more copies are reported as possible duplicates, and only a plan joins
them. "distinct" says two or more entries are different seams in the same files,
so the report stops asking. A list of any length settles every pair in it, so
one line can settle a whole cluster.

The merge never changes an entry already in seams.json on its own. When a
reviewer finds copies an existing seam does not list, the report names them,
and "extend" adds them to that entry.
"""
from __future__ import annotations

import collections
import datetime
import json
import re
from pathlib import Path

from seams import check

_TEXT = {"type": "string", "minLength": 1}
_OPT_TEXT = {"type": ["string", "null"]}

REVIEW_ENTRY = {
    "type": "object",
    "required": ["id", "title", "kind", "must_agree", "copies", "consequence", "risk"],
    "additionalProperties": False,
    "properties": {
        "id": _TEXT, "title": _TEXT, "must_agree": _TEXT, "consequence": _TEXT,
        "kind": {"enum": list(check.KINDS)},
        "copies": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["path"], "additionalProperties": False,
            "properties": {"path": _TEXT, "symbol": _OPT_TEXT, "line": {"type": ["integer", "null"]},
                           "note": _OPT_TEXT}}},
        "intentional_differences": _OPT_TEXT,
        "single_source": {"type": "boolean"},
        "ties": {"type": "array", "items": {
            "type": "object", "required": ["path", "covers"], "additionalProperties": False,
            "properties": {"path": _TEXT, "test": _OPT_TEXT, "covers": {"enum": ["all", "partial"]},
                           "note": _OPT_TEXT, "assert_line": _OPT_TEXT, "runs_in_ci": _OPT_TEXT}}},
        "tie_search": _OPT_TEXT,
        "drift": {"type": ["object", "null"], "required": ["text"], "additionalProperties": False,
                  # source and seen are accepted and ignored: a reviewer reads code, so its drift
                  # is always "reading" until someone confirms it.
                  "properties": {"text": _TEXT, "source": _OPT_TEXT, "seen": _OPT_TEXT}},
        "suggested_tie": _OPT_TEXT,
        "risk": {"enum": list(check.RISKS)},
        "risk_reason": _OPT_TEXT,
        "sensitive_finding": _OPT_TEXT,
    },
}
REVIEW_SCHEMA = {"type": "array", "items": REVIEW_ENTRY}
# A reviewer often sees a bug that is not a difference between copies: a missing comma that
# joins two names, a guard that checks the wrong field. Without a place for it, it reached
# only the reviewer's reply, and on netbox a confirmed drift was lost that way.
BUG_ENTRY = {
    "type": "object",
    "required": ["bug", "path"],
    "additionalProperties": False,
    "properties": {"bug": _TEXT, "path": _TEXT, "line": {"type": ["integer", "null"]},
                   "risk": {"enum": list(check.RISKS)}, "sensitive": {"type": "boolean"}},
}

RISK_ORDER = {r: i for i, r in enumerate(check.RISKS)}
PLAN_KEYS = ("absorb", "distinct", "drop", "rename", "extend", "confirm")
HUB_SEAMS = 6  # a file in this many entries is a hub (schema.sql): sharing it says little
NEAR_SAME = 0.75  # copy lists this alike are a possible duplicate even when every shared file is a hub
NEAR_SAME_MIN = 3  # ...if they share at least this many files. Two hub files alone say little.

# The sections the seams-review skill tells the user to settle. The report says "none" for each one that is empty,
# so a missing section never leaves the user guessing. The skill names them in step 5.
SETTLE = ["Possible duplicates", "Entries skipped", "Fields dropped", "Copies dropped", "Symbols dropped",
          "Seams dropped", "Ties dropped", "Ties kept without CI evidence", "Security findings",
          "High-risk drift to confirm first", "Drift the entry also calls deliberate",
          "Joined entries to read again", "Text to rewrite in a neutral voice", "Bugs outside the seam format"]
_VOICE = re.compile(
    r"\b(?:I|I've|I'm|we|We)\b\s+(?:ran|run|checked|found|searched|looked|grepped|read|verified|confirmed|saw)\b"
    r"|/tmp/|scratchpad|leads\.(?:md|json)|\bpacket\b|seam-review-", re.I)
_SLUG = re.compile(r"[^a-z0-9]+")
_PATHISH = re.compile(r"[\w.-]+(?:/[\w.-]+)+|[\w-]+\.[a-z]{1,5}\b")
# Every text field that reaches seams.json. A security finding's detail must stay out of all of them.
PRIVATE_HEADER = "# Private seam findings\n\nSecurity detail from the seam review. Keep this out of the repo.\n\n"
TEXT_FIELDS = ("title", "must_agree", "consequence", "intentional_differences", "suggested_tie")


def _slug(text):
    return _SLUG.sub("-", text.lower()).strip("-") or "seam"


class Report:
    def __init__(self):
        self.sections = {}

    def add(self, section, line):
        self.sections.setdefault(section, []).append(line)

    def render(self, summary):
        out = ["# Seam merge report", "", *summary]
        for title, lines in self.sections.items():
            out += ["", f"## {title}", ""] + [f"- {l}" for l in lines]
        empty = [s for s in SETTLE if not any(t.startswith(s) for t in self.sections)]
        if empty:
            out += ["", "## Checked, none found", ""] + [f"- {s}" for s in empty]
        return "\n".join(out) + "\n"


def read_reviews(out, report, findings=None):
    """[(source file, entry)] for every entry that matches REVIEW_ENTRY. A bug entry
    (BUG_ENTRY) goes to the report instead, or to `findings` when it is sensitive."""
    entries = []
    files = sorted((Path(out) / "reviews").glob("seam-review-*.json"))
    for f in files:
        try:
            data = check.load(f)
        except (ValueError, OSError) as e:
            report.add("Review files that could not be read", f"`{f.name}`: {e}")
            continue
        if not isinstance(data, list):
            report.add("Review files that could not be read", f"`{f.name}`: not a JSON array")
            continue
        for i, entry in enumerate(data):
            if isinstance(entry, dict) and "bug" in entry and "id" not in entry:
                _bug(entry, f"{f.name}[{i}]", report, findings)
                continue
            cleaned = clean_entry(entry, f"{f.name}[{i}]", report)
            if cleaned is not None:
                entries.append((f.name, cleaned))
    return files, entries


def _bug(entry, where, report, findings):
    errors = []
    check.validate(entry, BUG_ENTRY, where, errors)
    if errors:
        report.add("Entries skipped: wrong shape", "; ".join(errors[:2]))
        return
    loc = entry["path"] + (f":{entry['line']}" if entry.get("line") else "")
    risk = entry.get("risk", "unranked")
    if entry.get("sensitive") and findings is not None:
        findings.append(f"## Bug at {loc}\n\n{entry['bug']}\n")
        report.add("Bugs outside the seam format", f"`{loc}` ({risk}): security detail, in private-findings.md")
    else:
        report.add("Bugs outside the seam format", f"`{loc}` ({risk}): {entry['bug']}")


def clean_entry(entry, where, report):
    """The entry with bad optional parts dropped and reported, or None when a required
    field is bad. One stray field never costs a whole seam."""
    if not isinstance(entry, dict):
        report.add("Entries skipped: wrong shape", f"{where}: not an object")
        return None
    props = REVIEW_ENTRY["properties"]
    entry = dict(entry)
    for key in ("copies", "ties"):
        if not isinstance(entry.get(key), list):
            continue
        item_schema = props[key]["items"]
        kept = []
        for j, item in enumerate(entry[key]):
            if isinstance(item, dict):
                for k in [k for k in item if k not in item_schema["properties"]]:
                    report.add("Fields dropped: not in the review format", f"{where}.{key}[{j}].{k}")
                    item = {kk: v for kk, v in item.items() if kk != k}
            errors = []
            check.validate(item, item_schema, f"{where}.{key}[{j}]", errors)
            if errors:
                report.add(f"{key.capitalize()} dropped: wrong shape", "; ".join(errors[:2]))
            else:
                kept.append(item)
        entry[key] = kept
    for k in list(entry):
        if k not in props:
            report.add("Fields dropped: not in the review format", f"{where}.{k}")
            del entry[k]
            continue
        errors = []
        check.validate(entry[k], props[k], f"{where}.{k}", errors)
        if errors and k not in REVIEW_ENTRY["required"]:
            report.add("Fields dropped: wrong shape", "; ".join(errors[:2]))
            del entry[k]
    errors = []
    check.validate(entry, REVIEW_ENTRY, where, errors)
    if errors:
        report.add("Entries skipped: a required field is wrong", "; ".join(errors[:3]))
        return None
    return entry


def convert(entry, repo, report, findings, today):
    """A registry entry from one reviewer entry, with every claim checked. None to drop it."""
    sid = _slug(entry["id"])
    copies = []
    for c in entry["copies"]:
        path = c["path"]
        files, problem = repo.resolve(path)
        if problem and not check.path_problem(path.rstrip("/")) and (repo.root / path.rstrip("/")).is_dir():
            path = path.rstrip("/") + "/**/*"
            files, problem = repo.resolve(path)
            if not problem:
                report.add("Folder copies turned into globs", f"`{sid}`: `{c['path']}` is now `{path}`")
        if problem:
            report.add("Copies dropped: path not found", f"`{sid}`: `{c['path']}` {problem}")
            continue
        out = {"path": path}
        if c.get("symbol"):
            if len(c["symbol"]) >= 3 and repo.contains(files, c["symbol"]):
                out["symbol"] = c["symbol"]
            else:
                report.add("Symbols dropped: not in the file", f"`{sid}`: `{c['symbol']}` in `{c['path']}`")
        if c.get("note"):
            out["note"] = c["note"]
        if all(x["path"] != out["path"] for x in copies):
            copies.append(out)

    single = bool(entry.get("single_source", False))
    if len(copies) < (1 if single else 2):
        report.add("Seams dropped: too few copies left", f"`{sid}`: {len(copies)} real cop(ies)")
        return None

    ties = []
    for t in entry.get("ties", []):
        files, problem = repo.resolve(t["path"])
        ci = (t.get("runs_in_ci") or "").strip().lower()
        if problem:
            report.add("Ties dropped: file not found", f"`{sid}`: `{t['path']}` {problem}")
        elif t.get("test") and not repo.has_test(files, t["test"]):
            report.add("Ties dropped: test name not in the file", f"`{sid}`: `{t['test']}` in `{t['path']}`")
        elif ci.startswith("no") or re.search(r"\bnever\b|\bnot (?:run|in)\b", ci):
            report.add("Ties dropped: CI does not run them (check this claim)",
                       f"`{sid}`: `{t['path']}`: {t.get('runs_in_ci')}")
        elif t["covers"] == "partial" and not t.get("note"):
            report.add("Ties dropped: partial with no note", f"`{sid}`: `{t['path']}`")
        else:
            tie = {"path": t["path"], "covers": t["covers"]}
            for k in ("test", "note"):
                if t.get(k):
                    tie[k] = t[k]
            if not ci.startswith("yes"):
                report.add("Ties kept without CI evidence (check them)",
                           f"`{sid}`: `{t['path']}`: {t.get('runs_in_ci') or 'no runs_in_ci given'}")
            ties.append(tie)

    out = {"id": sid, "title": entry["title"], "kind": entry["kind"],
           "must_agree": entry["must_agree"], "copies": copies,
           "consequence": entry["consequence"], "risk": entry["risk"]}
    for k in ("intentional_differences", "suggested_tie"):
        if entry.get(k):
            out[k] = entry[k]
    if single:
        out["single_source"] = True
    if ties:
        out["ties"] = ties
    if entry.get("drift"):
        # Reviewers read code; they do not run it. Their drift is a lead until someone confirms it.
        out["drift"] = {"text": entry["drift"]["text"], "source": "reading", "seen": today}
    if entry.get("sensitive_finding"):
        findings.append(f"## {sid}\n\n{entry['sensitive_finding']}\n")
        texts = {f: out.get(f) for f in TEXT_FIELDS}
        texts["drift"] = out["drift"]["text"] if out.get("drift") else None
        for field, text in texts.items():
            if text:
                report.add("Security findings: check this text holds no exploit detail",
                           f"`{sid}`.{field}: {text}")
        out["sensitive"] = (f"A security finding from the seam review on {today} is kept out of this repo. "
                            "File it somewhere private and replace this line with a pointer to it.")
    texts = {f: out.get(f) for f in TEXT_FIELDS}
    texts["drift"] = out["drift"]["text"] if out.get("drift") else None
    for field, text in texts.items():
        m = _VOICE.search(text or "")
        if m:
            # Name the match: "packet" can be a ping packet, and then the text is right as it is.
            report.add("Text to rewrite in a neutral voice",
                       f"`{sid}`.{field}, flagged for \"{m.group(0)}\": {text[:120]}")
    return out


def _join(a, b):
    """Two texts as one, without saying the same thing twice."""
    if not a:
        return b
    if b.strip() in a:
        return a
    if a.strip() in b:
        return b
    return f"{a} {b}"


def _narrow(ties, owner, other_paths):
    """`ties` with each covers-all tie made partial when the joined entry has copies it never
    covered. A tie on two seed values does not tie every seed value. Returns (ties, downgraded)."""
    out, down = [], []
    for t in ties:
        if t["covers"] == "all" and other_paths:
            t = {**t, "covers": "partial",
                 "note": (t.get("note", "") + " " if t.get("note") else "")
                 + f"Covered every copy of `{owner}` before a join; not checked against "
                 + ", ".join(f"`{p}`" for p in sorted(other_paths)) + "."}
            down.append(t)
        out.append(t)
    return out, down


def absorb(keep, dupe, report=None):
    """Join `dupe` into `keep`: union of copies and ties, the higher risk, both drift notes.

    A covers-all tie from either side becomes partial when the other side brings copies
    it never covered. The report lists what the join could not decide: the absorbed
    entry's own must_agree, and texts that may now say one thing twice."""
    paths = {c["path"] for c in keep["copies"]}
    dupe_paths = {c["path"] for c in dupe["copies"]}
    keep_ties, down_k = _narrow(keep.get("ties", []), keep["id"], dupe_paths - paths)
    dupe_ties, down_d = _narrow(dupe.get("ties", []), dupe["id"], paths - dupe_paths)
    if keep_ties:
        keep["ties"] = keep_ties
    dupe = {**dupe, "ties": dupe_ties}
    if report is not None:
        for t in down_k + down_d:
            report.add("Joined entries to read again",
                       f"`{keep['id']}`: tie `{t['path']}`" + (f" (`{t['test']}`)" if t.get("test") else "")
                       + " now covers partial. If it does check every copy, set it back to all")
        if dupe["must_agree"].strip() != keep["must_agree"].strip():
            report.add("Joined entries to read again",
                       f"`{keep['id']}` absorbed `{dupe['id']}`, whose must_agree was: {dupe['must_agree']} "
                       "Fold it into the kept must_agree if the kept text no longer explains those copies")
        for k in ("intentional_differences", "drift"):
            a = (keep.get(k) or {}).get("text") if k == "drift" else keep.get(k)
            b = (dupe.get(k) or {}).get("text") if k == "drift" else dupe.get(k)
            if a and b and _join(a, b) not in (a, b):
                report.add("Joined entries to read again",
                           f"`{keep['id']}`.{k} now holds two texts. If they say one thing twice, keep one")
    keep["copies"] += [c for c in dupe["copies"] if c["path"] not in paths]
    seen = {(t["path"], t.get("test")) for t in keep.get("ties", [])}
    extra = [t for t in dupe.get("ties", []) if (t["path"], t.get("test")) not in seen]
    if extra:
        keep["ties"] = keep.get("ties", []) + extra
    if RISK_ORDER[dupe["risk"]] < RISK_ORDER[keep["risk"]]:
        keep["risk"] = dupe["risk"]
    for k in ("intentional_differences", "suggested_tie", "sensitive"):
        if dupe.get(k):
            keep[k] = _join(keep.get(k), dupe[k])
    if dupe.get("drift"):
        if keep.get("drift"):
            keep["drift"]["text"] = _join(keep["drift"]["text"], dupe["drift"]["text"])
        else:
            keep["drift"] = dupe["drift"]
    if dupe.get("single_source") and not keep.get("single_source"):
        keep["single_source"] = True


def report_duplicates(by_id, existing, distinct, report):
    """Pairs of new entries that share two or more copies, grouped into clusters.

    A file listed by many entries (a schema file, a migration runner) is a hub.
    Pairs that share only hubs are usually different knowledge, so they go in a
    short section of their own instead of each needing a decision. The exception:
    two entries whose copy lists are nearly the same are a possible duplicate even
    when every file is a hub. Duplicates make their own files look like hubs."""
    use = collections.Counter(c["path"] for e in list(by_id.values()) + existing for c in e["copies"])
    hubs = {p for p, n in use.items() if n >= HUB_SEAMS}
    strong, weak = [], 0
    ids = sorted(by_id)
    for i, a in enumerate(ids):
        pa = {c["path"] for c in by_id[a]["copies"]}
        for b in ids[i + 1:]:
            pb = {c["path"] for c in by_id[b]["copies"]}
            shared = pa & pb
            if len(shared) < 2 or frozenset((a, b)) in distinct:
                continue
            near_same = len(shared) >= NEAR_SAME_MIN and len(shared) / len(pa | pb) >= NEAR_SAME
            if shared <= hubs and not near_same:
                weak += 1
            else:
                strong.append((a, b, shared))
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _ in strong:
        parent[find(a)] = find(b)
    clusters = collections.defaultdict(list)
    for a, b, shared in strong:
        clusters[find(a)].append((a, b, shared))
    title = "Possible duplicates: settle each cluster with a plan (absorb, or distinct)"
    for n, pairs in enumerate(sorted(clusters.values(), key=lambda ps: -len(ps)), 1):
        members = sorted({x for a, b, _ in pairs for x in (a, b)})
        lines = [f"cluster {n}, {len(members)} entries:"]
        lines += [f"  - `{m}`: {by_id[m]['title']}. {by_id[m]['must_agree']}" for m in members]
        lines += [f"  - pair `{a}` and `{b}` share {', '.join(f'`{p}`' for p in sorted(s - hubs) or sorted(s))}"
                  f" ({len(s)} of {len(by_id[a]['copies'])} and {len(s)} of {len(by_id[b]['copies'])} copies)"
                  + (" (hub files only, but nearly the same copy list)" if s <= hubs else "")
                  for a, b, s in pairs]
        lines.append("  - if every pair is different knowledge, one plan line settles the cluster: "
                     f'`"distinct": [{json.dumps(members)}]`')
        report.add(title, "\n".join(lines))
    if weak:
        report.add("Pairs that share only hub files (usually different knowledge; no decision needed)",
                   f"{weak} pairs share only files listed by {HUB_SEAMS} or more entries. "
                   f"The {len(hubs)} hub files: "
                   + ", ".join(f"`{h}` ({use[h]})" for h in sorted(hubs)))


def merge(root, out, plan=None, today=None):
    """Returns (proposed registry, report text, private findings text, check errors)."""
    root, out = Path(root), Path(out)
    today = today or datetime.date.today().isoformat()
    plan = plan or {}
    report = Report()
    repo = check.Repo(root)

    reg_path = root / check.REGISTRY
    existing = check.load(reg_path) if reg_path.exists() else {"schema_version": 1, "seams": []}
    known = {s["id"] for s in existing["seams"]}

    findings = []
    files, raw = read_reviews(out, report, findings)
    by_id = {}
    for source, entry in raw:
        e = convert(entry, repo, report, findings, today)
        if e is None:
            continue
        e["id"] = plan.get("rename", {}).get(e["id"], e["id"])
        if e["id"] in by_id:
            report.add("Joined: same id from two reviewers", f"`{e['id']}` (from `{source}`)")
            absorb(by_id[e["id"]], e, report)
        else:
            by_id[e["id"]] = e

    for dupe, keep in plan.get("absorb", {}).items():
        if dupe in by_id and keep in by_id and dupe != keep:
            absorb(by_id[keep], by_id.pop(dupe), report)
            report.add("Joined by the plan", f"`{dupe}` into `{keep}`")
        else:
            report.add("Plan entries that matched nothing", f"absorb `{dupe}` into `{keep}`")
    for sid in plan.get("drop", []):
        if by_id.pop(sid, None) is None:
            report.add("Plan entries that matched nothing", f"drop `{sid}`")

    existing_by_id = {s["id"]: s for s in existing["seams"]}
    extend = set(plan.get("extend", []))
    new = []
    for sid, e in by_id.items():
        if sid not in known:
            new.append(e)
            continue
        old = existing_by_id[sid]
        extra = [c for c in e["copies"]
                 if not any(check.copy_matches(o["path"], c["path"]) for o in old["copies"])]
        # Drift a reviewer found on a recorded seam is news even when it found no new copy: the gap
        # passes on umami and frigate found key drift this way, and the merge used to drop it.
        found = (e.get("drift") or {}).get("text", "").strip()
        new_drift = bool(found) and found not in ((old.get("drift") or {}).get("text") or "")
        if not extra and not new_drift:
            report.add("Already in seams.json, nothing new: kept the existing entry", f"`{sid}`")
            continue
        names = ", ".join("`" + c["path"] + "`" for c in extra)
        if sid not in extend:
            if extra:
                report.add("Existing seams with copies they do not list: add them with \"extend\" in a plan",
                           f"`{sid}`: {names}")
            if new_drift:
                report.add("Drift found on seams already in seams.json: add it with \"extend\" in a plan",
                           f"`{sid}`: {found}")
            continue
        if extra:
            old["copies"] = old["copies"] + extra
            report.add("Existing seams extended by the plan", f"`{sid}`: added {names}")
            if e["must_agree"].strip() != old["must_agree"].strip():
                report.add("Joined entries to read again",
                           f"`{sid}` was extended. The reviewer's must_agree was: {e['must_agree']} "
                           "Fold it in if the kept text no longer explains the new copies")
        # An extend is a join: what the reviewer wrote must not vanish with it.
        if new_drift and not old.get("drift"):
            old["drift"] = e["drift"]
            report.add("Joined entries to read again", f"`{sid}`: the extend added the reviewer's drift (reading): {found}")
        elif new_drift:
            unconfirmed = " (found by reading, not confirmed)" if old["drift"].get("source") == "confirmed" else ""
            old["drift"]["text"] = old["drift"]["text"].rstrip() + f" A later review also found{unconfirmed}: {found}"
            report.add("Joined entries to read again",
                       f"`{sid}`: the extend appended the reviewer's drift to the recorded drift: {found} "
                       "If both describe one difference, keep one of them")
    for sid in extend - known:
        report.add("Plan entries that matched nothing", f"extend `{sid}`")

    distinct = {frozenset((a, b)) for group in plan.get("distinct", [])
                for i, a in enumerate(group) for b in group[i + 1:]}
    report_duplicates(by_id, existing["seams"], distinct, report)

    for e in new:
        pa = {c["path"] for c in e["copies"]}
        for s in existing["seams"]:
            shared = [p for p in pa if any(check.copy_matches(c["path"], p) for c in s["copies"])]
            if len(shared) >= 2 and frozenset((e["id"], s["id"])) not in distinct:
                report.add("Possible duplicates of seams already in seams.json",
                           f"new `{e['id']}` and existing `{s['id']}` share "
                           + ", ".join(f"`{p}`" for p in sorted(shared)))

    for sid in plan.get("confirm", []):
        target = by_id.get(sid) if sid not in known else existing_by_id.get(sid)
        if target is not None and target.get("drift"):
            target["drift"]["source"] = "confirmed"
            target["drift"]["seen"] = today
            report.add("Drift confirmed by the plan", f"`{sid}`")
        else:
            report.add("Plan entries that matched nothing", f"confirm `{sid}` (no such entry with drift)")
    for k in plan:
        if k not in PLAN_KEYS:
            report.add("Plan entries that matched nothing", f"unknown plan key `{k}`. Known: {', '.join(PLAN_KEYS)}")

    new.sort(key=lambda e: (RISK_ORDER[e["risk"]], e["id"]))
    proposed = {**{k: v for k, v in existing.items() if k != "seams"}, "seams": existing["seams"] + new}
    errors = check.check(proposed, root)

    drift = [e for e in new if e.get("drift")]
    confirmed = [e for e in drift if e["drift"]["source"] == "confirmed"]
    for e in new:
        if e.get("drift") and e.get("intentional_differences"):
            both = set(_PATHISH.findall(e["drift"]["text"])) & set(_PATHISH.findall(e["intentional_differences"]))
            if both:
                report.add("Drift the entry also calls deliberate",
                           f"`{e['id']}`: drift and intentional_differences both name "
                           + ", ".join(f"`{x}`" for x in sorted(both))
                           + ". If they describe one difference, keep it in one field")
    summary = [
        f"{len(files)} review files, {len(raw)} entries read, {len(new)} new seams proposed "
        f"({sum(e['risk'] == 'high' for e in new)} high, {sum(e['risk'] == 'medium' for e in new)} medium, "
        f"{sum(e['risk'] == 'low' for e in new)} low).",
        "",
        f"{sum(1 for e in new if any(t['covers'] == 'all' for t in e.get('ties', [])))} fully tied, "
        f"{sum(1 for e in new if e.get('ties') and not any(t['covers'] == 'all' for t in e['ties']))} partly, "
        f"{sum(1 for e in new if not e.get('ties'))} not at all. {len(drift)} carry drift: "
        f"{len(drift) - len(confirmed)} found by reading, {len(confirmed)} confirmed by the plan.",
        "",
        "Drift found by reading is a lead, not a confirmed bug. Check the high-risk ones by hand or at "
        "runtime before anyone calls them bugs.",
    ]
    if errors:
        summary += ["", "**The proposal does not pass the check:**", ""] + [f"- {e}" for e in errors]
    for e in drift:
        if e["risk"] == "high" and e["drift"]["source"] == "reading":
            report.add("High-risk drift to confirm first", f"`{e['id']}`: {e['drift']['text']}")
    private = (PRIVATE_HEADER + "\n".join(findings)) if findings else ""
    return proposed, report.render(summary), private, errors


def write_private(path, header, text):
    """Write the `## ...` sections of `text` to a private findings file, keeping every section
    an earlier pass or run wrote there. A new section replaces the old one with the same heading.
    Nothing is ever deleted: a gap pass moves the earlier reviews aside, and a rewrite from the
    current reviews alone once left only placeholders pointing at lost detail.
    Returns True when the file holds any section."""
    def sections(t):
        return {b.split("\n", 1)[0]: b.rstrip("\n") + "\n"
                for b in re.split(r"(?m)^(?=## )", t or "") if b.startswith("## ")}
    path = Path(path)
    old = sections(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = {**old, **sections(text)}
    if merged:
        path.write_text(header + "\n".join(merged.values()), encoding="utf-8")
    return bool(merged)


def apply_proposal(root, out, confirm=(), today=None):
    """Copy <out>/seams.proposed.json, hand edits and all, into seams.json when it passes
    the check. Returns the check's errors; nothing is written unless they are empty.

    `confirm` marks those seams' drift as confirmed first. It is the route for drift the
    drift check found: a merge would rebuild the proposal and lose it."""
    today = today or datetime.date.today().isoformat()
    prop_path = Path(out) / "seams.proposed.json"
    proposed = check.load(prop_path)
    if confirm:
        by_id = {s["id"]: s for s in proposed.get("seams", [])}
        bad = [i for i in confirm if not (by_id.get(i) or {}).get("drift")]
        if bad:
            return proposed, [f"--confirm: no seam with drift has the id {', '.join(bad)}"]
        for i in confirm:
            by_id[i]["drift"].update(source="confirmed", seen=today)
        prop_path.write_text(json.dumps(proposed, indent=2) + "\n", encoding="utf-8")
    reg_path = Path(root) / check.REGISTRY
    if reg_path.exists():
        # Settings set in seams.json after the proposal was written (such as "notes") survive.
        current = check.load(reg_path)
        proposed = {**{k: v for k, v in current.items() if k != "seams"}, **proposed}
    errors = check.check(proposed, root)
    if not errors:
        (Path(root) / check.REGISTRY).write_text(json.dumps(proposed, indent=2) + "\n", encoding="utf-8")
    return proposed, errors


def write(root, out, plan_path=None, apply=False):
    out = Path(out)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8")) if plan_path else None
    proposed, report, private, errors = merge(root, out, plan)
    (out / "seams.proposed.json").write_text(json.dumps(proposed, indent=2) + "\n", encoding="utf-8")
    (out / "merge-report.md").write_text(report, encoding="utf-8")
    write_private(out / "private-findings.md", PRIVATE_HEADER, private)
    applied = False
    if apply and not errors:
        (Path(root) / check.REGISTRY).write_text(json.dumps(proposed, indent=2) + "\n", encoding="utf-8")
        applied = True
    return proposed, errors, bool(private), applied
