# Presets: how much to spend, and what each level buys

A paid seamreg run has four steps: the review, the drift check, the lead check and the risk re-rating. A **preset** names the model and the effort for each one. The review skill opens by showing both presets with what each would cost on your repo, and waits for your choice. At the end of the run it offers to save that choice, so later runs do not ask again.

Costs here are API-equivalent dollars. On a Claude subscription you are not charged them: they count against your plan's usage. Read them as a relative measure, one preset against the other.

## The two presets

| | standard | all-in |
|---|---|---|
| Review | Sonnet, max effort | Sonnet, max effort |
| Drift check | Sonnet, max effort | Sonnet, max effort |
| Lead check | Sonnet, high effort | Sonnet, max effort |
| Risk re-rating | Opus, medium effort | Opus, max effort |
| Measured on one 555-file repo | about $30 | about $155, plus the re-rating at max (not measured) |
| Known drifts found there, of 17 | 4, plus 2 partly | 8, plus 3 partly |

**standard** is the measured best value. Its lead check runs at high effort, which adds about 2 known drifts to a review for about $4. On the measured repo it cost about 20% of all-in.

**all-in** runs every step at max effort. Its lead check reads much further beyond each lead's own files. That found about twice the known drifts of standard, for about five times the price. Most of the extra cost is the lead check: $129.54 at max against $4.44 at high.

`seams presets` shows both presets with this repo's estimate. The estimate counts the scan's reviewed lines and leads, so a large repo shows a larger number than the table above.

### Why there is no cheaper preset

A lead check without a review was the candidate for a cheap way in. Measured end to end with the shipped tool on two repos, agents making real past changes kept every copy in step in 16 of 36 clean runs with that registry. With no registry the figure was 13, and with a reviewed one it was 28. A cheaper preset will come back only when a configuration of it passes the same test against those two baselines.

## What the estimate counts

- **The agents.** The estimate prices each step's work at a rate measured on earlier runs (the table below). During a run, a hook adds up what each agent really cost from its own transcript, and the skill reports the two side by side at the end.
- **Not the session that runs them.** The agent you talk to also spends while it orchestrates. On first reviews that was 11 to 15% of the total. `seams presets` shows it on its own line, and the ceiling does not count it.
- **A setting with no measurement** is estimated from the nearest measured one, and errs high: an effort above every measured one takes the highest measured rate times 35, the largest jump measured from high to max. The text says "not measured at this effort". The first packet's real cost then corrects it.

## The ceiling

`seams run start` opens a record of the run, and its estimate becomes the run's ceiling. Before each seamreg agent starts, a plugin hook reserves that packet's estimated cost. It refuses the start when spend so far, plus the agents still running, plus this packet, would pass the ceiling. It also holds a step's second agent until the first one finishes. After that, each start of the step reserves the step's per-packet estimate or the costliest packet of the step so far, whichever is higher. So a first packet that cost more than its estimate raises what the rest of the batch reserves. A step the estimate gave no packets (a small repo can show no drift check) still reserves one full packet per start.

When a start is refused, the skill shows you what has been spent and asks. Only your yes raises the ceiling (`seams run raise --to <dollars>`). A run with nobody to ask, such as a benchmark or CI run, stops there and reports what finished and what did not.

A run ends at most one batch past its ceiling, because agents already running cannot be stopped.

`seams run finish` waits until every agent has finished. `seams run stop` closes the run at once: agents still running count at their reservations, and each one's real cost is still recorded when it ends. `seams spend` and the end of a run list each agent that ran on another model or effort than the preset. They also list each agent whose cost is not known, which counts at the step's estimate.

When a setting has no measured rate at all (a model with no measurement), `seams run start` asks for a ceiling instead of making one up: pass `--ceiling <dollars>`. Each step with no rate then reserves an even share of that ceiling per packet.

## Saving a preset

At the end of a run the skill offers to save the preset in `seams.settings.json`, beside `seams.json`. Commit it, so the whole team runs the same way. It holds the preset's name and only the settings you changed:

```json
{"schema_version": 1, "preset": "standard", "changes": {"lead_check": {"effort": "xhigh"}}}
```

A saved preset follows its name. When a new seamreg release changes what standard runs, your next run uses the new standard with your own changes kept, and the skill asks once before it runs. `seams check` fails on a setting it does not know, naming it.

The settings live in their own file because a team's CI runs its own copy of the checker. An older copy rejects any new field in `seams.json`, so a save there could turn CI red.

## When a saved preset asks again

| Run | Asks first? |
|---|---|
| A diff scan (only the leads new since the last review) | No, unless its estimate passes a share of a full run on the same preset: 25% unless you set `diff_limit_percent` |
| A full re-scan, or a gap pass | Yes, always |
| Any run after a release changed the saved preset | Yes, once |
| No preset saved | Yes |

A diff scan runs every step of the preset on the diff only: the reviewers take the new leads' packets, the lead check the new leads, and the drift check and re-rating the new seams.

## Every setting

| Setting | Values | Default | Pros | Cons |
|---|---|---|---|---|
| `review.model` | sonnet, opus, haiku, fable | sonnet | Sonnet found as many known drifts as Opus on two repos, for 57 to 60% of the cost | Sonnet rates risk lower: the re-rating fixes that |
| `review.effort` | low, medium, high, xhigh, max | max | Max found more of the known seams than high on the one repo measured | Lower efforts are not measured for the review |
| `drift_check.model`, `.effort` | as above | sonnet, max | Max is what every measured review used | High costs about a twentieth as much, measured only on seams a lead check added |
| `lead_check.model`, `.effort` | as above | sonnet, high (all-in: max) | High adds about 2 known drifts for about $4 | Max adds about 6, for about $130. xhigh found 6 plus 2 in one run of a different tool version |
| `rerate.model`, `.effort` | as above | opus, medium (all-in: max) | Opus raised the high-risk count that Sonnet reviews left low, for a few dollars | Only Opus's default effort is measured |
| `diff_limit_percent` | 5, 10, 15, 20, 25, 30, 40, 50, 75, 100 | 25 | Diff scans run without a question | A larger limit lets bigger diffs run unasked |

**To change a setting for one run,** say so in plain words ("use Opus reviewers this time"). The skill turns it into `--set review.model=opus`, tells you the new estimate before it starts, and offers to save it at the end. **To change it for good,** edit `changes` in `seams.settings.json`.

## Where the numbers come from

Every rate is measured on child-agent transcripts, with each response counted once and each token type priced on its own. Added to the orchestrating session, the totals match Claude Code's own cost figure for all 13 runs within half a cent. Prices are Anthropic's list prices from the model table cached 2026-11-03. The calibration repo is vaultwarden (Rust, 555 files). The reviews also come from dawarich and firefly-iii.

| Step | Model, effort | Rate | Runs | Repos |
|---|---|---|---|---|
| Review | Sonnet, max | $0.000194 per reviewed line (0.000134 to 0.000265 per run) | 4 | vaultwarden, dawarich (twice), firefly-iii |
| Drift check | Sonnet, max | $1.01 per seam | 5 | vaultwarden (twice), dawarich (twice), firefly-iii |
| Drift check | Sonnet, xhigh | $0.111 per seam | 1 | vaultwarden |
| Drift check | Sonnet, high | $0.053 per seam | 3 | vaultwarden |
| Lead check | Sonnet, max | $0.149 per lead | 1 | vaultwarden |
| Lead check | Sonnet, high | $0.00425 per lead | 1 | vaultwarden |
| Risk re-rating | Opus, medium | $0.0183 per seam | 2 | dawarich, firefly-iii |
| Seams recorded | Sonnet review | 5.4 per 10,000 reviewed lines | 4 | as the review |
| Orchestrating session | first review | 11 to 15% of the total | 4 | as the review |

Most rates rest on one or two runs, and the review's rate varies twice over between runs. Treat an estimate as a range of about that width. The benchmarks page has the detection and prevention results behind the trade-offs: [benchmarks.md](benchmarks.md).

## Limits

- **Claude Code only, in full.** The ceiling and the spend record need Claude Code's plugin hooks and per-agent effort (Claude Code v2.1.292 or later). In other agents the skill passes the model and the effort in words, and it cannot record spend. It tells you so after the first agent.
- **`CLAUDE_CODE_EFFORT_LEVEL` overrides every preset effort.** The skill warns when it is set, and the run record shows the effort each agent really ran at.
- **One calibration repo.** If a run's actual cost lands more than 30% from its estimate, please report it with the run's `seams spend --json`. That is how the rates get better: see [CONTRIBUTING.md](../CONTRIBUTING.md).
