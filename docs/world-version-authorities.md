# World version authorities

This contract owns the three server authorities that version a world's structure, its appearance
and its comfort settings. Each keeps immutable versions, one mutable current pointer per world, an
isolated preview, and compare-and-swap against the bases the caller read. Authored objects are a
fourth plane with a lifecycle of its own, specified in [world objects](world-objects-contract.md).
[ADR-0007](adr/0007-world-composition-and-customization.md) records the decision to keep these
planes separate. The browser half of appearance is the
[world customization contract](atlas-world-customization-contract.md).

## Contents

- [Shared discipline](#shared-discipline)
- [Structural authority](#structural-authority)
- [Appearance authority](#appearance-authority)
- [Structure and appearance compatibility](#structure-and-appearance-compatibility)
- [Source media](#source-media)
- [Comfort settings authority](#comfort-settings-authority)
- [HTTP surface](#http-surface)
- [Verification](#verification)

## Shared discipline

| Authority | Implementation | Current pointer |
| --- | --- | --- |
| Structure | migration `0020_durable_spatial_authority.sql`, `exulanica/world/structure.py`, `exulanica/world/structure_repository.py` | `world_structure_state` |
| Appearance | migrations `0017_adaptive_world_styles.sql`, `0023_frontend_world_recipe_contract.sql` and `0111_an_open_style_preview_expires.sql`, `exulanica/world/repository.py`, `exulanica/world/style-registry.v1.json` | `world_style_state` |
| Comfort settings | migration `0021_interaction_policy_versions.sql`, `exulanica/world/interaction.py`, `exulanica/world/interaction_repository.py`, `exulanica/world/interaction-policy-registry.v1.json` | `world_interaction_policy_state` |

All three follow the same rules:

- Versions, their regional or element rows and audit events reject UPDATE and DELETE in the
  database. The current pointer and the preview and proposal lifecycle rows are the only mutable
  rows.
- A preview validates a proposal and writes an isolated candidate. It never moves the pointer.
  Apply compares the bases the caller supplied, and the bases the preview recorded, with the live
  state, then inserts the version, moves the pointer, closes the preview and writes the audit event
  in one transaction. Discard closes only the preview. Rollback appends a new version that copies
  an earlier one; history is never rewritten and the pointer never moves backward.
- Values are canonical JSON in the repository's strict JCS subset (`exulanica.canonical`): sorted
  keys, compact UTF-8 and no IEEE-754 values. Protected values are fixed-point integers or
  reviewed choices, so an independent verifier can re-derive every digest.
- Every route except a registry catalog names the world as the `world_id` query parameter. An
  absent id and another workspace's id answer the same `404 unknown_reference`. FORCE row-level
  security applies to every table that holds a workspace's rows.
- The structural and comfort-settings writers, topology registration and every write bound to a
  saved world take the one per-workspace advisory lock (`exulanica/world/workspace_lock.py`) before
  any row lock. Appearance preview, apply and rollback lock the world's `world_style_state` row. The
  lock order for bound writes is in [saved-world entry](saved-world-entry.md#mutation-and-reopen).

## Structural authority

There is no public topology mutation route. Snapshots are written only by server-side composers
through `WorldStructureRepository`: the authored starter (`exulanica/world/starter.py`), the first
snapshot opened from composed sources (`bootstrap_world` in `exulanica/world/bootstrap.py`),
photographs added to a world made from photographs (`exulanica/world/personal_composition.py`), and
the frontier demonstration manifest (`exulanica/orchestration/demonstration.py`).
`@exulanica/atlas-core` also exports a browser draft adapter, `toSpatialAuthorityCandidateDraft` in
`web/packages/atlas-core/src/world/persistence.ts`, which quantizes a composed draft to integer
millimetres, microradians, thousandths and millidegrees and computes no authoritative digest. The
application submits no draft.

For every candidate the backend:

1. refuses floats and non-canonical ordering;
2. validates region, element, attachment, layout, neighborhood, destination, reachability,
   collision, source-evidence and dependency consistency;
3. derives canonical SHA-256 identities for topology, layout, placement, neighborhood and the
   enclosing snapshot;
4. validates every evidence, capture, entity and assertion dependency in the workspace;
5. computes a protected structural diff;
6. writes an isolated preview; and
7. on apply, repeats validation, inserts immutable history and moves the current pointer in the
   same transaction.

Arrays whose order carries no meaning arrive in the documented canonical order, so package
verification does not depend on a language-specific float printer.

**Concurrency and lineage.** Every preview records three bases: the current structural snapshot,
the graph SHA-256 and the reconstruction SHA-256. Apply takes the workspace lock and compares both
the caller's bases and the preview's with the current state. A mismatch closes the preview as stale
and changes no snapshot. Tombstone invalidation takes the same lock, which closes the race between
checking a dependency and committing. A world's first snapshot is made from its composed topology
(`base_composed_topology_digest`); photographs added to a made world append the next snapshot only
with the digest of the addition preview the person confirmed, which the applied audit row records.

Element identity is stable across snapshots. The database keeps the first snapshot and semantic
owner of each element, and each snapshot records membership and placement identity. Reusing an
element id for another world, region or relationship is refused. Moving a surviving region's
structural elements requires one explicit placement migration with a unique id, reason, before and
after digests, approver and committed snapshot.

**Deletion and fallback.** Each committed snapshot has relational dependency rows beside its
canonical JSON. A tombstone appends invalidation rows for every covered snapshot in its own
transaction; no snapshot is rewritten or deleted. `current()` reports the literal pointer and
whether deletion invalidated it. `effective_current()` walks parent links and returns the nearest
ancestor that is not invalid; when deletion covers the whole lineage it returns no structural
world, and a caller uses the non-spatial evidence and index path until a reviewed recomposition
commits a new snapshot. This is a fallback, not regeneration of deleted evidence.

**Separation from appearance.** A structural apply registers its topology contract with the
appearance authority in the same transaction: `register_topology` activates a composed contract,
and `register_topology_history` records one without moving the composed pointer or the style.
Appearance writes never touch a structural table.

**Package projection.** Every snapshot stores a declarative package projection: its identity,
parent, input graph and reconstruction identities, composer compatibility, fixed-point unit, and the
four section paths with their SHA-256 digests. The [World Memory Package](world-memory-package.md)
consumes that projection and never rereads a renderer scene.

## Appearance authority

The backend stores reviewed `WorldArtProfile` identifiers and versions; parameter values whose keys
resolve through a profile's manifest to the reviewed capability registry; immutable global and
regional style versions; protected topology digests, compatibility keys, region identities and
source-media slot bindings supplied by composition; isolated previews and their lifecycle; current
pointers; and proposal, apply, discard and rollback provenance. For a Companion proposal the
provenance includes reference ids, model id, prompt version and an optional `refines_proposal_id`.
The server derives the recipe, module and capability binding from its closed registry; clients and
models cannot submit one. Conversation text and preview-session state are not style fields.

It stores and returns no CSS, markup, JavaScript, shaders, renderer programs, remote texture URLs or
interface layout. `WorldStyleRepository.register_topology` is the internal handoff from a reviewed
composer after topology validation. Appearance requests cannot call it and cannot write region
identity, navigation, collision, transforms, evidence bindings, reconstruction requirements or
destinations.

**The registry.** `exulanica/world/style-registry.v1.json` is the one authored source for which
profiles exist, their names, descriptions, availability, modules and controls. The browser embeds
its exact bytes: `pnpm run world-style:sync` (`web/scripts/sync-world-style-registry.ts`) writes
`web/packages/presentation/src/world-style-registry-v1.generated.ts`, and
`tests/test_world_style_contract.py` and the presentation package's `world-style-registry.test.ts`
fail when the two differ. Only how each profile looks, and the historical module bindings a saved
world may still carry, are authored in the browser. The registry records the frontend recipe
contract it adapts (`frontend_contract.commit`, recipe schema version 1) and extends each descriptor
with an inert `recipeBinding`. The loader validates module ids, one-to-one capability ownership,
controls, profile versions, safe ranges and options, and availability and origin. Runtime database
roles read the registry rows and cannot write them. Two profiles are registered:
`origin-landscape@1`, shown as Aeroheart, which is supported and the default, and `survey-relief@1`,
which is experimental.

The catalog uses the frontend `WorldStyleCatalog` camel-case keys. Preview, apply and rollback
bodies accept both that casing and the API's snake-case names (`proposalId`, `baseStyleVersionId`,
`baseTopologyDigest`, `profileId`, `profileVersion` and regional `islandId`, beside `proposal_id`,
`base_style_version_id`, `base_topology_digest`, `profile_id`, `profile_version` and `region_id`) and
normalize both to one domain model.

**Fallback.** Unknown profile versions, modules, capabilities and parameters fail closed for new
proposals and when apply revalidates a preview. A new proposal names a supported exact profile
version, including one the registry marks experimental. Historical rows are never rewritten: a
removed, unsupported or unknown global profile resolves through its reviewed fallback chain with a
warning; a removed, unsupported, unknown or newly invalid regional override is ignored with a
warning; and the original row stays intact for export and audit. Historical parameters are
discarded, never interpreted against a newer recipe. The fallback chain is validated at load and
cannot contain a cycle; the default is `origin-landscape@1`.

**The style pack.** A version may name the style pack the world is drawn in: a pack of the host's
committed library ([style pack contract](style-pack-contract.md#9-the-library-the-host-serves)) by
id, version and manifest digest, in three columns that are all set or all null (migration 0141); a
version that names none, every version written before 0141 included, is drawn in the page's
default look. A preview may name a pack (`style_pack`, or `stylePack`, absent, a pack, or null for
none): a pack the library does not hold at exactly that version and digest is refused as
`invalid_style_data` naming it, and so is any pack named by a regional proposal, since a pack
dresses the whole world; a preview that names none keeps its base version's pack. Apply and
Rollback check the pack again against the library they run beside, so a host that no longer holds
it refuses the write by name rather than storing a pack it cannot serve; a version read from history
whose pack the host does not hold carries a warning naming it. A proposal row keeps the request as
sent (`{"pack": ...}`, or null when it named none), and each version, preview candidate and proposal
view states it (`style_pack`, with `style_pack_stated` on a proposal). A pack states no structure,
so naming one never touches the topology digest.

**The setting.** A version that names a pack may also state the world's own setting drawn over it
([style pack contract](style-pack-contract.md#12-a-worlds-setting)): one nullable column holding
the document (migration `a_world_states_its_own_setting`), stated inside `style_pack` on every
request, candidate, proposal and version that has one. It is checked against the manifests of
exactly the pack version named, at preview, Apply and Rollback, and one the pack cannot be drawn in
is `invalid_style_data`. A preview that names no pack keeps its base version's pack and setting; a
pack named with no setting clears it. Like the pack it states no structure. An appearance version
is history no erasure rewrites, so a setting holds nothing of a person: no words and no digest of
words.

**Transactions.** A style mutation locks the world's state row and compares both tokens:

```text
base_style_version_id == current_style_version_id
base_topology_digest   == current_topology_digest
```

Apply inserts the global version and all regional overrides, moves the pointer, closes the preview
and writes the audit event in one transaction. Rollback copies a historical version into a new
revision; regional overrides for regions absent from the current protected topology are omitted and
named in the rollback audit details.

**Open previews.** A preview stays open until apply or discard closes it, a new proposal replaces
it, or it outlives `OPEN_PREVIEW_LIFETIME` (seven days, in `exulanica/world/repository.py`, which
states the reason). The next preview of the world closes every preview past its lifetime as
`expired`, each with a `preview_expired` audit event, under the state-row lock every apply and
preview takes first. Apply refuses a preview past its lifetime as `409 preview_expired`; a discard
of one closes it as `expired`; and `GET /world/styles/proposals/{id}` reports it `expired` before
any write closes it, by the same predicate. `GET /world/styles/previews` reads back at most
`OPEN_PREVIEWS_READ` (eight) open previews a page may take up: proposals from an origin other than
Settings, of global scope, within their lifetime, newest first. The filter runs in the query before
the limit, and the read counts as `unreadable`, and leaves out, a row it cannot read, such as one
made before the recipe-binding contract. Opening a world closes no preview, because a page cannot
tell a preview an earlier page left from one a live tab holds. How a page takes up, shows and
refuses those proposals is the
[customization contract's frontend boundary](atlas-world-customization-contract.md#7-frontend-integration-boundary).

An apply bound to a saved world's resume point meets that world's checks first:
`409 stale_saved_world_entry` when another page advanced the resume point, and
`409 stale_style_version` when the saved appearance is no longer the live one. Those refuse without
closing the preview, which its lifetime then closes. Apply's own base check closes a stale preview
in the transaction that refuses it.

**Audit.** Rejected proposals are audit records too. Invalid style data, stale bases and topology
conflicts retain the supplied origin, the actor from the bearer token, the origin reference and the
rejection code. `settings` and `companion` proposals require an origin reference; `user` proposals
may omit one. The HTTP body has no actor field. Companion proposals also require a model id, a
prompt version and at least one opaque reference id. `GET /world/styles/proposals/{id}` exposes
accepted, rejected, discarded, stale or expired status, refinement lineage and the exact inert
recipe binding, without raw conversation or private reference media.

## Structure and appearance compatibility

`WorldStyleRepository.classify_structure_style_compatibility` is the plane-typed authority. It
writes nothing. Appearance preview, apply and rollback, topology registration, bootstrap and
saved-world source attachment call it as a closed check.

`compatibility_key` binds a reviewed profile family to a topology family. Matching keys are
necessary for family binding and insufficient for identity. Live composed topology digests are
appearance compare-and-swap tokens; structural `source_snapshot_id` values are authored-write
tokens. Hexadecimal equality across those planes is never the reason for compatibility, and live
typed identities may still agree when hex strings collide.

Appearance preview, apply and rollback classify the offered write bases after locking the live
pointers. A write-base style that never existed in this world is `unknown_reference`;
`historical_style_write_base` and `historical_style_topology_apply_base` are the refusals when the
named identity exists and is not current. `register_topology` classifies before it inserts history,
including the first registration: with no live style, the default profile family is the named
family. A starter's refusal uses a stored origin when one exists, the current snapshot's starter
composer key; with no snapshot, `world:authored:` is the stored starter `world_id` scheme. The saved
entry's `source_kind` column is not a classifier input.

| Named planes | Outcome | Token |
| --- | --- | --- |
| Live style version and live composed digest, optional authored `source_snapshot_id` | **compatible** | `live_authorities_agree` |
| Attachment membership naming the saved style, authored version and source snapshot | **compatible** | `attachment_membership_only` |
| `register_topology` family-matched digest change on a non-starter | **compatible** | `register_topology` |
| Bootstrap against the live composed digest with no current snapshot | **compatible** | `bootstrap_initial` |
| Bootstrap against the live composed digest and the existing current snapshot | **compatible** | `bootstrap_reuse` |
| Same profile family, style bound to a different composed digest than the live pointer | **preview_required** | `style_topology_drift` |
| Historical style version used as an appearance write base | **refuse** | `historical_style_write_base` |
| Historical or selected style topology used as an apply or preview token | **refuse** | `historical_style_topology_apply_base` |
| `register_topology` on a starter world with sourced slots | **refuse** | `starter_sourced_activation` |
| `register_topology` replacing a starter world's live composed digest | **refuse** | `starter_overlay` |
| Attachment rows offered as composition inputs | **refuse** | `attachment_is_not_composition` |
| Expired attachments offered as composition facts | **refuse** | `expired_source_not_composable` |
| Composed digest equal to a structural topology digest used as identity, without live typed-identity agreement | **refuse** | `cross_plane_digest_equality` |
| Snapshot and composed digest supplied as one source-media address | **refuse** | `conflicting_plane_addresses` |
| Profile family keys differ | **refuse** | `profile_family_incompatible` |
| Unknown or cross-world snapshot, style, authored version or attachment | **refuse** | `unknown_reference` |

`style_topology_drift` is a classification result; a family-matched digest change on
`register_topology` is the composer handoff. The two attachment refusals are what
[composition](world-composition-contract.md#composition-preview-and-apply) answers for an attachment
offered as a source; there is no attachment-to-geometry write. Historical style may be displayed.
Rollback copies historical values into a new version against the live composed digest and the live
style version, never onto the historical version or its bound topology.

Four digests may differ and none substitutes for another: the structural snapshot digest, the
structural topology digest, the composed topology digest, and a style version's bound topology
digest. Appearance writes compare the live style version and the live composed digest; authored
writes compare `source_snapshot_id` and the authored cursor.

## Source media

Source-media slots belong to a topology contract, never to a style proposal. A slot carries an
evidence span from the same workspace or a non-empty reason that evidence is missing; a composite
foreign key enforces the workspace and span together.

Source-media list and single-source reads accept `source_snapshot_id` or `topology_digest`. A
snapshot address resolves the exact structural topology in the requested workspace and world.
Unknown addresses return 404, invalidated snapshots 409, and both addresses together 422. Omitting
both reads the current topology. Saved-world reopening supplies its stored snapshot id rather than
following the global pointer.

`GET /world/source-media` reports one of three states:

- `available`: authorized evidence metadata exists, its capture is live, the blob is not purged and
  the bytes are in the content-addressed store;
- `unavailable_asset`: the binding exists but its capture, row or bytes are unavailable; a
  personal photograph whose authorization or human review is no longer current reads this way
  (`lapsed_personal_captures` in `exulanica/world/reviewed_sources.py`);
- `missing_evidence`: the topology recorded that no evidence exists for the slot, with the reason.

Only an available source carries a local authenticated evidence path such as `/evidence/{span_id}`
and an `asset_reference` naming its source slot and evidence-span provenance and declaring
workspace-bearer authorization. No remote asset URL is accepted or emitted.
`GET /world/source-media/{source_id}` returns `unavailable_asset` rather than inventing media.
Unknown and cross-workspace source ids return the identical `unknown_reference`. How the browser
loads these bytes is in the
[customization contract](atlas-world-customization-contract.md#6-source-media-contract).

## Comfort settings authority

The reviewed registry, `exulanica/world/interaction-policy-registry.v1.json`, seeded into
`interaction_capability_registry` by migration 0021, holds eight capabilities the browser already
understands: field of view, look sensitivity, vignette, camera bob, turn mode, transition style,
provenance detail and Companion initiative. Values are booleans, bounded integers or enumerated
strings; sensitivity is stored in integer thousandths. Runtime roles read the registry and cannot
extend it. A proposal cannot carry code, layout, shaders, URLs or an unreviewed capability. Every
candidate is derived deterministically from the complete current parameter set plus a validated
patch, so the policy SHA-256 has one language-independent input.

A world's comfort settings belong to that world: the browser reads and writes the policy of the
world it has open, when that world opens, and settings saved in one world are not read in another.

**Two origins, one lifecycle.** Settings and the Companion create the same durable proposal and
isolated preview records. Settings is a direct choice, so the browser may apply its preview after a
control's final `change` event; range `input` events are transient local previews that create no
history. A Companion suggestion stops after preview and returns a review handle; only a separate
confirmation calls `applyCompanionReview` (`web/packages/app/src/interaction-policy.ts`). Companion
proposals require an origin reference, model id, prompt version and at least one source or
observed-choice reference. Raw utterances, messages, transcripts, conversation payloads and prompt
text are refused as durable proposal input.

The browser hydrates an existing durable version in a later session or on another device, keeping
device-only display choices. It does not silently migrate a local preference bundle when no durable
version exists, and a failed durable write is reported as device-only.

**Protected bases.** Preview and apply compare the current policy version together with the current
structural snapshot id and topology SHA-256, under the workspace lock. An interaction transaction
cannot modify topology, layout, placement or neighborhoods. Proposal records keep origin, actor,
input summary, capability mapping, explanation, references, validation issues, refinement parent
and lifecycle state, so an inspector can answer why a change exists.

**Recommendations are observations.** `GET /world/interactions/recommendations` counts repeated
applied and rejected explicit choices and returns a proposed value, observation counts and an
explanation. Reading it creates no proposal, preview, version or audit event; a recommendation
changes the policy only through the reviewed lifecycle.

Human comprehensibility and long-term stability of these adaptations are not validated. That needs
consented participants, repeated sessions, a defined instrument and recorded results, and none are
recorded.

## HTTP surface

All routes require a bearer token.

| Method | Route | Result |
| --- | --- | --- |
| `GET` | `/world/styles/catalog` | Reviewed profiles and capability-backed controls |
| `GET` | `/world/styles/current` | Current version plus the independently current topology digest |
| `GET` | `/world/styles/versions` | Immutable resolved history with warnings and provenance |
| `GET` | `/world/styles/proposals/{id}` | Proposal status, provenance, refinement and recipe binding |
| `GET` | `/world/styles/previews` | Open previews a page may take up, newest first, each with its proposal, and how many could not be read |
| `POST` | `/world/styles/previews` | Validate and create an isolated preview |
| `POST` | `/world/styles/previews/{id}/apply` | Compare both bases and apply atomically |
| `DELETE` | `/world/styles/previews/{id}` | Discard without changing the current style |
| `POST` | `/world/styles/rollback` | Append a version matching historical style values |
| `GET` | `/world/source-media` | Source states at the requested topology |
| `GET` | `/world/source-media/{id}` | Require one source to be locally available |
| `GET` | `/world/interactions/catalog` | The reviewed comfort capabilities |
| `GET` | `/world/interactions/current` | The world's current policy version |
| `GET` | `/world/interactions/versions` | Immutable policy history |
| `GET` | `/world/interactions/proposals/{proposal_id}` | One proposal's status and provenance |
| `GET` | `/world/interactions/recommendations` | Observed repeated choices; writes nothing |
| `POST` | `/world/interactions/previews` | Validate and create an isolated preview |
| `POST` | `/world/interactions/previews/{preview_id}/apply` | Compare the policy and structural bases and apply |
| `DELETE` | `/world/interactions/previews/{preview_id}` | Discard without changing the current policy |
| `POST` | `/world/interactions/rollback` | Append a version copying an earlier one |

The problem codes are distinct because the recovery differs:

| HTTP | Code | Recovery |
| --- | --- | --- |
| `422` | `invalid_style_data` | Correct the profile, parameter, scope or provenance |
| `409` | `stale_style_version` | Read the current state and propose again. A historical write base maps here; a UUID that never existed in this world does not |
| `409` | `protected_topology_conflict` | Recompose or review against the conflicting topology; never force appearance over it |
| `424` | `unavailable_asset` | Show the recorded state or restore the authorized bytes |
| `409` | `invalid_preview_state` | Do not reapply a closed preview |
| `409` | `preview_expired` | The preview outlived its lifetime and is closed; propose the change again |
| `422` | `invalid_interaction_data` | Correct the comfort capability or value |
| `409` | `stale_interaction_policy` | Read the current policy and structural bases and propose again |
| `409` | `invalid_interaction_preview_state` | Do not reapply a closed comfort preview |
| `404` | `unknown_reference` | Absent and cross-workspace ids are indistinguishable, including an unknown style write base |

## Verification

- `tests/test_world_structure.py` covers canonical repeatability, embedded-digest tampering, float
  and ordering refusal, required-destination reachability and collision refusal.
  `tests/test_world_structure_postgres.py` covers immutable apply, stable identity, package
  projection, competing stale composers, required placement migrations, appearance separation,
  live evidence binding, tombstone invalidation and nearest-valid-ancestor fallback on PostgreSQL.
- `tests/test_world_style_contract.py` holds the registry equal to the browser's embedded copy and
  pins the frontend recipe contract, and refuses unknown modules and capabilities and executable or
  remote payload channels. `tests/test_world_style_postgres.py` executes preview isolation,
  competing-writer exclusion, topology invalidation, immutable rollback, three-origin audit
  provenance and source states. `tests/test_style_structure_compatibility.py` pins the classifier,
  including colliding hex with the live-authorities override, starter sourced activation, historical
  write bases and the attachment tokens. `tests/test_world_style_open_previews.py` holds the
  read-back filter, the preview lifetime, its closing and `409 preview_expired`.
  `tests/test_world_api.py` holds route shapes, problem codes, actor derivation and cross-workspace
  source behavior. `tests/test_world_style_pack_binding_postgres.py` and
  `tests/test_world_style_pack_api_postgres.py` hold a version's style pack through preview, apply,
  rollback and reads, and `tests/test_style_pack_binding_migration_postgres.py` holds 0141 over
  earlier rows and its checks. `tests/test_world_setting_binding_postgres.py` and
  `tests/test_world_setting_api_postgres.py` hold a version's setting the same way, with the
  migration that adds it over earlier rows.
- `tests/test_interaction_policy_postgres.py` covers registry parity, deterministic candidates,
  state-neutral discard, immutable apply, origin, model, prompt and refinement records, transcript
  exclusion, stale policy and structural bases, append-only rollback and recommendation
  non-mutation. `web/packages/app/test/interaction-policy.test.ts` covers exact Settings patches
  through preview then apply, device-only settings that write nothing, Companion attribution and
  the split between a Companion preview and its separate apply, and hydration that keeps device-only
  presentation; `interaction-settings.test.ts` holds the page's controls to the served catalog.
