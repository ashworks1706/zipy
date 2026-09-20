"""The repository wiring: workflows, branch rules, recipes and versions agree with each other."""

import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _recipes() -> set[str]:
    text = (ROOT / "justfile").read_text()
    return set(re.findall(r"^([a-z][\w-]*)(?:\s[^:\n]*)?:(?!=)", text, re.MULTILINE))


def _workspace_members() -> list[str]:
    """Every app the uv workspace holds."""
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return root["tool"]["uv"]["workspace"]["members"]


def test_the_image_copies_every_workspace_manifest_the_lockfile_is_checked_against():
    """uv sync --locked re-resolves when a member's pyproject is missing, and then refuses."""
    dockerfile = (ROOT / "deploy/Dockerfile").read_text()
    ignore = (ROOT / ".dockerignore").read_text()
    for member in _workspace_members():
        assert f"COPY {member}/pyproject.toml" in dockerfile, (
            f"deploy/Dockerfile does not copy {member}/pyproject.toml; the image build will fail"
        )
        if f"\n{member}\n" in f"\n{ignore}":
            assert f"!{member}/pyproject.toml" in ignore, (
                f".dockerignore excludes {member} without keeping its pyproject.toml"
            )


def test_the_ci_job_needs_every_other_job_so_none_is_forgotten():
    jobs = _workflow("ci.yml")["jobs"]
    assert set(jobs["ci"]["needs"]) == set(jobs) - {"ci"}
    assert jobs["ci"]["if"] == "always()"


def test_the_required_status_check_is_the_ci_job():
    ruleset = json.loads((ROOT / ".github/rulesets/main.json").read_text())
    rules = {rule["type"]: rule for rule in ruleset["rules"]}
    checks = rules["required_status_checks"]["parameters"]["required_status_checks"]
    assert [c["context"] for c in checks] == [_workflow("ci.yml")["jobs"]["ci"]["name"]]
    assert {"deletion", "non_fast_forward", "pull_request"} <= set(rules)
    assert rules["pull_request"]["parameters"]["required_review_thread_resolution"]


def test_merge_methods_match_between_the_ruleset_and_the_settings():
    ruleset = json.loads((ROOT / ".github/rulesets/main.json").read_text())
    pull_request = next(r for r in ruleset["rules"] if r["type"] == "pull_request")
    settings = json.loads((ROOT / ".github/settings.json").read_text())
    keys = {
        "squash": "allow_squash_merge",
        "merge": "allow_merge_commit",
        "rebase": "allow_rebase_merge",
    }
    enabled = {method for method, key in keys.items() if settings[key]}
    assert enabled == set(pull_request["parameters"]["allowed_merge_methods"])


def test_every_just_recipe_a_workflow_runs_exists():
    recipes = _recipes()
    for path in WORKFLOWS.glob("*.yml"):
        for command in re.findall(r"\bjust ([a-z][\w-]*)", path.read_text()):
            assert command in recipes, f"{path.name} runs just {command}"


def test_every_script_a_workflow_or_hook_runs_exists_and_is_executable():
    sources = [*WORKFLOWS.glob("*.yml"), *(ROOT / ".githooks").iterdir(), ROOT / "justfile"]
    for source in sources:
        for script in re.findall(r"\./(scripts/[\w.-]+)", source.read_text()):
            path = ROOT / script
            assert path.exists(), f"{source.name} runs {script}"
            assert path.stat().st_mode & 0o111, f"{script} is not executable"


def test_every_action_is_pinned_to_a_version():
    for path in WORKFLOWS.glob("*.yml"):
        for use in re.findall(r"uses: (\S+)", path.read_text()):
            assert re.search(r"@v\d", use), f"{path.name}: {use} is not pinned to a version"


def test_ci_paths_cover_every_app():
    filters = (WORKFLOWS / "ci.yml").read_text()
    for app in (ROOT / "apps").iterdir():
        if app.is_dir():
            assert f"apps/{app.name}/" in filters, f"no CI path filter covers apps/{app.name}"


def test_every_version_in_the_repo_agrees():
    versions = {}
    for app in ("engine", "cli", "testbed"):
        found = re.search(
            r'^version = "(.*)"', (ROOT / f"apps/{app}/pyproject.toml").read_text(), re.M
        )
        assert found, f"apps/{app}/pyproject.toml has no version"
        versions[app] = found.group(1)
    versions["website"] = json.loads((ROOT / "apps/website/package.json").read_text())["version"]
    assert len(set(versions.values())) == 1, versions


def test_dependabot_covers_every_ecosystem_in_the_repo():
    ecosystems = {
        u["package-ecosystem"]
        for u in yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())["updates"]
    }
    assert {"uv", "npm", "github-actions", "docker"} <= ecosystems


def test_ci_runs_the_python_gate_when_the_eval_cases_change():
    """The gate holds cases.toml to the stories, so a change to either must run it."""
    filters = (WORKFLOWS / "ci.yml").read_text()
    for path in ("evals/**", "docs/USER_STORIES.md"):
        assert f"'{path}'" in filters, f"no CI path filter covers {path}"
