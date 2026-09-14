---
name: check
description: Run the repo gate and fix what it reports. Use before claiming any change is done, and whenever a commit is about to be made.
---

# check

```
just check
```

Runs `check-python`, in order `ruff format --check`, `ruff check`, `scripts/check-deps.sh` (the
import-linter contracts), `mypy --strict`, `pytest -m "not integration"`; then `check-website`,
eslint and `tsc --noEmit` over `apps/website`. Run the half you touched while iterating.

Fix at the source. A `noqa` or a `type: ignore` gets the narrowest possible scope and a one-line
reason, and only when the constraint comes from a dependency's fixed signature.

A layering failure means either the import is wrong or the rule changed. If the rule changed, edit
the contracts in `pyproject.toml` and `docs/ARCHITECTURE.md` in the same commit. Never widen a
contract to make a red build green.

`just test integration` is separate and needs `just up` and `just migrate`. CI runs it.

A change under `.github/` also runs `uvx --from actionlint-py actionlint`; `tests/test_repo.py`
in the gate holds the workflows, rulesets and recipes to each other.

A change to a mermaid diagram in `docs/` also needs `just diagrams`; a change to
`apps/cli/assets` needs `just web-frames` and the regenerated `cli-frames.ts` committed with it.
