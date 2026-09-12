"""Persistence and fail-closed reads for admitted environment resources."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.db.session import set_workspace
from exulanica.environment.admission import (
    DerivedEnvironmentAsset,
    EnvironmentOperation,
    OperationRights,
    SourceAdmission,
    derived_receipt,
    source_receipt,
)
from exulanica.errors import ExulanicaError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import final_check
from exulanica.store.base import ContentAddressedStore, PutResult

ResourceKind = Literal["source", "asset"]


class UnknownEnvironmentResource(ExulanicaError):
    pass


class EnvironmentOperationDenied(ExulanicaError):
    pass


class EnvironmentResourceWithdrawn(ExulanicaError):
    pass


class SourceDigestMismatch(IntegrityError):
    pass


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

    def admit_source(self, value: SourceAdmission, *, actor: uuid.UUID) -> EnvironmentResource:
        stored = self._store_exact(
            value.local_path, value.expected_sha256, value.expected_byte_size
        )
        place = self.connection.execute(
            "select 1 from place where workspace_id=%s and place_id=%s",
            (self.workspace_id, value.place_id),
        ).fetchone()
        if place is None:
            raise UnknownEnvironmentResource("no such place")
        record, encoded, receipt_digest = source_receipt(value)
        with self.connection.transaction():
            self.connection.execute(
                """
                insert into environment_source_admission(
                  workspace_id,admission_id,place_id,provider_key,provider_original_id,
                  provider_revision,source_sha256,source_path,member_path,media_type,byte_size,
                  geographic_frame,geographic_bounds,operation_rights,attribution,
                  modification_notice,receipt_record,receipt_canonical,receipt_sha256,admitted_by)
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
                    stored.blob_id.digest,
                    value.source_path,
                    value.member_path,
                    value.media_type,
                    stored.byte_size,
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
        stored = self._store_exact(
            value.local_path, value.expected_sha256, value.expected_byte_size
        )
        source_hex = bytes(source["source_sha256"]).hex()
        record, encoded, receipt_digest = derived_receipt(value, source_sha256=source_hex)
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
                    stored.blob_id.digest,
                    value.source_member_path,
                    value.media_type,
                    stored.byte_size,
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
        return self.read_metadata("asset", value.asset_id, EnvironmentOperation.PERSIST)

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
    ) -> bytes:
        row = self._authorized_row(kind, resource_id, operation)
        digest = bytes(row["content_sha256"])
        data = self.store.get(BlobId(digest))
        if len(data) != row["byte_size"]:
            raise IntegrityError(
                f"stored environment bytes have size {len(data)}, expected {row['byte_size']}"
            )
        with final_check(self.connection) as at:
            current = self._row(kind, resource_id, operation, at=at)
            self._require_current(row, current, operation)
        return data

    def set_rights(
        self, kind: ResourceKind, resource_id: uuid.UUID, rights: OperationRights
    ) -> None:
        table, id_column = self._table(kind)
        result = self.connection.execute(
            f"update {table} set operation_rights=%s "
            f"where workspace_id=%s and {id_column}=%s and withdrawn_at is null",
            (Jsonb(rights.model_dump(mode="json")), self.workspace_id, resource_id),
        )
        if result.rowcount != 1:
            raise UnknownEnvironmentResource("no such environment resource")

    def withdraw(self, kind: ResourceKind, resource_id: uuid.UUID) -> None:
        table, id_column = self._table(kind)
        result = self.connection.execute(
            f"update {table} set withdrawn_at=coalesce(withdrawn_at,statement_timestamp()) "
            f"where workspace_id=%s and {id_column}=%s",
            (self.workspace_id, resource_id),
        )
        if result.rowcount != 1:
            raise UnknownEnvironmentResource("no such environment resource")

    def _store_exact(self, path: Path, expected_hex: str, expected_size: int) -> PutResult:
        actual = BlobId.of_file(path)
        size = path.stat().st_size
        if actual.hex != expected_hex or size != expected_size:
            raise SourceDigestMismatch(
                f"local bytes are sha256 {actual.hex} and size {size}; "
                f"expected {expected_hex} and {expected_size}"
            )
        stored = self.store.put_file(path)
        if stored.blob_id != actual or stored.byte_size != size:
            raise SourceDigestMismatch("stored bytes do not match the verified local file")
        return stored

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
        timestamp = at or self.connection.execute(
            "select statement_timestamp() as at"
        ).fetchone()["at"]
        if kind == "source":
            return self.connection.execute(
                """
                select receipt_record,receipt_sha256,operation_rights,withdrawn_at,
                       null::timestamptz as source_withdrawn_at,
                       source_sha256 as content_sha256,byte_size,
                       environment_resource_allows(%s,'source',admission_id,%s,%s) as allowed
                from environment_source_admission
                where workspace_id=%s and admission_id=%s
                """,
                (self.workspace_id, operation.value, timestamp, self.workspace_id, resource_id),
            ).fetchone()
        return self.connection.execute(
            """
            select a.receipt_record,a.receipt_sha256,a.operation_rights,a.withdrawn_at,
                   s.withdrawn_at as source_withdrawn_at,a.content_sha256,a.byte_size,
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
