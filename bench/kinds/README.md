# Benchmark kinds

A kind is one question about seamreg, with its own way to answer it. Each kind is a folder here. The core
scripts in [bench/](../README.md) give every kind the same workspace, the same blind session, the same
blindness scan and the same result file, so results from different people can be compared and added up.

## The kinds

| Kind | The question | Status |
|---|---|---|
| [detection](detection/README.md) | Run blind on an old snapshot, does seamreg record the seams and the drifts that the maintainers fixed later? | Ready |
| prevention | Replay real commits that missed a copy: does an agent with seamreg update every copy? | We run it privately. Its per-task check scripts are not packaged yet. A port is welcome. |
| forward | Replay a repo's changes in order, carrying the registry: does it keep up over time? | Private, as above |

## Add a kind

Make a folder `bench/kinds/<name>/` with:

1. **README.md**, which states:
   - the question the kind answers, in one sentence,
   - how to pick a repo and a snapshot for it, decided before anyone looks at the repo's seams,
   - the steps, as commands a session can follow,
   - the shape of its `measures`: every field, and what counts,
   - what a submission adds to the common files, and what it must leave out,
   - its limits: what a good score would and would not show.
2. **Prompts and briefs** for its sessions. A prompt for a blind session may use `@TOOL@` and `@WORK@`,
   and must ask the session to end with the line `RUN COMPLETE`.
3. **Scripts**, if it needs them (a per-task check, a scorer). Keep them inside the folder.

The rules every kind keeps:

- **Use the core for the blind part.** Make the workspace with `snapshot.sh`. Run every session that
  uses seamreg through `session.sh`, and check each one with `blindscan.py`. A kind that needs several
  snapshots (one per task, say) makes several workspaces.
- **The ground truth comes from outside the run:** later upstream commits, a test that passes or fails,
  a person's reading written down before the run. Never from the run's own output.
- **Write `measures.json` in `<session>/grade/`,** so `result.py` can assemble the result. Use counts with a
  `total` where you can (`{"total": 8, "caught": 3}`): `table.py` shows those as "caught 3/8".
- **Say what was tuned on what.** If the kind, or the seamreg change it tests, was designed by looking at
  a repo, a result on that repo counts for less. Mark it in the submission.
- **No answers in the tool.** Nothing in `skills/`, `agents/` or the briefs in `src/seams/` may point at
  `bench/` or name a benchmark repo's known drifts. A test checks this.

A new kind can go in with its first result. Open the pull request with both, and say in it why the
question matters.
