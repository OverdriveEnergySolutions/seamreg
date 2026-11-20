#!/usr/bin/env bash
# Usage: check_schedules.sh <commit> [repo]
# Every cron-schedule config key in src/config.rs (a String key whose default is a
# 6-field cron string) must be parsed in validate_config() with parse::<Schedule>().
# main.rs schedules them with .parse().unwrap(), so an unvalidated bad value panics the job thread.
set -euo pipefail
c=$1; repo=${2:?the path of a full vaultwarden clone}
src=$(git -C "$repo" show "$c:src/config.rs")
keys=$(echo "$src" | grep -E '^\s+[a-z0-9_]+:\s+String,\s+(true|false),\s+def,\s+"[0-9*/ ,-]+ [0-9*/ ,-]+ [0-9*/ ,-]+ [0-9*/ ,-]+ [0-9*/ ,-]+ [0-9*/ ,-]+"' | sed -E 's/^\s+([a-z0-9_]+):.*/\1/' | sort -u)
n=0
for k in $keys; do
  if ! echo "$src" | grep -qE "cfg\.$k\.parse::<Schedule>\(\)"; then echo "not validated: $k"; n=$((n+1)); fi
done
echo "schedule_keys=$(echo "$keys" | wc -w) violations=$n"
