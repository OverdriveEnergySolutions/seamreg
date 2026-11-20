#!/usr/bin/env bash
# Run one prompt blind on a benchmark workspace, in a fresh headless Claude Code session. Every
# benchmark kind uses this: the kind supplies the prompt, this script supplies the blindness.
#
#   [MODEL=claude-sonnet-5-5] [EFFORT=max] [MAX_TURNS=6] [ANSWER_FILE=f] \
#       bench/session.sh WORKDIR NAME PROMPT_FILE
#
# WORKDIR comes from bench/snapshot.sh. The session works in WORKDIR/blind and saves to WORKDIR/NAME/.
# PROMPT_FILE may use @TOOL@ (the frozen tool copy) and @WORK@ (WORKDIR). It must ask the session to
# end its final message with the line RUN COMPLETE. Until it does, the script resumes the session with
# the text of ANSWER_FILE (default: a yes that takes every recommended option), up to MAX_TURNS turns.
# It uses a frozen copy of this seamreg checkout (WORKDIR/tool, from its HEAD commit, without docs/
# and bench/), so editing seamreg during a run changes nothing.
# It runs on your normal Claude Code login, so a subscription works. Your own settings, skills,
# plugins, hooks and MCP servers are turned off for the run.
set -uo pipefail
W=$(cd "${1:?workdir from bench/snapshot.sh}" && pwd)
NAME=${2:?a name for the output folder of this session, such as detection}
PROMPT=$(cd "$(dirname "${3:?prompt file}")" && pwd)/$(basename "$3")
HERE=$(cd "$(dirname "$0")/.." && pwd)
MODEL=${MODEL:-claude-sonnet-5-5}; EFFORT=${EFFORT:-max}; MAX_TURNS=${MAX_TURNS:-6}
B=$W/blind; T=$W/tool; R=$W/$NAME
[ -d "$B/.git" ] || { echo "run: no blind clone in $W (run bench/snapshot.sh first)" >&2; exit 1; }
[ -e "$R" ] && { echo "run: $R exists already; move it aside to run again" >&2; exit 1; }
mkdir -p "$R/tmp"
log() { echo "$(date '+%F %T') $*" | tee -a "$R/run.log"; }

# A frozen copy of the tool, from the checkout's HEAD commit.
TOOL_SHA=$(git -C "$HERE" rev-parse HEAD)
DIRTY=$(git -C "$HERE" status --porcelain -- src skills agents .claude-plugin | head -1)
[ -n "$DIRTY" ] && log "warning: seamreg has uncommitted changes; the run uses HEAD $TOOL_SHA without them"
if [ ! -d "$T" ]; then  # one tool copy per workspace, so later sessions in it use the same tool
    mkdir -p "$T"; git -C "$HERE" archive HEAD | tar -x -C "$T"; rm -rf "$T/docs" "$T/bench"
    echo "$TOOL_SHA" > "$T/.bench-commit"
fi
TOOL_SHA=$(cat "$T/.bench-commit")

ANSWER_DEFAULT="Yes. Take your recommended option for every choice: one seam-reviewer per packet at max effort; for the drift check, the skill's default selection at default effort, and skip any optional second-opinion pass; for notes or agents, your pick. Then continue to the end of the workflow."
ANSWER=$ANSWER_DEFAULT; [ -n "${ANSWER_FILE:-}" ] && ANSWER=$(cat "$ANSWER_FILE")
sed -e "s|@TOOL@|$T|g" -e "s|@WORK@|$W|g" "$PROMPT" > "$R/prompt.md"
SID=$(python3 -c "import uuid; print(uuid.uuid4())"); echo "$SID" > "$R/session-id"

result() { python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result') or '')" "$1" 2>/dev/null; }
failed() { python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('is_error') or d.get('subtype')!='success' else 1)" "$1" 2>/dev/null; }
turn() {  # turn N MESSAGE [first]
    local how=(--resume "$SID"); [ -n "${3:-}" ] && how=(--session-id "$SID")
    (cd "$B" && TMPDIR="$R/tmp" ENABLE_CLAUDEAI_MCP_SERVERS=false claude -p "$2" "${how[@]}" \
        --plugin-dir "$T" --model "$MODEL" --effort "$EFFORT" --permission-mode auto \
        --setting-sources project,local --strict-mcp-config --output-format json \
        > "$R/turn$1.json" 2> "$R/turn$1.err")
    [ -s "$R/turn$1.json" ] && ! failed "$R/turn$1.json"
}

log "$NAME: $(python3 -c "import json;print(json.load(open('$W/bench.json'))['repo_url'])") at $(git -C "$B" rev-parse --short HEAD), seamreg ${TOOL_SHA:0:10}, $MODEL at $EFFORT effort"
turn 1 "$(cat "$R/prompt.md")" first || { log "STOP: turn 1 failed, see $R/turn1.err"; exit 1; }
n=1
while ! result "$R/turn$n.json" | tail -c 300 | grep -q 'RUN COMPLETE'; do
    [ $n -ge "$MAX_TURNS" ] && { log "STOP: no RUN COMPLETE after $n turns"; break; }
    n=$((n + 1)); turn $n "$ANSWER" || { log "STOP: turn $n failed, see $R/turn$n.err"; break; }
done

# Save what the run made. leads.json is large and the scan can rebuild it.
mkdir -p "$R/results"
cp "$B/seams.json" "$R/results/seams.json" 2>/dev/null
cp -r "$B/.seams-scan" "$R/results/seams-scan" 2>/dev/null; rm -f "$R/results/seams-scan/leads.json"
mv "$B/.seams-feedback.md" "$R/results/feedback.md" 2>/dev/null
(cd "$B" && git diff > "$R/results/repo-changes.diff")
rm -rf "$R/tmp"
python3 -I - "$R" "$MODEL" "$EFFORT" "$TOOL_SHA" "$SID" <<'PY'
import glob, json, os, sys
r, model, effort, tool, sid = sys.argv[1:6]
# total_cost_usd is the session's running total, so the last turn holds the run's cost.
turns = sorted(glob.glob(os.path.join(r, "turn*.json")), key=lambda f: int(os.path.basename(f)[4:-5]))
cost = 0.0
for f in turns:
    try: cost = max(cost, json.load(open(f)).get("total_cost_usd") or 0)
    except Exception: pass
try: seams = json.load(open(os.path.join(r, "results/seams.json")))["seams"]
except Exception: seams = []
done = False
try: done = "RUN COMPLETE" in (json.load(open(turns[-1])).get("result") or "")[-300:]
except Exception: pass
out = {"model": model, "effort": effort, "tool_commit": tool, "session_id": sid, "turns": len(turns),
       "complete": done, "cost_usd_api_equivalent": round(cost, 2), "seams": len(seams),
       "risk": {k: sum(s.get("risk") == k for s in seams) for k in ("high", "medium", "low")},
       "drift_claims": sum(bool(s.get("drift")) for s in seams)}
json.dump(out, open(os.path.join(r, "summary.json"), "w"), indent=2)
print(json.dumps(out))
PY
log "saved $R/results and $R/summary.json. Next: python3 bench/blindscan.py $W $NAME"
