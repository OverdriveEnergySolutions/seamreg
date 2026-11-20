"""The mechanical pre-scan: cheap leads for the reviewers, no agent and no network.

    seams scan [--root DIR] [--out DIR] [--new] [--since REF]

Writes two files to the out folder (default .seams-scan/ in the repo root):

    leads.json   every lead, for the next stage (split). Format: LEADS_VERSION.
    leads.md     the same leads for a person or an agent, strongest first.

The out folder holds a .gitignore of "*", so it never gets committed.

When the repo has a seams.json, each lead records the registered seams that
already cover it ("covered_by"), and the report says how many registered seams
the scan found. When it has a seams.baseline.json, each lead records whether
a past review already saw it ("seen"). A lead is new when neither is true.
--new lists only new leads in leads.md. --since REF keeps
only leads that touch a file changed since the merge base with REF: the leads a
branch may have created.

Leads are hints. Many are noise, and the scan misses seams that leave no
textual trace. A reviewer decides what is a seam.
"""
from __future__ import annotations

import collections
import hashlib
import json
import time
from pathlib import Path

from seams import check
from seams.scan import (cochange, conventions, dataflow, dupblocks, formats, keywriters, litsets, markers, names, packaging,
                        sharedids, siblings, ties, twins)
from seams.scan.inventory import Inventory, is_test, kind_of

LEADS_VERSION = 1
BASELINE = "seams.baseline.json"
BASELINE_VERSION = 1


def fingerprint(lead):
    """A lead's identity across scans: its kind and its files, without line numbers,
    so an ordinary edit does not make an old lead look new."""
    key = "\0".join([lead["kind"], *sorted({f["path"] for f in lead["files"]})])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def is_new(lead):
    return not lead.get("covered_by") and not lead.get("seen")


def load_baseline(path):
    """The set of reviewed fingerprints in a baseline file. Raises ValueError on a bad file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("baseline_version") != BASELINE_VERSION \
            or not isinstance(data.get("leads"), list) or not all(isinstance(x, str) for x in data["leads"]):
        raise ValueError(f"{path} is not a seams baseline (baseline_version {BASELINE_VERSION})")
    return set(data["leads"])


def write_baseline(path, fingerprints):
    body = {"baseline_version": BASELINE_VERSION,
            "about": "Leads a seam review already saw, kept or rejected. Written by `seams baseline` "
                     "and `seams merge --apply`. A re-scan treats these as old.",
            "leads": sorted(fingerprints)}
    Path(path).write_text(json.dumps(body, indent=0) + "\n", encoding="utf-8")
DETECTORS = [markers, dupblocks, names, litsets, conventions, siblings, twins, formats, packaging, sharedids, keywriters, dataflow, cochange, ties]
KINDS = {  # kind: what it is, for the report headings. Order is report order.
    "marker": "Comments that say two places must agree",
    "literal-set": "The same list of names in two files",
    "convention": "A pattern most members of a family follow, and the members that break it",
    "sibling": "Classes that share a base, and a counterpart of one that lacks a field the others carry",
    "twin": "Two implementations of one behavior: alike patterns, files in two languages, one copy per backend",
    "packaging": "What the image or the build ships against the code and its manifests: pinned versions, runtime files, engine versions",
    "date-format": "A named date format, and code beside its users that writes dates another way",
    "dupblock": "Code copied between files",
    "same-constant": "The same constant name in two or more areas",
    "same-name": "The same function or class name in two or more areas",
    "env-name": "The same env var in two or more areas",
    "same-file": "The same file name in two or more areas",
    "shared-ids": "Code in two folders that uses the same rare names (fields, columns, settings)",
    "key-writers": "Every file that writes the same key: they must build the same shape",
    "flow": "A rare key one file writes and another file reads",
    "access": "Two files that decide who may do what, with the same rare names",
    "co-change": "Files in different folders that keep changing in the same commits",
    "tie-candidate": "Tests that may already tie copies",
}
MD_LIMIT = 200  # leads per section in leads.md; leads.json holds all of them


def _lead_json(lead, inv):
    files = []
    for path, line, end in lead.locs:
        f = {"path": path}
        if line:
            f["line"] = line
        if end and end != line:
            f["end"] = end
        files.append(f)
    areas = sorted({inv.area(p) for p, _, _ in lead.locs})
    out = {"kind": lead.kind, "files": files, "areas": areas, "cross_area": len(areas) > 1,
           "touches_tests": any(is_test(p) for p, _, _ in lead.locs),
           "score": lead.score, "detail": lead.detail}
    if lead.extra:
        out["extra"] = lead.extra
    return out


def _sort_key(lead):
    # cross-area first, then code over tests, then strongest
    return (not lead["cross_area"], lead["touches_tests"], -lead["score"],
            lead["files"][0]["path"], lead["files"][0].get("line", 0))


def covering_seams(lead, seams):
    """Ids of registered seams that already account for `lead`.

    A seam covers a lead when its copies or ties name at least two of the
    lead's files, or the only file of a one-file lead."""
    paths = [f["path"] for f in lead["files"]]
    need = min(2, len(paths))
    out = []
    for s in seams:
        patterns = [c["path"] for c in s["copies"]] + [t["path"] for t in s.get("ties", [])]
        if sum(any(check.copy_matches(pt, p) for pt in patterns) for p in paths) >= need:
            out.append(s["id"])
    return out


def _counts(leads):
    counts = {k: {"all": 0, "cross_area": 0, "new": 0} for k in KINDS}
    for l in leads:
        c = counts[l["kind"]]
        c["all"] += 1
        c["cross_area"] += l["cross_area"]
        c["new"] += is_new(l)
    return counts


def scan(root, registry=None, since=None, baseline=None):
    """Scan the repo at `root`. Returns the leads.json document.

    registry: a parsed seams.json, to mark the leads it already covers.
    since: a git ref; keep only leads that touch a file changed since its merge base.
    baseline: a set of fingerprints a past review saw, to mark those leads as seen."""
    started = time.time()
    inv = Inventory(root)
    leads = []
    for detector in DETECTORS:
        leads += [_lead_json(l, inv) for l in detector.find(inv)]
    leads.sort(key=lambda l: (list(KINDS).index(l["kind"]), _sort_key(l)))

    reg_info = None
    if registry is not None:
        found = set()
        for lead in leads:
            lead["covered_by"] = covering_seams(lead, registry["seams"])
            found.update(lead["covered_by"])
        ids = [s["id"] for s in registry["seams"]]
        reg_info = {"seams": len(ids), "found_by_scan": [i for i in ids if i in found],
                    "missed_by_scan": [i for i in ids if i not in found]}
    for lead in leads:
        lead["fingerprint"] = fingerprint(lead)
        if baseline is not None:
            lead["seen"] = lead["fingerprint"] in baseline
    since_info = None
    if since:
        changed = set(check._git_changed(root, since))
        leads = [l for l in leads if any(f["path"] in changed for f in l["files"])]
        since_info = {"ref": since, "changed_files": len(changed)}

    return {
        "leads_version": LEADS_VERSION,
        "file_source": inv.source,
        "files_listed": len(inv.files),
        "files_read": len(inv.read),
        "lines_read": inv.lines(),
        "generated_files": inv.generated,
        "skipped_files": inv.skipped,
        "skipped_types": dict(collections.Counter(
            (p.rsplit(".", 1)[-1] if "." in p.rsplit("/", 1)[-1] else "(no extension)")
            for p in inv.files if p not in set(inv.read) and p not in set(inv.generated)
            and p not in inv.skipped and p not in set(inv.own)).most_common(12)),
        "areas": [{"area": a, "files": n, "lines": l} for a, n, l in inv.areas()],
        "files": [{"path": p, "area": inv.area(p), "lines": inv.text(p).count("\n") + 1,
                   "test": is_test(p), "doc": kind_of(p) == "doc"} for p in inv.read],
        "registry": reg_info,
        "baseline": None if baseline is None else {"leads": len(baseline)},
        "since": since_info,
        "counts": _counts(leads),
        "seconds": round(time.time() - started, 1),
        "leads": leads,
    }


def _loc(f):
    s = f["path"]
    if "line" in f:
        s += f":{f['line']}"
        if "end" in f:
            s += f"-{f['end']}"
    return s


def render_md(doc, only_new=False):
    out = ["# Seam scan leads", "",
           "Leads are hints from a mechanical scan. Many are noise. Open every copy before "
           "you call something a seam, and look past these leads too.", "",
           f"{doc['files_read']} files read ({doc['lines_read']} lines) of {doc['files_listed']} listed, "
           f"from {doc['file_source']}. {len(doc['generated_files'])} generated files skipped."]
    reg = doc.get("registry")
    if reg:
        out += ["", f"seams.json lists {reg['seams']} seams. The scan has a lead for "
                f"{len(reg['found_by_scan'])} of them."]
        if reg["missed_by_scan"]:
            out.append("No lead points at: " + ", ".join(f"`{i}`" for i in reg["missed_by_scan"][:30])
                       + (" and more." if len(reg["missed_by_scan"]) > 30 else "."))
    if doc.get("baseline"):
        out += ["", f"seams.baseline.json holds {doc['baseline']['leads']} leads a past review already saw."]
    if only_new:
        out += ["", "This list shows only new leads: no registered seam covers them, and no past review saw them."]
    if doc.get("since"):
        out += ["", f"Only leads that touch the {doc['since']['changed_files']} files changed since "
                f"`{doc['since']['ref']}`."]
    out += ["", "## Areas", "", "| Area | Files | Lines |", "|---|---|---|"]
    out += [f"| `{a['area']}` | {a['files']} | {a['lines']} |" for a in doc["areas"]]
    for kind, title in KINDS.items():
        rows = [l for l in doc["leads"] if l["kind"] == kind and not (only_new and not is_new(l))]
        c = doc["counts"][kind]
        new = f" {c['new']} new." if reg or doc.get("baseline") else ""
        out += ["", f"## {title}", "", f"{c['all']} leads, {c['cross_area']} across areas.{new}", ""]
        for l in rows[:MD_LIMIT]:
            tags = (" [cross-area]" if l["cross_area"] else "") + (" [test]" if l["touches_tests"] else "")
            tags += f" [covered: {', '.join(l['covered_by'])}]" if l.get("covered_by") else ""
            tags += " [seen]" if l.get("seen") else ""
            out.append(f"- {'  <->  '.join(_loc(f) for f in l['files'])}{tags}  \n  {l['detail']}")
        if len(rows) > MD_LIMIT:
            out.append(f"- ... {len(rows) - MD_LIMIT} more in leads.json")
    return "\n".join(out) + "\n"


def write(doc, out_dir, only_new=False):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("*\n", encoding="utf-8")
    (out / "leads.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    (out / "leads.md").write_text(render_md(doc, only_new), encoding="utf-8")
    stale = out / "shown.json"  # what an older split showed; a new scan makes it wrong
    if stale.exists():
        stale.unlink()
