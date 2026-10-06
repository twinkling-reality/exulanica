# ADR-0029: A world kind is data that one site grammar realises

- Status: Accepted
- Date: 2026-10-04
- Deciders: the product owner
- Related: [world kinds](../world-kinds-contract.md), [grammar contract](../grammar-package.md),
  [synthetic society contract](../synthetic-society-contract.md),
  [ADR-0027](0027-a-generated-world-is-drawn-in-its-own-world.md)

## Context

The city grammar generates one kind of place, a town, from a specification whose values a person
or a model chooses. People want worlds of other kinds: a farm, a building site, a cafe. Each such
world has to hold a living society (homes, workplaces, shops, a walking graph every resident can
use), keep a receipt it regenerates from, and be drawn by the application and dressed by style
packs. A model can describe a kind of place in words; a model cannot be trusted to produce
geometry the society can live in or a renderer can draw.

## Decision

A kind of world is a document, `exulanica.world-kind/v1`: parts in plain words, each with the
engine roles that say what the engine does with it and a look role a style pack dresses; zones and
how they are laid out; the kind's own use classes in the society's form; adjustable values with
ranges; and presets. Integers only, closed keys, bounds from a catalog with a reason for each.

One generator, the site grammar, realises every such document. Generators stay pluggable by
composer key: the town keeps the city grammar behind an adapter that lists it in the same
vocabulary without copying its specification, and a kind names the `site-plan` composer.

A kind is admitted only by deterministic checks: the document (stage A), then sample worlds at
every preset and every value's ends, each held to the society's place check, the measured graph
and population bounds, reachability from the entry and at least one worker (stage B). A model's
draft, a creator's upload and a shipped kind pass the same checks.

A world made from a kind keeps the whole kind document in its receipt, so it regenerates from the
receipt alone. The plan and output digests hold the world; the kind catalogs' digests are
provenance. The society reuses the walking-surfaces input profile with a site navigation profile
and a routine overlay, rather than a new input profile or engine. A site world is drawn from a
served document of slots, not from baked tiles.

Because a kind comes from a person or a model, the work generating from it can ask for is bounded
by the document's caps and a layout budget, and all of it (sample worlds, a world, a drawing's
records) runs in a worker process apart from the request's thread, bounded per job and per
workspace.

## Alternatives considered

- **A generator per kind in code.** Each new kind would need engineering, review and a release,
  and a model could not propose one. Rejected: kinds should grow as data.
- **A model generating geometry or a whole world directly.** Nothing would guarantee walkable,
  reachable, staffed places, and a world would not regenerate from a receipt. Rejected: the model
  drafts the document; the grammar and the checks decide what exists.
- **Extending the town specification with flags for other kinds.** The city grammar's stages are
  streets, blocks and lots; a farm or an interior is not a town with options, and the town's
  receipts and digests would move. Rejected.
- **A new society input profile and engine for site worlds.** It would need its own migration,
  identity rules and comparisons before any site world could hold people. Rejected in favour of
  additive acceptance in the existing walking-surfaces profile; the living engine is unchanged.
- **Baking site worlds into tiles.** Baking is offline and slow, and a site's parts are few and
  simple. Rejected: the drawing is generated again from the receipt on request, in the kind worker,
  kept by the receipt's digest and named by its own.
- **Gating a receipt on the kind catalogs' digests.** Any edit to a look family or a bound's reason
  would unmake every world. Rejected: the plan and output digests decide whether a world is the
  same.

## Consequences

- A new kind of world is a reviewed document, not a release. A refused kind is refused by name
  with the place in the document and every sample's sentence.
- Towns are unchanged: their receipts, digests and generator are the same, and making a town as a
  kind makes the same world.
- The bounds a kind may reach are the bounds a living society's tick was measured on. A larger
  world waits on a society measured to hold it.
- Style packs and generated pieces dress look roles, so a kind a model drafts is drawn with no
  per-kind art.
- The [world kinds contract](../world-kinds-contract.md) owns the document, the checks, the
  grammar, the receipt, the drawing and the routes.
