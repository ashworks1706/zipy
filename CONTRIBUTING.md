# Contributing

Zipy is collaborative agents for team logistics. Read [AGENTS.md](AGENTS.md) for the commands,
the dependency rule and the rules every change follows, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
before changing a boundary. Both apply to people and to coding agents alike.

## Setup

Needs [just](https://just.systems), [uv](https://docs.astral.sh/uv), Node 22 and Docker.

```
just bootstrap     # .env, git hooks, Python and website dependencies
just doctor        # what is missing
just check         # the gate
```

`just hooks` (part of bootstrap) installs the pre-commit hook, which runs the half of the gate a
commit touches, and the pre-push hook, which refuses direct pushes to `main`, checks commit
subjects, and runs `just check`.

## Branches and pull requests

`main` is protected by the rulesets in `.github/rulesets`:

- no direct pushes: every change is a pull request from a branch
- the `CI` check must pass, on a branch up to date with `main`
- review threads must be resolved; stale approvals are dismissed on a new push
- squash merge only, so `main` is linear with one commit per pull request
- `main` cannot be force-pushed or deleted; `v*` tags cannot be moved or deleted

Branch from `main` and name the branch for the change (`slack-platform`, `fix-confirm-expiry`).
One logical change per pull request, with a test for new behaviour. The pull request title becomes
the squashed commit's subject: imperative, at most 72 characters, no trailing period. The body
explains why.

`CI` is one job that waits for the others, so a change that touches only the website never waits
on Postgres, and a change that touches only Python never builds the website.

## CI and CD

| Workflow | Runs on | Does |
|---|---|---|
| CI | pull requests, main | gate, integration tests, image build, website build, commit subjects, then `CI` |
| Security | pull requests, main, weekly | pip-audit, npm audit, dependency review, gitleaks |
| CD | main, `v*` tags | multi-arch image to GHCR with SBOM and provenance attestation |
| Release | `v*` tags | verifies every version matches the tag, publishes the GitHub release |

## Releases

```
just release 0.2.0   # branch release/v0.2.0, every version set, notes in release-notes/v0.2.0.md
                     # edit the notes, push the branch, open and merge the pull request
just tag             # on main: tag v0.2.0 and push; CD and Release take it from there
```

A release whose `zipy.toml` tables changed shape bumps `config_version` and says how to update an
existing file in its notes.

## Repository settings

Branch rules and repository settings are code: `.github/settings.json` and `.github/rulesets`.
`just github` shows what differs from GitHub; `just github apply` applies it (admin only). Change
the files in a pull request, then apply after merge.

## Reporting

Bugs and plugin requests: the issue templates. Vulnerabilities: privately, see
[SECURITY.md](SECURITY.md).
