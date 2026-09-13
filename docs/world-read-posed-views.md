# World Read posed image bytes

Wire contract for posed image bytes. Written 2026-09-08; byte delivery is implemented.
Migration: NONE.
Release remains internal_only. Generated fixtures and scripted pose outputs establish
byte delivery, not reconstruction quality, training permission or redistribution rights.

Each existing view retains its capture, ordinal, registration, camera, exclusion and consent.
An additive photo_bytes object uses exulanica.world-read-view/v1 and either an explicit
unavailable reason or an available descriptor. Available descriptors bind the exact SHA-256,
byte length, decoded MIME type and dimensions, original source digest, pose input digest,
pose receipt digest, camera and authenticated fetch reference. The descriptor binding is the
canonical digest of these fields before the binding and URL are added. The existing authenticated
/evidence/{span_id}/masked route accepts the scene, capture and expected descriptor binding.
An unbound caller preserves its existing behavior. Original citation routes keep exact original
meaning; they never substitute a derivative.

Compatibility is conservative: selected viewer bytes must equal the pose frame's persisted
input digest and match the recorded camera pixel dimensions. The supported relationship is
identity: no crop, resize or EXIF transform at delivery, unchanged intrinsics. Non-identity
EXIF originals refuse because the pose receipt does not persist the decoder's orientation
convention. Dimensions alone cannot prove orientation, particularly reflections and 180-degree
rotations. Mask production receives open_upright output and encodes full-sized neutral-fill JPEG
without EXIF; a generated mask of an oriented original can therefore qualify when its exact
digest is the persisted pose frame. A later current mask is never substituted for historical
pose lineage. Different current/pose digests are named and refused, pending a persisted spatial
transform contract. Legacy missing bindings and members without cameras remain unavailable.

Producer trace: SceneReconstructionProcessor._manifest applies exact declared masked sources;
stage_scene_sources copies digest-verified bytes, and SourceFrame commits those same bytes.
COLMAP camera parsing retains image_size and calibration. recovered_camera_records exposes
those intrinsics and the established scene camera convention. No pixel calibration is invented.
This package does not modify producers or shared policy. Supporting transformed originals or
non-identical viewer/pose images would require a separately evidenced producer scope extension.

Build descriptors only after validating retained pose receipt and the existing member projection.
Use asset_read_policy.image_source for selection and scene_inputs/scene_allowed for geometry
lineage. Before download, reproduce the descriptor under the requesting workspace, buffer and
hash-verify the complete object, then reuse final_check to recheck exact scene bindings and
current image selection. No store reads or network delivery occur while holding its barrier.
A changed binding refuses with 409 and requires bundle refresh. Full and range responses are
checked against the full object digest before slicing; recipients reassemble ranges before
checking SHA-256. A range fragment cannot independently prove the full object digest.

Recorded-digest v2 remains byte-compatible: photo_bytes lives only in views, already excluded
from recorded_keys. Existing recorded recipient evidence, including its legacy photo_bytes
unavailable marker, remains unchanged. bundle_sha256 covers every live descriptor. Exact image
digests additionally identify the conditioning bytes independently of recorded identity.
Legacy readers may ignore the additive key; strict readers must explicitly support it. Tests
must remove only the addition and show identical recorded identity and changed full digest.

The offline verifier receives a trusted expected bundle digest and downloaded files. It checks
canonical envelope integrity, existing recipient evidence, descriptor structure/binding, exact
file digest and size, decoded orientation/dimensions, and camera agreement with the retained
pose receipt. It needs neither SQL nor a store or network connection. Missing legacy descriptors
report unavailable. Later withdrawals cannot be discovered offline. Unsigned issuer history is
not a completeness or authority proof. No public URLs, retained activation or model execution.

Implementation detail: the descriptor also commits the unchanged recipient evidence digest
and the capture's recorded region/consent digest inventory. This binds job and point lineage
as well as pose, and requires refresh even for a consent write that selects the same image.
The download rebuild occurs in a read-only repeatable-read snapshot; its buffered scene inputs
are checked after that snapshot closes. A final missing/corrupt buffer returns controlled 409.
Offline checks validate current-at-explicit-time recorded point lineage, including exact mask
manifest/build snapshots, before treating the downloaded view as verified. The fresh-process
test disables psycopg.connect as well as clearing database environment settings.

The first campaign at 3b8d97b passed 57 targeted cases and killed all three controls.
Its full backend run was deliberately interrupted to add an omitted acceptance distinction:
a newly generated selected replacement mask must remain different from the old pose source,
not merely cause a missing-mask refusal. That campaign and the development fixture failures
are retained. Replacement tests exercise both between-request and during-range changes, with
actual mask production, current /masked success, old binding 409, and separate selected/pose
SHA-256 fields in the unavailable descriptor. No producer or policy extension was required.

Absent legacy screening is exercised as a generated pre-admission-shaped row in the disposable
schema using the existing asset-read test technique: only the fixture setup transaction uses
replica mode, then asserts origin mode before actual route reads. Current producers' rejection
of an ordinary attempted missing-lineage update is preserved in the failed-attempt log.
This does not migrate or backfill a legacy database. Unregistered members remain visible in
an authenticated scene bundle and their attempted bound download refuses.

## Executed handoff

Source base: 8e88b59aadb41088dc5fab185c088e1f36c570b5. Contract-first commit: cc4309e.
Production implementation and verification scripts: 3b8d97b. Final gate source:
56a13a2e565e30076cfca8e736c17433b0e1fa83. Later commits retain documentation/evidence only.
The final gate source adds acceptance tests and a query line wrap; runtime and scripts remain
byte-identical to 3b8d97b. Worktree: exulanica-posed-view-bytes; branch: codex/posed-view-bytes.
No source or policy scope extension was used. Migration: NONE.

The final serialized campaign passed 64 targeted cases, 2180 backend tests (3 skips), Ruff,
all four import contracts, web typecheck and boundaries, and 876 web tests. Locked pose and
reconstruction extras were installed. All 292 retained artifact bindings and the predecessor
were checked, followed by retained-record checks after both new envelopes were generated.
The backend took 397 seconds; a read-only diagnostic sample during the run found no database
blocker. That run completed without intervention. The earlier intentionally interrupted run
and development fixture/lint failures remain in the final artifact inventory.

Actual authenticated scene and place requests each returned 200, then each delivered three
image downloads: two originals (161x100 and 162x100) and a real 160x100 neutral-fill mask.
The mask's generated original has a 100x160 sensor grid and EXIF orientation 6; intake produces
the upright 160x100 mask used by the scripted pose producer. Both fresh-process verifications
reproduced every downloaded digest, size, camera and retained source binding, with database
connection attempts disabled. The exact mask SHA-256 equals its persisted pose input SHA-256:
ad454bbfbe7d9212f01d4fd706b27ead9b9eb814937b0f4440bc8473b25c5d82.
The original source digest is separately retained; it is not relabelled as the mask digest.

Full and split-range delivery reproduce the complete object digest. Current replacement masks
return 200 while the old range binding returns 409, both between requests and during buffering.
The old pose input and new selected image digests remain distinct in the unavailable descriptor.
Expiry is tested one microsecond before and exactly at the boundary through actual SQL/routes.
Consent writes that retain image selection and lineage changes during buffering also refuse.
Cross-workspace IDs return 404; withdrawal returns 410; missing/corrupt objects and stale/missing
masks refuse. Unregistered members persist in a 200 scene bundle and their bound fetch returns
409. A generated legacy-shaped missing-screening row returns bound-download 409 and scene 404.
Legacy absent descriptors remain explicitly unavailable offline. Fresh processes independently
reject tampered downloads, malformed descriptors and missing files with named JSON errors.

All three controls have the exact selector's own FAILED line, not a different failing test:

- tests/test_world_read_views.py::test_wrong_bytes_under_declared_digest_refuse_route
- tests/test_world_read_views.py::test_final_permission_check_refuses_during_fetch
- tests/test_world_read_views.py::test_camera_pixel_space_refuses_route

Removing only photo_bytes from each saved scene/place bundle reproduces the same recorded v2
digest and changes the full bundle digest. The original recipient record was not changed.
Original citation routes still serve exact originals when permitted and refuse required masks;
workspace isolation and internal_only remain intact.

Every brief acceptance category has an executed generated-fixture or labelled legacy-simulation
case. Successful delivery of a non-identity EXIF original is deliberately unsupported, distinct
from the successful upright derivative case. Cropped/resized/transformed viewer-to-pose mappings
are not established. Legacy simulations are not migration/backfill evidence. Scripted pose
outputs are not measured reconstruction quality. Presentation permission does not grant training
or redistribution; offline verification cannot discover subsequent withdrawals. No retained-data
activation, personal media, hosted model, paid GPU, merge or push occurred.

- [Campaign and all preserved attempts](evaluation/2026-09-08-run-02-world-read-views.json)
- [Successor binding verification](evaluation/2026-09-08-verification-world-read-views.json)
- [Route and digest observations](evaluation/artifacts/2026-09-08-run-02-world-read-views/acceptance-observations.json)
- [Fresh-process negative results](evaluation/artifacts/2026-09-08-run-02-world-read-views/fresh-negative-results.json)
