# Roadmap


## v0.3 Google Workspace

- [ ] (built) Google OAuth: signed state, DM link, callback, token refresh worker
- [ ] (built) `@Zipy setup` wizard and `@Zipy connect google`
- [ ] (built) Calendar, Drive, Gmail and cross-Workspace search on Google's MCP servers; Drive
      keeps an API client for the document feed MCP has no tool for
- [ ] Offer a tool only when the org's grant carries its scopes. Today a tool is offered once its
      provider is connected, so an org that granted Google before gmail existed is offered gmail
      and learns it is missing a scope from the refusal. Reconnecting adds it, incrementally.

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
- [ ] A model post-trained on curated runs, kept only if the eval suite says it helps

## v0.7 Collaboration state

- [ ] Run the contrast table against a real model and decide whether it ships on
- [ ] A team-level state under the person's, for norms one person did not set
- [ ] Measured by the behaviour axis of the eval suite: same question, same model, different
      member, behaviour moves and correctness holds

## v1.0 Any org can self-host it

- [ ] Production compose on an Oracle Cloud free tier ARM box, behind Caddy
- [ ] Uptime Kuma alerts into the org's chat
- [ ] Setup guide an officer with no ops background can follow in under an hour
- [ ] The eval suite run before every release, with its baseline in the release notes
