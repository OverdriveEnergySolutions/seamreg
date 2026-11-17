## Seams

`seams.json` lists knowledge this repo keeps in more than one file: lists, maps, rules, payload shapes, copied helpers. A change to one copy alone breaks something, often with no error.

When you plan a change:

1. If you do not know the files yet, run `python3 scripts/seams_check.py --about "<topic>"`.
2. When you know the files you expect to touch, run `python3 scripts/seams_check.py --changed <files>`.
3. Put every copy it names into the plan, or say in the plan why that copy must differ.

Before you finish a change, run `python3 scripts/seams_check.py --staged`, or `--diff <base branch>` on a branch.

If you fix drift between copies, add a tie in the same change: a test that fails when the copies differ. Then list the seam in `seams.json`. If no seam listed those copies, also run `seams report-miss` (part of the seamreg tool, not the checker copy) with the files and the rule, so the miss can be shared.

The registry is not complete. A copy nobody listed does not show up in it.
