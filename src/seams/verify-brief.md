# Seam drift check brief

You check one seam: one piece of knowledge kept in two or more files that must agree. Your packet names the repo root, the seam, its copies and your output file. Decide one thing: **do the copies agree today?**

**Read only.** Your output file is the only file you write. Leave the repo as you found it.

**Judge from the code alone.** Skip `seams.json`, `.seams-scan/` and any CLAUDE.md or AGENTS.md block between `<!-- seams:start -->` and `<!-- seams:end -->`: they hold what others concluded. Your agent may also load a seams note when you open a copy, text that begins "The file you opened holds a copy of knowledge". Set it aside too.

**Stay inside the repo.** Read and search only under the repo root, plus your packet, the brief and your output file. Answer from what the repo's own files say. When a question needs more than that, such as an installed dependency, a package cache, a folder outside the repo, or a run of the code or its tests, say so in your answer and leave the question open.

Search with Grep and Glob, or in the shell with `rg`, `grep`, `git grep` or `git ls-files`. For a family of many members, you may also run a short script of your own that only reads files. Do not import or run the repo's own code.

## Method

1. Read the seam's `must_agree`. It says what must be the same.
2. Open every copy. In each one, find the part that holds the knowledge, and write down its elements:
   - for a list or a map: every item and every key,
   - for a rule or a format: every case, operator, field, unit and default,
   - for a payload: every field name, its type and who fills it,
   - for code that two places run: what each one does with a missing, empty, wrong-case or wrong-type value, and with the edge cases of its input (the longest value and one more, letters outside ASCII, separators, numbered and bulleted list items). For a pattern, copy it into a scratch script and run it on those inputs,
   - for a stored value (a date, a status, a JSON field): every code path that writes it, the rarely run ones too, and the format each one writes,
   - for a description (a README line, a help text, a doc): every claim it makes, line by line: each name, flag, step, number and path. Where it gives a list, such as steps in order or the users of a thing, compare it with the full list in the source: an item the description leaves out is drift too.
   - for a convention (a rule every member of a family follows, kind `convention`): list every member the copies' globs hold, and check each one against the rule. Name each member that breaks it, with path:line. Do not stop at the first few.
   When the code branches by backend, platform or version (a SQLite path and a MariaDB path, say), list the elements of every branch. Drift often hides in the branch the tests do not run.
3. Compare the elements copy by copy. Look closely at:
   - an item in one copy and not in another,
   - a field one side writes and the other side reads under another name, or only in some conditions,
   - a value one side treats as optional and the other side requires,
   - two comparisons of the same value that differ in case, whitespace, encoding, type or unit,
   - a default, a limit or a rounding rule that differs.
4. Ignore the differences the packet lists as deliberate.
5. A copy can also be a doc, a template or a test. Check it the same way.
6. Check each tie the packet lists. Open it and confirm it reads the files that hold the copies today, by their current path and names. A tie that reads another file, an old path or a renamed symbol passes while the copies drift. That is drift too: record it.

Say the copies agree only after you have listed the elements on every side. "They look the same" is not a check.

## Output

Write one JSON object to your output file:

```json
{
  "id": "order-status-names",
  "agree": false,
  "drift": "api/orders/status.py:2 lists 'returned'. web/src/status.ts:1 does not, so the web app drops returned orders from its status filter.",
  "checked": "Listed the five names in api/orders/status.py and the four in web/src/status.ts.",
  "sensitive_finding": null
}
```

- `id`: the seam id from your packet.
- `agree`: true when every element matches, apart from the deliberate differences.
- `drift`: when `agree` is false, what differs, with path:line on each side. Only what differs: what agrees goes in `checked`. Null when `agree` is true.
- `checked`: one sentence on what you compared. Required either way.
- `sensitive_finding`: if the drift is a security hole, describe it here. Then `drift` names only the difference, not the impact or how to use it.

A gap in a guard or a check that is not a difference between the copies (both copies miss the same case) is not drift. Say it in `checked`. If it is a security hole, put it in `sensitive_finding` too.

Write each text as a plain statement about the repo: "web/src/status.ts:1 lacks 'returned'", not "I found that it lacks 'returned'".

## Final reply

One line: the seam id, agree or not, and the output path.
