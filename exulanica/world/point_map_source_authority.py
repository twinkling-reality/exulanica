"""Whether a placed photo point map's source may be used, asked inside an edit.

A reviewed photograph's depth estimate, placed in a version by the person whose photograph it is,
pins a chain of receipts that live in other planes: the saved world's membership, the personal
authority and the human review the photograph was added under, the depth right, and the estimate
itself. This module is where those are asked, so the object repository that writes the placement
does not also have to be their authority. Three things are worth reading before the methods.

**What resolves is not the attachment.** An attachment is membership, and composing one is refused
(``attachment_is_not_composition``). What is placed is the depth artifact reached THROUGH a
current membership, and the membership is recorded so a detach can reach what it produced.

**The pinned screening decides which estimate.** The attachment pins the human review the
photograph was added under. The derivative worker builds from the NEWEST eligible screening. A
photograph reviewed twice therefore has an estimate the current reference does not name, and that
is ``PointMapReviewDiffers`` rather than "not produced": nothing is wrong, the reference is simply
older than the estimate, and the recovery is to add it back under the newer review.

**Availability is read, never stored.** Whether a person may see a placed estimate changes when a
right ends, a review expires, a photograph is deleted or a membership is detached, none of which
is an edit to their world. It is computed on read and kept out of the state digest.

Like :mod:`exulanica.world.environment_source_authority`, it never opens a transaction and raises
each refusal as the exact class composition preview maps. It also answers for one world: the
saved world entry a reference belongs to must be of the world this authority was built for.
``tests/test_source_authorities_postgres.py`` holds the reference check equal to the saved world's
own verdict on the same rows for every state a person can reach.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import psycopg

from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.reconstruction.validation import (
    OpmIntegrityError,
    OpmIntegrityReport,
    validate_opm,
)
from exulanica.store.base import ContentAddressedStore
from exulanica.world.errors import (
    PointMapNotPermitted,
    PointMapNotProduced,
    PointMapNotReadable,
    PointMapReviewDiffers,
    PointMapTooSparse,
    SourceAuthorityExpired,
    SourceNotCurrentMembership,
    UnavailableAsset,
    UnknownWorldResource,
)
from exulanica.world.photo_point_maps import (
    DEPTH_ROLE,
    PLACEABLE_RUNG,
    POINT_MAP_CONTAINER,
    PointMapInstance,
    PointMapModel,
    PointMapSourceBinding,
)

__all__ = ["PointMapSourceAuthority"]


class PointMapSourceAuthority:
    """One workspace and world's photo point map sources, asked on an edit's own connection."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str,
        store: ContentAddressedStore | None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id
        self.store = store

    def resolve(self, entry_id: uuid.UUID, attachment_id: uuid.UUID) -> PointMapSourceBinding:
        """Membership, then permission, then the estimate. Each step raises its own refusal.

        The order is the order a person would ask the questions in, and it decides which sentence
        they read: a detached photograph is not "no estimate exists", and a stopped depth right is
        not "your review expired".
        """
        row = self.connection.execute(
            """
            select a.attachment_id,a.capture_id,a.source_sha256,a.authorization_id,a.screening_id,
                   a.attached_by,cur.attachment_id as current_attachment_id,
                   auth.corpus_class,auth.capture_id as authorized_capture_id,
                   auth.source_sha256 as authorized_sha256,auth.authorized_by,
                   auth.valid_until as authorization_valid_until,auth.evidence_digest,
                   p.capture_id as screened_capture_id,p.source_sha256 as screened_sha256,
                   p.authorization_id as screened_authorization_id,p.screening_method,
                   p.reviewed_by,p.eligibility_state,p.valid_until as screening_valid_until,
                   p.receipt_digest as screening_receipt_digest,
                   c.blob_sha256 as current_source_sha256,
                   asset_capture_live(a.workspace_id,a.capture_id,statement_timestamp())
                     as source_live,
                   statement_timestamp() as evaluated_at
              from saved_world_source_attachment a
              join saved_world_entry e
                on e.workspace_id=a.workspace_id and e.entry_id=a.entry_id
              left join saved_world_source_current_membership cur
                on cur.workspace_id=a.workspace_id and cur.entry_id=a.entry_id
               and cur.capture_id=a.capture_id
              join capture c on c.workspace_id=a.workspace_id and c.capture_id=a.capture_id
              join capture_reconstruction_authorization auth
                on auth.workspace_id=a.workspace_id and auth.authorization_id=a.authorization_id
              join reconstruction_privacy_screening p
                on p.workspace_id=a.workspace_id and p.screening_id=a.screening_id
             where a.workspace_id=%s and a.entry_id=%s and a.attachment_id=%s
               and e.world_id=%s
            """,
            (self.workspace_id, entry_id, attachment_id, self.world_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such attachment on a saved world of this world")
        if row["current_attachment_id"] != attachment_id:
            raise SourceNotCurrentMembership(
                "this photograph is not currently a reference of this world"
            )
        at = row["evaluated_at"]
        if (
            not row["source_live"]
            or row["current_source_sha256"] != row["source_sha256"]
            or row["authorized_capture_id"] != row["capture_id"]
            or row["authorized_sha256"] != row["source_sha256"]
            or row["corpus_class"] != "personal"
            or row["screened_capture_id"] != row["capture_id"]
            or row["screened_sha256"] != row["source_sha256"]
            or row["screened_authorization_id"] != row["authorization_id"]
            or row["screening_method"] != "human_review"
            or row["reviewed_by"] is None
            or row["eligibility_state"] != "eligible"
        ):
            raise UnknownWorldResource(
                "this reference's photograph, authority and review no longer agree"
            )
        if (
            row["authorization_valid_until"] is not None and row["authorization_valid_until"] <= at
        ) or (row["screening_valid_until"] is not None and row["screening_valid_until"] <= at):
            raise SourceAuthorityExpired(
                "this reference's authority or review has expired; review the photograph again"
            )
        right = self._current_depth_right(row["capture_id"], at)
        artifact = self._artifact(row, right)
        return PointMapSourceBinding(
            entry_id=entry_id,
            attachment_id=attachment_id,
            capture_id=row["capture_id"],
            source_sha256=bytes(row["source_sha256"]).hex(),
            authorization_id=row["authorization_id"],
            authorization_evidence_sha256=bytes(row["evidence_digest"]).hex(),
            screening_id=row["screening_id"],
            screening_receipt_sha256=bytes(row["screening_receipt_digest"]).hex(),
            right_id=right["right_id"],
            right_receipt_sha256=bytes(right["receipt_sha256"]).hex(),
            model=PointMapModel(
                provider=right["model_provider"],
                role=right["model_role"],
                identifier=right["model_id"],
                revision=right["model_revision"],
                destination=right["destination"],
            ),
            artifact_id=artifact["artifact_id"],
            point_map_sha256=bytes(artifact["content_sha256"]).hex(),
            byte_size=int(artifact["byte_size"]),
            container=POINT_MAP_CONTAINER,
            stage_version=int(artifact["stage_version"]),
            rung=int(artifact["rung"]),
            declared_metric=bool(artifact["declared_metric"]),
            declared_fov_y_microdegrees=int(artifact["fov_y_microdegrees"]),
        )

    def _current_depth_right(self, capture_id: uuid.UUID, at: Any) -> Mapping[str, Any]:
        """The newest depth right that stands for this photograph right now, or a refusal.

        A role, not a checkpoint: which checkpoint ran is a property of the estimate, and the
        estimate's own binding is checked against this right afterwards. Asking for a named
        checkpoint here would refuse a person who granted the right again after the pin moved.
        """
        row = self.connection.execute(
            "select right_id,model_provider,model_role,model_id,model_revision,destination,"
            "receipt_sha256 from personal_model_right r "
            "where r.workspace_id=%s and r.capture_id=%s and r.model_role=%s "
            "and personal_model_right_allows(r.workspace_id,r.right_id,r.capture_id,"
            "r.model_provider,r.model_role,r.model_id,r.model_revision,r.destination,%s) "
            "order by r.granted_at desc,r.right_id desc limit 1",
            (self.workspace_id, capture_id, DEPTH_ROLE, at),
        ).fetchone()
        if row is None:
            raise PointMapNotPermitted(
                "no current permission lets a 3D estimate from this photograph be used"
            )
        return row

    def _artifact(
        self, reference: Mapping[str, Any], right: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """The estimate for these exact bytes under the review this reference pins.

        The rung comes from the recorded assertion and NOT from the container, which is the one
        place those two disagree and it matters. ``encode_opm`` writes ``rung: 3`` as a format
        constant on every map it produces, including one the quality gate decided was rung 4, so a
        reader that trusted the header would place a handful of points and call it somebody's
        kitchen. What ``decide_rung`` measured is the assertion the depth stage recorded beside
        the artifact, and that is what is read here.

        The field of view and the metric flag come from the container, because those are what a
        renderer places the camera from; a second copy in a row could disagree with what is drawn.
        """
        row = self.connection.execute(
            """
            select a.artifact_id,a.content_sha256,a.byte_size,a.stage_version,
                   a.privacy_screening_id,
                   (s.object_value->>'rung')::int as rung,
                   asset_point_allows(a.workspace_id,a.artifact_id,statement_timestamp())
                     as readable,
                   exists(select 1 from point_map_model_right b
                          where b.workspace_id=a.workspace_id and b.artifact_id=a.artifact_id
                            and b.right_id=%(right)s) as bound
              from artifact a
              join assertion s on s.workspace_id=a.workspace_id and s.status='active'
               and s.object_value->>'point_map_artifact'=a.artifact_id::text
              join predicate pr on pr.predicate_id=s.predicate_id
               and pr.key='reconstruction_rung_is'
             where a.workspace_id=%(w)s and a.kind='point_map'
               and a.source_blob_sha256=%(source)s
               and a.purged_at is null and not a.needs_repair and a.superseded_by is null
               and a.content_sha256 is not null and a.byte_size is not null
             order by a.privacy_screening_id=%(screening)s desc,a.stage_version desc,
                      s.asserted_at desc,a.artifact_id
             limit 1
            """,
            {
                "w": self.workspace_id,
                "source": reference["source_sha256"],
                "screening": reference["screening_id"],
                "right": right["right_id"],
            },
        ).fetchone()
        if row is None:
            raise PointMapNotProduced("no 3D estimate has been made from this photograph yet")
        if row["privacy_screening_id"] != reference["screening_id"]:
            raise PointMapReviewDiffers(
                "the estimate for this photograph was made under a different review than this "
                "world's reference names"
            )
        if not row["bound"]:
            raise PointMapNotPermitted(
                "this estimate was not made under the permission that stands now"
            )
        if row["rung"] is None or int(row["rung"]) != PLACEABLE_RUNG:
            raise PointMapTooSparse(
                "too little of this photograph could be placed to stand in front of"
            )
        if not row["readable"]:
            raise PointMapNotReadable("this estimate may not be read right now")
        report = self._read(bytes(row["content_sha256"]))
        return {
            **row,
            "declared_metric": report.metric,
            "fov_y_microdegrees": round(report.fov_y_degrees * 1_000_000),
        }

    def _read(self, content_sha256: bytes) -> OpmIntegrityReport:
        """The stored container, validated. Refuses bytes a renderer would refuse anyway."""
        if self.store is None:
            raise UnavailableAsset("point map composition requires the content-addressed store")
        try:
            data = self.store.get(BlobId(content_sha256))
        except (BlobNotFoundError, IntegrityError, OSError) as exc:
            raise PointMapNotReadable(
                "this estimate's row survived and its stored bytes did not"
            ) from exc
        try:
            return validate_opm(data)
        except OpmIntegrityError as exc:
            raise PointMapNotReadable(f"this estimate's bytes are not placeable: {exc}") from exc

    def final_authorization(self, instance: PointMapInstance) -> None:
        """Ask again under the global asset read lock, after the row is written.

        The same discipline ``EnvironmentSourceAuthority.final_authorization`` follows and the
        same one ``require_model_right`` follows before a hand-over: a withdrawal cannot commit
        while this runs, so it is either seen here or it waits, and an edit that committed against
        a permission that ended mid-transaction cannot exist.
        """
        lock_asset_reads_until_commit(
            self.connection,
            outside=(
                "a photograph's point map is authorized only inside the transaction that writes it"
            ),
        )
        self.require_current(instance)

    def require_current(self, instance: PointMapInstance) -> None:
        current = self.availability(instance)
        if current != "available":
            raise PointMapNotPermitted(f"this estimate cannot be used right now ({current})")

    def availability(self, instance: PointMapInstance) -> str:
        return self.state(instance)[0]

    def state(self, instance: PointMapInstance) -> tuple[str, str | None]:
        """Why a placed estimate can or cannot be drawn, computed now and never stored.

        Every branch names a state a person can act on. ``withdrawn`` carries which end of
        permission it was, because a stopped right, an expired review, a deleted photograph and a
        withdrawn person are four different situations with four different recoveries.
        """
        source = instance.source
        row = self.connection.execute(
            """
            select personal_model_right_allows(%(w)s,r.right_id,r.capture_id,r.model_provider,
                     r.model_role,r.model_id,r.model_revision,r.destination,
                     statement_timestamp()) as right_stands,
                   r.withdrawn_at is not null as right_withdrawn,
                   asset_point_allows(%(w)s,%(artifact)s,statement_timestamp()) as readable,
                   asset_capture_live(%(w)s,%(capture)s,statement_timestamp()) as source_live,
                   (select c.deleted_at is null from capture c
                     where c.workspace_id=%(w)s and c.capture_id=%(capture)s) as capture_present,
                   asset_screening_allows(%(w)s,%(capture)s,%(screening)s,statement_timestamp())
                     as review_stands,
                   (select cur.attachment_id from saved_world_source_current_membership cur
                     where cur.workspace_id=%(w)s and cur.entry_id=%(entry)s
                       and cur.capture_id=%(capture)s) as current_attachment_id
              from personal_model_right r
             where r.workspace_id=%(w)s and r.right_id=%(right)s
            """,
            {
                "w": self.workspace_id,
                "right": source.right_id,
                "capture": source.capture_id,
                "artifact": source.artifact_id,
                "screening": source.screening_id,
                "entry": source.entry_id,
            },
        ).fetchone()
        if not row["capture_present"] or not row["source_live"]:
            return "withdrawn", "source_deleted"
        if row["right_withdrawn"] or not row["right_stands"]:
            return "withdrawn", "model_right_withdrawn"
        if not row["review_stands"]:
            return "withdrawn", "review_expired"
        if row["current_attachment_id"] != source.attachment_id:
            # DETACHED, and rebinding never brings this back. A later attachment is a new
            # membership under a new review, and the placement pins the one it was made through.
            return "detached", None
        if not row["readable"]:
            # The permission terms above all stood, so what is left is the bytes or a person
            # whose likeness was withdrawn from this derivative.
            return "unavailable_bytes", None
        if self.store is not None and not self.store.exists(
            BlobId.from_hex(source.point_map_sha256)
        ):
            return "unavailable_bytes", None
        return "available", None
