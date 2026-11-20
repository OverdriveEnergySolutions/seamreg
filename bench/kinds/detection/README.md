# Detection

**The question:** run blind on an old snapshot of a public repo, does seamreg record the seams and the
drifts that the repo's maintainers fixed later?

A drift that the maintainers fixed is proof that it was real and that it mattered, so nobody has to judge
the tool's findings by taste. The score is how many of those drifts the blind run stated.

## Pick the repo and the snapshot

Pick them before you look at the repo's seams, and write down why.

- A public repo of 500 to 3,000 tracked files. Larger works, but costs more.
- A snapshot 4 to 12 months old, with many fix commits after it. 300 or more later non-merge commits is
  a good sign.
- Prefer a snapshot after the reviewing model's training cutoff, so the model cannot remember the fixes.
  If you cannot, say so in the submission.
- A stack or kind of repo the published results do not cover yet is worth more than another web app.

## Steps

Run these from an ordinary Claude Code session. First set two names: `SEAMREG`, the folder of your seamreg
clone, and `WORK`, a new folder on a real disk outside your home folder.

```sh
export SEAMREG=/path/to/seamreg WORK=/srv/bench/owner-repo
```

1. **Make the workspace.**
   ```sh
   "$SEAMREG/bench/snapshot.sh" <repo url> <snapshot commit> "$WORK"
   ```
   Check the line it prints: the blind clone holds no later commit, and the window holds the fixes.

2. **Build the answer key,** in its own session, before the blind run:
   ```sh
   cd "$WORK" && claude -p "Follow $SEAMREG/bench/kinds/detection/key-brief.md. Your workspace is $WORK." --permission-mode auto
   ```
   Or start an interactive session in `$WORK` and give it the same sentence. Read `key/key.md` when it is done. A key with fewer than 5 drift rows is weak: pick
   another snapshot or repo, or go on and say so.

3. **Run seamreg blind:**
   ```sh
   MODEL=claude-sonnet-5-5 EFFORT=max "$SEAMREG/bench/session.sh" "$WORK" detection "$SEAMREG/bench/kinds/detection/prompt.md"
   ```
   It answers the review's cost question with yes, so it starts the review without asking you. It saves
   to `$WORK/detection/`. Read `summary.json`: `complete` must be true.

4. **Check the blindness scan:**
   ```sh
   python3 "$SEAMREG/bench/blindscan.py" "$WORK" detection
   ```
   Read every hit (see [bench/README.md](../../README.md), step 5).

5. **Grade,** in a new session:
   ```sh
   cd "$WORK" && claude -p "Follow $SEAMREG/bench/kinds/detection/grade-brief.md. Your workspace is $WORK." --permission-mode auto
   ```
   It writes `detection/grade/grading.md` and `detection/grade/measures.json`.

6. **Assemble the result:**
   ```sh
   python3 "$SEAMREG/bench/result.py" "$WORK" detection detection
   ```

## Measures

```json
{
  "key_seams": {"total": 0, "full": 0, "partial": 0},
  "key_drifts": {"total": 0, "caught": 0, "partial": 0},
  "claims_graded": {"sampled": 0, "of": 0, "fixed": 0, "present": 0, "wrong": 0, "unclear": 0, "wrong_detail": 0}
}
```

`key_drifts.caught` is the headline. `claims_graded` says how far to trust the rest of what the run
claimed: a WRONG claim is a false alarm, and FIXED claims are real drift the key did not list.

## What to submit

The common files (see [bench/README.md](../../README.md#submitting-a-result)), plus `key/key.md`, any
rule scripts in `key/`, and `detection/grade/grading.md`.

## Limits

- One run. Runs of the same version vary by about one known drift.
- The key holds only drifts someone fixed. A run can find real drift nobody fixed yet: the PRESENT claims.
  They count for the tool, but do not show in the headline.
- Key seams are matched by reading, so two graders can differ by a seam or two. Drift counts are firmer,
  because each rests on a commit.
