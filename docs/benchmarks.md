# Benchmarks

Everything we have measured about seamreg, with the method, the numbers, and their limits. The first
section is the short version. The rest is the detail behind it, newest work first within each part.
[concepts.md](concepts.md) defines the terms.

This page is kept out of the README so that a blind benchmark run can read the README without reading
its own score.

**About the dollar figures.** Every cost on this page is the API-equivalent figure Claude Code reports
for a session. We ran everything on a Claude subscription, and we expect most users to do the same. On a
subscription you are not charged these amounts: the work counts against your plan's usage instead. Read
the dollars as a relative measure, for comparing one step or model with another.

## The short version

1. **When the registry holds the seam, agents keep the copies in step far more often.** Real past
   commits that missed a copy, replayed at their parent commit with and without seamreg, on 9 tasks with
   3 runs each: Opus 5.5 kept every copy in step in 26 of 27 runs with seamreg and 17 without (1.5
   times). Fable 5.2, 27 against 15 (1.8 times). Sonnet 5.5, on 17 tasks (7 of them among the 9), 28 of
   36 against 13 (2.2 times). Without seamreg the most common failure is an agent that notices the stale
   copy, says so, and leaves it.
2. **The weak link is getting the seam into the registry.** On the four newest benchmark repos, one blind
   first review recorded a third to a half of the seams an answer key lists, and caught 2 to 4 of 11 to 17
   known drifts. On older repos the range was much wider. On firefly-iii, reviews on Sonnet and on Opus
   missed the same 11 of 14 known drifts, for the same reason, so more of the same review does not close
   the gap.
3. **Cheap, narrow checks find some of what a review walks past.** A lead check (a cheap agent judges one
   scan lead at a time) found known drifts the reviews had missed on two of three repos, for $5 to $17 a
   repo, with no wholly false claim among the 55 graded.
4. **A Sonnet review found as many known drifts as an Opus review, for about 60% of the cost**, on two
   repos, but not the same ones. It rated far fewer seams high, and missed one high-risk security drift
   that Opus found. A re-rating pass on Opus raised the high count to Opus's level or above for about $2 a
   repo.
5. **Without a review, a lead-check registry gets about half the benefit.** Sonnet on 17 real tasks: 13 of
   36 runs kept every copy in step with no registry, 22 with a lead-check registry ($27 for two repos),
   28 with a reviewed one.
6. **Some things did not help:** focused passes on a repo they were not designed from, a sharper reviewer
   brief on its own tuning repo, a full re-check of every recorded seam's drift, look-alike file path
   leads, and, on Opus, a registry that did not hold the task's rule (19 against 18 of 39). Each is
   reported below.
7. **On easy tasks, strong models need little help.** With a careful developer CLAUDE.md, Sonnet and Opus
   kept 82 to 88% of a realistic task sequence in step on their own, and seamreg added cost without gain
   there. seamreg's value sits in the changes where an agent would otherwise leave a copy behind.
8. **On 7 tasks, Sonnet with seamreg did what Opus and Fable did.** Every model kept every copy in step in
   20 or 21 of 21 runs with seamreg. Without it, Sonnet managed 7, Fable 12 and Opus 14. Sonnet cost about
   a third of Opus per run.
9. **Read the numbers as signals.** Most arms are one run per version, or three runs per task on a few
   dozen tasks: differences of two or three runs are noise. Several changes were designed from the repos
   they were then measured on. Each section says which.

## Run one yourself, or ask us to

Every result on this page came from one maintainer's runs. To make the statistics broader than that, the
method is packaged as a harness in [bench/](../bench/README.md). Point a Claude Code session at
[bench/README.md](../bench/README.md) and name a repo: it makes a blind snapshot, builds an answer key
from the repo's later fixes, runs seamreg blind in an isolated session, checks the transcripts for leaks,
grades the run, and writes one result file. Submit the result as a pull request, and after review it is
added to the statistics, whatever it shows.

The harness is built to grow. Each kind of benchmark is one folder in
[bench/kinds/](../bench/kinds/README.md), on top of shared parts for the snapshot, the blind session, the
blindness scan and the result file. Detection is the first kind. If you find a new question worth
measuring, add a kind.

The first result through the harness is vaultwarden (Rust, 555 files, snapshot after the models'
training cutoff): 2 of 17 known drifts stated, 1 in part, 6 of 20 key seams in full, and 18 other claims
graded with none wrong. It cost $30.47 API-equivalent for the key, the blind run and the grading. Its files
are in [bench/results/](../bench/results/vaultwarden-169aa5efcc-detection/). One key row is held back
there until its fix ships in a vaultwarden release.

To ask us to run one instead, open an issue with the **Benchmark request** template.

## Models compared

We ran the same steps on Sonnet 5.5, Opus 5.5 and Fable 5.2 wherever we could afford to. Each row below
holds everything else fixed: the same tasks or snapshot, tool version and scoring.

| What | Sonnet 5.5 | Opus 5.5 | Fable 5.2 |
|---|---|---|---|
| Prevention, 7 tasks whose rule the registry states, with seamreg | 20 of 21 | 20 of 21 | 21 of 21 |
| The same tasks without seamreg | 7 of 21 | 14 of 21 | 12 of 21 |
| Cost per run, with / without | $0.23 / $0.11 | $0.75 / $0.35 | $1.25 / $0.56 |
| First review, dawarich: known drifts, cost | 4 + 2 partial, $42.66 | 4 + 1 partial, $74.58 | not run |
| First review, firefly-iii: known drifts, cost | 2 + 1 partial, $68.62 | 2 + 1 partial, $114.08 | not run |
| Seams rated high, dawarich / firefly-iii | 2 / 2 | 7 / 17 | not run |
| Forward chains, 17 tasks x 3, with a careful CLAUDE.md: without / with seamreg | 42 / 42 of 51 | 45 / 42 of 51 | not run |
| Forward chains: cost, with seamreg | $29.71 | $94.88 | not run |

Effort: Sonnet and Opus at high in the replays and chains, max in the reviews. Fable at its default.

What the table says, and what it does not:
- With seamreg on tasks whose seam the registry holds, the three models ended up level. Without it,
  Sonnet did worst and Opus best. So the weaker a model does alone, the more seamreg added: 13 runs for
  Sonnet, 9 for Fable, 6 for Opus. That is 7 tasks on 2 repos.
- A review on Sonnet found as many known drifts as on Opus on both repos tried, but not the same ones,
  and it rated risk much lower. `seams rerate` on Opus raised the high-risk count to 18 on dawarich (the
  Opus review had 7) and 14 on firefly-iii (Opus: 17), for $3.78 across both.
- On the forward chains, which mostly sit at the ceiling, the models were within three runs of each
  other with or without seamreg.
- Lead checks and drift checks ran on Sonnet only. We have no Opus lead check to compare.
- Not measured: Fable for reviews or chains, Haiku beyond one registry lookup, and Sonnet reviews on more
  than two repos. Seven tasks and two repos are small samples.

## How we test

Three kinds of benchmark, each answering a different question.

### Detection: does the tool find the seams and the drift?
1. Pick a public repo and a snapshot commit, 4 to 12 months before the key is built. The five newest
   snapshots are near 2026-07-01.
2. Build an **answer key** from the repo's later history: the seams its structure implies, and every
   drift its maintainers fixed after the snapshot. Each drift row names the fixing commit, and both sides
   were read at the snapshot.
3. Run the tool blind on a clone that holds only the snapshot's history, in a fresh headless Claude Code
   session.
4. Score the run against the key: key seams recorded, key drifts stated, and a hand grading of a sample of
   the run's other claims.

Grading verdicts for a claim: **FIXED** (true at the snapshot, fixed upstream later), **PRESENT** (true, and
still in the code at the latest commit), **WRONG** (false at the snapshot), **UNCLEAR**. We publish counts of
PRESENT claims, not their details, so we do not publish other projects' open bugs.

### Prevention replays: does the registry stop the next drift?
1. Collect real commits that changed one copy and missed another (39 tasks from 6 public repos).
2. For each, start an agent at the commit's parent with the task the commit did, phrased as a request.
3. Run it with and without seamreg, several times each.
4. A script per task checks whether the missed copy was updated.

A run **updated** every copy, **flagged** the stale copy in its reply but left it, or **missed** it.

### Forward chains: does it hold up over a sequence of changes?
The prevention tasks of one repo replayed in commit order, with the registry carried from task to task, so
the growth features (the Stop hook's reminder, the pre-PR scan, recording a found copy) get a chance to
act. Each task ends as a pull request. From chain 2 on, every session in every arm gets the same
developer CLAUDE.md.

### Controls
- **Blindness:** the transcripts of every first review, gap and focused pass, and forward-chain start
  review were scanned for reads of the answer key, the full-history clone and the benchmark folders, and
  for network use. All passed. The later cheap checks (triage, lead check, drift check, re-rating) ran as
  single agents on a clone at the snapshot, and their transcripts were not scanned.
- **Leaks:** a seeded registry built after a task's commit could state the answer. A leak check flags
  those tasks. They get one run, and are reported apart: the Sonnet numbers on this page count clean runs
  only.
- **Isolation:** the prevention replays, forward chains and cheap checks ran with the user's own
  settings, skills, plugins, hooks and MCP servers turned off. The detection reviews did not: they ran in
  the maintainer's own Claude Code setup. That keeps comparisons between tool versions fair, but adds an
  unknown to the absolute numbers. The public harness in [bench/](../bench/README.md) isolates every blind
  session.
- **Tool version:** the single-task prevention replays ran an early version (before 0.1), with no plugin
  and no CLAUDE.md. The 0.2 Stop hook, planning text and tie wording were measured only in the forward
  chains.
- **Training cutoff:** the models' training data ends in June 2026. For detection, most scored fixes came
  after it. For prevention, the tasks and most of their fixes came before it.

## Detection results

### First reviews, by repo

| Repo | Stack | Snapshot | Known drifts caught | Tool and model |
|---|---|---|---|---|
| [mattpocock/skills](https://github.com/mattpocock/skills) | Markdown skills | `2ab9580` | 7 of 7 | 0.1, Opus |
| [uptime-kuma](https://github.com/louislam/uptime-kuma) | Node, Vue | `3f944ded` | 2 of 3 | 0.1, Opus |
| [umami](https://github.com/umami-software/umami) | TypeScript | `a87d899e` | 5 of 8 | convention seams, Opus |
| [frigate](https://github.com/blakeblackshear/frigate) | Python, TypeScript | `9cb76d0b` | 4 of 8 | 0.1, Opus |
| [netbox](https://github.com/netbox-community/netbox) | Django | `3eb89531a` | 4 of 8 | convention seams, Opus |
| [memos](https://github.com/usememos/memos) | Go, React | `0e1d821fb` | 6 of 12 | convention seams, Opus |
| [plausible](https://github.com/plausible/analytics) | Elixir, TypeScript | `1c539f6bf0` | 2 of 11 | 0.1 and 0.2 brief, Opus |
| [dawarich](https://github.com/Freika/dawarich) | Rails | `7b877f9cc9` | 4 of 16, 1 partial | 0.2 brief, Opus and Sonnet |
| [firefly-iii](https://github.com/firefly-iii/firefly-iii) | Laravel | `a95b82b14c` | 2 of 14, 1 partial | 0.2 brief, Opus and Sonnet |
| [vaultwarden](https://github.com/dani-garcia/vaultwarden) | Rust | `169aa5efcc` | 2 of 17, 1 partial | 0.2, Sonnet, through the [harness](../bench/results/vaultwarden-169aa5efcc-detection/) |

plausible, dawarich and firefly-iii were picked on fixed criteria (a stack not yet tested, 500 to 3,000
files, many fix commits after the snapshot) before anyone looked at their seams. A first review costs $12
to $115 depending on size and model. [passes.md](passes.md) has the detail.

### Sonnet against Opus (2026-11-19)

The same tool, snapshot and answer key, with every agent on Sonnet 5.5 or on Opus 5.5:

| | dawarich, Sonnet | dawarich, Opus | firefly-iii, Sonnet | firefly-iii, Opus |
|---|---|---|---|---|
| Cost | $42.66 | $74.58 | $68.62 | $114.08 |
| Known drifts | 4, 2 partial | 4, 1 partial | 2, 1 partial | 2, 1 partial |
| Key seams fully recorded | 8 of 20 | 6 of 20 | 7 of 20 | 6 of 20 |
| Seams rated high | 2 | 7 | 2 | 17 |
| Graded claims wholly WRONG | 0 | 0 | 0 | 0 |
| Claims with a wrong detail | 0 | 1 of 26 | 5 of 43 | 2 of 56 |

Sonnet found as many known drifts, but not the same ones, and recorded slightly more key seams, at 57 to 60% of the cost. It
rated far fewer seams high, wrote more small wrong details inside true claims, and missed the one
high-risk key drift Opus found on dawarich (an API sign-in path that skipped a check the web form made).

**Risk re-rating** (`seams rerate`, Opus) on the two Sonnet registries cost $3.78 in all. Seams rated high
went from 2 to 18 on dawarich (Opus's own review: 7) and from 2 to 14 on firefly-iii (Opus: 17). The raised
seams we read were silent failures, security or abuse limits, or data loss, and included the seams
behind three known drifts. Re-rating cannot add a seam the review never recorded.

### Cheap checks after a review (2026-11-19)

| Check | What it is | Cost, 3 repos | Known drifts added | Graded claims |
|---|---|---|---|---|
| Triage | Sonnet judges every strong lead no seam covers, 25 at a time | $27.37 | 3 (firefly-iii 2, dawarich 1) | 30: 0 WRONG, 2 partly wrong |
| Lead check on shared-ids leads | The same, on a new lead kind, through the product's own command | $15.16 | 1 (dawarich) | 25: 0 WRONG |
| Drift check, seams with no drift | One Sonnet agent per seam | $10.34 | 0 | not graded |
| Drift check, blind second look | The same on seams whose drift came from reading, with that drift hidden | $18.25 | 0 | 15: 5 WRONG |

The triage became the product's lead check. One example of what it finds: two firefly-iii API
controllers held the same faulty condition. Upstream fixed one copy, and the other seven weeks later.
The review had the scan's lead pointing at exactly those two blocks (lead 248 of 400 in its packet) and
recorded nothing. The triage recorded the seam and named the shared mistake for $0.40.

The drift checks did not pay: the drifts the reviews missed sat in seams whose recorded definition
pointed the checker somewhere else, or in files no seam listed.

Running totals after every step, key drifts stated:

| Repo | Review alone | After the cheap checks |
|---|---|---|
| dawarich | 4 of 16, 1 partial | 6 of 16, 1 partial |
| firefly-iii | 2 of 14, 1 partial | 4 of 14, 1 partial |
| plausible | 2 of 11 | 2 of 11 |

### New lead kinds (2026-11-19, offline, no agents)

Measured on the scans of 7 repos with answer keys, and on the 32 prevention tasks scanned at their parent
commits. "Linked" means one lead holds a changed file and its missed copy, or two copies of a key seam.

| Lead | Key seams no other lead linked, newly linked | Prevention tasks linked, of 32 |
|---|---|---|
| Random file pairs (control) | 0 to 2 of 48 | 0 |
| Look-alike paths (web and API twins, create and update pairs) | 1 of 48 | not measured |
| shared-ids | 15 of 48 | 7 |
| flow | 4 of 33 | 9 |
| key-writers | 8 of 33 | 9 |
| access | 2 of 33 | 3 |
| The older copy-based kinds | (baseline) | 0 to 4 each |

The settings of the new kinds were picked while looking at these repos, so their rates on a fresh repo
are not known yet. The look-alike path leads were not kept.

### Earlier detection work (2026-11-15 to 11-17)

**Three passes on four repos.** A first review, then two gap passes, each in a fresh session.

| Repo | Known drifts | First review | After gap 1 | After gap 2 | Cost, 3 passes |
|---|---|---|---|---|---|
| uptime-kuma | 3 | 1 | 2 | 3 | $115 |
| umami | 8 | 4 | 5 | 6 | $103 |
| frigate | 8 | 4 | 5 | 5 | $282 |
| netbox | 8 | 0 | 0 | 0 | $271 |
| All | 27 | 9 | 12 | 14 | $770 |

Of 249 high and medium drift claims checked against the code, none was false. Maintainers later fixed 74.
netbox's drifts all broke one rule that every model's files follow, which led to convention seams.

**Convention seams.** A scan lead for a pattern most members of a family follow, and a seam kind whose
drift check covers every member. netbox went from 0 to 4 of 8 known drifts with one first review. Umami
from 4 to 5 of 8. Memos, not used to build the change, stayed at 6 of 12 for $48 instead of $64.

**Focused passes.** A twins pass (one behavior written twice) added 3 known drifts on memos, the repo it
was designed from, and 1 across the four others, for $21 to $29 each. None of its 76 graded claims was
false. On plausible, a fresh repo, a chain of four focused passes after the first review (twins,
siblings, packaging, open) cost $80.54 and added no known drift: the first review's 2 of 11 stayed 2 of 11.
They do add true but unscored findings, so they remain optional.

**A sharper reviewer brief** (full-depth compares, rule bypasses, limits stated in words, CI checked
against itself) was written from plausible's misses. On plausible it found the same 2 of 11 and recorded
2 more key seams, within run-to-run noise. It ships in 0.2. Dawarich and firefly-iii above ran with it,
with no old-brief baseline to compare.

**How the numbers moved on mattpocock/skills,** four runs on one snapshot: 3, 5, 5, then 7 of 7 known
drifts, as the scan learned to match doc lists and read git history, and the reviewer learned to check
that a description's list is complete. The last rule was written after seeing the misses, so it shows the
rule works there, not everywhere.

**Beyond the keys.** On mattpocock/skills an early run claimed 16 drifts. The maintainer later fixed 10 of
them without the tool. On uptime-kuma, runs caught a notification provider that had read the wrong field
for 15 months, a push message whose text said the opposite of its title, and an endpoint missing an
access check its siblings had. The project later fixed each one.

## Prevention results

### Single-task replays

These replays ran an early version of the tool (before 0.1), with no plugin and no CLAUDE.md: the
registry reached the agent through its notes and the edit hook.

| Model | Tasks | With seamreg | Without | Tasks better / worse / same |
|---|---|---|---|---|
| Fable 5.2, registry states the rule | 9 | 27 of 27 | 15 of 27 | 5 / 0 / 4 |
| Fable 5.2, no seam states it | 13 | 21 of 39 | 14 of 39 | 5 / 0 / 8 |
| Opus 5.5, registry states the rule | 9 | 26 of 27 | 17 of 27 | 5 / 0 / 4 |
| Opus 5.5, no seam states it | 13 | 19 of 39 | 18 of 39 | 2 / 2 / 9 |

The registries were the benchmark registries (a first review plus a twins pass), built after the tasks
with their drift text removed and pruned to what existed at each parent. "States the rule" was decided
by reading every candidate seam per task, before the runs. On Opus, one stated-rule failure cited the
planning text's old wording ("a drift fix needs a test") as its reason for leaving a copy. 0.2 changed
that wording so a missing test never blocks a fix.

### Sonnet, and how much each registry is worth (umami and memos, 17 tasks)

12 clean tasks with 3 runs each, plus 5 leaky tasks with 1 run each. The table counts clean runs. With
the leaky runs added, the order is the same (16, 19, 20, 25, 32 and 32 of 41).

| Registry | Kept every copy in step, clean runs | Registry cost |
|---|---|---|
| None | 13 of 36 (36%) | none |
| Lead check, every seam it judged real | 15 of 36 (42%) | $27 |
| Lead check, drift seams only | 16 of 36 (44%) | $19 |
| Lead check, drift seams plus agreeing seams from the precise kinds | **22 of 36 (61%)** | $27 |
| Reviewed registry | **28 of 36 (78%)** | a review per repo |
| Reviewed registry plus lead check | 28 of 36 (78%) | a review plus $13 |

The lead-check registry is not small: 158 and 157 seams, against about 60 in the reviewed ones. It
holds more seams, chosen with less judgment.

The lead checks ran once per repo, at the parent of its earliest task, on a clone with history up to
there only. Agreeing seams were real in 5 of 5 sampled for the flow, key-writers, twin and access kinds,
4 of 5 for shared-ids, 1 of 5 for copied code and 0 of 3 for shared value lists. Keeping all of them
buried the real ones. One task (umami `2524a95d2`) failed in every lead-check arm and passed 3 of 3 with
the reviewed registry.

## Forward chains

| Chain | Arms and result (runs that kept every copy in step) | What it showed |
|---|---|---|
| 1: Opus, frigate (7 tasks) and pocock (5) | frigate: without 16/21, static registry 18/21, growing 18/21, growing from empty 15/21. pocock: 12/15 in every arm | Growth added nothing over a static registry. The pre-PR scan ran in 7 of 108 runs and the Stop hook fired in 1, because agents committed before they stopped. Chain 1 gave the agents no CLAUDE.md. |
| 2: Opus and Sonnet, frigate, pocock and kuma (17 tasks) | Opus without 45/51, with 42/51. Sonnet without 42/51, with 42/51 | After the 0.2 fixes the pre-PR scan ran in 96 of 102 runs and the Stop hook fired in 100 of 102. Outcomes did not move: most tasks sat at the ceiling, and seamreg added 60 to 70% to the cost. One Sonnet task got worse: 3 of 3 without, 0 of 3 with. |
| 3: Sonnet, chain 2 with one CLAUDE.md line removed | without 40/51, with 43/51 | On the one task whose seam the registry held (a frigate API doc): 0 of 3 with neither the line nor seamreg, 2 of 3 with the line alone, and 3 of 3 with seamreg. |
| 4: Sonnet, chain 2 with lead-check seams added to the start registry | 42/51, the same as chain 2 | The new seams reached one task, which Sonnet already solved. |

Twenty runs in chain 1 and four in chain 2 hit a full `/tmp` (agents built large Python environments in
a small RAM disk). Every arm of chain 1's frigate runs was affected. Later runs give each session its own
temp folder.

## Costs

Every cost is the session's API-equivalent total, as Claude Code reports it. On a subscription, read it as
relative usage, not a charge. [passes.md](passes.md) lists each pass by repo size, model and effort. In everyday work an agent with seamreg costs more per task, because it reads notes and hook
text: about twice as much on Fable and Opus, 1.7 to 2.1 times on Sonnet.

## Read these with care

Each limit below is also an open question. [CONTRIBUTING.md](../CONTRIBUTING.md) says how to help close it.

- One run per version, or three runs per task. Runs vary by about a known drift, and by two or three
  runs in a 41-run arm.
- Answer keys are incomplete, and the person who built a key also graded seam matches. Drift counts are
  firmer: each rests on a later upstream commit.
- Several changes were designed from the repos they were measured on (memos for the twins pass,
  plausible for the sharper brief, all keyed repos for the new lead kinds). Each section says so.
- Security findings and unfixed bugs in other projects are counted, not described.
- Nine repos, mostly web apps. Nothing yet on mobile, embedded, data pipelines or monorepos over 5,000
  files.
- Prevention tasks are commits that missed a copy, which is the case seamreg is built for. How often such
  changes happen in a given repo is not measured, so the gain in everyday work is not known.
- The new lead kinds' settings and the lead check's list of precise kinds were picked on these repos. A
  repo the tool has never seen is the real test.
