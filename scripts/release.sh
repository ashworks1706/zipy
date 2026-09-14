#!/usr/bin/env bash
# Versions and releases. main takes no direct pushes, so a release is a pull request then a tag.
#
#   release.sh bump 0.2.0    on a clean, current main: branch release/v0.2.0, set every version,
#                            relock, commit, and write release-notes/v0.2.0.md for you to edit
#   release.sh tag           on a clean main that has the bump merged: tag v<version> and push it
#   release.sh verify 0.2.0  every version in the repo equals the given one (CI runs this on a tag)
#
# CD builds the tag's image; the Release workflow publishes the GitHub release.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

versions() {
  printf 'apps/engine/pyproject.toml %s\n' "$(sed -nE 's/^version = "(.*)"/\1/p' apps/engine/pyproject.toml)"
  printf 'apps/cli/pyproject.toml %s\n' "$(sed -nE 's/^version = "(.*)"/\1/p' apps/cli/pyproject.toml)"
  printf 'apps/website/package.json %s\n' "$(sed -nE 's/^  "version": "(.*)",/\1/p' apps/website/package.json)"
}

verify() {
  local want=$1 bad=0
  while read -r file have; do
    if [ "$have" != "$want" ]; then echo "$file is $have, not $want"; bad=1; fi
  done < <(versions)
  [ "$bad" -eq 0 ] && echo "every version is $want"
  return "$bad"
}

clean_main() {
  [ "$(git branch --show-current)" = main ] || { echo "switch to main first"; exit 1; }
  [ -z "$(git status --porcelain)" ] || { echo "the working tree is not clean"; exit 1; }
  git fetch --quiet origin main
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main is not origin/main; pull first"; exit 1; }
}

case "${1:-}" in
  bump)
    version=${2:?usage: release.sh bump X.Y.Z}
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || { echo "not a semver: $version"; exit 1; }
    clean_main
    git switch -c "release/v$version"
    sed -i -E "s/^version = \".*\"/version = \"$version\"/" apps/engine/pyproject.toml apps/cli/pyproject.toml
    sed -i -E "s/^  \"version\": \".*\",/  \"version\": \"$version\",/" apps/website/package.json
    (cd apps/website && npm install --package-lock-only --no-audit --no-fund >/dev/null)
    uv lock --quiet
    verify "$version"
    mkdir -p release-notes
    notes="release-notes/v$version.md"
    [ -f "$notes" ] || printf '## Highlights\n\n## Upgrading\n\nconfig_version: unchanged.\n' > "$notes"
    git add -A apps/engine/pyproject.toml apps/cli/pyproject.toml apps/website/package.json \
      apps/website/package-lock.json uv.lock "$notes"
    git commit --quiet -m "Release v$version"
    echo "edit $notes, amend, then: git push -u origin release/v$version and open a pull request"
    ;;
  tag)
    clean_main
    version=$(sed -nE 's/^version = "(.*)"/\1/p' apps/engine/pyproject.toml)
    verify "$version"
    git rev-parse -q --verify "refs/tags/v$version" >/dev/null && { echo "v$version already exists"; exit 1; }
    git tag -a "v$version" -m "v$version"
    git push origin "v$version"
    echo "pushed v$version: CD builds the image, Release publishes the GitHub release"
    ;;
  verify)
    verify "${2:?usage: release.sh verify X.Y.Z}"
    ;;
  *)
    sed -n '2,11p' "$0"; exit 1
    ;;
esac
