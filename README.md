<p align="center">
  <img width="1921" height="418" alt="image" src="https://github.com/user-attachments/assets/eea84b08-15c5-407b-9888-10521b8a0145" />
</p>

<p align="center">
    <b>The AI officer for student orgs</b>
</p>

<p align="center">
    <a href="https://github.com/ashworks1706/zipy/actions/workflows/ci.yml"><img src="https://github.com/ashworks1706/zipy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12">
</p>

<p align="center">
    <a href="docs/ARCHITECTURE.md">Architecture</a> •
    <a href="deploy/README.md">Self-host</a> •
    <a href="docs/ROADMAP.md">Roadmap</a>
</p>

---

> **Status:** being rebuilt from scratch. The layout, config, contracts and tests are in place;
> most modules are scaffolds. See the [roadmap](docs/ROADMAP.md).

Zipy is an open-source AI operations officer for university student organizations. It lives in the chat app the org already uses: Discord today, with Slack and others as plugins. Instead of officers juggling six tabs — Notion for tasks, Google Calendar for events, Google Drive for documents, Zoom for meeting recordings — they type one message and Zipy handles the rest.

It's not a chatbot. It reads your org's Notion databases, creates calendar events, searches your Drive, summarizes Zoom meetings, and tracks who asked for what. It knows your org's structure because you tell it once and it remembers.

Any university org can self-host it for free. Each org can link its Discord server, its Slack workspace, or both. Zipy connects to the org's shared accounts (not individual officers' personal accounts), so when the VP of Events graduates and a new officer takes over, nothing breaks. The org's context, integrations, and memory persist across officer turnover, and across platforms.

```
@Zipy when's the deadline for the next budget request?
@Zipy add an event next Tuesday 6pm, intro to LLMs workshop, CPCOM 210, invite sarah@asu.edu
@Zipy what did we decide about sponsorships in the last exec meeting?
@Zipy remember our budget tracker is the Notion database called Finance Tracker
```

## How it works

An officer types something like `@Zipy when's the deadline for the next budget request?` in their Discord server or Slack workspace.

Here's what happens behind the scenes:

1. The platform plugin catches the message and hands it to the gateway, which finds the org the workspace belongs to and who sent it (their role — admin, officer, or member).

2. It pulls context from three places. First, the last 20 messages in the channel so the LLM knows what "that" or "this" refers to. Second, the org's persistent facts — things like "budget requests are tracked in the Notion database called Finance Tracker" and "exec board meets Fridays at 3pm." Third, if the question sounds like it's about something historical ("what did we decide last month"), it runs a semantic search against stored documents — past Zoom transcripts, indexed Notion pages, Drive docs.

3. All of that context, plus the list of tools the org has connected, gets assembled into a system prompt and sent to a language model (Qwen, running on a cheap inference API like SiliconFlow or OpenRouter — not locally, because GPU servers cost too much for a student org budget).

4. The model decides what to do. For this question, it would call `notion.query_database` with the Finance Tracker database ID (which it already knows from the org context). If the question were "add an event Friday at 3pm," it would call `calendar.create_event`.

5. For read operations and creates, Zipy executes immediately. For destructive actions — updating, deleting, reassigning — it asks for confirmation with confirm and cancel buttons. The officer clicks confirm, then it executes. Confirmations expire after 2 minutes so stale buttons don't sit around.

6. The tool executor fetches the org's encrypted API credentials from the database, decrypts them, calls the external API (Google, Notion, Zoom, whatever), logs the action to an audit trail, and returns the result.

7. The result goes back to the LLM for a second call — this time just to format the raw API response into a human-readable message in the platform's own formatting. "The next budget request is due October 4th. It's tracked in the Finance Tracker database in Notion."

8. Every step — the prompt, the tool calls, the API responses, the final output — gets recorded in LangFuse so when something goes wrong, you can replay exactly what happened.

## Quick start

Needs [just](https://just.systems), [uv](https://docs.astral.sh/uv) and Docker.

```
just bootstrap          # .env, git hooks, dependencies
just fernet-key         # paste into ZIPY_DATA__FERNET_KEY in .env, with a platform token and model key
just up                 # postgres and redis
just migrate            # tables
just serve              # every enabled platform, the HTTP server and the workers
```

No Discord server yet? `just chat` talks to Zipy in the terminal, and `just console` opens the
developer console with the chat, every recipe, logs and live metrics.

`just doctor` says what is missing. Self-hosting on a VPS: [deploy/README.md](deploy/README.md).

## Stack

| | |
|---|---|
| Runtime | Python 3.12, asyncio, FastAPI + uvicorn, Pydantic |
| Platforms | Discord; Slack next; a terminal platform for development; each a plugin |
| Models | LiteLLM to any provider; Qwen on OpenRouter or SiliconFlow by default |
| Integrations | Google Calendar and Drive, Notion, Zoom, web and campus search; each a plugin |
| Data | PostgreSQL 16 + pgvector, Redis 7, Alembic |
| Observability | per-request trace files, LangFuse, Prometheus + Grafana, Sentry, structlog, Uptime Kuma |
| Tooling | uv, just, ruff, mypy strict, import-linter, pytest, a Textual developer console |
| Website | Next.js, React, Tailwind, TypeScript (`apps/website`, `just web`) |
| Deploy | Docker Compose on one box, no GPU |

The full table, with where each piece lives, is in [Tech stack](docs/ARCHITECTURE.md#tech-stack).

## What it does

**Calendar and scheduling:**

"When's the next exec board meeting?" — Zipy checks Google Calendar, finds the next event matching "exec board," and responds with the date, time, and location.

"Add an event to calendar inviting me and sarah@asu.edu — workshop on intro to LLMs, next Tuesday 6pm, room CPCOM 210." — Zipy creates the event in Google Calendar with both attendees, the room, and a default 1-hour duration. Sends back a confirmation with the event link.

"Can you readjust events this week? I want them to have 5-hour gaps between them." — Zipy fetches all events for the week, calculates new start times with 5-hour spacing, and posts a confirmation showing the before/after. Officer clicks confirm, Zipy updates each event. This is a multi-turn tool-calling loop — the LLM fetches, reasons, then writes.

"Am I free Thursday between 2 and 5?" — Checks the org calendar for conflicts in that window and responds with available slots.

**Notion and task management:**

"When do I have to submit the next budget request?" — Zipy queries the Finance Tracker Notion database, finds the next upcoming deadline, and responds with the date and any notes attached.

"Add Ben to this todo — I need to work with him on the sponsorship outreach." — Zipy updates the relevant Notion page, adding Ben as an assignee. If it's not clear which todo, it asks.

"What's the status of our event planning tasks?" — Queries the Notion database filtered by status, returns a summary of open, in-progress, and completed tasks.

"Create a new task: design the flyer for the AI workshop, assign to Maria, due next Friday." — Creates a new page in the org's task database with the right properties filled in.

**Google Drive:**

"Can you point me to where the officer contact list sheet is?" — Searches the org's connected Google Drive for files matching "officer contact list" and returns the file name and link.

"What's in the Events folder?" — Lists the contents of the specified Drive folder with file names and last-modified dates.

"Find the budget spreadsheet from last semester." — Searches Drive with relevant keywords and returns matching files.

**Zoom:**

"Please summarize the latest Zoom meeting we had." — Zipy checks its indexed transcripts (ingested automatically when Zoom sends a recording.completed webhook), retrieves the most recent one for the org, and sends the LLM a summarization prompt against the transcript chunks.

"What did we decide about sponsorships in the last exec meeting?" — Semantic search against stored transcript embeddings, retrieves relevant chunks, and has the LLM synthesize an answer.

**Web search and campus info:**

"What other clubs are doing AI and robotics stuff at ASU right now?" — Zipy searches the campus portal (Sun Devil Central or similar) for active organizations matching those keywords and summarizes what it finds.

"Look up the room booking policy for the MU building." — Web search targeting the university's facilities page, returns relevant info.

**Cross-tool queries:**

"What's happening this week?" — Zipy pulls from Google Calendar (upcoming events), Notion (open tasks with due dates this week), and optionally recent Zoom summaries, then compiles a digest.

"Prepare me a rundown for tomorrow's exec meeting — what's on the agenda, what tasks are due, and any notes from last week's meeting." — Multi-tool query: Calendar for the meeting details, Notion for due tasks, semantic search for last week's meeting notes.

**Org administration:**

"@Zipy setup" — Starts the onboarding wizard. Walks the admin through connecting Google, Notion, and Zoom via OAuth links sent privately.

"@Zipy remember our budget tracker is the Notion database called Finance Tracker" — Stores this as persistent org context so Zipy knows where to look for budget-related questions going forward.

"@Zipy status" — Shows what integrations are connected, what tools are enabled, current month's token usage, and any issues.

"@Zipy enable zoom" — Enables the Zoom tool module for this org (after credentials are connected).

## What this is not

Zipy is not a general-purpose AI assistant. It doesn't write essays, generate images, or answer random trivia. It's a specialized operations agent scoped to the tools and data your org has connected. If you ask it something outside its capabilities, it'll say so.

It's also not a replacement for Notion or Google Calendar. Those are your systems of record. Zipy is the natural language interface sitting on top of them, making them accessible from chat without context-switching.

And it's not a SaaS product. It's open-source infrastructure that any org can self-host. There's no pricing page, no vendor lock-in, no "enterprise tier." The whole thing runs on a free Oracle Cloud instance if you want it to.

## Working on Zipy

Read [CONTRIBUTING.md](CONTRIBUTING.md) for branches, pull requests, CI and releases, and
[AGENTS.md](AGENTS.md) for the commands, the dependency rule and the rules every change follows.
`just check` is the gate. Platforms, account providers and tools are plugins: a folder and a table
in `zipy.toml` each; see [Extension points](docs/ARCHITECTURE.md#extension-points).

## License

[Apache 2.0](LICENSE)
