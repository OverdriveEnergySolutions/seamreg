---
name: seams-review
description: Build or refresh a repo's seams registry (seams.json) with a full review. It scans the repo, runs reviewer agents, merges their findings, checks the copies for drift and writes the notes agents read. A review costs hundreds of thousands to millions of tokens, so use this only when the user asks to find a repo's seams, to build a seams registry, or to re-scan one with reviewer agents. For lookups and checks in an everyday change, use the seams skill.
---

# Seams review

A **seam** is one piece of knowledge kept in two or more files that must agree. A **tie** is an automated check that fails when the copies drift. The `seams` skill holds the full definitions, the commands and the rules for entries. Read it first.

This workflow spends real money: one reviewer agent per packet, and one drift checker per seam. Steps 3 and 6 show the user the cost and wait for a yes. Never skip them.

## Workflow

1. In the target repo, run `seams init`. Add the snippets under "Add these now": the CI workflow, the Claude Code hook, and the commit check. The printout says where the commit check goes in this repo. If the repo has no commit-hook setup, skip that item and tell the user: a file in `.git/hooks/` reaches only one clone. Leave the "After the first review" items for step 10.
2. Run `seams scan`, then `seams split`. The output folder, `.seams-scan/`, ignores itself in git. Nothing in it gets committed.
3. Read `.seams-scan/plan.md`. **Show the user the packet count, the cost at each effort level, the wall time and the "Not scanned" list. Get a yes before you start any reviewer.** Measured on one 2,200-file repo against a 150-seam reference registry, with a judge checking that each match records the same knowledge: two max-effort runs recorded 49% and 44% of the reference seams (70% and 65% with partial matches), for about 620k tokens per packet. One high-effort run recorded 36% (56%), for about 320k. Runs vary: each max run found seams the other missed, and the two together reached 59%. So one review finds about half the seams, and a second max run adds about 10 to 15 points. Use max for a first review. High is enough for a re-scan.
4. Start one `seam-reviewer` agent per packet, in parallel, at the effort level the user chose. In Claude Code, set it with the Agent tool's effort setting. Give each one only the path of its packet file. The packet and the brief hold everything else. Each reviewer's token use arrives in its completion notice, not in its reply. Without a `seam-reviewer` agent (outside Claude Code), start an ordinary sub-agent per packet with this prompt: "Read `<packet path>`, then the brief it names, and follow the brief exactly." If you cannot start sub-agents, review the packets one at a time yourself, the same way. The same applies to `seam-drift-checker` in step 6.
5. When every reviewer is done, run `seams merge`. Read `.seams-scan/merge-report.md` and settle each section:
   - **Possible duplicates** come in clusters. Read each entry's title and `must_agree`. Two entries can share files and still be different knowledge. In a plan file, use `{"absorb": {"dupe-id": "keep-id"}}` to join, or `{"distinct": [["id-a", "id-b"]]}` to keep both. A `distinct` list can hold a whole cluster, and the report prints that line for each cluster. Each pair says how many of each entry's copies it shares: a pair that shares 1 of 6 and 1 of 11 is rarely one seam. An absorb can expose a new pair, so merge again after each plan change. Pairs that share only hub files need no decision, unless the cluster says their copy lists are nearly the same.
   - **Entries skipped**, **Fields dropped**, **Copies dropped**, **Symbols dropped**, **Seams dropped** and **Ties dropped:** each line says why. A dropped tie whose test name is not in the file usually names a description instead of a function. Fix the name in the review file and merge again.
   - **Ties kept without CI evidence**, and ties dropped because CI does not run them: open the CI config and settle each claim. A wrong "CI never runs it" once slipped through a review.
   - **Security findings:** the report shows every text field of the entry. Make sure each one names the difference without the impact. Write the consequence as the behavior that differs ("one route applies a different visibility rule"), not what an outsider can get. In a public repo with the hole still open, leave the route or file out of the drift text too, and keep it in the private file. The detail belongs in `private-findings.md` only.
   - **High-risk drift to confirm first:** this drift comes from reading code, not from running it. Read both sides, then pick one:
     - The copies differ as stated, and nothing in the code marks the difference as deliberate: add the id to `"confirm"` in the plan.
     - The substance holds, but a detail is wrong, such as a line number: fix it in the review file, then confirm.
     - The code marks the difference as deliberate (a comment, a retired table): move it from `drift` to `intentional_differences` in the review file, and merge again.
     - The difference is temporary or explained, such as a version bumped ahead of a pending release: confirm it, and add that context to the drift text in the review file, so nobody "fixes" the wrong side.

     Confirmed means "the copies differ as stated". It does not mean "this is a bug". That needs a runtime check or the owner's word. Confirmed ids leave this section.
   - **Drift the entry also calls deliberate:** the drift and the deliberate differences name the same file. If they describe one difference, keep it in one field.
   - **Joined entries to read again:** a join keeps one entry's title, `must_agree` and consequence. Fold in the absorbed `must_agree` where the kept text no longer explains the absorbed copies. Remove a text that now says one thing twice. A full tie becomes partial when the join adds copies it never checked. Set it back to `all` only if it checks every copy.
   - **Text to rewrite in a neutral voice:** each line names the word it matched. Keep a word used in its domain sense, such as a ping "packet". Fix the rest in the review files, or in `seams.proposed.json` and then use `seams apply`.

   - **Bugs outside the seam format:** bugs a reviewer found that are not a difference between copies. They do not go into `seams.json`. List each one for the user in your final report, with its path:line. A sensitive one is in `private-findings.md`.

   The report ends with the sections it checked and found empty.
6. Run the drift check. Full reviews often record a seam but miss that its copies already differ: two max-effort reviews caught 2 of 5 known bugs between them. Run `seams verify --registry .seams-scan/seams.proposed.json`. It checks every high- and medium-risk seam with no drift recorded: a medium seam once held a confirmed bug that two full reviews missed. It also checks every convention seam with no drift, at any risk: its rule covers many members, and a reviewer may have checked only some. If more than about 20 qualify, add `--sample 20 --seed S`: it takes high-risk seams first, fills the rest with medium ones at random, and prints which. Each run replaces the packets of the one before. It prints the packet count and the measured cost. Show the user both, and on a yes start one `seam-drift-checker` agent per packet, at default effort. Then run `seams verify --collect --registry .seams-scan/seams.proposed.json` and read `.seams-scan/verify/verify-report.md`. For each new drift, read both sides, as in step 5. List the ids that hold as stated, and pass them in the next step as `seams apply --confirm <id,id>`. A plan cannot confirm them: a merge rebuilds the proposal and drops the drift check's results.

   Drift found by reading on medium- and low-risk seams gets no hand check in step 5. To get a second opinion on it, run `seams verify --reading --risk high,medium,low`. Its packets do not show the recorded drift. The report then says, for each seam, whether the checker saw a difference too. It changes nothing in the registry.
7. Write the result. `seams merge --plan <file> --apply` rebuilds the proposal and writes `seams.json`. If you edited `seams.proposed.json` by hand or ran the drift check, run `seams apply` instead, with `--confirm` for the drift you checked, or the merge throws those changes away. Both write only when the result passes the check, and both record the shown leads in `seams.baseline.json`. Commit both files.
8. If `.seams-scan/private-findings.md` or `.seams-scan/verify/private-findings.md` exists, tell the user. It holds security detail that must stay out of the repo. Each such seam has a `sensitive` placeholder in `seams.json`. The user files the detail somewhere private and replaces the placeholder with a pointer to it.
9. The rule "a fix for drift ships with a tie for that seam" needs one home. The planning text in step 10 states it. If the repo has a review checklist (`REVIEW.md`, review guidelines, a pull request template), write the rule there, and change the planning text's paragraph that starts "If you fix drift" to a pointer to it. Otherwise the planning text is the rule's home.
10. Do the "After the first review" items from the `seams init` printout:
   - Notes: set `"notes"` in `seams.json`, run `seams notes`, and commit the result. Pick a value for each kind of agent that works in the repo. Use a list for more than one: `["rules", "cursor"]`. Look for `.claude/`, `.cursor/rules/`, `.github/copilot-instructions.md` or `.github/instructions/`, and `AGENTS.md`, and ask the user which agents they use.
     - `"rules"` (Claude Code), `"cursor"` and `"copilot"` write one file per seam. Each costs nothing until a copy is opened. `"rules"` needs `.claude/rules/` in git. If the repo ignores `.claude/`, `seams notes` prints the lines that replace that ignore line: they also keep the step 1 hook file in git.
     - `"claude-md"` and `"agents-md"` add blocks to CLAUDE.md or AGENTS.md files, which load widely. For a large registry, use `"claude-md-high"` or `"agents-md-high"`.
     - `seams notes` prints the words the notes hold. Tell the user. Copies written as broad globs (`docs/**/*.md`) make most files load a note.
   - Planning: paste the planning text into the instruction file the repo's agents read: `CLAUDE.md`, `AGENTS.md` or `.github/copilot-instructions.md`. If the repo has none, ask the user which to create. Planning agents then ask the registry before they commit to a plan: `--about "<topic>"` first, then `--changed <planned files>`.
   - The CI workflow, the hook and the planning text all name the checker's path. If the review recorded that as a seam, add each new file as a copy.

## What to run next

`seams next` ranks the candidate next steps, each with its reason and cost: settle a merge, the drift check, the next gap pass (or the stopping rule), focused passes whose leads exist, a second opinion on drift found by reading, triage and ties. Each `seams split` adds the pass to `.seams-scan/passes.json`, so `seams next` also shows what every earlier pass added. Run it after each merge and show the user its list. `seams triage` lists the drift worth fixing first: confirmed drift ahead of drift found by reading, then by risk. A merge prints a short form of it.

## Gap passes: plan for three passes

One review finds about half of a repo's seams, and a second blind review spends much of its effort finding the same ones again. A gap pass hunts only for what the earlier passes missed. Measured on four public repos with known drifts, the share caught rose from 33% after a first review to 44% after one gap pass and 52% after two. The second gap pass still caught a known drift on two of the four, at about three quarters of a first review's cost. So after step 7, tell the user that a first review plus two gap passes is the measured starting point, and offer the first gap pass. Stop early when a gap pass adds no new high-risk seam and no new drift.

1. Run `seams split --gap`. It moves the earlier passes' review files and drift-check results into `done/` folders, because their seams are already in `seams.json`. Each packet lists the seams `seams.json` already records in its areas, and tells its reviewer to find the ones the list misses, including a second seam in a file the list names. A lead stays in unless one recorded seam names every one of its files by path: a glob copy does not hide a lead.
2. Show the user the packet count and the cost from `plan.md`, and get a yes. A gap packet costs about what a first-pass packet costs.
3. Start one `seam-reviewer` per gap packet, at max effort, as in step 4.
4. Run `seams merge` and settle the report as in step 5. Entries already in `seams.json` stay as they are unless a plan says otherwise. A new copy of a recorded seam shows under the section for existing seams, and drift a reviewer found on a recorded seam shows under "Drift found on seams already in seams.json". `"extend"` in a plan adds either one: it adds the copies, and it adds the drift, or appends it to drift already recorded.
5. Run the drift check on the new seams. The new seams are in the proposal until you apply it, so name it: `seams verify --registry .seams-scan/seams.proposed.json --ids <id,id>`, with the new high- and medium-risk seams and the new convention seams that have no drift. Show the user the count and the cost, and on a yes start one `seam-drift-checker` per packet. Then run `seams verify --collect --registry .seams-scan/seams.proposed.json`, read the report as in step 6, and run `seams apply --confirm <id,id>` for the drift that holds. Then `seams notes` if the registry sets notes.
6. The private findings files keep what earlier passes wrote, so step 8 applies to the whole file again.

## Focused passes

A focused pass hunts one kind of seam across the whole repo, with one reviewer that reads what the leads of that kind and its own searches point at. So it costs well under a full packet. It adds to the general passes and replaces none of them. The kinds:

- `twins`: two implementations of one behavior, such as a parser in the server and its copy in the client, two patterns for the same input, or one query per database. The reviewer tests each twin on edge-case inputs.
- `siblings`: classes that share a base class or mixin, and their counterparts in other layers (forms, serializers, filters, tables) named after each one. A field of the base that one sibling's counterpart carries and another's lacks is drift. The reviewer builds a table of layers and siblings. Its leads are under "Classes that share a base" in `leads.md`. Not measured yet.
- `open`: no fixed rule. The reviewer reads the repo, writes its own guesses about where copies hide, and tests each one across the repo with a short script. Its packet lists the recorded seams, the passes already run, and which folders earlier reviewers opened (from `seams looked-at`, which reads the earlier sessions' transcripts). Offer it after the fixed kinds, when the user wants to look further. Not measured yet.

Offer a focused pass after the gap passes, as an option and not in place of one, when `leads.md` lists leads of its kind ("Two implementations of one behavior"). Say how many there are. Measured on five public repos, one twins pass cost $21 to $29, and none of its 76 graded claims was false. It found differences the general passes had not, but it added a known drift on only one of the four repos it was not designed from.

`seams next` lists each focused pass whose leads the scan found, with the count. Offer the ones it lists.

1. Run `seams split --focus <kind>`. Like a gap pass, it needs `seams.json` and moves the earlier passes' review files and drift-check results into `done/` folders. Its one packet lists every recorded seam and the leads of its kind.
2. Show the user the lead count and the cost from `plan.md`, and get a yes.
3. Start one `seam-reviewer` on the packet, at max effort.
4. Settle the merge, run the drift check on the new seams, and apply, as in steps 4 to 6 of the gap passes.

## Re-scans

When the repo already has `seams.json`, do not run a full review again. Run `seams scan --new`, then `seams split --new-only`. Show the user the lead count from `plan.md` and get a yes. The cost of a lead-only review is not measured at scale yet, so start one packet first and report its token use before you start the rest. Then run the reviewers, settle the report, and apply.

If the repo was reviewed before it had a baseline, run `seams scan` and then `seams baseline` once.

Without reviewer agents, you can still read `.seams-scan/leads.md` yourself and write entries by hand. Follow the rules for entries in the `seams` skill.

