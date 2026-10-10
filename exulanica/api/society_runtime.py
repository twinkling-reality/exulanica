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

import datetime as dt
import hashlib
import json
import logging
import threading
import uuid
import weakref
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Final, Literal

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.arrival_source import (
    ArrivalAuthority,
    arrival_authority_under_lock,
    buffer_arrival_authority,
    current_arrival_descriptor,
)
from exulanica.canonical import canonical_json
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.db.session import set_workspace
from exulanica.environment.admission import MAX_ENVIRONMENT_PAYLOAD_BYTES
from exulanica.environment.district_geometry import DistrictGeometry, segment_blocked
from exulanica.environment.district_interpretation import Frame, validate_interpretation
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.grammar.errors import CatalogError
from exulanica.selection.validation import Session
from exulanica.store.base import ContentAddressedStore
from exulanica.world.arrival_selection import ArrivalDescriptor
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.composers import site_plan
from exulanica.world.errors import InvalidStructuralData, UnknownWorldResource
from exulanica.world.generated_worlds import generation_receipt, states_site, town_records
from exulanica.world.kinds.worker import (
    PLACE_SECONDS,
    KindWorkWaiting,
    kind_worker,
    place_job,
    place_key,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AuthoredObject
from exulanica.world.placed_things import WorkspaceKindReference
from exulanica.world.society import (
    SocietyBytesNotRead,
    SocietyPlaceWaiting,
    UnavailableSocietyInput,
    announced_inputs,
    society_state_sha256,
)
from exulanica.world.society_authored_ground import (
    SocietyGround,
    StandingPolicy,
    authored_input_region,
    build_authored_ground_society_input_v3,
    build_authored_ground_society_input_v4,
    build_authored_ground_society_input_v5,
    objects_in_region,
    read_authored_ground,
)
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_city_place import CityObstructions, city_obstructions
from exulanica.world.society_composition import (
    build_society_input,
    keep_registry,
    policy_dependency_refs,
    validate_recorded_registry,
    workspace_obstacle,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_input_policy import (
    ARRIVAL_INPUTS,
    AUTHORED_GROUND_COMPOSITION_V5,
    LEGACY_COMPOSITION,
    LIVING_INPUTS,
    LOCAL_INPUT,
    THING_INPUTS,
    WALKING_SURFACES_BY_FAMILY,
    WALKING_SURFACES_COMPOSITION,
    WALKING_SURFACES_COMPOSITION_V2,
    WALKING_SURFACES_COMPOSITION_V3,
    input_profile,
    is_authored_ground,
)
from exulanica.world.society_input_policy import (
    composition_profile as policy_for_input,
)
from exulanica.world.society_living import current_routine, input_routine, town_routine_of
from exulanica.world.society_place import place_sha256
from exulanica.world.society_planner import input_sha256, validate_society_input
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.town_people import TownPeopleRefused, people_frame

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


_LOG = logging.getLogger(__name__)

#: The name the log gives an input authorized without being announced (``inputs_ahead`` in
#: :mod:`exulanica.world.society`): a defect in its caller, whose bytes are then read under the
#: asset read lock, as every input's were before inputs were read ahead.
NOT_ANNOUNCED: Final = "society_input_not_announced"
_RACE: Final = (
    "a reviewed asset changed between reading a society input's stored bytes and taking the "
    "asset read lock; ask again"
)

#: A reviewed asset row as a society input's check depends on it: its bytes, their size and its
#: licence's bytes, or ``None`` where no row names the key.
ReviewedRow = tuple[str, int, str] | None


@dataclass(slots=True)
class _ReadFirst:
    """The stored bytes one transaction's society inputs depend on, read before the asset read lock.

    ``found`` is keyed by content digest and the size the check held it to, or ``None`` where it
    checks the hash alone. A value is the bytes where they are kept (a recorded registry, a
    district's artifacts), ``None`` for bytes checked and let go, or the words of the refusal
    checking them raised. ``rows`` is each reviewed asset row as it was when its bytes were read,
    so a row that names other bytes under the lock is known to have changed in between.
    ``locked`` is whether this transaction's society has taken the lock, after which nothing is
    read ahead. ``read`` holds what was already read ahead, so it is read once a transaction.
    ``towns`` holds, by world and snapshot, what a generated world's society is composed from:
    its records generated again through its receipt and the place they make, or the refusal
    reading them raised. Generating a world takes a noticeable time, and every guarded write in
    the deployment waits on the asset read lock while it is held, so it is done before the lock.
    """

    found: dict[tuple[str, int | None], bytes | str | None] = field(default_factory=dict)
    rows: dict[str, ReviewedRow] = field(default_factory=dict)
    read: set[tuple[str, str]] = field(default_factory=set)
    towns: dict[tuple[str, uuid.UUID], _TownRead] = field(default_factory=dict)
    arrivals: dict[str, ArrivalAuthority] = field(default_factory=dict)
    locked: bool = False


@dataclass(frozen=True, slots=True)
class _TownRead:
    """A generated world's records as its receipt generated them before the asset read lock: the
    receipt's digest, the records, and the place they make under the living routine a district
    reads, or the refusal generating them raised. A living town's place is made from the records
    only when a living input is composed, under the routine that input records
    (``living_places``, by the routine's digest), so a purposeful town's input never pays for it."""

    receipt_sha256: str | None
    place: Mapping[str, Any] | None
    refusal: str | None
    records: tuple[object, ...] = ()
    #: A town's receipt, which pins the routine its people are made under.
    receipt: Mapping[str, Any] | None = None
    living_places: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    #: For a world made from a world kind, its receipt and the routine it names: the place and the
    #: routine its society lives under come from it (:mod:`exulanica.world.composers.site_plan`),
    #: not from the town's, the routine read here, before either lock.
    site_receipt: Mapping[str, Any] | None = None
    site_routine: RoutineModel | None = None
    #: For a world made from a world kind whose place the kind worker has not made yet, why: raised
    #: when the input is composed (503 ``kind_work_*`` with when to ask again), and asked again
    #: later, the place is read from what the worker kept.
    waiting: KindWorkWaiting | None = None
    #: For a world made from a world kind whose place cannot be made, why, by name (such as
    #: ``kind_graph_over_budget``).
    place_refusal: str | None = None
    #: A town's own buildings, street furniture and trees, read from its records with its place,
    #: which a society of things keeps its things' places clear of.
    obstructions: CityObstructions | None = None


def _stored_site_place(
    stored: Mapping[str, Any] | None, ground: SocietyGround, routine: RoutineModel
) -> dict[str, Any] | None:
    """The place a site world's last stored input carries, when it is this ground's, made from
    this snapshot (which names the receipt) under the routine the receipt names, and sealed by the
    digest the input's ``site_place`` reference states; None otherwise."""
    if stored is None or stored.get("profile") not in LIVING_INPUTS:
        return None
    living = stored.get("living")
    if not isinstance(living, dict):
        return None
    place = living.get("place")
    if not isinstance(place, dict):
        return None
    if (
        stored.get("district_id") != ground.place_id
        or stored.get("base_artifact_sha256") != ground.snapshot_sha256
        or living.get("routine") != routine.binding()
        or place.get("place_id") != ground.place_id
        or place.get("routine_sha256") != routine.sha256
    ):
        return None
    stated = [
        ref["sha256"]
        for ref in stored.get("dependency_refs", ())
        if ref.get("kind") == "site_place" and ref.get("identity") == ground.place_id
    ]
    if stated != [place.get("document_sha256")] or place_sha256(place) != stated[0]:
        return None
    return place


def _site_read(
    connection: psycopg.Connection,
    binding: AuthoredWorldSocietyBinding,
    ground: SocietyGround,
    stored: Mapping[str, Any] | None = None,
) -> _TownRead:
    """A site world's place, never made or waited for here, since this is read inside a
    transaction that holds the workspace's lock: the place its last stored input carries
    (``stored``), else the one the kind worker keeps (made with the world, or before the
    transaction by :meth:`SocietyRuntime.prepare_saved_world`). One neither holds is asked of the
    worker without waiting, so asking again reads it, and is answered as waiting."""
    digest, receipt = generation_receipt(
        connection, binding.workspace_id, binding.world_id, ground.snapshot_id
    )
    try:
        routine = site_plan.receipt_routine(receipt)
    except InvalidStructuralData as exc:
        return _TownRead(None, None, str(exc))
    place = _stored_site_place(stored, ground, routine)
    if place is None:
        worker = kind_worker()
        workspace = str(binding.workspace_id)
        key = place_key(workspace, digest, ground.place_id)
        answer = worker.places.get(key)
        if answer is None:
            outcome = worker.run(
                key,
                0,
                place_job,
                workspace,
                dict(receipt),
                digest,
                ground.place_id,
                workspace=workspace,
                kept=worker.places,
            )
            if outcome.status != "done" or outcome.value is None:
                waiting = KindWorkWaiting(outcome.status, kept=True, reason=outcome.reason)
                return _TownRead(None, None, None, waiting=waiting)
            answer = outcome.value
        if answer["status"] != "done":
            return _TownRead(None, None, None, place_refusal=str(answer["detail"]))
        place = answer["place"]
    return _TownRead(digest, place, None, (), site_receipt=receipt, site_routine=routine)


#: What a saved world's input says of the edit it follows, not of what its society reads: its
#: place in the sequence, the version's edit cursor, and the digest over both.
_EDIT_CURSOR_FIELDS: Final = frozenset({"input_seq", "authored_state", "document_sha256"})
#: What only a society's first input states (the ability modules its minutes run for its whole
#: life, and what a town's people are made from), so a later input's not stating it is no
#: difference.
_FIRST_INPUT_ONLY: Final = frozenset({"modules", "people"})


def _reads_the_same(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Whether two successive inputs differ only in which edit they follow.

    Such an edit changed nothing the society reads, so it appends no input: an object in another
    region of the world, or a photograph hidden or moved. The modules only a first input states
    are no difference either. Every other field is what the society reads, and any difference
    there is a new input.
    """

    def read(document: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in document.items()
            if key not in _EDIT_CURSOR_FIELDS and key not in _FIRST_INPUT_ONLY
        }

    return read(previous) == read(current)


def _reviewed_view(row: Mapping[str, Any] | None) -> ReviewedRow:
    if row is None:
        return None
    return (row["content_sha256"], row["byte_size"], row["licence_sha256"])


def _pins_arrival(document: dict[str, Any]) -> bool:
    """Whether an input pins the opening source a person arrives at: every fourth-composition
    input, and a things-composition input whose ground states no arrival of its own."""
    return document.get("profile") in ARRIVAL_INPUTS and document.get("arrival") is not None


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
        # What each open connection's current transaction read before the asset read lock, with
        # the time that transaction began: one entry per connection (one database session),
        # replaced when a later transaction begins and gone with the connection.
        self._transactions: weakref.WeakKeyDictionary[
            psycopg.Connection, tuple[dt.datetime, _ReadFirst]
        ] = weakref.WeakKeyDictionary()
        self._transactions_lock = threading.Lock()
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
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        region_id: str | None = None,
    ) -> tuple[AuthoredWorldSocietyBinding, SocietyGround]:
        """The saved world's binding and the ground it composes over. Call under ``_lock``.

        A host registration wins. Without one, a version whose structural snapshot the society
        ground catalog states a ground for (the built-in starter, or a world made from
        photographs) derives its binding from the world itself; any other version is refused with
        the reason, and a version registered as a district composes one way only. ``region_id`` is
        the region the society stands in: the one a creation or an input names, else the one the
        version's society recorded. A world of several regions is refused without one.
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
        if region_id is None:
            stored = connection.execute(
                "select region_id from world_society where workspace_id=%s and world_id=%s "
                "and version_id=%s",
                (session.workspace_id, row["world_id"], version_id),
            ).fetchone()
            region_id = None if stored is None else stored["region_id"]
        ground = self._read_ground(
            connection, session, row["world_id"], row["source_snapshot_id"], region_id=region_id
        )
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

    def prepare_saved_world(
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        region_id: str | None = None,
    ) -> None:
        """Before the transaction that brings people into a saved world: a site world's place,
        made in the kind worker and waited for here, holding no transaction and so no lock, and
        kept for that transaction to read (:func:`_site_read`, which never waits). A place the
        worker does not make in time is refused as :class:`KindWorkWaiting`; anything else this
        reads is read again, and refused if it must be, under the lock.
        """
        if connection.info.transaction_status != TransactionStatus.IDLE:
            raise RuntimeError("a site world's place is waited for outside any transaction")
        try:
            binding, ground = self._authored_scope(connection, session, version_id, region_id)
            if ground.navigation_form != "walking_surfaces" or not states_site(
                connection, binding.workspace_id, binding.world_id, ground.snapshot_id
            ):
                return
            digest, receipt = generation_receipt(
                connection, binding.workspace_id, binding.world_id, ground.snapshot_id
            )
        except (UnavailableSocietyInput, InvalidStructuralData):
            return
        worker = kind_worker()
        workspace = str(binding.workspace_id)
        outcome = worker.run(
            place_key(workspace, digest, ground.place_id),
            PLACE_SECONDS,
            place_job,
            workspace,
            dict(receipt),
            digest,
            ground.place_id,
            workspace=workspace,
            kept=worker.places,
        )
        if outcome.status != "done":
            raise KindWorkWaiting(outcome.status, kept=True, reason=outcome.reason)

    def saved_world_place(
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        region_id: str | None = None,
    ) -> uuid.UUID:
        """The place a saved world's society binds, made on the person's own request.

        Call inside the transaction that creates the society, so a refusal leaves no place
        behind. A host registration names a place the host made; a derived one is made here,
        once, and asking again finds the same row. ``region_id`` is the region the society is
        asked for, which a world of several regions needs.
        """
        with connection.transaction():
            self._lock(connection, session)
            binding, _ = self._authored_scope(connection, session, version_id, region_id)
            if binding.binding_id.startswith(SAVED_WORLD_BINDING_PREFIX):
                # Writing a place takes the shared side of the asset read lock (its table's
                # mutation guard) and holds it until the commit, and a holder of either side reads
                # nothing from the store. So the creation's first input is read first, then the
                # lock is taken, and only then is the place written; the input composed next in
                # this transaction is answered from that read.
                read = self._transaction_read(connection)
                self._read_ahead(connection, session, read, composing=binding)
                self._lock_assets(connection, read)
                connection.execute(
                    "insert into place(workspace_id,place_id) values(%s,%s) on conflict do nothing",
                    (session.workspace_id, binding.place_id),
                )
            return binding.place_id

    @staticmethod
    def _lock(connection: psycopg.Connection, session: Session) -> None:
        """The workspace's lock, the first of the two a society takes, in the order authored edits
        and structural invalidation take them; the asset read lock follows (:meth:`_lock_assets`).
        """
        connection.row_factory = dict_row
        set_workspace(connection, session.workspace_id)
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880024))",
            (str(session.workspace_id),),
        )

    @staticmethod
    def _lock_assets(connection: psycopg.Connection, read: _ReadFirst) -> None:
        """The asset read lock, after the workspace's, once everything to be read is read."""
        lock_asset_reads_until_commit(
            connection,
            outside="a society's inputs are locked only inside the transaction that records them",
        )
        read.locked = True

    @staticmethod
    def _read_town_ahead(
        connection: psycopg.Connection,
        binding: AuthoredWorldSocietyBinding,
        ground: SocietyGround,
        read: _ReadFirst,
        stored: Mapping[str, Any] | None = None,
    ) -> None:
        """Generate a generated world's records and their place before the asset read lock.

        For a ground whose people walk the world's own surfaces, once a transaction: a town's
        records through the world's receipt (:func:`town_records`, which generates them again on a
        cold cache) and the place they make; a site world's place as its last stored input
        (``stored``) carries it or the kind worker keeps it (:func:`_site_read`). A refusal is
        kept and raised when the input is composed, so a transaction that composes nothing is not
        refused for a world it does not read.
        """
        key = (binding.world_id, ground.snapshot_id)
        if read.locked or ground.navigation_form != "walking_surfaces" or key in read.towns:
            return
        try:
            if states_site(connection, binding.workspace_id, binding.world_id, ground.snapshot_id):
                read.towns[key] = _site_read(connection, binding, ground, stored)
                return
            generated = town_records(
                connection, binding.workspace_id, binding.world_id, ground.snapshot_id
            )
        except InvalidStructuralData as exc:
            read.towns[key] = _TownRead(None, None, str(exc))
            return
        place = walking_surfaces_place(ground.place_id, generated.records)
        read.towns[key] = _TownRead(
            generated.receipt_sha256,
            place,
            None,
            tuple(generated.records),
            receipt=generated.receipt,
            # Held to their shapes by the place just made from them.
            obstructions=city_obstructions(generated.records, checked=True),
        )

    @staticmethod
    def _made_under(town: _TownRead) -> RoutineModel:
        """The routine a town's people are made under, as its receipt pins it."""
        if town.receipt is None:
            raise UnavailableSocietyInput("the town's receipt was not read before the lock")
        try:
            return town_routine_of(town.receipt)
        except (CatalogError, ValueError) as exc:
            raise UnavailableSocietyInput(
                f"the routine the town was made under cannot be read: {exc}"
            ) from exc

    @staticmethod
    def _living_place(
        ground: SocietyGround, town: _TownRead, routine: RoutineModel
    ) -> Mapping[str, Any]:
        """The living place a town's records make under ``routine``, made once a read."""
        place = town.living_places.get(routine.sha256)
        if place is None:
            try:
                place = walking_surfaces_place(ground.place_id, town.records, routine)
            except (CatalogError, InvalidStructuralData, ValueError) as exc:
                raise UnavailableSocietyInput(
                    f"the town's living place could not be made: {exc}"
                ) from exc
            town.living_places[routine.sha256] = place
        return place

    def _transaction_read(self, connection: psycopg.Connection) -> _ReadFirst:
        """What this transaction read before the asset read lock; call inside the transaction.

        A transaction is known by its connection and the time it began, which is fixed for the
        whole transaction, savepoints included: a later transaction on the same connection begins
        with nothing read, and so does each statement of a connection outside a transaction.
        """
        began = connection.execute("select transaction_timestamp() as began").fetchone()["began"]
        with self._transactions_lock:
            held = self._transactions.get(connection)
            if held is not None and held[0] == began:
                return held[1]
            read = _ReadFirst()
            self._transactions[connection] = (began, read)
            return read

    def _version(
        self, connection: psycopg.Connection, session: Session, binding: SocietyRuntimeBinding
    ) -> AlternateVersion:
        # Rows only: a district reads which placements its version holds, never whether their
        # bytes are present, and this is read under the asset read lock.
        try:
            version = WorldObjectRepository(
                connection, session.workspace_id, world_id=binding.world_id, store=None
            ).version(binding.version_id, with_availability=False)
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

    def _admitted_sources(
        self, connection: psycopg.Connection, session: Session, binding: SocietyRuntimeBinding
    ) -> dict[str, dict]:
        """The district's admitted source rows, each current and bound exactly as registered."""
        return {
            source.dataset_id: self._admitted_source(connection, session, binding, source)
            for source in binding.sources
        }

    @staticmethod
    def _source_key(source: RuntimeSourceBinding) -> str:
        """Where the record read ahead keeps an admitted source's row, beside reviewed assets'."""
        return f"source:{source.admission_id}"

    def _admitted_source(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: SocietyRuntimeBinding,
        source: RuntimeSourceBinding,
    ) -> dict:
        """One admitted source's row, current and bound exactly as registered, or its refusal."""
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
        return row

    def _district(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: SocietyRuntimeBinding,
        read: _ReadFirst,
    ) -> tuple[dict, bytes, DistrictGeometry]:
        rows = self._admitted_sources(connection, session, binding)
        for source in binding.sources:
            size = rows[source.dataset_id]["byte_size"]
            self._answer(
                read,
                source.source_sha256,
                size,
                reviewed=(self._source_key(source), (source.source_sha256, size, "")),
            )
        base_bytes = self._kept(read, binding.base_artifact_sha256)
        data = self._kept(read, binding.interpretation_artifact_sha256)
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

    def _registry(self, digest: str, read: _ReadFirst) -> dict[str, Any]:
        """The affordance registry with this digest: the current one, or one kept in the store."""
        if digest == self._registry_sha256:
            return json.loads(self._registry_bytes)
        try:
            data = self._kept(read, digest)
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

    def _recorded_registry(self, document: dict, read: _ReadFirst) -> tuple[str, dict[str, Any]]:
        """The registry a stored input was composed under, as the input itself names it."""
        refs = [
            ref
            for ref in document["dependency_refs"]
            if ref["kind"] == "society_affordance_registry"
        ]
        if len(refs) != 1 or refs[0]["identity"] != policy_for_input(document["profile"]):
            raise UnavailableSocietyInput("runtime registration or registry binding drift")
        return refs[0]["sha256"], self._registry(refs[0]["sha256"], read)

    @staticmethod
    def _reviewed_row(connection: psycopg.Connection, key: str) -> dict[str, Any] | None:
        return connection.execute(
            "select content_sha256,byte_size,licence_id,licence_sha256 from world_reviewed_asset "
            "where asset_key=%s",
            (key,),
        ).fetchone()

    def _workspace_obstacles(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        objects: Iterable[AuthoredObject],
    ) -> dict[str, dict[str, Any]]:
        """Each placed workspace asset's obstacle, from what its preparation measured.

        Rows only, so it is asked under the asset read lock. The preparation stands for its object
        whether or not its admission was withdrawn since: a withdrawn object stays where it was
        placed, and blocks walking, until it is removed. A preparation that does not record the
        object's exact output is a binding drift, and the input is unavailable by that name.
        """
        obstacles: dict[str, dict[str, Any]] = {}
        for obj in objects:
            if obj.removed or obj.workspace_preparation_id is None:
                continue
            row = connection.execute(
                "select output_sha256, width_mm, depth_mm from workspace_preparation "
                "where workspace_id = %s and preparation_id = %s",
                (workspace_id, obj.workspace_preparation_id),
            ).fetchone()
            if row is None or row["output_sha256"] != obj.asset_sha256 or row["width_mm"] is None:
                raise UnavailableSocietyInput("workspace asset preparation binding drift")
            obstacles[str(obj.workspace_preparation_id)] = workspace_obstacle(
                obj.workspace_preparation_id, row["width_mm"], row["depth_mm"]
            )
        return obstacles

    @staticmethod
    def _made_kinds(
        connection: psycopg.Connection, workspace_id: uuid.UUID, things: Iterable[Any]
    ) -> dict[str, dict[str, Any]]:
        """What a society runs of each kind its workspace keeps that a placed thing names: the
        kind's run form, by its digest (:meth:`~exulanica.world.thing_store.ThingStore.run_form`).

        Rows only, so it is asked under the asset read lock. A thing removed, or whose kind is
        gone, is passed by, and so is a kind whose run form the store cannot build: the composer
        leaves a thing of such a kind out and names the thing among those gone.
        """
        from exulanica.world.thing_store import ThingStore

        store = ThingStore(connection, workspace_id, None)
        forms: dict[str, dict[str, Any]] = {}
        for thing in things:
            kind = thing.kind
            if thing.removed or thing.kind_gone or not isinstance(kind, WorkspaceKindReference):
                continue
            if kind.sha256 in forms:
                continue
            form = store.run_form(kind.sha256)
            if form is not None:
                forms[kind.sha256] = form
        return forms

    def _workspace_ref(
        self, connection: psycopg.Connection, session: Session, ref: Mapping[str, str]
    ) -> None:
        """A stored input's workspace asset ref still names its preparation's recorded output."""
        row = connection.execute(
            "select 1 from workspace_preparation where workspace_id = %s "
            "and preparation_id = %s and output_sha256 = %s",
            (session.workspace_id, uuid.UUID(ref["identity"]), ref["sha256"]),
        ).fetchone()
        if row is None:
            raise UnavailableSocietyInput("workspace asset preparation binding drift")

    def _asset(
        self,
        connection: psycopg.Connection,
        key: str,
        digest: str,
        registry: Mapping[str, dict[str, Any]],
        read: _ReadFirst,
    ) -> None:
        """Whether a placed asset is still the reviewed one, its bytes and licence whole.

        Asked under the asset read lock: the rows are read here and the bytes are answered from
        what the transaction read before it.
        """
        assignment = registry.get(digest)
        if assignment is None or assignment["asset_key"] != key:
            raise UnavailableSocietyInput("reviewed affordance assignment is unavailable")
        row = self._reviewed_row(connection, key)
        if row is None or row["content_sha256"] != digest or row["licence_id"] != "CC0-1.0":
            raise UnavailableSocietyInput("reviewed authored asset binding drift")
        reviewed = (key, _reviewed_view(row))
        self._answer(read, digest, row["byte_size"], reviewed=reviewed)
        self._answer(read, row["licence_sha256"], None, reviewed=reviewed)

    # -- reading before the asset read lock -------------------------------------------------------

    def _answer(
        self,
        read: _ReadFirst,
        digest: str,
        size: int | None,
        *,
        keep: bool = False,
        reviewed: tuple[str, ReviewedRow] | None = None,
    ) -> bytes | None:
        """What reading these bytes before the lock found, raising the refusal it raised.

        ``reviewed`` names the reviewed asset row that named them, as it reads under the lock. A
        row that changed since the bytes were read is the race, refused to be asked again. Bytes
        nothing read ahead belong to an input its caller did not announce: that defect is logged
        by name and the bytes are read now, under the lock, as every input's were before inputs
        were read ahead, so the person is still answered.
        """
        held = read.found.get((digest, size))
        if (digest, size) not in read.found or (keep and held is None):
            if reviewed is not None:
                key, row = reviewed
                if key in read.rows and read.rows[key] != row:
                    raise SocietyBytesNotRead(_RACE)
            if read.locked:
                _LOG.error(
                    "%s: stored bytes %s are read under the asset read lock", NOT_ANNOUNCED, digest
                )
            self._read_first(read, digest, size, keep=keep)
        found = read.found[(digest, size)]
        if isinstance(found, str):
            raise UnavailableSocietyInput(found)
        return found

    def _kept(self, read: _ReadFirst, digest: str) -> bytes:
        """Bytes read and kept whole, such as a recorded registry or a district's artifacts."""
        data = self._answer(read, digest, None, keep=True)
        assert data is not None, "kept bytes are answered as bytes"
        return data

    def _read_first(
        self, read: _ReadFirst, digest: str, size: int | None, *, keep: bool = False
    ) -> None:
        """Read one stored object into ``read`` now; ``keep`` holds its bytes for later use."""
        if (digest, size) in read.found and not (keep and read.found[(digest, size)] is None):
            return
        try:
            data = self._blob(digest, size)
        except UnavailableSocietyInput as exc:
            read.found[(digest, size)] = str(exc)
        else:
            read.found[(digest, size)] = data if keep else None

    def _read_assets_ahead(
        self,
        connection: psycopg.Connection,
        read: _ReadFirst,
        named: Iterable[tuple[str, str]],
    ) -> None:
        """Read the bytes and licence of each (asset key, digest), with the row that names them.

        Only where the reviewed row names that digest: any other pair is refused by its rows under
        the lock before its bytes are asked for, exactly as :meth:`_asset` refuses it.
        """
        for key, digest in named:
            if ("asset:" + key, digest) in read.read:
                continue
            read.read.add(("asset:" + key, digest))
            row = self._reviewed_row(connection, key)
            read.rows.setdefault(key, _reviewed_view(row))
            if row is None or row["content_sha256"] != digest:
                continue
            self._read_first(read, digest, row["byte_size"])
            self._read_first(read, row["licence_sha256"], None)

    def _read_version_ahead(
        self, connection: psycopg.Connection, read: _ReadFirst, version: AlternateVersion
    ) -> None:
        """Read what composing ``version``'s input asks of the store: each live object's."""
        registry = json.loads(self._registry_bytes)
        self._read_assets_ahead(
            connection,
            read,
            (
                (registry[obj.asset_sha256]["asset_key"], obj.asset_sha256)
                for obj in version.objects
                if not obj.removed and obj.asset_sha256 in registry
            ),
        )

    def _read_district_ahead(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: SocietyRuntimeBinding,
        read: _ReadFirst,
    ) -> None:
        """Read a district's admitted sources and its two artifacts, before the lock.

        Each source is asked alone. One whose rows refuse it is not read, and is recorded as
        refused: its rows refuse it again under the lock, and rows that admit it there changed in
        between, which is the race rather than a caller's defect.
        """
        if read.locked or ("district", binding.binding_id) in read.read:
            return
        read.read.add(("district", binding.binding_id))
        for source in binding.sources:
            try:
                row = self._admitted_source(connection, session, binding, source)
            except UnavailableSocietyInput:
                read.rows.setdefault(self._source_key(source), None)
                continue
            read.rows.setdefault(
                self._source_key(source), (source.source_sha256, row["byte_size"], "")
            )
            self._read_first(read, source.source_sha256, row["byte_size"])
        self._read_first(read, binding.base_artifact_sha256, None, keep=True)
        self._read_first(read, binding.interpretation_artifact_sha256, None, keep=True)

    def _read_district_first(
        self, connection: psycopg.Connection, session: Session, binding: SocietyRuntimeBinding
    ) -> _ReadFirst:
        """This transaction's record, with a district's bytes read, and then the asset read lock.

        For a read of the district itself (``exulanica/api/society_district.py``); call it after
        :meth:`_lock`, inside the transaction.
        """
        read = self._transaction_read(connection)
        self._read_district_ahead(connection, session, binding, read)
        self._lock_assets(connection, read)
        return read

    def _read_composition_ahead(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: SocietyRuntimeBinding | AuthoredWorldSocietyBinding,
        read: _ReadFirst,
    ) -> None:
        """Read what composing the bound version's next input asks of the store, and generate a
        generated world's records and their place, all before the asset read lock."""
        if ("composition", binding.binding_id) in read.read:
            return
        read.read.add(("composition", binding.binding_id))
        try:
            if isinstance(binding, SocietyRuntimeBinding):
                version = self._version(connection, session, binding)
                self._read_district_ahead(connection, session, binding, read)
            else:
                version = self._authored_version(connection, session, binding)
                _, ground = self._authored_scope(
                    connection, session, binding.version_id, binding.region_id
                )
                self._read_town_ahead(connection, binding, ground, read)
        except UnavailableSocietyInput:
            return  # Refused the same way, from rows, under the lock.
        self._read_version_ahead(connection, read, version)

    def _read_input_ahead(
        self,
        connection: psycopg.Connection,
        session: Session,
        read: _ReadFirst,
        document: dict,
        binding: SocietyRuntimeBinding | AuthoredWorldSocietyBinding | None = None,
    ) -> None:
        """Read what authorizing one input asks of the store, before the asset read lock.

        The version's objects where the input is not stored yet (it is composed again and
        compared), a district's sources and artifacts where it reads them, the assets it names
        where it is available, and a registry it recorded that this runtime does not hold. An input
        whose scope its rows refuse reads nothing: it is refused from those rows under the lock,
        and so does a malformed one, which its own authorization refuses: reading ahead for other
        inputs never fails because one announced beside them is malformed.
        """
        try:
            self._read_one_input_ahead(connection, session, read, document, binding)
        except (
            UnavailableSocietyInput,
            InvalidStructuralData,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return

    def _read_one_input_ahead(
        self,
        connection: psycopg.Connection,
        session: Session,
        read: _ReadFirst,
        document: dict,
        binding: SocietyRuntimeBinding | AuthoredWorldSocietyBinding | None,
    ) -> None:
        marker = ("input", document["document_sha256"])
        if marker in read.read:
            return
        read.read.add(marker)
        if binding is None:
            version_id = uuid.UUID(document["version_id"])
            binding = (
                self._authored_scope(
                    connection, session, version_id, authored_input_region(document)
                )[0]
                if is_authored_ground(document["profile"])
                else self._binding(session, version_id)
            )
        stored = self._stored_input(connection, session, binding, document["input_seq"])
        available = document["availability"] != "unavailable"
        if stored is None:
            self._read_composition_ahead(connection, session, binding, read)
        elif available and isinstance(binding, SocietyRuntimeBinding):
            self._read_district_ahead(connection, session, binding, read)
        if available:
            self._read_assets_ahead(
                connection,
                read,
                (
                    (ref["identity"], ref["sha256"])
                    for ref in document["dependency_refs"]
                    if ref["kind"] == "reviewed_asset"
                ),
            )
        registries = [
            ref["sha256"]
            for ref in document["dependency_refs"]
            if ref["kind"] == "society_affordance_registry"
        ]
        if len(registries) == 1 and registries[0] != self._registry_sha256:
            self._read_first(read, registries[0], None, keep=True)

    def _read_ahead(
        self,
        connection: psycopg.Connection,
        session: Session,
        read: _ReadFirst,
        *documents: dict,
        composing: SocietyRuntimeBinding | AuthoredWorldSocietyBinding | None = None,
        announced: bool = True,
        binding: SocietyRuntimeBinding | AuthoredWorldSocietyBinding | None = None,
    ) -> None:
        """Read, before this transaction's asset read lock, everything its inputs ask of the store.

        ``documents`` are the inputs this call authorizes, of the version ``binding`` binds where
        the caller has resolved it, and ``composing`` the binding whose next input it composes.
        With ``announced``, every input and reviewed asset announced for this connection
        (:func:`~exulanica.world.society.inputs_ahead`) is read too, so later authorizations in the
        same transaction, made once the lock is held, are answered from what was read here; a
        transaction that authorizes one input alone reads only its own. Once the lock is held
        nothing more is read ahead.
        """
        if read.locked:
            return
        if composing is not None:
            self._read_composition_ahead(connection, session, composing, read)
        for document in documents:
            self._read_input_ahead(connection, session, read, document, binding)
            self._read_arrival_ahead(connection, session, read, document)
        if not announced:
            return
        announced_documents, assets = announced_inputs(connection)
        for document in announced_documents:
            self._read_input_ahead(connection, session, read, document)
            self._read_arrival_ahead(connection, session, read, document)
        if assets:
            self._read_assets_ahead(
                connection,
                read,
                (
                    (row["asset_key"], row["content_sha256"])
                    for row in connection.execute(
                        "select asset_key,content_sha256 from world_reviewed_asset "
                        "where content_sha256=any(%s) order by asset_key",
                        (sorted(assets),),
                    ).fetchall()
                ),
            )

    def _read_arrival_ahead(
        self,
        connection: psycopg.Connection,
        session: Session,
        read: _ReadFirst,
        document: dict,
    ) -> None:
        if not _pins_arrival(document):
            return
        try:
            descriptor = ArrivalDescriptor.model_validate(document["arrival"])
        except (KeyError, ValueError):
            return
        key = society_state_sha256(descriptor.model_dump(mode="json"))
        if key in read.arrivals:
            return
        authority = buffer_arrival_authority(
            connection, session.workspace_id, descriptor, self.store
        )
        if authority is not None:
            read.arrivals[key] = authority

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
        read: _ReadFirst,
    ) -> dict:
        """Compose a district's input under the asset read lock, from rows and ``read``."""
        if version.source_invalidated:
            return self._unavailable(binding, version, seq, "authored_source_invalidated")
        registry = json.loads(self._registry_bytes)
        refs = self._refs(binding)
        try:
            interpreted, base_bytes, geometry = self._district(connection, session, binding, read)
            workspace = self._workspace_obstacles(connection, session.workspace_id, version.objects)
            for obj in version.objects:
                if obj.removed or obj.workspace_preparation_id is not None:
                    continue
                assignment = registry.get(obj.asset_sha256)
                if assignment is None:
                    raise UnavailableSocietyInput("reviewed affordance assignment is unavailable")
                self._asset(connection, assignment["asset_key"], obj.asset_sha256, registry, read)
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
            workspace_obstacles=workspace,
        )

    def initial_input(
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        place_id: uuid.UUID | None,
        region_id: str,
        engine: str | None = None,
    ) -> dict:
        """The first input a new society consumes; ``place_id`` None names a saved world's own.

        ``engine`` is the engine the society is created with, which says how a world's own
        walking surfaces are composed for it: the living town reads the living place too."""
        if (session.workspace_id, version_id) not in self._bindings:
            return self._authored_initial_input(
                connection, session, version_id, place_id, region_id, engine
            )
        binding = self._binding(session, version_id)
        if place_id != binding.place_id or region_id != binding.region_id:
            raise UnavailableSocietyInput("requested place/region has no configured binding")
        with connection.transaction():
            self._lock(connection, session)
            read = self._transaction_read(connection)
            self._read_ahead(connection, session, read, composing=binding)
            self._lock_assets(connection, read)
            version = self._version(connection, session, binding)
            return self._compose(connection, session, binding, version, 1, read)

    def authorize(self, connection: psycopg.Connection, session: Session, document: dict) -> None:
        """Authorize an exact persisted historical input or exact fresh server recomposition.

        Every stored byte the input depends on, and those of every input announced for this
        connection, is read before this transaction's asset read lock, once a transaction; under
        the lock only rows are read (``docs/asset-read-currency.md``).
        """
        validate_society_input(document)
        # A transaction of this call's own authorizes this input alone, so only its own bytes are
        # read; what is announced is read by the first authorization of a caller's transaction.
        alone = connection.info.transaction_status == TransactionStatus.IDLE
        if is_authored_ground(document["profile"]):
            self._authored_authorize(connection, session, document, alone=alone)
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
            read = self._transaction_read(connection)
            self._read_ahead(
                connection, session, read, document, announced=not alone, binding=binding
            )
            self._lock_assets(connection, read)
            version = self._version(connection, session, binding)
            stored = self._stored_input(connection, session, binding, document["input_seq"])
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
                    connection, session, binding, version, document["input_seq"], read
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
            registry_sha256, registry = self._recorded_registry(document, read)
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
            # Even a correctly persisted historic input needs current rights and byte availability,
            # read before the lock and answered here from rows.
            self._district(connection, session, binding, read)
            for ref in document["dependency_refs"]:
                if ref["kind"] == "reviewed_asset":
                    self._asset(connection, ref["identity"], ref["sha256"], registry, read)
                elif ref["kind"] == "workspace_asset":
                    self._workspace_ref(connection, session, ref)

    def authored_edit(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> None:
        """Run inside each accepted edit transaction, after its immutable edit row is appended."""
        if (session.workspace_id, version_id) not in self._bindings:
            self._authored_world_edit(connection, session, version_id)
            return
        with connection.transaction():
            # The asset read lock is taken only once this version holds a society that takes
            # inputs and everything its next input reads from the store has been read.
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
            read = self._transaction_read(connection)
            self._read_ahead(connection, session, read, composing=binding)
            self._lock_assets(connection, read)
            version = self._version(connection, session, binding)
            document = self._compose(connection, session, binding, version, last + 1, read)
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
        region_id: str | None = None,
    ) -> SocietyGround:
        try:
            ground = read_authored_ground(
                connection, session.workspace_id, world_id, snapshot_id, region_id=region_id
            )
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
            connection,
            session,
            binding.world_id,
            binding.source_snapshot_id,
            region_id=binding.region_id,
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
        # Rows only: a society reads which placements a version holds, never whether their bytes
        # are present, and this is read under the asset read lock.
        try:
            version = WorldObjectRepository(
                connection, session.workspace_id, world_id=binding.world_id, store=None
            ).version(binding.version_id, with_availability=False)
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
        read: _ReadFirst,
        composition: str | None = None,
        living_routine: RoutineModel | None = None,
        arrival: ArrivalDescriptor | None = None,
    ) -> dict:
        """Compose a saved world's input under the asset read lock, from rows and ``read``.

        ``composition`` is the composition a world's own walking surfaces are composed under: the
        purposeful society's, when left out, or the living town's, which also carries the living
        place, made under ``living_routine``: the routine the society's inputs record, or for a
        new society the town's routine a new town is made under; a lattice ground has one
        composition and names none."""
        registry = json.loads(self._registry_bytes)
        reason = None
        workspace: dict[str, dict[str, Any]] = {}
        try:
            # Only the objects this society reads: another region's are another place's. A
            # person's own asset is no reviewed asset; its preparation states its obstacle.
            workspace = self._workspace_obstacles(
                connection, binding.workspace_id, objects_in_region(version, ground)
            )
            for obj in objects_in_region(version, ground):
                if obj.removed or obj.workspace_preparation_id is not None:
                    continue
                assignment = registry.get(obj.asset_sha256)
                if assignment is None:
                    raise UnavailableSocietyInput("reviewed affordance assignment is unavailable")
                self._asset(connection, assignment["asset_key"], obj.asset_sha256, registry, read)
        except UnavailableSocietyInput as exc:
            reason = str(exc)
        # What people walk is the ground's navigation form, from its catalog entry: a lattice over
        # the area the ground states or declares, or the walking surfaces the world's own records
        # state. A form with no composition is refused by name.
        if ground.navigation_form == "lattice":
            if composition == AUTHORED_GROUND_COMPOSITION_V5:
                # A society of things: the fourth composition's ground at its pinned arrival,
                # or the ground's own where it states one, and the things placed in it.
                at = (
                    ground
                    if arrival is None
                    else replace(
                        ground,
                        arrival_x_mm=arrival.position_local_mm[0],
                        arrival_z_mm=arrival.position_local_mm[2],
                    )
                )
                return build_authored_ground_society_input_v5(
                    ground=ground,
                    version=version,
                    arrival=arrival,
                    input_seq=seq,
                    dependency_refs=self._authored_refs(binding, at),
                    availability="available" if reason is None else "unavailable",
                    unavailable_reason=reason,
                    reviewed_affordances=registry,
                    segment_blocked=segment_blocked,
                    standing=self._standing,
                    workspace_obstacles=workspace,
                    made_kinds=self._made_kinds(connection, binding.workspace_id, version.things),
                )
            if arrival is not None:
                arrived_ground = replace(
                    ground,
                    arrival_x_mm=arrival.position_local_mm[0],
                    arrival_z_mm=arrival.position_local_mm[2],
                )
                return build_authored_ground_society_input_v4(
                    ground=ground,
                    version=version,
                    arrival=arrival,
                    input_seq=seq,
                    dependency_refs=self._authored_refs(binding, arrived_ground),
                    availability="available" if reason is None else "unavailable",
                    unavailable_reason=reason,
                    reviewed_affordances=registry,
                    segment_blocked=segment_blocked,
                    standing=self._standing,
                    workspace_obstacles=workspace,
                )
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
                workspace_obstacles=workspace,
            )
        if ground.navigation_form == "walking_surfaces":
            # The records and the place they make were generated before the asset read lock
            # (``_read_town_ahead``); under it only the receipt's digest is read again, so the
            # input is composed from the receipt the world's snapshot still names.
            town = read.towns.get((binding.world_id, ground.snapshot_id))
            if town is None:
                raise UnavailableSocietyInput(
                    "the world's records were not read before the asset read lock"
                )
            if town.waiting is not None:
                raise SocietyPlaceWaiting(
                    f"the world's place is still being made: {town.waiting}",
                    code=town.waiting.code,
                    retry_seconds=town.waiting.retry_seconds,
                )
            if town.place_refusal is not None:
                raise UnavailableSocietyInput(
                    f"the world's place cannot be made: {town.place_refusal}"
                )
            if town.refusal is not None or town.place is None:
                raise UnavailableSocietyInput(f"the world's records are unreadable: {town.refusal}")
            try:
                digest, _ = generation_receipt(
                    connection, binding.workspace_id, binding.world_id, ground.snapshot_id
                )
            except InvalidStructuralData as exc:
                raise UnavailableSocietyInput(f"the world's records are unreadable: {exc}") from exc
            if digest != town.receipt_sha256:
                raise UnavailableSocietyInput("the world's receipt changed after it was read")
            chosen = WALKING_SURFACES_COMPOSITION if composition is None else composition
            if chosen not in (
                WALKING_SURFACES_COMPOSITION,
                WALKING_SURFACES_COMPOSITION_V2,
                WALKING_SURFACES_COMPOSITION_V3,
            ):
                raise UnavailableSocietyInput(
                    f"no composition {chosen!r} walks a world's own surfaces"
                )
            routine = None
            place = town.place
            if town.site_receipt is not None:
                # A world made from a world kind is walked only by the living society, under the
                # routine its receipt names, over the place made from its records under it.
                if chosen != WALKING_SURFACES_COMPOSITION_V2:
                    raise UnavailableSocietyInput(
                        "a world made from a world kind is lived in by the living society only"
                    )
                routine = town.site_routine
                if routine is None:
                    raise UnavailableSocietyInput(
                        "the world's routine was not read before the lock"
                    )
                if living_routine is not None and living_routine.sha256 != routine.sha256:
                    raise UnavailableSocietyInput(
                        "the input names another routine than the world's"
                    )
            elif chosen == WALKING_SURFACES_COMPOSITION_V2:
                # A new society's people are made under the routine the town's own receipt pins,
                # whatever a new town is made under today; a society already held keeps its own.
                routine = self._made_under(town) if living_routine is None else living_routine
                place = self._living_place(ground, town, routine)
            people = None
            if chosen == WALKING_SURFACES_COMPOSITION_V3 and reason is None:
                # What the town's people are made from, under the routine the town's receipt
                # pins: the homes and positions the living town reads, so a society of things
                # over the town is the same people. Seed-free: its genesis completes it. Every
                # input states the population it gives; the first alone records the frame.
                made_under = self._made_under(town)
                try:
                    people = people_frame(self._living_place(ground, town, made_under), made_under)
                except TownPeopleRefused as exc:
                    raise UnavailableSocietyInput(
                        f"the town's people could not be stated: {exc}"
                    ) from exc
            return build_walking_surfaces_input(
                ground=ground,
                version=version,
                place=place,
                input_seq=seq,
                dependency_refs=self._authored_refs(binding, ground),
                availability="available" if reason is None else "unavailable",
                unavailable_reason=reason,
                reviewed_affordances=registry,
                standing=self._standing,
                living=routine,
                workspace_obstacles=workspace,
                # A society of things reads the things placed on the town's surfaces too, and
                # keeps their places clear of the town's own buildings, furniture and trees.
                things=chosen == WALKING_SURFACES_COMPOSITION_V3,
                segment_blocked=segment_blocked,
                obstructions=town.obstructions
                if chosen == WALKING_SURFACES_COMPOSITION_V3
                else None,
                people=people,
                made_kinds=self._made_kinds(connection, binding.workspace_id, version.things)
                if chosen == WALKING_SURFACES_COMPOSITION_V3
                else None,
            )
        raise UnavailableSocietyInput(
            f"no society composition walks a {ground.navigation_form!r} ground"
        )

    def _authored_initial_input(
        self,
        connection: psycopg.Connection,
        session: Session,
        version_id: uuid.UUID,
        place_id: uuid.UUID | None,
        region_id: str,
        engine: str | None = None,
    ) -> dict:
        with connection.transaction():
            self._lock(connection, session)
            binding, ground = self._authored_scope(connection, session, version_id, region_id)
            requested = binding.place_id if place_id is None else place_id
            if requested != binding.place_id or region_id != binding.region_id:
                raise UnavailableSocietyInput("requested place/region has no configured binding")
            read = self._transaction_read(connection)
            self._read_ahead(connection, session, read, composing=binding)
            arrival_authority: ArrivalAuthority | None = None
            if ground.ground_kind == "unstated":
                arrival = current_arrival_descriptor(
                    connection,
                    session.workspace_id,
                    binding.world_id,
                    binding.version_id,
                    binding.source_snapshot_id,
                    self.store,
                )
                if arrival is None or arrival.region_id != binding.region_id:
                    raise UnavailableSocietyInput("arrival_source_unavailable")
                arrival_authority = buffer_arrival_authority(
                    connection, session.workspace_id, arrival, self.store
                )
                if arrival_authority is None:
                    raise UnavailableSocietyInput("arrival_source_unavailable")
                read.arrivals[society_state_sha256(arrival.model_dump(mode="json"))] = (
                    arrival_authority
                )
            self._lock_assets(connection, read)
            if arrival_authority is not None and not arrival_authority_under_lock(
                connection, session.workspace_id, arrival_authority
            ):
                raise UnavailableSocietyInput("arrival_source_unavailable")
            version = self._authored_version(connection, session, binding)
            composition = None
            family = None if engine is None else society_engine(engine).state_family
            if family is not None and ground.navigation_form == "walking_surfaces":
                # A world's own walking surfaces are composed as the engine asked for reads them.
                composition = WALKING_SURFACES_BY_FAMILY.get(family)
                if composition is None:
                    raise UnavailableSocietyInput(
                        f"no composition of a world's own surfaces is read by a {family} engine"
                    )
            elif family == "things":
                # A society of things reads the things the author placed with the ground.
                composition = AUTHORED_GROUND_COMPOSITION_V5
            return self._authored_compose(
                connection,
                binding,
                ground,
                version,
                1,
                read,
                composition,
                arrival=None if arrival_authority is None else arrival_authority.descriptor,
            )

    def _stored_input(
        self,
        connection: psycopg.Connection,
        session: Session,
        binding: SocietyRuntimeBinding | AuthoredWorldSocietyBinding,
        input_seq: int,
    ) -> dict[str, Any] | None:
        """The input the bound society recorded at ``input_seq``, or ``None`` when it has none."""
        return connection.execute(
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
                input_seq,
            ),
        ).fetchone()

    def _authored_authorize(
        self, connection: psycopg.Connection, session: Session, document: dict, *, alone: bool
    ) -> None:
        """Authorize a saved world's input, reading the store only before the asset read lock.

        What authorizing asks of the store is read once a transaction, before its first lock, for
        this input and, unless the transaction is this call's ``alone``, every input announced for
        the connection; later authorizations in the transaction are answered from that.
        """
        with connection.transaction():
            self._lock(connection, session)
            binding, ground = self._authored_scope(
                connection,
                session,
                uuid.UUID(document["version_id"]),
                authored_input_region(document),
            )
            read = self._transaction_read(connection)
            already_locked = read.locked
            self._read_ahead(
                connection, session, read, document, announced=not alone, binding=binding
            )
            arrival_authority: ArrivalAuthority | None = None
            arrival = None
            if _pins_arrival(document):
                try:
                    arrival = ArrivalDescriptor.model_validate(document["arrival"])
                except (KeyError, ValueError) as exc:
                    raise UnavailableSocietyInput("arrival descriptor is invalid") from exc
                if (
                    not already_locked
                    and document["input_seq"] == 1
                    and self._stored_input(connection, session, binding, document["input_seq"])
                    is None
                ):
                    chosen = current_arrival_descriptor(
                        connection,
                        session.workspace_id,
                        binding.world_id,
                        binding.version_id,
                        binding.source_snapshot_id,
                        self.store,
                    )
                    if chosen != arrival:
                        raise UnavailableSocietyInput("arrival_source_unavailable")
                key = society_state_sha256(arrival.model_dump(mode="json"))
                arrival_authority = read.arrivals.get(key)
                if arrival_authority is None and not already_locked:
                    arrival_authority = buffer_arrival_authority(
                        connection, session.workspace_id, arrival, self.store
                    )
                    if arrival_authority is not None:
                        read.arrivals[key] = arrival_authority
                if arrival_authority is None:
                    raise UnavailableSocietyInput("arrival_source_unavailable")
            self._lock_assets(connection, read)
            if arrival_authority is not None and not arrival_authority_under_lock(
                connection, session.workspace_id, arrival_authority
            ):
                raise UnavailableSocietyInput("arrival_source_unavailable")
            if arrival is not None:
                ground = replace(
                    ground,
                    arrival_x_mm=arrival.position_local_mm[0],
                    arrival_z_mm=arrival.position_local_mm[2],
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
            stored = self._stored_input(connection, session, binding, document["input_seq"])
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
                    connection,
                    binding,
                    self._authored_ground(connection, session, binding),
                    version,
                    document["input_seq"],
                    read,
                    # Composed again under its own composition, a town's living one included,
                    # and under the routine it records.
                    policy_for_input(document["profile"])
                    if ground.navigation_form == "walking_surfaces"
                    or document["profile"] in THING_INPUTS
                    else None,
                    input_routine(document) if document["profile"] in LIVING_INPUTS else None,
                    arrival=arrival,
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
            _, registry = self._recorded_registry(document, read)
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
            # Even a correctly persisted historic input needs current asset byte availability,
            # read before the lock and answered here from rows.
            for ref in document["dependency_refs"]:
                if ref["kind"] == "reviewed_asset":
                    self._asset(connection, ref["identity"], ref["sha256"], registry, read)
                elif ref["kind"] == "workspace_asset":
                    self._workspace_ref(connection, session, ref)

    def _authored_world_edit(
        self, connection: psycopg.Connection, session: Session, version_id: uuid.UUID
    ) -> None:
        with connection.transaction():
            # Every accepted edit in every world reaches here. The asset read lock is global, so
            # it is taken only once this version is known to hold a society that reads assets and
            # everything its input names from the store has been read, in the same order as
            # always: workspace first, then assets. Under it only rows are read.
            self._lock(connection, session)
            row = connection.execute(
                "select society_id,world_id,place_id,region_id,engine_version from world_society "
                "where workspace_id=%s and version_id=%s",
                (session.workspace_id, version_id),
            ).fetchone()
            if row is None or not society_engine(row["engine_version"]).takes_inputs:
                return
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
            previous = connection.execute(
                "select document from world_society_input where workspace_id=%s and "
                "society_id=%s and input_seq=%s",
                (session.workspace_id, row["society_id"], last),
            ).fetchone()
            if previous is None:
                raise UnavailableSocietyInput("society input history is unavailable")
            last_document = previous["document"]
            read = self._transaction_read(connection)
            # A site world's next input is composed from the place its last input carries, so an
            # edit never waits on the kind worker (:func:`_site_read`).
            self._read_town_ahead(connection, binding, ground, read, last_document)
            self._read_ahead(connection, session, read, composing=binding)
            arrival_authority: ArrivalAuthority | None = None
            if _pins_arrival(last_document):
                arrival = ArrivalDescriptor.model_validate(last_document["arrival"])
                key = society_state_sha256(arrival.model_dump(mode="json"))
                arrival_authority = read.arrivals.get(key)
                if arrival_authority is None and not read.locked:
                    arrival_authority = buffer_arrival_authority(
                        connection, session.workspace_id, arrival, self.store
                    )
                    if arrival_authority is not None:
                        read.arrivals[key] = arrival_authority
                if arrival_authority is None:
                    raise UnavailableSocietyInput("arrival_source_unavailable")
            self._lock_assets(connection, read)
            if arrival_authority is not None and not arrival_authority_under_lock(
                connection, session.workspace_id, arrival_authority
            ):
                raise UnavailableSocietyInput("arrival_source_unavailable")
            version = self._authored_version(connection, session, binding)
            # A society's next input is composed as its last was: a living town's carries its
            # living place again, made under the routine its inputs record, never a newer one.
            document = self._authored_compose(
                connection,
                binding,
                ground,
                version,
                last + 1,
                read,
                policy_for_input(last_document["profile"])
                if last_document is not None
                and (
                    ground.navigation_form == "walking_surfaces"
                    or last_document["profile"] in THING_INPUTS
                )
                else None,
                input_routine(last_document)
                if last_document is not None and last_document["profile"] in LIVING_INPUTS
                else None,
                arrival=None if arrival_authority is None else arrival_authority.descriptor,
            )
            if previous is not None and _reads_the_same(previous["document"], document):
                # The edit changed nothing this society reads, such as an object in another
                # region of the world or a photograph hidden: its people have nothing to notice.
                return
            SocietyRepository(
                connection,
                session.workspace_id,
                world_id=binding.world_id,
                input_authorizer=lambda doc: self.authorize(connection, session, doc),
            ).record_input(version_id, document)
