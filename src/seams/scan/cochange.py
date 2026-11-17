"""Files that keep changing in the same commits: knowledge the history says moves together.

The other detectors read the code's text. This one reads git history, so it can point at
seams that share no text at all: a doc that describes a script, a payload built in one
service and read in another, logic copied between two places. Strength is code-maat's
degree: shared commits / the average commit count of the two files.

Pairs in one folder are left out (one feature changing together, not a seam), and so are
tests (a test changes with its code) and bulk commits (a rename touches everything). A repo
with no history gives no leads.
"""
from __future__ import annotations

import collections
import itertools
import subprocess

from seams.scan.inventory import Lead, is_test

MAX_FILES = 30      # a commit that touches more files than this is a bulk change
MIN_SHARED = 3      # commits the two files must share
MIN_DEGREE = 0.3    # shared / average commits of the two files
MAX_COMMITS = 10000


def history(root):
    """The file sets of the repo's recent non-merge commits, newest first. Rename detection
    is off: it made git log 100 times slower, and a renamed file only loses its older pairs."""
    try:
        run = subprocess.run(["git", "-C", str(root), "log", "--no-merges", "--name-only", "--format=tformat:@@", "--no-renames",
                              f"--max-count={MAX_COMMITS}"], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if run.returncode != 0:
        return []
    commits, cur = [], None
    for line in run.stdout.decode("utf-8", "replace").split("\n"):
        if line == "@@":
            cur = set()
            commits.append(cur)
        elif line.strip() and cur is not None:
            cur.add(line.strip())
    return commits


def find(inv):
    alive, readable = set(inv.files), set(inv.read)
    revs, shared = collections.Counter(), collections.Counter()
    for files in history(inv.root):
        files = files & alive
        if len(files) > MAX_FILES:
            continue
        revs.update(files)
        cand = sorted(f for f in files if f in readable and not is_test(f))
        for x, y in itertools.combinations(cand, 2):
            if x.rsplit("/", 1)[0] != y.rsplit("/", 1)[0]:
                shared[(x, y)] += 1
    leads = []
    for (x, y), n in shared.items():
        if n < MIN_SHARED:
            continue
        degree = n / ((revs[x] + revs[y]) / 2)
        if degree < MIN_DEGREE:
            continue
        leads.append(Lead("co-change", [(x, None, None), (y, None, None)],
                          f"changed together in {n} commits ({degree:.0%}): {x} has {revs[x]}, {y} has {revs[y]}",
                          score=round(n * degree, 2)))
    return leads
