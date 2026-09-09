# Authored world objects

Status: **PROVISIONAL**. Nothing in this document is implemented on the server. There is no
`exulanica/api/routes/world_objects.py`, no migration, and no stored object state. It was written
by the renderer and interface task so that the client, the surface and their tests had a contract
to be written against, and it is expected to be replaced or corrected by the backend task that
owns the routes. Where this document and a shipped route disagree, the route is right.

What **is** implemented is the browser half: `web/packages/app/src/world-objects-api.ts` speaks
exactly this contract, `web/packages/atlas-react/src/playcanvas/scene-objects.ts` loads and places
what it returns, `web/packages/atlas-core/src/behaviour/` is the behaviour registry it refers to,
and `web/packages/graph-client/test/fixtures/world-objects.json` is a fixture of these responses
that the client's tests read. That fixture is provisional too, and is the file to replace first.

This is the object half of [product-direction.md](product-direction.md)'s first milestone rows 3
and 4. It sits beside the appearance authority in
[world-style-backend.md](world-style-backend.md) and follows its shapes; it is not a verb on
`/world`, because `exulanica/api/routes/world.py` says in its first lines that there is
deliberately no topology mutation route there and an authored object is structural, not
appearance.

## 1. Boundary

An authored object is a **created** thing placed inside a **recovered** place. The two must not
become confusable, so:

- The server stores an object's identity, its asset reference, its transform, its origin, its
  optional behaviour, and the world version the edit was based on. It stores no geometry.
- Asset bytes are served from a workspace-local authenticated path, exactly as reconstruction
  artifacts are. A request may never carry a remote URL, markup, script, shader or renderer
  program, and a response may never emit one. This is the same refusal
  `exulanica/world/registry.py` makes for appearance recipes.
- An authored object is never evidence and is never a citation target. It supports no claim about
  the source world, and adding one to a region changes nothing about that region's coverage,
  reconstruction rung or provenance marks.
- Placing an object does not make the object's subject present in the captured place, and the
  interface must not say or imply that it does.

### The container

An authored object asset is a **self-contained GLB**, named `glb/2.0` in a closed container
vocabulary, the same way `exulanica/reconstruction/generated.py` names `sog/1` and `opm/2`.

This does not reopen [ADR-0010](adr/0010-opm-2.md), which rejected glTF as a **replacement for the
point-map container**, nor [ADR-0003](adr/0003-renderer-selection.md), which is about Spline's
export. Neither considered authored objects, which had no container at all. GLB is chosen because
the pinned renderer already decodes it from bytes in hand, so the reviewed-asset path costs a
validator rather than a decoder.

Self-contained is enforced by the client before the parser runs, and is part of the contract
rather than a client courtesy: a container carrying `buffers[].uri`, `images[].uri`, a required
extension, or one of the codec extensions whose decoder is fetched at load time
(`KHR_draco_mesh_compression`, `EXT_meshopt_compression`, `KHR_texture_basisu`) is refused. The
server should refuse the same containers at admission rather than leaving the browser as the only
gate.

## 2. The reviewed asset registry

There is no registry of 3D assets in this codebase today. This contract proposes one with the same
closed, reviewed, versioned shape as `exulanica/world/registry.py` and
`INTERACTION_POLICY_REGISTRY`: a person cannot place an arbitrary uploaded file, only an entry a
reviewer admitted.

A registry entry, in wire form:

```text
asset_id            stable identifier, one path segment
label               display name, reviewed copy
container           "glb/2.0"
reference           null when the bytes are not available, otherwise:
  href              "/world-objects/assets/{asset_id}/bytes"
  authorization     "workspace-bearer"
  content_sha256    lowercase hexadecimal SHA-256 of the bytes at href
  byte_size         exact length in bytes
origin              "fictional-source" | "appearance-reference" | "personal-association"
footprint           { radius, height } in region display units, for the placement preview
supported_behaviours  behaviour ids this asset may carry, subset of the behaviour registry
```

`reference` is `null` exactly when the bytes are unavailable, following
`exulanica/api/routes/geometry.py`. A null reference is an honest unavailable state and the
interface must show it as one; it must never be replaced with a stand-in shape that reads as the
object.

`origin` is chosen by the person, per product-direction.md: uploading an image establishes none of
these roles, and no automatic reality classifier is required or implied.

## 3. Object state

A placed object, in wire form:

```text
object_id                 stable identifier
asset_id                  a reviewed registry entry
region_id                 the region the object stands in
scene_id                  the reconstruction scene whose frame the transform is expressed in
scene_from_object         16 finite numbers, row-major, a similarity
origin                    the role the person chose for this object's source material
behaviour                 null, or { behaviour_id, parameters }
based_on_world_version_id the world version this edit was made against
recorded_sha256           the content hash of the object record, for lineage
```

`scene_from_object` is **region-local**: it is expressed in the reconstruction scene's own
recovered frame, the same frame a trained scene's `scene_from_asset` is in. The renderer composes
it with that region's display frame before drawing. Persisting the display-space transform instead
would detach the object from its region the first time new observations changed the recovered
cameras, because the display frame is derived from those cameras: the floor would move and the
object would not.

`behaviour.parameters` are bounded by the behaviour registry, not by this contract. The registry
declares the axes and the closed ranges; an unknown behaviour id, an unknown axis and a
non-finite parameter are all refusals, and an out-of-range number is clamped to the declared bound
with the clamp reported before anything is written. The one supported behaviour today is
`motion.bounded`, with `axis`, `amplitude` and `period`.

**Trigger, stop and reset are not persisted.** They are runtime state, and running is not a
property of the world. An object reopens at the transform its author placed, at rest. This is a
decision, and it is the answer to subsequent-milestone item 3's "define what persists and what
resets".

## 4. HTTP surface

All routes require a bearer token. The actor is derived from the token and is never a body field.

| Method | Route | Result |
| --- | --- | --- |
| `GET` | `/world-objects/assets` | The reviewed asset registry and its version |
| `GET` | `/world-objects/assets/{asset_id}/bytes` | Container bytes, `no-store`, ETag is the content hash |
| `GET` | `/world-objects/versions/{version_id}/objects` | Objects placed in an authored world version |
| `POST` | `/world-objects/versions/{version_id}/objects` | Place one object |
| `POST` | `/world-objects/versions/{version_id}/objects/{object_id}/transform` | Move it |
| `POST` | `/world-objects/versions/{version_id}/objects/{object_id}/behaviour` | Attach, change or clear its behaviour |
| `POST` | `/world-objects/versions/{version_id}/objects/{object_id}/removal` | Remove it |

Every mutation body carries `proposal_id`, minted by the client, and
`base_world_version_id` plus `base_recorded_sha256`. A replayed `proposal_id` answers `200` with
`already_recorded: true` rather than placing a second object, matching
`exulanica/api/routes/world_write.py`.

Every mutation is a `POST`, including the removal, and that is deliberate rather than a REST
lapse. A mutation here is a compare-and-swap that must carry a proposal id and two base tokens,
and a `DELETE` has nowhere to put them: `Transport` in `web/packages/graph-client` exposes
`getJson`, `postJson`, `delete(path)` and `getBytes`, and its `delete` takes neither a body nor a
query. Putting lineage tokens in a path segment to satisfy a verb would make them look like
identity. The appearance authority already reads this way with `POST /world/styles/rollback`.

The problem codes are intentionally distinct from the appearance authority's:

| HTTP | Code | Recovery |
| --- | --- | --- |
| `422` | `invalid_object_state` | Correct the transform, origin, or asset reference |
| `422` | `unsupported_behaviour` | Use a behaviour id and parameters the registry admits |
| `409` | `stale_world_version` | Read the current version and propose again against it |
| `424` | `unavailable_asset` | Show the recorded unavailable state; do not substitute a shape |
| `410` | `tombstoned` | The object or its version was withdrawn |
| `404` | `unknown_reference` | Absent and cross-workspace ids answer identically |

`404` for a foreign id and never `403`, per `exulanica/api/routes/world_read.py`: the two cases
must be indistinguishable. `stale_world_version` is a distinct code from the appearance
authority's `stale_style_version` on purpose, because a client branches on the code.

Concurrent edits fail clearly. There is no last-writer-wins and no automatic merge: a mutation
whose base tokens do not match current state is refused with `stale_world_version`, and the client
re-reads and asks the person again.

## 5. Failure and fallback

- Bytes that fail their digest or byte count are not decoded, and the region gets no object. The
  failure is reported in words rather than logged.
- A page with no `crypto.subtle` loads no authored object at all and says so. There is no
  unverified path.
- A container that fails validation is refused with the reason. The object is not drawn as a
  placeholder shape.
- An unsupported behaviour id does **not** prevent the object being drawn. The object is real and
  its geometry verified; the motion is refused, and the refusal is shown. Hiding a successful edit
  behind a failed one would be the worse error.
- An object whose region is not drawn in this world is refused rather than dropped silently.
- An object is drawn only while its region's body is drawn, so it never stands over ground that is
  not there.

## 6. Verification

Server-side verification is unwritten, because the server is unwritten. Any implementation must
add a `tests/test_world_objects_api.py` covering the route shapes, the problem codes, actor
derivation from the token, cross-workspace behaviour, and the replayed-proposal path, and must add
its routes to the `routable_paths` authorisation sweep in `tests/test_api.py`.

The browser half is verified today:

- `web/packages/atlas-react/test/scene-objects.test.ts` covers the container refusals, the digest
  and byte-count refusals, the `crypto.subtle` refusal, and the placement round trip.
- `web/packages/atlas-core/test/behaviour.test.ts` covers the registry refusal, the declared
  clamps, and reset exactness.
- `web/packages/app/test/world-objects-api.test.ts` covers the client against
  `web/packages/graph-client/test/fixtures/world-objects.json`.
- `web/packages/app/test/objects-surface.test.ts` covers confirm-then-commit against a scripted
  client, including that nothing is written without a confirmation.
