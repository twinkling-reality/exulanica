"""Whether an exact environment source may be composed into a world, asked inside an edit.

An environment instance pins one admitted source, one derived render asset and, for a feature, one
exact index publication. Whether those may be composed is a question about another plane, the
environment admission plane: its withdrawals, its operation rights and the bytes its receipts
name. This module is where that question is asked, so the object repository that writes the
instance does not also have to be the authority on environment sources.

**It never opens a transaction.** Every method runs inside the caller's, which is what makes its
answers mean something: :meth:`EnvironmentSourceAuthority.final_authorization` takes the global
asset read lock after the edit row is written, so a withdrawal either commits before it and is
seen, or waits until the edit has committed. ``tests/test_source_authorities_postgres.py`` pins
that order by the statements an edit runs and by the locks a second connection finds held.

**Refusals keep their classes.** Composition preview maps each refusal to a blocked reason by its
class, so every refusal here is the exact class it was before this module existed, raised at the
same step: missing binding, withdrawal, compose rights, bytes, publication.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg

from exulanica.canonical import canonical_json
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.environment_instances import (
    EnvironmentInstance,
    EnvironmentPlacement,
    EnvironmentSelection,
    EnvironmentSourceBinding,
)
from exulanica.world.errors import (
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentSourceWithdrawn,
    InvalidEnvironmentData,
    UnavailableAsset,
    UnknownWorldResource,
)

__all__ = ["EnvironmentSourceAuthority", "ResolvedEnvironmentSource"]


@dataclass(frozen=True, slots=True)
class ResolvedEnvironmentSource:
    """One authorized resolution of an exact environment source, before any destination.

    ``validate_environment_source`` returns it so a placement check in the same read can reuse it
    rather than resolving the source, and reading every pinned blob, a second time.
    """

    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None
    selection: EnvironmentSelection
    row: Mapping[str, Any]
    publication: Mapping[str, Any] | None
    bounds: Mapping[str, Any]

    @property
    def render_sha256(self) -> str:
        return bytes(self.row["render_sha256"]).hex()


class EnvironmentSourceAuthority:
    """One workspace's environment sources, asked on the connection an edit already holds."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        store: ContentAddressedStore | None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.store = store

    def binding(
        self,
        placement: EnvironmentPlacement,
        resolved: ResolvedEnvironmentSource | None = None,
    ) -> EnvironmentSourceBinding:
        if resolved is None:
            resolved = self.authorize(
                placement.admission_id,
                placement.render_asset_id,
                placement.publication_id,
                placement.selection,
            )
        elif (
            resolved.admission_id,
            resolved.render_asset_id,
            resolved.publication_id,
            resolved.selection,
        ) != (
            placement.admission_id,
            placement.render_asset_id,
            placement.publication_id,
            placement.selection,
        ):
            raise ValueError("the resolved source names a different binding than the placement")
        row, publication, bounds = resolved.row, resolved.publication, resolved.bounds
        return EnvironmentSourceBinding(
            admission_id=placement.admission_id,
            render_asset_id=placement.render_asset_id,
            publication_id=None if publication is None else publication["publication_id"],
            source_sha256=bytes(row["source_sha256"]).hex(),
            source_receipt_sha256=bytes(row["source_receipt_sha256"]).hex(),
            render_sha256=bytes(row["render_sha256"]).hex(),
            render_receipt_sha256=bytes(row["render_receipt_sha256"]).hex(),
            index_sha256=(
                None if publication is None else bytes(publication["index_sha256"]).hex()
            ),
            index_receipt_sha256=(
                None if publication is None else bytes(publication["index_receipt_sha256"]).hex()
            ),
            publication_receipt_sha256=(
                None
                if publication is None
                else bytes(publication["publication_receipt_sha256"]).hex()
            ),
            place_id=row["place_id"],
            frame=row["geographic_frame"],
            bounds=bounds,
            anchor=placement.source_anchor,
            selection=placement.selection,
        )

    def authorize(
        self,
        admission_id: uuid.UUID,
        render_asset_id: uuid.UUID,
        publication_id: uuid.UUID | None,
        selection: EnvironmentSelection,
    ) -> ResolvedEnvironmentSource:
        if self.store is None:
            raise UnavailableAsset("environment composition requires the content-addressed store")
        row = self.connection.execute(
            """
            select s.place_id,s.source_sha256,s.receipt_sha256 as source_receipt_sha256,
                   s.withdrawn_at as source_withdrawn_at,
                   r.content_sha256 as render_sha256,r.receipt_sha256 as render_receipt_sha256,
                   s.geographic_frame,s.geographic_bounds,
                   r.withdrawn_at as render_withdrawn_at,
                   environment_resource_allows(
                     %s,'source',s.admission_id,'compose',statement_timestamp()) source_compose,
                   environment_resource_allows(
                     %s,'asset',r.asset_id,'compose',statement_timestamp()) render_compose
              from environment_source_admission s
              join derived_environment_asset r
                on r.workspace_id=s.workspace_id and r.admission_id=s.admission_id
             where s.workspace_id=%s and s.admission_id=%s and r.asset_id=%s
            """,
            (
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                admission_id,
                render_asset_id,
            ),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such environment source and render binding")
        if row["source_withdrawn_at"] is not None or row["render_withdrawn_at"] is not None:
            raise EnvironmentSourceWithdrawn("the environment source or render asset is withdrawn")
        if not row["source_compose"] or not row["render_compose"]:
            raise EnvironmentCompositionDenied(
                "compose is not permitted for the source and render asset"
            )
        self._require_bytes(row["source_sha256"], row["render_sha256"], None)

        bounds = row["geographic_bounds"]
        publication = None
        if selection.kind == "feature":
            publication = self._current_publication(
                admission_id,
                render_asset_id,
                publication_id,
                require_rights=True,
            )
            index = self._read_feature(publication, selection.feature_id, selection.render_batch_id)
            bounds = {
                "kind": "bbox",
                "frame_name": row["geographic_frame"]["name"],
                "coordinate_scale": row["geographic_bounds"]["coordinate_scale"],
                "coordinates": index["bbox"],
            }
        elif selection.kind != "whole_asset" or publication_id is not None:
            raise InvalidEnvironmentData("whole-asset placement cannot name a publication")

        return ResolvedEnvironmentSource(
            admission_id=admission_id,
            render_asset_id=render_asset_id,
            publication_id=publication_id,
            selection=selection,
            row=row,
            publication=publication,
            bounds=bounds,
        )

    def _current_publication(
        self,
        admission_id: uuid.UUID,
        render_asset_id: uuid.UUID,
        publication_id: uuid.UUID | None,
        *,
        require_rights: bool,
    ) -> Mapping[str, Any]:
        row = self.connection.execute(
            """
            select p.publication_id,p.admission_id,p.render_asset_id,
                   p.source_sha256,p.source_receipt_sha256,
                   p.render_sha256,p.render_receipt_sha256,p.index_sha256,
                   p.index_receipt_sha256,p.receipt_sha256 as publication_receipt_sha256,
                   p.index_asset_id,i.withdrawn_at as index_withdrawn_at,
                   s.place_id,s.geographic_frame,s.geographic_bounds,
                   (select newest.publication_id
                      from environment_feature_index_publication newest
                     where newest.workspace_id=p.workspace_id
                       and newest.admission_id=p.admission_id
                     order by newest.published_at desc,newest.publication_id desc limit 1)
                     as current_publication_id,
                   environment_resource_allows(
                     %s,'source',p.admission_id,'index',statement_timestamp()) source_index,
                   environment_resource_allows(
                     %s,'asset',p.render_asset_id,'index',statement_timestamp()) render_index,
                   environment_resource_allows(
                     %s,'asset',p.index_asset_id,'index',statement_timestamp()) index_index,
                   environment_resource_allows(
                     %s,'asset',p.index_asset_id,'compose',statement_timestamp()) index_compose
              from environment_feature_index_publication p
              join environment_source_admission s
                on s.workspace_id=p.workspace_id and s.admission_id=p.admission_id
              join derived_environment_asset i
                on i.workspace_id=p.workspace_id and i.asset_id=p.index_asset_id
             where p.workspace_id=%s and p.admission_id=%s and p.publication_id=%s
            """,
            (
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                admission_id,
                publication_id,
            ),
        ).fetchone()
        if row is None or row["render_asset_id"] != render_asset_id:
            raise UnknownWorldResource("no such environment feature publication")
        if row["index_withdrawn_at"] is not None:
            raise EnvironmentSourceWithdrawn("the environment feature index is withdrawn")
        if row["publication_id"] != row["current_publication_id"]:
            raise EnvironmentBindingDrift("the named feature publication is no longer current")
        if require_rights and not all(
            row[key] for key in ("source_index", "render_index", "index_index", "index_compose")
        ):
            raise EnvironmentCompositionDenied(
                "feature placement requires index and compose rights on its exact binding"
            )
        return row

    def _read_feature(
        self,
        publication: Mapping[str, Any],
        feature_id: str | None,
        render_batch_id: int | None,
    ) -> Mapping[str, Any]:
        if self.store is None:
            raise UnavailableAsset("environment composition requires the content-addressed store")
        try:
            data = self.store.get(BlobId(bytes(publication["index_sha256"])))
            document = json.loads(data)
            payload = document["index"]
            if (
                (document.get("profile"), payload.get("profile"))
                not in (
                    (
                        "exulanica.environment-feature-index-envelope/v1",
                        "exulanica.environment-feature-index/v1",
                    ),
                    (
                        "exulanica.environment-feature-index-envelope/v2",
                        "exulanica.environment-feature-index/v2",
                    ),
                )
                or document.get("payload_sha256")
                != hashlib.sha256(canonical_json(payload)).hexdigest()
                or payload.get("admission_id") != str(publication["admission_id"])
                or payload.get("place_id") != str(publication["place_id"])
                or payload.get("source")
                != {
                    "content_sha256": bytes(publication["source_sha256"]).hex(),
                    "receipt_sha256": bytes(publication["source_receipt_sha256"]).hex(),
                }
                or payload.get("render_asset")
                != {
                    "asset_id": str(publication["render_asset_id"]),
                    "content_sha256": bytes(publication["render_sha256"]).hex(),
                    "receipt_sha256": bytes(publication["render_receipt_sha256"]).hex(),
                }
                or payload.get("geographic_frame") != publication["geographic_frame"]
                or payload.get("geographic_bounds") != publication["geographic_bounds"]
            ):
                raise IntegrityError("the pinned environment feature index binding is malformed")
            features = payload["features"]
        except BlobNotFoundError as exc:
            raise UnavailableAsset("the pinned environment index bytes are unavailable") from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IntegrityError("the pinned environment feature index is malformed") from exc
        matches = [
            feature
            for feature in features
            if isinstance(feature, dict) and feature.get("id") == feature_id
        ]
        if len(matches) != 1 or matches[0].get("render_batch_id") != render_batch_id:
            raise InvalidEnvironmentData(
                "the feature and render batch do not match the exact publication"
            )
        return matches[0]

    def _require_bytes(
        self, source_sha256: bytes, render_sha256: bytes, index_sha256: bytes | None
    ) -> None:
        if self.store is None:
            raise UnavailableAsset("environment composition requires the content-addressed store")
        try:
            for digest in (source_sha256, render_sha256, index_sha256):
                if digest is not None:
                    self.store.get(BlobId(bytes(digest)))
        except BlobNotFoundError as exc:
            raise UnavailableAsset("the exact pinned environment bytes are unavailable") from exc

    def require_current(
        self,
        instance: EnvironmentInstance,
        *,
        require_bytes: bool,
        validate_feature_bytes: bool = True,
    ) -> None:
        source = instance.source
        row = self.connection.execute(
            """
            select s.place_id,s.source_sha256,s.receipt_sha256 as source_receipt_sha256,
                   s.withdrawn_at as source_withdrawn_at,
                   r.content_sha256 as render_sha256,r.receipt_sha256 as render_receipt_sha256,
                   s.geographic_frame,s.geographic_bounds,
                   r.withdrawn_at as render_withdrawn_at,
                   environment_resource_allows(
                     %s,'source',s.admission_id,'compose',statement_timestamp()) source_compose,
                   environment_resource_allows(
                     %s,'asset',r.asset_id,'compose',statement_timestamp()) render_compose
              from environment_source_admission s
              join derived_environment_asset r
                on r.workspace_id=s.workspace_id and r.admission_id=s.admission_id
             where s.workspace_id=%s and s.admission_id=%s and r.asset_id=%s
            """,
            (
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                source.admission_id,
                source.render_asset_id,
            ),
        ).fetchone()
        if row is None:
            raise EnvironmentBindingDrift("the pinned environment binding no longer resolves")
        if row["source_withdrawn_at"] is not None or row["render_withdrawn_at"] is not None:
            raise EnvironmentSourceWithdrawn("the pinned environment source is withdrawn")
        if not row["source_compose"] or not row["render_compose"]:
            raise EnvironmentCompositionDenied("compose is no longer permitted")
        expected = (
            source.place_id,
            source.source_sha256,
            source.source_receipt_sha256,
            source.render_sha256,
            source.render_receipt_sha256,
            dict(source.frame),
            dict(source.bounds) if source.selection.kind == "whole_asset" else None,
        )
        actual = (
            row["place_id"],
            bytes(row["source_sha256"]).hex(),
            bytes(row["source_receipt_sha256"]).hex(),
            bytes(row["render_sha256"]).hex(),
            bytes(row["render_receipt_sha256"]).hex(),
            row["geographic_frame"],
            row["geographic_bounds"] if source.selection.kind == "whole_asset" else None,
        )
        if actual != expected:
            raise EnvironmentBindingDrift("the pinned environment source binding drifted")
        index_digest = None
        if source.publication_id is not None:
            publication = self._current_publication(
                source.admission_id,
                source.render_asset_id,
                source.publication_id,
                require_rights=True,
            )
            published = (
                bytes(publication["source_sha256"]).hex(),
                bytes(publication["source_receipt_sha256"]).hex(),
                bytes(publication["render_sha256"]).hex(),
                bytes(publication["render_receipt_sha256"]).hex(),
                bytes(publication["index_sha256"]).hex(),
                bytes(publication["index_receipt_sha256"]).hex(),
                bytes(publication["publication_receipt_sha256"]).hex(),
            )
            pinned = (
                source.source_sha256,
                source.source_receipt_sha256,
                source.render_sha256,
                source.render_receipt_sha256,
                source.index_sha256,
                source.index_receipt_sha256,
                source.publication_receipt_sha256,
            )
            if published != pinned:
                raise EnvironmentBindingDrift("the pinned feature publication binding drifted")
            if validate_feature_bytes:
                feature = self._read_feature(
                    publication,
                    source.selection.feature_id,
                    source.selection.render_batch_id,
                )
                feature_bounds = {
                    "kind": "bbox",
                    "frame_name": row["geographic_frame"]["name"],
                    "coordinate_scale": row["geographic_bounds"]["coordinate_scale"],
                    "coordinates": feature["bbox"],
                }
                if feature_bounds != dict(source.bounds):
                    raise EnvironmentBindingDrift("the pinned feature bounds drifted")
            index_digest = publication["index_sha256"]
        if require_bytes:
            self._require_bytes(row["source_sha256"], row["render_sha256"], index_digest)

    def final_authorization(self, instance: EnvironmentInstance) -> None:
        lock_asset_reads_until_commit(
            self.connection,
            outside=(
                "an environment instance is authorized only inside the transaction that writes it"
            ),
        )
        self.require_current(instance, require_bytes=False, validate_feature_bytes=False)

    def availability(self, instance: EnvironmentInstance) -> str:
        try:
            self.require_current(instance, require_bytes=False)
        except EnvironmentSourceWithdrawn:
            return "withdrawn"
        except UnavailableAsset:
            return "unavailable_bytes"
        except (EnvironmentBindingDrift, EnvironmentCompositionDenied, UnknownWorldResource):
            return "binding_drift"
        if self.store is None:
            return "unknown"
        try:
            source = instance.source
            self._require_bytes(
                bytes.fromhex(source.source_sha256),
                bytes.fromhex(source.render_sha256),
                None if source.index_sha256 is None else bytes.fromhex(source.index_sha256),
            )
        except UnavailableAsset:
            return "unavailable_bytes"
        return "available"
