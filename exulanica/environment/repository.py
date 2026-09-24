"""Persistence and fail-closed reads for admitted environment resources."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.session import set_workspace
from exulanica.environment.admission import (
    MAX_ENVIRONMENT_PAYLOAD_BYTES,
    PLACE_SOURCE_FRAME_PROFILE,
    DeclaredPlaceFrame,
    DerivedEnvironmentAsset,
    EnvironmentOperation,
    GeographicBounds,
    GeographicFrame,
    SourceAdmission,
    derived_receipt,
    place_frame_receipt,
    source_receipt,
)
from exulanica.environment.feature_index import (
    FEATURE_INDEX_DERIVATION,
    EnvironmentFeatureKind,
    FeatureIndexPublication,
    build_feature_index,
    filter_features,
    validate_feature_index,
)
from exulanica.errors import ExulanicaError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import final_check
from exulanica.ingest.spine import places
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.store.base import ContentAddressedStore

ResourceKind = Literal["source", "asset"]


class UnknownEnvironmentResource(ExulanicaError):
    pass


class EnvironmentOperationDenied(ExulanicaError):
    pass


class EnvironmentResourceWithdrawn(ExulanicaError):
    pass


class SourceDigestMismatch(IntegrityError):
    pass


class EnvironmentPayloadTooLarge(ExulanicaError):
    pass


class EnvironmentAdmissionRefused(ExulanicaError):
    """The database refused the write, and its own sentence is the reason.

    Raised rather than translated because the refusals behind it live in 0091's triggers and
    check constraints, which are the authority. A second copy of each rule here, phrased
    differently, would be a second place for the rule to be right or wrong.
    """


class DuplicateEnvironmentSource(ExulanicaError):
    """This provider revision is already admitted in this workspace."""


class PlaceFrameConflict(ExulanicaError):
    """This place already declared a different frame, and a declaration cannot be corrected."""


@dataclass(frozen=True, slots=True)
class EnvironmentResource:
    kind: ResourceKind
    resource_id: uuid.UUID
    receipt: dict[str, Any]
    receipt_sha256: str
    operation_rights: dict[str, bool]

    def document(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "resource_id": str(self.resource_id),
            "receipt": self.receipt,
            "receipt_sha256": self.receipt_sha256,
            "operation_rights": self.operation_rights,
        }


@dataclass(frozen=True, slots=True)
class AuthorizedEnvironmentBytes:
    data: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class EnvironmentFeatureCatalog:
    publication_id: uuid.UUID
    admission_id: uuid.UUID
    provider_key: str
    place_id: uuid.UUID
    index_asset_id: uuid.UUID
    render_asset_id: uuid.UUID
    geographic_frame: dict[str, Any]
    coordinate_scale: int
    receipt: dict[str, Any]
    receipt_sha256: str
    features: tuple[dict[str, Any], ...]

    def document(self) -> dict[str, Any]:
        return {
            "publication_id": str(self.publication_id),
            "admission_id": str(self.admission_id),
            "place_id": str(self.place_id),
            "index_asset_id": str(self.index_asset_id),
            "render_asset_id": str(self.render_asset_id),
            "geographic_frame": self.geographic_frame,
            "coordinate_scale": self.coordinate_scale,
            "receipt": self.receipt,
            "receipt_sha256": self.receipt_sha256,
            "features": list(self.features),
        }


@dataclass(frozen=True, slots=True)
class DeclaredPlace:
    """One place whose frame came from a provider's documentation."""

    place_id: uuid.UUID
    frame_authority: str
    provider_key: str
    provider_frame_statement: str
    geographic_frame: dict[str, Any]
    geographic_bounds: dict[str, Any]
    receipt: dict[str, Any]
    receipt_sha256: str

    def document(self) -> dict[str, Any]:
        return {
            "place_id": str(self.place_id),
            "frame_authority": self.frame_authority,
            "provider_key": self.provider_key,
            "provider_frame_statement": self.provider_frame_statement,
            "geographic_frame": self.geographic_frame,
            "geographic_bounds": self.geographic_bounds,
            "receipt": self.receipt,
            "receipt_sha256": self.receipt_sha256,
        }


def _refusal(exc: psycopg.Error) -> str:
    return exc.diag.message_primary or str(exc).strip()


class EnvironmentRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        store: ContentAddressedStore,
    ) -> None:
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)
        self.connection = connection
        self.workspace_id = workspace_id
        self.store = store

    def declare_place_frame(self, value: DeclaredPlaceFrame, *, actor: uuid.UUID) -> DeclaredPlace:
        """Create a place whose frame a provider documented, and declare that frame.

        The product's other way to make a place binds an anchor SCENE whose recovered frame the
        place adopts. A geography admitted from a provider has no photographs behind it, so it
        has no anchor scene and, before 0091, no way to exist at all. This writes the other
        authority and says in a column which one it is.

        Repeating the same declaration is the same declaration: a retried request returns the
        stored row rather than a conflict. Declaring a *different* frame for one place is
        refused, because a place's declared frame is what that place is, and correcting it names
        a different place.
        """
        scope = WorkspaceScope(self.connection, self.workspace_id)
        record, encoded, receipt_digest = place_frame_receipt(value)
        stored = places.source_frame(scope, place_id=value.place_id)
        if stored is not None:
            if stored.receipt_sha256 != receipt_digest:
                raise PlaceFrameConflict(
                    f"place {value.place_id} already declared a different frame"
                )
            return self._declared(stored)
        try:
            with self.connection.transaction():
                places.insert_place(scope, place_id=value.place_id)
                places.insert_source_frame(
                    scope,
                    place_id=value.place_id,
                    profile=PLACE_SOURCE_FRAME_PROFILE,
                    frame_authority=value.frame_authority,
                    provider_key=value.provider_key,
                    provider_frame_statement=value.provider_frame_statement,
                    geographic_frame=value.geographic_frame.model_dump(mode="json"),
                    geographic_bounds=value.geographic_bounds.model_dump(mode="json"),
                    receipt_record=record,
                    receipt_canonical=encoded,
                    receipt_sha256=receipt_digest,
                    declared_by=actor,
                )
        except psycopg.errors.UniqueViolation as exc:
            # A declaration of the same place in this workspace reached the insert first. A place
            # id is unique within its workspace (migration 0102), so no other workspace's place
            # can collide with it here, and the sentence names only the identifier asked for.
            raise PlaceFrameConflict(
                f"place {value.place_id} cannot be declared under this identifier"
            ) from exc
        except psycopg.errors.IntegrityError as exc:
            raise EnvironmentAdmissionRefused(_refusal(exc)) from exc
        written = places.source_frame(scope, place_id=value.place_id)
        if written is None:
            raise IntegrityError("the declared place frame was not stored")
        return self._declared(written)

    def declared_place(self, place_id: uuid.UUID) -> DeclaredPlace:
        """Read back what a place declared, so a later reader can tell declared from measured.

        Raises rather than returning None for a place that declared nothing, because the two
        answers a caller needs are "this place's frame is a provider's statement" and "there is
        no such declaration here"; a null would leave them to guess which.
        """
        stored = places.source_frame(
            WorkspaceScope(self.connection, self.workspace_id), place_id=place_id
        )
        if stored is None:
            raise UnknownEnvironmentResource("no such declared place frame")
        return self._declared(stored)

    def admit_source(self, value: SourceAdmission, *, actor: uuid.UUID) -> EnvironmentResource:
        """Admit one exact local file as a reusable environment source.

        **Nothing reaches the content-addressed store until every refusal is past.** The bytes
        are verified against the declared digest and size first, which needs no store, then the
        row is written, and only then are the bytes put. A refused admission therefore leaves
        nothing behind: no row, and no blob under a digest nothing references. Ordering the put
        after the insert rather than before a list of Python pre-checks is what makes that true
        of refusals nobody has written yet, including the ones 0091's triggers raise and any a
        later migration adds.
        """
        blob_id, byte_size = self._verified_bytes(
            value.local_path, value.expected_sha256, value.expected_byte_size
        )
        place = self.connection.execute(
            "select 1 from place where workspace_id=%s and place_id=%s",
            (self.workspace_id, value.place_id),
        ).fetchone()
        if place is None:
            raise UnknownEnvironmentResource("no such place")
        record, encoded, receipt_digest = source_receipt(value)
        try:
            with self.connection.transaction():
                self.connection.execute(
                    """
                    insert into environment_source_admission(
                      workspace_id,admission_id,place_id,provider_key,provider_original_id,
                      provider_revision,source_sha256,source_path,member_path,media_type,
                      byte_size,geographic_frame,geographic_bounds,operation_rights,attribution,
                      modification_notice,receipt_record,receipt_canonical,receipt_sha256,
                      admitted_by)
                    values(
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        self.workspace_id,
                        value.admission_id,
                        value.place_id,
                        value.provider_key,
                        value.provider_original_id,
                        value.provider_revision,
                        blob_id.digest,
                        value.source_path,
                        value.member_path,
                        value.media_type,
                        byte_size,
                        Jsonb(value.geographic_frame.model_dump(mode="json")),
                        Jsonb(value.geographic_bounds.model_dump(mode="json")),
                        Jsonb(value.operation_rights.model_dump(mode="json")),
                        value.attribution,
                        value.modification_notice,
                        Jsonb(record),
                        encoded,
                        receipt_digest,
                        actor,
                    ),
                )
                self._put_verified(value.local_path, blob_id, byte_size)
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateEnvironmentSource(_refusal(exc)) from exc
        except psycopg.errors.IntegrityError as exc:
            raise EnvironmentAdmissionRefused(_refusal(exc)) from exc
        return self.read_metadata("source", value.admission_id, EnvironmentOperation.PERSIST)

    def register_derived(
        self, value: DerivedEnvironmentAsset, *, actor: uuid.UUID
    ) -> EnvironmentResource:
        source = self.connection.execute(
            "select source_sha256 from environment_source_admission "
            "where workspace_id=%s and admission_id=%s and withdrawn_at is null",
            (self.workspace_id, value.admission_id),
        ).fetchone()
        if source is None:
            raise UnknownEnvironmentResource("no such environment source")
        if value.parent_asset_id is not None:
            parent = self.connection.execute(
                "select 1 from derived_environment_asset "
                "where workspace_id=%s and asset_id=%s and admission_id=%s "
                "and withdrawn_at is null",
                (self.workspace_id, value.parent_asset_id, value.admission_id),
            ).fetchone()
            if parent is None:
                raise UnknownEnvironmentResource("no such parent environment asset")
        blob_id, byte_size = self._verified_bytes(
            value.local_path, value.expected_sha256, value.expected_byte_size
        )
        source_hex = bytes(source["source_sha256"]).hex()
        record, encoded, receipt_digest = derived_receipt(value, source_sha256=source_hex)
        try:
            with self.connection.transaction():
                self.connection.execute(
                    """
                    insert into derived_environment_asset(
                      workspace_id,asset_id,admission_id,parent_asset_id,source_sha256,
                      content_sha256,source_member_path,media_type,byte_size,derivation_kind,
                      derivation_lineage,geographic_frame,geographic_bounds,operation_rights,
                      attribution,modification_notice,receipt_record,receipt_canonical,
                      receipt_sha256,created_by)
                    values(
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        self.workspace_id,
                        value.asset_id,
                        value.admission_id,
                        value.parent_asset_id,
                        source["source_sha256"],
                        blob_id.digest,
                        value.source_member_path,
                        value.media_type,
                        byte_size,
                        value.derivation_kind,
                        Jsonb(value.derivation_lineage),
                        Jsonb(value.geographic_frame.model_dump(mode="json")),
                        Jsonb(value.geographic_bounds.model_dump(mode="json")),
                        Jsonb(value.operation_rights.model_dump(mode="json")),
                        value.attribution,
                        value.modification_notice,
                        Jsonb(record),
                        encoded,
                        receipt_digest,
                        actor,
                    ),
                )
                self._put_verified(value.local_path, blob_id, byte_size)
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateEnvironmentSource(_refusal(exc)) from exc
        except psycopg.errors.IntegrityError as exc:
            raise EnvironmentAdmissionRefused(_refusal(exc)) from exc
        return self.read_metadata("asset", value.asset_id, EnvironmentOperation.PERSIST)

    def publish_feature_index(
        self,
        admission_id: uuid.UUID,
        value: FeatureIndexPublication,
        *,
        actor: uuid.UUID,
    ) -> EnvironmentFeatureCatalog:
        self._authorized_row("source", admission_id, EnvironmentOperation.INDEX)
        self._authorized_row("asset", value.render_asset_id, EnvironmentOperation.INDEX)
        source_record = self.connection.execute(
            """
            select place_id,provider_key,provider_original_id,provider_revision,source_sha256,
                   receipt_sha256,geographic_frame,geographic_bounds,operation_rights,
                   attribution
              from environment_source_admission
             where workspace_id=%s and admission_id=%s
            """,
            (self.workspace_id, admission_id),
        ).fetchone()
        render_record = self.connection.execute(
            """
            select admission_id,content_sha256,receipt_sha256,operation_rights
              from derived_environment_asset
             where workspace_id=%s and asset_id=%s
            """,
            (self.workspace_id, value.render_asset_id),
        ).fetchone()
        if (
            source_record is None
            or render_record is None
            or render_record["admission_id"] != admission_id
        ):
            raise UnknownEnvironmentResource("no such environment resource")

        source_hex = bytes(source_record["source_sha256"]).hex()
        render_hex = bytes(render_record["content_sha256"]).hex()
        source_receipt_hex = bytes(source_record["receipt_sha256"]).hex()
        render_receipt_hex = bytes(render_record["receipt_sha256"]).hex()
        frame = source_record["geographic_frame"]
        bounds = source_record["geographic_bounds"]
        data = build_feature_index(
            value,
            admission_id=admission_id,
            place_id=source_record["place_id"],
            provider_key=source_record["provider_key"],
            provider_original_id=source_record["provider_original_id"],
            provider_revision=source_record["provider_revision"],
            source_sha256=source_hex,
            source_receipt_sha256=source_receipt_hex,
            render_sha256=render_hex,
            render_receipt_sha256=render_receipt_hex,
            geographic_frame=self._frame(frame),
            geographic_bounds=self._bounds(bounds),
        )
        projected = validate_feature_index(
            data,
            admission_id=admission_id,
            place_id=source_record["place_id"],
            source_sha256=source_hex,
            source_receipt_sha256=source_receipt_hex,
            render_asset_id=value.render_asset_id,
            render_sha256=render_hex,
            render_receipt_sha256=render_receipt_hex,
        )
        stored = self.store.put_bytes(data)
        rights = {
            operation.value: bool(
                source_record["operation_rights"][operation.value]
                and render_record["operation_rights"][operation.value]
            )
            for operation in EnvironmentOperation
        }
        index_asset = DerivedEnvironmentAsset(
            admission_id=admission_id,
            parent_asset_id=value.render_asset_id,
            expected_sha256=stored.blob_id.hex,
            expected_byte_size=stored.byte_size,
            media_type="application/vnd.exulanica.environment-feature-index+json",
            derivation_kind=FEATURE_INDEX_DERIVATION,
            derivation_lineage={
                "method": "exulanica.environment-feature-index/v2",
                "input_sha256": [source_hex, render_hex],
            },
            geographic_frame=self._frame(frame),
            geographic_bounds=self._bounds(bounds),
            operation_rights=rights,
            attribution=source_record["attribution"],
            modification_notice="Generated feature catalog; source and render bytes are unchanged.",
            local_path=Path("<generated-environment-feature-index>"),
        )
        index_record, index_encoded, index_receipt_digest = derived_receipt(
            index_asset, source_sha256=source_hex
        )
        publication_record = {
            "profile": "exulanica.environment-feature-index-publication/v1",
            "publication_id": str(value.publication_id),
            "admission_id": str(admission_id),
            "index_asset_id": str(index_asset.asset_id),
            "render_asset_id": str(value.render_asset_id),
            "source_sha256": source_hex,
            "source_receipt_sha256": source_receipt_hex,
            "index_sha256": stored.blob_id.hex,
            "index_receipt_sha256": index_receipt_digest.hex(),
            "render_sha256": render_hex,
            "render_receipt_sha256": render_receipt_hex,
        }
        publication_encoded = canonical_json(publication_record)
        publication_digest = hashlib.sha256(publication_encoded).digest()
        with self.connection.transaction():
            self.connection.execute(
                """
                insert into derived_environment_asset(
                  workspace_id,asset_id,admission_id,parent_asset_id,source_sha256,
                  content_sha256,media_type,byte_size,derivation_kind,derivation_lineage,
                  geographic_frame,geographic_bounds,operation_rights,attribution,
                  modification_notice,receipt_record,receipt_canonical,receipt_sha256,created_by)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    self.workspace_id,
                    index_asset.asset_id,
                    admission_id,
                    value.render_asset_id,
                    source_record["source_sha256"],
                    stored.blob_id.digest,
                    index_asset.media_type,
                    stored.byte_size,
                    index_asset.derivation_kind,
                    Jsonb(index_asset.derivation_lineage),
                    Jsonb(frame),
                    Jsonb(bounds),
                    Jsonb(rights),
                    index_asset.attribution,
                    index_asset.modification_notice,
                    Jsonb(index_record),
                    index_encoded,
                    index_receipt_digest,
                    actor,
                ),
            )
            self.connection.execute(
                """
                insert into environment_feature_index_publication(
                  workspace_id,publication_id,admission_id,index_asset_id,render_asset_id,
                  source_sha256,source_receipt_sha256,index_sha256,index_receipt_sha256,
                  render_sha256,render_receipt_sha256,receipt_record,receipt_canonical,
                  receipt_sha256,published_by)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    self.workspace_id,
                    value.publication_id,
                    admission_id,
                    index_asset.asset_id,
                    value.render_asset_id,
                    source_record["source_sha256"],
                    source_record["receipt_sha256"],
                    stored.blob_id.digest,
                    index_receipt_digest,
                    render_record["content_sha256"],
                    render_record["receipt_sha256"],
                    Jsonb(publication_record),
                    publication_encoded,
                    publication_digest,
                    actor,
                ),
            )
            for feature in projected["features"]:
                self.connection.execute(
                    """
                    insert into environment_feature_index_entry(
                      workspace_id,publication_id,admission_id,place_id,feature_id,
                      provider_feature_id,feature_kind,label,render_batch_id,bbox)
                    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        self.workspace_id,
                        value.publication_id,
                        admission_id,
                        source_record["place_id"],
                        feature["id"],
                        feature["provider_feature_id"],
                        feature["kind"],
                        feature["label"],
                        feature["render_batch_id"],
                        Jsonb(feature["bbox"]),
                    ),
                )
        return self.read_features(admission_id)

    def read_features(
        self,
        admission_id: uuid.UUID,
        *,
        feature_id: str | None = None,
        kind: EnvironmentFeatureKind | None = None,
        bbox: tuple[int, ...] | None = None,
        label: str | None = None,
    ) -> EnvironmentFeatureCatalog:
        row = self._authorized_publication(admission_id)
        data = self.store.get(BlobId(bytes(row["index_sha256"])))
        try:
            payload = validate_feature_index(
                data,
                admission_id=admission_id,
                place_id=row["place_id"],
                source_sha256=bytes(row["source_sha256"]).hex(),
                source_receipt_sha256=bytes(row["source_receipt_sha256"]).hex(),
                render_asset_id=row["render_asset_id"],
                render_sha256=bytes(row["render_sha256"]).hex(),
                render_receipt_sha256=bytes(row["render_receipt_sha256"]).hex(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"stored environment feature index is invalid: {exc}") from exc
        selected = filter_features(
            payload["features"],
            feature_id=feature_id,
            kind=kind,
            bbox=bbox,
            label=label,
            dimensions=len(payload["geographic_frame"]["axis_order"]),
        )
        with final_check(self.connection) as at:
            current = self._publication_row(admission_id, at=at)
            self._require_publication_current(row, current)
        return EnvironmentFeatureCatalog(
            publication_id=row["publication_id"],
            admission_id=admission_id,
            provider_key=row["provider_key"],
            place_id=row["place_id"],
            index_asset_id=row["index_asset_id"],
            render_asset_id=row["render_asset_id"],
            geographic_frame=payload["geographic_frame"],
            coordinate_scale=payload["coordinate_scale"],
            receipt=row["publication_receipt"],
            receipt_sha256=bytes(row["publication_receipt_sha256"]).hex(),
            features=tuple(selected),
        )

    def read_metadata(
        self, kind: ResourceKind, resource_id: uuid.UUID, operation: EnvironmentOperation
    ) -> EnvironmentResource:
        row = self._authorized_row(kind, resource_id, operation)
        resource = self._resource(kind, resource_id, row)
        with final_check(self.connection) as at:
            current = self._row(kind, resource_id, operation, at=at)
            self._require_current(row, current, operation)
        return resource

    def read_bytes(
        self, kind: ResourceKind, resource_id: uuid.UUID, operation: EnvironmentOperation
    ) -> AuthorizedEnvironmentBytes:
        row = self._authorized_row(kind, resource_id, operation)
        if row["byte_size"] > MAX_ENVIRONMENT_PAYLOAD_BYTES:
            raise IntegrityError(
                f"environment row declares {row['byte_size']} bytes; buffered reads permit at most "
                f"{MAX_ENVIRONMENT_PAYLOAD_BYTES}"
            )
        digest = bytes(row["content_sha256"])
        data = self.store.get(BlobId(digest))
        if len(data) != row["byte_size"]:
            raise IntegrityError(
                f"stored environment bytes have size {len(data)}, expected {row['byte_size']}"
            )
        with final_check(self.connection) as at:
            current = self._row(kind, resource_id, operation, at=at)
            self._require_current(row, current, operation)
        return AuthorizedEnvironmentBytes(data=data, media_type=row["media_type"])

    def withdraw(self, kind: ResourceKind, resource_id: uuid.UUID) -> None:
        table, id_column = self._table(kind)
        result = self.connection.execute(
            f"update {table} set withdrawn_at=coalesce(withdrawn_at,statement_timestamp()) "
            f"where workspace_id=%s and {id_column}=%s",
            (self.workspace_id, resource_id),
        )
        if result.rowcount != 1:
            raise UnknownEnvironmentResource("no such environment resource")

    def _verified_bytes(
        self, path: Path, expected_hex: str, expected_size: int
    ) -> tuple[BlobId, int]:
        """Check a local file against what the request declared. Writes nothing anywhere.

        Separate from :meth:`_put_verified` so that everything a refusal needs to know is known
        before anything is stored. Both digest and size are checked, because a file whose bytes
        hash as promised and whose length does not is a file the caller does not have.
        """
        size = path.stat().st_size
        if size > MAX_ENVIRONMENT_PAYLOAD_BYTES or expected_size > MAX_ENVIRONMENT_PAYLOAD_BYTES:
            raise EnvironmentPayloadTooLarge(
                f"buffered environment payloads permit at most "
                f"{MAX_ENVIRONMENT_PAYLOAD_BYTES} bytes"
            )
        actual = BlobId.of_file(path)
        if actual.hex != expected_hex or size != expected_size:
            raise SourceDigestMismatch(
                f"local bytes are sha256 {actual.hex} and size {size}; "
                f"expected {expected_hex} and {expected_size}"
            )
        return actual, size

    def _put_verified(self, path: Path, blob_id: BlobId, byte_size: int) -> None:
        """Store bytes that :meth:`_verified_bytes` already accepted, inside the write.

        Called last, after the row is written, so that a refusal at any depth of the database
        leaves the store untouched. A file that changed between the two calls is a mismatch, not
        a silent substitution.
        """
        stored = self.store.put_file(path)
        if stored.blob_id != blob_id or stored.byte_size != byte_size:
            raise SourceDigestMismatch("stored bytes do not match the verified local file")

    @staticmethod
    def _declared(row: places.PlaceSourceFrameRow) -> DeclaredPlace:
        return DeclaredPlace(
            place_id=row.place_id,
            frame_authority=row.frame_authority,
            provider_key=row.provider_key,
            provider_frame_statement=row.provider_frame_statement,
            geographic_frame=row.geographic_frame,
            geographic_bounds=row.geographic_bounds,
            receipt=row.receipt_record,
            receipt_sha256=row.receipt_sha256.hex(),
        )

    def _authorized_row(
        self, kind: ResourceKind, resource_id: uuid.UUID, operation: EnvironmentOperation
    ) -> dict[str, Any]:
        row = self._row(kind, resource_id, operation)
        if row is None:
            raise UnknownEnvironmentResource("no such environment resource")
        if row["withdrawn_at"] is not None or row["source_withdrawn_at"] is not None:
            raise EnvironmentResourceWithdrawn("environment resource was withdrawn")
        if not row["allowed"]:
            raise EnvironmentOperationDenied(f"{operation.value} is not permitted")
        return row

    def _row(
        self,
        kind: ResourceKind,
        resource_id: uuid.UUID,
        operation: EnvironmentOperation,
        *,
        at: Any | None = None,
    ) -> dict[str, Any] | None:
        timestamp = (
            at or self.connection.execute("select statement_timestamp() as at").fetchone()["at"]
        )
        if kind == "source":
            return self.connection.execute(
                """
                select receipt_record,receipt_sha256,operation_rights,withdrawn_at,
                       null::timestamptz as source_withdrawn_at,
                       source_sha256 as content_sha256,byte_size,media_type,
                       environment_resource_allows(%s,'source',admission_id,%s,%s) as allowed
                from environment_source_admission
                where workspace_id=%s and admission_id=%s
                """,
                (self.workspace_id, operation.value, timestamp, self.workspace_id, resource_id),
            ).fetchone()
        return self.connection.execute(
            """
            select a.receipt_record,a.receipt_sha256,a.operation_rights,a.withdrawn_at,
                   s.withdrawn_at as source_withdrawn_at,a.content_sha256,a.byte_size,a.media_type,
                   environment_resource_allows(%s,'asset',a.asset_id,%s,%s) as allowed
            from derived_environment_asset a
            join environment_source_admission s
              on s.workspace_id=a.workspace_id and s.admission_id=a.admission_id
            where a.workspace_id=%s and a.asset_id=%s
            """,
            (self.workspace_id, operation.value, timestamp, self.workspace_id, resource_id),
        ).fetchone()

    def _require_current(
        self,
        buffered: dict[str, Any],
        current: dict[str, Any] | None,
        operation: EnvironmentOperation,
    ) -> None:
        if current is None:
            raise UnknownEnvironmentResource("environment resource became unavailable")
        if current["withdrawn_at"] is not None or current["source_withdrawn_at"] is not None:
            raise EnvironmentResourceWithdrawn("environment resource was withdrawn")
        if not current["allowed"]:
            raise EnvironmentOperationDenied(f"{operation.value} is not permitted")
        for key in ("receipt_sha256", "content_sha256", "byte_size", "operation_rights"):
            if current[key] != buffered[key]:
                raise EnvironmentOperationDenied("environment resource changed during read")

    def _authorized_publication(self, admission_id: uuid.UUID) -> dict[str, Any]:
        row = self._publication_row(admission_id)
        if row is None:
            raise UnknownEnvironmentResource("no such environment feature index")
        if any(
            row[key] is not None
            for key in ("source_withdrawn_at", "index_withdrawn_at", "render_withdrawn_at")
        ):
            raise EnvironmentResourceWithdrawn("environment feature index was withdrawn")
        if not row["source_allowed"] or not row["index_allowed"] or not row["render_allowed"]:
            raise EnvironmentOperationDenied("index is not permitted")
        self._require_publication_bindings(row)
        return row

    def _publication_row(
        self, admission_id: uuid.UUID, *, at: Any | None = None
    ) -> dict[str, Any] | None:
        timestamp = (
            at or self.connection.execute("select statement_timestamp() as at").fetchone()["at"]
        )
        return self.connection.execute(
            """
            select p.publication_id,p.admission_id,s.provider_key,s.place_id,
                   p.index_asset_id,p.render_asset_id,
                   p.source_sha256,p.source_receipt_sha256,p.index_sha256,
                   p.index_receipt_sha256,p.render_sha256,p.render_receipt_sha256,
                   p.receipt_record as publication_receipt,
                   p.receipt_sha256 as publication_receipt_sha256,
                   s.source_sha256 as live_source_sha256,
                   s.receipt_sha256 as live_source_receipt_sha256,
                   i.content_sha256 as live_index_sha256,
                   i.receipt_sha256 as live_index_receipt_sha256,
                   r.content_sha256 as live_render_sha256,
                   r.receipt_sha256 as live_render_receipt_sha256,
                   s.withdrawn_at as source_withdrawn_at,
                   i.withdrawn_at as index_withdrawn_at,
                   r.withdrawn_at as render_withdrawn_at,
                   environment_resource_allows(
                     %s,'source',p.admission_id,'index',%s) as source_allowed,
                   environment_resource_allows(
                     %s,'asset',p.index_asset_id,'index',%s) as index_allowed,
                   environment_resource_allows(
                     %s,'asset',p.render_asset_id,'index',%s) as render_allowed
              from environment_feature_index_publication p
              join environment_source_admission s
                on s.workspace_id=p.workspace_id and s.admission_id=p.admission_id
              join derived_environment_asset i
                on i.workspace_id=p.workspace_id and i.asset_id=p.index_asset_id
              join derived_environment_asset r
                on r.workspace_id=p.workspace_id and r.asset_id=p.render_asset_id
             where p.workspace_id=%s and p.admission_id=%s
             order by p.published_at desc,p.publication_id desc
             limit 1
            """,
            (
                self.workspace_id,
                timestamp,
                self.workspace_id,
                timestamp,
                self.workspace_id,
                timestamp,
                self.workspace_id,
                admission_id,
            ),
        ).fetchone()

    def _require_publication_current(
        self, buffered: dict[str, Any], current: dict[str, Any] | None
    ) -> None:
        if current is None:
            raise UnknownEnvironmentResource("environment feature index became unavailable")
        if any(
            current[key] is not None
            for key in ("source_withdrawn_at", "index_withdrawn_at", "render_withdrawn_at")
        ):
            raise EnvironmentResourceWithdrawn("environment feature index was withdrawn")
        if not all(current[key] for key in ("source_allowed", "index_allowed", "render_allowed")):
            raise EnvironmentOperationDenied("index is not permitted")
        self._require_publication_bindings(current)
        for key in (
            "publication_id",
            "index_asset_id",
            "render_asset_id",
            "source_sha256",
            "source_receipt_sha256",
            "index_sha256",
            "index_receipt_sha256",
            "render_sha256",
            "render_receipt_sha256",
            "publication_receipt_sha256",
        ):
            if current[key] != buffered[key]:
                raise EnvironmentOperationDenied(
                    "environment feature publication changed during read"
                )

    @staticmethod
    def _require_publication_bindings(row: dict[str, Any]) -> None:
        for published, live in (
            ("source_sha256", "live_source_sha256"),
            ("source_receipt_sha256", "live_source_receipt_sha256"),
            ("index_sha256", "live_index_sha256"),
            ("index_receipt_sha256", "live_index_receipt_sha256"),
            ("render_sha256", "live_render_sha256"),
            ("render_receipt_sha256", "live_render_receipt_sha256"),
        ):
            if row[published] != row[live]:
                raise EnvironmentOperationDenied(
                    "environment feature publication digest binding changed"
                )

    @staticmethod
    def _resource(
        kind: ResourceKind, resource_id: uuid.UUID, row: dict[str, Any]
    ) -> EnvironmentResource:
        return EnvironmentResource(
            kind=kind,
            resource_id=resource_id,
            receipt=row["receipt_record"],
            receipt_sha256=bytes(row["receipt_sha256"]).hex(),
            operation_rights=row["operation_rights"],
        )

    @staticmethod
    def _table(kind: ResourceKind) -> tuple[str, str]:
        if kind == "source":
            return "environment_source_admission", "admission_id"
        if kind == "asset":
            return "derived_environment_asset", "asset_id"
        raise ValueError("environment resource kind must be source or asset")

    @staticmethod
    def _frame(value: dict[str, Any]) -> GeographicFrame:
        return GeographicFrame.model_validate(value)

    @staticmethod
    def _bounds(value: dict[str, Any]) -> GeographicBounds:
        return GeographicBounds.model_validate(value)
