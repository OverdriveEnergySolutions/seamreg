"""Risk re-rating: a stronger model reads each recorded seam and sets its risk again.

Measured 2026-11-19 on two public repos: a Sonnet 5.5 review found the same known drifts as an Opus 5.5
review for about 60% of the cost, but rated far fewer seams high (2 against 7, and 2 against 17), and
risk decides what the hooks, notes and drift check put first. This pass keeps the cheap review and asks
a stronger model only the question it answered worse: what breaks, and for whom, when the copies drift.

    seams rerate              packets of seams to re-rate, one seam-risk-rater agent each
    seams rerate --collect    write the new risks into the registry, and list every change
"""
from __future__ import annotations

import json
from pathlib import Path

from seams import check

BATCH = 30
BRIEF = Path(__file__).with_name("rerate-brief.md")
RISKS = ("high", "medium", "low")
PREFIX = "rr-"


def _load_valid(registry_path):
    data = check.load(registry_path)
    errors = check.validate_errors(data)
    if errors:
        raise ValueError(f"{registry_path} does not match the schema: {'; '.join(errors[:3])}")
    return data


def _seam_md(i, s):
    copies = ", ".join(f"`{c['path']}`" + (f" ({c['symbol']})" if c.get("symbol") else "") for c in s["copies"])
    rows = [f"### {i}. `{s['id']}`: {s['title']}", "",
            f"- Kind: {s['kind']}. Current risk: **{s['risk']}**.",
            f"- Must agree: {s['must_agree']}",
            f"- Consequence recorded: {s.get('consequence') or '(none)'}",
            f"- Copies: {copies}"]
    if s.get("drift"):
        rows.append(f"- Drift recorded: {s['drift']['text']}")
    return "\n".join(rows) + "\n"


def write_packets(registry_path, root, out, batch=BATCH, ids=None):
    """Write rerate/packets/rr-NN.md, for every seam or only the seams in `ids`. Returns the packet paths."""
    data = _load_valid(registry_path)
    if ids is not None:
        missing = sorted(set(ids) - {s["id"] for s in data["seams"]})
        if missing:
            raise ValueError(f"no recorded seam has the id {', '.join(missing)}")
        data = {**data, "seams": [s for s in data["seams"] if s["id"] in set(ids)]}
    base = Path(out) / "rerate"
    (base / "packets").mkdir(parents=True, exist_ok=True)
    (base / "results").mkdir(exist_ok=True)
    for old in list((base / "packets").glob("*.md")) + list((base / "results").glob("*.json")):
        old.unlink()
    (base / "brief.md").write_text(BRIEF.read_text(encoding="utf-8"), encoding="utf-8")
    seams = sorted(data["seams"], key=lambda s: s["id"])
    paths = []
    for i in range(0, len(seams), batch):
        n = i // batch + 1
        name = f"{PREFIX}{n:02d}"
        rows = [f"# Risk re-rating packet {name}", "",
                f"Repo root: `{Path(root).resolve()}`",
                f"Brief: `{(base / 'brief.md').resolve()}`. Read it first and follow it exactly.",
                f"Output file: `{(base / 'results' / f'{name}.json').resolve()}`", "",
                f"## Seams ({len(seams[i:i + batch])})", ""]
        rows += [_seam_md(j, s) for j, s in enumerate(seams[i:i + batch], 1)]
        p = base / "packets" / f"{name}.md"
        p.write_text("\n".join(rows), encoding="utf-8")
        paths.append(p)
    return paths


def collect(registry_path, out):
    """Write the raters' risks into the registry. Returns (report lines, counts)."""
    data = _load_valid(registry_path)
    by_id = {s["id"]: s for s in data["seams"]}
    lines, counts = [], {"files": 0, "rated": 0, "up": 0, "down": 0}
    order = {r: i for i, r in enumerate(reversed(RISKS))}
    for f in sorted((Path(out) / "rerate" / "results").glob("*.json")):
        counts["files"] += 1
        try:
            rows = check.load(f)
        except (ValueError, OSError) as e:
            lines.append(f"- `{f.name}`: could not be read: {e}")
            continue
        if not isinstance(rows, list):
            lines.append(f"- `{f.name}`: not a JSON array")
            continue
        for r in rows:
            if not isinstance(r, dict) or r.get("risk") not in RISKS or r.get("id") not in by_id:
                lines.append(f"- `{f.name}`: skipped an entry with an unknown id or risk: {json.dumps(r)[:120]}")
                continue
            seam = by_id[r["id"]]
            counts["rated"] += 1
            old, new = seam["risk"], r["risk"]
            if old != new:
                counts["up" if order[new] > order[old] else "down"] += 1
                seam["risk"] = new
                lines.append(f"- `{r['id']}`: {old} to **{new}**. {r.get('reason', '').strip()}")
    errors = check.validate_errors(data)
    if not errors:
        Path(registry_path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    rated = set()
    for f in (Path(out) / "rerate" / "results").glob("*.json"):
        try:
            rated |= {r.get("id") for r in check.load(f) if isinstance(r, dict)}
        except (ValueError, OSError, TypeError):
            pass
    missing = sorted(set(by_id) - rated)
    if missing:
        lines.append(f"- Not rated ({len(missing)}), risk unchanged: " + ", ".join(f"`{m}`" for m in missing[:40]))
    return lines, counts, errors
