# ADR-0032: An outside AI agent enters through the same door as a game

- Status: Accepted
- Date: 2026-10-06
- Affects: [door contract](../door-contract.md), [outside AI agents](../capabilities/outside-agents.md)
- Related: [ADR-0031](0031-an-outside-program-decides-only-through-the-door.md), which opens the
  door to outside programs; [ADR-0030](0030-a-thing-is-a-typed-record-whose-looks-never-reach-the-simulation.md),
  whose deciders name an outside program by its bridge and grant

## Context

A developer with an AI agent of their own, built with any framework and thinking with any model,
should be able to give it a body in someone's world: let it perceive, decide, act and talk under
the world's rules, and be named on its card, with no change to the product per agent. The door
already lets an outside program decide for a world's things under a grant its owner issues, as a
game's adapter does: it is shown the request a model is shown, answers with one offered action, and
the decision host turns the answer into a receipt that replays without the program. The question
was whether agents need a second way in.

## Decision

- **An outside agent is a program at the door like any other.** A deployment admits outside agents
  with one bridge entry, run by each world's owner (`run_by` owner: the owner mints the agent's key
  for their own grant, and no shared bridge credential or invite exists) and marked as AI (`ai`
  true, so every thing it decides for and every line it says carries the AI mark). One grant per
  agent; no deployment change per agent.
- **It is shown exactly what a model is shown**: every ask carries the messages the role renders
  for a model and the forced function a model answers by, so no role's words are written a second
  time outside the product. It answers with one offered action, and a line where the action says
  one; the decision host checks and records it; replay reads the receipt and asks nobody.
- **What it says about itself stays on its card.** At hello an agent may declare its name, its
  maker and the mind it thinks with, held to an allow-list of characters and kept by digest; no
  society record or model context ever carries them, and each answer records which declaration
  gave it.
- **The agent's side lives outside the product**, in `bridges/agents`: a client library on the
  standard library alone and an MCP facade serving MCP 2026-07-28 (and earlier clients) through the
  official SDK, run beside the agent. The product never imports it, depends on it or packages it.
- **Nothing in the core is agent-specific.** Every door field an agent uses (per-bridge timing, who
  runs a bridge, whether its deciders are AI, a program's declaration, the model's messages in an
  ask) is one a game's adapter uses too.

## Alternatives rejected

| Alternative | Why not |
| --- | --- |
| An agent as a model provider the decision host calls | A model is called by the product, with the product's key, through the policy boundary, and must be reachable from the server. An agent runs on someone else's machine, holds its own model keys and dials out; the door already grants, revokes and receipts it |
| An MCP endpoint inside the API | It would put a protocol, its SDK and its sessions in the product for one kind of outside program, which no game would use. The facade outside the product can be hosted beside the API later with no core change |
| A bridge entry per agent | It would make every agent a deployment change. The bridge directory admits kinds of programs; grants admit instances |
| Rendering a role's words outside the product | A second wording of what a model is shown drifts with every engine version; the door hands over the model's own messages instead |
| A shared bridge credential for agents | Every developer would hold the same secret, so it would authenticate nothing. The owner's key per grant does |

## Consequences

- A developer brings an agent in with a key and a short program, or one entry in an MCP client's
  settings; a world's owner lets one in or stops it from the product.
- An agent cannot act outside its turns, invent an action, see more than a model sees, run anything
  inside the world, or put a name into it; a late or missing answer is decided by the world's
  routine.
- A turn waits up to the agents bridge's declared deadline, within the role contract's, so a world
  with an outside agent can take longer per minute than one run by its routine.
- Comparing an outside agent beside a model on the same thing is not provided: a comparison runs
  an outside-decided thing by its routine in every arm.
