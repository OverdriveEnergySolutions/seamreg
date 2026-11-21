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
- **Not the session that runs them.** The agent you talk to also spends while it orchestrates. On first reviews that was 11 to 15% of the total. `seams presets` shows it on its own line, and the run record does not count it.
- **A setting with no measurement** is estimated from the nearest measured one, and errs high: an effort above every measured one takes the highest measured rate times 35, the largest jump measured from high to max. The text says "not measured at this effort". A model with no measurement at all has no estimate: the text says "not measured".

## Model and effort are enforced, spend is not capped

`seams run start` opens a record of the run with its preset, its settings and its estimate. Before each seamreg agent starts, a plugin hook checks the Agent call: it must name the model and the effort the run's settings give that agent's step. A call that names another model or effort, or leaves either out, is refused, and the refusal names the right ones. So a review on standard cannot run on Opus by mistake, and a lead check cannot inherit max effort from the session. That mistake once cost $129.54, where the same lead check at high cost $4.44. The hook also refuses every start while `CLAUDE_CODE_EFFORT_LEVEL` would override the step's effort.

The run's spend is recorded, and reported against the estimate, but never capped. A cap set from the estimate stops runs half done: on a 555-file repo, standard's drift check had 15 packets to check where the estimate, made before the review, counted 7. Some repos need more than any estimate, and the price of each step comes from the model and effort, which the hook holds. When a run passes its estimate, the skill tells you at its next report and goes on.

When a seamreg agent ends, a second hook prices it from its own transcript. `seams spend` and the end of a run list each agent that still ran on another model or effort than the preset (Claude Code can apply a setting the call did not name), and each agent whose cost is not known, which counts at its step's per-packet estimate.

`seams run finish` waits until every agent has finished. `seams run stop` closes the run at once, and each agent still running is recorded when it ends.

The hooks act only on a run that `seams run start` opened for this user on this machine. It writes the run's id, preset and settings to a marker in your state folder (`$XDG_STATE_HOME/seamreg`, or `~/.local/state/seamreg`), outside the repo, and the hooks check each start against that copy. A run record a repo commits, or an edit to one, changes nothing.

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

A diff scan runs every step of the preset on the diff only: the reviewers take the new leads' packets, the lead check the new leads, and the drift check and re-rating the new seams. A diff scan's packets hold only the folders its new leads touch, so a small diff reviews little code. Each packet still costs its fixed part, about $8.50 on standard.

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
| Review | Sonnet, max | $8.53 per packet plus $0.0000434 per reviewed line (each run 0.83 to 1.36 times this) | 6 | vaultwarden, dawarich (twice), firefly-iii (twice), seamreg |
| Drift check | Sonnet, max | $1.01 per seam | 5 | vaultwarden (twice), dawarich (twice), firefly-iii |
| Drift check | Sonnet, xhigh | $0.111 per seam | 1 | vaultwarden |
| Drift check | Sonnet, high | $0.053 per seam | 3 | vaultwarden |
| Lead check | Sonnet, max | $0.149 per lead | 1 | vaultwarden |
| Lead check | Sonnet, high | $0.00425 per lead | 1 | vaultwarden |
| Risk re-rating | Opus, medium | $0.0183 per seam | 2 | dawarich, firefly-iii |
| Seams recorded | Sonnet review | 36 per first-review packet (24 to 55 per run), 15 per lead-only packet | 5, and 1 | as the review |
| Orchestrating session | first review | 11 to 15% of the total | 4 | as the review |

Most rates rest on one or two runs. A review packet costs mostly a fixed amount, because the reviewer re-reads its context at each step of its work, so a small repo's review costs nearly as much as a large one's. Treat an estimate as a range of about a third either way. The benchmarks page has the detection and prevention results behind the trade-offs: [benchmarks.md](benchmarks.md).

## Limits

- **Claude Code only, in full.** The model and effort check and the spend record need Claude Code's plugin hooks and per-agent effort (Claude Code v2.1.292 or later). In other agents the skill passes the model and the effort in words, and it cannot record spend. It tells you so after the first agent.
- **`CLAUDE_CODE_EFFORT_LEVEL` overrides every preset effort.** The skill warns when it is set, and the run record shows the effort each agent really ran at.
- **One calibration repo.** If a run's actual cost lands more than 30% from its estimate, please report it with the run's `seams spend --json`. That is how the rates get better: see [CONTRIBUTING.md](../CONTRIBUTING.md).
