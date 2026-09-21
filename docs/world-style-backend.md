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

Source-media list and single-source reads accept either `source_snapshot_id` or
`topology_digest`. Snapshot addresses resolve the exact structural topology within the
requested workspace and world. Unknown addresses return 404; invalidated snapshots return
409; supplying both addresses returns 422. Omitting both preserves current-topology reads.
Saved-world reopening supplies its stored snapshot ID rather than following the global pointer.

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

## Structural and composed style compatibility

`WorldStyleRepository.classify_structure_style_compatibility` is the plane-typed authority.
It writes nothing. Appearance preview, apply, rollback, topology registration, bootstrap, and
saved-world source attachment call it as a closed check.

`compatibility_key` binds a reviewed profile family to a topology family. Matching keys are
necessary for family binding and insufficient for structure/style identity. Live composed
topology digests are appearance compare-and-swap tokens. Structural `source_snapshot_id`
values are authored-write tokens. Hexadecimal equality across those planes is not the reason
for compatibility. Live typed identities may still agree when hex strings collide.

Appearance preview, apply, and rollback classify the offered write bases after locking the
live pointers. A write-base style that has never existed in this world is
`unknown_reference`. `historical_style_write_base` and
`historical_style_topology_apply_base` are the compare-and-swap refusals when the named
identity exists but is not current. `register_topology` classifies before it inserts
history, including the first register: with no live style, the default profile family is
the named family. `preview_required` / `style_topology_drift` is a CLASSIFY-family result;
family-matched digest change on `register_topology` is the composer handoff. COMPOSE tokens
are latent: there is no compose write. Attach admission refuses expired sources before
membership is written; that is not a stored-member COMPOSE pin.

Starter refuse uses a stored origin when one exists: the current snapshot's starter composer
key. When no snapshot exists, `world:authored:` is the stored starter `world_id` scheme, not
a heuristic over arbitrary strings. The saved entry `source_kind` column is not a
classifier input.

| Named planes | Outcome | Token |
| --- | --- | --- |
| Live style version and live composed digest, optional authored `source_snapshot_id` | **compatible** | `live_authorities_agree` |
| Attachment membership naming the saved style, authored version, and source snapshot | **compatible** | `attachment_membership_only` |
| `register_topology` family-matched digest change on a non-starter | **compatible** | `register_topology` |
| Bootstrap against the live composed digest with no current snapshot | **compatible** | `bootstrap_initial` |
| Bootstrap against the live composed digest and the existing current snapshot | **compatible** | `bootstrap_reuse` |
| Same profile family, style bound to a different composed digest than the live pointer (CLASSIFY) | **preview_required** | `style_topology_drift` |
| Historical style version used as an appearance write base | **refuse** | `historical_style_write_base` |
| Historical or selected style topology used as an apply or preview CAS token | **refuse** | `historical_style_topology_apply_base` |
| `register_topology` on a starter world with sourced slots | **refuse** | `starter_sourced_activation` |
| `register_topology` replacing a starter world's live composed digest | **refuse** | `starter_overlay` |
| Attachment rows offered as COMPOSE inputs (latent; no compose write) | **refuse** | `attachment_is_not_composition` |
| Expired attachments offered as COMPOSE facts (latent; no compose write) | **refuse** | `expired_source_not_composable` |
| Composed digest string equal to a structural topology digest used as identity, without live typed-identity agreement | **refuse** | `cross_plane_digest_equality` |
| Snapshot and composed digest supplied as one source-media address | **refuse** | `conflicting_plane_addresses` |
| Profile family keys differ | **refuse** | `profile_family_incompatible` |
| Unknown or cross-world snapshot, style, authored version, or attachment | **refuse** | `unknown_reference` |

Historical style may be displayed. Rollback copies historical values into a new version against
the live composed digest and the live style version. It does not write onto the historical
version or that version's bound topology.

Digests that may differ: structural snapshot digest, structural topology digest, composed
topology digest, and a style version's bound topology digest. None of those may be substituted
for another. Dual compare-and-swap remains: appearance writes compare live style version and
live composed digest; authored writes compare `source_snapshot_id` and the authored cursor.

Reviewed-source composition into geometry is absent. There is no public materialization route.

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
| `GET` | `/world/source-media` | Honest source states at the requested topology |
| `GET` | `/world/source-media/{id}` | Require one source to be locally available |

The domain problem codes are intentionally distinct:

| HTTP | Code | Recovery |
| --- | --- | --- |
| `422` | `invalid_style_data` | Correct the profile, manifest-backed parameter, scope, or provenance |
| `409` | `stale_style_version` | Read current state and create a new proposal. A historical style write base maps here; a UUID that never existed in this world does not |
| `409` | `protected_topology_conflict` | Recompose/review against the conflicting topology; never force appearance over it |
| `424` | `unavailable_asset` | Render the recorded honest fallback/state or restore authorised bytes |
| `409` | `invalid_preview_state` | Do not reapply a closed preview |
| `404` | `unknown_reference` | Treat absent and cross-workspace IDs identically, including an unknown style write base |

## Verification

`tests/test_world_style_contract.py` pins the Python adapter to the inspected frontend recipe
commit and rejects unknown modules/capabilities and executable/remote payload channels.
`tests/test_world_style_postgres.py` executes preview isolation, competing-writer exclusion,
topology invalidation, immutable rollback, three-origin audit provenance, and source states against
PostgreSQL 18. `tests/test_style_structure_compatibility.py` pins the plane-typed classifier,
including colliding hex with the live-authorities override, starter sourced activation,
historical write bases on the write path, and latent COMPOSE tokens.
`tests/test_world_api.py` holds the route shapes, problem codes (unknown
write-base style is `404 unknown_reference`; a historical style that exists but
is not current is `409 stale_style_version`), actor derivation, and
cross-workspace source behavior.
