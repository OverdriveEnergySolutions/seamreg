#!/usr/bin/env bash
# Usage: check_feature_flags.sh <commit> [repo]
# Compares SUPPORTED_FEATURE_FLAGS in src/config.rs with the flags documented
# in .env.template (lines '## - "flag": description'). Prints the
# differences and the count of violations (missing either side, or empty description).
set -euo pipefail
c=$1; repo=${2:?the path of a full vaultwarden clone}
code=$(git -C "$repo" show "$c:src/config.rs" | awk '/^pub const SUPPORTED_FEATURE_FLAGS/{f=1;next} f&&/^\];/{f=0} f' | grep -o '"[^"]*"' | tr -d '"' | sort -u)
tmpl_all=$(git -C "$repo" show "$c:.env.template" | awk '/^## Client Settings/{f=1} f&&/^# EXPERIMENTAL_CLIENT_FEATURE_FLAGS=/{f=0} f' | grep -E '^## - "[^"]+":')
tmpl=$(echo "$tmpl_all" | sed -E 's/^## - "([^"]+)".*/\1/' | sort -u)
empty=$(echo "$tmpl_all" | grep -E '^## - "[^"]+":\s*$' | sed -E 's/^## - "([^"]+)".*/\1/' || true)
n=0
for f in $(comm -23 <(echo "$code") <(echo "$tmpl")); do echo "in config.rs only: $f"; n=$((n+1)); done
for f in $(comm -13 <(echo "$code") <(echo "$tmpl")); do echo "in .env.template only: $f"; n=$((n+1)); done
for f in $empty; do echo "empty description in .env.template: $f"; n=$((n+1)); done
echo "violations=$n"
