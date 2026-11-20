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
if ! [[ $SNAP =~ ^[0-9a-fA-F]{7,40}$ ]]; then echo "snapshot: give the snapshot as a commit hash" >&2; exit 1; fi
if [ -e "$W/blind" ]; then echo "snapshot: $W/blind exists already" >&2; exit 1; fi
mkdir -p "$W"; W=$(cd "$W" && pwd)
[ -d "$W/full/.git" ] || git clone -q -- "$URL" "$W/full"
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
# The values go in as arguments, never into the Python source, so no URL can inject code.
python3 -I - "$W/bench.json" "$URL" "$FULL_SHA" "$SNAP_DATE" "$END_SHA" "$END_DATE" "$LATER" \
    "$(git -C "$W/blind" ls-files | wc -l)" <<'PY'
import json, sys
out, url, snap, snap_date, end, end_date, later, files = sys.argv[1:9]
json.dump({"repo_url": url, "snapshot": snap, "snapshot_date": snap_date, "window_end": end,
           "window_end_date": end_date, "later_commits": int(later), "files": int(files)},
          open(out, "w"), indent=2)
PY
echo "workspace $W"
echo "  blind clone at ${FULL_SHA:0:10} ($SNAP_DATE), $(git -C "$W/blind" ls-files | wc -l) files, no later commit"
echo "  key window: $LATER non-merge commits after the snapshot, up to ${END_SHA:0:10} ($END_DATE)"
