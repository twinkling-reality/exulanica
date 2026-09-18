# Adaptive world backend

Status: **IMPLEMENTED** for appearance styles and protected source-media metadata. Structural
authority is implemented separately in [spatial-world-authority.md](spatial-world-authority.md).

This document is the persistence and HTTP half of
[ADR-0007](adr/0007-world-composition-and-customization.md) and the
[Atlas world customization contract](atlas-world-customization-contract.md). The implementation is
`exulanica/world/`, migrations `0017_adaptive_world_styles.sql` and
`0023_frontend_world_recipe_contract.sql`, and the `/world` API routes.

## Boundary

The backend stores only:

- reviewed `WorldArtProfile` identifiers and versions;
- parameter values whose keys resolve through a profile manifest to the reviewed capability
  registry;
- immutable global and regional style versions;
- protected topology digests, compatibility keys, region identities, and source-media slot
  bindings supplied by the composition workflow;
- isolated preview candidates and their lifecycle state;
- current pointers; and
- proposal/apply/discard/rollback provenance.

For Companion proposals that provenance includes reference IDs, model ID, prompt version, and
optional `refines_proposal_id`. The server derives and stores the recipe/module/capability binding
from its closed registry; clients and models cannot submit executable bindings. Conversation text
and preview-session state are not durable style fields.

It does not store or return CSS, markup, JavaScript, shaders, renderer programs, remote texture
URLs, or interface layout. `WorldUiStyle`/presentation realization stays in the reviewed client
presentation system; the backend does not author panel structure, generated forms, or screen
layout. A new renderer capability is a reviewed registry/migration/code change, not a schema
submitted through this API.

There is deliberately no public topology mutation route. `WorldStyleRepository.register_topology`
is the internal handoff from a reviewed composer after topology validation. Appearance requests
cannot call it and cannot write region identity, navigation, collision, transforms, evidence
bindings, reconstruction requirements, or destinations.

## Registry and fallback

`exulanica/world/style-registry.v1.json` is pinned to the renderer-neutral portion of frontend commit
`55b123627314d328fba3850eb607d8a7682a8cad`. The referenced frontend history is on a divergent
branch, so this backend does not copy its visual profiles or executable TypeScript modules. The
loader instead validates their exact reviewed module IDs, one-to-one capability ownership,
controls, profile versions, safe ranges/options, and recipe availability/origin. The catalog uses
the frontend `WorldStyleCatalog` camel-case shape and extends each descriptor with an inert
`recipeBinding`. Runtime database roles have read-only access to the registry rows.

The catalog deliberately uses the existing frontend camel-case `WorldStyleCatalog` keys. Preview,
apply, and rollback bodies accept both that frontend casing and the API's established snake-case
names: `proposalId ↔ proposal_id`, `baseStyleVersionId ↔ base_style_version_id`,
`baseTopologyDigest ↔ base_topology_digest`, `profileId/profileVersion ↔
profile_id/profile_version`, and regional `islandId ↔ region_id`. The API normalizes both forms to
one domain model; it does not persist two schemas. The HTTP contract test submits the frontend form
and inspects the same backend-produced recipe binding.

Unknown profile versions, modules, capabilities, and parameters fail closed for new proposals and
for preview-to-apply revalidation. Historical immutable rows may resolve to a warned display
fallback, but historical parameters are discarded and never interpreted against a newer recipe.

New proposals must name a supported exact profile version, including one the registry marks experimental. Historical
versions are never rewritten when support changes:

- a removed, unsupported, or unknown global profile resolves through its reviewed fallback chain
  and returns a warning;
- a removed, unsupported, unknown, or newly-invalid regional override is ignored with a warning;
- the original immutable row remains intact, so export and audit can still report what was chosen.

The fallback chain is validated at registry load and cannot contain a cycle. The default is
`origin-landscape@1`.

## Transactions and concurrency

The database owns one current pointer per workspace/world. A style mutation locks that row and
compares both optimistic tokens:

```text
base_style_version_id == current_style_version_id
base_topology_digest   == current_topology_digest
```

Preview validates a proposal and writes an isolated candidate; it never moves the pointer. Apply
inserts the global version and all regional overrides, moves the pointer, closes the preview, and
writes the audit event in one transaction. Discard closes only the preview/proposal. Rollback
copies a historical version into a new revision and moves the pointer in one transaction; it never
updates the target. Regional overrides for regions absent from the current protected topology are
omitted and named in rollback audit details.

Topology contracts, topology regions/source slots, style versions/region versions, and audit
events reject UPDATE and DELETE in the database. Current pointers and preview/proposal lifecycle
rows are the intentionally mutable exceptions.

Rejected proposals are also audit records. Invalid style data, stale bases, and topology conflicts
retain the supplied origin, token-derived actor, origin reference, and rejection code. `settings`
and `companion` proposals require an origin reference; `user` proposals may omit one. The HTTP body
has no actor field: the actor comes from the bearer token. Companion proposals additionally require
model ID, prompt version, and at least one opaque reference ID. `GET /world/styles/proposals/{id}`
exposes acceptance/rejection/discard/stale status, refinement lineage, and the exact inert recipe
binding without storing raw conversation or private reference media.

## Source media

Source-media slots belong to a topology contract, never to a style proposal. A slot either carries
an evidence span from the same workspace or a non-empty reason that evidence is missing. The
database enforces the workspace and span together with a composite foreign key, and FORCE row-level
security applies to every source query.

`GET /world/source-media` reports one of three explicit states:

- `available`: authorised evidence metadata exists, its capture is live, the blob is not purged,
  and bytes exist in the configured content-addressed store;
- `unavailable_asset`: the authorised binding exists but its capture/row/bytes are unavailable;
- `missing_evidence`: the topology recorded that no evidence exists for the slot, with the stored
  reason.

Only an available source carries a local authenticated evidence path such as
`/evidence/{span_id}` and an `asset_reference` that names its source slot and evidence-span
provenance and declares workspace-bearer authorization. No remote asset URL is accepted or emitted.
Requiring one source through
`GET /world/source-media/{source_id}` returns `unavailable_asset` rather than inventing media.
Unknown and cross-workspace source IDs return the identical `unknown_reference` response.

## HTTP surface

All routes require a bearer token.

| Method | Route | Result |
| --- | --- | --- |
| `GET` | `/world/styles/catalog` | Reviewed profiles and capability-backed controls |
| `GET` | `/world/styles/current` | Current version plus the independently current topology digest |
| `GET` | `/world/styles/versions` | Immutable resolved history with warnings/provenance |
| `GET` | `/world/styles/proposals/{id}` | Proposal status, provenance, refinement, and recipe binding |
| `POST` | `/world/styles/previews` | Validate and create an isolated preview |
| `POST` | `/world/styles/previews/{id}/apply` | Compare both bases and atomically apply |
| `DELETE` | `/world/styles/previews/{id}` | Atomically discard without changing current style |
| `POST` | `/world/styles/rollback` | Append a version matching historical style values |
| `GET` | `/world/source-media` | Honest current-topology source states |
| `GET` | `/world/source-media/{id}` | Require one source to be locally available |

The domain problem codes are intentionally distinct:

| HTTP | Code | Recovery |
| --- | --- | --- |
| `422` | `invalid_style_data` | Correct the profile, manifest-backed parameter, scope, or provenance |
| `409` | `stale_style_version` | Read current state and create a new proposal |
| `409` | `protected_topology_conflict` | Recompose/review against the conflicting topology; never force appearance over it |
| `424` | `unavailable_asset` | Render the recorded honest fallback/state or restore authorised bytes |
| `409` | `invalid_preview_state` | Do not reapply a closed preview |
| `404` | `unknown_reference` | Treat absent and cross-workspace IDs identically |

## Verification

`tests/test_world_style_contract.py` pins the Python adapter to the inspected frontend recipe
commit and rejects unknown modules/capabilities and executable/remote payload channels.
`tests/test_world_style_postgres.py` executes preview isolation, competing-writer exclusion,
topology invalidation, immutable rollback, three-origin audit provenance, and source states against
PostgreSQL 18. `tests/test_world_api.py` holds the route shapes, problem codes, actor derivation, and
cross-workspace source behavior.
