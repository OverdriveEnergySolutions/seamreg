---
paths:
  - "skills/seams-review/SKILL.md"
  - "src/seams/merge.py"
---
<!-- Generated from seams.json by seams_check.py --notes. Edit seams.json, not this text. -->

The file you opened holds a copy of knowledge that other files must match. When you plan or make a change here, include the other copies, or say why they must differ.

```
seam 'merge-report-sections' (risk medium): Merge report sections the skill tells the user to settle
  must agree: Every section name that step 5 of the seams-review skill bolds is in merge.SETTLE, and merge.py writes a section with that name.
  copies: skills/seams-review/SKILL.md, src/seams/merge.py
  tie: tests/test_workflow.py (test_every_section_the_skill_names_is_one_the_merge_writes), covers all
```
