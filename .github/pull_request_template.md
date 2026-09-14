## What and why

<!-- One logical change. What it does, and why; the diff shows how. -->

## Checklist

- [ ] `just check` passes (the pre-push hook runs it)
- [ ] New behaviour has a test; anything needing Postgres or Redis is marked `integration`
- [ ] No contradiction with `docs/ARCHITECTURE.md` or `docs/ROADMAP.md`, or the doc is updated here
- [ ] A new setting is in `zipy.toml` at its default; a new secret is in `.env.example`
- [ ] A table changed shape: `config_version` is bumped and the upgrade is in the release notes
- [ ] A schema change comes with its migration
- [ ] A new plugin has its `zipy.toml` table and is listed by `just plugins`
- [ ] Nothing here lets a credential reach a prompt, a log, a trace or a metric label
