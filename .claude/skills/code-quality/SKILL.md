---
name: code-quality
description: Refactoring and cleanup pass — naming for longevity, reuse over duplication, registries over enumeration, deleting dead code and silent fallbacks. Quality only, not bug hunting. User-invoked.
---

# code-quality

A cleanup pass over code that already works. Not a bug hunt — use `/systematic-debugging` for that.

Behavior must not change. If you find a bug, say so and stop; do not fold a fix into a refactor.

## What to look for

**Naming for longevity.** Names should survive the next change. A protocol named for its
capability (`ChatModel`, `CredentialStore`) outlives one named for its current implementation
(`LiteLlmChat` and `PgCredentials` are the *types*, not the protocols). A plugin named for what
it connects (`slack`, `notion`) means the next one is a new folder, not an edit. A name that describes today's implementation will be a lie next
quarter.

**Registries over enumeration.** If adding a platform or integration means editing an if-chain in three
files, the shape is wrong. One folder per case plus one config table is the target; the three
plugin kinds are the model. Ask: what does adding the *next* one cost?

**Reuse.** Duplicated logic across packages usually means the shared thing belongs one layer down.
Two near-identical functions are a question about ownership, not an invitation to write a third.

**Dead code.** Modules nothing imports, config knobs nothing reads, abstractions with one
implementation and no second in sight. Delete it — git remembers. Note the deletion in the commit
message so it can be found.

**Silent fallbacks.** A fallback that logs nothing hides a misconfiguration until it becomes a
mystery. Either it is expected (log at `debug` and document it) or it is not (log at `warn`).
Silence is the bug.

**Altitude.** A function mixing HTTP shapes with byte offsets is operating at two altitudes at
once. Split it at the layer boundary.

## What not to do

- Do not rename for taste. A rename must make a future change cheaper, and the commit message
  should say which change.
- Do not add abstraction for a second case that does not exist yet. Two implementations justify a
  trait; one is speculation.
- Do not touch public API without saying so.
- Do not reformat unrelated code — it buries the actual change.

## Zipy-specific

Check against `AGENTS.md`: does anything query without an org_id, let a credential reach a prompt
or a log, decide an action type outside `zipy.toml`, name a specific platform, provider or tool
outside its own folder and table, import a library another plugin owns, or coordinate tools
anywhere but the orchestrator? Those are the failure modes that matter most here.

## Finish

`just check` must pass. Report what you changed and why each change makes a future edit cheaper.
