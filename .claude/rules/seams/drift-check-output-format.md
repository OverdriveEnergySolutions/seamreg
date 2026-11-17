---
paths:
  - "src/seams/verify-brief.md"
  - "src/seams/verify.py"
---
<!-- Generated from seams.json by seams_check.py --notes. Edit seams.json, not this text. -->

The file you opened holds a copy of knowledge that other files must match. When you plan or make a change here, include the other copies, or say why they must differ.

```
seam 'drift-check-output-format' (risk high): Drift check output format: brief and collector
  must agree: The JSON example in the drift check brief has exactly the fields the collector accepts.
  copies: src/seams/verify-brief.md, src/seams/verify.py
  tie: tests/test_verify.py (test_brief_example_matches_what_collect_accepts), covers all
```
