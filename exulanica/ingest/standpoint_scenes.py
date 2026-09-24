"""The standpoint stage: a published scene's photographs, joined where they were taken.

Pose recovery needs the camera to move between photographs. A person who turned on the spot and
took a few photographs gave it nothing to triangulate, so their scene publishes with no member
registered, and until this stage its photographs could only be laid out in an arrangement the
client derived and labelled unmeasured. This stage measures that arrangement instead, with
:func:`exulanica.reconstruction.standpoint.join_standpoint`, and writes one scene artifact, a
``standpoint_scene`` record, that the graph serves in place of the unmeasured one.

**Which scenes.** A published scene whose current build registered no member and has at least two.
A scene pose placed is never touched: its members have recovered positions, and joining them again
from one standpoint would put a second, weaker arrangement beside a measured one.

**What it reads, exactly.** Each member's point map as the scene's own placement record binds it
(artifact and digest), the exact pixels the depth model read to make it (the masked derivative
when anybody in the photograph is hidden, the decoded derivative for a HEIF, the original
otherwise, as the point map's own row names them), and the focal length the photograph's own
EXIF recorded at intake. Nothing else, and no model: MoGe-2 ran in the depth stage.

**Permission is the depth stage's.** A member is read only when its point map may be read now
(``asset_point_allows``: the capture is live, its review stands, nobody in it has been withdrawn,
and a bound depth right has not ended) and, where ``personal_model_right_required`` says the
capture needs one, when that map is bound to a depth right that still stands. A member without
permission is recorded as ``not_permitted`` with nothing of it read. Everything is asked again
under the global asset read lock inside the publication transaction, so a withdrawal cannot land
between the question and the write.

**Withdrawal.** The record binds every member it read. The graph withholds the whole arrangement
when any of them can no longer be read, because every rotation in it was measured with that
member's pixels; this stage then finds the scene due again, with that member ``not_permitted``,
and joins what remains. Deleting a member reaches the artifact through the scene's own
many-to-many identity, like every scene artifact (migration 0024).

**When it runs.** From the scene worker's refresh pass, once per new input state, and on demand
from the command at the bottom of this module. It runs where pycolmap is installed (the pose extra),
because its features are COLMAP's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from exulanica.canonical import canonical_json
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.reconstruction.standpoint_record import STANDPOINT_KIND, STANDPOINT_STAGE

if TYPE_CHECKING:
    from exulanica.ingest.ledger import Ledger, StageRecorder
    from exulanica.ingest.repository import IngestRepository
    from exulanica.ingest.stages import StageSpec
    from exulanica.reconstruction.standpoint import FeatureExtractor, StandpointPolicy
    from exulanica.store.base import ContentAddressedStore

__all__ = [
    "StandpointDue",
    "publish_standpoint_scene",
    "scenes_due_standpoint",
]

#: EXIF 2.3 FocalLengthIn35mmFilm, as the intake probe keys the EXIF IFD's raw tags.
_FOCAL_35MM_TAG: Final = "41989"

#: A published scene's current build, the same narrowing the segment lift uses.
_SCENE: Final = """
select s.scene_id, j.job_id,
       placement.artifact_id as placement_id, placement.content_sha256 as placement_sha256
  from reconstruction_scene s
  join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id and j.job_id = s.current_job_id and j.status = 'succeeded'
  join artifact placement on placement.workspace_id = s.workspace_id
   and placement.artifact_id = j.placement_artifact_id
   and placement.kind = 'point_map_placement' and placement.purged_at is null
 where s.workspace_id = %s and s.scene_id = %s
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
"""

#: Every such scene whose build registered nobody, with the members its build names.
_UNPLACED_SCENES: Final = """
select s.scene_id, j.job_id, placement.content_sha256 as placement_sha256,
       (select count(*) from reconstruction_scene_build_member m
         where m.workspace_id = s.workspace_id and m.job_id = j.job_id) as member_count
  from reconstruction_scene s
  join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id and j.job_id = s.current_job_id and j.status = 'succeeded'
  join artifact placement on placement.workspace_id = s.workspace_id
   and placement.artifact_id = j.placement_artifact_id
   and placement.kind = 'point_map_placement' and placement.purged_at is null
 where s.workspace_id = %s
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
   and not exists (select 1 from reconstruction_scene_build_member m
                    where m.workspace_id = s.workspace_id and m.job_id = j.job_id and m.registered)
 order by s.scene_id
"""

_MEMBERS: Final = """
select capture_id, ordinal from reconstruction_scene_build_member
 where workspace_id = %s and job_id = %s order by ordinal
"""

#: One member's point map as the placement record binds it, whether it may be read now, and
#: whether the depth right it was made under still stands where one is required.
_PERMISSION: Final = """
select a.artifact_id, a.source_blob_sha256, a.read_source_sha256,
       asset_point_allows(a.workspace_id, a.artifact_id, statement_timestamp()) as readable,
       personal_model_right_required(a.workspace_id, c.capture_id, a.privacy_screening_id)
         as right_required,
       exists(select 1 from point_map_model_right b
                join personal_model_right r
                  on r.workspace_id = b.workspace_id and r.right_id = b.right_id
               where b.workspace_id = a.workspace_id and b.artifact_id = a.artifact_id
                 and personal_model_right_allows(r.workspace_id, r.right_id, r.capture_id,
                       r.model_provider, r.model_role, r.model_id, r.model_revision,
                       r.destination, statement_timestamp())) as right_stands,
       t.probe_json
  from artifact a
  join capture c on c.workspace_id = a.workspace_id and c.capture_id = %(capture)s
   and c.blob_sha256 = a.source_blob_sha256
  left join media_track t on t.blob_sha256 = c.blob_sha256 and t.track_key = 'img'
 where a.workspace_id = %(w)s and a.artifact_id = %(artifact)s and a.kind = 'point_map'
   and a.content_sha256 = %(digest)s and a.byte_size is not null and a.purged_at is null
   and not a.needs_repair and not tombstone_blocks_capture(a.workspace_id, c.capture_id)
"""


class _JoinRefused(RuntimeError):
    """This scene cannot be joined as it stands. Fails its own stage and returns as a skip."""


@dataclass(frozen=True, slots=True)
class _MemberState:
    """One member as it stands now: what the join would read, or that it may not be read."""

    ordinal: int
    capture_ref: str
    artifact_ref: str
    point_map_sha256: str
    permitted: bool
    read_sha256: str | None
    focal_35mm: float | None

    def binding(self) -> dict[str, Any]:
        return {
            "artifact_ref": self.artifact_ref,
            "capture_ref": self.capture_ref,
            "focal_35mm_milli": None if self.focal_35mm is None else round(self.focal_35mm * 1000),
            "ordinal": self.ordinal,
            "permitted": self.permitted,
            "point_map_sha256": self.point_map_sha256,
            "read_sha256": self.read_sha256 if self.permitted else None,
        }


@dataclass(frozen=True, slots=True)
class StandpointDue:
    """A scene to join (again), and why."""

    scene_id: uuid.UUID
    job_id: uuid.UUID
    input_digest: bytes
    reason: str


def _focal_35mm(probe: Mapping[str, Any] | None) -> float | None:
    """The photograph's FocalLengthIn35mmFilm as intake recorded it, or None when it has none."""
    if not isinstance(probe, Mapping):
        return None
    exif = probe.get("exif")
    tags = exif.get("exif") if isinstance(exif, Mapping) else None
    value = tags.get(_FOCAL_35MM_TAG) if isinstance(tags, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def _member_states(
    repository: IngestRepository, job_id: uuid.UUID, placement_bytes: bytes
) -> list[_MemberState]:
    """Every member of the build, in order, with the point map its placement record binds."""
    connection = repository.connection
    inputs = {
        str(item["capture_ref"]): (str(item["artifact_ref"]), str(item["content_sha256"]))
        for item in json.loads(placement_bytes)["placement"]["point_map_inputs"]
    }
    states: list[_MemberState] = []
    rows = connection.execute(_MEMBERS, (repository.workspace_id, job_id)).fetchall()
    # A standpoint record numbers members by their position in the build's own order, which is
    # what the graph matches on together with each member's capture id.
    for position, member in enumerate(rows):
        capture_ref = str(member["capture_id"])
        if capture_ref not in inputs:
            raise _JoinRefused("the placement record does not bind a point map for every member")
        artifact_ref, digest = inputs[capture_ref]
        row = connection.execute(
            _PERMISSION,
            {
                "w": repository.workspace_id,
                "capture": member["capture_id"],
                "artifact": uuid.UUID(artifact_ref),
                "digest": bytes.fromhex(digest),
            },
        ).fetchone()
        permitted = bool(
            row is not None
            and row["readable"]
            and (not row["right_required"] or row["right_stands"])
        )
        states.append(
            _MemberState(
                ordinal=position,
                capture_ref=capture_ref,
                artifact_ref=artifact_ref,
                point_map_sha256=digest,
                permitted=permitted,
                read_sha256=(
                    None
                    if row is None
                    else bytes(row["read_source_sha256"] or row["source_blob_sha256"]).hex()
                ),
                focal_35mm=None if row is None else _focal_35mm(row["probe_json"]),
            )
        )
    return states


def _input_digest(
    placement_sha256: str, states: Sequence[_MemberState], extractor: Mapping[str, str]
) -> bytes:
    """Everything the join's output depends on besides the stage parameters, which key it too."""
    return hashlib.sha256(
        canonical_json(
            {
                "feature_extractor": dict(extractor),
                "members": [state.binding() for state in states],
                "placement_receipt_sha256": placement_sha256,
            }
        )
    ).digest()


def _extractor(policy: StandpointPolicy) -> FeatureExtractor:
    from exulanica.reconstruction.standpoint_features import PycolmapSift

    return PycolmapSift(
        max_features=policy.max_features,
        peak_threshold=policy.peak_threshold,
        threads=policy.feature_threads,
    )


def scenes_due_standpoint(
    repository: IngestRepository,
    store: ContentAddressedStore,
    *,
    extractor_identity: Mapping[str, str],
) -> list[StandpointDue]:
    """Unplaced scenes whose inputs no standpoint artifact answers for yet.

    Due means the key a join would write under does not exist: the first join of a scene, a
    member whose permission changed either way, a new build, a changed stage parameter or a new
    feature extractor. Asked of every unplaced scene on each pass; it reads one small receipt per
    scene and one row per member, and computes nothing heavier.
    """
    from exulanica.errors import BlobNotFoundError, IntegrityError
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.scene_reconstruction import _scene_key
    from exulanica.ingest.stages import stage

    spec = stage(STANDPOINT_STAGE)
    due: list[StandpointDue] = []
    rows = repository.connection.execute(_UNPLACED_SCENES, (repository.workspace_id,)).fetchall()
    for row in rows:
        if int(row["member_count"]) < 2:
            continue
        try:
            placement_bytes = store.get(BlobId(bytes(row["placement_sha256"])))
            states = _member_states(repository, row["job_id"], placement_bytes)
        except (BlobNotFoundError, IntegrityError, KeyError, ValueError, _JoinRefused):
            continue
        if sum(state.permitted for state in states) < 2:
            continue
        digest = _input_digest(bytes(row["placement_sha256"]).hex(), states, extractor_identity)
        if repository.find_artifact(_scene_key(row["scene_id"], spec.key, digest)) is None:
            due.append(
                StandpointDue(
                    scene_id=row["scene_id"],
                    job_id=row["job_id"],
                    input_digest=digest,
                    reason="no standpoint scene answers for this build's current members",
                )
            )
    return due


def publish_standpoint_scene(
    repository: IngestRepository,
    store: ContentAddressedStore,
    scene_id: uuid.UUID,
    *,
    extractor: FeatureExtractor | None = None,
    ledger: Ledger | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Join one unplaced scene and write its standpoint record, idempotently.

    Returns what happened. A scene with no current build, one pose placed, one with fewer than two
    members that may be read, and a deletion that reaches the scene are skips with their reason;
    anything else raises after its stage has recorded ``stage_failed``. A second run over unchanged
    inputs writes nothing and says so.
    """
    from exulanica.errors import BlobNotFoundError, IntegrityError, TombstonedError
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.ledger import Ledger
    from exulanica.ingest.stages import stage
    from exulanica.reconstruction.standpoint import StandpointPolicy

    started = time.monotonic()
    spec = stage(STANDPOINT_STAGE)
    policy = StandpointPolicy.from_params(spec.params)
    outcome: dict[str, Any] = {"scene_id": str(scene_id)}
    row = repository.connection.execute(_SCENE, (repository.workspace_id, scene_id)).fetchone()
    if row is None:
        return _skipped(ledger, spec, outcome, "the scene has no current succeeded build")
    outcome["job_id"] = str(row["job_id"])
    registered = repository.connection.execute(
        "select bool_or(registered) as any_registered from reconstruction_scene_build_member "
        "where workspace_id = %s and job_id = %s",
        (repository.workspace_id, row["job_id"]),
    ).fetchone()
    if registered is not None and registered["any_registered"]:
        return _skipped(
            ledger, spec, outcome, "pose placed photographs of this scene; it is not joined again"
        )
    try:
        placement_bytes = store.get(BlobId(bytes(row["placement_sha256"])))
        states = _member_states(repository, row["job_id"], placement_bytes)
    except (BlobNotFoundError, IntegrityError, KeyError, ValueError) as error:
        return _skipped(
            ledger, spec, outcome, f"the scene's placement record is unreadable: {error}"
        )
    except _JoinRefused as refusal:
        return _skipped(ledger, spec, outcome, str(refusal))
    if sum(state.permitted for state in states) < 2:
        return _skipped(
            ledger, spec, outcome, "fewer than two of the scene's photographs may be read"
        )
    extractor = extractor if extractor is not None else _extractor(policy)
    run = ledger if ledger is not None else Ledger.start_run(repository, trigger=trigger)
    try:
        with run.stage(
            spec,
            input_artifact_ids=[
                row["placement_id"],
                *(uuid.UUID(state.artifact_ref) for state in states if state.permitted),
            ],
        ) as recorder:
            outcome, inserted = _join_and_write(
                repository,
                store,
                scene_id,
                bytes(row["placement_sha256"]).hex(),
                states,
                spec=spec,
                policy=policy,
                extractor=extractor,
                recorder=recorder,
                outcome=outcome,
                started=started,
            )
    except _JoinRefused as refusal:
        _finish(run, ledger, "failed")
        return {**outcome, "action": "skipped", "reason": str(refusal)}
    except TombstonedError as error:
        _finish(run, ledger, "failed")
        return {**outcome, "action": "skipped", "reason": f"deletion reaches this scene: {error}"}
    except BaseException:
        _finish(run, ledger, "failed")
        raise
    _finish(run, ledger, "succeeded")
    return {**outcome, "action": "written" if inserted else "already-present"}


def _join_and_write(
    repository: IngestRepository,
    store: ContentAddressedStore,
    scene_id: uuid.UUID,
    placement_sha256: str,
    states: Sequence[_MemberState],
    *,
    spec: StageSpec,
    policy: StandpointPolicy,
    extractor: FeatureExtractor,
    recorder: StageRecorder,
    outcome: dict[str, Any],
    started: float,
) -> tuple[dict[str, Any], bool]:
    """The join itself, inside its open stage: read, join, check again, and write."""
    from exulanica.canonical import sha256_of_canonical
    from exulanica.errors import BlobNotFoundError, IntegrityError
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.committed_store import committed_writes
    from exulanica.ingest.decode import open_upright
    from exulanica.ingest.scene_reconstruction import _scene_key
    from exulanica.ingest.stages import artifact_id_for
    from exulanica.reconstruction.standpoint import (
        StandpointExclusion,
        StandpointInput,
        join_standpoint,
    )
    from exulanica.reconstruction.standpoint_record import parse_standpoint_record

    input_digest = _input_digest(placement_sha256, states, extractor.identity)
    key = _scene_key(scene_id, spec.key, input_digest)
    existing = repository.find_artifact(key)
    if existing is not None:
        return {**outcome, "artifact_id": str(existing.artifact_id)}, False
    inputs: list[StandpointInput] = []
    excluded: list[StandpointExclusion] = []
    for state in states:
        if not state.permitted or state.read_sha256 is None:
            excluded.append(
                StandpointExclusion(ordinal=state.ordinal, member_ref=state.capture_ref)
            )
            continue
        try:
            point_map = store.get(BlobId.from_hex(state.point_map_sha256))
            pixels = store.get(BlobId.from_hex(state.read_sha256))
        except (BlobNotFoundError, IntegrityError) as error:
            raise _JoinRefused(f"a member's stored bytes are unreadable: {error}") from error
        image, _facts = open_upright(pixels)
        inputs.append(
            StandpointInput(
                ordinal=state.ordinal,
                member_ref=state.capture_ref,
                point_map_artifact_ref=state.artifact_ref,
                point_map=point_map,
                image=image.convert("RGB"),
                image_sha256=state.read_sha256,
                exif_focal_35mm=state.focal_35mm,
            )
        )
    record = join_standpoint(
        scene_ref=str(scene_id),
        inputs=inputs,
        excluded=excluded,
        policy=policy,
        policy_sha256=sha256_of_canonical(spec.params).hex(),
        stage_version=spec.version,
        extractor=extractor,
    )
    payload = record.to_bytes()
    # Checked here rather than trusted, so that bytes the graph would refuse are never written.
    parse_standpoint_record(
        payload,
        expected_scene_ref=str(scene_id),
        expected_members=[
            (
                state.capture_ref,
                None if not state.permitted else state.artifact_ref,
                None if not state.permitted else state.point_map_sha256,
            )
            for state in states
        ],
    )
    artifact_id = artifact_id_for(key, workspace_id=repository.workspace_id)
    content_id = BlobId.of_bytes(payload)
    joined = 0 if record.arrangement is None else len(record.arrangement.members)
    outcome = {
        **outcome,
        "artifact_id": str(artifact_id),
        "standpoint_sha256": content_id.hex,
        "byte_size": len(payload),
        "members": len(states),
        "joined": joined,
        "not_permitted": len(excluded),
        "refusal": record.refusal,
        "join_seconds": round(time.monotonic() - started, 3),
    }
    with (
        repository.locked_stored_objects([content_id]),
        committed_writes(repository, store) as pending,
    ):
        # The final check: under the global asset read lock, every member the join read is asked
        # again, in the transaction that writes the record. A withdrawal that committed while the
        # join ran is seen here, and one that has not committed yet waits for this to finish.
        lock_asset_reads_until_commit(
            repository.connection,
            outside="a standpoint record is published only inside the transaction that writes it",
        )
        for state in _member_states(
            repository, uuid.UUID(outcome["job_id"]), _placement(store, placement_sha256)
        ):
            if not state.permitted and any(i.ordinal == state.ordinal for i in inputs):
                raise _JoinRefused(
                    "a member's permission ended while its photographs were being joined"
                )
        inserted = repository.insert_scene_artifact(
            artifact_id=artifact_id,
            kind=STANDPOINT_KIND,
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
        pending.append(payload)
        if inserted:
            recorder.record_output(artifact_id)
    return outcome, inserted


def _placement(store: ContentAddressedStore, digest: str) -> bytes:
    from exulanica.evidence.blob import BlobId

    return store.get(BlobId.from_hex(digest))


def _skipped(
    ledger: Ledger | None, spec: StageSpec, outcome: dict[str, Any], reason: str
) -> dict[str, Any]:
    """A skip decided before any work began: an event in a caller's run, and nothing otherwise."""
    if ledger is not None:
        ledger.skipped(spec, reason=reason)
    return {**outcome, "action": "skipped", "reason": reason}


def _finish(run: Ledger, caller: Ledger | None, status: str) -> None:
    """Close a run this join opened. A caller's run is the caller's to close."""
    if caller is None:
        run.finish(status)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m exulanica.ingest.standpoint_scenes --workspace <uuid> [--scene <uuid>]``.

    With ``--scene``, joins that scene; without it, every scene due.
    """
    from exulanica.db import Database
    from exulanica.env import resolve_data_dir
    from exulanica.ingest.repository import IngestRepository
    from exulanica.ingest.stages import STAGES, stage
    from exulanica.reconstruction.standpoint import StandpointPolicy
    from exulanica.store.local import LocalContentAddressedStore

    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--scene", type=uuid.UUID, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    store = LocalContentAddressedStore(resolve_data_dir(explicit=args.data_dir).resolve() / "blobs")
    extractor = _extractor(StandpointPolicy.from_params(stage(STANDPOINT_STAGE).params))
    results = []
    with Database.from_env().session(args.workspace) as connection:
        repository = IngestRepository(connection, args.workspace)
        repository.register_stages(STAGES)
        scenes = (
            [args.scene]
            if args.scene is not None
            else [
                item.scene_id
                for item in scenes_due_standpoint(
                    repository, store, extractor_identity=extractor.identity
                )
            ]
        )
        for scene in scenes:
            results.append(publish_standpoint_scene(repository, store, scene, extractor=extractor))
    json.dump(results, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if all(r.get("action") in {"written", "already-present"} for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
