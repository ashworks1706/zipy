# engine

The one Zipy process: chat platform plugins, the gateway, the agent with its tools and memory,
provider plugins, the HTTP server and the background workers. `zipy` is its command.

```
zipy serve             every enabled platform, the HTTP server, the workers
zipy chat [--jsonl]    the local platform in this terminal
zipy traces [id]       request traces under telemetry.trace_dir
zipy plugins           platforms, providers and tools checked against zipy.toml
zipy config [table]    the resolved configuration, secrets masked
zipy db <verb>         alembic: upgrade, downgrade, revision, current
```

Layers, plugins and invariants: [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md). Rules for
changing it: [AGENTS.md](../../AGENTS.md). Tests: `tests/` for the engine, `tools/<name>/tests/`
per tool.
