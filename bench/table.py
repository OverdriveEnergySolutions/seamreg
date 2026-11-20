"""Print the statistics from every submitted benchmark, one table per kind.

    python3 bench/table.py [RESULTS_DIR]     (default: bench/results)

Each folder in RESULTS_DIR holds one result.json (see bench/result.py). The common columns come from
the envelope. The rest come from the kind's "measures", flattened, so a new kind shows up with no change
here. A count pair such as {"total": 8, "caught": 3} prints as "caught 3/8".
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def flatten(measures):
    cells = {}
    for key, val in measures.items():
        if isinstance(val, dict) and "total" in val:
            cells[key] = ", ".join(f"{k} {v}/{val['total']}" for k, v in val.items() if k != "total")
        elif isinstance(val, dict):
            cells[key] = ", ".join(f"{k} {v}" for k, v in val.items())
        else:
            cells[key] = str(val)
    return cells


def load(results_dir):
    rows = defaultdict(list)
    for f in sorted(Path(results_dir).glob("*/result.json")):
        r = json.loads(f.read_text())
        rows[r["kind"]].append((f.parent.name, r))
    return rows


def render(rows):
    out = []
    for kind, items in sorted(rows.items()):
        keys = []
        for _, r in items:
            keys += [k for k in r.get("measures", {}) if k not in keys]
        head = ["Benchmark", "Snapshot", "Model, effort", "Cost (API-equivalent)", "Blind"] + keys
        out += [f"## {kind}", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for name, r in items:
            b = r["blindscan"]
            blind = "clean" if not (b["forbidden"] or b["network"]) else f"{b['forbidden']} + {b['network']} hits"
            cells = flatten(r.get("measures", {}))
            row = [name, f"`{r['snapshot'][:10]}` ({r['snapshot_date']})", f"{r['model']}, {r['effort']}",
                   f"${r['cost_usd_api_equivalent']:.2f}", blind] + [cells.get(k, "") for k in keys]
            out.append("| " + " | ".join(row) + " |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "results"
    print(render(load(d)) or "no results yet")
