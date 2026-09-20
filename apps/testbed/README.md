# apps/testbed

The offline half. Datasets from real runs, the decisions made about them, the post-training that
reads them, and experiments over what a deployment produced.

It imports nothing else in the repo. Anything that has to run the agent lives in
`apps/engine/evals`, which is a layer of the engine and can build the real gateway and
orchestrator; this app reads the database, the traces and exported files instead. The independence
contract in the root `pyproject.toml` holds the line.

```
core/           settings, types, tests
datasets/       traces to examples: export, redact, verify, review, curate
curation/       decisions.jsonl, the ledger, committed
posttrain/      SFT over the curated set. Needs a GPU and `uv sync --extra gpu`
configs/        post-training configs
experiments/    one folder per experiment, free-form
```

## Datasets

An export can be run again; a judgment cannot. That is why the ledger is committed and the
exports are not.

```
just data export    every generation the traces hold, redacted   .zipy/training/raw/generations.jsonl
just data verify    well-formed, not empty, not duplicated       .zipy/training/processed/verified.jsonl
just data review    keep, drop or fix, one at a time             apps/testbed/curation/decisions.jsonl
just data curate    accepted decisions only                      .zipy/training/processed/sft.jsonl
```

An example nobody has reviewed is not training data. `data curate` says how many it left out and
why. Each decision carries the fingerprint of the example it judged, so a changed example is
reported as stale rather than trained on.

Curation feeds the evals as well as the training set: a run worth keeping can become a case in
`evals/cases.toml` with `zipy eval-add`.

## Post-training

`just train sft` over the curated set. Needs a GPU and `uv sync --extra gpu`; nothing else here
does, and the gate never installs them.
