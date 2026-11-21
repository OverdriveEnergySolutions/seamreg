"""The `seams` command.

Built: init, check (with --changed, --staged and --diff), schema, scan,
split, merge, notes, verify, tie, next, triage and mcp. Each stage reads and writes
plain files, so one stage can run without the others.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from seams import check as checker
from seams.check import RULES_IGNORE_LINES
from seams import split as splitter

DEFAULT_CHECKER = "scripts/seams_check.py"
EMPTY_REGISTRY = {"schema_version": 1, "seams": []}

SNIPPETS = Path(__file__).with_name("snippets")


def snippet(name, checker=DEFAULT_CHECKER):
    """A setup snippet shipped with the package, pointed at this repo's checker copy."""
    return (SNIPPETS / name).read_text(encoding="utf-8").replace(DEFAULT_CHECKER, checker)


def _indent(text):
    return "\n".join("    " + line if line else "" for line in text.rstrip("\n").split("\n"))


def setup_text(root, checker):
    claude_ignored = _claude_ignored(root)
    hook_file = ".claude/settings.local.json" if claude_ignored else ".claude/settings.json"
    lines = ["Add these now:", "",
             "1. CI. A workflow file. On a pull request it posts one comment, and edits it on",
             "   each push. If the repo takes pull requests from forks, use the two files",
             "   github-actions-forks.yml and github-actions-forks-comment.yml in",
             f"   {SNIPPETS}",
             "   instead: a fork's token cannot post.", "", _indent(snippet("github-actions.yml", checker)), "",
             f"2. Claude Code: warn the agent before it edits one copy of a seam. Add to {hook_file}:", "",
             _indent(snippet("claude-code-settings.json", checker))]
    if claude_ignored:
        lines += ["", "   .claude/ is ignored by git here, so this hook reaches this machine only. To give it",
                  "   to the team, un-ignore .claude/settings.json, or have the script that sets up a",
                  "   clone write it to the project's .claude/settings.json. Never put it in the",
                  "   user-wide ~/.claude/settings.json: it would run in every repo on the machine."]
    lines += ["", "3. A commit check, for edits made without an agent. " + _hook_setup(root), "",
              "   With the pre-commit framework:", "",
              _indent(snippet("pre-commit.yaml", checker)), "",
              "   With a plain git hook, add these lines to it instead:", "",
              _indent(snippet("git-hook.sh", checker)), "",
              "After the first review (`seams merge --apply`):", "",
              '4. Notes. Add "notes" to seams.json, then run `seams notes` and commit what it writes.',
              '   One value, or a list for each kind of agent that works in the repo:',
              '   "rules" writes .claude/rules/seams/ for Claude Code, "cursor" writes',
              '   .cursor/rules/seams/, and "copilot" writes .github/instructions/seams-*.',
              '   Each note costs nothing until a copy is opened. "rules" needs .claude/rules/',
              '   in git. If .gitignore ignores .claude/, replace that line with these:',
              *[f"       {line}" for line in RULES_IGNORE_LINES],
              '   "claude-md" and "agents-md" write blocks into CLAUDE.md or AGENTS.md files',
              '   (high and medium risk). "claude-md-high" and "agents-md-high" keep only',
              '   high risk, for a large registry.', "",
              "5. Planning. Paste this into CLAUDE.md or AGENTS.md:", "",
              _indent(snippet("agent-instructions.md", checker)), "",
              "6. Any agent: the same lookups as an MCP server. For Claude Code, commit this as .mcp.json;",
              "   other agents take the same command in their own MCP config:", "",
              _indent(snippet("mcp.json", checker)), ""]
    return "\n".join(lines)


def _hook_setup(root):
    """Which commit-hook setup the repo has, in one sentence for the printout."""
    root = Path(root)
    if (root / ".pre-commit-config.yaml").is_file():
        return "This repo uses the pre-commit framework: add the first form to .pre-commit-config.yaml."
    if (root / ".husky").is_dir():
        return "This repo uses husky: add the plain lines to .husky/pre-commit."
    hooks_path = checker._git(root, "config", "core.hooksPath") if (root / ".git").exists() else None
    if hooks_path and hooks_path.returncode == 0 and hooks_path.stdout.strip():
        return f"This repo keeps its hooks in {hooks_path.stdout.strip()}: add the plain lines to pre-commit there."
    return ("This repo has no commit-hook setup that git tracks. Skip this item, or put the plain lines in "
            ".git/hooks/pre-commit, which reaches only this clone. Adding a hook manager only for this check "
            "is the owner's call. The CI job and the Claude Code hook still cover pull requests and agent edits.")


def _claude_ignored(root):
    return checker._ignored(root, ".claude/settings.json")


def _checker_version(path):
    m = re.search(r'^__version__ = "([^"]+)"', path.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def cmd_init(args):
    root = Path(args.root)
    problem = checker.path_problem(args.checker)
    if problem:
        print(f"seams: --checker '{args.checker}' {problem}", file=sys.stderr)
        return 2
    dest = root / args.checker
    body = Path(checker.__file__).read_bytes()

    if dest.exists() and dest.read_bytes() != body and not args.upgrade:
        print(f"seams: {args.checker} exists and is not checker {checker.__version__} "
              f"(it is {_checker_version(dest) or 'unknown'}). "
              "Run `seams init --upgrade` to replace it.", file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    dest.chmod(0o755)
    print(f"wrote {args.checker} (checker {checker.__version__})")

    reg = root / checker.REGISTRY
    if reg.exists():
        print(f"kept {checker.REGISTRY}")
    else:
        reg.write_text(json.dumps(EMPTY_REGISTRY, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {checker.REGISTRY} (empty)")
    print()
    print(setup_text(root, args.checker))
    return 0


def cmd_check(args):
    copy = Path(args.root) / args.checker
    if copy.is_file():
        found = _checker_version(copy)
        if found != checker.__version__:
            print(f"seams: warning: {args.checker} is checker {found or 'unknown'}, "
                  f"this tool is {checker.__version__}. CI runs the copy. "
                  "Run `seams init --upgrade` to match them.", file=sys.stderr)
    passthrough = ["--root", args.root]
    if args.registry:
        passthrough += ["--registry", args.registry]
    if args.changed:
        passthrough += ["--changed", *args.changed]
    if args.diff:
        passthrough += ["--diff", args.diff]
    if args.staged:
        passthrough.append("--staged")
    if args.about:
        passthrough += ["--about", args.about]
    if args.fail_untied:
        passthrough.append("--fail-untied")
    if args.markdown:
        passthrough.append("--markdown")
    return checker.main(passthrough)


def cmd_notes(args):
    return checker.main(["--root", args.root, "--notes"])


def cmd_schema(args):
    schema = checker.SETTINGS_SCHEMA if args.settings else checker.SCHEMA
    text = json.dumps(schema, indent=2) + "\n"
    if args.write:
        Path(args.write).write_text(text, encoding="utf-8")
        print(f"wrote {args.write}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_scan(args):
    from seams import scan

    root = Path(args.root)
    if not root.is_dir():
        print(f"seams: root '{root}' is not a folder", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else root / ".seams-scan"
    registry = None
    reg_path = root / checker.REGISTRY
    if reg_path.exists():
        try:
            registry = checker.load(reg_path)
            if checker.validate_errors(registry):
                raise ValueError("it does not match the schema")
        except ValueError as e:
            print(f"seams: warning: ignoring {checker.REGISTRY} ({e}); leads are not marked covered.",
                  file=sys.stderr)
            registry = None
    baseline = None
    base_path = root / scan.BASELINE
    if base_path.exists():
        try:
            baseline = scan.load_baseline(base_path)
        except ValueError as e:
            print(f"seams: warning: ignoring it: {e}", file=sys.stderr)
    if args.new and registry is None and baseline is None:
        print(f"seams: --new needs a {checker.REGISTRY} or a {scan.BASELINE} to compare against.",
              file=sys.stderr)
        return 2
    try:
        doc = scan.scan(root, registry=registry, since=args.since, baseline=baseline)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"seams: cannot list the changes since {args.since}: {e}", file=sys.stderr)
        return 2
    scan.write(doc, out, only_new=args.new)
    print(f"read {doc['files_read']} files ({doc['lines_read']} lines) in "
          f"{len(doc['areas'])} areas, {doc['seconds']} s")
    if doc.get("since"):
        print(f"kept leads that touch the {doc['since']['changed_files']} files changed since {args.since}")
    for kind, c in doc["counts"].items():
        new = f", {c['new']:5} new" if registry or baseline is not None else ""
        print(f"  {kind:14} {c['all']:6} leads, {c['cross_area']:5} across areas{new}")
    if doc.get("registry"):
        r = doc["registry"]
        print(f"the scan has a lead for {len(r['found_by_scan'])} of the {r['seams']} seams in {checker.REGISTRY}")
    print(f"wrote {out / 'leads.md'} and leads.json. Leads are hints, not seams.")
    return 0


def cmd_baseline(args):
    from seams import scan

    out = _out(args)
    try:
        doc = splitter.load_leads(out)
    except FileNotFoundError:
        print(f"seams: no {out / 'leads.json'}. Run `seams scan` first.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"seams: {e}", file=sys.stderr)
        return 2
    if doc.get("since"):
        print("seams: this scan was filtered with --since, so it does not hold every lead. "
              "Run `seams scan` without --since, then `seams baseline`.", file=sys.stderr)
        return 2
    path = Path(args.root) / scan.BASELINE
    old = scan.load_baseline(path) if path.exists() else set()
    shown = out / "shown.json"
    if shown.exists():
        new = set(json.loads(shown.read_text(encoding="utf-8")))
        what = "leads the review packets showed"
    else:
        new = {l["fingerprint"] for l in doc["leads"]}
        what = "leads in the last scan (no split ran, so all of them)"
    scan.write_baseline(path, old | new)
    covered = sum(1 for l in doc["leads"] if l.get("fingerprint") in new)
    print(f"wrote {scan.BASELINE}: {len(old | new)} lead fingerprints ({len(new - old)} added, from the {what}: "
          f"{len(new)} fingerprints for {covered} leads, because leads of the same kind in the same files "
          "count once). Commit it: a re-scan treats these leads as old.")
    return 0


def cmd_apply(args):
    from seams import merge

    out = _out(args)
    if not (out / "seams.proposed.json").exists():
        print(f"seams: no {out / 'seams.proposed.json'}. Run `seams merge` first.", file=sys.stderr)
        return 2
    confirm = [i for i in (args.confirm or "").split(",") if i]
    proposed, errors = merge.apply_proposal(args.root, out, confirm)
    if errors:
        for e in errors:
            print(e)
        print(f"seams: the proposal fails the check ({len(errors)} problem(s)). {checker.REGISTRY} is unchanged.")
        return 1
    print(f"wrote {checker.REGISTRY} ({len(proposed['seams'])} seams) from {out / 'seams.proposed.json'}."
          + (f" Drift confirmed: {', '.join(confirm)}." if confirm else ""))
    if (out / "leads.json").exists():
        cmd_baseline(args)
    return 0


def cmd_rerate(args):
    from seams import rerate

    out = _out(args)
    reg = Path(args.registry) if args.registry else Path(args.root) / checker.REGISTRY
    if not reg.exists():
        print(f"seams: no {reg}.", file=sys.stderr)
        return 2
    try:
        if args.collect:
            lines, counts, errors = rerate.collect(reg, out)
            report = out / "rerate" / "rerate-report.md"
            report.write_text("# Risk re-rating report\n\n" + ("\n".join(lines) or "No risk changed.") + "\n",
                              encoding="utf-8")
            if errors:
                print(f"seams: the result does not match the schema; {reg} is unchanged.", file=sys.stderr)
                return 1
            print(f"{counts['rated']} seams rated from {counts['files']} file(s): {counts['up']} raised, "
                  f"{counts['down']} lowered, written to {reg}. Report: {report}")
            return 0
        paths = rerate.write_packets(reg, args.root, out, args.batch)
    except ValueError as e:
        print(f"seams: {e}", file=sys.stderr)
        return 2
    print(f"{len(paths)} re-rating packet(s) in {out / 'rerate' / 'packets'}. Start one seam-risk-rater agent per "
          "packet, then run `seams rerate --collect`.")
    return 0


def cmd_verify(args):
    from seams import verify

    out = _out(args)
    reg = Path(args.registry) if args.registry else Path(args.root) / checker.REGISTRY
    if not reg.exists():
        print(f"seams: no {reg}.", file=sys.stderr)
        return 2
    if args.collect:
        try:
            lines, private, errors, counts = verify.collect(reg, out)
        except ValueError as e:
            print(f"seams: {e}", file=sys.stderr)
            return 2
        report = out / "verify" / "verify-report.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Drift check report\n\nDrift here comes from reading code. Confirm it before "
                          "anyone calls it a bug: read both sides, and when the copies differ as stated, run "
                          "`seams apply --confirm <id,id>`.\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
        if private:
            from seams import merge
            merge.write_private(out / "verify" / "private-findings.md",
                                "# Private findings from the drift check\n\n", "\n".join(private))
            print(f"security findings kept out of the registry: {out / 'verify' / 'private-findings.md'}")
        if errors:
            print(f"seams: the result does not match the schema; {reg} is unchanged.", file=sys.stderr)
            return 1
        print(f"{counts['files']} result file(s), {counts['drift']} with new drift written to {reg}, "
              f"{counts['sensitive']} security finding(s). Report: {report}")
        return 0
    ids = set(args.ids.split(",")) if args.ids else None
    try:
        chosen = verify.write_packets(reg, args.root, out, tuple(args.risk.split(",")), ids, args.all,
                                      args.sample, args.seed, args.reading)
    except ValueError as e:
        print(f"seams: {e}", file=sys.stderr)
        return 2
    print(f"{len(chosen)} drift-check packet(s) in {out / 'verify' / 'packets'}, replacing any from "
          "an earlier run. Start one seam-drift-checker agent per packet, then run `seams verify --collect`.")
    if chosen:
        print(verify.cost_text(len(chosen)))
    if args.sample is not None:
        print("picked at random: " + ", ".join(s["id"] for s in chosen))
    return 0


def _out(args):
    return Path(args.out) if args.out else Path(args.root) / ".seams-scan"


def cmd_mcp(args):
    return checker.main(["--mcp", "--root", args.root])


def cmd_report_miss(args):
    from seams import misses
    try:
        r = misses.make_report(args.root, args.changed, args.missed, args.rule, args.summary, args.shape, args.kind,
                               args.cause, args.fix, args.repo, args.public, args.found_by, args.notes)
    except ValueError as e:
        print(f"seams: {e}", file=sys.stderr)
        return 2
    errs = misses.errors(r)
    if errs:
        print("seams: the report does not match its format: " + "; ".join(errs[:3]), file=sys.stderr)
        return 2
    out = _out(args) / "misses"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{r['reported']}-{r['id']}.json"
    path.write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    print(misses.render_md(r), end="")
    print(f"\nSaved the full report: {path} (git ignores it).")
    if r["registry"] == "recorded-rule-missing":
        print("A seam already lists both copies, but its rule did not say this. Sharpen its must_agree too.")
    else:
        print("Add the seam to seams.json in the same change as the fix, with a tie if you can.")
    print("To help seamreg learn this shape, share the text above (an issue on the seamreg repo). "
          + ("It holds the repo and commits." if r["public"] else
             "It holds only the shape: no paths, no commits, no code. Add --public and the commits for a public repo."))
    return 0


def cmd_catalog(args):
    from seams import misses
    reports = misses.load_library(args.folders or None)
    print(misses.catalog_text(reports), end="")
    return 0


def cmd_looked_at(args):
    from seams import lookedat
    out = _out(args)
    doc = lookedat.collect(args.root, args.sources, args.prefix or (), args.passes or ())
    out.mkdir(parents=True, exist_ok=True)
    (out / "looked-at.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"{doc['transcripts']} transcript(s): {len(doc['read'])} files read, {len(doc['searched'])} searched. "
          f"Wrote {out / 'looked-at.json'}. `seams split --focus open` shows it to the reviewer.")
    return 0


def cmd_next(args):
    from seams import passes
    print(passes.next_text(args.root, _out(args)), end="")
    return 0


def cmd_triage(args):
    from seams import passes
    out = _out(args)
    reg = Path(args.registry) if args.registry else Path(args.root) / checker.REGISTRY
    try:
        data = checker.load(reg)
    except (OSError, ValueError) as e:
        print(f"seams: cannot read {reg}: {e}", file=sys.stderr)
        return 2
    if checker.validate_errors(data):
        print(f"seams: {reg} does not match the schema. Run `seams check`.", file=sys.stderr)
        return 2
    text = passes.triage_text(data, args.top)
    out.mkdir(parents=True, exist_ok=True)
    (out / "triage.md").write_text(text, encoding="utf-8")
    print(text, end="")
    print(f"Saved: {out / 'triage.md'}")
    return 0


def cmd_tie(args):
    from seams import tie

    out = _out(args)
    reg = Path(args.registry) if args.registry else Path(args.root) / checker.REGISTRY
    if not reg.exists():
        print(f"seams: no {reg}.", file=sys.stderr)
        return 2
    try:
        if args.collect:
            lines, errors, counts = tie.collect(reg, args.root, out)
            report = out / "tie" / "tie-report.md"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("# Tie report\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
            print("\n".join(lines))
            if errors:
                print(f"seams: the result does not match the schema; {reg} is unchanged.", file=sys.stderr)
                return 1
            print(f"{counts['files']} result(s): {counts['added']} tie(s) added to {reg}, "
                  f"{counts['refused']} not added. Report: {report}. Review the new tests like any "
                  "other code, then commit them with seams.json.")
            return 0
        ids = list(args.ids)
        if args.untied:
            ids += tie.untied(tie._load_valid(reg), tuple(args.risk.split(",")))
        if not ids:
            print("seams: name the seam ids to tie, or pass --untied.", file=sys.stderr)
            return 2
        chosen, fws = tie.write_packets(reg, args.root, out, ids)
    except ValueError as e:
        print(f"seams: {e}", file=sys.stderr)
        return 2
    print(f"{len(chosen)} tie packet(s) in {out / 'tie' / 'packets'}, replacing any from an earlier run. "
          "Start one seam-tie-writer agent per packet, then run `seams tie --collect`.")
    print("Test frameworks found: " + (", ".join(f"{f['name']} ({f['evidence']})" for f in fws) or
                                       "none. The agents will look for one, or say there is none."))
    print("Each agent writes a test file in the repo and runs the repo's tests, so run it where that is safe.")
    return 0


def cmd_split(args):
    split = splitter
    out = _out(args)
    try:
        doc = split.load_leads(out)
    except FileNotFoundError:
        print(f"seams: no {out / 'leads.json'}. Run `seams scan` first.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"seams: {e}", file=sys.stderr)
        return 2
    known = None
    if sum(map(bool, (args.gap, args.focus, args.lead_check))) > 1:
        print("seams: --gap, --focus and --lead-check are separate passes. Pick one.", file=sys.stderr)
        return 2
    if args.gap or args.focus or args.lead_check:
        reg = Path(args.root) / checker.REGISTRY
        try:
            data = checker.load(reg)
            if checker.validate_errors(data):
                raise ValueError("it does not match the schema")
        except FileNotFoundError:
            flag = "focus" if args.focus else "lead-check" if args.lead_check else "gap"
            print(f"seams: --{flag} needs a {checker.REGISTRY} from a first review.",
                  file=sys.stderr)
            return 2
        except ValueError as e:
            print(f"seams: cannot read {reg}: {e}", file=sys.stderr)
            return 2
        if not data["seams"]:
            print(f"seams: {checker.REGISTRY} records no seams yet. Run a first review first.",
                  file=sys.stderr)
            return 2
        known = data["seams"]
    if args.lead_check:
        return _split_lead_check(args, doc, out, known)
    try:
        bins = split.write(doc, args.root, out, args.max_lines, args.new_only, args.cross_area_only, known,
                           args.focus)
    except ValueError as e:
        print(f"seams: {e}", file=sys.stderr)
        return 2
    if not bins:
        print("seams: no leads are left after the filters. Nothing to review.")
        return 0
    from seams import passes
    kind = (f"focus:{args.focus}" if args.focus else "gap" if args.gap else
            "lead-only" if args.new_only or args.cross_area_only else "first")
    try:
        current = checker.load(Path(args.root) / checker.REGISTRY)
    except (OSError, ValueError):
        current = None
    passes.record_pass(out, kind, len(bins), sum(len(b["leads"]) for b in bins), current)
    total = sum(b["lines"] for b in bins)
    print(f"{len(bins)} packets in {out / 'packets'}, {total} lines of non-test code.")
    for b in bins:
        print(f"  {b['name']:40} {b['lines']:8} lines {len(b['leads']):6} leads")
    print(f"Plan and cost estimate: {out / 'plan.md'}. Start one seam-reviewer agent per packet.")
    return 0


def _split_lead_check(args, doc, out, known):
    from seams import leadcheck, passes
    bins = leadcheck.write(doc, args.root, out, known, keep_agreeing=args.keep_agreeing)
    if not bins:
        print("seams: every strong lead is covered by a recorded seam. Nothing to check.")
        return 0
    n = sum(len(b["leads"]) for b in bins)
    passes.record_pass(out, "lead-check", len(bins), n, {"seams": known})
    print(f"{len(bins)} lead check packets in {out / 'packets'}, {n} leads, about "
          f"${leadcheck.COST_PER_LEAD * n:.0f} with Sonnet. Plan: {out / 'plan.md'}.")
    print("Start one seam-lead-checker agent per packet, then run `seams merge`.")
    return 0


def split_focus_names():
    from seams import split
    return split.FOCUS


def cmd_merge(args):
    from seams import merge

    out = _out(args)
    if not (out / "reviews").is_dir():
        print(f"seams: no {out / 'reviews'}. Run `seams split` and the reviewers first.", file=sys.stderr)
        return 2
    proposed, errors, private, applied = merge.write(args.root, out, args.plan, args.apply)
    print(f"proposed {len(proposed['seams'])} seams: {out / 'seams.proposed.json'}")
    print(f"report: {out / 'merge-report.md'}")
    if private:
        print(f"security findings kept out of the registry: {out / 'private-findings.md'}")
    if errors:
        print(f"seams: the proposal fails the check ({len(errors)} problem(s)); see the report.",
              file=sys.stderr)
        return 1
    from seams import passes
    short = passes.triage_short(proposed)
    if short:
        print(short)
    if applied:
        print(f"wrote {checker.REGISTRY}. Run `seams check` in CI to keep it true.")
        if (out / "leads.json").exists():
            cmd_baseline(args)  # a filtered scan explains itself; the registry is written either way
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="seams", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"seams {checker.__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="copy the checker into a repo and start seams.json")
    p.add_argument("--root", default=".")
    p.add_argument("--checker", default=DEFAULT_CHECKER, help="where the copy goes, repo-relative")
    p.add_argument("--upgrade", action="store_true", help="replace an older or edited copy")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", help="fail when seams.json no longer matches the repo")
    p.add_argument("--root", default=".")
    p.add_argument("--registry")
    p.add_argument("--checker", default=DEFAULT_CHECKER, help="the repo's copy, for a version warning")
    lookup = p.add_mutually_exclusive_group()
    lookup.add_argument("--changed", nargs="+", metavar="FILE", help="list the seams these files touch")
    lookup.add_argument("--diff", metavar="REF", help="list the seams touched since the merge base with REF")
    lookup.add_argument("--staged", action="store_true", help="list the seams the staged changes touch")
    lookup.add_argument("--about", metavar="TEXT", help="list the seams that mention TEXT (for planning)")
    p.add_argument("--fail-untied", action="store_true",
                   help="exit 1 when a change leaves a copy of an untied seam alone")
    p.add_argument("--markdown", action="store_true",
                   help="with --changed, --diff or --staged: print the pull request comment")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("scan", help="find candidate seams without an agent")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="output folder (default: <root>/.seams-scan)")
    p.add_argument("--new", action="store_true",
                   help="list only leads that seams.json does not already cover")
    p.add_argument("--since", metavar="REF",
                   help="keep only leads that touch a file changed since the merge base with REF")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("split", help="group the scan's areas into one packet per reviewer agent")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--max-lines", type=int, default=splitter.DEFAULT_MAX_LINES,
                   help=f"non-test code lines per packet (default {splitter.DEFAULT_MAX_LINES})")
    p.add_argument("--new-only", action="store_true",
                   help="drop leads seams.json already covers; reviewers check leads, not whole areas")
    p.add_argument("--cross-area-only", action="store_true",
                   help="drop leads inside one area; reviewers check leads, not whole areas")
    p.add_argument("--gap", action="store_true",
                   help="a second full pass: reviewers get the seams seams.json records and hunt for the ones it misses")
    p.add_argument("--lead-check", action="store_true",
                   help="after a first review: cheap agents judge every strong lead no recorded seam covers, "
                        "and record the seams whose copies differ or share a mistake")
    p.add_argument("--keep-agreeing", action="store_true",
                   help="with --lead-check: also record seams whose copies agree today (more seams, more noise)")
    p.add_argument("--focus", choices=sorted(split_focus_names()),
                   help="a focused pass after a first review: one reviewer hunts one kind of seam across the repo "
                        "(twins: two implementations of one behavior)")
    p.set_defaults(func=cmd_split)

    p = sub.add_parser("merge", help="turn reviewer output into registry entries")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--plan", help="a merge plan JSON file. Keys: absorb, distinct, drop, rename, extend, confirm")
    p.add_argument("--apply", action="store_true", help="write the proposal to seams.json if it passes the check")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("notes", help="write a note for each seam where agents read it")
    p.add_argument("--root", default=".")
    p.set_defaults(func=cmd_notes)

    p = sub.add_parser("apply", help="copy seams.proposed.json, hand edits and all, into seams.json")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--confirm", metavar="ID,ID",
                   help="mark these seams' drift as confirmed first: you checked that the copies differ as stated")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("verify", help="check whether seams' copies agree today, one agent per seam")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--registry", help="registry to read and update (default: <root>/seams.json)")
    p.add_argument("--risk", default="high,medium", help="risks to check, comma-separated (default: high,medium)")
    p.add_argument("--ids", help="check these seam ids only, comma-separated")
    p.add_argument("--all", action="store_true", help="check every seam, whatever its risk or drift")
    p.add_argument("--reading", action="store_true",
                   help="check seams in --risk whose drift was found only by reading: a second opinion")
    p.add_argument("--sample", type=int, help="check at most this many: higher risk first, random within a level")
    p.add_argument("--seed", type=int, default=0, help="seed for --sample, so a pick can be repeated")
    p.add_argument("--collect", action="store_true", help="write the checkers' results into the registry")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("rerate", help="a stronger model sets each recorded seam's risk again, one agent per packet")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--registry", help="registry to read and update (default: <root>/seams.json)")
    p.add_argument("--batch", type=int, default=30, help="seams per packet (default 30)")
    p.add_argument("--collect", action="store_true", help="write the raters' risks into the registry")
    p.set_defaults(func=cmd_rerate)

    p = sub.add_parser("mcp", help="run the registry lookups as an MCP server on stdio, for any agent")
    p.add_argument("--root", default=".")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("report-miss", help="record drift between copies that no seam listed, so seamreg can learn it")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--changed", action="append", required=True, metavar="FILE", help="a copy the change updated")
    p.add_argument("--missed", action="append", required=True, metavar="FILE", help="a copy the change left behind")
    p.add_argument("--rule", required=True, help="what the copies had to keep the same")
    p.add_argument("--summary", help="the shape in general words, with no names from the repo (default: the rule)")
    p.add_argument("--shape", default="unknown", help="a short tag that groups reports (siblings, packaging, ...)")
    p.add_argument("--kind", default="unknown", choices=list(checker.KINDS) + ["unknown"])
    p.add_argument("--found-by", default="drift-fix", choices=["drift-fix", "review", "open-pass", "benchmark", "other"])
    p.add_argument("--cause", metavar="SHA", help="the commit that changed one copy and missed the other")
    p.add_argument("--fix", metavar="SHA", help="the commit that fixed the drift")
    p.add_argument("--repo", metavar="URL", help="the public repo")
    p.add_argument("--public", action="store_true", help="the repo is public: keep paths, repo and commits")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_report_miss)

    p = sub.add_parser("catalog", help="rank the missed shapes no pass handles yet, from a library of miss reports")
    p.add_argument("folders", nargs="*", metavar="FOLDER", help="folders of reports (default: the library that ships with seamreg)")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("looked-at", help="list the files earlier reviewers opened, from Claude Code transcripts")
    p.add_argument("sources", nargs="+", metavar="TRANSCRIPTS", help="transcript files (.jsonl) or folders of them")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--prefix", action="append", metavar="PATH",
                   help="another absolute path the repo had in those sessions (a copy or a snapshot); repeatable")
    p.add_argument("--pass", dest="passes", action="append", metavar="KIND",
                   help="a pass those sessions ran (first, gap, focus:twins), when passes.json does not list it")
    p.set_defaults(func=cmd_looked_at)

    p = sub.add_parser("next", help="rank the candidate next passes, each with its reason and cost")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("triage", help="list the drift worth fixing first, confirmed drift first")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--registry", help="registry to read (default: <root>/seams.json)")
    p.add_argument("--top", type=int, default=10, help="how many to list (default 10)")
    p.set_defaults(func=cmd_triage)

    p = sub.add_parser("tie", help="draft a test that fails when a seam's copies disagree, one agent per seam")
    p.add_argument("ids", nargs="*", metavar="ID", help="seam ids to tie")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.add_argument("--registry", help="registry to read and update (default: <root>/seams.json)")
    p.add_argument("--untied", action="store_true", help="add every seam in --risk with no full tie")
    p.add_argument("--risk", default="high,medium", help="risks for --untied, comma-separated (default: high,medium)")
    p.add_argument("--collect", action="store_true", help="add the ties the agents proved to the registry")
    p.set_defaults(func=cmd_tie)

    p = sub.add_parser("baseline", help="record the last scan's leads as reviewed, so re-scans skip them")
    p.add_argument("--root", default=".")
    p.add_argument("--out", help="the scan's output folder (default: <root>/.seams-scan)")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("schema", help="print the registry JSON Schema")
    p.add_argument("--settings", action="store_true",
                   help="print the schema of seams.settings.json, the saved preset, instead")
    p.add_argument("--write", metavar="PATH", help="write it to PATH instead")
    p.set_defaults(func=cmd_schema)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
