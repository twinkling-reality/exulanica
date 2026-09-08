# World Memory Package v1

Status: **BUILT AND EXIT-GATED**. The implementation profile is `exulanica-wmp-1.0`.

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
exulanica-wmp verify DIRECTORY
exulanica-wmp inspect DIRECTORY
exulanica-wmp diff BEFORE_DIRECTORY AFTER_DIRECTORY
exulanica-wmp import-check DIRECTORY [receiver capability declarations]
```

`verify`, `inspect`, `diff`, and `import-check` do not open PostgreSQL. Diff output reports semantic
JSON pointers and before/after value hashes, not the values themselves. `import-check` never mutates
a live world; absent receiver capability declarations produce `indeterminate`, not a fabricated
compatibility pass. Import remains a later explicit transaction and is not implemented as a side
effect of inspection.

## Exit evidence

The phase-specific tests cover a clean subprocess with database URLs removed, one-byte payload and
manifest mutation, every prohibited class, symlink and unexpected-file rejection, concurrent
mutation after the repeatable-read snapshot begins, immutable audit receipts, deterministic
unchanged re-export, and deletion followed by a new root and semantic removed-state diff. The full
backend PostgreSQL suite, Ruff, migration count, and import boundaries are run before the phase
commit; those command results, not this status sentence alone, are the exit gate.

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
