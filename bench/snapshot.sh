#!/usr/bin/env bash
# Make a benchmark workspace: a full clone for the answer key, and a blind clone that holds the
# snapshot's history and nothing later.
#
#   bench/snapshot.sh REPO_URL SNAPSHOT_COMMIT WORKDIR
#
# WORKDIR/full   full history, read only. The key builder reads it. The blind run must never see it.
# WORKDIR/blind  history up to SNAPSHOT_COMMIT only, no remote, no tags. The blind run works here.
# WORKDIR/bench.json  the workspace's facts, which the other scripts read.
set -euo pipefail
URL=${1:?repo url}; SNAP=${2:?snapshot commit}; W=${3:?workdir}
if [ -e "$W/blind" ]; then echo "snapshot: $W/blind exists already" >&2; exit 1; fi
mkdir -p "$W"; W=$(cd "$W" && pwd)
[ -d "$W/full/.git" ] || git clone -q "$URL" "$W/full"
FULL_SHA=$(git -C "$W/full" rev-parse --verify "$SNAP^{commit}")
git -C "$W/full" branch -f bench-snapshot "$FULL_SHA" >/dev/null
git clone -q --single-branch --branch bench-snapshot --no-tags "file://$W/full" "$W/blind"
git -C "$W/blind" remote remove origin
git -C "$W/blind" branch -q -m bench-snapshot main
git -C "$W/full" branch -q -D bench-snapshot
# Every commit in the blind clone must be an ancestor of the snapshot, so no later fix is in it.
ALL=$(git -C "$W/blind" rev-list --all | wc -l); HEAD_N=$(git -C "$W/blind" rev-list HEAD | wc -l)
if [ "$(git -C "$W/blind" rev-parse HEAD)" != "$FULL_SHA" ] || [ "$ALL" != "$HEAD_N" ]; then
    echo "snapshot: LEAK, the blind clone holds commits beyond $SNAP" >&2; exit 1
fi
echo ".seams-feedback.md" >> "$W/blind/.git/info/exclude"
SNAP_DATE=$(git -C "$W/full" log -1 --format=%cs "$FULL_SHA")
END_SHA=$(git -C "$W/full" rev-parse HEAD); END_DATE=$(git -C "$W/full" log -1 --format=%cs HEAD)
LATER=$(git -C "$W/full" rev-list --count --no-merges "$FULL_SHA..HEAD")
python3 - "$W/bench.json" <<PY
import json, sys
json.dump({"repo_url": "$URL", "snapshot": "$FULL_SHA", "snapshot_date": "$SNAP_DATE",
           "window_end": "$END_SHA", "window_end_date": "$END_DATE", "later_commits": $LATER,
           "files": $(git -C "$W/blind" ls-files | wc -l)}, open(sys.argv[1], "w"), indent=2)
PY
echo "workspace $W"
echo "  blind clone at ${FULL_SHA:0:10} ($SNAP_DATE), $(git -C "$W/blind" ls-files | wc -l) files, no later commit"
echo "  key window: $LATER non-merge commits after the snapshot, up to ${END_SHA:0:10} ($END_DATE)"
