# User stories

What officers ask Zipy, and what it does. Each is a candidate eval case (see the v1.0 roadmap).

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
