# ADR-0030: A thing is a typed record whose looks never reach the simulation

- Status: Accepted
- Date: 2026-10-06
- Affects: [things contract](../things-contract.md) and the
  [decision roles contract](../decision-roles-contract.md#who-decides-deciders-and-the-owners-choice)
- Related: [ADR-0023](0023-epistemically-typed-world-memory.md), whose assertion provenance is a
  different axis from where a piece came from

## Context

A world holds people and the furniture they use, and it is meant to hold far more: a sword someone
carries, a spirit with no body, a visitor whose game decides for it. Without a shared description,
each would need code of its own, and each would bring its own way of being drawn and its own way of
saying where it came from. Several of those already exist side by side: world kinds, style packs,
generated pieces, a person's prepared assets, reviewed imports and catalog entries each state their
origin in a vocabulary of their own. A society's people are drawn only as the people catalog draws
them, and nothing records what a thing is apart from how it looks.

The society engines are deterministic and replayable: a run is its input, its draws and its
receipts, and a replay reads no model. Anything that lets appearance reach that state would make
redrawing a thing rewrite its history.

## Decision

- **A thing kind is a typed, versioned, fingerprinted record** (`exulanica.thing-kind/v1`): its
  class, a body plan with bounded figures, the movement modules it moves by, abilities and offers
  from catalogs, its routine's weights, the deciders that may run it, suggested looks, its origin
  and source data no engine reads. Checks are deterministic and refuse by name. A new kind of thing
  is data; a new kind of mechanism is a reviewed ability module, never code per thing.
- **Bodies are a few body plans named by version.** The humanoid plan is the VRM 1.0 humanoid's
  bones, so any look that maps its joints onto them, a rigged mesh, rigid blocky parts or a game's
  character, moves and holds things on the same named bones. A body with no bones and a rigid
  object are plans of their own.
- **A look is a separate record, and no look reference enters a society's input, state or decision
  context.** Any look of a thing's body plan may be chosen for it. What a society is given of a kind
  carries no look, so swapping a look leaves every state and decision digest unchanged by
  construction, and a replay never reads one.
- **Where a piece came from is one origin record** (`exulanica.origin/v1`). Pieces that carry an
  older vocabulary keep their bytes, and one reader for each turns it into the record. Who supports
  an assertion stays its own axis.
- **Bringing something in from elsewhere writes a translation manifest** that accounts for every
  field of the source exactly once, carried, approximated, dropped or kept opaque, with reasons. A
  foreign mechanic is never emulated.

## Alternatives rejected

| Alternative | Why not |
| --- | --- |
| An entity-component runtime, as in SpatialOS or Ambient | The society engines are already deterministic modules over typed, replayable state. A general runtime would need its determinism, replay and authorization rebuilt, and gives a reviewer nothing to check about what a thing is |
| One universal avatar schema or ontology | It cannot be held to bounded checks, and every source would be forced into it. A few body plans with bounded figures, and a manifest saying what did not fit, can be |
| Looks inside society state | A look swap would rewrite a world's history and move its digests, and appearance would reach the models that decide |
| A ninth origin vocabulary beside the others | It would be one more shape for a reader to know. The record replaces the need, and the readers are each format's way to it |
| Emulating a game's mechanics, such as its health | A world would carry rules no module of its own states and no replay could check. A field only another game can act on is dropped or kept opaque, and the manifest says so |
| Learned retargeting as the contract | It is not deterministic. A rig's bone map is data a reviewer reads and a test holds |
| OpenUSD as the runtime store | Its layering and composition answer a question the society does not ask. A format like it belongs at an importer's edge, read into kinds and looks with a manifest |
| SMPL-X as the body | Its model licence permits non-commercial research use only |

## Consequences

- Adding a kind of thing, a look or an origin is a reviewed document that a test checks, with no
  code. The things package is pure data and readers, held by an import contract to no database,
  store, world, model or numeric stack.
- Four catalogs (body plans, abilities, offers, look kinds) are maintained as every catalog is,
  each entry with its licence and reason.
- A thing is only as capable as the ability modules that serve its kind. Until an engine reads
  kinds and a store keeps a thing's chosen look, a kind changes nothing in a running world; the
  [things contract](../things-contract.md#what-is-not-built) states those limits.
