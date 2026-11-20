"""Assemble a benchmark's result.json, the one file every benchmark kind submits.

    python3 bench/result.py WORKDIR NAME KIND [--submitter NAME] [--notes TEXT]

Reads WORKDIR/bench.json (the repo and snapshot), WORKDIR/NAME/summary.json (from bench/session.sh),
WORKDIR/NAME/blindscan.txt (from bench/blindscan.py) and WORKDIR/NAME/grade/measures.json (the kind's
own numbers, written by its grading step). Writes WORKDIR/NAME/result.json.

The envelope is the same for every kind. What a kind measures goes in "measures", in the shape its
README defines, so a new kind needs no change here.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

ENVELOPE = ("kind", "repo_url", "snapshot", "snapshot_date", "window_end", "window_end_date", "files",
            "tool_commit", "model", "effort", "cost_usd_api_equivalent", "complete", "blindscan",
            "measures", "date")


def blindscan_counts(text):
    m = re.search(r"(\d+) tool calls, forbidden (\d+), network (\d+)", text)
    if not m:
        raise ValueError("blindscan.txt has no summary line; run bench/blindscan.py")
    return {"tool_calls": int(m.group(1)), "forbidden": int(m.group(2)), "network": int(m.group(3))}


def build(work, name, kind, submitter=None, notes=None):
    work = Path(work)
    bench = json.loads((work / "bench.json").read_text())
    summary = json.loads((work / name / "summary.json").read_text())
    if not summary.get("complete"):
        raise ValueError("the session did not finish (summary.json: complete is false). Resume it with RESUME=1")
    if (work / name / "blindscan.txt").stat().st_mtime < (work / name / "summary.json").stat().st_mtime:
        raise ValueError("blindscan.txt is older than the last session turn. Run bench/blindscan.py again")
    scan = blindscan_counts((work / name / "blindscan.txt").read_text())
    measures = json.loads((work / name / "grade" / "measures.json").read_text())
    out = {"kind": kind, **{k: bench[k] for k in ("repo_url", "snapshot", "snapshot_date", "window_end",
                                                    "window_end_date", "files")},
           **{k: summary[k] for k in ("tool_commit", "model", "effort", "cost_usd_api_equivalent", "complete")},
           "registry": {k: summary[k] for k in ("seams", "risk", "drift_claims")},
           "blindscan": scan, "measures": measures, "date": datetime.date.today().isoformat()}
    # Every session's cost: the blind run, plus any key, grading or other session bench/task.sh ran.
    costs = {name: summary["cost_usd_api_equivalent"]}
    for f in sorted((work / "sessions").glob("*.json")) if (work / "sessions").is_dir() else []:
        try:
            costs[f.stem] = round(json.loads(f.read_text()).get("total_cost_usd") or 0, 2)
        except ValueError:
            pass
    out["costs_usd_api_equivalent"] = dict(costs, total=round(sum(costs.values()), 2))
    out["resumes"] = summary.get("resumes", 0)
    if submitter:
        out["submitter"] = submitter
    if notes:
        out["notes"] = notes
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Assemble a benchmark's result.json.")
    p.add_argument("workdir"); p.add_argument("name"); p.add_argument("kind")
    p.add_argument("--submitter"); p.add_argument("--notes")
    a = p.parse_args(argv)
    try:
        out = build(a.workdir, a.name, a.kind, a.submitter, a.notes)
    except (OSError, ValueError) as e:
        print(f"result: {e}", file=sys.stderr)
        return 1
    path = Path(a.workdir) / a.name / "result.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {path}")
    if out["blindscan"]["forbidden"] or out["blindscan"]["network"]:
        print("note: the blindness scan has hits. Explain each one in the pull request.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
