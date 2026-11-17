---
paths:
  - "pyproject.toml"
  - ".claude-plugin/plugin.json"
  - "src/seams/check.py"
---
<!-- Generated from seams.json by seams_check.py --notes. Edit seams.json, not this text. -->

The file you opened holds a copy of knowledge that other files must match. When you plan or make a change here, include the other copies, or say why they must differ.

```
seam 'version-number' (risk medium): Release version
  must agree: The package, the plugin and the checker state the same version.
  copies: pyproject.toml, .claude-plugin/plugin.json, src/seams/check.py
  tie: tests/test_own_seams.py (test_versions_agree), covers all
```
