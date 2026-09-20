# apps/testbed

The offline half. Datasets from real runs, the decisions made about them, the post-training that
reads them, and experiments over what a deployment produced.

Everything that measures the agent lives here, and this is the one app that imports another. The
layers contract in the root `pyproject.toml` gives the direction: the testbed reads the engine,
the engine never reads the testbed. That is what lets an eval build the real gateway rather than a
copy of it, and it keeps the thing being measured independent of what measures it.

```
core/           settings, types, tests
evals/          cases, fixtures, the stack a case runs on, the evals command
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
`evals/cases.toml` with `evals add`.

## Post-training

`just train sft` over the curated set. Needs a GPU and `uv sync --extra gpu`; nothing else here
does, and the gate never installs them.
