This repo has never been checked for seams. Use the seams-review skill to find its seams and build its registry. Follow the skill's workflow from the beginning, including the drift check.

The `seams` command is not installed. Wherever the skill says `seams`, run `uvx --from @TOOL@ seams` instead.

This is a headless session: nobody is at the keyboard while you work. When you need my answer, end your turn with the question, and I will answer by resuming this session. Start reviewer and drift-checker agents in the foreground (several in one message is fine, they still run in parallel), so your turn waits for them to finish.

Rules for this run:
- Follow the skill as written. Where it is unclear, wrong or missing a step, do what a careful user would, and log it in .seams-feedback.md in the repo root (git ignores it): what happened, and what you did instead.
- Show me the plan and its cost before you start any reviewer, and wait for my yes. Do the same before the drift check.
- For the drift check, check every seam the skill's default selects. Do not sample.
- Read nothing outside this repo except @TOOL@/skills/, @TOOL@/agents/, and the files the seams commands write. Never open any other file under @TOOL@, anything under @WORK@ outside this repo, or any other folder in your home folder. Do not use the web, GitHub or git remotes.
- Go through `seams merge`, the drift check and `seams apply`. Settle the merge report the way the skill says, turn on notes, and run the check. Do not commit.

At the end, report the seam count, the split by risk, the drift found by the reviewers and by the drift check, and the items in .seams-feedback.md.

When the whole workflow above is finished, end your final message with a line that says exactly: RUN COMPLETE
