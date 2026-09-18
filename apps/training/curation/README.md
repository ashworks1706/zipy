# curation

The review decisions, in source control.

`decisions.jsonl` holds one line per judged example: the id, the verdict (keep, drop or fix), the
reviewer's reason, the reply they wrote when the verdict is fix, and the fingerprint of the example
as it was judged.

An export can be run again and produces the same examples. A judgment cannot, which is why it lives
here rather than in the dataset. A decision whose fingerprint no longer matches its example is
stale, and `just data curate` reports it rather than using it.
