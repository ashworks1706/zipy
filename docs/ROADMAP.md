# Roadmap

Each phase ends with something an org can use. A step is done when a test or a real run in a
chat workspace shows it, not when its code exists.

A step whose code is written and tested against a stand-in for a third party, but which has not
yet run against the real Discord, Google, Notion or Zoom, is left unticked and marked (built).
The stand-in proves the code, not that the provider agrees with it.

## v0.2 Answers

- [ ] (built) LiteLLM chat client per model role with spend in Usage; structlog with org and member bound
- [ ] (built) Discord platform: mentions and DMs to Inbound, install to WorkspaceInstalled, history, send
- [ ] (built) LangFuse traces for every model call; Sentry for errors

## v0.3 Google Workspace

- [ ] (built) Google OAuth: signed state, DM link, callback, token refresh worker
- [ ] (built) `@Zipy setup` wizard and `@Zipy connect google`
- [x] MCP seam: one streamable-HTTP client, a committed catalog per server, action types pinned
      in zipy.toml rather than taken from the server's annotations
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
- [x] Attached files read into text and stored for recall: pdf, docx, pptx, xlsx, csv, json, zip
- [x] A sandbox tool: a sealed container per command, sessions named by the member, the runtime
      as the session registry, idle reaping, and `just down` removing every one
- [x] On by default: `just bootstrap` builds the image, a `sandboxd` sidecar gives compose a
      runtime, and a boot probe degrades loudly where there is none
- [x] A sub-agent gets its own sandbox workspace, reaped when it ends. Its loop stays in the
      engine: a container holding the model's network and the org's tokens is not a sandbox
- [x] Attached files parsed inside the sandbox, not in the engine process, behind files.sandbox
- [x] The console shows live sessions and what each is running, and can kill one or all
- [x] One level of delegation: a named subtask, a subset of the tools, its own turn limit, and a
      destructive call inside it suspends and resumes

## v0.6 Benchmark

- [ ] run on existing benchmarks
- [ ] make short tech writeup on readme
- [x] Eval cases from the user stories, scored on correctness and behaviour, over fixtures
- [x] `zipy eval-add` drafts a case from a real request's trace
- [x] `apps/training`: traces to examples, reviewed one at a time, curated set, SFT
- [ ] A model post-trained on curated runs, kept only if the eval suite says it helps

## v0.7 Collaboration state

Built and shipped off, deliberately: the code is in and the switch is false until the contrast
table earns it.

A compact, per-person state derived from how someone works, not from what they say about
themselves, conditioning the agent per member. Chat history stays unstored, so the state updates
from behaviour and keeps none of the text behind it. It moves tone and autonomy and never a
permission: the three unticked items below are the evidence the claim still owes, not backlog.

Conditioning goes through a renderer chosen by what the endpoint accepts. Text is built and works
on every tier. A prefix in embedding space, which would condition the model below the text, needs
a serving tier that takes input embeddings (vLLM or SGLang); it is a renderer and a tier, not a
change to the loop. It is worth building only if the contrast table says text conditioning is what
limits the adaptation.

- [x] Per-member profile: named dimensions with the observation count behind each
- [x] Derived from behaviour: confirmation outcomes, and what a turn following an answer asks for
- [x] Readable and correctable by the person it describes, with `prefer`
- [x] Conditions the prompt behind a switch, off until the evals say it earns its place
- [x] A conditioning seam: one renderer per endpoint capability, text built
- [ ] Run the contrast table against a real model and decide whether it ships on
- [ ] A team-level state under the person's, for norms one person did not set
- [ ] Measured by the behaviour axis of the eval suite: same question, same model, different
      member, behaviour moves and correctness holds

## v1.0 Any org can self-host it

- [ ] Production compose on an Oracle Cloud free tier ARM box, behind Caddy
- [ ] Uptime Kuma alerts into the org's chat
- [ ] Setup guide an officer with no ops background can follow in under an hour
- [ ] The eval suite run before every release, with its baseline in the release notes

## Out of scope

- A general assistant: essays, images, trivia
- Replacing Notion or Google Calendar as the system of record
- A hosted SaaS, pricing, or an enterprise tier
- Sub-agents per integration, a specialist agent per tool, or any agent that exists before a
  request. One level of delegation on a named subtask is in; a fleet of standing agents is not.
- Storing chat history from any platform. The runtime keeps none: memory reads history back off
  the platform, and collaboration state records what behaviour showed rather than what was said.
  A training dataset is the one thing that holds conversation text, and it is not the runtime: it
  is built by hand from local traces, redacted, reviewed example by example, and never read by a
  request. `apps/training` is not deployed, and the engine never imports it.
- Letting an MCP server decide what an action may do. A server says what its tools take; the
  action type, the confirmation, the role check and the audit entry stay here.
- Features that work on only one platform when the gateway could offer them on all
