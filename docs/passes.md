# Passes: what to run, what it costs

Building a registry takes several passes. The first review finds a third to a half of a repo's seams on the newer benchmarks, and the range is wider across all of them. After it, `seams next` ranks the passes worth running next, from the repo's leads and from what each earlier pass added. This page lists the passes, what each one cost on public repos, and when to run them side by side.

Every number here is measured, not estimated. Each one names the model and the effort it ran at. A cell that says "not measured" means nobody has run it yet.

**The dollar figures are API-equivalent.** They are the cost Claude Code reports for each session. We ran everything on a Claude subscription, and on a subscription you are not charged these amounts: the work counts against your plan's usage. Read them as relative sizes, to compare passes and models. Your numbers will differ with your repo and your model.

## The passes

| Pass | Command | What it does |
|---|---|---|
| First review | `seams split` | One reviewer per packet sweeps the whole repo with the scan's leads as hints. |
| Gap pass | `seams split --gap` | The same sweep, told which seams the registry already has, hunting for the rest. |
| Lead check | `seams split --lead-check` | A cheap agent judges every strong lead no recorded seam covers, 25 leads per agent. |
| Focused pass | `seams split --focus <kind>` | One reviewer hunts one kind of seam across the whole repo. |
| Drift check | `seams verify` | One small agent per seam checks whether its copies agree today. |
| Risk re-rating | `seams rerate` | A stronger model sets each seam's risk again, 30 seams per agent. |
| Tie | `seams tie <id>` | One agent writes a test that fails when a seam's copies disagree, and proves it. |

The focused kinds are `twins` (two implementations of one behavior), `siblings` (classes that share a base carry its fields into every layer), `packaging` (build files against manifests and the files the app reads) and `open` (guesses at new kinds of seam, each tested with a script). `seams next` offers a kind only when the scan found leads for it.

## What each pass cost

A pass's cost is the whole headless session at API prices: scan, reviewers, merge, drift check on the new seams, apply. The reviewers ran on Claude Opus 5.5 at max effort. The drift checkers ran at default effort.

| Repo | Code lines | Packets | First review | Gap pass | Twins | Packaging | Siblings |
|---|---|---|---|---|---|---|---|
| mattpocock/skills | 504 | 1 | $16 to $21 | not measured | not measured | not measured | not measured |
| uptime-kuma | 54,926 | 1 | $45 | $33 to $36 | $27 | not measured | not measured |
| umami | 53,169 | 1 | $47 | $25 to $31 | $24 | $9 | not measured |
| memos | 72,594 | 1 | $48 to $64 | not measured | $21 | not measured | not measured |
| netbox | 167,034 | 3 | $84 to $101 | $84 to $85 | $29 | not measured | $40 |
| frigate | 197,125 | 3 | $103 | $81 to $97 | $26 | not measured | not measured |

Reviews on Sonnet 5.5 at max effort, same tool and snapshots: dawarich (2 packets, 112,955 code lines) $42.66 against $74.58 on Opus, and firefly-iii (5 packets, 305,865 code lines) $68.62 against $114.08. They found as many known drifts as Opus, though not the same ones. See [benchmarks.md](benchmarks.md#models-compared).

Packets matter as much as lines: two one-packet repos of 504 and 54,926 lines cost $16 to $21 and $45. A gap pass cost 0.55 to 0.94 of the same repo's first review. A focused pass cost $9 to $40, a fifth to three fifths of the same repo's first review.

| Pass | Wall time measured |
|---|---|
| First review, 3 packets | 86 to 104 minutes |
| Gap pass | 56 to 81 minutes |
| Twins | 60 to 74 minutes |
| Packaging | 35 minutes |
| Siblings, netbox | 69 minutes |

A focused pass is cheaper than a broad one, but not faster. It is one reviewer working through every lead in turn, while a broad pass splits the repo across reviewers that run side by side.

## Smaller costs

| Step | Model and effort | Measured |
|---|---|---|
| Drift check, per seam | default effort (model not recorded) | 46k to 113k tokens, 64k on average, 2 to 10 minutes (34 seams, three repos). Later runs used more: about 108k on average for 14 seams on one repo, and up to 161k and 16 minutes for one seam. |
| Drift check, per seam | max effort (model not recorded) | 87k to 242k tokens, 169k on average |
| `seams tie`, per seam | Opus 5.5, default effort | $0.80 and $1.03, about 9 minutes each (2 seams) |
| An MCP lookup | Haiku | under $0.01 |
| Lead check, per lead | Sonnet 5.5, high effort | about $0.016 (1,670 leads, $27.37). From an empty registry, two repos had 1,181 and 1,528 strong leads. |
| Drift check, per seam | Sonnet 5.5, default effort | $0.11 to $0.13 (235 seams) |
| Risk re-rating, per seam | Opus 5.5, default effort | about $0.02 (206 seams, $3.78) |

## What the registry costs in everyday work

An agent doing an ordinary task reads the registry's notes, the hook's text and the Stop hook's message, so a task costs more with seamreg. Measured on real commits replayed at their parent commit, with and without seamreg:

| Tasks | Cost per task with seamreg | Without |
|---|---|---|
| The registry holds the rule the task needs (9 tasks), Fable 5.2 | $1.52 | $0.70 |
| The same 9 tasks, Opus 5.5 at high effort | $1.00 | $0.51 |
| 17 tasks on umami and memos, Sonnet 5.5 at high effort | $0.29 | $0.15 |
| netbox, 104-seam registry, Fable 5.2 | $2.00 | $1.16 |

On those 9 tasks Fable updated every copy in 27 of 27 runs with seamreg, and in 15 of 27 without. Opus: 26 against 17. On the 17 umami and memos tasks Sonnet: 32 of 41 against 16. That is the return on the extra cost. Where the registry did not hold the rule, Fable gained less (54% of runs against 36%), and Opus gained nothing (49% against 46%).

## Side by side or one after another

Run these side by side:

- the reviewers of one pass, one per packet,
- the drift checkers, one per seam.

All of them only read files, so they cannot disturb each other.

Run these one after another:

- **Passes of different kinds.** `seams next` picks the next pass from the last one's yield. If a siblings pass records the relation a writers pass would hunt, you can skip the writers pass. Run both at once and that choice is lost, and the pass ledger cannot say which pass found what.
- **Two passes from one registry.** Each one starts from the same `seams.json`. Both can record the same new seam, and a merge catches duplicates only inside one pass.
- **Tie writers in one working tree.** A tie writer breaks copies on purpose to prove its test fails. Two in one tree see each other's broken files. Give each one its own clone, or run them one at a time.

Also watch the account's rate limits. Five max-effort sessions ran side by side without trouble in our runs. More than that is not measured.

## Not measured yet

- Reviewers on Sonnet on more than two repos, on Haiku, or at any effort below max.
- The `siblings` pass on any repo but netbox.
- A focused pass split into packets that run side by side.
- Lead checks on a repo the lead kinds were not tuned on.
