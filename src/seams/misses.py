"""Miss reports: drift between copies that seamreg did not record, so the tool can learn it.

    seams report-miss --changed FILE --missed FILE --rule TEXT [--summary TEXT] [--shape NAME]
                      [--cause SHA --fix SHA --repo URL --public]
    seams catalog [FOLDER ...]

A miss is one piece of knowledge kept in two or more files where a change updated one copy and
left another, and the registry had no seam that said so. Each report records the rule the copies
had to keep, which copy changed and which was missed, and what the registry held at the time.

A report is written twice. The full one stays in the repo's .seams-scan/misses/ (git ignores it).
The shareable one is printed. For a private repo it holds only the shape: the rule in general words,
the copies' roles and file types, and the registry status, never a path, a commit or code. With
--public and the commits, it holds everything a prevention replay needs (the commit that missed the
copy, and the one that fixed it), so a public report becomes a benchmark task.

`seams catalog` reads a library of reports (by default the one that ships with seamreg) and ranks the
shapes no pass handles yet. That ranking says which kind to build next. A new kind is judged on
reports it was not built from.
"""
from __future__ import annotations

import datetime
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from seams import check

LIBRARY = Path(__file__).with_name("catalog") / "misses"
REGISTRY_STATES = ("no-registry", "none", "glob-only", "recorded-rule-missing", "recorded-stale")
FOUND_BY = ("drift-fix", "review", "open-pass", "benchmark", "other")
_TEXT = {"type": "string", "minLength": 1}
_OPT = {"type": ["string", "null"]}
MISS = {
    "type": "object",
    "required": ["miss_version", "id", "reported", "summary", "must_agree", "shape", "copies", "registry",
                 "found_by", "public"],
    "additionalProperties": False,
    "properties": {
        "miss_version": {"const": 1},
        "id": {"type": "string", "pattern": r"^[a-z0-9]+(-[a-z0-9]+)*$"},
        "reported": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "summary": _TEXT,          # the shape in general words: no names from the repo
        "must_agree": _TEXT,       # the rule the copies had to keep
        "shape": _TEXT,            # a short tag that groups reports: siblings, packaging, doc-claims ...
        "kind": {"enum": list(check.KINDS) + ["unknown"]},
        "languages": {"type": "array", "items": _TEXT},
        "copies": {"type": "array", "minItems": 2, "items": {
            "type": "object", "required": ["role"], "additionalProperties": False,
            "properties": {"role": {"enum": ["changed", "missed"]}, "path": _TEXT, "symbol": _TEXT,
                           "file_type": _TEXT}}},
        "registry": {"enum": list(REGISTRY_STATES)},
        "found_by": {"enum": list(FOUND_BY)},
        "public": {"type": "boolean"},
        "repo": _OPT,
        "commits": {"type": ["object", "null"], "additionalProperties": False,
                    "properties": {"cause": _TEXT, "fix": _TEXT}},
        "handled_by": _OPT,        # the pass or kind that records this shape now, once one does
        "notes": _OPT,
    },
}


# File names generic enough to share as a file's type: they say what kind of file it is, not which.
GENERIC_NAMES = {"Dockerfile", "Makefile", "Procfile", "Caddyfile", "Justfile", "Gemfile", "Rakefile", "Jenkinsfile",
                 "Vagrantfile", "go.mod", "package.json", "pyproject.toml", "Cargo.toml", ".env"}


# Extensions common enough to share. A suffix is whatever follows the last dot, so an unlisted one
# (invoice.acme-billing) can carry a name from the repo: it is shared as "other".
KNOWN_EXT = {".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte", ".go", ".rs", ".java",
             ".kt", ".kts", ".scala", ".cs", ".fs", ".rb", ".php", ".swift", ".m", ".c", ".h", ".cc", ".cpp", ".hpp",
             ".ex", ".exs", ".erl", ".dart", ".lua", ".pl", ".r", ".jl", ".sql", ".prisma", ".proto", ".graphql",
             ".gql", ".sh", ".bash", ".ps1", ".bat", ".md", ".mdx", ".rst", ".txt", ".adoc", ".html", ".htm", ".css",
             ".scss", ".sass", ".less", ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml",
             ".env", ".properties", ".tf", ".hcl", ".csv", ".lock", ".mod", ".sum", ".gradle", ".dockerfile"}


def file_type(path):
    """What may be shared about a file in a private report: a known extension, a generic name, or 'other'."""
    name = Path(path).name
    if name in GENERIC_NAMES:
        return name
    ext = Path(path).suffix.lower()
    return ext if ext in KNOWN_EXT else ("no-extension" if not ext else "other")


def slug(text, limit=6):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:limit]) or "miss"


def registry_state(data, changed, missed):
    """What the registry held: no seam with both kinds of copy, only a glob, or a seam that names both."""
    if data is None:
        return "no-registry"
    exact = glob = False
    for s in data.get("seams", []):
        paths = [c["path"] for c in s["copies"]]
        if not any(check.copy_matches(p, f) for p in paths for f in changed):
            continue
        if any(p in missed for p in paths):
            exact = True
        elif any(check.copy_matches(p, m) for p in paths for m in missed):
            glob = True
    return "recorded-rule-missing" if exact else "glob-only" if glob else "none"


def make_report(root, changed, missed, rule, summary=None, shape="unknown", kind="unknown", cause=None, fix=None,
                repo=None, public=False, found_by="drift-fix", notes=None, today=None):
    root = Path(root)
    rel = lambda f: check.relative(f, root) or f
    changed, missed = [rel(f) for f in changed], [rel(f) for f in missed]
    try:
        data = check.load(root / check.REGISTRY)
    except (OSError, ValueError):
        data = None
    if not public and not summary:
        raise ValueError("a private report needs --summary: the shape in general words, with no names from the "
                         "repo. The rule stays in the local copy only.")
    summary = summary or rule
    copies = [{"role": "changed", "path": p, "file_type": file_type(p)} for p in changed]
    copies += [{"role": "missed", "path": p, "file_type": file_type(p)} for p in missed]
    report = {"miss_version": 1, "id": slug(summary), "reported": today or datetime.date.today().isoformat(),
              "summary": summary, "must_agree": rule, "shape": shape, "kind": kind,
              "languages": sorted({file_type(p).lstrip(".") for p in changed + missed if file_type(p).startswith(".")}),
              "copies": copies, "registry": registry_state(data, changed, missed), "found_by": found_by,
              "public": bool(public), "repo": repo if public else None,
              "commits": ({"cause": cause, "fix": fix} if public and cause and fix else None),
              "handled_by": None, "notes": notes}
    return report


def errors(report):
    out = []
    check.validate(report, MISS, report.get("id", "miss") if isinstance(report, dict) else "miss", out)
    return out


PRIVATE_RULE = "(kept private: the rule may name things in the repo; the summary gives the shape)"


def shareable(report):
    """The report as it may leave the repo: everything when public, the shape only when not.

    A private report shares only fields the reporter wrote to be shared (the summary, the shape) or
    that cannot name anything (roles, extensions, the registry state). The rule and the notes are free
    text written about the repo, so they stay behind, and so do paths, the repo and the commits."""
    if report["public"]:
        return dict(report)
    r = {k: v for k, v in report.items() if k not in ("repo", "commits", "notes")}
    r["must_agree"] = PRIVATE_RULE
    r["copies"] = [{"role": c["role"], "file_type": file_type(c.get("path") or c.get("file_type") or "")}
                   for c in report["copies"]]
    r["languages"] = sorted({c["file_type"].lstrip(".") for c in r["copies"] if c["file_type"].startswith(".")})
    return r


def render_md(report):
    r = shareable(report)
    lines = [f"### Missed seam: {r['summary']}", "",
             f"- Rule the copies had to keep: {r['must_agree']}",
             f"- Shape: {r['shape']} (kind {r.get('kind', 'unknown')})",
             f"- Registry at the time: {r['registry']}",
             f"- Found by: {r['found_by']}",
             "- Copies: " + "; ".join(f"{c['role']} `{c['path']}`" if "path" in c else f"{c['role']} {c['file_type']} file"
                                     for c in r["copies"])]
    if r.get("repo"):
        lines.append(f"- Repo: {r['repo']}")
    if r.get("commits"):
        lines.append(f"- Commit that missed the copy: {r['commits']['cause']}; the fix: {r['commits']['fix']}")
    lines += ["", "```json", json.dumps(r, indent=2), "```"]
    return "\n".join(lines) + "\n"


def load_library(folders=None):
    """[(path, report)] for every valid report in the folders (default: the library that ships with seamreg)."""
    out = []
    for folder in folders or [LIBRARY]:
        for f in sorted(Path(folder).glob("*.json")):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(r, dict) and not errors(r):
                out.append((f, r))
    return out


def catalog_text(reports):
    """Shapes ranked by how many reports no pass handles yet: the next kind to build is at the top."""
    by_shape = defaultdict(list)
    for _, r in reports:
        by_shape[r["shape"]].append(r)
    open_ = {s: [r for r in rs if not r.get("handled_by")] for s, rs in by_shape.items()}
    lines = [f"# Miss library: {len(reports)} reports", "",
             "Shapes with the most reports that no pass handles yet come first. Build the next kind from some "
             "of a shape's reports, and judge it on the others.", "",
             "| Shape | Reports | Not handled | Handled by | Registry at the time |", "|---|---|---|---|---|"]
    for shape, rs in sorted(by_shape.items(), key=lambda kv: (-len(open_[kv[0]]), -len(kv[1]), kv[0])):
        handled = Counter(r["handled_by"] for r in rs if r.get("handled_by"))
        reg = Counter(r["registry"] for r in rs)
        lines.append(f"| {shape} | {len(rs)} | {len(open_[shape])} | "
                     + (", ".join(f"{k} {n}" for k, n in handled.items()) or "-") + " | "
                     + ", ".join(f"{k} {n}" for k, n in reg.most_common()) + " |")
    lines += ["", "## Not handled yet", ""]
    for shape, rs in sorted(open_.items(), key=lambda kv: -len(kv[1])):
        for r in rs:
            lines.append(f"- **{shape}**: {r['summary']}" + (f" ({r['repo']})" if r.get("repo") else ""))
    return "\n".join(lines) + "\n"
