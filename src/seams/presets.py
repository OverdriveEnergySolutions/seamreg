"""Presets: what each named level of a paid run does, and what it costs on this repo.

`seams presets` prints this for the review skill, as text or as JSON. The skill shows the
choice, then passes each step's model and effort to every agent it starts.

This module is the one place that says what a preset runs. check.py holds the names and
allowed values it validates, and the agent files carry standard's effort as a floor, tied
to this table by a test.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from seams import check

STEPS = check.STEPS
AGENT = {"review": "seam-reviewer", "drift_check": "seam-drift-checker",
         "lead_check": "seam-lead-checker", "rerate": "seam-risk-rater"}
STEP_TEXT = {"review": "review", "drift_check": "drift check", "lead_check": "lead check", "rerate": "risk re-rating"}
DEFAULT_DIFF_LIMIT = check.DEFAULT_DIFF_LIMIT

# What each preset runs. Values come from the measured runs (docs/presets.md lists each source).
DEFINITIONS = {
    "standard": {
        "review": {"model": "sonnet", "effort": "max"},
        "drift_check": {"model": "sonnet", "effort": "max"},
        "lead_check": {"model": "sonnet", "effort": "high"},
        "rerate": {"model": "opus", "effort": "medium"},
    },
    "all-in": {
        "review": {"model": "sonnet", "effort": "max"},
        "drift_check": {"model": "sonnet", "effort": "max"},
        "lead_check": {"model": "sonnet", "effort": "max"},
        "rerate": {"model": "opus", "effort": "max"},
    },
}
BUYS = {
    "standard": "a full review, a drift check, a lead check at high effort, and stronger risk ratings",
    "all-in": "the same steps with every one at max effort: the lead check finds about twice the drifts",
}

# Dollars (API-equivalent) per unit of work, by step, model and effort. Measured on child-agent
# transcripts, each message counted once; docs/presets.md gives the source of every row.
UNIT = {"review": "reviewed line", "drift_check": "seam", "lead_check": "lead", "rerate": "seam"}
RATES = {
    ("review", "sonnet", "max"): 0.000194,  # 4 first reviews, 561k lines; per run 0.000134 to 0.000265
    ("drift_check", "sonnet", "max"): 1.01,  # 5 runs, 33 seams
    ("drift_check", "sonnet", "xhigh"): 0.111,  # 1 run
    ("drift_check", "sonnet", "high"): 0.053,  # 3 runs, seams a lead check added
    ("lead_check", "sonnet", "max"): 0.149,  # 1 run
    ("lead_check", "sonnet", "high"): 0.00425,  # 1 run
    ("rerate", "opus", "medium"): 0.0183,  # 2 runs, at Opus's default effort
}
# An effort above every measured one borrows the highest measured rate below it, times the largest
# measured jump from high to max (the lead check's, 35x), so the estimate errs high until measured.
MAX_STRETCH = 35
# The model id each model setting runs as, to report an agent that ran on another model.
MODEL_IDS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5",
             "fable": "claude-fable-5-2"}
# Dollars per million tokens: input, output, cache write (5 minutes), cache write (1 hour), cache read.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 4.00, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 8.00, 0.20),
}
SEAMS_PER_LINE = 0.00054  # seams a first review records per reviewed line, 4 reviews
CHECKED_SHARE = 0.2  # share of recorded seams the drift check picks: high and medium risk, no drift yet
CHECKED_CAP = 20  # the skill samples at most this many
ORCHESTRATOR_SHARE = 0.13  # the session that runs the skill: 11 to 15% of a first review's total


def fingerprint(name):
    """Changes whenever a release changes what the preset runs."""
    text = json.dumps(DEFINITIONS[name], sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# --- settings, in layers ---------------------------------------------------

def load_saved(root):
    """The saved settings, or None. Raises ValueError naming the problem."""
    path = Path(root) / check.SETTINGS
    if not path.is_file():
        return None
    errors = check.settings_errors(root)
    if errors:
        raise ValueError("; ".join(errors))
    return check.load(path)


def parse_set(text):
    """'lead_check.effort=xhigh' -> ('lead_check', 'effort', 'xhigh'). Raises ValueError."""
    key, eq, value = text.partition("=")
    step, dot, field = key.partition(".")
    if not eq or not dot:
        raise ValueError(f"--set '{text}': write it as step.setting=value, for example lead_check.effort=xhigh")
    if step not in STEPS:
        raise ValueError(f"--set '{text}': unknown step '{step}'. Steps: {', '.join(STEPS)}")
    allowed = {"model": check.MODELS, "effort": check.EFFORTS}.get(field)
    if allowed is None:
        raise ValueError(f"--set '{text}': unknown setting '{field}'. Settings: model, effort")
    if value not in allowed:
        raise ValueError(f"--set '{text}': {field} must be one of {', '.join(allowed)}")
    return step, field, value


def resolve(name, saved=None, sets=()):
    """Effective settings for preset `name`: its definition, then the saved changes when the
    saved preset is this one, then this run's changes. Each value records where it came from."""
    steps = {s: {k: {"value": v, "source": "preset"} for k, v in DEFINITIONS[name][s].items()} for s in STEPS}
    if saved and saved.get("preset") == name:
        for step, fields in (saved.get("changes") or {}).items():
            for k, v in fields.items():
                steps[step][k] = {"value": v, "source": "saved"}
    for text in sets:
        step, k, v = parse_set(text)
        steps[step][k] = {"value": v, "source": "this run"}
    limit = (saved or {}).get("diff_limit_percent")
    return {"preset": name, "fingerprint": fingerprint(name), "steps": steps,
            "diff_limit_percent": {"value": limit or DEFAULT_DIFF_LIMIT, "source": "saved" if limit else "preset"}}


def plain(settings):
    """{step: {"model": .., "effort": ..}} without the sources."""
    return {s: {k: v["value"] for k, v in f.items()} for s, f in settings["steps"].items()}


# --- the estimate -----------------------------------------------------------

def rate(step, model, effort):
    """(dollars per unit, measured) for a step. An unmeasured effort borrows the nearest measured
    higher effort for the same model. Above every measured effort, it takes the highest measured
    rate times MAX_STRETCH. Either way the estimate errs high. None when the model has no rate."""
    if (step, model, effort) in RATES:
        return RATES[(step, model, effort)], True
    order = check.EFFORTS
    higher = order[order.index(effort) + 1:]
    for e in higher:
        if (step, model, e) in RATES:
            return RATES[(step, model, e)], False
    for e in reversed(order[:order.index(effort)]):
        if (step, model, e) in RATES:
            return RATES[(step, model, e)] * MAX_STRETCH, False
    return None, False


def counts(doc, known, new_only=False):
    """Units of work for each step, from a scan's leads, before any agent runs."""
    from seams import leadcheck, rerate, split
    picked = split.filter_leads(doc, new_only=new_only)
    bins = split._drop_empty(split.plan(picked, lead_units_only=new_only))
    lines = sum(b["lines"] for b in bins)
    leads = len(leadcheck.select(picked, known))
    seams = round(lines * SEAMS_PER_LINE)
    checked = min(CHECKED_CAP, round(seams * CHECKED_SHARE))
    return {"review": lines, "lead_check": leads, "drift_check": checked, "rerate": seams,
            "packets": {"review": len(bins), "lead_check": math.ceil(leads / leadcheck.BATCH),
                        "drift_check": checked, "rerate": math.ceil(seams / rerate.BATCH)}}


def _packet_units():
    """Units of work in one full packet, by step: the floor of a step's per-packet estimate."""
    from seams import leadcheck, rerate, split
    return {"review": split.DEFAULT_MAX_LINES, "lead_check": leadcheck.BATCH, "drift_check": 1,
            "rerate": rerate.BATCH}


def estimate(settings, work):
    """Dollars per step and in all. A step whose rate or count is not known has dollars None,
    and the totals then say so. A step estimated at no packets still gets a per-packet estimate,
    one full packet's worth, because the agents may still find work for it."""
    steps, total, known = {}, 0.0, True
    full = _packet_units()
    for step in STEPS:
        model, effort = settings[step]["model"], settings[step]["effort"]
        r, measured = rate(step, model, effort)
        n = work.get(step)
        dollars = None if r is None or n is None else round(r * n, 2)
        packets = work["packets"].get(step) or 0
        if r is None:
            per_packet = None
        elif dollars and packets:
            per_packet = round(dollars / packets, 2)
        else:
            per_packet = round(r * full[step], 2)
        steps[step] = {"agent": AGENT[step], "model": model, "effort": effort, "units": n, "unit": UNIT[step],
                       "dollars": dollars, "measured": measured, "per_packet": per_packet, "packets": packets}
        if dollars is None:
            known = False
        else:
            total += dollars
    agents = round(total, 2) if known else None
    session = round(agents * ORCHESTRATOR_SHARE, 2) if agents is not None else None
    return {"steps": steps, "agents": agents, "orchestrator": session}


def report(root, out, preset=None, sets=(), last=None):
    """Everything the skill needs before a paid run, as one JSON-ready dict. `last` is the last
    finished run (spend.last_finished), which says whether a preset changed since."""
    from seams import split
    root, out = Path(root), Path(out)
    saved = load_saved(root)
    doc = split.load_leads(out)
    reg = root / check.REGISTRY
    known = check.load(reg)["seams"] if reg.is_file() else []
    full = counts(doc, known)
    has_registry = bool(doc.get("registry") or doc.get("baseline"))
    diff = counts(doc, known, new_only=True) if has_registry else None
    names = [preset] if preset else list(DEFINITIONS)
    rows = {}
    for name in names:
        s = resolve(name, saved, sets if (preset or name == (saved or {}).get("preset")) else ())
        eff = plain(s)
        row = {"settings": s, "buys": BUYS[name], "full": estimate(eff, full)}
        if diff is not None:
            row["diff"] = estimate(eff, diff)
            a, b = row["diff"]["agents"], row["full"]["agents"]
            row["diff_percent"] = round(100 * a / b) if a is not None and b else None
            limit = s["diff_limit_percent"]["value"]
            row["diff_over_limit"] = None if row["diff_percent"] is None else row["diff_percent"] > limit
        row["definition_changed"] = bool(last and last.get("preset") == name
                                         and last.get("fingerprint") != s["fingerprint"])
        rows[name] = row
    return {"saved": (saved or {}).get("preset"), "has_registry": has_registry, "presets": rows,
            "counts": {"full": full, "diff": diff}}


def _money(x):
    return "not measured" if x is None else f"${x:,.2f}"


def text(rep):
    """The report for a person."""
    out = []
    if rep["saved"]:
        out.append(f"Saved preset: {rep['saved']} (seams.settings.json).")
    else:
        out.append("No preset saved yet. Choose one; docs/presets.md explains each setting.")
    for name, row in rep["presets"].items():
        full = row["full"]
        out += ["", f"{name}: {row['buys']}.",
                f"  Full run: about {_money(full['agents'])} for the agents"
                + (f", plus about {_money(full['orchestrator'])} for the session that runs them." if full["orchestrator"] else ".")]
        for step, st in full["steps"].items():
            src = row["settings"]["steps"][step]
            mark = "" if all(v["source"] == "preset" for v in src.values()) else \
                " (" + ", ".join(f"{k} {v['source']}" for k, v in src.items() if v["source"] != "preset") + ")"
            out.append(f"    {STEP_TEXT[step]}: {st['model']} at {st['effort']}{mark}, "
                       f"{st['units'] if st['units'] is not None else '?'} {st['unit']}(s), {_money(st['dollars'])}"
                       + ("" if st["measured"] or st["dollars"] is None else ", not measured at this effort: estimated high"))
        if "diff" in row:
            out.append(f"  Diff scan: about {_money(row['diff']['agents'])}"
                       + (f", {row['diff_percent']}% of a full run" if row["diff_percent"] is not None else "")
                       + (" (over the limit: ask first)" if row.get("diff_over_limit") else ""))
        if row["definition_changed"]:
            out.append("  This preset changed in this release since your last run: ask before running it.")
    return "\n".join(out)
