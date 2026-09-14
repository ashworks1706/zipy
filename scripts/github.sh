#!/usr/bin/env bash
# Branch rules and repository settings as code: .github/settings.json and .github/rulesets/*.json.
#
#   github.sh          show what would change, change nothing
#   github.sh apply    create or update every ruleset by name, and patch the repository settings
#
# Needs gh, logged in with admin on the repository. The repository is the origin remote.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
command -v gh >/dev/null || { echo "gh not found: https://cli.github.com"; exit 1; }
command -v jq >/dev/null || { echo "jq not found"; exit 1; }
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
mode=${1:-plan}
[ "$mode" = plan ] || [ "$mode" = apply ] || { sed -n '2,7p' "$0"; exit 1; }
echo "repository: $repo ($mode)"

echo "settings:"
current=$(gh api "repos/$repo")
jq -r 'to_entries[] | "\(.key) \(.value)"' .github/settings.json | while read -r key want; do
  have=$(jq -r --arg k "$key" '.[$k]' <<<"$current")
  [ "$have" = "$want" ] && printf '  ok      %s = %s\n' "$key" "$want" || printf '  change  %s: %s -> %s\n' "$key" "$have" "$want"
done
[ "$mode" = apply ] && gh api -X PATCH "repos/$repo" --input .github/settings.json >/dev/null && echo "  applied"

echo "rulesets:"
existing=$(gh api "repos/$repo/rulesets")
for file in .github/rulesets/*.json; do
  name=$(jq -r .name "$file")
  id=$(jq -r --arg n "$name" '.[] | select(.name == $n) | .id' <<<"$existing")
  if [ -z "$id" ]; then
    printf '  create  %s (%s)\n' "$name" "$file"
    [ "$mode" = apply ] && gh api -X POST "repos/$repo/rulesets" --input "$file" >/dev/null && echo "          created"
  else
    live=$(gh api "repos/$repo/rulesets/$id" | jq -S '{name, target, enforcement, conditions, bypass_actors, rules}')
    want=$(jq -S '{name, target, enforcement, conditions, bypass_actors, rules}' "$file")
    if [ "$live" = "$want" ]; then
      printf '  ok      %s\n' "$name"
    else
      printf '  update  %s (%s)\n' "$name" "$file"
      diff <(echo "$live") <(echo "$want") | sed 's/^/          /' || true
      [ "$mode" = apply ] && gh api -X PUT "repos/$repo/rulesets/$id" --input "$file" >/dev/null && echo "          updated"
    fi
  fi
done
[ "$mode" = plan ] && echo "nothing changed; run: just github apply"
exit 0
