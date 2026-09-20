# Vision

Zipy is an adaptive agent harness for teams. What that is for, in one page. `docs/ROADMAP.md`
says what is being built and in what order; `docs/ARCHITECTURE.md` says how it is put together.
This says why any of it is worth building.

Two reasons, and they are not the same reason. It is a thing a student org can run, and it is a
place to measure how an agent models the people it works with, on a platform they were already
using rather than in a study. The first pays for the second.


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
- Not a mechanistic research platform. Zipy runs models through LiteLLM and sees text, tool calls
  and token counts. It holds no activations, no attention and no logits, and exposing them is not
  on the roadmap. Anything that needs hooks needs a different harness. What Zipy is a testbed for
  is the section below.
- Not a general agent framework. The loop, the tool layer, the permissions, the memory and the
  traces exist because the claim above needs somewhere to stand, not as the product.


## As a testbed

The second reason to build this. Almost every result about how an agent adapts to a person comes
from a benchmark or a paid annotator session: one sitting, a task the person did not choose, and a
rater who knows they are rating. Zipy runs on Discord and Slack, where a student org's officers
ask it for things they actually want, over months, with turnover. That is a rare place to measure
user modelling, and the instrumentation for it is already in the tree rather than bolted on.

What an experiment gets:

- **Real longitudinal interaction.** The same person, many sessions, a task they chose, on a
  platform they were already in. No annotator effect.
- **Sparse implicit supervision, already categorised.** `Evidence` records why a dimension moved:
  a confirmation taken or cancelled, a follow-up asking for shorter or for more, a correction, a
  stated preference. Categories, never the words. That is a labelled stream of deference and
  pushback that most deployments throw away.
- **An ablation that already exists.** `collaboration.enabled` is a switch, `Conditioning` is a
  seam with one renderer per endpoint capability, and the eval suite scores correctness and
  behaviour on separate axes. Same question, same model, different state, is a run rather than a
  build.
- **A ground truth for the thing being modelled.** The person is reachable. A model of them can be
  shown to them and contradicted by them, with `prefer`, which a benchmark cannot offer.

Questions it can carry, stated as things it could actually measure:

- Whether behavioural adaptation from sparse implicit signals moves user-visible behaviour without
  moving task correctness. That is the contrast table, and it is the first one owed.
- Whether a stated preference should outweigh accumulated behaviour, and for how long.
  `STATED_WEIGHT` is four observations because four was a guess.
- Whether adaptation drifts toward agreement. An agent that reads a cancelled confirmation as
  "ask less" and a correction as "defer more" has a path to becoming agreeable rather than useful,
  and `Evidence` plus the audit log is a record of exactly when it deferred and when it was
  corrected. Sycophancy has a behavioural signature that is measurable here, without activations,
  and it is the closest thing in this repo to interpretability work.

Two constraints on using it that way. Anything run on a real org needs their consent, and the
no-text-column rule helps rather than hinders: the state that would be studied holds scores and
counts, not what anyone said. And a behavioural result is a behavioural result. It can say an
agent became more agreeable; it cannot say what inside the model changed. Treating the second as
following from the first is the mistake this section exists to prevent.


## How it gets settled

The contrast table in the eval suite: same question, same model, different member state.
Behaviour moves, correctness holds. Until that table exists against a real model,
`collaboration.enabled` stays false and the claim stays a claim.
