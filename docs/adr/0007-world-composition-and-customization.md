# ADR-0007: Versioned world composition and protected customization

Status: **ACCEPTED AND IMPLEMENTED** for reviewed structural composition authority and appearance
authority. Direct user-authored structural editing remains outside the public surface.

## Context

Atlas needs to grow from a five-region preview into a long-lived personal world. Re-running local
placement code is deterministic but not persistent. Renderer entities cannot be the durable model:
their names, transforms, enabled state, and assets are implementation details, and style previews
must not mutate navigation or evidence truth.

## Decision

Atlas uses four separated layers:

1. a versioned **module catalog** containing passive bounds, sockets, collision, navigation, LOD,
   accessibility, evidence requirement, fallbacks, and allowed customization axes;
2. a versioned **recipe catalog** containing validated directed attachment graphs;
3. a deterministic **world composer** that consumes one scene and the complete catalogs, resolves
   honest fallbacks, assigns stable element IDs, records provenance, builds navigation and
   streaming metadata, validates reachability, and emits an immutable draft topology snapshot;
4. an orthogonal **style-version controller** for preview, validation, apply, discard, and rollback.

Element IDs derive from semantic owner + recipe key + slot key. They do not derive from transform,
graph state version, renderer object name, or appearance profile.

World appearance may change geometry realization only while the module's topology compatibility
contract remains identical. Changes to bounds, sockets, collision, navigation, evidence, or
reconstruction capability are structural and require recomposition plus protected-value review.

The frontend never upgrades a draft topology to persisted authority. Production persistence is a
backend transaction that compares base versions, validates, writes an immutable snapshot, moves a
current pointer, and records lineage atomically.

## Alternatives rejected

- **Autonomous smart modules.** Rejected because local agents cannot guarantee global
  reachability, deterministic assembly, sparse routing, or one conflict policy.
- **Renderer scene graph as storage.** Rejected because engine lifecycle and LOD would become data
  lifecycle, and a style preview could silently rewrite world identity.
- **Seed-only regeneration.** Rejected because algorithm/catalog upgrades and deletion can change
  outputs even with one seed, and persistence requires recoverable historical versions.
- **A user-facing identity menu before alternatives are validated.** Rejected because exposing
  unfinished profiles makes renderer experiments look like product identity. Aeroheart is the sole
  complete authored default; experimental profiles remain internal compatibility fixtures. Each
  complete style may expose its own capability-backed parameter manifest.
- **Every generated mesh as a durable element.** Rejected because most are renderer detail.
  Durable elements are only those with navigation, interaction, persistence, configuration,
  collision, accessibility, streaming, or evidence meaning.

## Consequences

Positive:

- topology can be tested without PlayCanvas;
- style preview cannot move regions or evidence bindings;
- missing reconstruction fails to source-first evidence rather than invented geometry;
- stable IDs and provenance survive reloads and graph-state changes;
- module fallback, recipe attachment, reachability, and digest checks fail before render;
- both Settings and Companion can share one proposal lifecycle without sharing UI.

Costs and open work:

- WMP 1.0, its opt-in authored-world 1.0 extension, and its opt-in environment-instances 1.0
  extension are implemented; runtime import, society projection, and the geographic
  composition rights extension remain delivery work;
- structural customization has a protected backend diff preview but remains an internal reviewed
  composer workflow rather than a public appearance control;
- readable stable element IDs are now durable backend identities; snapshot and migration records
  use UUIDs;
- physical asset streaming and renderer batching still sit behind the emitted streaming keys;
- reconstructed navigation artifacts must be supplied by the reconstruction pipeline.

## Validation

The core tests require deterministic output, stable IDs across state reloads, honest reconstruction
fallback, complete provenance, reachable destinations, invalid attachment rejection, digest
rejection, preview isolation, stale-proposal rejection, protected structural rejection, regional
scope, immutable apply/rollback history, and unknown-profile fallback.

The architectural evidence and follow-up gates are in
[atlas-world-research.md](../atlas-world-research.md).
The implemented persistence and API contract is in
[world-style-backend.md](../world-style-backend.md).
