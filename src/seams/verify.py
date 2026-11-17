"""Check whether each seam's copies agree today: one small agent per seam.

    seams verify [--registry FILE] [--risk high,medium] [--ids a,b] [--all] [--reading] [--sample N]
    seams verify --collect [--registry FILE]                           read the results

Reviewers in a full review often find a seam but miss that its copies already
differ. This pass gives one focused agent one seam, and asks only "do the copies
agree today?" It writes to <out>/verify/:

    brief.md                   the drift check brief, the same for every packet
    packets/<id>.md            one packet per seam
    results/<id>.json          where each seam-drift-checker agent writes its answer

--collect writes the drift it finds into the registry (seams.json, or the
proposal with --registry), as drift found by reading. It never touches a seam
that already records drift, and it never deletes drift.

--reading checks seams whose recorded drift was found only by reading, to get a
second opinion before anyone confirms it. Its packets do not show the recorded
drift, so the checker judges from the code. --collect then reports whether the
checker saw a difference too. It changes nothing: confirming stays a person's call.
"""
from __future__ import annotations

import datetime
import json
import random
import re
from pathlib import Path

from seams import check

BRIEF = Path(__file__).with_name("verify-brief.md")
_TEXT = {"type": "string", "minLength": 1}
_OPT_TEXT = {"type": ["string", "null"]}
RESULT = {
    "type": "object",
    "required": ["id", "agree", "checked"],
    "additionalProperties": False,
    "properties": {"id": _TEXT, "agree": {"type": "boolean"}, "drift": _OPT_TEXT,
                   "checked": _TEXT, "sensitive_finding": _OPT_TEXT},
}


RISK_ORDER = ("high", "medium", "low")

# Measured drift-check cost per seam at default effort: 46k to 113k tokens over 6 seams, 64k on
# average over 13 more. At max: 87k to 242k over 15 seams, 169k on average. 2 to 10 minutes each.
COST_DEFAULT = (46_000, 64_000, 113_000)
COST_MAX = (87_000, 169_000, 242_000)
MINUTES = (2, 10)
_LOCATION = re.compile(r"[\w./-]+\.\w+:\d+")


def cost_text(n):
    """What `n` drift-check packets cost, from the measured rates above."""
    lo, mid, hi = COST_DEFAULT
    mlo, mmid, mhi = COST_MAX
    k = lambda x: f"{round(x / 1000):,}k"
    return (f"Cost at default effort: about {k(n * mid)} tokens ({k(n * lo)} to {k(n * hi)}). "
            f"At max: about {k(n * mmid)} ({k(n * mlo)} to {k(n * mhi)}). Each checker takes "
            f"{MINUTES[0]} to {MINUTES[1]} minutes, and they run in parallel. Measured on {6 + 13 + 15} seams in "
            "three repos.")


def select(data, risks=("high", "medium"), ids=None, every=False, sample=None, seed=0, reading=False):
    """The seams to check: by default high and medium risk with no drift recorded. With
    `reading`, the seams in `risks` whose drift was found only by reading.

    Medium is in the default because a medium seam held a confirmed bug that two full
    reviews missed. A convention seam with no drift is checked at any risk: its rule covers
    many members, a reviewer may have checked only some, and on netbox the low-risk ones
    held real drift. With `sample`, at most that many: higher risk first, and a random pick
    within the risk level that does not fit (the same seed gives the same pick)."""
    out = []
    for s in data["seams"]:
        if ids is not None:
            if s["id"] in ids:
                out.append(s)
        elif reading:
            if s["risk"] in risks and (s.get("drift") or {}).get("source") == "reading":
                out.append(s)
        elif every or (not s.get("drift") and (s["risk"] in risks or s.get("kind") == "convention")):
            out.append(s)
    if sample is not None and sample < len(out):
        rng, keep = random.Random(seed), set()
        for risk in RISK_ORDER:
            level = [s for s in out if s["risk"] == risk]
            room = sample - len(keep)
            keep |= {s["id"] for s in (level if len(level) <= room else rng.sample(level, room))}
        out = [s for s in out if s["id"] in keep]
    return out


def packet_md(seam, root, out):
    result = out / "verify" / "results" / f"{seam['id']}.json"
    copies = "\n".join(f"- `{c['path']}`" + (f" (`{c['symbol']}`)" if c.get("symbol") else "")
                       for c in seam["copies"])
    lines = [f"# Drift check: {seam['id']}", "",
             f"Read the brief first: `{out / 'verify' / 'brief.md'}`.", "",
             f"- Repo root: `{root}`",
             f"- Output file: `{result}`", "",
             f"## {seam['title']}", "",
             f"**Must agree:** {seam['must_agree']}", "",
             f"**If one copy changes alone:** {seam['consequence']}", "",
             "**Copies:**", "", copies]
    if seam.get("intentional_differences"):
        lines += ["", f"**Deliberate differences, ignore these:** {seam['intentional_differences']}"]
    if seam.get("ties"):
        lines += ["", "**Ties (checks that should fail when the copies drift):**", ""]
        lines += [f"- `{t['path']}`" + (f" (`{t['test']}`)" if t.get("test") else "") + f", covers {t['covers']}"
                  for t in seam["ties"]]
    return "\n".join(lines) + "\n"


def _load_valid(registry_path):
    """The registry, refused when it fails the schema. The schema's id pattern is what
    keeps a seam id from naming a path outside the packets folder."""
    data = check.load(registry_path)
    errors = check.validate_errors(data)
    if errors:
        raise ValueError(f"{registry_path} does not match the schema: {'; '.join(errors[:3])}")
    return data


def _inside(folder, name):
    path = (folder / name).resolve()
    path.relative_to(folder.resolve())  # raises ValueError when the name leaves the folder
    return path


def write_packets(registry_path, root, out, risks=("high", "medium"), ids=None, every=False, sample=None, seed=0,
                  reading=False):
    """Replaces the packet set: packets from an earlier run are deleted first."""
    data = _load_valid(registry_path)
    root, out = Path(root).resolve(), Path(out).resolve()
    if ids is not None:
        # Checked before the old packets go: a gap pass once ran --ids against seams.json, where its
        # new seams were not yet, got 0 packets, exited 0 and lost the packets it had.
        missing = sorted(set(ids) - {s["id"] for s in data["seams"]})
        if missing:
            raise ValueError(f"{registry_path} has no seam with the id {', '.join(missing)}. New seams are in "
                             "the proposal until `seams apply`: add --registry .seams-scan/seams.proposed.json")
    chosen = select(data, risks, ids, every, sample, seed, reading)
    d = out / "verify"
    (d / "packets").mkdir(parents=True, exist_ok=True)
    (d / "results").mkdir(exist_ok=True)
    for old in (d / "packets").glob("*.md"):
        old.unlink()
    (d / "brief.md").write_text(BRIEF.read_text(encoding="utf-8"), encoding="utf-8")
    for s in chosen:
        _inside(d / "packets", f"{s['id']}.md").write_text(packet_md(s, root, out), encoding="utf-8")
    return chosen


SENSITIVE_DRIFT = ("The copies differ in a way with a security impact. The detail is in the drift check's private "
                   "findings. Rewrite this as the behavior that differs before the registry is committed.")


def collect(registry_path, out, today=None):
    """Write the drift the checkers found into the registry.
    Returns (report lines, private findings, schema errors, counts)."""
    today = today or datetime.date.today().isoformat()
    data = _load_valid(registry_path)
    by_id = {s["id"]: s for s in data["seams"]}
    lines, private = [], []
    counts = {"files": 0, "drift": 0, "sensitive": 0}
    for f in sorted((Path(out) / "verify" / "results").glob("*.json")):
        counts["files"] += 1
        try:
            res = check.load(f)
        except (ValueError, OSError) as e:
            lines.append(f"- `{f.name}`: could not be read: {e}")
            continue
        errors = []
        check.validate(res, RESULT, f.name, errors)
        if errors:
            lines.append(f"- `{f.name}`: wrong shape: {'; '.join(errors[:2])}")
            continue
        seam = by_id.get(res["id"])
        if seam is None:
            lines.append(f"- `{res['id']}`: no such seam in the registry")
            continue
        if res["agree"]:
            lines.append(f"- `{res['id']}`: copies agree. {res['checked']}")
            if seam.get("drift"):
                lines.append(f"  **the registry records drift here ({seam['drift']['source']}), and the drift "
                             "check found none.** Read both sides. If the recorded drift is wrong, remove it")
        elif not res.get("drift"):
            lines.append(f"- `{res['id']}`: says the copies differ but gives no drift text; nothing written")
        elif seam.get("drift"):
            # A second opinion on recorded drift. It changes nothing: confirming is a person's call.
            lines.append(f"- `{res['id']}`: already records drift ({seam['drift']['source']}), and the drift "
                         f"check saw a difference too: {res['drift']} If both describe the same difference, "
                         f"confirm it with `seams apply --confirm {res['id']}`")
        elif res.get("sensitive_finding"):
            # A checker's drift text for a security hole often says how to use it, and it would land in
            # a committed file (frigate). Keep it private and record a neutral placeholder.
            seam["drift"] = {"text": SENSITIVE_DRIFT, "source": "reading", "seen": today}
            counts["drift"] += 1
            private.append(f"## {res['id']} (drift text)\n\n{res['drift']}\n")
            lines.append(f"- `{res['id']}`: **drift found**, with a security impact. The checker's text is in the "
                         "private file. Replace the placeholder in the registry with the behavior that differs "
                         "(\"one route checks the role, the other does not\"), not how to use it")
        else:
            seam["drift"] = {"text": res["drift"], "source": "reading", "seen": today}
            counts["drift"] += 1
            lines.append(f"- `{res['id']}`: **drift found**: {res['drift']}")
            # One defect can break two seams. Say so, so nobody counts it twice.
            places = set(_LOCATION.findall(res["drift"]))
            for other in data["seams"]:
                if other is not seam and other.get("drift"):
                    same = places & set(_LOCATION.findall(other["drift"]["text"]))
                    if same:
                        lines.append(f"  seam `{other['id']}` records drift at the same place: "
                                     + ", ".join(f"`{x}`" for x in sorted(same)))
        # A security finding is kept whatever `agree` says: a checker can see a gap that is not drift.
        if res.get("sensitive_finding"):
            counts["sensitive"] += 1
            private.append(f"## {res['id']}\n\n{res['sensitive_finding']}\n")
            if seam.get("sensitive"):
                lines.append("  a security finding is in the private file; the seam already has a pointer")
            else:
                seam["sensitive"] = (f"A security finding from the drift check on {today} is kept out of this "
                                     "repo. File it somewhere private and replace this line with a pointer to it.")
                lines.append("  a security finding is in the private file; check that the text above holds "
                             "no exploit detail")
    errors = check.validate_errors(data)
    if not errors:
        Path(registry_path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return lines, private, errors, counts
