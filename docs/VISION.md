# Vision

Zipy is an adaptive agent harness for teams. What that is for, in one page. `docs/ROADMAP.md` says what is being built and in what order;
`docs/ARCHITECTURE.md` says how it is put together. This says why any of it is worth building.


## The claim

An agent shared by a whole team has to adapt to each person individually, while acting on
resources the whole team owns.

Both halves are load-bearing. A single-user assistant can adapt freely, because the only person
who pays for a bad guess is the person it guessed about. A multi-tenant agent can act on shared
resources safely, because it treats everyone in the org identically. Zipy wants both at once, and
that is the interesting part: the adaptation is per person, the consequences are not.


## The bet

Adaptation may change how the agent talks and how much it does on its own. It may never lower the
bar on a consequential action.

So a person's state can move an answer from three paragraphs to one line, and it can move the
agent from asking first to acting first on the calls where asking is optional. It cannot make a
destructive call stop needing a confirmation, and it cannot widen what a role is allowed to do.
Those are pinned in `zipy.toml` and in the role table, and nothing derived from behaviour reaches
either. `apps/engine/tests/test_permissions.py` holds that as a test rather than as a hope.


## The one mechanism

Per-member collaboration state: three named dimensions (depth, autonomy, formality), each a score
and a count of the observations behind it, updated by an exponential moving average over what
behaviour showed. No text column, ever.

That last constraint is not a privacy garnish, it is what makes the mechanism necessary. Storing
chat history from any platform is out of scope, so the usual approach, retrieval over a person's
message log, is not available. A compact state that updates from behaviour and keeps none of the
words is the only way left to personalise, which is why it is worth building rather than being one
feature among many.

The dimensions are named and countable on purpose. At the scale Zipy runs at, tens of
interactions per person, a learned encoder fits noise. Named dimensions can be shown to the person
they describe, corrected by them, and ablated one at a time in an eval.


## What this is not

- Not a model of how people on a team relate to each other. There is no who-knows-what, no
  assignment, no routing between members. One person, one state.
- Not an opaque vector. No learned encoder, no embedding of a person, until an eval says named
  dimensions are what limits the adaptation.
- Not a research platform. Zipy runs models through LiteLLM and sees text, tool calls and token
  counts. It holds no activations and exposes no hooks, and adding them is not on the roadmap.
- Not a general agent framework. The loop, the tool layer, the permissions, the memory and the
  traces exist because the claim above needs somewhere to stand, not as the product.


## How it gets settled

The contrast table in the eval suite: same question, same model, different member state.
Behaviour moves, correctness holds. Until that table exists against a real model,
`collaboration.enabled` stays false and the claim stays a claim.
