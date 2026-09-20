# Experiments

One folder per experiment, named for the question it asks. Nothing outside this directory imports
anything in it, so an experiment can be abandoned by deleting its folder.

An experiment may reach the database, the traces, files another testbed module exported, and the
engine itself. The layers contract in the root `pyproject.toml` allows that one direction and
forbids the other, so an experiment can build the real gateway the way `../evals/stack.py` does,
and nothing the engine ships depends on an experiment existing.

A folder holds whatever it needs. The convention is a `README.md` saying what is being asked and
what would answer it, and a `run.py` that produces a result file rather than printing one.
