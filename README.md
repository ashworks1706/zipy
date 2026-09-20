<p align="center">
  <img width="1921" height="418" alt="image" src="https://github.com/user-attachments/assets/eea84b08-15c5-407b-9888-10521b8a0145" />
</p>

<p align="center"><b>Adaptive agent harness for teams</b></p>

<p align="center">
    <a href="https://github.com/ashworks1706/zipy/actions/workflows/ci.yml"><img src="https://github.com/ashworks1706/zipy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12">
</p>

<p align="center">
    <a href="docs/VISION.md">Vision</a> •
    <a href="docs/ARCHITECTURE.md">Architecture</a> •
    <a href="docs/USER_STORIES.md">User stories</a> •
    <a href="deploy/README.md">Self-host</a> •
    <a href="docs/ROADMAP.md">Roadmap</a>
</p>

Zipy is an open-source, self-hosted adaptive agent harness for teams. One agent a whole team
shares, adapting to each person individually, how much explanation they want and how readily it
acts before asking, while acting on the calendars, drives and pages the org owns. Adaptation
changes how it talks and how far it goes on its own. It never changes what needs a confirmation.

That is the bet, and [docs/VISION.md](docs/VISION.md) is one page on why it is worth making. The
per-person half of it is built and ships switched off, until the eval suite's contrast table says
the adaptation earns its place; the half that holds it, that nothing derived from a person can
move a permission or a confirmation, is a test today. The rest is the machinery both need to stand
on: the loop, the tool layer, the permissions, the memory and the traces, with the chat app as one
surface rather than the product.

It is also a testbed. Adaptation on a chat platform a team already uses, over months rather than
one annotator sitting, with the signals categorised and the conditioning behind an ablation
switch, is a place to measure user modelling in deployment rather than in a study.
[docs/VISION.md](docs/VISION.md#as-a-testbed) says what that can and cannot answer.

A team configures its agent, its tools, providers and knowledge once, and talks to it where it
already works (Discord today, Slack next), against the org's shared Google Workspace, Notion,
GitHub and Zoom accounts. Nothing breaks when an officer graduates. Built first for university
student orgs, which have the turnover to prove it.

Calendar, Drive, Gmail and cross-Workspace search run on Google's own MCP servers, so those tools
are a catalog and a table rather than a client: a new server becomes a tool without new code. What
a tool is allowed to do is never the server's call. Every action's type is pinned in `zipy.toml`,
and that is what decides whether it runs at once or waits for a confirmation.

<img width="1671" height="833" alt="image" src="https://github.com/user-attachments/assets/7a2c95a6-5387-4702-89e4-3ebb247d259a" />


Asking is one way in. Whatever the surface, the same runtime resolves the org and the asker's
role, assembles the context, runs the tool loop, holds anything destructive for a confirmation,
and writes an audit entry and a trace for every step.

```
when's the deadline for the next budget request?     notion.query_database
add an event next Tuesday 6pm, intro to LLMs         calendar.create_event
workshop, CPCOM 210, invite sarah@asu.edu
what did we decide about sponsorships last meeting?  semantic recall over stored transcripts
remember our budget tracker is the Finance Tracker   an org fact, kept for every later request
```


## How it works

1. A platform plugin hands the message to the gateway, which finds the org and the sender's role.
2. Zipy gathers the recent conversation, the org's remembered facts, and, for questions about the
   past, matching transcripts and pages.
3. The harness runs the loop: one agent picks tools (`calendar.create_event`,
   `notion.query_database`, ...) through LiteLLM, against the local `llama-server` by default or
   any hosted model.
4. Reads and creates run at once. Updates and deletes wait for a confirm button.
5. Credentials never reach the model, every action is audited, and every step is traced.

## Quick start

Needs [just](https://just.systems), [uv](https://docs.astral.sh/uv), Node 22 and Docker.

```
just bootstrap     # .env, git hooks, dependencies
just up            # postgres and redis
just model         # llama-server for chat and embeddings; no model account needed
just migrate       # tables
just serve         # every enabled platform, the HTTP server, the workers
just chat          # or talk to Zipy in the terminal, no chat app needed
just console       # every recipe, its logs, the stack and a chat, in one screen
```

`just model` downloads two small GGUFs and serves them on the CPU, which is why a fresh clone
answers without an API key. `just model-gpu` puts them on a card, and any role can be pointed at
a hosted provider with one variable. See [deploy/inference](deploy/inference/README.md).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers branches, CI and releases; [AGENTS.md](AGENTS.md) the
commands and rules. Platforms, providers and tools are plugins: a folder and a `zipy.toml` table.

## License

[Apache 2.0](LICENSE)
