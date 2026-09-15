"""The image: every path deploy/Dockerfile copies survives .dockerignore.

An excluded source makes COPY fail, but only once the layer is built without a cache hit, so a
build cache can hide it for as long as the copied file does not change.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "deploy" / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def patterns() -> list[str]:
    """The .dockerignore patterns in file order, comments and blank lines dropped."""
    lines = DOCKERIGNORE.read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def copied() -> list[str]:
    """Every build context path a COPY instruction reads, the destination dropped."""
    sources = []
    for line in DOCKERFILE.read_text().splitlines():
        match = re.match(r"^COPY\s+(.*)$", line.strip())
        if not match:
            continue
        words = [word for word in match.group(1).split() if not word.startswith("--")]
        sources.extend(words[:-1])
    return sources


def ignored(path: str, rules: list[str]) -> bool:
    """Whether .dockerignore excludes the path. The last rule that matches decides.

    Covers the forms this .dockerignore uses: a literal path, a glob, and a ! negation, each
    matching the path itself or any directory above it.
    """
    parts = PurePosixPath(path).parts
    ancestors = ["/".join(parts[:depth]) for depth in range(1, len(parts) + 1)]
    verdict = False
    for rule in rules:
        negated = rule.startswith("!")
        pattern = rule[1:] if negated else rule
        if any(fnmatch(ancestor, pattern) for ancestor in ancestors):
            verdict = not negated
    return verdict


def test_every_copied_path_exists_and_is_not_excluded():
    rules = patterns()
    for source in copied():
        assert (ROOT / source).exists(), source
        assert not ignored(source, rules), source


def test_the_matcher_reads_the_rules_this_dockerignore_uses():
    rules = ["apps/cli", "!apps/cli/pyproject.toml", "*.egg-info"]
    assert ignored("apps/cli/units.py", rules)
    assert not ignored("apps/cli/pyproject.toml", rules)
    assert ignored("cli.egg-info/PKG-INFO", rules)
    assert not ignored("apps/engine/pyproject.toml", rules)
