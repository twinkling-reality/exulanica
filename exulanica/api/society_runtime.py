"""Explicit host-configured society composition and current dependency authorization.

Configuration is an immutable, workspace/version-scoped registration, not request input.
No frame is inferred, no admission is created, and no source rights are granted here.
The host wires these callbacks into Services/app state and the accepted-edit transaction.

One runtime serves two kinds of registration. A district binding composes an admitted
interpretation of real city sources. An authored-world binding composes a saved world over the
flat ground its own structural snapshot declares, with no admitted source and no district.
A version is registered under one kind or the other, never both.

A saved world needs no host registration. When the person asks for inhabitants in a version
whose snapshot is the built-in authored starter, the binding is derived from that world itself:
its region is the snapshot's own and its place identity is derived from the version, the way the
society's identity already is. A host registration for the same version takes precedence, and a
version whose snapshot is anything else derives nothing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final, Literal

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.canonical import canonical_json
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.db.session import set_workspace
from exulanica.environment.admission import MAX_ENVIRONMENT_PAYLOAD_BYTES
from exulanica.environment.district_geometry import DistrictGeometry, segment_blocked
from exulanica.environment.district_interpretation import Frame, validate_interpretation
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.selection.validation import Session
from exulanica.store.base import ContentAddressedStore
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.errors import InvalidStructuralData, UnknownWorldResource
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.society import UnavailableSocietyInput, society_state_sha256
from exulanica.world.society_authored_ground import (
    SocietyGround,
    StandingPolicy,
    build_authored_ground_society_input_v3,
    read_authored_ground,
)
from exulanica.world.society_composition import (
    build_society_input,
    keep_registry,
    policy_dependency_refs,
    validate_recorded_registry,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_input_policy import (
    LEGACY_COMPOSITION,
    LOCAL_INPUT,
    input_profile,
    is_authored_ground,
)
from exulanica.world.society_input_policy import (
    composition_profile as policy_for_input,
)
from exulanica.world.society_living import current_routine
from exulanica.world.society_planner import input_sha256, validate_society_input
from exulanica.world.society_repository import SocietyRepository

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=500)]
Millimetre = Annotated[StrictInt, Field(ge=-1_000_000_000, le=1_000_000_000)]
_OPERATIONS = ("display", "persist", "modify", "compose")

#: The name a saved world's society place is derived under, from the authored version's identity,
#: exactly as the society's own identity is derived under ``exulanica-society/v1``. The place names
#: where in the workspace the society lives; it claims nothing about anywhere on the Earth.
SAVED_WORLD_PLACE_NAME: Final = "exulanica-society/saved-world-place/v1"
#: The prefix of a derived binding's identity. The whole binding is a function of the authored
#: version and its snapshot, so a runtime built again from nothing derives it byte for byte.
SAVED_WORLD_BINDING_PREFIX: Final = "exulanica.society-saved-world/v1:"


def saved_world_place_id(version_id: uuid.UUID) -> uuid.UUID:
    """The place identity a saved world's society binds, derived from its authored version."""
    return uuid.uuid5(version_id, SAVED_WORLD_PLACE_NAME)


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
        if is_authored_ground(input_profile(composition_profile)):
            raise ValueError("the authored-ground policy is selected by binding, not by profile")
        self._composition_profile = composition_profile
        # Where a saved world's destinations seat their occupants, from the same catalog figures
        # the living society keeps its standing spacing with.
        policy = current_routine().policy
        self._standing = StandingPolicy(
            spacing_mm=policy["standing_spacing_mm"], radius_mm=policy["standing_radius_mm"]
        )
        self._bindings: dict[tuple[uuid.UUID, uuid.UUID], SocietyRuntimeBinding] = {}
        self._authored: dict[tuple[uuid.UUID, uuid.UUID], AuthoredWorldSocietyBinding] = {}
        # Freeze caller-owned dictionaries by serializing once; no mutable registry leaks out. The
        # registry this runtime composes with is kept in the store under its own digest, so an
        # input composed under it keeps authorising after the registry changes.
        self._registry_bytes, self._registry_sha256 = keep_registry(store, reviewed_affordances)
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

    def _authored_scope(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> tuple[AuthoredWorldSocietyBinding, SocietyGround]:
        """The saved world's binding and the ground it composes over. Call under ``_lock``.

        A host registration wins. Without one, a version whose structural snapshot is the
        built-in authored starter derives its binding from the world itself; any other version
        is refused with the reason, and a version registered as a district composes one way only.
        """
        registered = self._authored.get((session.workspace_id, version_id))
        if registered is not None:
            return registered, self._authored_ground(connection, session, registered)
        if (session.workspace_id, version_id) in self._bindings:
            raise UnavailableSocietyInput("this version is registered to compose a district")
        row = connection.execute(
            "select world_id,source_snapshot_id from world_alternate_version "
            "where workspace_id=%s and version_id=%s",
            (session.workspace_id, version_id),
        ).fetchone()
        if row is None:
            raise UnavailableSocietyInput("this workspace holds no authored version by that id")
        ground = self._read_ground(connection, session, row["world_id"], row["source_snapshot_id"])
        binding = AuthoredWorldSocietyBinding(
            binding_id=f"{SAVED_WORLD_BINDING_PREFIX}{version_id}",
            workspace_id=session.workspace_id,
            world_id=row["world_id"],
            version_id=version_id,
            source_snapshot_id=row["source_snapshot_id"],
            place_id=saved_world_place_id(version_id),
            region_id=ground.region_id,
        )
        return binding, ground

    def saved_world_place(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> uuid.UUID:
        """The place a saved world's society binds, made on the person's own request.

        Call inside the transaction that creates the society, so a refusal leaves no place
        behind. A host registration names a place the host made; a derived one is made here,
        once, and asking again finds the same row.
        """
        with connection.transaction():
            self._lock(connection, session)
            binding, _ = self._authored_scope(connection, session, version_id)
            if binding.binding_id.startswith(SAVED_WORLD_BINDING_PREFIX):
                connection.execute(
                    "insert into place(workspace_id,place_id) values(%s,%s) on conflict do nothing",
                    (session.workspace_id, binding.place_id),
                )
            return binding.place_id

    @staticmethod
    def _lock(connection: psycopg.Connection, session: Session, *, assets: bool = True) -> None:
        connection.row_factory = dict_row
        set_workspace(connection, session.workspace_id)
        # Same order as authored edits/structural invalidation, then source withdrawal exclusion.
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880024))",
            (str(session.workspace_id),),
        )
        if assets:
            lock_asset_reads_until_commit(
                connection,
                outside=(
                    "a society's inputs are locked only inside the transaction that records them"
                ),
            )

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

    def _registry(self, digest: str) -> dict[str, Any]:
        """The affordance registry with this digest: the current one, or one kept in the store."""
        if digest == self._registry_sha256:
            return json.loads(self._registry_bytes)
        try:
            data = self._blob(digest)
        except UnavailableSocietyInput as exc:
            raise UnavailableSocietyInput(
                "the affordance registry this input was composed under is not held here"
            ) from exc
        try:
            registry = json.loads(data)
            if canonical_json(registry) != data:
                raise ValueError("a registry is stored in its canonical form")
            validate_recorded_registry(registry)
        except ValueError as exc:
            raise UnavailableSocietyInput(
                "the affordance registry this input names is not a reviewed registry"
            ) from exc
        return registry

    def _recorded_registry(self, document: dict) -> tuple[str, dict[str, Any]]:
        """The registry a stored input was composed under, as the input itself names it."""
        refs = [
            ref
            for ref in document["dependency_refs"]
            if ref["kind"] == "society_affordance_registry"
        ]
        if len(refs) != 1 or refs[0]["identity"] != policy_for_input(document["profile"]):
            raise UnavailableSocietyInput("runtime registration or registry binding drift")
        return refs[0]["sha256"], self._registry(refs[0]["sha256"])

    def _asset(
        self,
        connection: psycopg.Connection,
        key: str,
        digest: str,
        registry: Mapping[str, dict[str, Any]],
    ) -> None:
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
        self,
        binding: SocietyRuntimeBinding,
        *,
        composition: str | None = None,
        registry_sha256: str | None = None,
    ) -> list[dict[str, str]]:
        """The policy references an input binds: its composition, registration and registry.

        Left out, the composition is this runtime's and the registry its current one, as a new
        input is composed; a stored input passes the ones it recorded.
        """
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
                "sha256": self._registry_sha256 if registry_sha256 is None else registry_sha256,
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
                self._asset(connection, assignment["asset_key"], obj.asset_sha256, registry)
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
        place_id: uuid.UUID | None,
        region_id: str,
    ) -> dict:
        """The first input a new society consumes; ``place_id`` None names a saved world's own."""
        if (session.workspace_id, version_id) not in self._bindings:
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
        if is_authored_ground(document["profile"]):
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
            # A stored input is held to the registry it recorded, never to whichever registry this
            # runtime holds now; a fresh one was compared byte for byte with a current composition.
            registry_sha256, registry = self._recorded_registry(document)
            required = {
                (r["kind"], r["identity"], r["sha256"])
                for r in self._refs(binding)
                + self._policy_refs(
                    binding,
                    composition=policy_for_input(document["profile"]),
                    registry_sha256=registry_sha256,
                )
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
                    self._asset(connection, ref["identity"], ref["sha256"], registry)

    def authored_edit(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> None:
        """Run inside each accepted edit transaction, after its immutable edit row is appended."""
        if (session.workspace_id, version_id) not in self._bindings:
            self._authored_world_edit(connection, session, version_id)
            return
        with connection.transaction():
            self._lock(connection, session)
            row = connection.execute(
                "select society_id,world_id,place_id,region_id,engine_version from world_society "
                "where workspace_id=%s and version_id=%s",
                (session.workspace_id, version_id),
            ).fetchone()
            # Only an engine that consumes inputs reacts to an edit; an engine the table does not
            # state is refused by name rather than passed over.
            if row is None or not society_engine(row["engine_version"]).takes_inputs:
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

    def _read_ground(
        self,
        connection: psycopg.Connection,
        session: Session,
        world_id: str,
        snapshot_id: uuid.UUID,
    ) -> SocietyGround:
        try:
            ground = read_authored_ground(connection, session.workspace_id, world_id, snapshot_id)
        except InvalidStructuralData as exc:
            raise UnavailableSocietyInput(f"authored ground is unreadable: {exc}") from exc
        if ground is None:
            raise UnavailableSocietyInput("registered structural snapshot is unavailable")
        return ground

    def _authored_ground(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: AuthoredWorldSocietyBinding,
    ) -> SocietyGround:
        ground = self._read_ground(
            connection, session, binding.world_id, binding.source_snapshot_id
        )
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
        self,
        binding: AuthoredWorldSocietyBinding,
        ground: SocietyGround,
        composition: str,
        registry: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        return policy_dependency_refs(
            composition_profile=composition,
            version_id=binding.version_id,
            registration=ground.registration(),
            reviewed_affordances=registry,
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
                self._asset(connection, assignment["asset_key"], obj.asset_sha256, registry)
        except UnavailableSocietyInput as exc:
            reason = str(exc)
        return build_authored_ground_society_input_v3(
            ground=ground,
            version=version,
            input_seq=seq,
            dependency_refs=self._authored_refs(binding, ground),
            availability="available" if reason is None else "unavailable",
            unavailable_reason=reason,
            reviewed_affordances=registry,
            segment_blocked=segment_blocked,
            standing=self._standing,
        )

    def _authored_initial_input(
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        place_id: uuid.UUID | None,
        region_id: str,
    ) -> dict:
        with connection.transaction():
            self._lock(connection, session)
            binding, ground = self._authored_scope(connection, session, version_id)
            requested = binding.place_id if place_id is None else place_id
            if requested != binding.place_id or region_id != binding.region_id:
                raise UnavailableSocietyInput("requested place/region has no configured binding")
            version = self._authored_version(connection, session, binding)
            return self._authored_compose(connection, binding, ground, version, 1)

    def _authored_authorize(
        self, connection: psycopg.Connection, session: Session, document: dict
    ) -> None:
        with connection.transaction():
            self._lock(connection, session)
            binding, ground = self._authored_scope(
                connection, session, uuid.UUID(document["version_id"])
            )
            if document["world_id"] != binding.world_id:
                raise UnavailableSocietyInput("society input scope binding drift")
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
            # A stored input is held to the policy its own profile names and the registry it
            # recorded, never to whichever this runtime would choose for a new one.
            _, registry = self._recorded_registry(document)
            required = {
                (r["kind"], r["identity"], r["sha256"])
                for r in self._authored_refs(binding, ground)
                + self._authored_policy_refs(
                    binding, ground, policy_for_input(document["profile"]), registry
                )
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
                    self._asset(connection, ref["identity"], ref["sha256"], registry)

    def _authored_world_edit(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> None:
        with connection.transaction():
            # Every accepted edit in every world reaches here. The asset read lock is global, so
            # it is taken only once this version is known to hold a society that reads assets,
            # in the same order as always: workspace first, then assets.
            self._lock(connection, session, assets=False)
            row = connection.execute(
                "select society_id,world_id,place_id,region_id,engine_version from world_society "
                "where workspace_id=%s and version_id=%s",
                (session.workspace_id, version_id),
            ).fetchone()
            if row is None or not society_engine(row["engine_version"]).takes_inputs:
                return
            lock_asset_reads_until_commit(
                connection,
                outside=(
                    "an accepted edit reaches a society only inside the transaction that records it"
                ),
            )
            genesis = connection.execute(
                "select document->>'profile' as profile from world_society_input "
                "where workspace_id=%s and society_id=%s and input_seq=1",
                (session.workspace_id, row["society_id"]),
            ).fetchone()
            if genesis is None or not is_authored_ground(genesis["profile"]):
                # A district society whose host registration is gone. Its edits need that
                # registration, exactly as they always have.
                raise UnavailableSocietyInput(
                    "society frame binding is not configured for this scope"
                )
            binding, ground = self._authored_scope(connection, session, version_id)
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
            version = self._authored_version(connection, session, binding)
            document = self._authored_compose(connection, binding, ground, version, last + 1)
            SocietyRepository(
                connection,
                session.workspace_id,
                world_id=binding.world_id,
                input_authorizer=lambda doc: self.authorize(connection, session, doc),
            ).record_input(version_id, document)
