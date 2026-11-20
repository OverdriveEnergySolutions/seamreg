# Grade a detection run

You are scoring a blind seamreg run against an answer key. The run recorded seams in a registry. The key
lists the seams and the drifts a later upstream fix proved. Score what the run recorded, and check a
sample of what else it claimed.

## Where things are

Your workspace is the folder that holds this run's `bench.json` (the repo, the snapshot, the window).

- `key/key.md` is the answer key.
- `detection/results/seams.json` is the run's registry. `detection/results/seams-scan/` holds its
  reviewer output and reports.
- `full/` is the full-history clone, read only (`git show <commit>:<path>`, `git log`, `git grep`).
- Write only `detection/grade/grading.md` and `detection/grade/measures.json`.

## 1. Key seams

For each seam in the key, find the run's entries that cover it.
- **full**: one entry, or a few entries together, list the copies the key seam's rule lives in, and its
  must_agree states the same rule.
- **partial**: the run recorded part of it: some of the copies, or a narrower rule.
- **missed**: nothing in the run covers it.

## 2. Key drifts

For each drift row in the key, decide whether the run **stated** it: an entry's `drift`, or a bug entry,
describes the same disagreement on the same copies.
- **caught**: the run states the disagreement the fix later removed.
- **partial**: the run states a related disagreement on the same copies, or only part of it.
- **missed**: otherwise. A seam recorded without the drift is a miss for this score.

## 3. Other claims

Take the run's drift claims and bug entries that match no key row. If there are more than 20, take 20 at
random and say how you picked them. For each one, read both sides at the snapshot, and again at the
window's end, and give one verdict:
- **FIXED**: true at the snapshot, and changed later so the copies agree.
- **PRESENT**: true at the snapshot, and still there at the window's end.
- **WRONG**: false at the snapshot.
- **UNCLEAR**: you cannot tell from the code.
Also count claims that are true but carry a wrong detail (a wrong line, a wrong value on one side).

## Output

`grading.md`: a table per step, one row per key seam, key drift and sampled claim, each with a
one-sentence reason. For a PRESENT claim, give the verdict and the seam id only. Do not describe it:
that is an open bug in someone else's project. Leave out anything about security that is still open.

`measures.json`, exactly these fields:

```json
{
  "key_seams": {"total": 0, "full": 0, "partial": 0},
  "key_drifts": {"total": 0, "caught": 0, "partial": 0},
  "claims_graded": {"sampled": 0, "of": 0, "fixed": 0, "present": 0, "wrong": 0, "unclear": 0, "wrong_detail": 0}
}
```

`of` is the number of non-key claims the sample was drawn from. Read the file back and make sure it
parses.

## Final reply

The three scores in one line each, and every WRONG claim with its seam id.
