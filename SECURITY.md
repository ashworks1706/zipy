# Security

Zipy holds OAuth tokens for student orgs' shared Google, Notion and Zoom accounts, and can change
their calendars and pages. Please report anything that could expose those or act without
permission.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/ashworks1706/zipy/security/advisories/new).
Do not open a public issue. Expect an acknowledgement within a week. Zipy is pre-1.0; only the
latest release and `main` are supported.

## In scope

- one org reaching another org's data, credentials, facts or recalled documents
- a token, key or secret reaching a model prompt, a log line, a trace, a metric or a chat message
- a destructive action running without its confirmation, or confirmed by someone without the role
- OAuth state, webhook or platform event signatures that can be forged or replayed
- prompt injection through org content that leads to an action a member did not ask for

## Model

- The tenant is the org; every query is scoped by `org_id`, resolved from the workspace.
- Credentials and per-workspace bot tokens are encrypted at rest with Fernet
  (`ZIPY_DATA__FERNET_KEY`) and decrypted only at use. Secrets come from the environment only.
- Action types (read, create, destructive) are fixed in `zipy.toml`, never chosen by the model;
  destructive actions need a confirmation that expires.
- Every tool execution is written to an append-only audit log.
- Content from org accounts reaches the model only as tool results or recalled context, never the
  system prompt.
- Each deployment is self-hosted; no telemetry is sent to the project.

## Dependencies

pip-audit and npm audit weekly and on dependency changes, dependency review on pull requests,
gitleaks on every push, Dependabot weekly. Images carry an SBOM and a build provenance attestation.
