# Contributing

seamreg gets better from evidence: drift it missed, warnings that were wrong, shapes of seams it cannot
find yet, and repos it has never seen. Most of what changed in 0.2 came from studying misses on public
repos. We want that loop to run on your repos too.

You do not need to write code to help. The most useful contributions take a few minutes.

## 1. Report a miss

A miss is drift between two files that seamreg did not warn you about: you or an agent changed one copy,
another copy had to change too, and no seam in `seams.json` listed it. Each miss teaches the tool a shape.

When you fix one, run:

```sh
seams report-miss --changed <the file you changed> --missed <the file that also had to change> \
  --rule "<what the two had to keep the same>" --summary "<the same, in general words>"
```

It prints a short report. Open an issue on this repo and paste it. Add `--public` for a public repo, with
`--cause <commit>` and `--fix <commit>` if you know them: then we can replay the miss and test a fix
against it.

**For a private repo, leave out `--public`.** The printed report then holds only the shape: the rule in
your general words, the file types, and what the registry held. No path, commit, repo name or code. Read
it before you paste it. The full report stays on your machine in `.seams-scan/misses/`.

The agent instructions `seams init` writes already ask agents to run `seams report-miss` when they find
an unlisted copy, so check your agent's replies for a report to share.

## 2. Report noise

A warning about a seam that is not real costs your agents attention and makes them trust the registry
less. Tell us when:

- a seam in `seams.json` is not one piece of knowledge (look-alike code, or a shared name only),
- the edit hook or the Stop hook named a copy that did not need to change,
- a pass recorded drift that is not there.

Open an issue with the entry from `seams.json` and one sentence on why it is wrong. For a private repo,
describe the shape instead of pasting the entry.

## 3. Close an open question

[docs/benchmarks.md](docs/benchmarks.md) ends with what we have not measured. Each item is a place to
help. The ones we most want answered:

- **A repo the tool has never seen.** The newest lead kinds and the lead check's list of precise kinds
  were tuned on the benchmark repos. A run on a fresh repo with known later fixes is the real test.
- **Other stacks.** Nine repos so far, mostly web apps. Nothing yet on mobile, embedded, data pipelines,
  or monorepos over 5,000 files.
- **Other agents.** The Cursor, Copilot and `AGENTS.md` notes follow those tools' documentation but are
  untested in them. The MCP server is untested in Codex, Cursor and Copilot.
- **Other models.** Nothing on Haiku beyond one registry lookup. Sonnet reviews on only two repos.
- **Everyday frequency.** How often real changes leave a copy behind, in your repo, over a month.

If you run one of these, open an issue with what you ran, the model and effort, the cost Claude Code
reported, and what you found.

## 4. Propose a new kind of lead or seam

`seams catalog` ranks the shapes of reported misses that no pass handles yet. The top of that list is the
next thing worth building. A proposal is strongest with:

1. **The shape**, in general words, with two or three real examples from public repos.
2. **A mechanical lead**: what in the code points at it, without an agent.
3. **An offline measure** against misses it was not designed from. Our check: of the real commits that
   missed a copy, how many does the new lead link (a changed file and its missed copy in one lead)? Then
   the same for the same number of random file pairs. A lead that beats random pairs by a wide margin is
   worth a paid test.

We measured the leads in 0.2 this way, though on the repos they were tuned on. The flow and key-writer
leads linked 9 of 32 past misses each, and random pairs linked none. Their rate on a new repo is open.

## 5. Run a benchmark

Point a Claude Code session at [bench/README.md](bench/README.md) and name a public repo. The harness makes
a blind snapshot, builds an answer key from the repo's later fixes, runs seamreg blind, checks the
transcripts for leaks, grades the run and writes one result file. Open a pull request with the result, and
after review it joins the published statistics. A result that does not favor seamreg is as welcome as one
that does.

**A new or changed preset** needs the same proof as a pass. A cheaper preset joins only when a
configuration of it passes the prevention replay test against two baselines, no registry and a reviewed
one. A changed rate in `src/seams/presets.py` names the runs it came from in
[docs/presets.md](docs/presets.md). If a run's actual cost lands more than 30% from its estimate, report it
with the run's `seams spend --json`.

If you find a new question worth measuring, add a kind of benchmark: [bench/kinds/README.md](bench/kinds/README.md)
says how. To ask us to run a benchmark instead, open an issue with the **Benchmark request** template.

## 6. Code

```sh
git clone https://github.com/OverdriveEnergySolutions/seamreg && cd seamreg
uv run pytest -q          # or: pip install pytest && PYTHONPATH=src python3 -m pytest -q
```

Some rules the code keeps:

- **The checker stays standard-library only.** `src/seams/check.py` is copied into users' repos and runs
  in their CI with no install. No dependencies, Python 3.9 or later.
- **No benchmark answers in text a reviewer reads.** The skills, agents and briefs never name a benchmark
  repo or its known drifts, and never point at `src/seams/catalog/`. A test checks this. A blind run is
  only blind if the tool does not hand it the answers.
- **Measure before you claim.** A change to a brief, a lead or a pass comes with a measured result: which
  repos, which model and effort, how many runs, and what it cost. Say when a change was designed from the
  repo it was measured on.
- **Plain writing.** Skills, briefs and docs use short sentences in plain English, because agents and
  people whose first language is not English read them. No em or en dashes.

Open a pull request against `main`. Keep it to one change, and say in its description what you measured.

## Security

If seamreg itself has a security problem, or a run of it showed you a security hole in someone else's
project, do not open a public issue. Use this repo's private vulnerability reporting (the Security tab),
or the other project's own security policy.

## License

By contributing, you agree that your contribution is licensed under the MIT license in
[LICENSE](LICENSE).
