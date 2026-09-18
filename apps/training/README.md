# apps/training

Datasets from real runs, the decisions made about them, and the post-training that reads them.

The engine writes one JSONL trace per request, and a `generation` event in it carries the messages
sent to the model and the reply that came back. That is a training example already, so nothing here
needs a telemetry service.

```
just data export    every generation the traces hold, redacted   .zipy/training/raw/generations.jsonl
just data verify    well-formed, not empty, not duplicated       .zipy/training/processed/verified.jsonl
just data review    keep, drop or fix, one at a time             apps/training/curation/decisions.jsonl
just data curate    accepted decisions only                      .zipy/training/processed/sft.jsonl
just data stats     what the set holds and what is unjudged
just train sft --dry-run
just train sft
```

An example nobody has reviewed is not training data. `data curate` says how many it left out and
why, and a decision carries the fingerprint of what it judged, so an example that changed
underneath is reported as stale rather than trained on under a judgment about something else.

| Module | Holds |
|---|---|
| `datasets/export.py` | Generations read out of the engine's trace files. |
| `datasets/redact.py` | Emails, phone numbers, platform ids and tokens, inside messages and tool arguments. |
| `datasets/verify.py` | Schema, a non-empty reply or a named tool call, dedupe by content hash. |
| `datasets/curate.py` | The ledger: one decision per example, fingerprinted. |
| `datasets/review.py` | Showing one example and reading back the verdict. |
| `curation/decisions.jsonl` | The decisions, committed. |
| `posttrain/sft.py` | Unsloth QLoRA over the curated set. Writes an adapter. |
| `configs/train/sft.yaml` | What a run does. `dataset` is what `data curate` writes. |

Post-training needs a GPU and `uv sync --extra gpu`; nothing else here does, and the gate never
installs it. What serves an adapter is a question for `[models.chat]`, and is not decided here.

Curation feeds the evals as well as the training set: a run worth keeping can become a case in
`evals/cases.toml`, which `just eval` runs. See `docs/ARCHITECTURE.md`.
