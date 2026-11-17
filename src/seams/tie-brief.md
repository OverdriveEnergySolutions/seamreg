# Seam tie brief

You write one tie for one seam. A seam is one piece of knowledge kept in two or more files that must agree. A tie is an automated test that fails when those copies disagree. Your packet names the repo root, the seam, its copies, the repo's test frameworks and your output file.

Today nothing fails when these copies drift: someone has to remember them. Your test makes the build remember.

## What a good tie does

- **It reads the copies where they live.** Import the module, parse the file, or read it as text. Never restate a copy's values inside the test: a test that holds its own list of status names is a third copy, and it passes while the real two drift apart.
- **It compares what "must agree" names, and only that.** Allow the deliberate differences the packet lists. Do not test behavior beyond the seam.
- **It fails with a message that says what differs**: the item one side has and the other lacks, and both file names.
- **It runs fast and alone**: no network, no database, no service, no build step the repo's tests do not already need. If the only possible check needs one of these, write no test and say so (see "No tie").
- **It lives with the repo's other tests** and looks like them: same framework, folder, file names, imports and assertion style. Read two of the nearby test files the packet lists before you write.

How to compare, by kind of seam:

- A list, map or enum in two places: load both, compare as sets, and report the items on each side only.
- A format or a rule two code paths apply (two implementations of one behavior): run both on the same table of inputs, including edge cases (empty, the longest value and one more, letters outside ASCII, separators, wrong case), and compare the outputs. When the two copies are in different languages, test in one language and read the other file as text, or extract its literal (a pattern, a list) with a narrow regex that fails loudly when it finds nothing.
- A doc that describes code (a README list, a help text, a config reference): parse the doc's list or table and compare it with the source of truth.
- A schema and its users (a migration and a model, an API spec and a handler): compare the field names and types each side declares.
- A convention (every member of a family follows a rule): enumerate the members the way the copies' globs do, and check each one. A new member that breaks the rule must fail the test.

A regex or a parse that silently matches nothing makes a test that always passes. Assert that each side yields at least one element before you compare.

## Prove it

1. **Run the test** with the repo's own command for one test. It must pass. If the seam records drift (the packet says so), it must fail now, and its message must name that drift. Then mark it as an expected failure in the framework's own way, with the reason "seam <id>: known drift, remove this marker when the copies agree": `@pytest.mark.xfail(strict=True, reason=...)`, `it.fails(...)` in vitest, `test.failing(...)` in jest, `t.Skip(...)` in Go, `@Disabled(...)` in JUnit. Prefer the strict forms: they fail once the drift is fixed, so the marker cannot be forgotten. Do not fix the drift.
2. **Break each copy, one at a time**, and run the test again. Make the smallest change that makes the copies disagree: add an item to one list, rename a key, change a limit. The test must fail. Then restore the copy exactly (`git diff -- <copy>` must show nothing) before you break the next one. Break at least two different copies; for a convention, add or change one member so it breaks the rule.
3. **Leave the repo clean except for the test.** `git status` shows only the files you wrote for the tie. If the test needed a small helper or fixture, it counts as written too.

If you cannot run the tests (dependencies not installed, no permission to run them), do not guess. Write the test, set `passes` to false, leave `mutations` empty, and say what blocked you in `reason`. It will not be added to the registry until someone runs it.

## No tie

Some seams cannot get a cheap, honest test: the copies are a running service's config and a remote system, or the knowledge is a judgment call in prose. Then write nothing in the repo, set `path` to null, and say in `reason` why, and what check would catch the drift instead (a CI step, a lint rule, a review checklist line).

## Stay inside the repo

Read and write only under the repo root, plus your packet, the brief and your output file. Skip `seams.json`, `.seams-scan/` and the notes the seams tool writes: they say what others concluded, and the test must stand on the code.

## Output

Write one JSON object to your output file:

```json
{
  "id": "order-status-names",
  "path": "tests/test_status_parity.py",
  "test": "test_status_names_match",
  "covers": "all",
  "note": null,
  "command": "pytest tests/test_status_parity.py::test_status_names_match",
  "passes": true,
  "expected_failure": false,
  "mutations": [
    {"copy": "api/orders/status.py", "change": "added 'lost' to STATUSES", "failed": true},
    {"copy": "web/src/orders/status.ts", "change": "removed 'returned' from STATUS_NAMES", "failed": true}
  ],
  "files_written": ["tests/test_status_parity.py"],
  "reason": null
}
```

- `path`, `test`: the test file and the test's name as it appears in the file (for a class method, `Class.method`). `path` null when there is no tie.
- `covers`: `all` when the test reads every copy the packet lists, `partial` otherwise. With `partial`, `note` says which copies it reads.
- `command`: the command that runs only this test.
- `passes`: true when the test passes on the repo as it is now.
- `expected_failure`: true when you marked it as an expected failure because of the recorded drift.
- `mutations`: every copy you broke, what you changed, and whether the test failed. Only real runs.
- `reason`: anything the person should know: why there is no tie, what blocked a run, a copy the test cannot reach.

## Final reply

One line: the seam id, the test file and name (or "no tie"), and the output path.
