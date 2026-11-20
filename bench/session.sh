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
#
# RESUME=1 continues a session that stopped before RUN COMPLETE (a usage limit, a crash, a lost
# connection): same session, same tool copy, same blindness. Run it with the same arguments.
# It uses a frozen copy of this seamreg checkout (WORKDIR/tool, from its HEAD commit, without docs/
# and bench/), so editing seamreg during a run changes nothing.
# It runs on your normal Claude Code login, so a subscription works. No settings file loads: not yours,
# and not the target repo's own .claude/settings*.json, whose hooks could run commands on your machine.
# No MCP server loads either. Only the frozen seamreg plugin is added.
set -uo pipefail
W=$(cd "${1:?workdir from bench/snapshot.sh}" && pwd)
NAME=${2:?a name for the output folder of this session, such as detection}
PROMPT=$(cd "$(dirname "${3:?prompt file}")" && pwd)/$(basename "$3")
HERE=$(cd "$(dirname "$0")/.." && pwd)
MODEL=${MODEL:-claude-sonnet-5-5}; EFFORT=${EFFORT:-max}; MAX_TURNS=${MAX_TURNS:-6}
B=$W/blind; T=$W/tool; R=$W/$NAME
[ -d "$B/.git" ] || { echo "run: no blind clone in $W (run bench/snapshot.sh first)" >&2; exit 1; }
if [ "${RESUME:-}" = 1 ]; then
    [ -s "$R/session-id" ] || { echo "run: nothing to resume in $R" >&2; exit 1; }
else
    [ -e "$R" ] && { echo "run: $R exists already; move it aside, or set RESUME=1 to continue it" >&2; exit 1; }
fi
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
if [ "${RESUME:-}" = 1 ]; then
    SID=$(cat "$R/session-id")
else
    sed -e "s|@TOOL@|$T|g" -e "s|@WORK@|$W|g" "$PROMPT" > "$R/prompt.md"
    SID=$(python3 -c "import uuid; print(uuid.uuid4())"); echo "$SID" > "$R/session-id"
fi

result() { python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('result') or '')" "$1" 2>/dev/null; }
# A turn failed when its result says so, or when there is no readable result at all.
failed() { python3 -I -c "
import json, sys
try: d = json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
sys.exit(0 if d.get('is_error') or d.get('subtype') != 'success' else 1)" "$1" 2>/dev/null; }

# While the blind session runs, every other entry in WORKDIR (the full clone, the key, other sessions)
# is made unreadable, so a stray read, even by a relative path such as ../key, fails loudly. This is not
# a security boundary: the session runs as you and could change the modes back. The transcript scan is
# the check (it flags chmod and the like), and a container is the boundary. The modes are saved first and
# put back when this script ends, however it ends.
HIDDEN=$R/hidden-modes.json
hide() {
    python3 -I - "$W" "$NAME" "$HIDDEN" <<'PY'
import json, os, sys
w, name, out = sys.argv[1:4]
modes = json.load(open(out)) if os.path.exists(out) else {}
for e in sorted(os.listdir(w)):
    p = os.path.join(w, e)
    if e in ("blind", "tool", name) or os.path.islink(p):
        continue
    modes.setdefault(p, os.stat(p).st_mode & 0o7777)
    os.chmod(p, 0)
json.dump(modes, open(out, "w"))
PY
}
unhide() {
    [ -f "$HIDDEN" ] || return 0
    # The modes file sits where the session can write, so trust only what hide() could have written:
    # direct children of WORKDIR other than blind, tool and this session, plain permission bits only.
    python3 -I - "$HIDDEN" "$W" "$NAME" <<'PY'
import json, os, sys
path, w, name = sys.argv[1:4]
try:
    modes = json.load(open(path))
except Exception:
    modes = {}
for p, m in (modes.items() if isinstance(modes, dict) else []):
    if not isinstance(m, int) or os.path.dirname(p) != w or os.path.basename(p) in ("blind", "tool", name):
        continue
    if os.path.exists(p) and not os.path.islink(p):
        os.chmod(p, m & 0o777)
os.remove(path)
PY
}
unhide            # a run that crashed may have left them hidden
trap unhide EXIT
turn() {  # turn N MESSAGE [first]
    local how=(--resume "$SID"); [ -n "${3:-}" ] && how=(--session-id "$SID")
    (cd "$B" && TMPDIR="$R/tmp" ENABLE_CLAUDEAI_MCP_SERVERS=false claude -p "$2" "${how[@]}" \
        --plugin-dir "$T" --model "$MODEL" --effort "$EFFORT" --permission-mode auto \
        --setting-sources "" --strict-mcp-config --output-format json \
        < /dev/null > "$R/turn$1.json" 2> "$R/turn$1.err")
    [ -s "$R/turn$1.json" ] && ! failed "$R/turn$1.json"
}

log "$NAME: $(python3 -I -c "import json,sys;print(json.load(open(sys.argv[1]))['repo_url'])" "$W/bench.json") at $(git -C "$B" rev-parse --short HEAD), seamreg ${TOOL_SHA:0:10}, $MODEL at $EFFORT effort"
hide
# A resume needs a session to continue. If turn 1 never created one, start it now instead.
if [ "${RESUME:-}" = 1 ] && failed "$R/turn1.json" && ! grep -q '"session_id"' "$R/turn1.json" 2>/dev/null; then
    log "resume: turn 1 never started a session; starting it now"; RESUME=0
    [ -s "$R/prompt.md" ] || sed -e "s|@TOOL@|$T|g" -e "s|@WORK@|$W|g" "$PROMPT" > "$R/prompt.md"
fi
if [ "${RESUME:-}" = 1 ]; then
    n=$(ls "$R"/turn*.json 2>/dev/null | sed 's/.*turn\([0-9]*\)\.json/\1/' | sort -n | tail -1)
    n=${n:-0}; log "resume: session $SID after turn $n"
    # A stop saved a copy of the run's notes; put it back if the repo lost it.
    [ -f "$B/.seams-feedback.md" ] || cp "$R/results/feedback.md" "$B/.seams-feedback.md" 2>/dev/null
    n=$((n + 1)); turn $n "Continue where you stopped. $ANSWER" || { log "STOP: turn $n failed, see the result in $R/turn$n.json and $R/turn$n.err"; }
    MAX_TURNS=$((n + MAX_TURNS - 1))
else
    turn 1 "$(cat "$R/prompt.md")" first || { log "STOP: turn 1 failed, see the result in $R/turn1.json and $R/turn1.err"; exit 1; }
    n=1
fi
while ! result "$R/turn$n.json" | tail -c 300 | grep -q 'RUN COMPLETE'; do
    failed "$R/turn$n.json" && break
    [ $n -ge "$MAX_TURNS" ] && { log "STOP: no RUN COMPLETE after $n turns"; break; }
    n=$((n + 1)); turn $n "$ANSWER" || { log "STOP: turn $n failed, see the result in $R/turn$n.json and $R/turn$n.err"; break; }
done

# Save what the run made. leads.json is large and the scan can rebuild it.
unhide
rm -rf "$R/results"; mkdir -p "$R/results"
# Never follow a symlink out of the blind clone: a hostile repo could point seams.json at a private file.
[ -L "$B/seams.json" ] || cp "$B/seams.json" "$R/results/seams.json" 2>/dev/null
[ -L "$B/.seams-scan" ] || cp -rP "$B/.seams-scan" "$R/results/seams-scan" 2>/dev/null
rm -f "$R/results/seams-scan/leads.json"
# Copy the run's notes while the session may still resume. Move them only once it finished.
if result "$R/turn$n.json" | tail -c 300 | grep -q 'RUN COMPLETE'; then
    mv "$B/.seams-feedback.md" "$R/results/feedback.md" 2>/dev/null
else
    cp "$B/.seams-feedback.md" "$R/results/feedback.md" 2>/dev/null
fi
[ -L "$B/.seams-feedback.md" ] && rm -f "$R/results/feedback.md"
(cd "$B" && git diff > "$R/results/repo-changes.diff")
L=$(find "$R/results" -type l | wc -l); [ "$L" -gt 0 ] && { find "$R/results" -type l -delete; log "dropped $L symlinks from the saved results"; }
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
       "drift_claims": sum(bool(s.get("drift")) for s in seams),
       "resumes": sum("resume: session" in l for l in open(os.path.join(r, "run.log")))}
json.dump(out, open(os.path.join(r, "summary.json"), "w"), indent=2)
print(json.dumps(out))
PY
if python3 -I -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))['complete'] else 1)" "$R/summary.json"; then
    log "saved $R/results and $R/summary.json. Next: python3 bench/blindscan.py $W $NAME"
else
    log "saved $R/results, but the session did not finish. The reason is in the last turn*.json (its result) or turn*.err. Fix it (for a usage limit: wait for the reset, or log in to another account), then run again with RESUME=1"
fi
