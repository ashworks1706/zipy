# Deploy

One box, one compose file. 1-2 cores, 2-4 GB RAM, 20 GB disk with a hosted model, and a
further 4 GB of RAM and 5 GB of disk to run the models locally, which is the default. See
[inference](inference/README.md) for the model layer and how to point a role at a provider
instead.

| Service | Image | Profile | Port |
|---|---|---|---|
| zipy | built from `deploy/Dockerfile`, or `ghcr.io/ashworks1706/zipy` | app | 8080 |
| postgres | `pgvector/pgvector:pg16` | default | 5432 |
| redis | `redis:7-alpine` | default | 6379 |
| langfuse | `langfuse/langfuse:2` | observe | 3000 |
| uptime-kuma | `louislam/uptime-kuma:1` | observe | 3001 |
| prometheus | `prom/prometheus:v3.1.0`, scraping zipy `/metrics` | observe | 9090 |
| grafana | `grafana/grafana:11.5.1`, the provisioned Zipy dashboard | observe | 3002 |
| chat | `ghcr.io/ggml-org/llama.cpp:server`, the chat and summary model | model | 8000 |
| embed | `ghcr.io/ggml-org/llama.cpp:server`, the embedding model | model | 8001 |

## Local

```
just bootstrap          # .env, hooks, dependencies
just up                 # postgres and redis
just model              # llama-server for chat and embeddings, on the CPU
just migrate            # tables
just serve              # every enabled platform, the HTTP server and the workers, from source
just up langfuse prometheus grafana uptime-kuma
just chat               # talk to Zipy in the terminal, no chat app needed
just traces             # the newest request traces from .zipy/traces
```

## Observability

| What | Where | Holds |
|---|---|---|
| Trace files | `.zipy/traces/<org_id>/<request_id>.jsonl`, the `zipydata` volume in compose | every model call, tool call and reply of one request; `just traces <id>` |
| LangFuse | :3000 | the same, with prompts, cost and latency, searchable |
| Metrics | zipy `/metrics`, Prometheus :9090 | counters and latencies by platform, model role and tool, never by org |
| Dashboards | Grafana :3002, folder Zipy | `deploy/monitoring/grafana/dashboards/zipy.json` |
| Logs | stdout; JSON in the image | org, member and request id on every line |
| Errors | Sentry, when `ZIPY_TELEMETRY__SENTRY_DSN` is set | stack traces with the request id |
| Uptime | Uptime Kuma :3001 | pings `/health`, alerts into the org's chat |

## Production

On the box (Oracle Cloud free tier ARM, or any small VPS):

```
cp .env.example .env    # fill every secret; ZIPY_API__PUBLIC_URL is the HTTPS origin
just prod-up
docker compose -f deploy/compose.yml -f deploy/compose.prod.yml exec zipy zipy db upgrade head
```

Put Caddy or nginx in front of `127.0.0.1:8080` for HTTPS; OAuth providers and HTTP-based
platforms require it. Every URL follows the plugin name, so a new plugin adds a URL, not a route:

```
<ZIPY_API__PUBLIC_URL>/auth/<provider>/callback      OAuth redirect, per [providers.*]
<ZIPY_API__PUBLIC_URL>/webhooks/<provider>           provider webhooks (zoom)
<ZIPY_API__PUBLIC_URL>/platforms/<platform>/...      platform events and installs (slack)
```

Discord connects outward over a websocket and needs no public URL.

## Website

`apps/website` is a static Next.js site, deployed apart from the stack: import the repo on Vercel
with `apps/website` as the root directory, or `just web-build` and serve it with `npm run start` on
any Node host. Set `NEXT_PUBLIC_SITE_URL` to its public origin.

## Backups

Everything that matters is in the `pgdata` volume, plus `ZIPY_DATA__FERNET_KEY`. Without that key
the stored credentials and workspace bot tokens cannot be decrypted; every org would reconnect.
