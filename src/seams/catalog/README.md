# The miss library

Each file in misses/ is one miss report: drift between copies that seamreg did not record, with the rule
the copies had to keep, which copy changed and which was missed, and what the registry held at the time.
`seams catalog` reads this folder and ranks the shapes no pass handles yet. The top of that list is the
next kind of pass worth building.

Rules for the library:

- **Public repos only, here.** A report from a private repo carries its shape only (`seams report-miss`
  without --public). Paths, commits and code from a private repo never go in this folder.
- **Judge a new kind on reports it was not built from.** Build it from some of a shape's reports and
  measure it, with the prevention replays, on the others.
- **Benchmark runs must not read this folder.** Its reports name real drifts in benchmark repos. The
  skills, the agents and the briefs never point here, and a test checks that.
- **handled_by** names the pass that now records the shape. Set it only after a measured run shows it.

candidates/ holds the open pass's tested guesses, one file per repo: each guess, its perspective, whether
it held, the script that tested it and the seams it produced. A guess that holds on several repos is a
candidate kind. The first 111 (56 held) come from five open passes on 2026-11-16. Guesses about access control, logins and secrets are left out of this public copy until any issue they point at is reported and fixed.

The first 13 reports come from the prevention benchmark (2026-11-17): the replay tasks whose rule the
seeded registry did not state. Four are handled by the siblings and packaging passes.
