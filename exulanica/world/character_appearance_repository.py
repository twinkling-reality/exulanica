"""Revisioned authored appearance on existing workspace/world/version/subject authority.

The world is always named by the caller: appearance history is kept per world version, and a
workspace holds several worlds.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.asset_import import ReviewedAssetImport
from exulanica.world.character_appearance import (
    AppearanceUnavailable,
    CharacterFamily,
    CharacterRecipe,
    CharacterSubject,
    RepresentationBinding,
    StaleAppearance,
    catalog_family_base,
    document_sha256,
    is_catalog_family,
    look_containers,
    look_from_recipe,
    validate_recipe,
)
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.society import UnknownSociety
from exulanica.world.society_repository import SocietyRepository


class CharacterAppearanceRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        *,
        families: tuple[CharacterFamily, ...] = (),
        authorize_family: Callable[[CharacterFamily], bool] | None = None,
        society_input_authorizer: Callable[[dict[str, Any]], None] | None = None,
        store: ContentAddressedStore | None = None,
        catalog: Mapping[str, Any] | None = None,
        world_id: str,
    ) -> None:
        self.connection, self.workspace_id, self.actor = connection, workspace_id, actor
        self.world_id, self.store, self.catalog = world_id, store, catalog
        # Copy declarations to isolate mutable nested data from the host and callers.
        self.families = {
            f.sha256: CharacterFamily.model_validate_json(f.model_dump_json()) for f in families
        }
        self.authorize_family = authorize_family
        self.societies = SocietyRepository(
            connection, workspace_id, world_id=world_id, input_authorizer=society_input_authorizer
        )

    def _scope(self, version_id: uuid.UUID, subject: CharacterSubject) -> tuple:
        return (self.workspace_id, self.world_id, version_id, subject.kind, subject.subject_id)

    def _authorize(self, version_id: uuid.UUID, subject: CharacterSubject) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880024))", (str(self.workspace_id),)
        )
        if subject.kind == "avatar" and subject.subject_id != self.actor:
            raise UnknownWorldResource("no such authorized character")
        version = WorldObjectRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        ).version(version_id)
        if version.source_invalidated:
            raise AppearanceUnavailable("character's world source is invalidated")
        if subject.kind == "synthetic-inhabitant":
            try:
                snapshot = self.societies.snapshot(version_id)
            except UnknownSociety as exc:
                raise UnknownWorldResource("no such authorized character") from exc
            if snapshot["society_id"] != subject.society_id or snapshot["created_by"] != self.actor:
                raise UnknownWorldResource("no such authorized character")
            if not any(
                i["id"] == str(subject.subject_id) and i.get("synthetic") is True
                for i in snapshot["state"]["inhabitants"]
            ):
                raise UnknownWorldResource("no such authorized character")

    def _family(self, recipe: CharacterRecipe) -> CharacterFamily:
        family = self.families.get(recipe.family_sha256)
        if family is None or family.family_id != recipe.family_id:
            raise AppearanceUnavailable("exact character family revision is not configured")
        if self.authorize_family is None or self.authorize_family(family) is not True:
            raise AppearanceUnavailable("character family sources are not currently authorized")
        return family

    def _row(
        self, version_id: uuid.UUID, subject: CharacterSubject, revision: int | None = None
    ) -> dict | None:
        suffix = " order by revision desc limit 1" if revision is None else " and revision=%s"
        params = self._scope(version_id, subject) + (() if revision is None else (revision,))
        return self.connection.execute(
            "select * from world_character_appearance_revision "
            "where workspace_id=%s and world_id=%s "
            "and version_id=%s and subject_kind=%s and subject_id=%s" + suffix,
            params,
        ).fetchone()

    @staticmethod
    def _validated(row: dict) -> tuple[CharacterRecipe, CharacterFamily]:
        document = row["document"]
        if document_sha256(document) != row["document_sha256"]:
            raise ValueError("stored character appearance digest disagrees")
        recipe = CharacterRecipe.model_validate(document["recipe"])
        family = CharacterFamily.model_validate(document["family"])
        subject = CharacterSubject.model_validate(document["subject"])
        if (
            str(row["version_id"]),
            row["subject_kind"],
            str(row["subject_id"]),
            str(row["society_id"]) if row["society_id"] else None,
        ) != (
            document["version_id"],
            subject.kind,
            str(subject.subject_id),
            str(subject.society_id) if subject.society_id else None,
        ):
            raise ValueError("stored character appearance subject disagrees")
        validate_recipe(recipe, family, subject)
        return recipe, family

    def _render_status(self, binding: RepresentationBinding | None) -> str:
        if binding is None:
            return "no_prepared_representation"
        pin = binding.asset
        row = self.connection.execute(
            "select a.*,i.receipt_sha256 from world_reviewed_asset a "
            "join world_reviewed_asset_import i using(asset_key,content_sha256) "
            "where a.asset_key=%s",
            (pin.asset_key,),
        ).fetchone()
        if row is None or (row["content_sha256"], row["receipt_sha256"], row["byte_size"]) != (
            pin.content_sha256,
            pin.receipt_sha256,
            pin.byte_size,
        ):
            return "asset_withdrawn_or_unreviewed"
        if self.store is None:
            return "asset_store_unavailable"
        try:
            payload = self.store.get(BlobId.from_hex(pin.content_sha256))
            receipt = self.store.get(BlobId.from_hex(pin.receipt_sha256))
            licence = self.store.get(BlobId.from_hex(row["licence_sha256"]))
            preparation = self.store.get(BlobId.from_hex(binding.preparation_receipt_sha256))
            if (
                len(payload) != pin.byte_size
                or hashlib.sha256(payload).hexdigest() != pin.content_sha256
            ):
                return "asset_integrity_unavailable"
            for data, sha in (
                (receipt, pin.receipt_sha256),
                (licence, row["licence_sha256"]),
                (preparation, binding.preparation_receipt_sha256),
            ):
                if hashlib.sha256(data).hexdigest() != sha:
                    return "asset_integrity_unavailable"
            manifest = ReviewedAssetImport.model_validate_json(receipt)
            if (
                manifest.asset_key,
                manifest.content_sha256,
                manifest.byte_size,
                manifest.licence_sha256,
            ) != (pin.asset_key, pin.content_sha256, pin.byte_size, row["licence_sha256"]):
                return "asset_integrity_unavailable"
        except (BlobNotFoundError, IntegrityError, ValueError):
            return "asset_bytes_unavailable"
        return "available"

    def _catalog_render_status(self, recipe: CharacterRecipe, family: CharacterFamily) -> str:
        """Whether every container a catalog look composes is published and present.

        A catalog look has no single prepared body: the browser composes it from the body,
        worn parts and material packs the catalog names, each fetched as a reviewed asset.
        """
        if self.catalog is None:
            return "catalog_unavailable"
        try:
            catalog_family_base(self.catalog, family)
            look = look_from_recipe(self.catalog, recipe, family)
            containers = look_containers(self.catalog, look)
        except ValueError:
            return "catalog_unavailable"
        rows = {
            row["asset_key"]: row
            for row in self.connection.execute(
                "select a.asset_key,a.content_sha256,a.byte_size,a.licence_sha256 "
                "from world_reviewed_asset a "
                "join world_reviewed_asset_import i using(asset_key,content_sha256) "
                "where a.asset_key = any(%s)",
                ([ref["assetKey"] for ref in containers],),
            ).fetchall()
        }
        for ref in containers:
            row = rows.get(ref["assetKey"])
            if row is None or (row["content_sha256"], row["byte_size"]) != (
                ref["contentSha256"],
                ref["byteSize"],
            ):
                return "asset_withdrawn_or_unreviewed"
        if self.store is None:
            return "asset_store_unavailable"
        for ref in containers:
            for digest in (ref["contentSha256"], rows[ref["assetKey"]]["licence_sha256"]):
                if not self.store.exists(BlobId.from_hex(digest)):
                    return "asset_bytes_unavailable"
        return "available"

    def _view(self, row: dict) -> dict:
        recipe, _family = self._validated(row)
        try:
            current = self._family(recipe)
        except AppearanceUnavailable:
            status = "family_source_unavailable"
        else:
            subject = CharacterSubject.model_validate(row["document"]["subject"])
            binding = validate_recipe(recipe, current, subject)
            status = (
                self._catalog_render_status(recipe, current)
                if is_catalog_family(current)
                else self._render_status(binding)
            )
        return {
            "revision": row["revision"],
            "operation": row["operation"],
            "restored_from_revision": row["restored_from_revision"],
            "document": row["document"],
            "document_sha256": row["document_sha256"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "render_status": status,
            "generation_status": "not_requested",
        }

    def available_families(self, version_id: uuid.UUID, subject: CharacterSubject) -> list[dict]:
        with self.connection.transaction():
            self._authorize(version_id, subject)
            use = "authored-avatar" if subject.kind == "avatar" else "synthetic-inhabitant"
            return [
                {"family_sha256": family.sha256, "family": family.model_dump(mode="json")}
                for family in self.families.values()
                if use in family.permitted_uses
                and self.authorize_family is not None
                and self.authorize_family(family) is True
            ]

    def read(self, version_id: uuid.UUID, subject: CharacterSubject) -> dict:
        with self.connection.transaction():
            self._authorize(version_id, subject)
            row = self._row(version_id, subject)
            return (
                {"revision": 0, "current": None}
                if row is None
                else {"revision": row["revision"], "current": self._view(row)}
            )

    def history(
        self,
        version_id: uuid.UUID,
        subject: CharacterSubject,
        *,
        before_revision: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (
                before_revision is not None
                and (type(before_revision) is not int or before_revision < 1)
            )
        ):
            raise ValueError("invalid appearance history page")
        with self.connection.transaction():
            self._authorize(version_id, subject)
            rows = self.connection.execute(
                "select * from world_character_appearance_revision "
                "where workspace_id=%s and world_id=%s "
                "and version_id=%s and subject_kind=%s and subject_id=%s and revision<%s "
                "order by revision desc limit %s",
                (
                    *self._scope(version_id, subject),
                    before_revision if before_revision is not None else 2**63 - 1,
                    limit,
                ),
            ).fetchall()
            return [self._view(row) for row in rows]

    def save(
        self,
        version_id: uuid.UUID,
        subject: CharacterSubject,
        recipe: CharacterRecipe,
        *,
        base_revision: int,
    ) -> dict:
        return self._write(version_id, subject, base_revision, recipe=recipe)

    def reset(
        self,
        version_id: uuid.UUID,
        subject: CharacterSubject,
        *,
        base_revision: int,
        restore_revision: int | None = None,
    ) -> dict:
        """Append a default or historical recipe, without touching simulation events or identity."""
        return self._write(version_id, subject, base_revision, restore_revision=restore_revision)

    def _write(
        self,
        version_id: uuid.UUID,
        subject: CharacterSubject,
        base_revision: int,
        *,
        recipe: CharacterRecipe | None = None,
        restore_revision: int | None = None,
    ) -> dict:
        if type(base_revision) is not int or not 0 <= base_revision < 2**63 - 1:
            raise ValueError("invalid appearance base revision")
        if restore_revision is not None and (
            type(restore_revision) is not int or not 1 <= restore_revision <= base_revision
        ):
            raise ValueError("invalid appearance restore revision")
        with self.connection.transaction():
            self._authorize(version_id, subject)
            prior = self._row(version_id, subject)
            if (prior["revision"] if prior else 0) != base_revision:
                raise StaleAppearance("appearance changed; reload before saving")
            operation = "save" if recipe is not None else "reset"
            if recipe is None:
                target = (
                    prior
                    if restore_revision is None
                    else self._row(version_id, subject, restore_revision)
                )
                if target is None:
                    raise UnknownWorldResource("no saved appearance to reset")
                recipe, _ = self._validated(target)
                family = self._family(recipe)
                if restore_revision is None:
                    recipe = CharacterRecipe(
                        family_id=family.family_id,
                        family_sha256=family.sha256,
                        parameters={p.key: p.default for p in family.parameters},
                        seed=family.default_seed,
                    )
            # Revalidate even models constructed by an internal caller, whose dicts can be mutable.
            recipe = CharacterRecipe.model_validate_json(recipe.model_dump_json())
            family = self._family(recipe)
            binding = validate_recipe(recipe, family, subject)
            document = {
                "profile": "exulanica.character-appearance-revision/v1",
                "version_id": str(version_id),
                "subject": subject.model_dump(mode="json"),
                "recipe": recipe.model_dump(mode="json"),
                "family": family.model_dump(mode="json"),
                "representation": None if binding is None else binding.model_dump(mode="json"),
                "origin": "authored",
                "plane": "fictional",
                "producer": "exulanica.character-appearance/v1",
            }
            row = self.connection.execute(
                "insert into world_character_appearance_revision(workspace_id,world_id,version_id,"
                "subject_kind,subject_id,"
                "society_id,revision,operation,restored_from_revision,"
                "document,document_sha256,created_by) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                (
                    *self._scope(version_id, subject),
                    subject.society_id,
                    base_revision + 1,
                    operation,
                    restore_revision,
                    Jsonb(document),
                    document_sha256(document),
                    self.actor,
                ),
            ).fetchone()
            return {"revision": row["revision"], "current": self._view(row)}
