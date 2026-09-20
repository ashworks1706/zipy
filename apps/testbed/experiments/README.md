# Experiments

One folder per experiment, named for the question it asks. Nothing outside this directory imports
anything in it, so an experiment can be abandoned by deleting its folder.

What an experiment may reach: the database, the traces, and files another testbed module exported.
Not the engine. Anything that has to run the agent belongs in `apps/engine/evals`, which is a
layer of the engine and can build the real gateway; the independence contract in the root
`pyproject.toml` stops this app importing it.

A folder holds whatever it needs. The convention is a `README.md` saying what is being asked and
what would answer it, and a `run.py` that produces a result file rather than printing one.
