## Seams

`seams.json` lists knowledge this repo keeps in more than one file: lists, maps, rules, payload shapes, copied helpers. A change to one copy alone breaks something, often with no error.

When you plan a change:

1. If you do not know the files yet, run `python3 scripts/seams_check.py --about "<topic>"`.
2. When you know the files you expect to touch, run `python3 scripts/seams_check.py --changed <files>`.
3. Put every copy it names into the plan, or say in the plan why that copy must differ.

Before you finish a change, run `python3 scripts/seams_check.py --staged`, or `--diff <base branch>` on a branch.

If a copy is stale, update it in the same change. Never leave a copy stale because it has no test. A tie (a test that fails when the copies differ) is a good follow-up: add one if it is cheap, or suggest it.

When you find knowledge that another file must match and no seam lists it, add the seam to `seams.json` in this change, with every copy you know of. Do this even when you leave the other copy alone and only mention it: the next change reads the registry, not your reply. After any edit to `seams.json`, run `python3 scripts/seams_check.py --notes`, then `python3 scripts/seams_check.py`, and fix what it reports. A seam's `kind` is one of: mirror, contract, vocabulary, copied-helper, config, schema, convention. If the `seams` command is installed, also run `seams report-miss` with the files and the rule, so the miss can be shared.

Before you open a pull request, if the `seams` command is installed, run `seams scan --since <base branch> --new`. Each lead it lists may be a seam this branch created. Add the real ones to `seams.json` in the same pull request.

The registry is not complete. A copy nobody listed does not show up in it.
