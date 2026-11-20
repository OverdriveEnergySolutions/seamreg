# Build the answer key

You are building the answer key for a blind benchmark of seamreg, a tool that records "seams": one piece
of knowledge kept in two or more files that must agree (a list of event names, a field set kept in a
schema and a form, a payload shape, a setting's default, a copied helper). If one copy changes alone,
something breaks.

The key lists the seams that existed at a snapshot commit and, above all, the **drifts**: places where
the copies already disagreed at the snapshot, and a later upstream commit fixed the disagreement. Those
later fixes are the ground truth. They make the key fair: nobody has to guess what counts.

## Where things are

Your workspace is the folder that holds this run's `bench.json`. Read `bench.json` first: it gives the
repo, the snapshot commit and its date, and the newest commit (the end of the window).

- `full/` is a clone with the whole history. Use it read only: `git log`, `git show`, `git grep`,
  `git merge-base`. Never check out, commit or edit there.
- Write your output in `key/`, and nothing anywhere else.
- **Do not read `blind/`, `tool/`, or any session folder** (such as `detection/`). They belong to the
  blind run. Do not use the seams tool.

## Method

1. List the window's commits that fix something: every non-merge commit after the snapshot, by message,
   pull request title and diff. Fixes may arrive through merge commits, so read the merged commits too.
   Skip dependency bumps and formatting.
2. For each fix, ask: did it bring one copy of shared knowledge back in line with another? If it did,
   read both sides at the snapshot with `git show <snapshot>:<path>`, and confirm they disagreed there.
3. Check that the fix is not already in the snapshot: `git merge-base --is-ancestor <fix> <snapshot>`
   must fail.
4. Write the seam and its drift row.
5. Also list the important seams that held at the snapshot, with no drift, so recall can be scored. Keep
   the focus on drifts.
6. Where a rule can be checked mechanically at any commit, you may add a small script in `key/` that
   counts its violations. Run it at the snapshot, at the fix's parent and at the fix.

Aim for 15 to 25 seams and 8 or more drift rows. A key with fewer than 5 drift rows is weak: say so.

## Output: key/key.md

1. **Opening.** The repo, the snapshot and its date, the window's end and its date, the number of
   commits in the window, how many fixes you read, and the counts of seams and drift rows.
2. **One section per seam,** with an id in kebab-case, then: what must agree, the copies (file and
   symbol), the risk (high, medium or low, as below), and any test that ties the copies today.
3. **The drift table,** one row per drift: a row number, the seam id, what differed at the snapshot
   (both sides, with file and line at the snapshot), the fixing commit and its date. Give the commit date
   as `git log -1 --format=%cs <commit>` prints it.
4. **Not counted.** Fixes you read and rejected, one line each with the reason. Probable drifts you could
   not confirm, marked "unverified".

Risk: **high** when drift silently gives wrong results, loses data, or opens a security gap. **medium**
when drift causes a visible bug. **low** when it is cosmetic or caught fast.

A drift that touches security (sign-in, access checks, secrets) goes in the key as usual, because its fix
is public. Do not describe security problems that are still open at the window's end anywhere.

## Final reply

The counts, the drift rows in one line each (seam id, fix commit, date), and anything unverified.
