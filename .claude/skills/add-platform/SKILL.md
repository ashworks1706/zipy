---
name: add-platform
description: Add a chat platform Zipy lives on (Slack, Microsoft Teams, Telegram, a web chat) as a platform plugin. Use when asked to support a new chat app, or to extend what an existing platform renders.
---

# add-platform

A platform is a folder under `apps/engine/platforms/` and a `[platforms.<name>]` table. It
translates events in and renders gateway output. It knows nothing about orgs, tools, models or
memory, and the gateway knows nothing about it beyond its name and capabilities.

## Steps

1. `apps/engine/platforms/<name>/__init__.py` and `platform.py`: a `BasePlatform` subclass with
   `name = "<name>"`, `owns` (the platform SDK), and `<Name>Settings` with its secrets as
   `SecretStr` and `message_limit`.
2. `capabilities`: the markup the platform renders, its message limit, and whether it has buttons,
   threads and direct messages. Be exact; the gateway shapes output from this and nothing else.
3. Inbound, in `run()` for an outward connection (websocket, polling) or `router()` for HTTP
   events, mounted at `/platforms/<name>`:
   - a mention, a direct message, or a reply in a thread Zipy is in becomes `Inbound`, with the
     platform's own ids as strings in `ChannelRef` and `MemberRef`;
   - a confirm or cancel becomes `InboundAnswer`;
   - an install becomes `WorkspaceInstalled`.
   An HTTP route verifies the platform's signature before anything else.
4. Outbound, in `send()`: `Text` as a message (privately when `private_to` is set) and
   `ConfirmPrompt` as the platform's native prompt, in `render.py`.
5. `recent()`: the last messages of a conversation, oldest first, Zipy's own as assistant. A
   thread is its own conversation where the platform has threads.
6. A per-workspace bot token (Slack) is sealed into the workspace row at install, never kept in
   settings.
7. `zipy.toml`: `[platforms.<name>]` with `enabled` and `message_limit`. `.env.example`:
   `ZIPY_PLATFORMS__<NAME>__*` for each secret.
8. `apps/engine/pyproject.toml`: the SDK in dependencies, `engine.platforms.<name>` in packages.
9. Tests against recorded payloads: every inbound shape maps to the right gateway message, a bad
   signature is rejected, a long reply renders within the limit.
10. `just check`, then `just plugins`.

## Never

- Put org, role, rate limit, admin command or tool logic in a platform. That is the gateway's.
- Compare a platform name anywhere outside the platform's own folder.
- Store message history. The platform is the store.
- Import another platform, or a library another plugin owns.
