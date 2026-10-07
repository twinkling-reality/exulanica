# Workspace asset admission

This contract owns how a person's own 3D asset enters their workspace: what may be uploaded, how
it is validated and prepared, how the prepared output is delivered, how it may be placed, and how
it is withdrawn and erased. An admitted asset is the workspace's alone. It never becomes reviewed
catalog content and is never visible to another workspace.

Placement itself belongs to the [composition contract](world-composition-contract.md), which owns
the `workspace_asset` source kind's preview and apply rules, and a placed object's lifecycle in a
version belongs to the [world objects contract](world-objects-contract.md). Rigged and animated
characters are outside this profile; a character's preparation shares the queue described here
and is owned by the character catalog.

## Contents

- [Profile](#profile)
- [Declaration and rights](#declaration-and-rights)
- [Admission](#admission)
- [Preparation](#preparation)
- [Delivery](#delivery)
- [Placement and what placed objects mean elsewhere](#placement-and-what-placed-objects-mean-elsewhere)
- [Withdrawal and erasure](#withdrawal-and-erasure)
- [Isolation](#isolation)
- [Routes](#routes)
- [Capabilities](#capabilities)
- [Limits and boundaries](#limits-and-boundaries)
- [Supporting code and tests](#supporting-code-and-tests)

## Profile

The one content kind is `static_glb`, profile `exulanica.static-glb/v1`: a self-contained binary
glTF 2.0 container with one scene of static triangle meshes, materials and embedded PNG or JPEG
textures. Everything it draws is inside the uploaded bytes.

[static_glb.py](../exulanica/world/static_glb.py) inspects a container without decoding geometry
it has not first bounded, and refuses with one of these reasons:

| Reason | What it refuses |
| --- | --- |
| `malformed_container` | A header, chunk, length, alignment, accessor or buffer view that does not hold; JSON with a repeated key or a non-finite number; a node with two parents or a cycle |
| `compressed_content` | A geometry or texture codec the product ships no decoder for: Draco, meshopt, mesh quantization, Basis Universal, WebP or AVIF |
| `required_extension` | Any required extension |
| `extension_not_admitted` | A used extension outside the static profile |
| `external_reference` | Any `uri`, including `data:` URIs: bytes come from the upload only |
| `not_static` | Skins, morph targets or animations: anything that moves or deforms the object |
| `unsupported_feature` | Cameras, sparse accessors, a primitive mode other than triangles, an attribute the profile does not read, an image other than PNG or JPEG, more than one scene, a property the profile does not know |
| `resource_limit_exceeded` | Any bound below, counted after instancing, including texels and image sides read from image headers |
| `invalid_image` | An image whose header does not match its declared type, or that fails to decode |
| `invalid_geometry` | No scene, node or triangle to draw; indices that are not whole triangles or name a vertex past the end; a non-finite position |
| `dimensions_disagree` | Measured dimensions outside the stated tolerance of the declared ones |

The bounds are declared limits, not measured capacity. `GET /workspace-assets` states each one,
with its unit in its name:

| Bound | Value |
| --- | --- |
| Content bytes | 32 MiB |
| Declaration bytes | 64 KiB |
| JSON chunk bytes | 4 MiB |
| Nodes, meshes, primitives | 1,024, 256, 1,024 |
| Accessors, buffer views | 4,096 each |
| Materials, textures, images, samplers | 64, 64, 32, 32 |
| Draw calls after instancing | 512 |
| Rendered vertices and triangles after instancing | 1,048,576 each |
| Texture side and total texels | 4,096 px and 16,777,216 |
| Scene depth | 32 |
| Placeable largest extent | 10 mm to 50,000 mm |
| Retained bytes per workspace | 2 GiB unless configured (`EXULANICA_WORKSPACE_ASSET_RETAINED_BYTES`, 64 MiB to 1 TiB) |

A container that passes is admitted. Being admitted does not make it placeable: its preparation
must also succeed and its prepared object must meet the placeable-object profile
(`exulanica.placeable-object/v1`, the extent bounds above).

## Declaration and rights

Admission takes two parts: a `declaration`, the person's JSON statement about the bytes, and the
`content` bytes themselves. The declaration's profile is `exulanica.workspace-asset-admission/v1`:

| Field | Rule |
| --- | --- |
| `content_kind` | `static_glb` |
| `title` | 1 to 200 characters, trimmed, no control characters |
| `content_sha256`, `byte_size` | Exactly the uploaded bytes; a mismatch is `content_digest_mismatch` |
| `unit` | `millimetre`, `centimetre` or `metre`: what one glTF unit is |
| `expected_dimensions_mm` | Optional width, height and depth; when given, the measure must agree within the larger of 2 mm and 5% |
| `rights.basis` | `own_work`, naming no licence, or `licensed`, naming one |
| `rights.licence_id` | For a licensed asset, `CC0-1.0` or `CC-BY-4.0`; any other is `licence_not_admitted` |
| `rights.attribution` | Required for `CC-BY-4.0` (`attribution_required`) |
| `rights.source_reference` | Provenance text; never fetched or followed |
| `rights.statement` | `exulanica.workspace-asset-rights-statement/v1`, the statement the person makes |

Unknown fields are refused. The server, not the declaration, decides how the asset may be used:
`exulanica.workspace-asset-use/v1`, which permits placing it in this workspace's worlds and
delivering it to this workspace, and nothing else. A permissive licence does not widen that use.

## Admission

`POST /workspace-assets` is one multipart request. It validates the declaration, the rights rule,
the digest and the whole container before anything is written, so every refusal leaves no row and
no byte. A request is bytes only: no path, no URL, nothing fetched on the person's behalf.

An admission records the declaration exactly, its canonical digest, the input digest and the use
policy, then stores the input in the workspace's own namespace and requests its preparation.
The same declaration over the same bytes returns the existing live asset with 200 rather than
admitting it twice; any change to either admits a new asset. A workspace holds at most 64 live
assets and 512 MiB of input, requests at most 64 preparations a day and has at most 8 waiting or
running at once (`workspace_asset_quota_exceeded`, 429).

Its namespace also retains at most the configured number of bytes: every object not yet purged,
admitted originals and prepared outputs, withdrawn ones included until the workspace is erased. The
default, 2 GiB, keeps the whole live bound (512 MiB of input and about as much again of prepared
output) twice over, leaving as much again for withdrawn assets, whose bytes stay because per-asset
erasure is later work. An admission whose bytes would cross the limit is refused
`workspace_asset_quota_exceeded` with a detail naming the limit, and so is a preparation, which then
fails with class `quota_exceeded`; reaching the limit exactly is allowed, and bytes the namespace
already holds add nothing. `GET /readyz` states the limit under
`capacity.workspace_assets.retained_bytes_per_workspace`, a declared limit and never a count.

## Preparation

One queue, `workspace_preparation`, prepares every input a workspace admits; character recipes use
the same queue under their own preparer. `exulanica-asset-preparation` is the process that claims
work: it runs only the preparers registered in code that its host can run, each under its declared
timeout and lease, and refuses to start when it can run none. A preparation whose preparer no
running worker can run waits in `requested`. The process connects as the runtime role, refuses an
owner or a superuser, and has no HTTP surface.

The static preparer (`exulanica.static-glb-preparer`, version 1) takes these steps, and only one of
them changes bytes:

| Step | Kind | What it does |
| --- | --- | --- |
| `container` | validate | The profile inspection above, again, on the stored input |
| `data` | validate | Every accessor read within its bounds |
| `images` | validate | Every image decoded through the one decode site |
| `measure` | validate | Exact bounds of every instanced position, in millimetres |
| `normalize` | transform | A new root node scales to metres and stands the object's bottom centre at the origin; extras and empty extension lists are removed; the generator is stated; JSON is written canonically. The binary chunk is copied byte for byte |
| `output` | validate | The output is inspected again under the profile with its one added node |

Preparation is deterministic: the same input and parameters give the same output bytes, which a
golden digest holds. The receipt (`exulanica.workspace-preparation-receipt/v1`) names the
admission, the preparer and the digest of its source, the parameters, the input and output
digests, every step, the measured dimensions, the placeable verdict and the use policy.

A preparation moves `requested` to `running` to `prepared`, `failed` or `cancelled`. A claim holds
a lease; a lease that lapses is reclaimed, at most three attempts in all, after which it fails
`exhausted`. Output is write-once: it is recorded under the object's lock before its bytes are
written, so an interrupted run leaves either nothing or an output a re-run reproduces exactly. A
content failure (`invalid_content`) is answered, not run again, when the same preparation is
requested again. Cancelling stops a preparation that has not finished; a prepared one cannot be
cancelled, only withdrawn. A preparation whose bytes are missing may be requested again, and its
re-run must produce the same digest.

**Invariant.** Once a preparation publishes an output, that asset's prepared digest never changes.
Placement pins it, and apply names it.

## Delivery

`GET /workspace-assets/{asset_id}/prepared/bytes` serves the prepared container after the final
read check of migration 0041: the bytes are hash-checked, then the preparation is asked again
under the global asset read lock whether it is still current, so a withdrawal or an erasure that
commits first is never outlived by a response. The answer is `private, no-store`, carries the
output digest as its ETag, and names the asset and its licence in `X-Exulanica-Asset-Id` and
`X-Exulanica-Licence`.

The bytes are copied from the store into a file of the request's own that has no name on disk,
and checked against the output digest as they are copied, before the final check is asked. Once
it is answered, the route closes its database connection and sends that file 1 MiB at a time with
its length declared. So the bytes sent are the bytes checked, the whole output is never held in
memory, nothing is read from the store or sent while the lock is held, and the file is gone when
the response ends, however it ends. A withdrawal that commits after the final check does not cut
short a response it already permitted.

## Placement and what placed objects mean elsewhere

A prepared, placeable asset composes through the composition routes as source kind
`workspace_asset` with its `asset_id` and, on apply, the `prepared_sha256` the preview reported.
The [composition contract](world-composition-contract.md#composition-preview-and-apply) owns the
order of refusals. The placed object pins its preparation: its document carries
`workspace_preparation_id` beside `asset_sha256`, and a binding trigger refuses writing a pin
unless that preparation may be placed at that moment. A placed workspace asset takes no behaviour.

| Plane | What a placed workspace asset is |
| --- | --- |
| Version read | `asset` is null and `workspace_asset` names the asset, preparation, digest, licence and `availability` (`available`, `withdrawn`, `unavailable_bytes` or `unknown`); such a version reads with `schema_version` 4 |
| Society | An obstacle: no activity, blocking walking over half its measured width and depth, rounded up. Its input names the preparation as a `workspace_asset` dependency. A world without one composes exactly the bytes it did before |
| Flight | One solid box of its measured bounds; it hosts no flyer and no perch |
| World package export | Withheld: a version holding one, and every version branched from it, is counted under `section_not_carried` with the name `workspace_assets`; the versions before it export |
| Judge seed | A workspace holding asset objects is refused, as one holding private material bakes is |

## Withdrawal and erasure

`POST /workspace-assets/{asset_id}/withdraw` is final and idempotent. It hides; it destroys
nothing. From then on the asset reads 410, its bytes are not delivered, a waiting or running
preparation is cancelled `withdrawn` and never publishes, and composing it is refused
`workspace_asset_withdrawn`. An object already placed stays in its version with availability
`withdrawn` and is not drawn; it stays an obstacle to people and to flight until it is removed.
Moving it is placing it again and is refused 410 `withdrawn`; removing it and undoing an edit are
allowed, and a branch leaves it behind with reason `source_withdrawn`. A restore from an older
backup writes the withdrawal again before any tombstone (the `workspace_asset` kind of the restore
withdrawal catalog).

Erasure is a workspace tombstone. In the tombstone's own transaction every waiting, running or
failed preparation is cancelled `deleted` and every object in the workspace's asset namespace is
queued for the purge as kind `workspace_asset`. The purge worker destroys them as the purge role,
asking `workspace_asset_purge_is_authorized`, and the tombstone is complete only when every one is
gone. A purge worker started without the asset namespaces claims none of these jobs, so the
tombstone stays incomplete and says so.

## Isolation

Each workspace's inputs and outputs live in its own namespace, `workspace-assets/<workspace>/`, in
the configured content store (`exulanica.store.configured`): a directory under the data directory,
or the same key prefix in the shared object store, beside and never inside the shared blob
namespace. Every lock on one of its objects is the workspace's own (workspace and digest), so
another workspace's identical bytes are never waited for. Every table is under forced row-level
security keyed on the workspace. Recognising an identical upload compares only the
workspace's own live assets, so identical bytes in two workspaces are two admissions with separate
rows, files and preparations, and no answer depends on what another workspace holds. Another
workspace's asset id, with or without its digest, is answered exactly as an id that never existed:
404 on the asset routes and `unknown_workspace_asset` in composition. Admission writes nothing to
the reviewed catalog.

## Routes

Every route requires a session for the workspace. Writes need `admission.write` and reads
`world.read`.

| Route | Answers |
| --- | --- |
| `POST /workspace-assets` | 201 admitted, 200 already admitted; 422 `invalid_declaration` (with `problems`), `licence_not_admitted`, `attribution_required`, `content_digest_mismatch`, `asset_content_refused` (reason in `detail`); 413 `asset_too_large`, or `body_too_large` for a body over the route's bound; 429 `workspace_asset_quota_exceeded` |
| `GET /workspace-assets` | The live assets and an `admission` block stating content kinds, units, licences, rights bases, use policy and every bound |
| `GET /workspace-assets/{asset_id}` | One asset with its preparation and `availability`: `placeable`, or `not_placeable` with `not_prepared`, `preparing`, `preparation_failed`, `preparation_cancelled`, `incompatible` or `prepared_bytes_missing` |
| `POST /workspace-assets/{asset_id}/preparation` | 202 while a run waits or runs, 200 once prepared or when a content failure is answered |
| `POST /workspace-assets/{asset_id}/preparation/cancel` | 200, or 409 `preparation_finished` |
| `POST /workspace-assets/{asset_id}/withdraw` | 200, also when already withdrawn |
| `GET /workspace-assets/{asset_id}/prepared/bytes` | 200 bytes; 409 `preparation_not_ready` or `prepared_bytes_missing` |

Any asset route answers 404 `unknown_reference` for an id this workspace never admitted, 410
`withdrawn` once withdrawn or erased, 503 `workspace_assets_unavailable` on an instance started
without asset namespaces, 503 `retry` with `Retry-After` when a delivery held the lock a write
needs, 403 `workspace_assets_read_only` where the deployment's role may not append these
tables, and 500 `integrity_failure` when stored bytes no longer hash to the digest they are
stored under.

`POST /workspace-assets` is an upload in the API's admission classes, as `POST /intake` is
([deployment](deployment.md#541-admission)): it shares their limit and a workspace's share with
photograph uploads and may take 600 seconds for its body. Its body is bounded to one asset and one
declaration at their bounds with the multipart framing around them, about 32 MiB, and a body
declared over that is refused 413 `body_too_large` before any of it is read. The route reads its own
body: it is refused 503 `capacity_exhausted` when its class is full, 401 without a credential and
429 `workspace_capacity_exhausted` at its workspace's share, each before its body is read, and it
holds no database connection while the body arrives. A body that is not one `declaration` field of
at most 64 KiB and one `content` file, including one the multipart parser cannot read, is 422
`invalid_declaration`.

## Capabilities

The list and the asset read carry `capabilities`, the descriptors the
[capability guide](capabilities/world-api.md#discovering-what-a-world-supports) defines, each state
taken from the predicate its own write path checks:

| Operation | Where | Unavailable when |
| --- | --- | --- |
| `POST /workspace-assets` | the list | a count bound is met: 64 live assets, 64 requests in a day or 8 preparations waiting (`workspace_asset_quota_exceeded`) |
| `POST /workspace-assets/{asset_id}/preparation` | each asset | it would queue a run and a request bound is met (`workspace_asset_quota_exceeded`), or the asset was withdrawn (`withdrawn`) |
| `POST /workspace-assets/{asset_id}/preparation/cancel` | each asset | it is prepared (`preparation_finished`), or it has no preparation (`preparation_not_ready`) |
| `POST /workspace-assets/{asset_id}/withdraw` | each asset | never |

The byte total and two requests racing for the last place are still refused 429 by the write
itself. Admission and preparation carry the `preparation` effect, which takes the state of the
installation's `preparation` component, and a preparation request needs that component
([world API](capabilities/world-api.md)). The route itself does not read the installation: where
the installation runs no preparation process, it still queues a request, which waits until one
runs. Where the process states no installation, or has no profile to see a preparation process by,
the effect's state is `unknown`. An instance
without asset namespaces serves no descriptor; every asset route answers it 503
`workspace_assets_unavailable`. Composition preview and apply name `GET /workspace-assets` beside
`GET /world/assets` among the reads that list their sources.

## Limits and boundaries

- One content kind. Compressed geometry or textures, external or data URIs, skins, morph targets,
  animations, cameras and required extensions are refused, not converted.
- A placed workspace asset has no reviewed behaviour and no activity for inhabitants; it is an
  obstacle with a measured box.
- Withdrawal hides and erasure destroys the whole namespace. Erasing one asset while keeping the
  workspace is not offered, so a withdrawn asset's bytes count against the retained-bytes limit
  until the workspace is erased.
- Versions holding a placed workspace asset do not export into a world package.
- The browser reads a version holding a placed workspace asset only once its version parser takes
  a null `asset` and the `workspace_asset` view, and draws one only once it fetches the prepared
  bytes route; until both are in place, the browser's support for these versions is a gap.
- Preparation time and memory at the largest admitted inputs are bounded by the limits above and
  by the preparer's timeout; they are not a measured capacity.
- A download holds its requests slot until its last byte is sent, and up to the output's size of
  disk under the data directory until it ends
  ([deployment](deployment.md#544-decode-memory-the-term-that-sizes-the-box)).

## Supporting code and tests

| Concern | Code | Tests |
| --- | --- | --- |
| Profile and preparation steps | [static_glb.py](../exulanica/world/static_glb.py) | `tests/test_static_glb.py` |
| Declaration, admission, withdrawal, authority | [workspace_assets.py](../exulanica/world/workspace_assets.py) | `tests/test_workspace_assets_postgres.py` |
| Shared preparation queue | [workspace_preparations.py](../exulanica/world/workspace_preparations.py), [asset_preparation.py](../exulanica/world/asset_preparation.py), [asset_preparation_command.py](../exulanica/world/asset_preparation_command.py), [preparation.py](../exulanica/orchestration/installation/preparation.py) (the preparers an installation's profile installs) | `tests/test_workspace_assets_postgres.py` |
| Schema, guards, binding, erasure | [0126](../exulanica/migrations/0126_a_workspace_admits_and_prepares_its_own_assets.sql), [deletion worker](../exulanica/deletion/worker.py) | `tests/test_workspace_asset_erasure_postgres.py` |
| Routes | [workspace_assets.py](../exulanica/api/routes/workspace_assets.py) | `tests/test_workspace_assets_postgres.py`, `tests/test_existence_oracle.py` |
| Placement, society and flight | [composition_preview.py](../exulanica/world/composition_preview.py), [society_composition.py](../exulanica/world/society_composition.py), [flight_input.py](../exulanica/world/flight_input.py) | `tests/test_workspace_asset_placement_postgres.py`, `tests/test_society_workspace_obstacles.py`, `tests/test_flight_workspace_assets.py` |
| Delivery read check | [workspace_preparations.py](../exulanica/world/workspace_preparations.py) | `tests/test_final_read_check_callers.py` |
| Export and seed | [export_partition.py](../exulanica/world_package/export_partition.py), [judge_seed.py](../exulanica/orchestration/judge_seed.py) | `tests/test_world_package_export_partition.py`, `tests/test_workspace_assets_postgres.py` |
