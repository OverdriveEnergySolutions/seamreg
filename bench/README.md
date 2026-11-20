# Benchmark harness

This folder lets anyone benchmark seamreg on a repo of their choice, the same way we benchmark it, and
submit the result to be added to the published statistics in [docs/benchmarks.md](../docs/benchmarks.md).

**To run one,** point a Claude Code session at this file. For example:

> Read bench/README.md in the seamreg repo, and run a detection benchmark on https://github.com/owner/repo.

**To ask us to run one instead,** open an issue with the "Benchmark request" template. Say which repo and
why. We pick requests by how much they would teach us: a new stack, a new kind of repo, or a claim worth
testing.

## How it works

A benchmark is only worth adding if the tool could not see the answers. Every benchmark here has the same
shape:

1. **A snapshot.** Pick a public repo and an older commit. The tool runs on that commit, in a clone that
   holds no later history.
2. **Ground truth from the future.** The repo's later commits show what its maintainers fixed. That is the
   answer key, and nobody has to guess what counts.
3. **A blind session.** seamreg runs in a fresh headless Claude Code session, with your own settings,
   skills, plugins, hooks and MCP servers turned off, and a frozen copy of the tool.
4. **A blindness scan.** A script reads every transcript of the blind session, its subagents included,
   and lists each touch of a forbidden place and each possible network call.
5. **Grading** against the key, in a separate session.
6. **One result file** in a format shared by every kind of benchmark.

The parts are separate so new kinds of benchmark can reuse them:

| Part | What it does | Who uses it |
|---|---|---|
| [`snapshot.sh`](snapshot.sh) | Makes a workspace: a full clone, a blind clone at the snapshot, and `bench.json` | Every kind |
| [`session.sh`](session.sh) | Runs one prompt blind in the workspace, and records the model, effort and cost. `RESUME=1` continues a session that stopped early | Every kind that runs seamreg |
| [`blindscan.py`](blindscan.py) | Checks one blind session's transcripts | Every blind session |
| [`result.py`](result.py) | Writes `result.json`: a common envelope plus the kind's own `measures` | Every kind |
| [`table.py`](table.py) | Prints the statistics from `results/`, one table per kind | Maintainers |
| [`kinds/`](kinds/) | One folder per kind of benchmark: its question, its prompts, its briefs | See [kinds/README.md](kinds/README.md) |

## Before you start

- Claude Code, logged in. A subscription works. Every cost the scripts record is the API-equivalent
  figure Claude Code reports, which on a subscription is a measure of usage, not a charge.
- `git`, `python3` (3.9 or later) and [`uv`](https://docs.astral.sh/uv/).
- A clone of this repo. The blind session uses a frozen copy of its HEAD commit.
- Disk space for two clones of the target repo. Put the workspace on a real disk, outside your home
  folder: `/tmp` is a small RAM disk on some systems, and a workspace in your home folder can load your
  own `CLAUDE.md` files into the blind session.
- Time and usage. A detection benchmark is three sessions. The blind run is the large one: it is a full
  first review ([docs/passes.md](../docs/passes.md) lists what reviews cost).

## Safety

A benchmark runs agents on someone else's code, with permission to run commands. Treat the target repo as
untrusted.

- The blind session loads no settings files, neither yours nor the repo's own `.claude/settings*.json`,
  whose hooks could otherwise run commands on your machine. It loads no MCP servers. The repo's
  `CLAUDE.md` files still load as text, as they would for any agent working there.
- The key and grading sessions read the full repo as well. Text in a repo can try to steer an agent.
- For a repo you do not trust, run the whole benchmark in a container or a virtual machine that holds no
  credentials except your Claude Code login.

## Steps for a session that runs a benchmark

Follow these in order. Stop and tell the user if any step fails.

1. **Pick the kind.** Read [kinds/README.md](kinds/README.md). Use `detection` unless the user asks for
   another kind.
2. **Pick the repo and the snapshot** with the user, by the kind's rules, before anyone looks at the
   repo's seams. Write down why you picked them.
3. **Make the workspace.** Set `SEAMREG` to the folder of your seamreg clone, and `WORK` to a new
   folder on a real disk outside your home folder. Then:
   ```sh
   "$SEAMREG/bench/snapshot.sh" <repo url> <snapshot commit> "$WORK"
   ```
4. **Follow the kind's README** from here. For `detection`: build the key, run blind, scan, grade.
5. **Check the blindness scan.** Read every hit. A hit can be harmless (a path named in a reply), but a
   read of the key, the full clone or the miss library makes the run invalid. Say which it is.
6. **Assemble the result:**
   ```sh
   python3 "$SEAMREG/bench/result.py" "$WORK" <session name> <kind>
   ```
7. **Submit,** if the user wants to (see below).

You run steps 1 to 7 from an ordinary session. Only the blind run must be a fresh session, and
`session.sh` starts it for you. Never paste anything from the key, the full clone or a grading into the
blind session.

## Submitting a result

Open a pull request that adds one folder, `bench/results/<repo>-<snapshot first 10>-<kind>/`, holding:

| File | Required |
|---|---|
| `result.json` | Yes |
| `blindscan.txt` | Yes |
| The kind's key and grading files (for detection: `key.md`, `grading.md`) | Yes |
| The session's `summary.json` and the run's `feedback.md` | Yes |
| Anything else the kind's README lists | As listed |

Leave out the run's own registry and reviewer output. A run records bugs that may still be open in
someone else's project, and some may touch security. Keep them, and send them to a maintainer if asked.
Report anything about security that is still open to that project's own security contact.

In the pull request, say: the repo and why you picked it, the model and effort, the cost, every
blindness scan hit and what it was, and anything that went wrong.

**What we check before we add it:**
- The snapshot and every fix commit in the key exist upstream, and no fix is an ancestor of the snapshot.
- The blindness scan is clean, or each hit is explained and harmless.
- A sample of the key's drift rows and of the grading holds when we read the code.
- The tool commit is one we published.

A result we cannot reproduce from the files goes back to its author with questions. A result that does
not favor seamreg is just as welcome: the statistics are only useful if they include the misses.
