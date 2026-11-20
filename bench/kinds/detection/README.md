# Detection

**The question:** run blind on an old snapshot of a public repo, does seamreg record the seams and the
drifts that the repo's maintainers fixed later?

A drift that the maintainers fixed is proof that it was real and that it mattered, so nobody has to judge
the tool's findings by taste. The score is how many of those drifts the blind run stated.

## Pick the repo and the snapshot

Pick them before you look at the repo's seams, and write down why.

- A public repo of 500 to 3,000 tracked files. Larger works, but costs more.
- A snapshot 4 to 12 months old, with many fix commits after it. 300 or more later non-merge commits is
  a good sign, not a rule: what counts is the key. The first harness run had 114 later commits and still
  gave 17 drift rows.
- Prefer a snapshot after the reviewing model's training cutoff, so the model cannot remember the fixes.
  If you cannot, say so in the submission.
- A stack or kind of repo the published results do not cover yet is worth more than another web app.

## Steps

Run these from an ordinary Claude Code session. Each long step takes minutes to an hour, more than one
shell command may run in an agent's foreground: an agent should start each one in the background and
wait for it to finish. Keep your own notes beside `$WORK`, not in it, because the blind session can list
that folder. First set two names: `SEAMREG`, the folder of your seamreg
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
   "$SEAMREG/bench/task.sh" "$WORK" key "$SEAMREG/bench/kinds/detection/key-brief.md"
   ```
   About 10 to 30 minutes. It loads none of your own settings or MCP servers, and saves its cost in
   `$WORK/sessions/key.json`. Read `key/key.md` when it is done. A key with fewer than 5 drift rows is weak: pick
   another snapshot or repo, or go on and say so.

3. **Run seamreg blind:**
   ```sh
   MODEL=claude-sonnet-5-5 EFFORT=max "$SEAMREG/bench/session.sh" "$WORK" detection "$SEAMREG/bench/kinds/detection/prompt.md"
   ```
   About 30 to 90 minutes. It answers the review's cost question with yes, so it starts the review
   without asking you. It saves to `$WORK/detection/`. Read `summary.json`: `complete` must be true.

   **If it stopped early** (a usage limit, a crash, a lost connection), `run.log` says so, and the reason
   is in the last `turn*.json` (its `result` field), or in the `turn*.err` beside it. Fix the cause: for
   a usage limit, wait for the reset or log in to another account. Then run the same command with
   `RESUME=1` in front. It continues the same session with the same frozen tool, even if you updated
   seamreg since, and sends it "Continue where you stopped" with the same yes. The cost in
   `summary.json` stays the whole run's, and `resumes` counts the restarts. A session resumed on another
   login may see a notice about the account change: that is expected.

4. **Check the blindness scan:**
   ```sh
   python3 "$SEAMREG/bench/blindscan.py" "$WORK" detection --show
   ```
   Read every hit (see [bench/README.md](../../README.md), step 5). `--show` prints what each call
   returned, so you can tell a read of the key from a path named in a reply.

5. **Grade,** in a new session:
   ```sh
   "$SEAMREG/bench/task.sh" "$WORK" grade "$SEAMREG/bench/kinds/detection/grade-brief.md"
   ```
   About 5 to 20 minutes. It writes `detection/grade/grading.md` and `detection/grade/measures.json`.

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
rule scripts in `key/`, `detection/grade/grading.md`, and `$WORK/sessions/*.json` for the key and grading
costs.

## Limits

- One run. Runs of the same version vary by about one known drift.
- The key holds only drifts someone fixed. A run can find real drift nobody fixed yet: the PRESENT claims.
  They count for the tool, but do not show in the headline.
- Key seams are matched by reading, so two graders can differ by a seam or two. Drift counts are firmer,
  because each rests on a commit.
