"""Write the graph projection for scenes that published before the projection stage existed.

A scene published from now on writes its own projection, inside the same atomic acceptance as its
pose, placement and gate receipts (`exulanica/ingest/scene_reconstruction.py`). A scene published
before that has none, so its first graph read in every fresh process still rebuilds the placement
from 780 MB of point maps and walks every point in Python. This is the one-shot that fixes those.

It runs as the ordinary worker role, `exulanica_app`, against `EXULANICA_DATABASE_URL`, and writes
exactly what the worker would have written: the same stage, the same deterministic artifact id, the
same bytes. It is idempotent, because the artifact id is derived from the three receipt digests and
`insert_scene_artifact` is `on conflict do nothing`; running it twice writes nothing the second
time and says so.

WHAT IT REFUSES, and why each refusal is a refusal rather than a warning:

*   A scene whose job is not `reconstruction_scene.current_job_id`. This is the important one.
    Nothing in `exulanica.ingest` ever sets `artifact.superseded_by`, so every projection a scene
    has ever had stays live, and the graph offers the newest few by `created_at`. A projection
    written now for a superseded build would be the newest and would fail every binding, so it
    would cost that scene its fast path rather than restore it. Only the current job is projected.
*   A scene whose durable member list disagrees with the member list inside its placement record.
    The graph binds the projection to the database's list, so a projection built from the other one
    would be refused on every read. Better to say so here than to write bytes nobody will use.
*   A scene whose placement does not revalidate against its pose receipt and its current point
    maps. The projection transcribes a validated record; transcribing an unvalidated one would be
    laundering it. This is the slow part, and it is the same work the graph read used to do on
    every cold process, done once here instead.
*   A tombstone-blocked scene, which the database refuses outright. That is a normal skip.

It records what it wrote: one JSON document on stdout, and to `--output` if given, naming every
scene it considered and what happened to it.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from exulanica.db import Database
from exulanica.env import resolve_data_dir
from exulanica.errors import BlobNotFoundError, IntegrityError, TombstonedError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.committed_store import committed_writes
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.scene_projection import (
    SCENE_PROJECTION_STAGE,
    build_scene_projection,
    projection_point_map_inputs,
    validate_scene_projection,
)
from exulanica.ingest.scene_reconstruction import _scene_key
from exulanica.ingest.stages import STAGES, artifact_id_for, input_digest_of, stage
from exulanica.reconstruction.placement import PointMapInput, validate_placement_record
from exulanica.store.local import LocalContentAddressedStore

PROFILE = "exulanica.scene-projection-backfill/v1"


class _Disagrees(Exception):
    """An existing projection row disagrees with the bytes recomputed from the same receipts."""


#: Every published scene in the workspace, with the three receipt digests of its CURRENT job.
#: Modelled on `_SCENES` in `exulanica/graph/reconstruction_scenes.py`, and narrowed the same way:
#: a job that is not the scene's current one is not selected at all, rather than selected and
#: skipped, so the refusal cannot be lost to a later edit of the loop below.
_SCENES = """
select s.scene_id,
       j.job_id,
       pose.artifact_id     as pose_id,
       pose.content_sha256  as pose_sha256,
       placement.content_sha256 as placement_sha256,
       gate.content_sha256  as gate_sha256
  from reconstruction_scene s
  join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id
   and j.job_id = s.current_job_id
   and j.status = 'succeeded'
  join artifact pose
    on pose.workspace_id = s.workspace_id
   and pose.artifact_id = j.pose_receipt_artifact_id
   and pose.kind = 'pose_receipt'
   and pose.purged_at is null
  join artifact placement
    on placement.workspace_id = s.workspace_id
   and placement.artifact_id = j.placement_artifact_id
   and placement.kind = 'point_map_placement'
   and placement.purged_at is null
  join artifact gate
    on gate.workspace_id = s.workspace_id
   and gate.artifact_id = j.gate_artifact_id
   and gate.kind = 'scene_gate_receipt'
   and gate.purged_at is null
 where s.workspace_id = %s
   and (%s::uuid is null or s.scene_id = %s::uuid)
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
 order by s.scene_id
"""

#: The scene's members as the GRAPH resolves them, which is the list the projection is bound to.
#: `reconstruction_scene_build_member` and this exact ordering, because that is what `_members`
#: reads for a scene with a job, and a projection bound to any other list is refused on every read.
_MEMBERS = """
select capture_id
  from reconstruction_scene_build_member
 where workspace_id = %s and job_id = %s
 order by ordinal, capture_id
"""

#: The live artifact row for one point map, with the same predicates the graph applies. A purged,
#: superseded or tombstone-blocked point map makes its scene unprojectable, exactly as it makes it
#: unreadable, and the placement's own reference is not enough to establish otherwise.
_POINT_MAP = """
select a.artifact_id
  from artifact a
  join capture c
    on c.workspace_id = a.workspace_id
   and c.capture_id = %s
   and c.blob_sha256 = a.source_blob_sha256
 where a.workspace_id = %s
   and a.artifact_id = %s
   and a.kind = 'point_map'
   and a.content_sha256 = %s
   and a.byte_size is not null
   and a.purged_at is null
   and not tombstone_blocks_capture(a.workspace_id, c.capture_id)
"""


def _placement_inputs(placement_bytes: bytes):
    """The placement's point-map references, in record order."""
    raw = json.loads(placement_bytes)["placement"]["point_map_inputs"]
    if not isinstance(raw, list):
        raise ValueError("the placement point-map input list is malformed")
    return [
        (str(item["capture_ref"]), str(item["artifact_ref"]), str(item["content_sha256"]))
        for item in raw
    ]


def _project_one(repository, store, row) -> dict:
    """Consider one scene. Returns what happened to it, never raising for a per-scene refusal."""
    scene_id = row["scene_id"]
    outcome = {
        "scene_id": str(scene_id),
        "job_id": str(row["job_id"]),
        "pose_receipt_sha256": bytes(row["pose_sha256"]).hex(),
        "placement_receipt_sha256": bytes(row["placement_sha256"]).hex(),
        "gate_receipt_sha256": bytes(row["gate_sha256"]).hex(),
    }
    members = [
        str(item["capture_id"])
        for item in repository.connection.execute(
            _MEMBERS, (repository.workspace_id, row["job_id"])
        ).fetchall()
    ]
    outcome["member_count"] = len(members)
    if not members:
        return {**outcome, "action": "skipped", "reason": "the scene has no durable members"}

    # Asked BEFORE the expensive work, not after. The identity key is a pure function of the
    # scene and the three receipt digests, all of which are already in `row`, so a scene that
    # already has its projection can be answered without reading its pose receipt or hashing
    # 780 MB of point maps. That is what makes a run resumable: an operator whose 40 scene
    # backfill died at scene 12 re-runs it and pays for scenes 12 to 40, not 1 to 40.
    spec = stage(SCENE_PROJECTION_STAGE)
    input_digest = input_digest_of(
        [
            bytes(row["pose_sha256"]),
            bytes(row["placement_sha256"]),
            bytes(row["gate_sha256"]),
        ]
    )
    key = _scene_key(scene_id, spec.key, input_digest)
    artifact_id = artifact_id_for(key)
    existing = repository.find_artifact(key)
    if existing is not None and existing.artifact_id == artifact_id:
        stored = bytes(existing.content_sha256).hex()
        if store.exists(BlobId.from_hex(stored)):
            return {
                **outcome,
                "action": "already-present",
                "artifact_id": str(artifact_id),
                "projection_sha256": stored,
            }
        # The row is live but its bytes are not there, which is what a run killed between the
        # row commit and the byte flush leaves behind. The graph offers that row, fails to read
        # it and rebuilds, so this is the case the backfill most needs to heal rather than
        # report as done. Fall through and rewrite the bytes.
        outcome["repaired_missing_bytes"] = True

    try:
        pose_bytes = store.get(BlobId(bytes(row["pose_sha256"])))
        placement_bytes = store.get(BlobId(bytes(row["placement_sha256"])))
    except BlobNotFoundError:
        return {**outcome, "action": "skipped", "reason": "a scene receipt is missing its bytes"}
    except IntegrityError:
        return {
            **outcome,
            "action": "skipped",
            "reason": "a scene receipt failed its content digest",
        }

    try:
        references = _placement_inputs(placement_bytes)
    except (KeyError, TypeError, ValueError) as error:
        return {**outcome, "action": "skipped", "reason": f"the placement is malformed: {error}"}

    point_maps = {}
    for capture_ref, artifact_ref, content_sha256 in references:
        live = repository.connection.execute(
            _POINT_MAP,
            (
                uuid.UUID(capture_ref),
                repository.workspace_id,
                uuid.UUID(artifact_ref),
                bytes.fromhex(content_sha256),
            ),
        ).fetchone()
        if live is None:
            return {
                **outcome,
                "action": "skipped",
                "reason": f"point map {artifact_ref} is not live for this scene",
            }
        try:
            content = store.get(BlobId.from_hex(content_sha256))
        except BlobNotFoundError:
            return {**outcome, "action": "skipped", "reason": "a point map is missing its bytes"}
        except IntegrityError:
            return {
                **outcome,
                "action": "skipped",
                "reason": "a point map failed its content digest",
            }
        point_maps[capture_ref] = PointMapInput(
            capture_ref, artifact_ref, content_sha256, content
        )

    # The slow part, and the whole point of doing it here: this is the work the cold graph read
    # used to repeat in every fresh process. `validate_placement_record` rebuilds the placement
    # from the pose receipt and these exact point maps and refuses if it disagrees.
    try:
        placement = validate_placement_record(
            placement_bytes,
            expected_scene_ref=str(scene_id),
            pose_receipt=pose_bytes,
            member_capture_refs=members,
            point_maps=point_maps,
        )
    except (KeyError, TypeError, ValueError) as error:
        return {
            **outcome,
            "action": "skipped",
            "reason": f"the placement does not revalidate: {error}",
        }
    if tuple(placement.member_capture_refs) != tuple(members):
        return {
            **outcome,
            "action": "skipped",
            "reason": "the durable member list disagrees with the placement's",
        }

    pose_sha256 = bytes(row["pose_sha256"]).hex()
    placement_sha256 = bytes(row["placement_sha256"]).hex()
    gate_sha256 = bytes(row["gate_sha256"]).hex()
    payload = build_scene_projection(
        scene_ref=str(scene_id),
        pose_receipt=pose_bytes,
        pose_receipt_sha256=pose_sha256,
        placement_receipt_sha256=placement_sha256,
        gate_receipt_sha256=gate_sha256,
        member_capture_refs=members,
        placement=placement,
    )
    # Checked before it is stored, on the same bytes that will be stored, so a projection no
    # reader would accept is never written.
    validate_scene_projection(
        payload,
        expected_scene_ref=str(scene_id),
        pose_receipt_sha256=pose_sha256,
        placement_receipt_sha256=placement_sha256,
        gate_receipt_sha256=gate_sha256,
        member_capture_refs=members,
        point_map_inputs=projection_point_map_inputs(placement),
    )

    content_id = BlobId.of_bytes(payload)
    outcome |= {
        "artifact_id": str(artifact_id),
        "projection_sha256": content_id.hex,
        "byte_size": len(payload),
        "placed_member_count": len(placement.placed),
        "recovered_camera_count": len(json.loads(payload)["projection"]["recovered_cameras"]),
    }

    # "manual" rather than "repair": `pipeline_run.trigger` is a closed CHECK set of ingest,
    # reprocess, repair and manual, and this run was started by an operator filling in an artifact
    # a later version of the worker would have written, not repairing bytes that went missing.
    ledger = Ledger.start_run(repository, trigger="manual")
    try:
        with (
            ledger.stage(spec) as recorder,
            repository.locked_stored_objects([content_id]),
            committed_writes(repository, store) as pending,
        ):
            inserted = repository.insert_scene_artifact(
                artifact_id=artifact_id,
                kind=spec.output_kind,
                scene_id=scene_id,
                stage_key=spec.key,
                stage_version=spec.version,
                params_digest=spec.params_digest,
                input_digest=input_digest,
                idempotency_key=key,
                content_sha256=content_id.digest,
                storage_key=store.key_for(content_id),
                byte_size=len(payload),
                produced_by_event=recorder.stage_started_event,
            )
            # Appended unconditionally, which is what `SceneReconstructionProcessor._accept` does
            # and for the same reason. `insert_scene_artifact` is `on conflict do nothing` and
            # `committed_writes` commits the ROW and then flushes the BYTES, so a run killed in
            # that window leaves a live artifact row with nothing behind it. The graph then offers
            # that row as a candidate forever, fails to read it, and rebuilds. Appending only when
            # `inserted` would make the re-run that should heal it report "already-present"
            # instead, which is a false claim that the scene has its projection.
            pending.append(payload)
            if inserted:
                recorder.record_output(artifact_id)
            else:
                # The row already existed. It must agree with what was just recomputed, or this
                # stage is not the deterministic function it declares itself to be, and that is
                # worth refusing rather than reporting as an ordinary no-op. Same check
                # `SceneReconstructionProcessor._accept` makes.
                existing = repository.find_artifact(key)
                if (
                    existing is None
                    or existing.artifact_id != artifact_id
                    or existing.content_sha256 != content_id.digest
                ):
                    raise _Disagrees(
                        "an existing projection disagrees with the bytes recomputed from this "
                        "scene's receipts"
                    )
    except TombstonedError as error:
        ledger.finish("failed")
        return {**outcome, "action": "skipped", "reason": f"deletion reaches this scene: {error}"}
    except _Disagrees as error:
        ledger.finish("failed")
        return {**outcome, "action": "refused", "reason": str(error)}
    except BaseException:
        ledger.finish("failed")
        raise
    ledger.finish("succeeded")
    return {**outcome, "action": "written" if inserted else "already-present"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=uuid.UUID,
        action="append",
        required=True,
        help="Workspace to backfill. Repeatable.",
    )
    parser.add_argument(
        "--scene", type=uuid.UUID, default=None, help="Only this scene, in every named workspace."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Overrides EXULANICA_DATA_DIR. The object store is <data-dir>/blobs.",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Also write the record to this path."
    )
    args = parser.parse_args()

    data_directory = resolve_data_dir(explicit=args.data_dir)
    store = LocalContentAddressedStore(data_directory.resolve() / "blobs")
    database = Database.from_env()

    scenes = []
    for workspace_id in args.workspace:
        with database.session(workspace_id) as connection:
            repository = IngestRepository(connection, workspace_id)
            # The `pipeline_event` trigger refuses a stage that is not in `stage_definition`, and
            # a database provisioned before this stage existed does not have it.
            repository.register_stages(STAGES)
            rows = connection.execute(
                _SCENES, (workspace_id, args.scene, args.scene)
            ).fetchall()
            print(f"{workspace_id}: {len(rows)} published scenes", file=sys.stderr, flush=True)
            for row in rows:
                print(f"  {row['scene_id']}", file=sys.stderr, flush=True)
                # A scene that raises must not take the record of everything already written
                # down with it. Each `Database.session` is autocommit and each `committed_writes`
                # is its own transaction, so the scenes before this one stay committed either
                # way; what would be lost is the only document naming them, which is exactly the
                # case where an operator most needs it.
                try:
                    outcome = _project_one(repository, store, row)
                except Exception as error:
                    outcome = {
                        "scene_id": str(row["scene_id"]),
                        "job_id": str(row["job_id"]),
                        "action": "failed",
                        "reason": f"{type(error).__name__}: {error}",
                    }
                scenes.append({"workspace_id": str(workspace_id), **outcome})

    actions: dict[str, int] = {}
    for scene in scenes:
        actions[scene["action"]] = actions.get(scene["action"], 0) + 1
    record = {
        "profile": PROFILE,
        "workspaces": [str(workspace_id) for workspace_id in args.workspace],
        "scene_filter": str(args.scene) if args.scene else None,
        "considered": len(scenes),
        "actions": dict(sorted(actions.items())),
        "scenes": scenes,
    }
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(text)
    print(text, end="")
    # A skip or a refusal is a recorded outcome, not a process failure: a scene whose point maps are gone genuinely
    # cannot be projected, and the graph reads it exactly as it did before. Only an unhandled
    # exception, which propagates, is a failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
