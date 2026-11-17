---
paths:
  - "src/seams/check.py"
  - "schema/seams.schema.json"
---
<!-- Generated from seams.json by seams_check.py --notes. Edit seams.json, not this text. -->

The file you opened holds a copy of knowledge that other files must match. When you plan or make a change here, include the other copies, or say why they must differ.

```
seam 'registry-schema' (risk high): Registry schema: checker spec and published file
  must agree: The published JSON Schema is the exact output of the checker's SCHEMA.
  copies: src/seams/check.py, schema/seams.schema.json
  tie: tests/test_own_seams.py (test_committed_schema_matches_generated), covers all
```
