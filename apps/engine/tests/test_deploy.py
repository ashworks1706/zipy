"""The images: what deploy/Dockerfile copies, and what the sandbox image can run.

An excluded source makes COPY fail, but only once the layer is built without a cache hit, so a
build cache can hide it for as long as the copied file does not change. The sandbox image
carries the parsers without the engine, so a parser that grows an engine import breaks it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
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


SANDBOX_DOCKERFILE = ROOT / "deploy" / "sandbox" / "Dockerfile"

#: The parser modules the sandbox image carries, in the order its Dockerfile copies them.
SANDBOX_PARSERS = ("errors", "registry", "text", "pdf", "office", "archive")


def _laid_out(root: Path) -> Path:
    """The sandbox image's /opt/zipy, built the way its Dockerfile builds it."""
    package = root / "parsers"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for name in SANDBOX_PARSERS:
        source = ROOT / "apps" / "engine" / "memory" / "ingest" / "parsers" / f"{name}.py"
        body = source.read_text().replace("engine.memory.ingest.parsers", "parsers")
        (package / f"{name}.py").write_text(body)
    (root / "extract.py").write_text((ROOT / "deploy" / "sandbox" / "extract.py").read_text())
    return root


def test_the_sandbox_dockerfile_copies_every_parser_module():
    written = SANDBOX_DOCKERFILE.read_text()
    for name in SANDBOX_PARSERS:
        assert f"parsers/{name}.py" in written, name


def test_no_parser_reaches_the_engine_once_the_image_has_rewritten_its_imports(tmp_path):
    """The image carries the parsers and no engine package.

    Its Dockerfile rewrites engine.memory.ingest.parsers to parsers. Any other engine import
    survives that rewrite and breaks the image the first time someone attaches a file.
    """
    package = _laid_out(tmp_path) / "parsers"
    for name in SANDBOX_PARSERS:
        for line in (package / f"{name}.py").read_text().splitlines():
            stripped = line.strip()
            assert not stripped.startswith(("from engine", "import engine")), f"{name}.py: {line}"


def test_the_laid_out_package_imports_with_no_engine_on_the_path(tmp_path):
    root = _laid_out(tmp_path)
    done = subprocess.run(
        [sys.executable, "-c", "import extract"],
        capture_output=True,
        text=True,
        cwd=root,
        env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_the_extractor_reads_a_file_the_way_the_image_will(tmp_path):
    root = _laid_out(tmp_path)
    (root / "notes.txt").write_text("Budget due 30 September")

    done = subprocess.run(
        [sys.executable, str(root / "extract.py"), str(root / "notes.txt"), "text/plain", "1000"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["text"].strip() == "Budget due 30 September"


def test_the_extractor_says_why_rather_than_printing_a_traceback(tmp_path):
    root = _laid_out(tmp_path)
    (root / "broken.pdf").write_bytes(b"not a pdf at all")

    done = subprocess.run(
        [
            sys.executable,
            str(root / "extract.py"),
            str(root / "broken.pdf"),
            "application/pdf",
            "1000",
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
        check=False,
    )

    assert done.returncode == 1
    assert "could not be read" in json.loads(done.stdout)["error"]
    assert "Traceback" not in done.stdout


def test_the_extractor_refuses_a_type_no_parser_reads(tmp_path):
    root = _laid_out(tmp_path)
    (root / "a.exe").write_bytes(b"MZ")

    done = subprocess.run(
        [
            sys.executable,
            str(root / "extract.py"),
            str(root / "a.exe"),
            "application/x-msdownload",
            "1000",
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
        check=False,
    )

    assert done.returncode == 1
    assert "nothing here reads" in json.loads(done.stdout)["error"]
