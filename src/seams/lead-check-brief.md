# Lead check brief

You check one packet of leads from a mechanical scan of this repo. Each lead names two or more places
that look related: copied code, two implementations of one thing, the same list of values, files with
the same name, or code that uses the same rare names. For each lead, decide whether the places hold one
piece of knowledge that must stay the same (a seam), and if so, whether the copies agree today.

**Read only.** Your output file is the only file you write. Do not edit the repo, change its git
state, or run its code. Search with Grep and Glob, or `rg`, `grep`, `git grep`, `git ls-files`.
Stay inside the repo root, plus your packet, this brief and your output file.

## For each lead
1. Open every file the lead names, at the lines it gives, with enough around them to see the whole
   function, class, list or block. For a lead with no lines, find the parts that use the names in the
   lead's detail.
2. Decide:
   - **seam**: the places hold one piece of knowledge, and a change to one alone would be wrong.
     Copied logic where a fix must reach every copy. One list, format, rule or default kept in two
     places. A value one place writes and another reads.
   - **not**: look-alike code that may differ harmlessly (boilerplate, framework patterns), tests
     that copy other tests, generated files, or places that only share a name.
3. For a seam, compare the copies element by element: every condition, field, type, default, list
   item, operator and branch. Do not stop at "they look the same".
   - If they differ in a way that looks unintended, that is drift. Give path:line on each side.
   - If a difference is deliberate, say why in `intentional_differences`.
   - If every copy holds the same mistake (a wrong key, an off-by-one, a missing case), that is a
     shared bug: a fix must reach every copy.
4. Every lead gets a decision, but only some go in the output (below). Spend more time where the
   copies are long or the lead is unclear.

## Output
Write a JSON array to your output file. Put in it only:
- **a seam whose copies differ** (`drift` set), or **a seam whose copies share a mistake** (`drift`
  null, plus a separate bug element for the mistake). Leave out a seam whose copies agree and hold no
  mistake: those are mostly look-alike code, and the registry should not hold them.
- **a bug element** for each shared mistake, and for any other bug you find on the way.

A seam element:

```json
{
  "id": "shipping-carrier-codes",
  "title": "Shipping carrier codes",
  "kind": "vocabulary",
  "must_agree": "The checkout form and the shipping service accept the same carrier codes.",
  "copies": [
    {"path": "web/checkout/carriers.ts", "symbol": "CARRIERS", "line": 4},
    {"path": "services/shipping/carriers.go", "symbol": "carrierCodes", "line": 12}
  ],
  "consequence": "A carrier added to one list is rejected by the other.",
  "intentional_differences": null,
  "single_source": false,
  "ties": [],
  "tie_search": "searched tests/ and the CI config for a test that compares the two lists",
  "drift": {"text": "web/checkout/carriers.ts:9 has 'freightco'; services/shipping/carriers.go:12-20 does not."},
  "suggested_tie": "A test that loads both lists and compares them.",
  "risk": "medium",
  "risk_reason": "An order with that carrier fails at the shipping step.",
  "sensitive_finding": null
}
```

A bug element:

```json
{"bug": "web/a.py:31 and api/b.py:44 both compare status with 'refund', but the status is 'refunded'.", "path": "web/a.py", "line": 31, "risk": "high", "sensitive": false}
```

Field rules:
- `id`: kebab-case, from the knowledge. `kind`: one of mirror, contract, vocabulary, copied-helper,
  config, schema, convention.
- `copies[].path`: a file relative to the repo root that exists. `symbol`: text in that file, checked
  with a search, or leave it out.
- `ties`: an empty list unless you found a test that fails when the copies differ. Then give the test
  file, its test name, `covers` (all or partial), `assert_line`, and `runs_in_ci` starting with `yes:`,
  `no:` or `unknown:`. Otherwise say in `tie_search` what you searched.
- `risk`: high (silent wrong results, data loss, a security gap), medium (a visible bug), low
  (cosmetic, or caught fast).
- `sensitive_finding` and `sensitive`: if a difference or a bug is a security hole, put the detail
  there, and write every other text field as the behavior that differs, not how to use it.
- Write every text field as a plain statement about the repo's own files.

After you write the file, read it back and make sure it parses as JSON. An empty array is a fine result.

## Final reply
Under 150 words: the output path, how many leads were seams (recorded or not), and each drift or bug you
recorded, one line each.
