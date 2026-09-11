# World Memory Package v1

Status: **BUILT AND EXIT-GATED**. The implementation profile is `exulanica-wmp-1.0`.

**Creative-world state:** [product-direction.md](product-direction.md#package-and-api-boundaries)
asks for authored state and behaviour references without changing the 1.0 profile. They are
carried by an optional, separately versioned extension, `exulanica-wmp-ext-authored-world` 1.0,
specified in [its own section below](#authored-world-extension-10). The 1.0 profile, its eighteen
required paths and its signature payload are unchanged, and a package written without the
extension is byte for byte what the projector wrote before the extension existed.

The World Memory Package (WMP) is a signed projection of one PostgreSQL snapshot. It is not the
live store, a backup, a consent grant, or an executable world. An exported copy cannot be recalled.
After a deletion, a new export has a new root and the semantic diff is the durable account of what
was removed or recomputed.

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
same database snapshot. The projector writes a sibling staging directory, scans every JSON payload,
builds and signs the manifest, inserts the append-only `world_package_export` receipt, and renames
the staging directory into place before commit. A failed transaction removes the newly published
directory.

The receipt records the protected current-version IDs, profile version, Merkle root, manifest
digest, optional parent root, Ed25519 public-key fingerprint, actor, export policy, and database
time. None of those audit rows feed the package root, so exporting unchanged state with the same
lineage produces the same root. The receipt is a workspace-keyed FORCE RLS table and rejects
update and delete. It was described here as "the forty-eighth", which stopped being true at the
next migration that added one: the count is measured by
`test_the_prose_count_of_workspace_isolated_tables_matches_the_schema` and an ordinal in prose is
not.

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

The default scanner rejects raw media, credentials, biometric templates, embeddings, private
conversation fields, model caches/internals, training intermediates, executable UI assets, shaders,
and remote executable bindings. Media references contain a digest, size, type, RFC 6920 `ni` URI,
and the explicit statement that an authorized content-addressed resolver is required. An `ni` URI
is not presented as a public download URL.

## Integrity format

`wmp/manifest.json` lists every payload path, byte length, and SHA-256 digest in sorted path order.
Leaves bind the domain separator `exulanica-wmp-leaf-v1`, the UTF-8 path, and the file digest.
Internal nodes bind `exulanica-wmp-node-v1` and the two child hashes; an odd final child is
duplicated. Those separators are the current v1 domain-separation strings. `wmp/signature.json`
contains the Ed25519 public key and a signature over the canonical profile version, manifest digest,
and Merkle root. The manifest and signature do not include themselves in the Merkle inventory.

The offline verifier rejects non-canonical JSON, symbolic links, inventory additions/removals,
digest or length changes, root changes, signature changes, unsupported profiles, and prohibited
content. Integrity does not establish export authorization; `policy/export.json` and the CLI say so
explicitly.

## Commands

```text
exulanica-wmp project --workspace UUID --actor UUID --private-key KEY --output DIRECTORY
                      [--extension authored-world-1.0]
exulanica-wmp verify DIRECTORY
exulanica-wmp inspect DIRECTORY
exulanica-wmp diff BEFORE_DIRECTORY AFTER_DIRECTORY
exulanica-wmp import-check DIRECTORY [--loader-capability CAPABILITY ...]
                           [--supported-style-profile ID@VERSION ...]
                           [--supported-interaction-capability KEY@VERSION ...]
```

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

## Exit evidence

The phase-specific tests cover a clean subprocess with database URLs removed, one-byte payload and
manifest mutation, every prohibited class, symlink and unexpected-file rejection, concurrent
mutation after the repeatable-read snapshot begins, immutable audit receipts, deterministic
unchanged re-export, and deletion followed by a new root and semantic removed-state diff. The full
backend PostgreSQL suite, Ruff, migration count, and import boundaries are run before the phase
commit; those command results, not this status sentence alone, are the exit gate.

## Authored-world extension 1.0

Status: **BUILT**, opt-in. Implementation: `exulanica/world_package/authored.py` (sections,
verifier rules, loader report), `projector.py` (`_authored_world`), `package.py` (extension
discovery and `import-check`). It carries the state [world-objects-contract.md](world-objects-contract.md)
defines: alternate versions, their authored objects and source-element overrides, and the reviewed
asset and behaviour references those objects make.

### Why an extension and not a 1.1 profile

Section 8 of the objects contract sketched a 1.1 profile with new required paths. Two facts rule
that out without a migration, and this change has none. `REQUIRED_PAYLOAD_PATHS` is checked before
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

`delta` is the document `exulanica.world.objects.canonical_delta_document` builds, so its SHA-256
over the canonical JSON rule is the version's `state_sha256`, the same token `GET /world/versions`
returns and every edit names as its base. Objects keep their region-local fixed-point transforms,
their `origin` (`authored`, with the role the person chose) and their behaviour key, version and
parameters. Ids are pseudonymised with the same `urn:exulanica:wmp:<kind>:<sha256>` rule as the 1.0
components, so `version_id` is `sha256("alternate-version:" + uuid)`: a holder of the version id
can match it, and the package alone does not reveal it.

The extension is added only when `project` is given `--extension authored-world-1.0`. With it, the
eighteen 1.0 payloads are unchanged except `ro-crate-metadata.json`, which gains the four files in
`hasPart`, one `Profile` node for the extension, and a `conformsTo` on `extension.json`. The crate
root still conforms to the 1.0 profile alone, because a 1.0 verifier requires exactly that value.
The export receipt's `export_policy` records the extension; the package root does not depend on it.

### What is not exported

- **Actors.** `created_by` and each edit's `actor` are omitted, as tombstones omit the requesting
  actor. The digests that make the edit chain checkable are kept.
- **Versions whose source was deleted.** This is the decision section 8 left open. A version is
  invalid exactly when its source snapshot carries a `world_structure_invalidation` row. The
  projector already withdraws a scene when one member is deleted, and an authored delta posed in the
  regions of withdrawn structure is the same kind of claim, so such a version is withheld and only
  counted (`withheld.invalidated_source_versions`), never named. The authored work survives in the
  database and in `GET /world/versions`. Invalidation is per source snapshot and a branch shares its
  parent's source, so no exported version names a withheld parent.
- **Asset bytes and runtime code.** An asset is a digest an authorized resolver supplies; a
  behaviour is an identifier with bounded parameters. Embedding reviewed CC0 bytes would be a new,
  separately versioned opt-in, and this version refuses any file it does not name.

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
| `wmp-extension:exulanica-wmp-ext-authored-world@1.0` | the extension is present |
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
unsupported, the milestone's "unsupported behavior fails visibly". `import-check` runs no loader: a
declared capability is the loader's claim, and the answer is a comparison of that claim with the
signed content.

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

[evaluation/2026-09-11-developer-proof.json](evaluation/2026-09-11-developer-proof.json) retains the
same proof on the reference copy: a package projected from the version the second client edited,
verified by this code and by the verifier at 90edb49, checked against four loader declarations, and
the same snapshot projected without the extension by this code and by the 90edb49 projector,
byte-identical in every file including the signature.

## Explicit training dataset profile

`exulanica-wmp-training-1.1` is an independently selected dataset profile. The ordinary `project`
command still writes `exulanica-wmp-1.0`, whose eighteen required paths and signed profile identity
are unchanged. The new profile has its own required documents: RO-Crate metadata, profile,
materials, training consent, and export provenance. It shares the inventory, Merkle construction
and Ed25519 verifier with the memory profile. It does not imply that a memory export is licensed
for training, nor does importing a dataset create an interactive memory world.

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

Migration 0039 adds one workspace-isolated receipt table. The live schema assertion confirms
66 such tables. Exports take an exclusive workspace source lock through validation and publication;
source mutations take its shared counterpart, so ordinary ingest and withdrawal writers can still
race as the existing deletion protocol requires. A package lock serializes training decisions
with exports. This closes the withdrawal/publication race while permitting other workspaces to
continue. The tradeoff is that source mutations and other exports in the exporting workspace wait
during signing and publication. The current authoring API also holds selected asset bytes in memory; it is
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

The Phase 7B acceptance test produces a synthetic sample with exact source photos, scripted
recovered cameras/calibration, sparse observations, a structurally valid scripted trained SOG,
frozen split and provenance. No real COLMAP, CUDA training, or vision-model execution is claimed.
FR-11 remains outstanding: two prospective licensees must independently evaluate a sample and
state in writing what they would pay for what volume. The phase remains a design until that
demand evidence exists.
