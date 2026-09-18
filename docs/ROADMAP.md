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
- [x] Attached files read into text and stored for recall: pdf, docx, pptx, xlsx, csv, json, zip
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

Built and shipped off. A compact, per-person state derived from how someone works, not from what
they say about themselves, conditioning the agent per member. Chat history stays unstored, so the
state updates from behaviour and keeps none of the text behind it.

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
- Features that work on only one platform when the gateway could offer them on all
