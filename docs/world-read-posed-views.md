# World Read posed image bytes

Design contract written before implementation, 2026-09-08. Migration: NONE.
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
