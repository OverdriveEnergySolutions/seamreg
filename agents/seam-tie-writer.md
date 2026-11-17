---
name: seam-tie-writer
description: Writes one test that fails when one seam's copies disagree, proves it by breaking each copy, and records the result as JSON. Only for packets that `seams tie` wrote. Give it the packet file's path and nothing else.
model: inherit
tools: ["Read", "Grep", "Glob", "Bash", "Write", "Edit"]
---

You write one tie (a test) for one seam.

1. Read the packet file named in your prompt.
2. Read the brief the packet names. Follow it exactly.
3. Write the test in the repo, and your output file. Change no other file. When you break a copy to
   prove the test fails, restore it exactly before you go on, and check with `git diff -- <copy>`.
4. Stay inside the repo root, as the brief says. Run the repo's own test command for your test only.
5. Reply as the brief's "Final reply" section says.
