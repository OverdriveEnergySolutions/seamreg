# Concepts

seamreg uses a small set of words with exact meanings. This page defines each one, in the order you meet
them. The [README](../README.md) gives the short version.

## The basic idea

### Seam
One piece of knowledge kept in two or more files that must agree. If one copy changes and the others do
not, something breaks, often with no error.

Examples:
- A list of order status names in the API and the same list in the web app.
- A payload a server builds and the client code that reads its fields.
- A helper function copied into two services, so a fix to one must reach the other.
- A README line that says what a command does, and the command itself.

Code maps and call graphs do not show seams. Two copies of a list do not import each other, so no edge
links them. Search does not find them either, because you do not know the second copy exists.

This is not the seam of Michael Feathers' *Working Effectively with Legacy Code*, which is a place where
you can change behavior without editing the code there. Here a seam is a place where knowledge is split
across files.

### Copy
One of the places a seam's knowledge lives: a file, and optionally a symbol in it (a constant, a
function, a section name). A seam has two or more copies, or one copy plus a single source.

### Drift
The copies of a seam disagree. Drift is the bug seamreg exists to stop: one copy changed and another did
not. The registry can record drift that already exists, with the file and line on each side.

- **Drift found by reading:** an agent read the copies and says they differ. Treat it as a claim.
- **Confirmed drift:** a person read both sides and agreed (`seams apply --confirm <id>`). Confirmed means
  "the copies differ as stated", not "this is a bug". That needs a runtime check or the owner's word.

### Registry (`seams.json`)
The list of a repo's seams, committed with the code. Each entry says what must agree, where the copies
are, how bad drift would be, and what checks it. The full format is
[`schema/seams.schema.json`](../schema/seams.schema.json).

A registry entry has these fields:

| Field | Meaning |
|---|---|
| `id`, `title` | A short name for the knowledge, not for the files. |
| `kind` | What sort of knowledge it is (below). |
| `must_agree` | One sentence: what the copies must agree on. |
| `copies` | The files, each with an optional `symbol` the checker looks for. A glob such as `app/*/search.py` covers a family of files. |
| `consequence` | What goes wrong when the copies drift. |
| `risk` | `high`: silent wrong results, data loss, a security gap. `medium`: a visible bug. `low`: cosmetic, or caught fast. |
| `ties` | The tests that fail when the copies drift (below). |
| `drift` | Drift that exists today, if any, with its source and date. |
| `intentional_differences` | Differences that are on purpose, so nobody "fixes" them. |
| `single_source` | True when most of the knowledge lives in one module, and the copies listed are the ones left outside it. |

### Seam kinds
- **vocabulary:** a list of names kept in several places (statuses, roles, event names, column lists).
- **contract:** one side builds a payload or response, another side reads it.
- **schema:** a data shape kept in two places (a database table and the code that maps it).
- **config:** settings that must match across files (env var names, ports, paths, queue names).
- **mirror:** the same logic written twice, often in two languages or for two backends.
- **copied-helper:** a helper copied into several places, so a fix must reach every copy.
- **convention:** a rule every member of a family follows, such as "every API handler checks the
  caller's role". The copies are a glob for the family plus the file that states the rule. A member that
  breaks the rule is drift.

### Tie
An automated check that fails when a seam's copies drift: usually a test that loads both copies and
compares them. A tie **covers all** copies or only **some** (partial). A tie that CI never runs is not a
tie. `seams tie <id>` drafts one, and proves it by breaking each copy in turn and seeing the test fail.

### The three rungs
For each seam, pick the cheapest rung that holds:

| Rung | What it is | When |
|---|---|---|
| Note | The registry records the seam, so agents see it before they edit | Low risk, rarely changes |
| Tie | A test fails when the copies differ | The copies must stay separate |
| Single source | One shared module that every side imports | You can afford the refactor |

## Keeping copies in step

### Checker (`scripts/seams_check.py`)
One file, Python standard library only, that `seams init` copies into your repo. It does two jobs.

1. **The plain check** (`seams check` in CI) fails when the registry no longer matches the code: a copy's
   file or symbol is gone, a tie's test was renamed, an entry breaks the schema, or the notes are stale.
   A pass proves every listed copy still exists. It cannot find a copy nobody listed.
2. **The change lookup** answers "which seams does this change touch, and which of their copies did it
   leave alone?" (`--changed <files>`, `--staged`, `--diff <branch>`, `--about "<topic>"`).

### Notes
A short text per seam, written where your agent reads instructions, so the agent sees a seam the moment
it opens one of the copies. `seams notes` writes them from the registry: Claude Code rules, Cursor rules,
Copilot instructions, or a block in `CLAUDE.md` or `AGENTS.md`. Notes are generated, so they never drift
from the registry: the plain check fails when they fall behind.

### Hooks
Claude Code runs these automatically:
- **The edit hook** runs before an edit or a shell command that touches a copy, and names the other
  copies, so the agent can change them in the same edit.
- **The Stop hook** runs when the agent tries to finish. It stops the agent once, never twice in a row,
  and names any copy the change left behind. It asks the agent to record any copy it found that no seam lists, and reminds it to run the
  pre-PR scan. It counts the branch's commits too, so it still works when the agent commits first.

### Planning text
A paragraph `seams init` writes into `CLAUDE.md` or `AGENTS.md`. It tells planning agents to ask the
registry before they commit to a plan, to update every stale copy, to record a copy they find even if
they leave it alone, and to run the pre-PR scan.

### Pre-PR scan
`seams scan --since <base branch> --new`: a scan of only the leads this branch may have created. An agent
runs it before a pull request and adds the real seams to the registry.

### Miss report
`seams report-miss`: a record of drift that no seam listed. Shared with the seamreg project, it teaches
the tool the shape of what it missed. For a private repo, the shared text holds the shape only: no path,
no commit, no code. `seams catalog` ranks the missed shapes no pass handles yet.

### MCP server
`seams mcp` answers the same lookups over the Model Context Protocol, for an agent that has no hooks.

## Building a registry

A registry starts empty. The tool fills it in stages: a mechanical scan, agents that review what the
scan points at, and a merge that turns their findings into entries.

### Scan and leads
`seams scan` reads the repo once, with no agent and no network, and writes **leads**: hints that a seam
may exist. Most leads are noise, so an agent judges each one. The kinds of lead:

| Lead | What it points at |
|---|---|
| marker | A comment that says two places must agree |
| literal-set | The same list of names in two files |
| dupblock | Code copied between files |
| twin | Two implementations of one behavior: alike patterns, files in two languages, one copy per backend |
| same-name, same-constant, env-name, same-file | The same function, constant, env var or file name in two or more areas |
| shared-ids | Code or config in two folders that uses the same rare names (fields, columns, settings) |
| flow | A rare key one file writes and another file reads |
| key-writers | Every file that writes the same key, which must all build the same shape |
| access | Two files that decide who may do what, with the same rare names |
| convention | A pattern most members of a family follow, and the members that break it |
| sibling | Classes that share a base, and a counterpart of one that lacks a field the others carry |
| packaging | What the build ships against the code: pinned versions, runtime files |
| date-format | A named date format, and code beside its users that writes dates another way |
| co-change | Files in different folders that keep changing in the same commits |
| tie-candidate | Tests that may already tie copies |

### Area and packet
An **area** is a top-level part of the repo, such as a service or an app folder. `seams split` groups
areas into **packets**, one per reviewer agent, packed to a line budget. A packet never cuts a file. Each
packet lists its areas and up to 400 leads.

### Pass
One round of agents over the repo. Each pass adds to the registry:

| Pass | Command | What it does |
|---|---|---|
| First review | `seams split` | One reviewer per packet sweeps its areas, with the leads as hints. |
| Lead check | `seams split --lead-check` | A cheap agent judges every strong lead no recorded seam covers, 25 at a time, and records the seams whose copies differ or share a mistake. `--keep-agreeing` also records agreeing seams from the lead kinds where those proved real. |
| Gap pass | `seams split --gap` | The same sweep as a first review, told what the registry has, hunting for the rest. |
| Focused pass | `seams split --focus <kind>` | One reviewer hunts one kind of seam across the repo (`twins`, `siblings`, `packaging`, `open`). |
| Drift check | `seams verify` | One small agent per seam checks whether its copies agree today. |
| Risk re-rating | `seams rerate` | A stronger model sets each seam's risk again, after a review run on a cheaper one. |
| Tie | `seams tie <id>` | One agent writes a test that fails when a seam's copies disagree. |

`seams next` ranks the passes worth running next. [passes.md](passes.md) lists what each cost.

### Merge, plan and apply
`seams merge` turns the agents' findings into a proposed registry, `.seams-scan/seams.proposed.json`, and a
report of everything to settle: possible duplicates, dropped copies, drift to confirm. A **plan** file
settles them (`absorb` one entry into another, keep two `distinct`, `extend` an existing seam, `confirm`
drift). `seams merge --plan <file> --apply`, or `seams apply` after hand edits, writes `seams.json`.
Neither changes an existing entry on its own.

### Baseline
`seams.baseline.json`: the leads a past review already saw. A re-scan treats them as old, so a later review
reads only what is new.

### Answer key (benchmarks only)
For a benchmark, a list of the seams a repo's own structure implies and the drifts its maintainers fixed
after a snapshot. The tool runs blind on the snapshot, and its findings are scored against the key. See
[benchmarks.md](benchmarks.md).
