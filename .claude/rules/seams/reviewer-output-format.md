---
paths:
  - "src/seams/brief.md"
  - "src/seams/merge.py"
---
<!-- Generated from seams.json by seams_check.py --notes. Edit seams.json, not this text. -->

The file you opened holds a copy of knowledge that other files must match. When you plan or make a change here, include the other copies, or say why they must differ.

```
seam 'reviewer-output-format' (risk high): Reviewer output format: brief and merge
  must agree: The JSON example in the reviewer brief has exactly the fields the merge accepts.
  copies: src/seams/brief.md, src/seams/merge.py
  tie: tests/test_merge.py (test_brief_example_matches_what_merge_accepts), covers all
```
