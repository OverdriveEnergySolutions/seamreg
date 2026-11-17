"""Draft a tie for a seam: a test in the repo's own framework that fails when the copies disagree.

    seams tie ID [ID ...] [--registry FILE]      write one packet per seam
    seams tie --collect [--registry FILE]        add the proven ties to the registry

A tie turns a note into an enforced check. The rule "every drift fix ships with a
tie" was words only: writing the test was left to whoever fixed the drift. This
command hands that job to one seam-tie-writer agent per seam. It writes to
<out>/tie/:

    brief.md                   the tie brief, the same for every packet
    packets/<id>.md            one packet per seam: its copies, and the repo's test frameworks
    results/<id>.json          where each agent writes what it did

The agent writes the test into the repo, runs it, and then breaks each copy in turn
to prove the test fails, and restores it. --collect adds a tie only when the result
proves both: the test passes on the repo as it is (or fails only for the drift the
seam records, marked as an expected failure), and it failed when a copy changed.
It never removes a tie and never adds one twice.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from seams import check

BRIEF = Path(__file__).with_name("tie-brief.md")
_TEXT = {"type": "string", "minLength": 1}
_OPT_TEXT = {"type": ["string", "null"]}
RESULT = {
    "type": "object",
    "required": ["id", "path", "command", "passes", "mutations"],
    "additionalProperties": False,
    "properties": {
        "id": _TEXT,
        "path": _OPT_TEXT,           # the test file; null when no tie could be written
        "test": _OPT_TEXT,           # the test name, as it appears in the file
        "covers": {"enum": ["all", "partial", None]},
        "note": _OPT_TEXT,           # which copies, when covers is partial
        "command": _OPT_TEXT,        # how to run only this test
        "passes": {"type": "boolean"},
        "expected_failure": {"type": "boolean"},  # marked xfail/skip because of the recorded drift
        "mutations": {"type": "array", "items": {
            "type": "object", "required": ["copy", "change", "failed"], "additionalProperties": False,
            "properties": {"copy": _TEXT, "change": _TEXT, "failed": {"type": "boolean"}}}},
        "files_written": {"type": "array", "items": _TEXT},
        "reason": _OPT_TEXT,         # why there is no tie, or anything the person should know
    },
}

# --- the repo's test frameworks --------------------------------------------------
# Each entry: name, language, how to tell it is in use, and the usual test file names.
# Evidence is a file the agent can open; the agent still reads the repo's own tests.

_JS = ("vitest", "jest", "mocha", "ava", "@playwright/test", "uvu", "tap")


def _read(p):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _package_json(root):
    out = []
    for p in sorted(root.glob("package.json")) + sorted(root.glob("*/package.json"))[:20] + \
            sorted(root.glob("*/*/package.json"))[:40]:
        if "node_modules" in p.parts:
            continue
        try:
            data = json.loads(_read(p))
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append((p, data))
    return out


def frameworks(root):
    """[{name, language, evidence, run}] for the test frameworks the repo uses, in the order checked
    (not ranked: the packet lists them all, and the agent picks the one beside the copies)."""
    root = Path(root)
    found = []

    def add(name, language, evidence, run):
        if not any(f["name"] == name and f["evidence"] == evidence for f in found):
            found.append({"name": name, "language": language, "evidence": evidence, "run": run})

    rel = lambda p: p.relative_to(root).as_posix()
    # Python
    for f in ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"):
        text = _read(root / f)
        if "[tool.pytest" in text or "[pytest]" in text or "[tool:pytest]" in text:
            add("pytest", "python", f, "pytest <file>::<test>")
    if (root / "conftest.py").is_file() or any(root.glob("*/conftest.py")):
        add("pytest", "python", "conftest.py", "pytest <file>::<test>")
    if any(root.glob("manage.py")):
        add("django test", "python", "manage.py", "python manage.py test <module>")
    # JavaScript and TypeScript
    for p, data in _package_json(root):
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        script = ((data.get("scripts") or {}).get("test") or "") if isinstance(data.get("scripts"), dict) else ""
        where = rel(p)
        for name in _JS:
            if name in deps or re.search(rf"\b{re.escape(name.split('/')[-1])}\b", script):
                add(name, "javascript/typescript", where, f"npm test in {p.parent.relative_to(root).as_posix() or '.'}"
                    + (f" (scripts.test: {script})" if script else ""))
        if "node --test" in script:
            add("node:test", "javascript/typescript", where, f"scripts.test: {script}")
        if "bun test" in script:
            add("bun test", "javascript/typescript", where, f"scripts.test: {script}")
    # Go, Rust, JVM, Ruby, PHP, .NET, Elixir, shell
    if (root / "go.mod").is_file():
        add("go test", "go", "go.mod", "go test ./<pkg> -run <Test>")
    if (root / "Cargo.toml").is_file():
        add("cargo test", "rust", "Cargo.toml", "cargo test <name>")
    for f, name in (("pom.xml", "junit (maven)"), ("build.gradle", "junit (gradle)"),
                    ("build.gradle.kts", "junit (gradle)")):
        if (root / f).is_file():
            add(name, "java/kotlin", f, "mvn test -Dtest=<Class>" if f == "pom.xml" else "gradle test --tests <Class>")
    if (root / ".rspec").is_file() or (root / "spec" / "spec_helper.rb").is_file():
        add("rspec", "ruby", ".rspec" if (root / ".rspec").is_file() else "spec/spec_helper.rb", "bundle exec rspec <file>")
    elif (root / "Gemfile").is_file() and (root / "test").is_dir():
        add("minitest", "ruby", "Gemfile", "bin/rails test <file> or ruby -Itest <file>")
    for f in ("phpunit.xml", "phpunit.xml.dist"):
        if (root / f).is_file():
            add("phpunit", "php", f, "vendor/bin/phpunit --filter <test>")
    for p in sorted(root.glob("**/*.csproj"))[:50]:
        text = _read(p)
        for name in ("xunit", "nunit", "MSTest"):
            if name.lower() in text.lower():
                add(name, "c#", rel(p), "dotnet test --filter <Name>")
    if (root / "mix.exs").is_file():
        add("ExUnit", "elixir", "mix.exs", "mix test <file>")
    bats = sorted(root.glob("**/*.bats"))
    if bats:
        add("bats", "shell", rel(bats[0]), "bats <file>")
    return found


_TEST_NAME = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go|rb|exs)|[^/]*\.(test|spec)\.[cm]?[jt]sx?|"
                        r"[^/]*_spec\.rb|[^/]*Tests?\.(java|kt|cs|php)|[^/]*\.bats)$")


def nearby_tests(root, copies, limit=5):
    """Existing test files, the ones closest to the copies first: the agent copies their style."""
    root = Path(root)
    tests = [f for f in check.Repo(root).files() if _TEST_NAME.search(f)]
    dirs = [c["path"].split("/")[:-1] for c in copies]

    def distance(f):
        parts = f.split("/")[:-1]
        best = 99
        for d in dirs:
            common = 0
            for a, b in zip(parts, d):
                if a != b:
                    break
                common += 1
            best = min(best, len(parts) + len(d) - 2 * common)
        return (best, f)

    return sorted(tests, key=distance)[:limit]


# --- packets ----------------------------------------------------------------------

def packet_md(seam, root, out, fws, tests):
    result = out / "tie" / "results" / f"{seam['id']}.json"
    copies = "\n".join(f"- `{c['path']}`" + (f" (`{c['symbol']}`)" if c.get("symbol") else "")
                       + (f": {c['note']}" if c.get("note") else "") for c in seam["copies"])
    lines = [f"# Tie: {seam['id']}", "",
             f"Read the brief first: `{out / 'tie' / 'brief.md'}`.", "",
             f"- Repo root: `{root}`",
             f"- Output file: `{result}`", "",
             f"## {seam['title']} (kind {seam['kind']}, risk {seam['risk']})", "",
             f"**Must agree:** {seam['must_agree']}", "",
             f"**If one copy changes alone:** {seam['consequence']}", "",
             "**Copies:**", "", copies]
    if seam.get("intentional_differences"):
        lines += ["", f"**Deliberate differences, the tie must allow these:** {seam['intentional_differences']}"]
    if seam.get("suggested_tie"):
        lines += ["", f"**Suggested tie (from the review):** {seam['suggested_tie']}"]
    if seam.get("drift"):
        d = seam["drift"]
        lines += ["", f"**Known drift ({d['source']}):** {d['text']}", "",
                  "The copies differ today. Write the tie to the rule in \"must agree\", confirm it fails "
                  "because of this drift, and mark it as an expected failure (see the brief). Do not fix the drift."]
    if seam.get("ties"):
        lines += ["", "**Ties it has already (do not duplicate them; cover what they miss):**", ""]
        lines += [f"- `{t['path']}`" + (f" (`{t['test']}`)" if t.get("test") else "") + f", covers {t['covers']}"
                  + (f": {t['note']}" if t.get("note") else "") for t in seam["ties"]]
    lines += ["", "## The repo's tests", ""]
    if fws:
        lines += [f"- {f['name']} ({f['language']}), seen in `{f['evidence']}`. Runs as: {f['run']}" for f in fws]
    else:
        lines += ["- No test framework found from the usual config files. Look for one yourself. If the repo "
                  "has none, see the brief: \"A repo with no tests\"."]
    if tests:
        lines += ["", "Test files nearest the copies (follow their style, imports and folder):", ""]
        lines += [f"- `{t}`" for t in tests]
    return "\n".join(lines) + "\n"


def _load_valid(registry_path):
    data = check.load(registry_path)
    errors = check.validate_errors(data)
    if errors:
        raise ValueError(f"{registry_path} does not match the schema: {'; '.join(errors[:3])}")
    return data


def _inside(folder, name):
    path = (folder / name).resolve()
    path.relative_to(folder.resolve())
    return path


def write_packets(registry_path, root, out, ids):
    """One packet per seam id. Packets from an earlier run are deleted first."""
    data = _load_valid(registry_path)
    root, out = Path(root).resolve(), Path(out).resolve()
    by_id = {s["id"]: s for s in data["seams"]}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"{registry_path} has no seam with the id {', '.join(missing)}")
    chosen = [by_id[i] for i in dict.fromkeys(ids)]
    d = out / "tie"
    (d / "packets").mkdir(parents=True, exist_ok=True)
    (d / "results").mkdir(exist_ok=True)
    for old in (d / "packets").glob("*.md"):
        old.unlink()
    (d / "brief.md").write_text(BRIEF.read_text(encoding="utf-8"), encoding="utf-8")
    fws = frameworks(root)
    for s in chosen:
        _inside(d / "packets", f"{s['id']}.md").write_text(
            packet_md(s, root, out, fws, nearby_tests(root, s["copies"])), encoding="utf-8")
    return chosen, fws


def untied(data, risks=("high", "medium")):
    """Seam ids with no full tie, highest risk first: the ones `seams tie --untied` picks."""
    pick = [s for s in data["seams"] if s["risk"] in risks and not check.fully_tied(s)]
    return [s["id"] for s in sorted(pick, key=lambda s: check.RISKS.index(s["risk"]))]


# --- collect ----------------------------------------------------------------------

def _refuse(res, seam):
    """Why this result cannot become a tie, or None when it can."""
    if not res.get("path"):
        return f"no tie written: {res.get('reason') or 'no reason given'}"
    if not res.get("covers"):
        return "the result does not say what the tie covers (all or partial)"
    if res["covers"] == "partial" and not res.get("note"):
        return "covers partial, so the result must say which copies (note)"
    if not res["passes"] and not res.get("expected_failure"):
        return "the test does not pass, and it is not marked as an expected failure"
    if res.get("expected_failure") and not seam.get("drift"):
        return "the test is marked as an expected failure, but the seam records no drift"
    muts = res["mutations"]
    if not muts:
        return "no mutation was run: nothing shows the test fails when a copy changes"
    bad = [m["copy"] for m in muts if not m["failed"]]
    if res["covers"] == "all" and bad:
        return f"covers all, but the test still passed when these copies changed: {', '.join(bad)}"
    if not any(m["failed"] for m in muts):
        return "the test passed after every mutation: nothing shows it catches drift"
    if res["covers"] == "all" and len(seam["copies"]) >= 2:
        # A test that reads one copy and restates the other passes the one-side check and is
        # still a third copy. Breaking two different copies is the cheapest proof it reads both.
        hit = {i for i, c in enumerate(seam["copies"]) for m in muts if check.copy_matches(c["path"], m["copy"])}
        if len(hit) < 2:
            return ("covers all, but the mutations broke fewer than two of the seam's copies; "
                    "break another copy too, or say covers partial")
    return None


def collect(registry_path, root, out):
    """Add each proven tie to its seam. Returns (report lines, schema errors, counts)."""
    data = _load_valid(registry_path)
    repo = check.Repo(Path(root))
    by_id = {s["id"]: s for s in data["seams"]}
    lines, counts = [], {"files": 0, "added": 0, "refused": 0}
    for f in sorted((Path(out) / "tie" / "results").glob("*.json")):
        counts["files"] += 1
        try:
            res = check.load(f)
        except (ValueError, OSError) as e:
            lines.append(f"- `{f.name}`: could not be read: {e}")
            counts["refused"] += 1
            continue
        errors = []
        check.validate(res, RESULT, f.name, errors)
        if errors:
            lines.append(f"- `{f.name}`: wrong shape: {'; '.join(errors[:2])}")
            counts["refused"] += 1
            continue
        seam = by_id.get(res["id"])
        if seam is None:
            lines.append(f"- `{res['id']}`: no such seam in the registry")
            counts["refused"] += 1
            continue
        why = _refuse(res, seam)
        if why is None:
            files, problem = repo.resolve(res["path"])
            if problem:
                why = f"the test file '{res['path']}' {problem}"
            elif res.get("test") and not repo.has_test(files, res["test"]):
                why = f"the test name '{res['test']}' does not appear in '{res['path']}'"
        if why:
            lines.append(f"- `{res['id']}`: **not added**: {why}")
            counts["refused"] += 1
            continue
        tie = {"path": res["path"]}
        if res.get("test"):
            tie["test"] = res["test"]
        tie["covers"] = res["covers"]
        if res.get("note"):
            tie["note"] = res["note"]
        ties = seam.setdefault("ties", [])
        if any(t["path"] == tie["path"] and t.get("test") == tie.get("test") for t in ties):
            lines.append(f"- `{res['id']}`: the tie `{tie['path']}` is in the registry already")
            continue
        ties.append(tie)
        if seam.get("suggested_tie") and tie["covers"] == "all":
            seam["suggested_tie"] = None
        counts["added"] += 1
        tried = ", ".join(f"{m['copy']} ({m['change']})" for m in res["mutations"] if m["failed"])
        missed = [f"{m['copy']} ({m['change']})" for m in res["mutations"] if not m["failed"]]
        lines.append(f"- `{res['id']}`: **tie added**: `{tie['path']}`" + (f" `{tie['test']}`" if "test" in tie else "")
                     + f", covers {tie['covers']}. Run: `{res['command']}`. Failed when changed: {tried}."
                     + (f" Still passed when changed (not covered): {', '.join(missed)}." if missed else "")
                     + (" Marked as an expected failure until the recorded drift is fixed: when the fix lands, "
                        "remove the marker." if res.get("expected_failure") else "")
                     + (f" Note: {res['reason']}" if res.get("reason") else ""))
    errors = check.validate_errors(data)
    if not errors:
        Path(registry_path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return lines, errors, counts
