#!/usr/bin/env bash
# Fails when a commit subject between two revisions breaks the AGENTS.md rule: at most 72
# characters and no trailing period. Merge commits are skipped. Usage: check-commits.sh BASE HEAD
set -euo pipefail
base=${1:?base revision}
head=${2:?head revision}
bad=0
while IFS= read -r subject; do
  if [ "${#subject}" -gt 72 ]; then
    echo "longer than 72 characters (${#subject}): $subject"; bad=1
  elif [[ "$subject" == *. ]]; then
    echo "ends with a period: $subject"; bad=1
  fi
done < <(git log --no-merges --format=%s "$base..$head")
[ "$bad" -eq 0 ] && echo "commit subjects ok"
exit "$bad"
