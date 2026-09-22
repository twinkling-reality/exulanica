"""Explicit host-configured society composition and current dependency authorization.

Configuration is an immutable, workspace/version-scoped registration, not request input.
No frame is inferred, no admission is created, and no source rights are granted here.
The host wires these callbacks into Services/app state and the accepted-edit transaction.

One runtime serves two kinds of registration. A district binding composes an admitted
interpretation of real city sources. An authored-world binding composes a saved world over the
flat ground its own structural snapshot declares, with no admitted source and no district.
A version is registered under one kind or the other, never both.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.canonical import canonical_json
from exulanica.db.session import set_workspace
from exulanica.environment.admission import MAX_ENVIRONMENT_PAYLOAD_BYTES
from exulanica.environment.district_geometry import DistrictGeometry, segment_blocked
from exulanica.environment.district_interpretation import Frame, validate_interpretation
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.selection.validation import Session
from exulanica.store.base import ContentAddressedStore
from exulanica.world.errors import InvalidStructuralData, UnknownWorldResource
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AlternateVersion
from exulanica.world.society import UnavailableSocietyInput, society_state_sha256
from exulanica.world.society_authored_ground import (
    SocietyGround,
    authored_ground_from_snapshot,
    build_authored_ground_society_input,
)
from exulanica.world.society_composition import build_society_input, policy_dependency_refs
from exulanica.world.society_input_policy import (
    AUTHORED_GROUND_COMPOSITION,
    AUTHORED_GROUND_INPUT,
    LEGACY_COMPOSITION,
    LOCAL_INPUT,
    input_profile,
)
from exulanica.world.society_input_policy import (
    composition_profile as policy_for_input,
)
from exulanica.world.society_planner import input_sha256, validate_society_input
from exulanica.world.society_repository import SocietyRepository

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=500)]
Millimetre = Annotated[StrictInt, Field(ge=-1_000_000_000, le=1_000_000_000)]
_OPERATIONS = ("display", "persist", "modify", "compose")
#: The engine profiles that consume ordered inputs, and so react to an accepted authored edit.
_INPUT_ENGINES = ("exulanica-society/v2", "exulanica-society/v3", "exulanica-society/v4")


class RuntimeSourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: Literal["5zhs-2jue", "52n9-sdep"]
    admission_id: uuid.UUID
    source_sha256: Digest
    receipt_sha256: Digest


class SocietyRuntimeBinding(BaseModel):
    """Persist this exact host configuration across reload; never construct it from a request."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: Text
    workspace_id: uuid.UUID
    world_id: Text
    version_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    place_id: uuid.UUID
    region_id: Text
    district_id: Text
    frame: Frame
    translation_mm: tuple[Millimetre, Millimetre, Millimetre]
    yaw_microradians: Literal[0]
    scale_milli: Literal[1000]
    base_artifact_sha256: Digest
    interpretation_artifact_sha256: Digest
    interpretation_document_sha256: Digest
    sources: tuple[RuntimeSourceBinding, RuntimeSourceBinding]

    def registration(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "version_id": str(self.version_id),
            "source_snapshot_id": str(self.source_snapshot_id),
            "region_id": self.region_id,
            "district_id": self.district_id,
            "frame_name": self.frame.name,
            "translation_mm": list(self.translation_mm),
            "yaw_microradians": 0,
            "scale_milli": 1000,
        }


class AuthoredWorldSocietyBinding(BaseModel):
    """One saved world registered to hold inhabitants, with no district and no admitted source.

    Persist this exact host configuration across reload; never construct it from a request. It
    names nothing the world does not already hold: the region is the authored region of the
    version's own structural snapshot, and ``place_id`` is the workspace-scoped place identity
    the society row binds, not a claim about anywhere on the Earth.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: Text
    workspace_id: uuid.UUID
    world_id: Text
    version_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    place_id: uuid.UUID
    region_id: Text


class SocietyRuntime:
    def __init__(
        self,
        *,
        store: ContentAddressedStore,
        bindings: Sequence[SocietyRuntimeBinding] = (),
        authored_bindings: Sequence[AuthoredWorldSocietyBinding] = (),
        reviewed_affordances: Mapping[str, dict[str, Any]],
        composition_profile: str = LEGACY_COMPOSITION,
    ) -> None:
        self.store = store
        input_profile(composition_profile)
        if composition_profile == AUTHORED_GROUND_COMPOSITION:
            raise ValueError("the authored-ground policy is selected by binding, not by profile")
        self._composition_profile = composition_profile
        self._bindings: dict[tuple[uuid.UUID, uuid.UUID], SocietyRuntimeBinding] = {}
        self._authored: dict[tuple[uuid.UUID, uuid.UUID], AuthoredWorldSocietyBinding] = {}
        # Freeze caller-owned dictionaries by serializing once; no mutable registry leaks out.
        self._registry_bytes = canonical_json(dict(reviewed_affordances))
        for supplied in bindings:
            binding = SocietyRuntimeBinding.model_validate_json(supplied.model_dump_json())
            key = (binding.workspace_id, binding.version_id)
            if key in self._bindings or {s.dataset_id for s in binding.sources} != {
                "5zhs-2jue",
                "52n9-sdep",
            }:
                raise ValueError("duplicate or incomplete scoped society runtime binding")
            self._bindings[key] = binding
        for candidate in authored_bindings:
            authored = AuthoredWorldSocietyBinding.model_validate_json(candidate.model_dump_json())
            key = (authored.workspace_id, authored.version_id)
            # One version composes one way. A version registered as both would authorize two
            # different spatial authorities for the same stored history.
            if key in self._authored or key in self._bindings:
                raise ValueError("duplicate or conflicting scoped society runtime binding")
            self._authored[key] = authored

    def _binding(self, session: Session, version_id: uuid.UUID) -> SocietyRuntimeBinding:
        binding = self._bindings.get((session.workspace_id, version_id))
        if binding is None:
            raise UnavailableSocietyInput("society frame binding is not configured for this scope")
        return binding

    def _authored_binding(
        self, session: Session, version_id: uuid.UUID
    ) -> AuthoredWorldSocietyBinding:
        binding = self._authored.get((session.workspace_id, version_id))
        if binding is None:
            raise UnavailableSocietyInput(
                "authored-world society binding is not configured for this scope"
            )
        return binding

    @staticmethod
    def _lock(connection: psycopg.Connection, session: Session) -> None:
        connection.row_factory = dict_row
        set_workspace(connection, session.workspace_id)
        # Same order as authored edits/structural invalidation, then source withdrawal exclusion.
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880024))",
            (str(session.workspace_id),),
        )
        connection.execute("select asset_read_lock()")

    def _version(
        self, connection: psycopg.Connection, session: Session, binding: SocietyRuntimeBinding
    ) -> AlternateVersion:
        try:
            version = WorldObjectRepository(
                connection, session.workspace_id, world_id=binding.world_id, store=self.store
            ).version(binding.version_id)
        except UnknownWorldResource as exc:
            raise UnavailableSocietyInput("bound authored version is unavailable") from exc
        if version.source_snapshot_id != binding.source_snapshot_id:
            raise UnavailableSocietyInput("authored source snapshot binding drift")
        region = connection.execute(
            "select 1 from world_structure_snapshot_region where workspace_id=%s and world_id=%s "
            "and snapshot_id=%s and region_id=%s",
            (session.workspace_id, binding.world_id, binding.source_snapshot_id, binding.region_id),
        ).fetchone()
        if region is None:
            raise UnavailableSocietyInput("registered source region is unavailable")
        return version

    def _blob(self, digest: str, expected_size: int | None = None) -> bytes:
        try:
            data = self.store.get(BlobId.from_hex(digest))
        except (BlobNotFoundError, IntegrityError, OSError) as exc:
            raise UnavailableSocietyInput("required exact asset bytes are unavailable") from exc
        if (
            len(data) > MAX_ENVIRONMENT_PAYLOAD_BYTES
            or (expected_size is not None and len(data) != expected_size)
            or hashlib.sha256(data).hexdigest() != digest
        ):
            raise UnavailableSocietyInput("required asset bytes failed integrity validation")
        return data

    def _source_rows(
        self, connection: psycopg.Connection, session: Session, binding: SocietyRuntimeBinding
    ) -> dict[str, dict]:
        rows = {}
        for source in binding.sources:
            row = connection.execute(
                "select *, environment_resource_allows(%s,'source',admission_id,'display'"
                ",statement_timestamp()) "
                "and environment_resource_allows(%s,'source',admission_id,'persist',state"
                "ment_timestamp()) "
                "and environment_resource_allows(%s,'source',admission_id,'modify',statem"
                "ent_timestamp()) "
                "and environment_resource_allows(%s,'source',admission_id,'compose',state"
                "ment_timestamp()) as allowed "
                "from environment_source_admission where workspace_id=%s and admission_id=%s",
                (session.workspace_id,) * 5 + (source.admission_id,),
            ).fetchone()
            if row is None or not row["allowed"] or row["withdrawn_at"] is not None:
                raise UnavailableSocietyInput("district source is unavailable or operation denied")
            receipt = canonical_json(row["receipt_record"])
            if (
                row["place_id"] != binding.place_id
                or row["provider_key"] != "nyc-open-data"
                or row["provider_original_id"] != source.dataset_id
                or bytes(row["source_sha256"]).hex() != source.source_sha256
                or bytes(row["receipt_sha256"]).hex() != source.receipt_sha256
                or hashlib.sha256(receipt).hexdigest() != source.receipt_sha256
                or bytes(row["receipt_canonical"]) != receipt
                or any(row["operation_rights"].get(op) is not True for op in _OPERATIONS)
            ):
                raise UnavailableSocietyInput("district source binding drift")
            self._blob(source.source_sha256, row["byte_size"])
            rows[source.dataset_id] = row
        return rows

    def _district(
        self, connection: psycopg.Connection, session: Session, binding: SocietyRuntimeBinding
    ) -> tuple[dict, bytes, DistrictGeometry]:
        rows = self._source_rows(connection, session, binding)
        base_bytes = self._blob(binding.base_artifact_sha256)
        data = self._blob(binding.interpretation_artifact_sha256)
        try:
            interpreted = validate_interpretation(data, base_bytes)
        except (ValueError, TypeError, KeyError) as exc:
            raise UnavailableSocietyInput("configured district artifact is invalid") from exc
        if (
            interpreted.document_sha256 != binding.interpretation_document_sha256
            or interpreted.district_id != binding.district_id
            or interpreted.frame != binding.frame
        ):
            raise UnavailableSocietyInput("configured district/frame binding drift")
        for dep in interpreted.source_dependencies:
            row = rows[dep.dataset_id]
            if (
                dep.sha256 != bytes(row["source_sha256"]).hex()
                or dep.provider_revision != row["provider_revision"]
                or dep.attribution != row["attribution"]
                or dep.source_url != row["source_path"]
            ):
                raise UnavailableSocietyInput("interpretation source binding drift")
        return (
            interpreted.model_dump(mode="json"),
            base_bytes,
            DistrictGeometry(json.loads(base_bytes)),
        )

    def _asset(self, connection: psycopg.Connection, key: str, digest: str) -> None:
        registry = json.loads(self._registry_bytes)
        assignment = registry.get(digest)
        if assignment is None or assignment["asset_key"] != key:
            raise UnavailableSocietyInput("reviewed affordance assignment is unavailable")
        row = connection.execute(
            "select content_sha256,byte_size,licence_id,licence_sha256 from world_reviewed_asset "
            "where asset_key=%s",
            (key,),
        ).fetchone()
        if row is None or row["content_sha256"] != digest or row["licence_id"] != "CC0-1.0":
            raise UnavailableSocietyInput("reviewed authored asset binding drift")
        self._blob(digest, row["byte_size"])
        self._blob(row["licence_sha256"])

    def _refs(self, binding: SocietyRuntimeBinding) -> list[dict[str, str]]:
        refs = [
            {
                "kind": "society_runtime_binding",
                "identity": binding.binding_id,
                "sha256": society_state_sha256(binding.model_dump(mode="json")),
            },
            {
                "kind": "district_base",
                "identity": binding.district_id,
                "sha256": binding.base_artifact_sha256,
            },
            {
                "kind": "district_interpretation_blob",
                "identity": binding.district_id,
                "sha256": binding.interpretation_artifact_sha256,
            },
        ]
        refs.extend(
            {
                "kind": "environment_source",
                "identity": str(s.admission_id),
                "sha256": s.source_sha256,
            }
            for s in binding.sources
        )
        return refs

    def _policy_refs(
        self, binding: SocietyRuntimeBinding, *, composition: str | None = None
    ) -> list[dict[str, str]]:
        profile = self._composition_profile if composition is None else composition
        input_profile(profile)
        return [
            {
                "kind": "society_composition_policy",
                "identity": profile,
                "sha256": society_state_sha256({"profile": profile}),
            },
            {
                "kind": "society_frame_registration",
                "identity": str(binding.version_id),
                "sha256": society_state_sha256(binding.registration()),
            },
            {
                "kind": "society_affordance_registry",
                "identity": profile,
                "sha256": hashlib.sha256(self._registry_bytes).hexdigest(),
            },
        ]

    def _unavailable(
        self, binding: SocietyRuntimeBinding, version: AlternateVersion, seq: int, reason: str
    ) -> dict:
        # Do not read withdrawn bytes or carry stale geometry/targets into an unavailable input.
        refs = self._refs(binding) + self._policy_refs(binding)
        doc = {
            "profile": input_profile(self._composition_profile),
            "input_seq": seq,
            "world_id": binding.world_id,
            "version_id": str(binding.version_id),
            "district_id": binding.district_id,
            "district_document_sha256": binding.interpretation_document_sha256,
            "base_artifact_sha256": binding.base_artifact_sha256,
            "frame": binding.frame.model_dump(mode="json"),
            "authored_state": {"edit_seq": version.edit_seq, "delta_sha256": version.state_sha256},
            "navigation": {
                "profile": "bounded-sidewalk-graph/v1",
                "clearance_mm": 450,
                "nodes": [],
                "edges": [],
                "destinations": [],
                "unavailable_reason": reason,
            },
            "targets": [],
            "dependency_refs": sorted(refs, key=lambda r: (r["kind"], r["identity"], r["sha256"])),
            "availability": "unavailable",
            "unavailable_reason": reason,
        }
        if doc["profile"] == LOCAL_INPUT:
            doc["unavailable_affordances"] = []
        doc["document_sha256"] = input_sha256(doc)
        validate_society_input(doc)
        return doc

    def _compose(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: SocietyRuntimeBinding,
        version: AlternateVersion,
        seq: int,
    ) -> dict:
        if version.source_invalidated:
            return self._unavailable(binding, version, seq, "authored_source_invalidated")
        registry = json.loads(self._registry_bytes)
        refs = self._refs(binding)
        try:
            interpreted, base_bytes, geometry = self._district(connection, session, binding)
            for obj in version.objects:
                if obj.removed:
                    continue
                assignment = registry.get(obj.asset_sha256)
                if assignment is None:
                    raise UnavailableSocietyInput("reviewed affordance assignment is unavailable")
                self._asset(connection, assignment["asset_key"], obj.asset_sha256)
                refs.append(
                    {
                        "kind": "reviewed_asset",
                        "identity": assignment["asset_key"],
                        "sha256": obj.asset_sha256,
                    }
                )
        except UnavailableSocietyInput as exc:
            return self._unavailable(binding, version, seq, str(exc))
        return build_society_input(
            interpretation=interpreted,
            base_bytes=base_bytes,
            version=version,
            registration=binding.registration(),
            input_seq=seq,
            dependency_refs=refs,
            availability="available",
            unavailable_reason=None,
            reviewed_affordances=registry,
            supports=geometry.supports,
            segment_blocked=segment_blocked,
            composition_profile=self._composition_profile,
        )

    def initial_input(
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        place_id: uuid.UUID,
        region_id: str,
    ) -> dict:
        if (session.workspace_id, version_id) in self._authored:
            return self._authored_initial_input(
                connection, session, version_id, place_id, region_id
            )
        binding = self._binding(session, version_id)
        if place_id != binding.place_id or region_id != binding.region_id:
            raise UnavailableSocietyInput("requested place/region has no configured binding")
        with connection.transaction():
            self._lock(connection, session)
            version = self._version(connection, session, binding)
            return self._compose(connection, session, binding, version, 1)

    def authorize(self, connection: psycopg.Connection, session: Session, document: dict) -> None:
        """Authorize an exact persisted historical input or exact fresh server recomposition."""
        validate_society_input(document)
        if document["profile"] == AUTHORED_GROUND_INPUT:
            self._authored_authorize(connection, session, document)
            return
        binding = self._binding(session, uuid.UUID(document["version_id"]))
        if (
            document["world_id"] != binding.world_id
            or document["district_id"] != binding.district_id
            or document["district_document_sha256"] != binding.interpretation_document_sha256
            or document["base_artifact_sha256"] != binding.base_artifact_sha256
            or document["frame"] != binding.frame.model_dump(mode="json")
        ):
            raise UnavailableSocietyInput("society input scope or frame binding drift")
        with connection.transaction():
            self._lock(connection, session)
            version = self._version(connection, session, binding)
            stored = connection.execute(
                "select i.document,i.document_sha256 from world_society_input i join "
                "world_society s "
                "on s.workspace_id=i.workspace_id and s.society_id=i.society_id "
                "where i.workspace_id=%s and s.world_id=%s and s.version_id=%s and s.place_id=%s "
                "and s.region_id=%s and i.input_seq=%s",
                (
                    session.workspace_id,
                    binding.world_id,
                    binding.version_id,
                    binding.place_id,
                    binding.region_id,
                    document["input_seq"],
                ),
            ).fetchone()
            if stored is None:
                next_seq = connection.execute(
                    "select coalesce(max(i.input_seq),0)+1 as seq from world_society s "
                    "join world_society_input i on s.workspace_id=i.workspace_id "
                    "and s.society_id=i.society_id where s.workspace_id=%s "
                    "and s.world_id=%s and s.version_id=%s",
                    (session.workspace_id, binding.world_id, binding.version_id),
                ).fetchone()["seq"]
                if document["input_seq"] != next_seq:
                    raise UnavailableSocietyInput("unpersisted input sequence is not current")
                expected = self._compose(
                    connection, session, binding, version, document["input_seq"]
                )
                if document != expected:
                    raise UnavailableSocietyInput(
                        "input was not derived from current authorized state"
                    )
            elif (
                stored["document"] != document
                or stored["document_sha256"] != document["document_sha256"]
            ):
                raise UnavailableSocietyInput("historical society input binding drift")
            actual = {(r["kind"], r["identity"], r["sha256"]) for r in document["dependency_refs"]}
            required = {
                (r["kind"], r["identity"], r["sha256"])
                for r in self._refs(binding)
                + self._policy_refs(binding, composition=policy_for_input(document["profile"]))
            }
            if not required.issubset(actual):
                raise UnavailableSocietyInput("runtime registration or registry binding drift")
            if document["availability"] == "unavailable":
                if (
                    any(document["navigation"][k] for k in ("nodes", "edges", "destinations"))
                    or document["targets"]
                    or document.get("unavailable_affordances")
                ):
                    raise UnavailableSocietyInput(
                        "unavailable input contains materializable geometry"
                    )
                return
            if version.source_invalidated:
                raise UnavailableSocietyInput("authored source invalidated")
            # Even a correctly persisted historic input needs current rights and byte availability.
            self._district(connection, session, binding)
            for ref in document["dependency_refs"]:
                if ref["kind"] == "reviewed_asset":
                    self._asset(connection, ref["identity"], ref["sha256"])

    def authored_edit(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> None:
        """Run inside each accepted edit transaction, after its immutable edit row is appended."""
        if (session.workspace_id, version_id) in self._authored:
            self._authored_world_edit(connection, session, version_id)
            return
        with connection.transaction():
            self._lock(connection, session)
            row = connection.execute(
                "select society_id,world_id,place_id,region_id,engine_version from world_society "
                "where workspace_id=%s and version_id=%s",
                (session.workspace_id, version_id),
            ).fetchone()
            if row is None or row["engine_version"] not in _INPUT_ENGINES:
                return
            binding = self._binding(session, version_id)
            if (row["world_id"], row["place_id"], row["region_id"]) != (
                binding.world_id,
                binding.place_id,
                binding.region_id,
            ):
                raise UnavailableSocietyInput("society scope disagrees with configured binding")
            last = connection.execute(
                "select max(input_seq) as seq from world_society_input where "
                "workspace_id=%s and society_id=%s",
                (session.workspace_id, row["society_id"]),
            ).fetchone()["seq"]
            if last is None:
                raise UnavailableSocietyInput("society input history is unavailable")
            version = self._version(connection, session, binding)
            document = self._compose(connection, session, binding, version, last + 1)
            SocietyRepository(
                connection,
                session.workspace_id,
                world_id=binding.world_id,
                input_authorizer=lambda doc: self.authorize(connection, session, doc),
            ).record_input(version_id, document)

    # An authored world composes over the ground its own structural snapshot declares. There is
    # no district, no admitted source and no surveyed frame, so none of the source, artifact or
    # interpretation checks above apply; the checks that do are the version's own scope, the
    # snapshot the ground was read from, and the reviewed assets the placed objects use.

    def _authored_ground(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: AuthoredWorldSocietyBinding,
    ) -> SocietyGround:
        row = connection.execute(
            "select composer_key,composer_version,topology,placement,snapshot_sha256 "
            "from world_structure_snapshot where workspace_id=%s and world_id=%s "
            "and snapshot_id=%s",
            (session.workspace_id, binding.world_id, binding.source_snapshot_id),
        ).fetchone()
        if row is None:
            raise UnavailableSocietyInput("registered structural snapshot is unavailable")
        try:
            ground = authored_ground_from_snapshot(
                world_id=binding.world_id,
                snapshot_id=binding.source_snapshot_id,
                snapshot_sha256=row["snapshot_sha256"],
                composer_key=row["composer_key"],
                composer_version=row["composer_version"],
                topology=row["topology"],
                placement=row["placement"],
            )
        except InvalidStructuralData as exc:
            raise UnavailableSocietyInput(f"authored ground is unreadable: {exc}") from exc
        if ground.region_id != binding.region_id:
            raise UnavailableSocietyInput("registered region is not this world's authored region")
        return ground

    def _authored_version(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: AuthoredWorldSocietyBinding,
    ) -> AlternateVersion:
        try:
            version = WorldObjectRepository(
                connection, session.workspace_id, world_id=binding.world_id, store=self.store
            ).version(binding.version_id)
        except UnknownWorldResource as exc:
            raise UnavailableSocietyInput("bound authored version is unavailable") from exc
        if version.source_snapshot_id != binding.source_snapshot_id:
            raise UnavailableSocietyInput("authored source snapshot binding drift")
        return version

    def _authored_refs(
        self, binding: AuthoredWorldSocietyBinding, ground: SocietyGround
    ) -> list[dict[str, str]]:
        return [
            {
                "kind": "society_runtime_binding",
                "identity": binding.binding_id,
                "sha256": society_state_sha256(binding.model_dump(mode="json")),
            },
            {
                "kind": "authored_ground",
                "identity": ground.region_id,
                "sha256": ground.document_sha256,
            },
            {
                "kind": "world_structure_snapshot",
                "identity": str(ground.snapshot_id),
                "sha256": ground.snapshot_sha256,
            },
        ]

    def _authored_policy_refs(
        self, binding: AuthoredWorldSocietyBinding, ground: SocietyGround
    ) -> list[dict[str, str]]:
        return policy_dependency_refs(
            composition_profile=AUTHORED_GROUND_COMPOSITION,
            version_id=binding.version_id,
            registration=ground.registration(),
            reviewed_affordances=json.loads(self._registry_bytes),
        )

    def _authored_compose(
        self,
        connection: psycopg.Connection,
        binding: AuthoredWorldSocietyBinding,
        ground: SocietyGround,
        version: AlternateVersion,
        seq: int,
    ) -> dict:
        registry = json.loads(self._registry_bytes)
        reason = None
        try:
            for obj in version.objects:
                if obj.removed:
                    continue
                assignment = registry.get(obj.asset_sha256)
                if assignment is None:
                    raise UnavailableSocietyInput("reviewed affordance assignment is unavailable")
                self._asset(connection, assignment["asset_key"], obj.asset_sha256)
        except UnavailableSocietyInput as exc:
            reason = str(exc)
        return build_authored_ground_society_input(
            ground=ground,
            version=version,
            input_seq=seq,
            dependency_refs=self._authored_refs(binding, ground),
            availability="available" if reason is None else "unavailable",
            unavailable_reason=reason,
            reviewed_affordances=registry,
            segment_blocked=segment_blocked,
        )

    def _authored_initial_input(
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        place_id: uuid.UUID,
        region_id: str,
    ) -> dict:
        binding = self._authored_binding(session, version_id)
        if place_id != binding.place_id or region_id != binding.region_id:
            raise UnavailableSocietyInput("requested place/region has no configured binding")
        with connection.transaction():
            self._lock(connection, session)
            ground = self._authored_ground(connection, session, binding)
            version = self._authored_version(connection, session, binding)
            return self._authored_compose(connection, binding, ground, version, 1)

    def _authored_authorize(
        self, connection: psycopg.Connection, session: Session, document: dict
    ) -> None:
        binding = self._authored_binding(session, uuid.UUID(document["version_id"]))
        if document["world_id"] != binding.world_id:
            raise UnavailableSocietyInput("society input scope binding drift")
        with connection.transaction():
            self._lock(connection, session)
            ground = self._authored_ground(connection, session, binding)
            if (
                document["district_id"] != ground.place_id
                or document["district_document_sha256"] != ground.document_sha256
                or document["base_artifact_sha256"] != ground.snapshot_sha256
                or document["frame"] != ground.frame()
            ):
                raise UnavailableSocietyInput("authored ground or frame binding drift")
            version = self._authored_version(connection, session, binding)
            stored = connection.execute(
                "select i.document,i.document_sha256 from world_society_input i join "
                "world_society s "
                "on s.workspace_id=i.workspace_id and s.society_id=i.society_id "
                "where i.workspace_id=%s and s.world_id=%s and s.version_id=%s and s.place_id=%s "
                "and s.region_id=%s and i.input_seq=%s",
                (
                    session.workspace_id,
                    binding.world_id,
                    binding.version_id,
                    binding.place_id,
                    binding.region_id,
                    document["input_seq"],
                ),
            ).fetchone()
            if stored is None:
                next_seq = connection.execute(
                    "select coalesce(max(i.input_seq),0)+1 as seq from world_society s "
                    "join world_society_input i on s.workspace_id=i.workspace_id "
                    "and s.society_id=i.society_id where s.workspace_id=%s "
                    "and s.world_id=%s and s.version_id=%s",
                    (session.workspace_id, binding.world_id, binding.version_id),
                ).fetchone()["seq"]
                if document["input_seq"] != next_seq:
                    raise UnavailableSocietyInput("unpersisted input sequence is not current")
                expected = self._authored_compose(
                    connection, binding, ground, version, document["input_seq"]
                )
                if document != expected:
                    raise UnavailableSocietyInput(
                        "input was not derived from current authorized state"
                    )
            elif (
                stored["document"] != document
                or stored["document_sha256"] != document["document_sha256"]
            ):
                raise UnavailableSocietyInput("historical society input binding drift")
            actual = {(r["kind"], r["identity"], r["sha256"]) for r in document["dependency_refs"]}
            required = {
                (r["kind"], r["identity"], r["sha256"])
                for r in self._authored_refs(binding, ground)
                + self._authored_policy_refs(binding, ground)
            }
            if not required.issubset(actual):
                raise UnavailableSocietyInput("runtime registration or registry binding drift")
            if document["availability"] == "unavailable":
                if (
                    any(document["navigation"][k] for k in ("nodes", "edges", "destinations"))
                    or document["targets"]
                    or document["unavailable_affordances"]
                ):
                    raise UnavailableSocietyInput(
                        "unavailable input contains materializable geometry"
                    )
                return
            if version.source_invalidated:
                raise UnavailableSocietyInput("authored source invalidated")
            # Even a correctly persisted historic input needs current asset byte availability.
            for ref in document["dependency_refs"]:
                if ref["kind"] == "reviewed_asset":
                    self._asset(connection, ref["identity"], ref["sha256"])

    def _authored_world_edit(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> None:
        with connection.transaction():
            self._lock(connection, session)
            row = connection.execute(
                "select society_id,world_id,place_id,region_id,engine_version from world_society "
                "where workspace_id=%s and version_id=%s",
                (session.workspace_id, version_id),
            ).fetchone()
            if row is None or row["engine_version"] not in _INPUT_ENGINES:
                return
            binding = self._authored_binding(session, version_id)
            if (row["world_id"], row["place_id"], row["region_id"]) != (
                binding.world_id,
                binding.place_id,
                binding.region_id,
            ):
                raise UnavailableSocietyInput("society scope disagrees with configured binding")
            last = connection.execute(
                "select max(input_seq) as seq from world_society_input where "
                "workspace_id=%s and society_id=%s",
                (session.workspace_id, row["society_id"]),
            ).fetchone()["seq"]
            if last is None:
                raise UnavailableSocietyInput("society input history is unavailable")
            ground = self._authored_ground(connection, session, binding)
            version = self._authored_version(connection, session, binding)
            document = self._authored_compose(connection, binding, ground, version, last + 1)
            SocietyRepository(
                connection,
                session.workspace_id,
                world_id=binding.world_id,
                input_authorizer=lambda doc: self.authorize(connection, session, doc),
            ).record_input(version_id, document)
