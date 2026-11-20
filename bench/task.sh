#!/usr/bin/env bash
# Run one non-blind session of a benchmark (building the key, grading), isolated and with its cost kept.
#
#   [MODEL=...] [EFFORT=...] bench/task.sh WORKDIR NAME BRIEF_FILE
#
# The session starts in WORKDIR and follows BRIEF_FILE. Like the blind session, it loads no settings file
# (yours or the repo's) and no MCP server, so your own instructions do not shape the key or the grading.
# It may still use the web, as the brief allows. Saves WORKDIR/sessions/NAME.json (the session's result
# and cost), which bench/result.py adds to result.json. These sessions take about 5 to 30 minutes.
set -uo pipefail
W=$(cd "${1:?workdir from bench/snapshot.sh}" && pwd)
NAME=${2:?a name for this session, such as key or grade}
BRIEF=$(cd "$(dirname "${3:?brief file}")" && pwd)/$(basename "$3")
mkdir -p "$W/sessions"
OUT=$W/sessions/$NAME.json
[ -s "$OUT" ] && { echo "task: $OUT exists already; move it aside to run again" >&2; exit 1; }
MODEL_ARGS=(); [ -n "${MODEL:-}" ] && MODEL_ARGS+=(--model "$MODEL"); [ -n "${EFFORT:-}" ] && MODEL_ARGS+=(--effort "$EFFORT")
echo "$(date '+%F %T') $NAME: started, following $BRIEF"
(cd "$W" && ENABLE_CLAUDEAI_MCP_SERVERS=false claude -p "Follow $BRIEF. Your workspace is $W." \
    "${MODEL_ARGS[@]}" --permission-mode auto --setting-sources "" --strict-mcp-config \
    --output-format json < /dev/null > "$OUT" 2> "$W/sessions/$NAME.err")
python3 -I - "$OUT" "$NAME" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    sys.exit(f"task: {sys.argv[2]} left no readable result ({e}); see the .err file beside it")
state = "failed" if d.get("is_error") or d.get("subtype") != "success" else "done"
print(f"{sys.argv[2]}: {state}, ${d.get('total_cost_usd') or 0:.2f} API-equivalent")
print((d.get("result") or "")[-600:])
sys.exit(1 if state == "failed" else 0)
PY
