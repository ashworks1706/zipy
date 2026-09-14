---
name: add-tool
description: Add a new integration to Zipy - a tool plugin the model can call, and its provider plugin if it needs a new account type. Use when asked to add Trello, GitHub, Canvas, Google Sheets or any other integration, or a new action to an existing tool.
---

# add-tool

A tool is a folder under `apps/engine/tools/` and a `[tools.<name>]` table. An account type is a
folder under `apps/engine/auth/providers/` and a `[providers.<name>]` table. Both are discovered.
Nothing in the gateway, agent, API, workers, or another plugin changes.

## A new provider (only if no existing provider covers the account)

1. `apps/engine/auth/providers/<name>/__init__.py` and `provider.py`: a `BaseProvider` subclass
   with `name = "<name>"`, `owns` (its SDK, if any), and a `<Name>Settings` model holding
   `client_id` and `client_secret: SecretStr` plus anything else it needs. Implement
   `authorize_url`, `exchange`, `refresh`, and `webhook` if the provider pushes events.
2. `zipy.toml`: `[providers.<name>]` with `enabled = true`.
3. `.env.example`: `ZIPY_PROVIDERS__<NAME>__CLIENT_ID` and `__CLIENT_SECRET`.
4. `deploy/README.md` needs nothing: redirects are `/auth/<name>/callback` for every provider.

## A new tool

1. `apps/engine/tools/<name>/` with:
   - `__init__.py`: one-line docstring naming the service and what the tool does.
   - `schemas.py`: `<Name>Settings` (every key its table has besides enabled, provider, scopes and
     actions), one params and one result model per action. Every model is `extra="forbid"`.
   - `client.py`: the provider API. Takes a `ProviderAuth` and the settings. One async method per
     action. Failures raise `ToolError`; an expired or revoked token raises `CredentialError`.
   - `tool.py`: a `BaseTool[<Name>Settings]` with `name`, `provider` (a provider plugin name, or
     omitted), `owns` (every third-party library the folder imports), `settings_model`, `actions`,
     and `execute` dispatching to the client. Override `target` so audit entries and confirmation
     prompts say what an action touches.
   - `tests/test_<name>.py`: params parse real requests from the user stories; client methods
     against recorded or hand-written responses, never the live API.
2. `zipy.toml`: `[tools.<name>]` with provider, enabled, scopes, the settings at their defaults,
   and `[tools.<name>.actions]` giving every action a type. Anything that changes or removes data
   the org already has is `destructive`.
3. Searchable content: `syncs = True`, implement `documents()`, and `sync_hours` in the table and
   settings. The workers and memory pick it up.
4. `apps/engine/pyproject.toml`: add `engine.tools.<name>` (and the provider package) to packages.
5. `just check` (test_plugins proves isolation and ownership), then `just plugins`.

## Scopes

Ask for the least access the actions need. Read-only by default; a write scope only when an action
of type create or destructive needs it, and say so in the table's comment.

## Never

- Let the model choose an action type, or put one in the tool class.
- Put a token, header or raw credential in a params or result model.
- Import another tool, or a library another plugin owns.
- Add the tool name to an enum, an if-chain, or a list anywhere outside its folder and its table.
