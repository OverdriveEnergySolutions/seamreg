---
paths:
  - "src/seams/presets.py"
  - "agents/seam-reviewer.md"
  - "agents/seam-drift-checker.md"
  - "agents/seam-lead-checker.md"
  - "agents/seam-risk-rater.md"
---
<!-- Generated from seams.json by seams_check.py --notes. Edit seams.json, not this text. -->

The file you opened holds a copy of knowledge that other files must match. When you plan or make a change here, include the other copies, or say why they must differ.

```
seam 'preset-effort-floors' (risk medium): Agent effort floors and the standard preset
  must agree: Each seamreg agent file's effort is the standard preset's effort for that agent's step.
  copies: src/seams/presets.py, agents/seam-reviewer.md, agents/seam-drift-checker.md, agents/seam-lead-checker.md, agents/seam-risk-rater.md
  tie: tests/test_agents.py (test_agent_effort_floors_match_the_standard_preset), covers all
```
