# Roadmap

Each phase ends with something an org can use. A step is done when a test or a real run in a
chat workspace shows it, not when its code exists.

A step whose code is written and tested against a stand-in for a third party, but which has not
yet run against the real Discord, Google, Notion or Zoom, is left unticked and marked (built).
The stand-in proves the code, not that the provider agrees with it.

## v0.2 Talks back

- [ ] (built) LiteLLM chat client per model role with spend in Usage; structlog with org and member bound
- [ ] (built) Discord platform: mentions and DMs to Inbound, install to WorkspaceInstalled, history, send
- [ ] (built) LangFuse traces for every model call; Sentry for errors

## v0.3 Calendar and Drive

- [ ] (built) Google OAuth: signed state, DM link, callback, token refresh worker
- [ ] (built) Calendar tool: list, free slots, create; update and delete behind confirmation
- [ ] (built) Drive tool: search and list folder, read-only scope
- [ ] (built) `@Zipy setup` wizard and `@Zipy connect google`

## v0.4 Notion and campus search

- [ ] (built) Notion OAuth and tool: query database, get page, create page, update page confirmed
- [ ] (built) Search tool: web search and the campus organization portal
- [ ] Role overrides per org

## v0.5 Memory

- [ ] Zoom provider webhook to document jobs; Drive and Notion documents() and periodic sync
- [ ] Summary model role for transcripts; retention pruning
- [ ] Cross-tool digests: "what's happening this week", exec meeting rundown

## v0.6 Benchmark
- [ ] run on existing benchmarks
- [ ] make short tech writeup on readme

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
