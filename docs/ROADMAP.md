# Roadmap

Each phase ends with something an org can use. A step is done when a test or a real run in a
chat workspace shows it, not when its code exists.

A step whose code is written and tested against a stand-in for a third party, but which has not
yet run against the real Discord, Google, Notion or Zoom, is left unticked and marked (built).
The stand-in proves the code, not that the provider agrees with it.

## v0.1 Skeleton

- [x] Repo in the house layout: uv workspace, justfile, gate, import contracts, CI, compose
- [x] zipy.toml with every table, the tool action types, and the config loader
- [x] Protocols and doubles for every seam
- [x] Tool registry: discovery, config match, per-org merge, function schemas
- [x] Platform-neutral core: org and workspace identity, the gateway, plugin discovery for
      platforms, providers and tools, plugin isolation tests
- [x] Scaffolded layers, plugins and the console
- [x] First alembic migration from `engine/data/tables.py`; IVFFlat index created after data exists

## v0.2 Talks back

- [x] Postgres repositories: orgs, workspaces, members, org_context, audit_log, confirmations
- [ ] (built) LiteLLM chat client per model role with spend in Usage; structlog with org and member bound
- [x] Gateway: org and role resolution, rate limit, admin command dispatch, reply splitting
- [ ] (built) Discord platform: mentions and DMs to Inbound, install to WorkspaceInstalled, history, send
- [x] Orchestrator loop with conversation memory and org facts, and tool calls
- [x] `@Zipy remember`, `@Zipy status`; budget and rate limit enforced before the model call
- [ ] (built) LangFuse traces for every model call; Sentry for errors

## v0.3 Calendar and Drive

- [x] Credential vault (Fernet) and the credentials repository
- [ ] (built) Google OAuth: signed state, DM link, callback, token refresh worker
- [x] Executor: permission, credential, validation, audit
- [ ] (built) Calendar tool: list, free slots, create; update and delete behind confirmation
- [x] Confirmation prompts: Discord buttons, typed answers for platforms without, expiry, cleanup
- [ ] (built) Drive tool: search and list folder, read-only scope
- [ ] (built) `@Zipy setup` wizard and `@Zipy connect google`

## v0.4 Notion and campus search

- [ ] (built) Notion OAuth and tool: query database, get page, create page, update page confirmed
- [ ] (built) Search tool: web search and the campus organization portal
- [x] `@Zipy enable`, `@Zipy disable`, `@Zipy config <tool> <key> <value>`
- [ ] Role overrides per org

## v0.5 Slack

- [ ] Slack platform: Events API router with signing verification, per-workspace OAuth install,
      sealed bot tokens, Block Kit confirmations, threads as conversations; add slack-sdk to owns
- [ ] Linking a second workspace to an existing org with a one-time admin code
- [ ] The same eval cases passing on Discord and Slack

## v0.6 Memory

- [x] Chunking, embedding and the documents repository with pgvector search
- [x] Recall triggered by keyword, injected as RELEVANT PAST CONTEXT
- [ ] Zoom provider webhook to document jobs; Drive and Notion documents() and periodic sync
- [ ] Summary model role for transcripts; retention pruning
- [ ] Cross-tool digests: "what's happening this week", exec meeting rundown

## v1.0 Any org can self-host it

- [ ] Production compose on an Oracle Cloud free tier ARM box, behind Caddy
- [ ] Uptime Kuma alerts into the org's chat
- [ ] Setup guide an officer with no ops background can follow in under an hour
- [ ] Eval cases from the user stories in docs/ARCHITECTURE.md, run before every release

## Out of scope

- A general assistant: essays, images, trivia
- Replacing Notion or Google Calendar as the system of record
- A hosted SaaS, pricing, or an enterprise tier
- Local GPU inference
- Sub-agents per integration
- Storing chat history from any platform
- Features that work on only one platform when the gateway could offer them on all
