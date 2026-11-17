# Seam review brief

You review one packet of a repo for seams. Your packet file names the repo root, your areas, your leads and your output file. Read this brief first, then the packet.

**Read only.** Your output file is the only file you write. Leave every file in the repo, and its git state, as you found them. Search with Grep and Glob, or in the shell with `rg`, `grep`, `git grep` or `git ls-files`. To check a rule against every member of a family, you may also run a short script of your own that only reads files, such as a Python one-liner that lists every class with a given base and the names in its field list. Do not import or run the repo's own code.

**Stay inside the repo.** Read and search only under the repo root, plus your packet, the brief and your output file. Answer from what the repo's own files say. When a question needs more than that, such as an installed dependency, a package cache, a folder outside the repo, or a run of the code or its tests, say so in your answer and leave the question open.

## What a seam is

A seam is one piece of knowledge that lives in two or more places in the repo, where the places must agree. If one place changes without the others, the result is wrong: a bug, a wrong number, a silent failure, a security gap, or a visible inconsistency. The knowledge can be a list, a map, a rule, a format, a payload shape, a constant, a behavior or an algorithm.

It includes:

- code mirrored between two services, or between a client and a server,
- producer and consumer contracts: a payload built in one place and parsed in another, or an API response and the frontend code that reads it,
- vocabularies repeated in several files: status names, types, field lists, permission names, database CHECK or enum values against code constants,
- copied helper code, where a fix to one copy must reach the others (auth, retry, parsing),
- config that must match across files: env var names, ports, paths, service names,
- a doc that states a code fact, only when someone acts on that fact.
- a rule that every member of a family must follow: every payment provider class implements refunds; every API handler checks the caller's role; every CLI command registers its help text. The copies are the family's files, and a member that breaks the rule is drift.

It excludes:

- boilerplate and look-alike code that may differ harmlessly,
- anything only in historical docs (plans, brainstorms, old reviews),
- tests that duplicate other tests. A test that checks two copies against each other is a tie, not a seam.
- generated code. A generator with one input is a single source.
- knowledge repeated inside one file, such as one list written once per section of a config file. A copy is a file, so the registry cannot hold it.

Record **one seam per piece of knowledge, not per file pair**. Group every copy of the same knowledge into one seam.

Some differences between copies are deliberate: two databases with different placeholder syntax, or two services that name the same field differently on purpose. Record these in `intentional_differences`, so nobody "fixes" them.

## What a tie is

A tie is an automated check that **fails** when the copies drift: a test, or a script that CI runs. A single source of truth is better than a tie: one shared module that every side imports. If the knowledge already has a single source, set `single_source` to true, and list only the copies that remain outside it. If none remain, it is not a seam.

Claims about ties need evidence:

- To claim a tie, open the test and quote the assertion that fails on drift in `assert_line`. Say whether it covers all the copies or only some.
- Find how CI runs that test (the CI config files). A test that CI never runs is not a tie. Say so in `runs_in_ci`.
- To claim there is no tie, say in `tie_search` what you searched.

## Method

0. If the repo root has a `seams.json`, read it first. It lists the seams found earlier. Record the seams it does not list. Record a listed seam only when you find a copy it misses: then use the same `id`, and give the new copies and one copy it already lists.
1. Read your leads. They come from a mechanical scan. Many are noise. A `co-change` lead comes from git history: two files that keep changing in the same commits. They may share no text at all, so open both and look for the knowledge they hold in common. Look past the leads too: the scan cannot see a payload built in one place and parsed in another when the two share no names and never changed together.
2. Hunt for the seams the scan cannot see. They share no names and no copied text, so no lead points at them. In each of your areas, look for:
   - the same behavior in two places: date, time zone and number formatting; rounding; unit conversion; thresholds and limits; retry rules,
   - identity and auth helpers that each decide who the caller is,
   - a value that more than one code path writes to the same column, key or file: a date, a status name, a JSON blob. Find every writer, the rarely run ones too (an admin action, a cleanup job, an import), and check that each one writes the same format. A `date-format` lead names a format constant and the files beside its users that write dates another way: open each one and see where its dates go,
   - a message or payload built in one place and read in another: queue and MQTT topics, retained messages, webhook bodies, API responses and the code that reads them,
   - config that code must match: scrape and relabel rules, collector configs, templates, compose and deploy files,
   - docs that state a code fact an agent acts on: CLAUDE.md files, architecture docs, catalogs and their generators,
   - a short description of something defined elsewhere: a README or index line for each module, skill or command, a router or help text that says what each one does, a CHANGELOG or ADR line that says one part uses another. Record one seam for each kind of description, such as "README descriptions match each skill", with the description files and the described files as copies. Then compare each description with what its thing does today, item by item,
   - a guard or a test that checks a file by path, and whether that path still holds the thing it checks.
   - a family that the repo builds one way: the subclasses of one base class, the files in one folder that do the same job, one file per app or plugin. Find the rule its members follow, from the repo's own checklist (a doc such as "adding a provider", a CONTRIBUTING section, a pull request template) or from what most members do. A `convention` lead names a family, its pattern and the members that break it. Read the checklist docs in your areas even when no lead points at them: each step that names a file is a copy of the rule.
3. For each candidate, open every copy and decide: seam or not.
4. For a seam, check whether the copies agree today. If they differ in a way that looks unintended, record it in `drift`, with path:line on each side.
   - For a description seam, list every claim each description makes: each name, flag, step, number and path. Check each one against the thing it describes. One stale line among twenty is still drift, and it is the line a quick read skips.
   - A description can be true and still drift by what it leaves out. Where it gives a list, compare the list with the full one in the source: a sequence of steps ("parse → validate → save") with one of the source's steps missing, or the users of a thing ("used by the API and the worker") when a third service uses it too. Record a missing item as drift. A summary that leaves out detail but gives no list is not drift.
   - When the code branches by backend, platform or version (a SQLite path and a MariaDB path, say), check every branch. Drift often hides in the branch the tests do not run.
   - When a difference is temporary or explained, such as a version bumped ahead of a pending release, say so in the drift text, with the evidence.
   - For a convention seam, check every member of the family, not a sample. List the members (a script helps), check each one against the rule, and name each member that breaks it with path:line. A member with a reason to differ, such as a provider that cannot refund, is not drift: say why in `intentional_differences`.
5. Rank the risk:
   - **high:** drift would silently produce wrong results, lose data, open a security gap, or misdrive hardware.
   - **medium:** drift would cause a visible bug or a broken feature.
   - **low:** drift is cosmetic, or a test or a user would catch it fast.

Your packet lists the areas other reviewers own. You may read any file in the repo. If a seam's copies sit mostly in another packet, record it anyway. A merge step joins duplicates. Name each seam after its knowledge, not its file names, so two reviewers give the same seam the same `id`.

## Output

Write a JSON array to your output file. Each element:

```json
{
  "id": "order-status-names",
  "title": "Order status names",
  "kind": "vocabulary",
  "must_agree": "The API and the web app list the same order status names.",
  "copies": [
    {"path": "api/orders/status.py", "symbol": "ORDER_STATUSES", "line": 2},
    {"path": "web/src/status.ts", "symbol": "ORDER_STATUSES", "line": 1}
  ],
  "consequence": "The web app filters on a status the API never sends.",
  "intentional_differences": null,
  "single_source": false,
  "ties": [
    {"path": "api/tests/test_status.py", "test": "test_status_names_match", "covers": "all",
     "assert_line": "assert api_names == web_names", "runs_in_ci": "yes: the test job runs pytest"}
  ],
  "tie_search": null,
  "drift": {"text": "api/orders/status.py:2 has 'returned'; web/src/status.ts:1 does not."},
  "suggested_tie": null,
  "risk": "high",
  "risk_reason": "A returned order disappears from the web app with no error.",
  "sensitive_finding": null
}
```

Field rules:

- `id`: kebab-case, from the knowledge.
- `kind`: one of mirror, contract, vocabulary, copied-helper, config, schema, convention. A convention seam's copies are globs for the family (`payments/providers/*.py`) plus the files that state the rule: its base class and its checklist doc.
- `copies[].path`: a file or a glob, relative to the repo root, with forward slashes. Every path must exist. A folder is not a copy: write `dir/**/*` instead.
- `copies[].symbol`: text that appears in that file, such as a function, constant or section name. Check it with a search. Omit it when no stable name exists.
- `ties[].test`: one test name that appears in the tie's file: a function name, or `Class.method`. Not a description, and not two names. For a runner that names a test by a string (Playwright, Jest and RSpec `test("...")` or `it("...")`), the name is that string.
- `ties[].covers`: `all` or `partial`. A partial tie needs a `note` that says which copies it checks.
- `ties[].runs_in_ci`: start with `yes:` and name the CI job or step, or start with `no:` and say why. If you cannot tell, write `unknown:` and what you looked at. The merge reads the first word.
- `drift`: null when the copies agree. Leave out `source` and `seen`: the merge sets them.
- `suggested_tie`: the cheapest automated check that would catch drift, or null when a full tie exists.
- `sensitive_finding`: if drift is a security hole, describe it here. The merge step keeps this field out of the registry. Every other text field then names only the difference, not the impact or how to use it. Write `consequence` as the behavior that differs ("one route applies a different visibility rule from the others"), not what an outsider can get, and keep the same care in `suggested_tie`.

A bug you find that is not a difference between copies, such as a check on the wrong value or a limit that is off by one, still goes in the array, as its own element:

```json
{"bug": "api/orders/refund.py:31 compares order.status with 'refund', but the status is 'refunded', so a second refund of the same order goes through.", "path": "api/orders/refund.py", "line": 31, "risk": "high", "sensitive": false}
```

Set `sensitive` to true for a security hole: the merge then keeps the text out of the report.

Write every text field as a plain statement about the repo: "api/status.py lists five names", not "I found five names". Name only the repo's own files: not scratch files, the packet or the leads.

Aim for completeness, not volume. A typical area holds 5 to 25 seams. After you write the file, read it back and make sure it parses as JSON.

## Final reply

Keep it under 200 words: the output path and the seam count, the three highest-risk seams, any drift you found, and anything you could not check.
