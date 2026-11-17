# Benchmarks

Each benchmark is one blind run: a fresh Claude Code session ran the whole workflow at max effort on a snapshot from before the fixes, with no access to the answers. A headless session ran it, and its transcripts were checked afterwards for any read of the answer key. Each answer key lists the seams the repo's own rules or structure imply, and the drifts that its maintainers fixed after the snapshot. A drift counts as caught when the run records it.

This page is kept out of the README so that a blind run can read the README without reading its own score.

## Latest runs (seams 0.1, 2026-11-15)

| | [mattpocock/skills](https://github.com/mattpocock/skills) at `2ab9580` | [louislam/uptime-kuma](https://github.com/louislam/uptime-kuma) at `3f944ded` |
|---|---|---|
| What it is | Agent skills: 110 Markdown files, JSON manifests | A Node server and a Vue client, 636 files |
| Scan alone, no agents: key seams with a lead | 12 of 13 | 8 of 8 |
| Blind run: key seams recorded | 11 of 13, the other 2 in part | 7 of 8 |
| Known drifts caught | 7 of 7 | 2 of 3 |
| Seams recorded / with drift | 35 / 23 | 65 / 36 |
| Cost at API prices | $21 | $49 |

## Three passes on four repos (2026-11-16)

Each repo got a first review and then two gap passes (`seams split --gap`). Each pass ran in a fresh headless session. A gap pass is a second review that hunts only for the seams the earlier passes missed.

| Repo | Known drifts | First review | After gap 1 | After gap 2 | Cost, 3 passes |
|---|---|---|---|---|---|
| [uptime-kuma](https://github.com/louislam/uptime-kuma) `3f944ded` | 3 | 1 | 2 | 3 | $115 |
| [umami](https://github.com/umami-software/umami) `a87d899e` | 8 | 4 | 5 | 6 | $103 |
| [frigate](https://github.com/blakeblackshear/frigate) `9cb76d0b` | 8 | 4 | 5 | 5 | $282 |
| [netbox](https://github.com/netbox-community/netbox) `3eb89531a` | 8 | 0 | 0 | 0 | $271 |
| All | 27 | 9 | 12 | 14 | $770 |

- The second gap pass still caught a known drift on two of the four repos. It also recorded 14 more claims that the maintainers fixed later. It costs about three quarters of a first review. Three passes is the minimum we recommend.
- Every second gap pass still added high-risk seams, so the point where more passes stop paying is not measured yet.
- We checked 249 high and medium drift claims against the code at the snapshot. None was false. The maintainers later fixed 74 of them, and most of the rest are still in the code.
- More passes do not fix netbox. Its known drifts all break one checklist: each model repeats its field list in its form, serializer, search index and filters. The tool records seams between named copies. It does not yet record a rule that every file of one kind must follow. umami's two missed drifts have the same shape.
- The model's training data ends in June 2026. Of the 64 later fixes we could date on umami, frigate and netbox, 39 came after that date. Memorized fixes do not explain these results.

## Convention seams (2026-11-16)

netbox's known drifts all broke one rule that every model's files follow: the form, serializer and search index list the model's fields. The tool had no way to record such a rule, so three passes found none of them. Version 267fff2 adds a scan lead for a pattern most members of a family follow and the members that break it, a `convention` seam kind whose drift check covers every member, and a place for bugs that are not seams. One first review per repo, on the same snapshots:

| Repo | Before: first review | Before: three passes | After: first review | Cost of the first review, before and after |
|---|---|---|---|---|
| netbox | 0 of 8 | 0 of 8 | 4 of 8 | $101, $84 |
| umami | 4 of 8 | 6 of 8 | 5 of 8 | $47, $47 |
| memos (not used to build the change) | 6 of 12 | not run | 6 of 12 | $64, $48 |

- On netbox, the run recorded 14 convention seams. A grader checked 12 of them against every member with a script, and nearly all held exactly. One named member was wrong. All 9 bugs reported outside the seam format held, and the maintainers later fixed 4.
- On umami, a convention seam caught a drift that no earlier pass had found. The run lost one drift that the old first review caught: a reviewer rated that seam low, and the drift check skipped it.
- The change was built after studying netbox's misses, so a repo that was not used to build it is the fairer test. On [memos](https://github.com/usememos/memos) at `0e1d821fb` (Go and React, snapshot 2026-07-01, 12 known drifts all fixed later), one first review with each version found the same 6 of 12. The scan's 3 convention leads there were style patterns, and none of memos' known drifts is a member of a family breaking its rule. The new version cost $48 and the old one $64. So the change helps where a repo's knowledge lives in families of look-alike files, and it found no extra drift where it does not. One run each, and runs vary by about a drift.

## A focused pass: twins (2026-11-16)

A focused pass runs after a first review and hunts one kind of seam across the whole repo. The first one hunts twins: one behavior written twice, such as a parser in the server and its copy in the client, or one query per database. Its reviewer tests each twin on edge-case inputs. Each run started from that repo's first-review registry, on a fresh snapshot.

| Repo | Cost | New seams | Known drifts added |
|---|---|---|---|
| memos (the pass was designed from its misses) | $21 | 20 | 3, now 9 of 12 |
| umami | $24 | 9 | 1, now 6 of 8 |
| netbox | $29 | 13 | 0 |
| frigate | $26 | 21 | 0 |
| uptime-kuma | $27 | 15 | 0 |

- None of the 76 high and medium claims graded was false.
- It costs about half a first review. On the four repos it was not designed from, it added one known drift, while a gap pass added three. Its other finds were differences no general pass had made, such as NULL against an empty string in negative filters on one database only.
- So it is offered as an optional pass after the gap passes, not in place of one. One run each, and runs vary by about a drift.

## How the numbers moved

mattpocock/skills, four runs on the same snapshot:

| Run | Known drifts caught | What changed before it |
|---|---|---|
| 1 | 3 of 7 | the first version |
| 2 | 5 of 7 | the scan matches doc lists, reads git history, and the reviewer hunts for descriptions of things defined elsewhere |
| 3 | 5 of 7 | fixes from four earlier runs' feedback |
| 4 | 7 of 7 | the reviewer checks that a description's list of steps or users is complete, not only true |

Runs 2 and 3 missed the same two drifts. Both were lists that were true but left items out: a skill's steps without its first step, and one skill's users without three of the others. The rule added for run 4 was written after seeing those misses, so run 4 shows that the rule works on this repo, not that it works on every repo. The skill split and a rewording of the briefs went in at the same time.

uptime-kuma, two runs: both caught 2 of 3 known drifts. Both missed a date that one code path wrote with `toISOString()` while the rest of the server used the repo's SQL date format. The second run did not record that seam at all. The scan now has a lead for this shape: a named date format, and a file beside its users that writes dates another way. A third run had that lead and still missed the drift. The reviewer opened the right file and recorded a different date problem there. That run also lost a drift the first two caught, so it caught 1 of 3: one run per version varies by about a drift either way.

## What the runs found beyond the keys

- On mattpocock/skills, an early run claimed 16 drifts. The maintainer later fixed 10 of them himself, without the tool. None was a clear false alarm. Run 3 also found a skill that hands off to a skill only a user can start. The maintainer later fixed that too.
- On uptime-kuma, the first run found that one public endpoint lacked an access check that its sibling endpoints had. The project later fixed exactly that, in a private security advisory. The runs also caught a notification provider that had read the wrong field name for 15 months, a push message whose text said the opposite of its title, two translation keys the edit page used but never defined, and a translation tool that pointed at a deleted folder. The project later fixed each one.

## Read these with care

- One run per version. Runs vary: on a third, private repo, two full reviews each found seams the other missed.
- The answer keys are incomplete, and the person who built them also graded the seam matches. The drift counts are firmer: each rests on a commit the maintainers made later.
- Costs are for the whole workflow: setup, one reviewer, the drift check and the notes. Before 2026-11-16 this page added up the cost each resumed turn of a session reported, but that figure is the session's running total, so runs of more than one turn showed up to 1.9 times their real cost. The figures here are corrected.
