---
paths:
  - "src/seams/cli.py"
  - "README.md"
  - "skills/seams/SKILL.md"
  - "skills/seams-review/SKILL.md"
  - "docs/usage.md"
  - "docs/concepts.md"
  - "docs/passes.md"
  - "docs/benchmarks.md"
  - "CONTRIBUTING.md"
---
<!-- Generated from seams.json by seams_check.py --notes. Edit seams.json, not this text. -->

The file you opened holds a copy of knowledge that other files must match. When you plan or make a change here, include the other copies, or say why they must differ.

```
seam 'documented-commands' (risk low): Commands the docs name
  must agree: Every `seams <command>` the docs name exists in the CLI.
  copies: src/seams/cli.py, README.md, skills/seams/SKILL.md, skills/seams-review/SKILL.md, docs/usage.md, docs/concepts.md, docs/passes.md, docs/benchmarks.md, CONTRIBUTING.md
  tie: tests/test_own_seams.py (test_documented_commands_exist), covers partial
  no full tie: nothing fails if these copies drift. Update every copy. A tie is welcome but never a reason to leave a copy stale.
```
