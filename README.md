<img src=".claude-plugin/icon.png" alt="" width="96" align="right">

# seamreg

seamreg keeps a list of the places in your code that must change together, and makes sure your coding
agents know about them before they edit.

Every codebase has knowledge kept in more than one file: a list of status names in the API and again in
the web app, a payload one service builds and another reads, a helper copied into two places. We call
each of these a **seam**. When one copy changes and the others do not, something breaks, usually with no
error. Coding agents make this worse. Each session copies what it needs, and a later session changes
only one copy.

Search and code maps cannot find these. The copies do not import each other, and you cannot search for a
file you do not know exists. seamreg finds them, records them in a registry, and puts that knowledge in
front of the agent at every step of a change.

## What it does

1. **Finds the seams.** A scan reads your repo and points at likely seams. Reviewer agents judge what the
   scan found and record the real ones in `seams.json`.
2. **Warns at the moment of an edit.** When an agent opens or edits one copy, it is told where the others
   are. Before it finishes, it is reminded of any copy it left behind.
3. **Checks in CI.** A one-file checker fails the build when the registry no longer matches the code, and
   comments on a pull request that changes one copy but not another.
4. **Learns.** Agents record new copies as they find them, and report drift the registry missed so the
   tool can learn its shape.

## Does it work?

In our tests, agents kept every copy in step **1.5 to 2.2 times as often** when the registry held
the seam. We replayed real commits from public projects in which a developer changed one copy and
missed another, and gave the same task to agents with and without seamreg.

On 7 tasks whose seam the registry held, Sonnet, Opus and Fable all ended up level with seamreg, in 20
or 21 of 21 runs. Without it they managed 7 to 14. The weaker a model did alone, the more seamreg added,
so **Sonnet with seamreg matched Opus and Fable** there, at about a third of Opus's cost per task.

Finding the seams is the harder half. On our three newest benchmarks, a first review recorded a third
to a half of the seams a careful answer key lists. More passes usually find more, but not on every repo.
We publish what we measured, including what did not work and what we have not tested, in
[docs/benchmarks.md](docs/benchmarks.md).

## Install

In Claude Code, add the plugin. It brings the skills, the reviewer agents and the hooks:

```
/plugin marketplace add OverdriveEnergySolutions/seamreg
/plugin install seams@seamreg
```

Then install the `seams` command, which the skills run (Python 3.9 or later, no dependencies):

```sh
uv tool install git+https://github.com/OverdriveEnergySolutions/seamreg
# or: pipx install git+https://github.com/OverdriveEnergySolutions/seamreg
```

In your repo, ask Claude to **"find this repo's seams"**. It tells you what the review will cost and
waits for your yes before it starts. When it finishes, it sets up the hooks, the notes and the CI check.

Other agents (Codex, Cursor, Copilot and others) can use the skills, the checker and the MCP server,
though we have tested them only in Claude Code. See
[docs/usage.md](docs/usage.md#use-it-with-your-agent).

## What it costs

A first review of a mid-sized repo is roughly the size of an hour or two of heavy agent work: $40 to $115
in API-equivalent terms on the repos we tried, and about 40% less on Sonnet. On a Claude subscription you
are not charged that amount: it counts against your plan's usage. Afterwards, the checker and the lookups
cost nothing, and an agent working with the registry costs about twice as much per task, because it
reads the warnings. [docs/passes.md](docs/passes.md) has the measured figures for every step.

Without a review, a cheaper lead check builds a registry for about a quarter of the price, and gets
about half the benefit.

## The words

| Term | Meaning |
|---|---|
| **Seam** | One piece of knowledge kept in two or more files that must agree |
| **Copy** | One of the places a seam lives |
| **Drift** | The copies disagree: one changed and another did not |
| **Registry** | `seams.json`, the list of a repo's seams, committed with the code |
| **Tie** | A test that fails when a seam's copies drift |
| **Lead** | A hint from the scan that a seam may exist, for an agent to judge |
| **Pass** | One round of agents that adds seams to the registry |
| **Notes** | Short per-seam texts placed where your agent reads instructions |

[docs/concepts.md](docs/concepts.md) defines every term in full.

## Learn more

- [docs/concepts.md](docs/concepts.md): what each term means, with examples.
- [docs/usage.md](docs/usage.md): setting up by hand, the checker, hooks, notes, CI, re-scans and other
  agents.
- [docs/passes.md](docs/passes.md): every pass, what it does and what it cost.
- [docs/benchmarks.md](docs/benchmarks.md): every measurement, its method and its limits.

## Help it learn

seamreg improves from evidence: drift it missed, warnings that were wrong, and repos it has never seen.
When it misses a copy, `seams report-miss` writes a short report you can share, and for a private repo it
shares only the shape. [CONTRIBUTING.md](CONTRIBUTING.md) lists the open questions and how to help close
them.

## License

MIT. See [LICENSE](LICENSE).
