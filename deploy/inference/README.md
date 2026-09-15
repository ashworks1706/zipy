# deploy/inference

The model layer. Zipy reaches every model through LiteLLM, which speaks the OpenAI-compatible
API, so a local `llama-server` and a hosted provider are the same thing to the engine: a model
string, an `api_base` and an `api_key`.

The committed defaults in `zipy.toml` are the local servers, so a fresh clone answers without a
hosted account.

| Role | Default GGUF | Port | Alias | Flags |
|---|---|---|---|---|
| `chat` | `Qwen/Qwen3-4B-GGUF:Q4_K_M` | 8000 | `zipy-chat` | `--jinja` for tool calls, `--metrics`, `--ctx-size 16384`, `--parallel 2` |
| `summary` | the chat server | 8000 | `zipy-chat` | one loaded model serves both roles |
| `embedding` | `Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0` | 8001 | `zipy-embed` | `--embeddings --pooling last`, `--metrics`, batch 1024 |

`--alias` is what makes `openai/zipy-chat` resolve: the server answers to that model id whatever
GGUF is loaded, so changing the GGUF changes no configuration.

## Running it

```bash
just model        # both servers on the CPU; GGUFs download on first run
just model-gpu    # the CUDA image, every layer on one NVIDIA card
just model-down   # stop them, keep the downloaded GGUFs
```

The GGUFs land in the `modelcache` volume and survive `just model-down`. Endpoints are
`http://127.0.0.1:8000/v1` and `:8001/v1`; inside compose the hosts are `chat` and `embed`, which
the `zipy` service is pointed at by default.

CPU is the default because it runs anywhere. A 4B model at Q4 answers, slowly: expect seconds
per reply on a laptop, and prefer `just model-gpu` or a hosted provider for anything a team is
waiting on.

## Sizing

`--parallel N` gives the server N slots and continuous batching decodes them together over one
copy of the weights. `--ctx-size` is the total across slots, so per-slot context is
`ctx-size / parallel` and the KV cache scales with the total.

```bash
ZIPY_CHAT_PARALLEL=4 ZIPY_CHAT_CTX=16384 just model-gpu   # 4 slots x 4096 tokens
```

| Override | Default | What it changes |
|---|---|---|
| `ZIPY_CHAT_GGUF`, `ZIPY_EMBED_GGUF` | see the table | which weights load |
| `ZIPY_CHAT_CTX`, `ZIPY_EMBED_CTX` | 16384, 4096 | context across all slots |
| `ZIPY_CHAT_PARALLEL`, `ZIPY_EMBED_PARALLEL` | 2 | slots |
| `ZIPY_CHAT_NGL`, `ZIPY_EMBED_NGL` | 0, and 99 under `just model-gpu` | layers on the card |
| `ZIPY_LLAMA_IMAGE`, `ZIPY_LLAMA_GPU_IMAGE` | `llama.cpp:server`, `:server-cuda` | the image |

## Going hosted

Each role is independent. Sending one to a provider takes its three variables in `.env`, which
win over `zipy.toml`:

```bash
ZIPY_MODELS__CHAT__MODEL=openrouter/qwen/qwen3-32b
ZIPY_MODELS__CHAT__API_BASE=
ZIPY_MODELS__CHAT__API_KEY=sk-...
```

An empty `API_BASE` sends the call to the provider's own endpoint.

The embedding role is the one exception: `models.embedding.dimensions` must equal
`EMBEDDING_DIMENSIONS` in `apps/engine/data/tables.py`, which is the width of the pgvector
column. Changing the embedding model to one of another width is a migration and a re-embed of
every document. `apps/engine/tests/test_data.py` holds the two together.

## Deployed

`just prod-up` brings the model profile up with everything else, so a self-hosted box runs
without a model account. On a box serving a real team, either give it a card and use
`deploy/compose.gpu.yml`, or point the chat role at a provider and leave the embedding role
local, where a 0.6B model on the CPU is cheap.
