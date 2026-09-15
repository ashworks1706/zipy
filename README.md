<p align="center">
  <img width="1921" height="418" alt="image" src="https://github.com/user-attachments/assets/eea84b08-15c5-407b-9888-10521b8a0145" />
</p>

<p align="center"><b>Agent harness for team operations</b></p>

<p align="center">
    <a href="https://github.com/ashworks1706/zipy/actions/workflows/ci.yml"><img src="https://github.com/ashworks1706/zipy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12">
</p>

<p align="center">
    <a href="docs/ARCHITECTURE.md">Architecture</a> •
    <a href="docs/USER_STORIES.md">User stories</a> •
    <a href="deploy/README.md">Self-host</a> •
    <a href="docs/ROADMAP.md">Roadmap</a>
</p>

Zipy is an open-source, self-hosted agent harness for team operations: the loop, the tool
layer, the permissions, the memory and the traces that a team's agents need, with the chat app
as one surface rather than the product.

A team configures its agents, their tools, providers and knowledge once, and talks to them where
it already works (Discord today, Slack next), against the org's shared Google Calendar, Drive,
Notion and Zoom accounts. Nothing breaks when an officer graduates. Built first for university
student orgs, which have the turnover to prove it.

<img width="2372" height="1258" alt="image" src="https://github.com/user-attachments/assets/a5b9ff46-a09a-4129-81b9-8142251d953f" />


```
@Zipy when's the deadline for the next budget request?
@Zipy add an event next Tuesday 6pm, intro to LLMs workshop, CPCOM 210, invite sarah@asu.edu
@Zipy what did we decide about sponsorships in the last exec meeting?
@Zipy remember our budget tracker is the Notion database called Finance Tracker
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
