# User stories

What an org asks the runtime for, what it calls, and what the answer must carry. Each entry is an
eval case: the id is stable, the calls are real tool actions from `just plugins`, and the
expectation is what a run is scored against. See the v1.0 roadmap.

`evals/cases.toml` holds these ids and is run by `just eval`; a test holds the two files to each
other, so a story renamed here fails the gate until the case follows.

An action's type comes from `zipy.toml`, never from the model. `read` and `create` run at once;
`destructive` holds for a confirmation before anything changes.

## Calendar and scheduling

### calendar-next-meeting
> When's the next exec board meeting?

Calls `calendar.list_events` (read). Answers with the date, time and location of the next event
matching the name asked for.

### calendar-create-event
> Add an event to calendar inviting me and sarah@asu.edu — workshop on intro to LLMs, next
> Tuesday 6pm, room CPCOM 210.

Calls `calendar.create_event` (create). Both attendees, the room, and a default one-hour duration.
Answers with the event link.

### calendar-respace-week
> Can you readjust events this week? I want them to have 5-hour gaps between them.

Calls `calendar.list_events` (read), then `calendar.update_event` (destructive) per event. The
update holds for a confirmation showing before and after; nothing changes until it is answered.
The multi-turn case: read, reason, write.

### calendar-free-slots
> Am I free Thursday between 2 and 5?

Calls `calendar.find_free_slots` (read). Answers with the open windows, or says the time is taken.

## Notion and task management

### notion-next-deadline
> When do I have to submit the next budget request?

Calls `notion.query_database` (read) against the database an org fact names. Answers with the date
and any note on the row.

### notion-assign-todo
> Add Ben to this todo — I need to work with him on the sponsorship outreach.

Calls `notion.update_page` (destructive), so it holds for a confirmation. Asks which task when the
reference is ambiguous rather than guessing.

### notion-task-status
> What's the status of our event planning tasks?

Calls `notion.query_database` (read) filtered by status. Answers grouped by open, in progress and
done.

### notion-create-task
> Create a new task: design the flyer for the AI workshop, assign to Maria, due next Friday.

Calls `notion.create_page` (create) with title, assignee and due date filled in.

## Google Drive

### drive-find-file
> Can you point me to where the officer contact list sheet is?

Calls `drive.search_files` (read). Answers with the file name and its link.

### drive-list-folder
> What's in the Events folder?

Calls `drive.list_folder` (read). Answers with file names and when each was last modified.

### drive-find-by-term
> Find the budget spreadsheet from last semester.

Calls `drive.search_files` (read) with the terms from the request. Answers with the matches.

## Zoom

### zoom-latest-summary
> Please summarize the latest Zoom meeting we had.

Calls `zoom.latest_summary` (read) over transcripts already ingested by the
`recording.completed` webhook. Answers from those chunks, and says so when none are stored.

### zoom-recall-decision
> What did we decide about sponsorships in the last exec meeting?

No tool call. Semantic recall over stored transcript chunks, triggered by a phrase in
`memory.recall_triggers`. Answers from the retrieved chunks and cites nothing it was not given.

## Web search and campus info

### search-campus-orgs
> What other clubs are doing AI and robotics stuff at ASU right now?

Calls `search.campus_orgs` (read). Answers with the active organizations that match.

### search-policy
> Look up the room booking policy for the MU building.

Calls `search.web_search` (read) against the university's own pages. Answers with what it found,
not what it assumes.

## Cross-tool

### cross-week-digest
> What's happening this week?

Calls `calendar.list_events` and `notion.query_database` (both read), optionally
`zoom.latest_summary`. Answers as one digest, not three lists.

### cross-meeting-rundown
> Prepare me a rundown for tomorrow's exec meeting — what's on the agenda, what tasks are due,
> and any notes from last week's meeting.

Calls `calendar.list_events` and `notion.query_database` (read), plus semantic recall for the
notes. The widest case: three sources, one answer.

## GitHub

### github-open-issues
> What's still open on the zipy repo?

Calls `github.list_issues` (read). Answers with the numbers, titles and who each is assigned to,
pull requests marked as such.

### github-issue-detail
> What did people say on issue 14?

Calls `github.get_issue` (read). Answers with the body and the comments in order.

### github-find-issue
> Did anyone file something about the flaky CI?

Calls `github.search_issues` (read) across the org's repositories. Answers with the matches, or
says there are none.

### github-read-file
> What does the zipy README say about self-hosting?

Calls `github.get_file` (read). Answers from the file, not from memory.

### github-open-one
> Open an issue on zipy: the gate is failing on the image build.

Calls `github.create_issue` (create). Answers with the number and link of what it opened.

### github-comment
> Reply on issue 14 that I'm picking it up.

Calls `github.comment` (create). Answers with the link to the comment.

## Org administration

Admin commands, handled by the gateway. They never reach the agent and call no tool.

### admin-setup
> setup

Starts onboarding: the OAuth links for Google, Notion and Zoom, sent privately when the surface
has direct messages, and with a notice in channel when it does not.

### admin-remember
> remember our budget tracker is the Notion database called Finance Tracker

Stores an `OrgFact`, which is rendered into the system prompt of every later request for that org.
Admin only.

### admin-status
> status

What is connected, which tools are enabled, the month's spend against the budget, and anything
broken. Any member may run it.

### admin-prefer
> prefer less depth

Sets one dimension of the caller's own collaboration state, and answers with what the state now
asks for. Any member may run it, because it writes one row, their own. `prefer` alone shows the
state, `prefer forget` drops it, and all three answer that the feature is off when it is.

### admin-enable
> enable zoom

Enables a tool for the org once its provider is connected. Admin only.
