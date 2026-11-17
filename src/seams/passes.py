"""What to run next on a registry, and which drift to fix first.

    seams next [--root .]          the candidate next steps, ranked, each with its reason and cost
    seams triage [--top 10]      the drift worth fixing first, confirmed drift ahead of drift found by reading

Each `seams split` adds one entry to <out>/passes.json: the kind of pass, when it
started, its packets, and a picture of the registry at that moment (each seam's
risk, and which seams record drift). A pass's yield is the difference between its
picture and the next pass's, or the registry as it stands now for the last pass.
So a merge run twice, a hand edit or a drift check between passes all count, and
nothing else has to write to the ledger.

The ranking is fixed rules for now: the measured order from the benchmarks
(docs/benchmarks.md). Each entry carries its yield, so once enough repos have
ledgers the rules can be replaced by measured yields per kind of pass.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from seams import check

LEDGER = "passes.json"

# Measured on four public repos (docs/benchmarks.md, three-pass runs): known drifts caught
# rose from 33% after a first review to 44% after one gap pass and 52% after two. A gap
# pass cost 0.55 to 0.94 of the same repo's first review.
GAP_COST_SHARE = (0.55, 0.75, 0.94)
GAP_YIELD = "On four public repos, known drifts caught rose from 33% (first review) to 44% (one gap pass) and 52% (two)."
STOP_RULE = "a gap pass that adds no new high-risk seam and no new drift"


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def picture(data):
    """What the ledger keeps of a registry: each seam's risk, and the seams with drift."""
    seams = (data or {}).get("seams") or []
    return {"seams": {s["id"]: s["risk"] for s in seams},
            "drift": sorted(s["id"] for s in seams if s.get("drift"))}


def load_ledger(out):
    try:
        doc = json.loads((Path(out) / LEDGER).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) and isinstance(doc.get("passes"), list) else {"passes": []}
    except (OSError, ValueError):
        return {"passes": []}


def record_pass(out, kind, packets, leads, registry):
    """Add one pass to the ledger. `kind`: first, gap, lead-only or focus:<name>."""
    doc = load_ledger(out)
    doc["passes"].append({"kind": kind, "started": _now(), "packets": packets, "leads": leads,
                          "before": picture(registry)})
    path = Path(out) / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def yields(ledger, current):
    """Per pass: new seams by risk and new drift, from the pictures."""
    passes = ledger["passes"]
    out = []
    for i, p in enumerate(passes):
        after = passes[i + 1]["before"] if i + 1 < len(passes) else picture(current)
        before = p["before"]
        new = [sid for sid in after["seams"] if sid not in before["seams"]]
        out.append({**p, "new": {r: sum(after["seams"][s] == r for s in new) for r in check.RISKS},
                    "new_drift": len(set(after["drift"]) - set(before["drift"]))})
    return out


def yield_text(y):
    n = y["new"]
    return (f"{sum(n.values())} new seams ({n['high']} high, {n['medium']} medium, {n['low']} low), "
            f"{y['new_drift']} with new drift")


def _registry(root, out):
    """The newest registry: the proposal when it is newer than seams.json (a merge not yet applied)."""
    reg, prop = Path(root) / check.REGISTRY, Path(out) / "seams.proposed.json"
    pending = prop.exists() and (not reg.exists() or prop.stat().st_mtime > reg.stat().st_mtime)
    for path in ([prop, reg] if pending else [reg]):
        try:
            data = check.load(path)
            if not check.validate_errors(data):
                return data, pending and path == prop
        except (OSError, ValueError):
            continue
    return {"schema_version": 1, "seams": []}, False


def merged_since(out, started):
    """True when a merge wrote the proposal after `started`: the pass's reviews are in."""
    prop = Path(out) / "seams.proposed.json"
    try:
        return datetime.datetime.fromtimestamp(prop.stat().st_mtime) >= datetime.datetime.fromisoformat(started)
    except (OSError, ValueError):
        return False


def _checked_ids(out):
    """Seam ids a drift check has answered for, in this pass or an earlier one (done/)."""
    ids = set()
    for f in (Path(out) / "verify" / "results").glob("**/*.json"):
        try:
            ids.add(json.loads(f.read_text(encoding="utf-8"))["id"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return ids


def _first_review_tokens(ledger, out):
    """Tokens for one first review: its packet count at max effort, or None when not known."""
    from seams import split
    first = [p for p in ledger["passes"] if p["kind"] == "first"]
    packets = first[0]["packets"] if first else None
    if packets is None:
        try:
            packets = len(split.plan(split.filter_leads(split.load_leads(out))))
        except (OSError, ValueError, KeyError):
            return None
    return packets * split.PER_PACKET["max"][0]


def _tok(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k"


def candidates(root, out):
    """[(command, reason, cost)] in the order to run them."""
    from seams import split, tie, verify
    out = Path(out)
    data, pending = _registry(root, out)
    ledger = load_ledger(out)
    ys = yields(ledger, data)
    seams = data["seams"]
    rows = []
    if ys and not merged_since(out, ys[-1]["started"]):
        y = ys[-1]
        return [(f"finish the {y['kind']} pass: one seam-reviewer per packet, then `seams merge`",
                 f"`seams split` wrote its {y['packets']} packet(s) on {y['started'][:10]} and no merge came after, "
                 "so its yield is not known yet. The next step depends on it.", "see plan.md")]
    if pending:
        rows.append(("settle the merge report, then `seams apply`",
                     "the proposal is newer than seams.json: the last pass's seams are not in the registry yet. "
                     "The rows below count them anyway.", "no agents"))
    if not seams and not any(p["kind"] == "first" for p in ys):
        if not (out / "leads.json").exists():
            rows.append(("`seams scan`", "no scan yet: the passes start from its leads", "no agents, seconds to minutes"))
        tokens = _first_review_tokens(ledger, out)
        rows.append(("`seams split`, then one seam-reviewer per packet (the first review)",
                     "no registry yet. One first review finds about half of a repo's seams.",
                     f"about {_tok(tokens)} tokens at max effort" if tokens else "see plan.md after `seams split`"))
        return rows

    unchecked = [s["id"] for s in verify.select(data) if s["id"] not in _checked_ids(out)]
    if unchecked:
        rows.append((f"`seams verify` ({len(unchecked)} seams)",
                     "high- and medium-risk seams (and convention seams) with no drift recorded and no drift check "
                     "yet. Full reviews often record a seam and miss that its copies already differ.",
                     verify.cost_text(len(unchecked))))

    gaps = [y for y in ys if y["kind"] == "gap"]
    tokens = _first_review_tokens(ledger, out)
    gap_cost = (f"about {_tok(tokens * GAP_COST_SHARE[1])} tokens at max effort "
                f"({GAP_COST_SHARE[0]:.2f} to {GAP_COST_SHARE[2]:.2f} of a first review)" if tokens
                else f"{GAP_COST_SHARE[0]:.2f} to {GAP_COST_SHARE[2]:.2f} of a first review")
    last = gaps[-1] if gaps else None
    if last is not None and last["new"]["high"] == 0 and last["new_drift"] == 0:
        rows.append(("no more gap passes", f"the stopping rule fired: gap pass {len(gaps)} added "
                     f"{yield_text(last)}. The rule is {STOP_RULE}.", "-"))
    elif len(gaps) < 2:
        why = (GAP_YIELD + " " if not gaps else f"gap pass {len(gaps)} added {yield_text(last)}. ") + \
              f"Plan for three passes in all. Stop at {STOP_RULE}."
        rows.append((f"`seams split --gap` (gap pass {len(gaps) + 1})", why, gap_cost))
    else:
        rows.append((f"`seams split --gap` (gap pass {len(gaps) + 1}, optional)",
                     f"gap pass {len(gaps)} still added {yield_text(last)}. The measured runs never reached the "
                     "stopping rule, so the ceiling is not known. Compare this yield with its cost.", gap_cost))

    doc = None
    try:
        doc = split.load_leads(out)
    except (OSError, ValueError):
        pass
    for name, spec in split.FOCUS.items():
        done = [y for y in ys if y["kind"] == f"focus:{name}"]
        if done:
            rows.append((f"focused pass `{name}`: done", f"it added {yield_text(done[-1])}.", "-"))
            continue
        if doc is None:
            continue
        leads = [l for l in doc["leads"] if l["kind"] in spec["kinds"]]
        open_ = [l for l in leads if not split._fully_covered(l, seams)]
        if leads:
            rows.append((f"`seams split --focus {name}`",
                         f"{len(leads)} leads of its kinds ({', '.join(sorted(spec['kinds']))}), {len(open_)} that no "
                         f"recorded seam covers. It hunts {spec['title']} across the whole repo and tests each on "
                         "edge cases.", "one reviewer; its cost is not measured yet"))

    reading = [s for s in seams if (s.get("drift") or {}).get("source") == "reading"]
    if reading:
        rows.append((f"`seams verify --reading --risk high,medium,low` ({len(reading)} seams)",
                     "drift found only by reading. A second checker that does not see the recorded drift says "
                     "whether it sees a difference too. Then confirm what holds with `seams apply --confirm`.",
                     verify.cost_text(len(reading))))
    if any(s.get("drift") for s in seams):
        rows.append(("`seams triage`", "lists the drift worth fixing first.", "no agents"))
    untied = tie.untied(data)
    if untied:
        rows.append((f"`seams tie --untied` ({len(untied)} seams)",
                     "high- and medium-risk seams with no full tie: nothing fails when their copies drift. "
                     "Each agent writes a test and proves it by breaking each copy.", "one agent per seam; not measured yet"))
    return rows


def next_text(root, out):
    out = Path(out)
    data, _ = _registry(root, out)
    ledger = load_ledger(out)
    lines = ["# Next passes", ""]
    ys = yields(ledger, data)
    if ys:
        lines += ["Passes so far (yield: what the registry gained between this pass and the next):", ""]
        for i, y in enumerate(ys, 1):
            lines.append(f"{i}. {y['kind']}, {y['started'][:10]}, {y['packets']} packet(s): {yield_text(y)}")
        lines.append("")
    elif data["seams"]:
        lines += ["No pass ledger (passes.json): the passes ran before seamreg kept one, so yields are unknown.", ""]
    lines += ["Ranked by fixed rules from the measured benchmarks:", ""]
    for i, (cmd, why, cost) in enumerate(candidates(root, out), 1):
        cost = cost[len("Cost "):] if cost.startswith("Cost ") else cost
        lines += [f"{i}. {cmd}", f"   Why: {why}", f"   Cost: {cost}"]
    return "\n".join(lines) + "\n"


# --- triage -----------------------------------------------------------------------

def triage(data, top=10):
    """(confirmed, reading) drift lists, each highest risk first."""
    rank = lambda s: (check.RISKS.index(s["risk"]), 0 if s.get("sensitive") else 1, s["id"])
    drifted = [s for s in data["seams"] if s.get("drift")]
    confirmed = sorted((s for s in drifted if s["drift"]["source"] == "confirmed"), key=rank)
    reading = sorted((s for s in drifted if s["drift"]["source"] != "confirmed"), key=rank)
    return confirmed[:top], reading[:max(0, top - len(confirmed[:top]))], len(confirmed), len(reading)


TRIAGE_CHARS = 400  # a triage list is read in one sitting; the full text stays in seams.json


def _clip(text, n=TRIAGE_CHARS):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ... (full text in seams.json)"


def _entry(s):
    tie_line = ("tied" if check.fully_tied(s) else
                f"no full tie. Suggested: {_clip(s['suggested_tie'], 200).rstrip('.')}" if s.get("suggested_tie")
                else "no full tie")
    paths = [c["path"] for c in s["copies"]]
    copies = ", ".join(paths[:6]) + (f" and {len(paths) - 6} more" if len(paths) > 6 else "")
    return [f"- **{s['id']}** (risk {s['risk']}): {s['title']}",
            f"  Differs: {_clip(s['drift']['text'])}",
            f"  If left: {_clip(s['consequence'], 200)}",
            f"  Copies: {copies}",
            f"  Tie: {tie_line}. Fix the drift and add a tie in the same change (`seams tie {s['id']}`)."]


def triage_text(data, top=10):
    confirmed, reading, n_conf, n_read = triage(data, top)
    lines = ["# Drift to fix first", "",
             f"{n_conf} seams record confirmed drift and {n_read} record drift found only by reading. "
             f"The top {len(confirmed) + len(reading)}, confirmed first, then by risk:", ""]
    if confirmed:
        lines += ["## Confirmed", ""]
        for s in confirmed:
            lines += _entry(s)
        lines.append("")
    if reading:
        lines += ["## Found by reading, not confirmed", "",
                  "Read both sides before you call one a bug. Confirm what holds with "
                  "`seams apply --confirm <id,id>`, or get a second opinion with `seams verify --reading`.", ""]
        for s in reading:
            lines += _entry(s)
        lines.append("")
    if not confirmed and not reading:
        lines += ["No seam records drift.", ""]
    return "\n".join(lines)


def triage_short(data, top=5):
    """A few lines for the end of a merge: the drift worth fixing, not every seam."""
    confirmed, reading, n_conf, n_read = triage(data, top)
    if not (n_conf or n_read):
        return ""
    lines = [f"drift: {n_conf} confirmed, {n_read} found by reading. Worth fixing first:"]
    for s in confirmed + reading:
        lines.append(f"  {s['id']} (risk {s['risk']}, {s['drift']['source']}): {s['drift']['text'][:140]}"
                     + ("..." if len(s["drift"]["text"]) > 140 else ""))
    lines.append("Full list: `seams triage`. Next passes: `seams next`.")
    return "\n".join(lines)
