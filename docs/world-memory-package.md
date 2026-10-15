# World Memory Package v1

This contract owns the World Memory Package (WMP): the signed, portable projection of one world
and the authorized workspace state it draws on, under profile `exulanica-wmp-1.0`; its two optional
extensions for authored state; the separately selected training dataset profile; and the distinct
editable repository checkpoint boundary. Verifying a
package never loads a world, and a package is never the live store.

**Authored world state:** [product direction](product-direction.md#package-and-api-boundaries)
asks for authored state and behaviour references without changing the 1.0 profile. Objects,
overrides and schema-version-1 deltas are carried by an optional, separately versioned
extension, `exulanica-wmp-ext-authored-world`, in versions 1.0 and 1.1, specified in
[its own section below](#authored-world-extension-10). Environment-inclusive authored state
is a second optional extension, `exulanica-wmp-ext-environment-instances`, also in versions 1.0
and 1.1, specified in [Environment-instances extension 1.0](#environment-instances-extension-10).
Version 1.1 of each also carries the edits that give a placed object a behaviour, change it or
take it away, so a world with motion exports whole. One rule decides which alternate versions
an extension carries ([Which versions an extension carries](#which-versions-an-extension-carries)).
The 1.0 profile, its eighteen required paths and its signature payload do not change with the
extensions, and a package written without either extension is byte for byte what the projector
wrote before the extensions existed, apart from the names a withdrawn person's rows withhold (see
[Inventory and privacy boundary](#inventory-and-privacy-boundary)).

The World Memory Package (WMP) is a signed projection of one PostgreSQL snapshot. It is not the
live store, a backup, a consent grant, or an executable world. An exported copy cannot be recalled.
After a deletion, a new export has a new root and the semantic diff is the durable account of what
was removed or recomputed.

**Composition extension:** [world-composition-contract.md](world-composition-contract.md)
defines imported geography, selected subsets, place relationships, source-use
rights and authored placement. Source-use rights, reusable geographic selection
and a runnable import are not part of WMP 1.0, authored-world 1.0, or
environment-instances 1.0. Durable authored environment placements are the
environment-instances extension. A signed package does not grant source reuse
rights, carry missing asset bytes or establish a runnable import.

<details>
<summary>Sections</summary>

- [Why the package is a projection, not the store](#why-the-package-is-a-projection-not-the-store)
- [Standards and compatibility boundary](#standards-and-compatibility-boundary)
- [Snapshot, publication, and receipt](#snapshot-publication-and-receipt)
- [Inventory and privacy boundary](#inventory-and-privacy-boundary)
- [Integrity format](#integrity-format)
- [Commands](#commands)
- [Profile verification](#profile-verification)
- [Which versions an extension carries](#which-versions-an-extension-carries)
- [Authored-world extension 1.0](#authored-world-extension-10)
- [Environment-instances extension 1.0](#environment-instances-extension-10)
- [Explicit training dataset profile](#explicit-training-dataset-profile)
- [Editable repository checkpoints](#editable-repository-checkpoints)

</details>

## Why the package is a projection, not the store

Content addressing, an append-only ledger and a right to erasure cannot all hold of one store: every
export format that gives strong versioning and reproducibility does so by making history immutable,
so if the package were the database, deletion would be a lie. GDPR does not itself define erasure,
and erasure may be satisfied by irreversibly destroying the link between the data and the data
subject; standard guidance for immutable stores is to keep personal data off them
(<https://arxiv.org/pdf/2210.04541>, VERIFIED 2026-08-27).

**DECISION (wmp-1): two zones.**

| | Zone 1: live store | Zone 2: World Memory Package |
| --- | --- | --- |
| What | PostgreSQL plus blob storage | A materialised RO-Crate produced by projecting zone 1 at an instant |
| Mutability | Mutable; rows are deletable | Immutable once written, content addressed, signed |
| Raw media | Lives here, and only here | Excluded by default, described by fetch-style external references with digests, so a recipient can verify but not read |
| Embeddings and identity exemplars | Live here | Excluded by default |
| Append-only content | The pipeline ledger only, with payloads scrubbed to hashes on deletion | The whole package, by construction |
| Deletion | Real and complete | Not possible; an exported package cannot be recalled |

Rejected: making the content-addressed, append-only package the live store, which gives the
strongest reproducibility story and makes deletion impossible; and DVC or a Git-coupled pointer
system, where erasing an exemplar is a history rewrite that every clone keeps.

**DECISION (wmp-2): the format.** RO-Crate 1.2 under an Exulanica profile crate, with a Croissant
1.0 and RAI descriptor for the learning dataset in the same JSON-LD graph, BagIt-style fetch
semantics for excluded raw media, and a signed Merkle-root manifest supplying the versioning
RO-Crate lacks. VERIFIED (2026-08-27): RO-Crate 1.2 requires exactly one `ro-crate-metadata.json` at
the crate root, is JSON-LD over schema.org and is backwards compatible with 1.1; Croissant 1.0 is
JSON-LD over schema.org with a RAI extension (`rai:dataCollection`, `rai:dataAnnotationProtocol`,
`rai:personalSensitiveInformation`), so a Croissant `sc:Dataset` can be a node in the RO-Crate
graph; BagIt (RFC 8493) requires a checksum per payload file, and `fetch.txt` declares payload held
outside the bag. Sources: <https://www.researchobject.org/ro-crate/specification/1.2/structure>,
<https://docs.mlcommons.org/croissant/docs/croissant-spec.html>,
<https://docs.mlcommons.org/croissant/docs/croissant-rai-spec.html>,
<https://www.rfc-editor.org/rfc/rfc8493.html>. Rejected: OCI image spec 1.1 artifacts as the format
(they need a registry, registry deletion is tag-and-garbage-collect rather than erasure, and they
impose no schema; kept as a possible transport); Frictionless Data Package v2; LakeFS; Delta Lake
and Iceberg; and a hand-rolled content-addressed directory, whose Merkle-root idea is adopted.

**What the product must say.** Deletion in the live store is real and complete, within the limits
in [privacy-consent-threat-model.md](privacy-consent-threat-model.md) section 5.5. A package
exported to a third party cannot be recalled, and the export dialog says so before the export runs.
Re-exporting after a deletion produces another version with a different Merkle root, and the diff
between two package versions is the honest answer to "what changed".

## Standards and compatibility boundary

`wmp/profile.json` is the versioned Exulanica profile. The identifier is `exulanica-wmp-1.0`.
The pre-release `orimera-wmp-1.0` profile was withdrawn before release; ADR-0011 records that
no externally retained signed package used it. WMP remains version 1 under the corrected name.
`ro-crate-metadata.json`
uses the RO-Crate 1.2 context by reference, describes `./` as the root Dataset, and declares that
profile on the root. The same graph contains a Croissant 1.0 and Croissant RAI 1.0 compatibility node with the
package limitations and sensitive-information declaration. WMP does not claim that its component
JSON documents are generic Croissant record sets.

Canonical component files use Exulanica's strict no-float JSON subset. That subset has the sorted
keys, UTF-8, and insignificant-whitespace properties needed by RFC 8785, but goes further: an IEEE
754 value is never emitted as a JSON number. Historical database floats are represented as tagged
exact hexadecimal values. Protected topology, placement, appearance, and interaction values remain
their fixed-point integers or reviewed choices.

## Snapshot, publication, and receipt

`project` requires an idle workspace-scoped connection and starts a `REPEATABLE READ` transaction.
The first reads capture the current structure, appearance, and interaction pointers. Every graph,
evidence, artifact, provenance, evaluation, deletion, and policy component is then read from that
same database snapshot. Every read names the projected workspace itself rather than relying on
row-level security, so a projection on an owner or BYPASSRLS connection, as person withdrawal and
the package command make, carries no other workspace's rows
(`tests/test_world_package_scoped_postgres.py`). The projector writes a sibling staging directory, scans every JSON payload,
builds and signs the manifest, inserts the append-only `world_package_export` receipt, and renames
the staging directory into place before commit. A failed transaction removes the newly published
directory.

The receipt records the protected current-version IDs, profile version, Merkle root, manifest
digest, optional parent root, Ed25519 public-key fingerprint, actor, export policy, and database
time. None of those audit rows feed the package root, so exporting unchanged state with the same
lineage produces the same root. The receipt is a workspace-keyed FORCE RLS table and rejects
update and delete.

No signing key is generated implicitly. `project` requires an explicit Ed25519 private-key path.
`keygen-test` is named and reported as ephemeral test material; tests generate keys only in their
temporary directories or memory. No production key or trust decision is committed here.

## Inventory and privacy boundary

The package contains canonical JSON for:

- semantic graph, evidence descriptors, and digest-only authorized fetch references;
- reconstruction descriptors and honest unavailable, purged, repair, or resolver-required state;
- current topology, layout, placement, neighborhood, appearance, and interaction state;
- reviewed appearance and interaction registry references required to interpret current values;
- pipeline/model attempt provenance without hosts, error messages, or payload bytes;
- explicitly supplied evaluation reports, or `unavailable` with its reason;
- deletion tombstones without the private reason or requesting actor; and
- export/consent boundary and generated-content declarations.

A package holds no search entries, so a `caption_search` tombstone, written when a person stops a
photograph's search right, is in `deletion/tombstones.json` as an audit record that blocks nothing:
the photograph and the rest of `memory/graph.json` are the same in a package made after the stop as
in one made before it (`tests/test_world_package_caption_search.py`).

A person who withdrew is exported without their name. Their entity row and their naming
assertions stay in `memory/graph.json`, so the package still shows that somebody was named and
when; the entity's `display_name` and each naming assertion's `object_value` are null, and each
such row carries `withheld` naming the field and the reason. The rule is the read path's
(`exulanica/graph/entities.py`), asked of the same predicate. Before signing, the projector reads
back the files it is about to sign: every row of a withdrawn person must withhold its name and say
why, and the package is refused when any JSON value anywhere in it is a name that person was ever
saved under, so a field that carried a name past the rule is refused rather than signed. The one
exception is a name somebody who did not withdraw is also saved under and carries in their own
row: two people can share a name, and the one who did not withdraw keeps theirs, which also means
a later field carrying that shared name is not caught
(`tests/test_world_package_withdrawal_postgres.py`).

The default scanner rejects raw media, credentials, biometric templates, embeddings, private
conversation fields, model caches/internals, training intermediates, executable UI assets, shaders,
and remote executable bindings. Media references contain a digest, size, type, RFC 6920 `ni` URI,
and the explicit statement that an authorized content-addressed resolver is required. An `ni` URI
is not presented as a public download URL.

## Integrity format

`wmp/manifest.json` lists every payload path, byte length, and SHA-256 digest in sorted path order.
Leaves bind the domain separator `exulanica-wmp-leaf-v1`, the UTF-8 path, and the file digest.
Internal nodes bind `exulanica-wmp-node-v1` and the two child hashes; an odd final child is
duplicated. Those separators are the v1 domain-separation strings. `wmp/signature.json`
contains the Ed25519 public key and a signature over the canonical profile version, manifest digest,
and Merkle root. The manifest and signature do not include themselves in the Merkle inventory.

The offline verifier rejects non-canonical JSON, symbolic links, inventory additions/removals,
digest or length changes, root changes, signature changes, unsupported profiles, and prohibited
content. Integrity does not establish export authorization; `policy/export.json` and the CLI say so
explicitly.

## Commands

```text
exulanica-wmp project --workspace UUID --world WORLD_ID --actor UUID --private-key KEY
                      --output DIRECTORY [--parent-root ROOT] [--evaluation-report REPORT ...]
                      [--extension authored-world-1.0 | authored-world-1.1]
                      [--extension environment-instances-1.0 | environment-instances-1.1]
exulanica-wmp verify DIRECTORY
exulanica-wmp inspect DIRECTORY
exulanica-wmp diff BEFORE_DIRECTORY AFTER_DIRECTORY
exulanica-wmp import-check DIRECTORY [--loader-capability CAPABILITY ...]
                           [--supported-style-profile ID@VERSION ...]
                           [--supported-interaction-capability KEY@VERSION ...]
```

`project` packages the world `--world` names, one of the workspace's worlds (`GET /worlds` lists
them), and refuses one the workspace does not hold. It takes at most one version of each extension
and refuses a request for two.
`verify`, `inspect`, `diff`, and `import-check` do not open PostgreSQL. Diff output reports semantic
JSON pointers and before/after value hashes, not the values themselves. `import-check` never mutates
a live world; absent receiver capability declarations produce `indeterminate`, not a fabricated
compatibility pass. Import remains a later explicit transaction and is not implemented as a side
effect of inspection.

**Verification is not loading, and the output says so.** `verify` reports `verified: true` together
with `runtime_loadability: "not assessed: verify never loads a world..."` and a `summary` sentence
naming exactly what was checked: bytes, inventory, canonical JSON, profile, prohibited-content
boundary, the rules of every extension this verifier knows, the Merkle root and the Ed25519
signature. It names any extension it does not know as not checked, and `uninterpreted_paths` lists
any optional payload outside `extensions/`. Only `import-check`, given what a receiving loader
declares, says anything about loading.

## Profile verification

The WMP 1.0 tests cover a clean subprocess with database URLs removed, one-byte payload and
manifest mutation, every prohibited class, symlink and unexpected-file rejection, concurrent
mutation after the repeatable-read snapshot begins, immutable audit receipts, deterministic
unchanged re-export, and deletion followed by a new root and semantic removed-state diff.

## Which versions an extension carries

A version is written into an extension only when it and every version it was branched from fit
that extension version's format: every edit kind in their edit chains is one the version admits,
and every delta section their state holds or their chains change is one it carries. The formats
are data in [`extension_formats.py`](../exulanica/world_package/extension_formats.py), each
version's closed list of edit kinds stated once. [`export_partition.py`](../exulanica/world_package/export_partition.py)
decides from those lists and from the edit-kind registry
([`edit_kinds.py`](../exulanica/world/edit_kinds.py)), which says which subject each kind
changes; the projection itself names no edit kind. A kind the product gains later is in no
format, so every version whose lineage carries it is withheld until an extension version admits
it (a 1.1 package names the kind among its reasons), and a kind the registry does not hold
refuses the export by name.
`tests/test_world_package_export_partition.py` adds a kind to a copy of the registry and shows
it withheld.

| Extension versions | Edit kinds admitted beyond 1.0 | How withheld versions are counted |
| --- | --- | --- |
| authored-world 1.0, environment-instances 1.0 | none | One total, `withheld.invalidated_source_versions`, under a deletion's reason whatever withheld them |
| authored-world 1.1, environment-instances 1.1 | `set_object_behaviour` | By reason: `source_invalidated`, `edit_kind_not_admitted` or `section_not_carried`, each with the kinds or sections it names |

No version carries a placed photograph point map (the `add_point_map`, `move_point_map` and
`remove_point_map` edits and the `point_map_instances` section). A placed estimate is a reading
of somebody's home bound to a right its owner can end, and a package that leaves the machine is
beyond the reach of that withdrawal, so exporting one is a decision rather than a projection:
those versions, and every version branched from one, are withheld and counted. A withheld version
is never named: its title, identifier and state stay out of the package.

No version carries an object drawn from a workspace's own admitted asset either. Such an asset is
used in its own workspace's worlds and nowhere else
([workspace asset admission](workspace-asset-admission.md)), so a version holding one, and every
version branched from it, is withheld under `section_not_carried` with the name
`workspace_assets`, which no format carries. The versions before it still export.

A version goes to the smallest extension family that carries every section its lineage needs:
authored-world for objects and overrides alone, environment-instances when environment
instances are involved. A family that was not requested is judged by its format of the version
that was, so a request for 1.0 behaves exactly as it did before 1.1 existed. A kept version that
only an unrequested family can hold refuses the export and names the extension to request.
`tests/fixtures/wmp-goldens` pins every file of a rich fixture world, and every refusal, under
every combination of extension versions.

## Authored-world extension 1.0

Status: **OPT-IN EXTENSION `exulanica-wmp-ext-authored-world` 1.0 AND 1.1**. Implementation:
`exulanica/world_package/authored.py` (sections, verifier rules and loader report for both
versions), `extension_projection.py` (the projection), `package.py` (extension discovery and
`import-check`). It carries the state [world-objects-contract.md](world-objects-contract.md)
defines: alternate versions, their authored objects and source-element overrides, and the reviewed
asset and behaviour references those objects make.

### Why an extension and not a 1.1 profile

A 1.1 profile with new required paths is ruled out by two facts, without a migration.
`REQUIRED_PAYLOAD_PATHS` is checked before
the signature, so a new required path makes every already-signed 1.0 package unverifiable while its
bytes are sound (`tests/test_world_package_verifier.py` holds this). Migration 0028 checks
`world_package_export.profile_version = 'exulanica-wmp-1.0'`, so the projector cannot receipt a
1.1 export. An optional directory breaks neither: the manifest inventories it, the Merkle root and
signature cover it, the prohibited-content scanner reads it, and a verifier that predates it still
verifies the package. The profile version in the manifest and the signature stays `exulanica-wmp-1.0`.

### Layout

Exactly four canonical JSON files under `extensions/authored-world-1.0/`; any other file there is
refused, which is what keeps asset bytes from riding along unchecked.

| File | Holds |
| --- | --- |
| `extension.json` | Name `exulanica-wmp-ext-authored-world`, version `1.0`, base profile `exulanica-wmp-1.0`, section paths, counts, `required_loader_capabilities`, and the fixed statements that asset bytes are not embedded and runtime code is not carried |
| `versions.json` | Every exported alternate version: pseudonymous `version_id`, `parent_version_id`, `source_snapshot_id` and `style_version_id` URNs, title, `origin`, `state_sha256`, `edit_seq`, `created_at`, the canonical `delta`, and the edit chain; plus `source_snapshots` (URN, `snapshot_sha256`, `current`, region and element ids) and a `withheld` count |
| `assets.json` | The reviewed assets the objects name: key, title, summary, media type, `content_sha256`, byte size, licence id and licence digest, an RFC 6920 `ni` URI, and `retrieval: "requires an authorized content-addressed resolver"`. No URL and no bytes |
| `behaviours.json` | The reviewed behaviours the objects name: key, version, summary and parameter bounds |

`delta` is the document `exulanica.world.authored_delta.canonical_delta_document` builds, so its
SHA-256 over the canonical JSON rule is the version's `state_sha256`, the same token
`GET /world/versions` returns and every edit names as its base. Objects keep their region-local
fixed-point transforms, their `origin` (`authored`, with the role the person chose) and their
behaviour key, version and parameters. Ids are pseudonymised with the same
`urn:exulanica:wmp:<kind>:<sha256>` rule as the 1.0 components, so `version_id` is
`sha256("alternate-version:" + uuid)`: a holder of the version id can match it, and the package
alone does not reveal it.

The extension is added only when `project` is given `--extension authored-world-1.0`, or
`--extension authored-world-1.1`, which writes `extensions/authored-world-1.1/` with the same four
files and the differences [the rule above](#which-versions-an-extension-carries) names. With it, the
eighteen 1.0 payloads are unchanged except `ro-crate-metadata.json`, which gains the four files in
`hasPart`, one `Profile` node for the extension, and a `conformsTo` on `extension.json`. The crate
root still conforms to the 1.0 profile alone, because a 1.0 verifier requires exactly that value.
The export receipt's `export_policy` records the extension; the package root does not depend on it.

### What is not exported

- **Actors.** `created_by` and each edit's `actor` are omitted, as tombstones omit the requesting
  actor. The digests that make the edit chain checkable are kept.
- **Versions whose source was deleted.** A version is
  invalid exactly when its source snapshot carries a `world_structure_invalidation` row. The
  projector already withdraws a scene when one member is deleted, and an authored delta posed in the
  regions of withdrawn structure is the same kind of claim, so such a version is withheld and only
  counted (`withheld.invalidated_source_versions`, or `source_invalidated` in 1.1), never named.
  The authored work survives in the database and in `GET /world/versions`. Invalidation is per
  source snapshot and a branch shares its parent's source, so no exported version names a
  withheld parent.
- **Under 1.0, versions whose edit chain changes a behaviour.** The 1.0 closed lists of edit kinds
  do not name `set_object_behaviour`, the edit that gives a placed object a behaviour, changes it
  or takes it away, so under 1.0 a version whose chain carries one, and every version branched from
  it, is withheld and counted in `withheld.invalidated_source_versions`, the 1.0 package's one
  withheld total. Version 1.1 admits the edit and exports those versions: each object carries the
  reviewed behaviour and parameters the database stores, and the chain names every behaviour edit.
  A behaviour named when the object was added is part of `add_object` and exports with the object
  under either version.
- **Asset bytes and runtime code.** An asset is a digest an authorized resolver supplies; a
  behaviour is an identifier with bounded parameters. Embedding reviewed CC0 bytes would be a new,
  separately versioned opt-in, and this version refuses any file it does not name.
- **Environment instances and society.** The extension is frozen against authored delta schema
  version 1. Durable `environment_instances` select schema version 2 and are not projected by
  `exulanica/world_package/authored.py`. A version whose live state includes those instances, or
  whose edit chain names an environment edit, is absent from this directory. A schema-v1
  descendant of such a version is absent too: the parent cannot be written here, and a parent
  pointer must resolve in this directory. Projecting `authored-world-1.0` alone then refuses;
  the environment-instances extension below is the export of that state. Dual export does not
  write this directory with zero versions while those versions live next door. Deterministic
  society state and events are also absent. A receiver therefore cannot reconstruct an imported
  district placement or resume its synthetic society from this extension. Those capabilities
  are never inferred from the presence of authored objects.

### Verifier rules

A verifier that knows the extension refuses the package, even though its signature is sound, when:
the directory does not hold exactly the four files; a section has an unknown profile, a missing or
extra field, or items out of sorted order; a `state_sha256` does not re-derive from its `delta`; an
object names an asset or behaviour the sections do not list, a region its source snapshot lacks, a
non-authored origin, a transform outside the fixed-point contract, or a parameter outside its
reviewed bound; an override names an element its source lacks; a parent is missing, on another
source, or cyclic; the edit chain is not contiguous, an edit's base is not the previous result, a
source-created version's first base is not the empty delta's digest, or the chain does not end at
the exported state; the source snapshot marked `current` disagrees with `world/structure.json` or
`world/topology.json`; the sections list assets, behaviours or snapshots nothing references; or
`extension.json` does not match what the sections require. The digest is re-derived with the
canonical JSON rule alone, not with the product's domain code, and a test holds the two equal.
A 1.1 verifier also admits `set_object_behaviour` in a chain, and refuses a `withheld` section
whose reasons are out of order or repeated, fall outside the three reasons, name a kind or
section for a deletion or none for the other two, count no version, or do not add up to its
total. The same chain under 1.0 is refused at the behaviour edit.

Any other directory under `extensions/` must carry an `extension.json` naming its extension,
version, base profile and required loader capabilities, or the package is refused. An extension
this verifier does not know is verified for integrity only and reported as not checked.

### Loader capabilities and `import-check`

A loader declares capabilities in one vocabulary. The existing flags are the same declarations
without their prefix and are merged in.

| Capability | Required when |
| --- | --- |
| `style-profile:<id>@<version>` | the appearance is current (unchanged 1.0 rule) |
| `interaction:<key>@<version>` | the interaction policy is current (unchanged 1.0 rule) |
| `wmp-extension:exulanica-wmp-ext-authored-world@1.0` or `@1.1` | that version of the extension is present |
| `asset-resolution:sha256-content-address` | any object that is not removed exists |
| `asset-media:model/gltf-binary` | such an object's asset has that media type |
| `behaviour:motion.bounded-path@1` | such an object carries that behaviour |

A removed object requires nothing, because it is part of the state digest and is not drawn.
`import-check` keeps every 1.0 field with its 1.0 meaning, including `compatible` for the base
world, and adds `declared_loader_capabilities`, `unsupported_capabilities`, a per-extension report
and `loadability`:

| `loadability` | Meaning |
| --- | --- |
| `indeterminate` | The loader declared nothing, so nothing is called supported or unsupported |
| `refused` | A base style profile or interaction capability is unsupported |
| `partial` | The base loads; an extension, an asset path or a behaviour is unsupported and is named |
| `complete` | Every capability the signed content requires was declared |

A loader without extension support gets `load: "not loaded"` and a warning naming how many alternate
versions and present objects it leaves behind, which it must say rather than present the source
world as the whole package. A loader with the extension but not a behaviour gets the objects listed
under `objects_with_unsupported_behaviour`, to be shown present with the behaviour marked
unsupported, so an unsupported behaviour fails visibly. `import-check` runs no loader: a
declared capability is the loader's claim, and the answer is a comparison of that claim with the
signed content.

A verified package and one a loader can run are separate answers. `verify` checks a moving
object's behaviour against its reviewed bounds and says loading was not assessed; only
`import-check` answers for a loader. One that does not declare `behaviour:motion.bounded-path@1`
gets the moving objects under `objects_with_unsupported_behaviour`, and one that declares
authored-world 1.0 and not 1.1 gets `not loaded` with what it leaves behind.

### What a signed package does and does not guarantee

It guarantees that the bytes are the ones the key holder signed, that the inventory is complete, that
no prohibited class of content is present, and, for a verifier that knows the extension, that the
authored state is internally consistent: every state token re-derives, every edit chain closes, and
every reference resolves inside the package.

It does not guarantee that the signer was authorized to export, which needs the issuer's trusted key
fingerprint and is outside the package. It does not guarantee historical truth: an authored object is
authored, and `origin.role` is what a person chose, never a claim the source world supports. It does
not guarantee that the assets can be fetched, since only their digests travel, or that any renderer
will execute a behaviour, or execute it identically: the registry bounds parameters and the runtime
owns trigger, stop and reset. It does not reveal authored work that was withheld because its source
was deleted, and it cannot recall a copy already handed out.

One limit is structural rather than a gap to close. A verifier or `import-check` written before this
extension verifies an extended package and reports `compatible` without mentioning the authored
state, because it cannot know the directory exists. That is the price of not breaking it. A loader
that must never drop authored state silently needs a verifier that knows the `extensions/`
convention; every verifier from this version on names each extension it finds, known or not.

### Compatibility evidence

`tests/fixtures/wmp-1.0-before-authored-world` is a package the unmodified projector wrote at
90edb49, beside what that commit's verifier said about it. `tests/test_world_package_extension.py`
verifies it unchanged, rebuilds it byte for byte from its own components and key (Ed25519 signing is
deterministic), and shows the extension changes only `ro-crate-metadata.json` among the 1.0 files.
`tests/test_world_package_extension_postgres.py` round-trips one alternate version holding one object
from live PostgreSQL through a signed package and reads it back with a loader that lacks the
extension and one that has it, and shows a version whose source was deleted is withheld.
`tests/test_world_package_motion_postgres.py` round-trips a world with motion under 1.1 (the
object's stored behaviour, every behaviour edit in the chain, a branch that took the motion
away, an environment version with motion under environment-instances 1.1), answers three loader
declarations, and shows a verifier that knows only 1.0 naming 1.1 as not checked.
`tests/test_world_package_behaviour_extension.py` refuses the same chain under 1.0 and holds the
1.1 `withheld` rules.

The developer-proof record (`2026-09-11-developer-proof`), a local-only evaluation record a clone
does not contain, retains the same proof on the reference copy: a package projected from the
version the second client edited, verified by this code and by the verifier at 90edb49, checked
against four loader declarations, and the same snapshot projected without the extension by this
code and by the 90edb49 projector, byte-identical in every file including the signature.

## Environment-instances extension 1.0

Status: **OPT-IN EXTENSION `exulanica-wmp-ext-environment-instances` 1.0 AND 1.1**.
Implementation: `exulanica/world_package/environments.py` (sections, verifier rules and loader
report for both versions), `export_partition.py` (the lineage partition),
`extension_projection.py` (the projection), `package.py` (extension discovery and
`import-check`). Version 1.1 differs from 1.0 as
[Which versions an extension carries](#which-versions-an-extension-carries) states, and its
declaration names authored-world 1.1 where 1.0's names authored-world 1.0. It carries the
environment-inclusive authored state [world-objects-contract.md](world-objects-contract.md)
section 11 defines: alternate versions
whose current delta includes `environment_instances`, or whose edit chain names an environment
edit, together with the objects and overrides those versions still hold, the schema-v1
ancestors those parent pointers require, and schema-v1 descendants that cannot live in
authored-world 1.0 because an ancestor is environment-bearing.

### Why a second extension

Authored-world 1.0 required paths, schema version 1, and edit kinds are a closed contract. Live
state that includes environment instances selects schema version 2 and appends
`add_environment`, `move_environment` and `remove_environment` edits. Emitting that document
under `extensions/authored-world-1.0` would make a verifier that knows authored-world 1.0
refuse a sound package, or would teach that verifier a schema the 1.0 name never admitted.
An optional directory under `extensions/` does neither. The profile version in the manifest
and the signature stays `exulanica-wmp-1.0`. A verifier that predates this extension still
verifies a 1.0 package, including one that also carries authored-world 1.0.

### Layout

Exactly four canonical JSON files under `extensions/environment-instances-1.0/`; any other file
there is refused.

| File | Holds |
| --- | --- |
| `extension.json` | Name `exulanica-wmp-ext-environment-instances`, version `1.0`, base profile `exulanica-wmp-1.0`, section paths, counts, `required_loader_capabilities`, and the fixed statements that asset bytes, environment source bytes and runtime code are not embedded, that source-use rights are not granted, that availability is not in `state_sha256`, and that a receiver without this capability must omit these versions rather than infer objects from authored-world 1.0 |
| `versions.json` | Every exported environment-bearing version, plus the schema-v1 ancestors those parent pointers require and the schema-v1 descendants that cannot live in authored-world 1.0: the authored-world 1.0 envelope fields, the honest `delta` (environment-inclusive when instances remain), `environment_availability` beside that delta, and the edit chain, where environment kinds add `environment_instance_id`; plus `source_snapshots` and a `withheld` count |
| `assets.json` | The reviewed object assets those versions name, in the same digest-only form as authored-world 1.0 |
| `behaviours.json` | The reviewed behaviours those objects name |

`delta` is the document `exulanica.world.authored_delta.canonical_delta_document` builds when
environment instances are supplied. Schema version 2 and `environment_instances` appear only
when at least one instance remains after omitting undone additions. Schema version 1 is the
current state of a version whose environment additions were all undone; its edit chain still
names those edits, which is why the version sits here and not under authored-world 1.0.
`state_sha256` is the SHA-256 of that document under the canonical JSON rule, the same token
`GET /world/versions` returns. Availability is a parallel array of `instance_id` and one of
`available`, `unavailable_bytes`, `withdrawn`, `binding_drift`, or `unknown`. It is not hashed.

Source identifiers inside the canonical instance (`admission_id`, `place_id`, render
`asset_id`, publication id) remain the live UUID strings, because they participate in
`state_sha256`. Envelope ids (`version_id`, `edit_id`, `source_snapshot_id`) stay
`urn:exulanica:wmp:<kind>:<sha256>`.

The extension is added only when `project` is given `--extension environment-instances-1.0`.
With it, the eighteen 1.0 payloads are unchanged except `ro-crate-metadata.json`, which gains
the four files in `hasPart`, one `Profile` node for the extension, and a `conformsTo` on
`extension.json`. The crate root still conforms to the 1.0 profile alone.

### What is exported and omitted

| Exported | Omitted |
| --- | --- |
| Environment-bearing versions, their environment-inclusive delta, and their edit chain | Versions whose live state, edit chain, and ancestor chain are schema version 1 only; those stay in authored-world 1.0 when that extension is requested |
| Schema-v1 ancestors a parent pointer in this directory needs, with their honest schema-v1 delta | A rewrite of those ancestors as schema version 2 |
| Schema-v1 descendants whose parent is environment-bearing | Those descendants under authored-world 1.0, where the parent cannot be written |
| Current environment instances after `addition_undone` is applied | Undone environment additions, as authored-world 1.0 omits an undone object |
| Honest availability for each exported instance | A fabricated `available` when bytes were not inspected (`unknown`) or when the pinned source is withdrawn, missing, or drifted |
| Reviewed object asset and behaviour descriptors those versions name | Asset bytes, environment source, render and index bytes, runtime code |
| A withheld count for invalidated sources | Versions whose source snapshot carries a `world_structure_invalidation` row; they are counted and not named |
| | Actors, `created_by`, and each edit's `actor` |
| | Source-use rights, a compose grant, or a claim that the receiver may reuse the pinned geography |
| | Deterministic society state and events |

Projecting `--extension authored-world-1.0` alone refuses when a kept version belongs in this
extension. It does not write schema version 2 under the 1.0 name, and it does not export a 1.0
directory that looks complete while dropping those versions. Dual export writes this directory
as a lineage-closed set: a `parent_version_id` resolves here, either because the parent is
environment-bearing or because a schema-v1 ancestor was copied in. Authored-world 1.0 still
holds that ancestor when the ancestor's own chain is schema version 1, so the 1.0 subset stays
complete. Dual export omits the authored-world directory when every kept version belongs here
and nothing honest remains to declare there; an empty 1.0 directory would look like a complete
world with no alternate versions.

### Verifier rules

A verifier that knows the extension refuses the package, even though its signature is sound,
when: the directory does not hold exactly the four files; a section has an unknown profile, a
missing or extra field, or items out of sorted order; `state_sha256` does not re-derive from
the environment-inclusive delta; schema version 2 has an empty `environment_instances` array,
or schema version 1 carries that field; an instance or object names a region its source
snapshot lacks, a non-authored origin, or a transform outside the fixed-point contract; an
instance source binding is malformed; `environment_availability` does not name exactly the
exported instances in the same order, or uses a state outside the five honest values; an
object names an asset or behaviour the sections do not list; an override names an element its
source lacks; a parent is missing, on another source, or cyclic; the edit chain is not
contiguous, an environment edit lacks `environment_instance_id`, a 1.0 edit kind carries that
field, or the chain does not end at the exported state; the source snapshot marked `current`
disagrees with `world/structure.json` or `world/topology.json`; the sections list assets,
behaviours or snapshots nothing references; or `extension.json` does not match what the
sections require. The digest is re-derived with the canonical JSON rule alone.

A verifier that does not know this extension still verifies the 1.0 profile and any
authored-world 1.0 directory it does know. This directory is then named as not checked.

### Loader capabilities and `import-check`

| Capability | Required when |
| --- | --- |
| `wmp-extension:exulanica-wmp-ext-environment-instances@1.0` or `@1.1` | that version of the extension is present |
| `environment-source:sha256-content-address` | any environment instance that is not removed exists |
| `asset-resolution:sha256-content-address` | any object that is not removed exists |
| `asset-media:model/gltf-binary` | such an object's asset has that media type |
| `behaviour:motion.bounded-path@1` | such an object carries that behaviour |

A removed instance or object requires nothing. Availability is not a capability: a withdrawn
or unavailable instance stays named. A loader without this extension capability gets
`load: "not loaded"` and a warning that names how many versions and present environment
instances it leaves behind, and that it must not infer objects from authored-world 1.0 as the
whole authored state. `import-check` runs no loader and does not write a live world.

### Compatibility evidence

`tests/test_world_package_extension.py` still verifies
`tests/fixtures/wmp-1.0-before-authored-world` unchanged and still rebuilds that package byte
for byte. `tests/test_world_package_environment.py` checks that schema version 2 is refused
under authored-world 1.0, that this extension re-derives an environment-inclusive digest
without the product domain types, that a schema-v1 ancestor and environment-bearing child
verify together, that a schema-v1 grandparent and parent of an environment-bearing child stay
in the authored-world set and are copied into the environment set, that a child whose parent
is absent from this directory is refused, and that
a loader without the capability is told to omit rather than infer.
`tests/test_world_package_environment_postgres.py` round-trips a live environment instance,
omits an undone addition, states withdrawn and unavailable honestly, refuses an
authored-world-1.0-only export of a version that has environments, verifies a parent in
authored-world 1.0 whose child later gained an environment, includes that parent in an
environment-only cut, closes that two-ancestor chain in a dual export, tells a loader without
the environment capability to omit the parent/child dual rather than treat the authored-world
subset as the whole authored state, verifies a schema-v1 child whose parent stayed
environment-bearing after undo, and omits an empty authored-world directory when every kept
version belongs here.

## Explicit training dataset profile

`exulanica-wmp-training-1.1` is an independently selected dataset profile. The ordinary `project`
command still writes `exulanica-wmp-1.0`, whose eighteen required paths and signed profile identity
are unchanged. The `exulanica-wmp-training-1.1` profile has its own required documents: RO-Crate metadata, profile,
materials, training consent, and export provenance. It shares the inventory, Merkle construction
and Ed25519 verifier with the memory profile. It does not imply that a memory export is licensed
for training, nor does importing a dataset create an interactive world.

Default off has three executable boundaries. `training-export` requires `--opt-in` before opening
the database; `export_training_dataset` independently defaults `owner_opt_in` to false; and the
offline verifier requires an immutable `package-owner` grant for the exact package, licensee,
model classes, contract digest and dates. Per-person grants do not substitute for that grant.
Training decisions use the separate plane described in `person-presentation-consent.md`; they
never change presence, naming, likeness, temporary hiding, or the five presentation states.

### Inventory, withdrawal and trust

Every admitted capture carries its exact source image or a verified masked derivative, source
digest, camera/calibration state, frozen train/held-out assignment, rung and provenance. A scene
export binds the current reconstruction job, every contributing capture, its exact pose receipt,
the sparse observations, and any included trained SOG with its exact publication receipt. The
camera and calibration declarations must match that pose receipt; unavailable measurements are
stated as unavailable. Geometry cannot survive removal of one of its contributors. A denied
member removes its entire scene from a successor export, and the successor names the removed
material IDs and predecessor root. A first export with an unconsented, unmasked person refuses
instead of silently delivering a partial dataset.

Mask declarations are checked against current person regions, both presentation resolvers, the
exact masked-source key and the retained mask manifest. A presentation mask cannot establish
that a person whose likeness was permitted is hidden for training. That case refuses until an
appropriate derivative exists. Original pixels cannot accompany a masked-only admission. The
retained real-photo masking chain has not been established by the synthetic acceptance test.

Source screening must be a current eligible durable receipt for the exact bytes. Unknown or
omitted person regions, tombstoned sources, stale jobs and unbound geometry are refused. Only
decoded metadata-free JPEG/PNG, restricted PLY, recognized pose/publication JSON and self-contained
validated SOG payloads are accepted. The scanner preserves the credential, conversation,
biometric, executable and model-internal exclusions of the memory profile. Image metadata or
trailing payloads cause refusal; an export never silently edits an original to make it pass.
Binary format validation is not a semantic prohibited-content classifier. That decision still
requires the retained screening and trust in its issuer.

The manifest states `recorded captures; no simulation or adaptation claim`. Synthetic acceptance
materials additionally identify their scripted provenance. Offline verification establishes the
signed bytes, inventory, declarations and consent state at export time. It cannot establish the
identity or authority of a signer, discover a later withdrawal, or independently inspect whether
a human screening was truthful. Licensees need the issuer's trusted key fingerprint and current
ledger. Account-holder attestations are identified as such; this CLI does not authenticate a
photographed subject or claim that a subject signed the receipt.

The append-only `world_package_export` ledger stores licensee, exact terms, attribution, payment,
roots, material identities and capture splits. `training-ledger` joins later training withdrawals
back to past exports without rewriting their signed records. A withdrawal dominates subsequent
grants for that subject/package/licensee relationship. A revocation applies to its exact terms.
Held-out assignments remain frozen across the package's export history, including different
licensees and material renaming. Revocation prevents future issuance; it cannot remove bytes a
licensee already downloaded or reverse training they already performed.

Migration 0039 adds one workspace-isolated receipt table. Exports take an exclusive workspace
source lock through validation and publication; source mutations take its shared counterpart, so
ordinary ingest and withdrawal writers race as the deletion protocol requires. A package lock
serializes training decisions with exports. This closes the withdrawal/publication race while permitting other workspaces to
continue. The tradeoff is that source mutations and other exports in the exporting workspace wait
during signing and publication. The authoring API also holds selected asset bytes in memory; it is
a sample-export path, not a claim of streaming multi-terabyte delivery.

### Training commands

```text
exulanica-wmp training-consent --workspace UUID --actor UUID --terms TERMS.json --subject package-owner --decision granted
exulanica-wmp training-consent --workspace UUID --actor UUID --terms TERMS.json --subject PERSON_UUID --decision granted
exulanica-wmp training-export --workspace UUID --actor UUID --request REQUEST.json --private-key KEY --output DIRECTORY --opt-in
exulanica-wmp training-ledger --workspace UUID
exulanica-wmp verify DIRECTORY
```

`TERMS.json` contains `package_id`, `licensee`, sorted unique `model_classes`, offset-aware
`valid_from` and `valid_until`, and `terms_sha256` binding the licensing agreement. `REQUEST.json`
contains `terms`, `materials`, `attribution` and `payment`. Each material declares `material_id`,
`capture_id`, `assets`, `people`, `screening`, `camera`, `calibration`, `metadata`, `split`, `rung`
and `provenance`. Asset paths resolve under `assets/` beside the request, and each asset declares
its role and SHA-256. Scene assets additionally name their retained artifact IDs; provenance
names the scene, job and pose receipt path. The database validator checks those declarations.
The acceptance fixtures in `tests/test_training_inputs.py` show complete image and scene forms.

The acceptance tests (`tests/test_training_export_postgres.py`,
`tests/test_world_package_dataset.py`) produce a synthetic sample with exact source photos,
scripted recovered cameras and calibration, sparse observations, a structurally valid scripted
trained SOG, frozen split and provenance. No real COLMAP, CUDA training or vision-model execution is
claimed, and whether anyone would license such a dataset is not established.

## Editable repository checkpoints

The separate `exulanica.world-project/v1` profile carries a reviewed selection of authored
things and model bindings in `world-project.json`. Decision evidence lives beside it in session
files of the sibling profile `exulanica.world-project-evidence/v1`. Neither changes any WMP
profile or signature guarantee. `uv run python -m exulanica.world_package.projects schema` and
`... evidence-schema` print the closed JSON schemas. The adapter keeps project data; it does not
install a runnable world. The connected learning journey remains a requirement in
[product direction](product-direction.md#repository-backed-learning-and-development).

### Selection and provenance

`select_checkpoint` in `exulanica/world_package/projects/projection.py` accepts an already-authorized
`AlternateVersion`, explicit thing IDs and explicitly supplied dependencies, model bindings and
selected evidence. It verifies the native state's digest, refuses an invalidated source and
omits unselected things, actor records, edit history and other runtime data. Its caller must use
the world's existing authorized read boundary and establish rights to export the selection.
The pure adapter grants no permission and has no database or world API route.

A checkpoint names its source world, version, source snapshot ID, source state digest and source
snapshot digest. Its selected things retain native IDs, kind references, region-local fixed-point
poses, origins and removal state, validated through the existing placed-thing contract. Shipped
kinds must match the installed catalog. Workspace kinds retain a digest reference. Support-bound
placements, authored mesh objects, environment instances, point maps, complete world definitions
and simulation state are unsupported; unknown fields are refused rather than silently dropped.
A selection's source state digest covers the native source version, not just its selected things.
The checkpoint has a separate content digest.

Dependencies declare a content digest, source identifier, licence identifier and one of four
kinds: source snapshot, thing kind, decision contract or model identity manifest. No dependency
bytes or fetch credentials enter the checkpoint. `inspect` accepts local files named by digest,
checks their bytes and JSON object shape, and resolves shipped kinds from the installed catalog.
It checks supplied kind documents, declared model deciders, registered decision contracts and
model identity manifests. A manifest contains only `provider`, `model_id` and `revision`; its
presence does not prove provider availability, immutable hosted weights, an open-source licence
or model-role eligibility. Those remain checks for the execution authority. Source snapshot
semantics, transitive rendering dependencies and source-use authorization are not validated here.
`dependencies_ready` describes the declared dependencies only; `runtime_loadable`,
`source_binding_verified` and `model_availability_verified` remain false.

Every string in a checkpoint or evidence file is also scanned by value. A value shaped like a
local filesystem path or a credential (token prefixes, bearer values, private key headers) is
refused, naming the field and never echoing the value. The scan reduces accidental inclusion; it
cannot recognize every private identifier placed in an otherwise valid field.

### Decision evidence

A decision record binds to a model assignment by the digest of that binding and to its source
record by digest. It carries an observation digest, offered action/target identifiers, the chosen
option, the recorded applied/refused/not-applied outcome, reason code, elapsed time and token
counts when supplied. An optional `readable` addition carries what the source record itself
stores, made readable: the situation text rebuilt from the record's own context, the offered
labels, the choice and spoken line, receipt status and reason, the minute the society consumed it
and its disposition, the served model and recorded cost with `cost_known`. Leaving `readable` out
keeps a record's digest unchanged. No record carries system instructions, raw provider bodies,
hidden model reasoning, private conversations, raw logs or model weights.

The evidence file format is specified field by field in the
[world project evidence format](world-project-evidence-format.md). An evidence file holds one session's records with the model assignments they were made under, so
a record stays bound after the checkpoint's assignment changes. Each file has its own digest,
separate from the checkpoint's; evidence is what happened, never part of the world definition. A
file holds at most 1024 records; `watch` continues a longer session in numbered files.
`playback` orders the checkpoint's and the session files' records without provider calls. It
reports `source_records_verified: false` and `engine_replay_verified: false`: this is evidence
playback, not the native engine's verified deterministic replay. An editable record cannot prove
the source record was authentic. Inference reruns are not implemented by this adapter.

### Project folders

A project is a plain local git repository: `world-project.json`, `evidence/<session>.json`, an
optional `project-link.json` and optional `dependencies/<sha256>` files. No account, remote or hook is involved. Every git call
names the folder's own `.git` directory with environment overrides removed, so it cannot reach an
enclosing checkout; a folder with a remote is refused.

```sh
uv run python -m exulanica.world_package.projects create ./my-project --from selected.json
uv run python -m exulanica.world_package.projects record ./my-project --from edited.json --evidence session.json
uv run python -m exulanica.world_package.projects changes ./my-project --from HEAD~1
uv run python -m exulanica.world_package.projects history ./my-project
uv run python -m exulanica.world_package.projects reopen ./my-project
uv run python -m exulanica.world_package.projects fork-project ./my-project --to ./my-fork --project-id project:my-fork
```

`record` commits only when the selected world or its evidence differs from the last commit; an
unchanged selection makes no commit, however long the world ran. Without `--from` it records the
folder's edited files. Commits are by `Exulanica project <project@exulanica.invalid>` unless `--author-name` and
`--author-email` state another author; git runs without the system's or the person's own git
configuration, so a project commits the same on every machine and no personal email enters its
history unless stated. Commit messages are one line without an em dash or attribution trailer;
when none is given, the message is drawn from the plain-word summary. Evidence files are
append-only: a saved record cannot be changed or removed.

Every comparison reports world changes and evidence apart, in plain words, with the raw field
diff underneath: "moved the knight 2 m east", "assigned a model to the knight", "recorded 3 more
decision records from session S". `history` returns the read a history panel uses, described
below. `reopen` validates the last commit offline,
reports missing, corrupt and unsupported dependencies, uncommitted edits, and a labelled warning
for a session file of another project or one made under assignments no longer current. It
installs nothing and reports `installed: false`. A fork is a new folder and project identity
whose checkpoint records its parent project and checkpoint digest; the parent's evidence stays
with the parent.

The file-level commands from the first version remain: `save` writes a new private checkpoint
file and refuses an existing destination, `diff` compares two files, `inspect` checks
dependencies against `--dependencies` and `--expected-source`, `fork` writes a forked file and
`playback` lists records. Reopening refuses duplicate JSON keys, floats, unknown fields, symlinks
and documents over 2 MiB. No command applies checkpoint edits to live state. A future live
importer must repeat authorization, source validity, identity mapping, dependency and
optimistic-concurrency checks through existing world writers.

### History read

`history FOLDER [--limit N] [--publication]` returns one document of profile
`exulanica.world-project-history/v1`. From the folder's git history, exactly: the project and
its fork lineage, the link, the head, pending world changes and pending evidence, and the
checkpoints newest first. Each checkpoint has its commit, time and message; its kind (`checkpoint`
for world, evidence or dependency files, `link`, or `application`); its world changes and evidence
changes in the summaries' words against the commit before; the session files it holds with record
counts, records added, digests and warnings; and `applied_as`, the world versions it became.
`more` is true when `--limit` left older checkpoints out.

Which merge became which version comes from records the folder commits itself: after `apply`
succeeds, or finds the merge already applied, it commits `applications/<merge commit>.json`
(profile `exulanica.world-project-application/v1`: repository, pull request, merge commit, the
applied checkpoint and evidence digests, version identity and title). A record is shown on the
newest content checkpoint holding exactly that content; records not matched to a listed
checkpoint are named. Merges applied from another folder are not known here, and the read says
its source is this folder's records; no world credentials are read. Records are never published.

Publication is `not read` unless `--publication` is given. Then one GitHub read (the linked
branch's files and its newest pull request into the base) either succeeds whole or the command
fails; the read reports the branch head, the newest local checkpoint whose world and evidence
files equal the branch's (the same match the publisher uses), whether the branch matches local
history at all, and the pull request's number, link, state and merge commit. Each checkpoint is
then marked published or not; without the read, `published` is null.

### Capture and automatic tracking

`capture` reads one version of a running world through the World API with GET requests only and
builds the selection: the named placed things, each one's current model assignment, and the model
decisions the society consumed for them, mapped back to placed things through the society's
subject identity, at most the latest 256 consumed records per capture. `--session` puts the
decisions in an evidence file; `--readable` adds the readable records. The bearer is read from a file into memory and sent only in the request header.
Every request passes through the egress check held to the one origin the caller names
([security floor](security-floor.md)); plain http is accepted only for `localhost`, and redirects
are not followed. Errors name the route and status, never a value. Capture writes nothing to the
world, reports `state_digest_verified: false` because the version view cannot recompute the
native digest, and leaves source snapshot bytes as a missing dependency.

```sh
uv run python -m exulanica.world_package.projects capture --api http://localhost:PORT --token-file TOKEN --world WORLD --version VERSION --thing THING --project-id project:mine --session session:one --readable --output checkpoint.json --evidence-output session.json
uv run python -m exulanica.world_package.projects watch ./my-project --api http://localhost:PORT --token-file TOKEN --world WORLD --version VERSION --thing THING
```

`--living-session ID` (or `latest`) on `capture`, `record-world` and `watch` captures one living
session as its own evidence file: the decisions asked in its minutes, every request with its
receipt when the session read lists them all (its counted decisions equal its total;
`coverage: all`, so unanswered and timed-out requests appear), and the session's receipts and spending as the spending authority reads them; the watcher
records a checkpoint as soon as the session closes. The fields are in the
[evidence format](world-project-evidence-format.md#living_session).

`record-world` captures straight into a project folder as one checkpoint and one session's
evidence, creating the folder when `--project-id` is given. A later run's world may still hold an
earlier run's records; a record already kept in another session, recognized by its source record
digest, is not repeated. Request identities derive from the being and the minute, so two runs from
one starting state reuse identities for different decisions; the digest keeps both.

```sh
uv run python -m exulanica.world_package.projects record-world ./my-project --api http://localhost:PORT --token-file TOKEN --world WORLD --version VERSION --thing THING --session session:run-1 --readable --project-id project:mine
```

`watch` keeps a project's history without a save button. It captures at a bounded interval
(5 to 300 seconds, default 15) into one evidence session per run and writes pending changes to
the folder so they are visible before they are recorded. It records a checkpoint once the
selection has stayed the same for a settle period (default 120 seconds), after a change has been
pending for a maximum time (default 30 minutes, since evidence grows while models play), and
once when stopped. Edits that cancel out before then record nothing. Each capture is merged into
the session's saved and pending records, so a record the capture window no longer returns is kept,
and a session past 1024 records continues as `session:S:2`, `session:S:3` and so on. A daily cap (default 48)
holds further changes pending; a checkpoint is committed at the watcher's own time and the cap
counts the day's checkpoints in the project's history, so a watcher started again the same day
holds it. A record takes every pending session file, including one the cap held back. An
unreachable world is reported and retried. The watcher writes only the local project folder,
never the world and never a remote.

### Following a world

`follow FOLDER` makes a project folder follow its world with nobody running a command afterwards.
For a new folder it reads the world once by GET and starts the project from every placed thing a
checkpoint can hold (or the `--thing` list), then writes `project-follow.json` (profile
`exulanica.world-project-follow/v1`) as one local commit: the world and version; the things,
`every` or a list; whether readable text is kept (`--readable`); `sessions.since`, the instant from
which living sessions are recorded, the command's own time unless `--sessions-since` names another,
or null with `--no-sessions`; and optional `limits` in whole numbers (`--poll-seconds`,
`--settle-seconds`, `--max-pending-seconds`, `--daily-cap`), each absent one at the watcher's
default. Running it again on a followed folder changes only what its flags name. The file holds no
origin, credential or path, is scanned like a checkpoint and is never published. `unfollow FOLDER`
removes it as one commit and leaves the project as it is, pending changes included. `history`
names these commits `follow` and returns the folder's settings as `follow`.

```sh
uv run python -m exulanica.world_package.projects follow ./projects/my-world --api http://localhost:PORT --token-file TOKEN --world WORLD --version VERSION --project-id project:mine
uv run python -m exulanica.orchestration.project_worker --projects ./projects --api http://localhost:PORT --token-file TOKEN
```

The project worker keeps every followed folder of one projects directory current, in a process of
its own beside the API. The HTTP surface may not import this package, and a follower is a client
of the World API rather than of its database: it needs the API's origin, plain http only for
`localhost`, and a bearer with `world.read`, and no database, store or model key. A folder that
gains, changes or loses its follow file is followed, followed anew or left within a few seconds.
Each poll reads the world's living sessions, then captures the world through the watcher above
with at most one living session as its own evidence file: one the project holds as open until it
is held closed, else the oldest one opened since `sessions.since` that the project does not hold,
so a session that opened and closed between two polls, or while no worker ran, is still recorded.
A closed session that leaves no evidence of a followed thing is passed over. A version with no
society is followed for its edits alone, and one with nothing placed waits. A capture that reads
no decision record for a model keeps the revision the project holds for it, so a binding does not
change between sessions. One project's fault never stops another, one worker holds a projects
directory at a time, and it follows at most 64 folders unless `EXULANICA_PROJECTS_MAXIMUM` states
another number. The three settings may also be given as `EXULANICA_PROJECTS_DIRECTORY`,
`EXULANICA_PROJECT_API_URL` and `EXULANICA_PROJECT_TOKEN_FILE`. SIGTERM or SIGINT stops it: the
round in hand finishes, each project with pending changes records them once within 60 seconds
(`EXULANICA_PROJECT_FINISH_SECONDS`), and it exits 0. Each event is one line of JSON naming a
folder by its name, never its path, and never carrying the bearer. It writes only the project
folders, never the world and never a remote.

### GitHub transport

Both GitHub paths use the user's authenticated GitHub CLI and an explicitly supplied repository;
neither scans a working directory, stages files, executes repository code or infers a destination
from the source checkout. Publication supports repositories personally owned by the authenticated
CLI user with write permission. Organization ownership, repository creation and whole-repository
forking are outside both. Dependency bytes are never published. Fetch may read an accessible
repository without write permission.

**Repository and link.** `review-repository NAME` reads the signed-in GitHub login and whether
the name is free, and returns a digest over the owner, name, private visibility, README first
commit and description. `create-repository NAME --review-sha256 DIGEST --allow-publication`
recomputes it, creates the private repository with a README so its default branch has a commit,
and confirms GitHub's reply names a private repository. An existing name is refused; `link`
records an existing repository instead. No account or repository name is built in: the owner is
the CLI's login and the name is the argument.

`link FOLDER --repository OWNER/NAME --base BRANCH --branch BRANCH` writes `project-link.json`
(profile `exulanica.world-project-link/v1`: repository, base branch and project branch; no
credential, token or URL) and records it as one checkpoint. Nothing is contacted. Branch commands
read the link when their flags are omitted and refuse a flag that disagrees with it; the link is
not published. The link lives in the folder rather than in the workspace database because a
project must work with no account or server, and GitHub authentication stays in the GitHub CLI.

```sh
uv run python -m exulanica.world_package.projects review-repository my-world
uv run python -m exulanica.world_package.projects create-repository my-world --review-sha256 REVIEW_DIGEST --allow-publication
uv run python -m exulanica.world_package.projects link ./my-project --repository OWNER/my-world --base main --branch exulanica/my-project
```

**Rolling pull request.** A project folder publishes its last saved commit, never pending edits,
to one project branch with one open pull request against a base branch, the way dependency bots
group updates:

```sh
uv run python -m exulanica.world_package.projects review-branch ./my-project
uv run python -m exulanica.world_package.projects publish-branch ./my-project --review-sha256 REVIEW_DIGEST --allow-publication
```

`review-branch` writes nothing. It reads the base branch, the project branch and its open pull
request, refuses a branch holding another project or evidence the folder does not hold, and lists
the actions publication would take: create the branch from the base head, commit, then open the
pull request or update its text. Each saved checkpoint not yet on the branch becomes its own commit
with its own plain-word message and only the `world-project.json` and `evidence/` files it
changed, each chained by `expectedHeadOid`. The branch is matched to the newest saved checkpoint
whose files it holds; a branch matching none, or more than 50 unpublished checkpoints, is
published as one commit of the last saved state, using `--message` when given. The pull request text describes, against the base branch, the changes to the
world and, separately, the decision evidence, which is never called part of the world. It then
tells what the beings did in each session (each decision's offered option count, its answer and
its verdict in the browser's choice account words, `assets/catalogs/roles/choice-account-words.v1.json`)
and how each model did (the served measures of `exulanica/world/decision_measures.py`: counts out
of totals, "not enough data yet" below a measure's minimum sample, latency, and cost as computed
or bounded, never a bill). A living session's evidence is headed by its minutes, why it stopped
in the society's own words (`SESSION_CLOSED_WORDS`, `exulanica/world/society_sessions.py`, the
table the page reads), its limits and its spending as the spending authority read it, including
the most that calls of unknown cost can have cost; a table by living session sets each session's
models side by side, with timeouts only where every request of the session was read. It is
regenerated from the committed files on every review and ends
with their digests. What the files cannot support (requests no minute took up, receipts older
files lack) is named as unavailable, never shown as zero. Labels, spoken lines and situations
appear only when the repository's visibility reads `PRIVATE`; a public or internal repository gets
option numbers and codes only, and the review digest binds which. The generated text passes the
value scan and stays within 60,000 characters, below the 65,536 GitHub is reported to accept
(its pull request API page states no limit); it leaves out decision lines first, then older
sessions' detail, and says so, never the counts or the model table. When the
saved project again equals the base branch, the open pull request is closed instead. Unchanged
files make no commit and unchanged text is not rewritten. The review digest binds the target,
both branch heads, the pull request, each commit's message and file digests, and the text; `publish-branch` recomputes
it and refuses any difference. A failed step stops publication, names the steps already done and
is not retried.

**Applying a merged pull request.** A merged pull request becomes a new alternate version of the
running world through the World API's own routes; the version the project was captured from is
never edited.

```sh
uv run python -m exulanica.world_package.projects review-apply ./my-project --pull-request 1 --api http://localhost:PORT --token-file TOKEN
uv run python -m exulanica.world_package.projects apply ./my-project --pull-request 1 --api http://localhost:PORT --token-file TOKEN --review-sha256 REVIEW_DIGEST --allow-world-write
```

`review-apply` reads the pull request through the project's link (GitHub reads only): it must be
merged into the link's base branch, and the merge commit's `world-project.json` and evidence files
must pass their closed schemas and the value scan. The review compares the project's selected
things with the source version and lists the edits that would make a new version hold them:
additions, moves and turns within a region, and removals, worded like the summaries. Things the
project never selected are left as they are. It refuses, writing nothing, when the source version
is invalidated or its state digest differs from the checkpoint's (the world changed since capture;
the project carries no per-thing base values, so there is no three-way merge), and when a thing
would change region, kind or origin, be restored after removal, or use a workspace kind the
workspace does not hold, since no route does those. A merge that changes only evidence applies
nothing. Model assignments are listed as to assign after the world is started: a new version has
no society until it is started, and recording an assignment authorizes later model spending.
Evidence, the link and dependency files are never applied.

`apply` needs `--allow-world-write` and the review digest, which binds the merge commit, the edits,
the refusals and the version state; it recomputes the review and refuses any difference. It
branches one version from the source version, titled `From OWNER/REPO commit SHA (pull request
#N)`, checks that the branch inherited what the review saw, then sends each edit with the state
token of the one before. Creating a version is not idempotent, so a write is never retried: a
later review finds the version by its title and resumes with the remaining edits, and a finished
merge reviews as already applied. Writes need `world.write`; this applies to an isolated copy or a
workspace the caller is authorized to change, never by editing a running version in place.

**Single file.** The first transport writes only the root `world-project.json` to an existing
branch:

```sh
uv run python -m exulanica.world_package.projects fetch --repository OWNER/REPOSITORY --branch BRANCH --output reopened.json
uv run python -m exulanica.world_package.projects review edited.json --repository OWNER/REPOSITORY --branch BRANCH --message 'Move the knight'
uv run python -m exulanica.world_package.projects publish edited.json --repository OWNER/REPOSITORY --branch BRANCH --message 'Move the knight' --review-sha256 REVIEW_DIGEST --allow-publication
```

Review returns a field diff and a digest binding the selected content, destination, exact branch
head and one-line commit subject. Publication is a separate explicit action: it rereads the head,
recomputes the review and refuses any change. GitHub's
[`createCommitOnBranch`](https://docs.github.com/en/graphql/reference/commits#createcommitonbranch)
mutation uses `expectedHeadOid` to refuse a concurrent branch move atomically. An unchanged
selection creates no commit. A successful response supplies the commit and GitHub compare links.
A failed or timed-out request is not automatically retried because its outcome may be unknown;
read the branch again before preparing a new review. The transport uses
[`gh api` structured input](https://cli.github.com/manual/gh_api), never shell interpolation.

Review every selected value and its publication rights before publishing. Selected identifiers
and evidence digests can still be private. Local saves, GitHub access and native world
permissions are separate. Publication cannot recall copies already fetched by others.

Synthetic tests cover native selection, project folders, append-only evidence, plain-word
summaries, capture against a fake World API, automatic tracking and following with a fake clock,
a project worker process stopped by SIGTERM, dependency failures, base conflicts, evidence
playback, review binding and concurrent publication refusal through a fake GitHub server. They do
not establish hosted publication, a worker following a running world for days, live-world
restoration, real model behavior, verified engine replay, or educational/portfolio value. The latter requires
a learner completing the connected task and explaining a behavior change from authentic
execution evidence.
