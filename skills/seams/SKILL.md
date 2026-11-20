---
name: seams
description: Use a repo's seams registry (seams.json), the list of knowledge kept in two or more files that must agree. Before you plan or edit, ask it which other files hold copies of what you will change. Before you finish, check which copies the change left alone. When you fix drift between copies, fix every copy first; a tie is a follow-up. Use when the repo has seams.json, when a change touches a shared list, map, rule or payload shape, or when a bug came from one copy changing alone. To build a registry with a full review, use the seams-review skill.
---

# Seams

A **seam** is one piece of knowledge kept in two or more files that must agree. If one copy changes alone, something else breaks, often with no error. (This is not Michael Feathers' seam, a place to change behavior without editing the code there. Other skills may use the word that way.) Repos built one feature at a time by separate agent sessions grow seams fast. Each session copies what it needs, and a later change reaches only one copy.

A **tie** is an automated check that fails when the copies drift: a test, or a script that CI runs.

Pick the cheapest rung that holds:

1. **Note.** The registry records the seam, so an agent sees it before it edits a copy.
2. **Tie.** A test fails on drift.
3. **Single source.** One shared module that every side imports. Then there is nothing to tie.

The registry does not force a refactor. It records coupling and catches drift. Structure grows where something broke: every drift fix ships with a tie.

## What is built (0.1)

- `seams init` copies the checker into the repo at `scripts/seams_check.py`, starts an empty `seams.json`, and prints the setup snippets.
- `seams check` fails when `seams.json` no longer matches the repo. With `--changed`, `--staged` or `--diff`, it lists the seams a change touches and the copies it left alone. With `--about`, it lists the seams on a topic, for planning.
- `seams scan` finds candidate seams without an agent.
- `seams split` groups the repo into packets, one per reviewer agent, with a cost estimate. `--new-only` and `--cross-area-only` make a lead-only review.
- `seams merge` checks the reviewers' claims and proposes registry entries. `seams apply` writes an edited proposal as it stands.
- `seams verify` gives each high- and medium-risk seam with no drift recorded to a `seam-drift-checker` agent, which compares the copies and the ties. `seams verify --collect` writes what they find.
- `seams tie <id>` gives a seam to a `seam-tie-writer` agent. The agent writes a test in the repo's own framework that fails when the copies disagree, and proves it: the test passes, and it fails when each copy is broken in turn. `seams tie --collect` adds each proven test to the seam's ties. `--untied` picks every high- and medium-risk seam with no full tie.
- `seams baseline` records which leads a review saw, so a re-scan treats them as old.
- `seams notes` writes a note for each seam where agents read it.
- `seams schema` prints the registry's JSON Schema.

## Use the registry in a change

Use `python3 scripts/seams_check.py` (the copy `seams init` put in the repo) or the `seams check` command. Both read only `seams.json` and the file names, so they are fast.

1. **Before you plan.** If you do not know the files yet, run `--about "<topic>"`. Once you know the files you expect to touch, run `--changed <files>`. Put every copy it names into the plan, or say in the plan why that copy must differ. A seam with known drift says so: decide which side is right before you edit either.
2. **Before you finish.** Run `--staged`, or `--diff <base branch>` on a branch. If it names a copy you left alone, update that copy or say why it must differ.
3. **When you fix drift between copies,** fix every stale copy first. Never leave a copy stale because it has no tie. A tie (a test that fails when the copies differ) is a good follow-up: add one in the same change if it is cheap, or suggest it to the user. Then list the tie in the seam's entry, or add the seam to `seams.json` if it is not there. To have an agent draft it, run `seams tie <id>`, start one `seam-tie-writer` agent on the packet it names, then run `seams tie --collect`. Read the test it wrote like any other code before you commit it.
   **When you find a copy no seam lists,** add the seam to `seams.json` in this change, even if you leave that copy alone and only mention it in your reply. The next change reads the registry, not your reply.
   If no seam listed those copies, the registry missed them. Run `seams report-miss --changed <file> --missed <file> --rule "<what had to agree>"`, and give the shape in general words with `--summary`. Tell the user what it printed: shared with the seamreg project, it helps the tool learn that shape. For a private repo the shared text holds only the shape, never a path, a commit or code.
4. **Before you open a pull request,** run `seams scan --since <base branch> --new`. It uses no agents. Any lead it lists may be a seam this branch created. Check each one, and add the real ones to `seams.json` in the same pull request.

After you edit `seams.json`, run the plain check, and `seams notes` if the registry has a `"notes"` setting. The check fails in CI when the notes fall behind.

The CI step for pull requests only warns at first. It posts one comment on the pull request, and edits it on each push. Add `--fail-untied` when most seams have a full tie. Until then it fails most pull requests that touch a seam.

## Rules for entries

- **One seam per piece of knowledge, not per file pair.** Group every copy of the same knowledge into one entry.
- **A copy is a file or a glob.** A folder is not a copy. Write `dir/**/*` instead. Knowledge repeated inside one file is out of scope: the registry cannot hold it.
- **Name a symbol, not a line.** Line numbers go stale. A symbol is text that must appear in the file, and the check verifies it.
- **A tie names one test.** Its `test` is a function name, or `Class.method`, that appears in the tie's file. For a runner that names a test by a string (Playwright, Jest, RSpec), the name is that string.
- **Record deliberate differences** in `intentional_differences`, so nobody "fixes" them.
- **A tie needs evidence.** Quote the assertion that fails on drift. If CI does not run the test, it is not a tie.
- **Drift found by reading is a lead.** In `seams.json`, set `drift.source` to `reading`. Use `confirmed` only after a check that the copies differ as stated.
- **No exploitable detail.** If drift is a security hole, describe it somewhere private and put a pointer in `sensitive`. The drift text names the difference, not how to exploit it.
- **Neutral voice.** No "I ran", no scratch-file paths.
- **Keep the id stable.** Other tools key on it.

## Never claim the registry is complete

`seams check` proves that every listed copy still exists. It cannot find a copy that nobody listed. Say so wherever the result is reported.

