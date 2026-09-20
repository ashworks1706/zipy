"""How the agent works with one person: what a turn showed, what is held, what conditions on it.

Separate from memory because memory answers what is true and this answers how to work with
someone. Memory assembles read-only context for one request; this has its own write path, its own
store and its own switch, and nothing here is ever an input to a permission or a confirmation.
"""
