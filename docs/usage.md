# Using seamreg

The [README](../README.md) covers install and the short version. This page is the full guide: setting up
a repo by hand, what the checker proves, how the registry reaches your agents at each step of a change,
re-scans, and agents other than Claude Code. [concepts.md](concepts.md) defines every term.

## Set up a repo by hand

Install the `seams` command (see the [README](../README.md#install)), or from a clone with `pipx install .` or `uv tool install .`.

The package is named `seamreg`, because `seams` on PyPI is an unrelated project. The command it installs is `seams`.

In your repo:

```sh
seams init            # writes scripts/seams_check.py and an empty seams.json
seams scan            # writes candidate seams to .seams-scan/leads.md
seams check           # fails when seams.json no longer matches the repo
```

`seams init` copies the checker into your repo, so CI needs no install and no network. It is one file that uses only the Python standard library. It prints the setup snippets: a CI workflow, a Claude Code hook, a commit check, and two items for after the first review. For the commit check, it says which form fits your repo, or that your repo has no commit-hook setup that git tracks. They also live in [`src/seams/snippets/`](../src/seams/snippets/).

When a new release changes the checker, run `seams init --upgrade`. `seams check` warns when your copy is a different version.

## A registry entry

```json
{
  "id": "order-status-names",
  "title": "Order status names",
  "kind": "vocabulary",
  "must_agree": "The API and the web app list the same status names.",
  "copies": [
    {"path": "api/orders/status.py", "symbol": "STATUSES"},
    {"path": "web/src/orders/status.ts", "symbol": "STATUSES"}
  ],
  "consequence": "The web app filters on a status the API never sends.",
  "ties": [
    {"path": "tests/test_status_parity.py", "test": "test_status_names_match", "covers": "all"}
  ],
  "risk": "medium"
}
```

The full format is [`schema/seams.schema.json`](../schema/seams.schema.json).

## What the check proves, and what it does not

`seams check` fails when:

- an entry does not match the schema, or two entries share an id,
- a path is absolute, leaves the repo, or matches no file,
- a listed `symbol` or tie `test` name no longer appears in its file.

A pass proves that every listed copy still exists. **It cannot find a copy that nobody listed.** A passing check never means the registry is complete.

## Catch drift while it happens

The checker also answers a second question: which seams does this change touch, and which of their copies did it leave alone?

```sh
python3 scripts/seams_check.py --changed api/orders/status.py   # these files
python3 scripts/seams_check.py --staged                         # this commit
python3 scripts/seams_check.py --diff origin/main --fail-untied # this branch
```

```
seam 'order-status-names' (risk medium): Order status names
  must agree: The API and the web app list the same status names.
  changed: api/orders/status.py
  not changed: web/src/orders/status.ts
  tie: tests/test_status_parity.py (test_status_names_match), covers all
```

This lookup reads only `seams.json` and the list of changed files, so it is fast enough to run on every edit. Use it in three places. [`src/seams/snippets/`](../src/seams/snippets/) has each snippet.

- **Claude Code hooks.** Before the agent edits one copy, it hears about the others, so it can change all of them in the same edit. The hook also reads Bash commands, because an agent in auto mode often edits with `sed` or a heredoc and never calls Edit or Read. When the agent tries to finish, a Stop hook stops it once: it names any copy left behind, and asks the agent to add any unlisted copy it found to `seams.json`, even one it left alone. It counts the branch's commits too, so it still works when the agent commits before it finishes. ([`claude-code-settings.json`](../src/seams/snippets/claude-code-settings.json))
- **A commit check**, for edits made without an agent: a pre-commit framework hook ([`pre-commit.yaml`](../src/seams/snippets/pre-commit.yaml)) or lines for a plain git hook ([`git-hook.sh`](../src/seams/snippets/git-hook.sh)).
- **CI on a pull request.** It posts one comment on the pull request: each seam the change touches, the copies it changed, the copies it did not change, the risk and the tie. Each push edits that comment, and a push that leaves no copy behind clears it. It warns at first. Add `--fail-untied` once most seams have a full tie: then the build fails only when a change leaves a copy behind and no test covers the seam. ([`github-actions.yml`](../src/seams/snippets/github-actions.yml))

  A pull request from a fork gets a read-only token, so this workflow puts the report in the job summary there. A repo that takes fork pull requests uses two files instead: [`github-actions-forks.yml`](../src/seams/snippets/github-actions-forks.yml) runs the check with the read-only token and saves the report, and [`github-actions-forks-comment.yml`](../src/seams/snippets/github-actions-forks-comment.yml) posts it. The second file runs only code from the default branch and never checks out the pull request.

### Any agent: the MCP server

`python3 scripts/seams_check.py --mcp` (or `seams mcp`) answers the same lookups over the Model Context Protocol, so an agent with no hook can ask the registry itself. It has five read-only tools. `seams_for_files` names the seams some files hold a copy of, and their other copies. `seams_about` finds the seams on a topic. `seams_changed` finds the copies the current changes left alone, or the ones since a base branch. `seams_get` returns one entry. `seams_check` says whether the registry still matches the repo. It reads `seams.json` again on every call and writes nothing.

For Claude Code, commit [`mcp.json`](../src/seams/snippets/mcp.json) as `.mcp.json`. It starts the server from the repo root, so it works from a subfolder too (it needs `sh` and `git`). For Codex: `codex mcp add seams -- sh -c 'cd "$(git rev-parse --show-toplevel)" && exec python3 scripts/seams_check.py --mcp'`. Other agents take the same command in their own MCP config file. Tested in Claude Code: from the repo root, from a subfolder, and with a plain relative path, which fails from a subfolder. Not yet tested in Codex, Cursor or Copilot.

## Make it part of how your agents work

A scan you run once goes stale. The value comes from wiring the registry into every change, so each agent session starts from what the last one learned.

The most important place is **planning**. An agent that plans a change finds its files with search. Search shows where the code is. It cannot show which other file must change too, because the agent does not know to look for it. The registry answers that question. So a planning agent finds its files, asks the registry, and only then commits to a plan:

```sh
python3 scripts/seams_check.py --about "order status"            # before you know the files
python3 scripts/seams_check.py --changed api/orders/status.py    # once you do
```

Paste [the planning text](../src/seams/snippets/agent-instructions.md) into your `CLAUDE.md` or `AGENTS.md`, and every planning agent follows that order. `seams init` prints it too.

Notes make the same step automatic. Set `"notes"` in `seams.json` and run `seams notes`. It writes a note for each seam where your agents read instructions:

| `"notes"` | What it writes | Who reads it |
|---|---|---|
| `"rules"` | `.claude/rules/seams/<id>.md`, one per seam | Claude Code, the moment an agent reads one of the seam's copies |
| `"cursor"` | `.cursor/rules/seams/<id>.mdc`, one per seam | Cursor, when one of the copies is in context |
| `"copilot"` | `.github/instructions/seams-<id>.instructions.md`, one per seam | GitHub Copilot, for work on one of the copies |
| `"claude-md"`, `"agents-md"` | A block in the nearest `CLAUDE.md` or `AGENTS.md`, one line per seam, high and medium risk only | Claude Code; Codex, Cursor, Copilot and other agents that read `AGENTS.md` |
| `"claude-md-high"`, `"agents-md-high"` | The same block, high risk only | The same |

For a repo that more than one kind of agent works in, give a list: `"notes": ["rules", "cursor", "copilot"]`.

The per-seam files are the better choice where the agent supports them. A note costs nothing until one of its copies is opened, and every risk level gets one. Blocks load widely, so on a large registry they add up: one real registry of 238 seams added half again to its CLAUDE.md files.

Some things to know:

- **Rules need `.claude/rules/` in git.** If your repo ignores `.claude/`, `seams notes` prints four lines to put in `.gitignore` instead. They keep the rules and the hook file in git and ignore the rest of `.claude/`.
- **Codex reads fewer `AGENTS.md` files than the others.** Its docs say it reads the files on the path from the repo root to the folder it starts in. A block in `api/AGENTS.md` reaches Codex only when it starts in `api/`. Cursor and Copilot read the `AGENTS.md` nearest to the file.
- **Cursor and Copilot take one comma-separated list of paths.** A copy whose path holds a comma is left out of those notes, with a warning.
- **Tested so far in Claude Code only.** The Cursor, Copilot and `AGENTS.md` notes follow each tool's documentation, read on 2026-11-15.

Saved presets live in their own file, `seams.settings.json`, not in `seams.json`, so an older checker copy in CI never sees them. [presets.md](presets.md#saving-a-preset) explains it.

When the notes fall behind `seams.json`, the plain check fails in CI. When you drop a value from `"notes"`, `seams notes` removes its notes. It never touches a file it did not write.

The full loop:

| When | What runs | Set up with | Status |
|---|---|---|---|
| Planning a change | `--about` and `--changed` on the planned files | [The planning text](../src/seams/snippets/agent-instructions.md) | Built |
| Reading a file | A note about its seams loads with the file | `"notes"` in `seams.json`, then `seams notes` | Built. Tested in Claude Code. Cursor, Copilot and `AGENTS.md` notes follow their docs |
| Editing a copy | A hook names the other copies before an edit or a Bash command that names a copy; a Stop hook catches a copy left behind | [The hooks](../src/seams/snippets/claude-code-settings.json) | Built. Tested in Claude Code: in benchmark runs the Stop hook fired in 100 of 102 sessions |
| Committing | `--staged` | [pre-commit](../src/seams/snippets/pre-commit.yaml) or [a git hook](../src/seams/snippets/git-hook.sh) | Built |
| Pull request | The registry check, then `--diff` as one comment on the pull request (warn, then `--fail-untied` once tied) | [The CI job](../src/seams/snippets/github-actions.yml) | Built. The comment scripts are tested against a stand-in for `gh`, not yet on GitHub |
| Drift no seam listed | `seams report-miss` records the miss; shared, it teaches seamreg the shape (a private repo shares the shape only) | The rule in `agent-instructions.md` and the `seams` skill | Built. `seams catalog` ranks the missed shapes no pass handles yet |
| Fixing drift | The fix updates every copy and records the seam. A tie is a follow-up | The rule in `agent-instructions.md`. `seams tie <id>` drafts the tie | Built. The rule is not a check. `seams tie` was tried on two seams of one public Go and TypeScript repo: two ties added, $0.80 and $1.03 each |
| Before a pull request | `seams scan --since main --new`: leads this branch may have created | The CLAUDE.md text `seams init` writes, the Stop hook's reminder, the skill, or by hand | Built |
| Any agent, any time | The MCP server answers the lookups: `seams_for_files`, `seams_about`, `seams_changed` | [`mcp.json`](../src/seams/snippets/mcp.json), or the agent's own MCP config | Built. Tested in Claude Code |
| Weekly or monthly | A re-scan that reviews only new leads | See below | Built. Its cost at scale is not measured yet. |

"Fresh" means two things here:

- **The registry is still true.** The CI check runs on every push, so a listed copy cannot vanish or get renamed without a failed build.
- **The registry still covers the repo.** New seams appear as people copy code. The edit hook and the drift rule catch some of them. A re-scan catches more.

### Re-scan only what is new

A full review is expensive, and most of what it reads is noise it already rejected. So the tool remembers which leads a review saw, kept or rejected, in `seams.baseline.json`. Commit that file next to `seams.json`. A lead's fingerprint is its kind and its files, without line numbers, so ordinary edits do not make old leads look new.

```sh
seams scan --new                 # leads.md shows only new leads
seams split --new-only           # packets hold only new leads; reviewers check leads, not whole areas
# run the seam-reviewer agents, then:
seams merge --apply              # writes seams.json and adds this scan's leads to the baseline
```

A lead is new when no seam in `seams.json` covers it and no past review saw it. The merge never changes an existing entry by itself. When a reviewer finds a new copy of a seam you already have, the report names it, and `"extend"` in a merge plan adds it.

If you reviewed a repo before you had a baseline, run `seams scan` and then `seams baseline` once to record that review.

Measured on a busy 2,200-file repo: after three weeks (1,586 commits, 1,386 files changed), 1,447 of 4,545 leads were new. That is about a third of a full review's reading. `--cross-area-only` cut it to 651. On a branch, `--since` cuts it to the leads that touch changed files.

## Use it with your agent

Two skills come with the tool. [`seams`](../skills/seams/SKILL.md) is for everyday changes: the lookups before and after a change, fixing drift with a tie, and the rules for entries. Agents can start it on their own whenever a repo has `seams.json`. [`seams-review`](../skills/seams-review/SKILL.md) runs the full review that builds a registry. It costs real money, so ask for it by name: it shows the cost and waits for a yes before it starts any agent. [passes.md](passes.md) lists each pass, what it cost on public repos with the model and effort it ran at, and which steps can run side by side. Install the CLI first (see [Set up a repo by hand](#set-up-a-repo-by-hand)). The skill runs it.

In Claude Code, install this repo as a plugin. You get both skills and the two reviewer agents:

```
/plugin marketplace add OverdriveEnergySolutions/seamreg
/plugin install seams@seamreg
```

Other agents (Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode and others) read skills in the [Agent Skills](https://agentskills.io) format, which both skills follow. Copy the folders from a clone:

```sh
cp -r skills/seams skills/seams-review ~/.agents/skills/   # for every repo on this machine
cp -r skills/seams skills/seams-review .agents/skills/     # or for one project, committed with it
```

Check where your agent looks for skills. `~/.agents/skills` and `.agents/skills` are the common folders, but each agent picks its own. Outside Claude Code there are no `seam-reviewer` agents, so `seams-review` tells the agent to start an ordinary sub-agent for each packet instead.

## What the scan reads

The scan reads the repo once, with no agent and no network. It reads code, config, JSON and Markdown docs. It looks for sync comments, copied code, a named date format with a file beside its users that writes dates another way, the same list of names in two files (code, JSON or docs, including a doc list split under several headings), shared constants, function and env var names, and tests that may already tie copies. It also reads the git history for files in different folders that keep changing in the same commits, which points at seams that share no text: a doc that describes a script, a payload built in one service and read in another. It skips its own files: the registry, the notes and the copied checker. `plan.md` names every file it left unread, and why.
