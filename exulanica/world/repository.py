"""PostgreSQL authority for protected world topology and appearance versions.

The public write methods each own one database transaction.  A preview is a candidate document,
never a current version; apply and rollback insert a new immutable version and move the pointer in
the same transaction.  Every optimistic check happens after locking that pointer.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Final

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from exulanica.db.read_check import ConnectionNotIdle
from exulanica.world.errors import (
    ExpiredPreview,
    InvalidPreviewState,
    InvalidStyleData,
    ProtectedTopologyConflict,
    StaleStyleVersion,
    StyleWriteBusy,
    UnknownWorldResource,
    WorldNotConfigured,
)
from exulanica.world.models import (
    ProposalOrigin,
    ProposalProvenance,
    StylePackBinding,
    StylePreview,
    StyleProposal,
    StyleProposalRecord,
    StyleReference,
    StyleScope,
    StyleVersion,
    TopologyContract,
    TopologySourceSlot,
)
from exulanica.world.registry import STYLE_REGISTRY, StyleRegistry
from exulanica.world.style_pack_library import (
    StylePackLibrary,
)
from exulanica.world.style_packs import canonical_json
from exulanica.world.style_repository_checks import (
    APPEARANCE_BASES,
    AUTHORED_DESIGN_BASIS,
    EVIDENCE_BASIS,
    StyleProposalChecks,
)
from exulanica.world.style_repository_packs import StylePackReads
from exulanica.world.style_repository_sources import StyleSourceReads
from exulanica.world.style_structure import (
    CompatibilityIntent,
    ComposedTopologyRef,
    StructureStyleCompatibility,
    StyleVersionRef,
)

__all__ = [
    "APPEARANCE_BASES",
    "AUTHORED_DESIGN_BASIS",
    "EVIDENCE_BASIS",
    "WorldStyleRepository",
]


@dataclass(frozen=True, slots=True)
class OpenStylePreviews:
    """A world's open previews this code could read, each with its proposal, and how many not."""

    readable: tuple[tuple[StylePreview, StyleProposalRecord], ...]
    unreadable: int


#: What reading one stored preview back raises when the row is older than, or otherwise outside,
#: the contract this code reads: a candidate missing the recipe-binding fields (0023), a stored
#: style the registry refuses, or a proposal row that no longer resolves. Anything else is a fault
#: and surfaces as one.
_UNREADABLE_PREVIEW: Final = (InvalidPreviewState, InvalidStyleData, UnknownWorldResource)

#: How many of a world's open previews, newest first, a page reads back when it opens the world.
#: A declared bound, not a measurement: the page takes up one, the newest made against the current
#: version or else the newest, so eight lets that one be found behind a few made against earlier
#: versions while holding every world opening to eight proposal reads, however many previews tabs
#: and the Companion have left open over time. Only previews a page may take up count towards it
#: (see ``open_previews``), so no number of newer Settings drafts hides a staged proposal.
OPEN_PREVIEWS_READ: Final = 8

#: How long an open preview waits for a person's decision before the world closes it as expired.
#: A declared product bound, not a measurement: a proposal staged before a weekend away is still
#: there to decide, and a world's open previews, which every opening of it reads, stay few however
#: many tabs and proposals have left them. The age does not protect later changes: a preview made
#: for an earlier version is refused by its base (``_check_concurrency``) whatever its age.
OPEN_PREVIEW_LIFETIME: Final = dt.timedelta(days=7)

#: The longest a write to a world's look waits for EACH lock it takes, in milliseconds, before it is
#: refused as busy (:class:`StyleWriteBusy`) with nothing written: the world's style state, and for
#: a saved world its entry and the workspace lock the entry's writers share, which a Companion
#: question also holds while it reads. A declared product figure: each hold is one short
#: transaction, so a longer one is not another write finishing. It bounds each wait, not the whole
#: write: ``tests/test_world_style_write_wait.py`` counts the waits of a real Apply on a saved world
#: and holds their sum under the page's own deadline for a world style request
#: (``WORLD_STYLE_REQUEST_TIMEOUT_MS`` in ``web/packages/app/src/world-style-api.ts``), so the page
#: hears the server's answer. PostgreSQL states ``lock_timeout`` in whole milliseconds.
STYLE_WRITE_LOCK_WAIT_MS: Final = 2_000

#: A preview past ``OPEN_PREVIEW_LIFETIME``, over a preview row named ``v``, with the lifetime as
#: its one parameter. The one predicate the reads, the closing in ``preview`` and ``apply`` use,
#: so a read never calls waiting a preview that Apply would refuse.
_PAST_LIFETIME: Final = "v.created_at <= now() - %s::interval"

#: The previews a page may take up when it opens a world: a proposal from another origin than the
#: panel's own Settings, over the whole world. A Settings preview is a live tab's draft, and no page
#: shows a regional one as a change (docs/atlas-world-customization-contract.md, section 7).
_TAKEN_UP_ORIGIN_EXCLUDED: Final = ProposalOrigin.SETTINGS.value
_TAKEN_UP_SCOPE: Final = "global"


class WorldStyleRepository(StylePackReads, StyleProposalChecks, StyleSourceReads):
    """A workspace-scoped world-style repository over an already scoped connection.

    This class creates, previews, applies, discards and rolls back versions. Three parts hold the
    rest of its methods, each in its own module: ``StylePackReads`` (style_repository_packs) reads
    the style packs a proposal may name, ``StyleProposalChecks`` (style_repository_checks) holds
    proposals and topology contracts to their checks, and ``StyleSourceReads``
    (style_repository_sources) reads the source media and source rows a version was made from.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        registry: StyleRegistry = STYLE_REGISTRY,
        world_id: str,
        style_packs: StylePackLibrary | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.registry = registry
        self.world_id = world_id
        #: The library a named style pack must belong to; the host's committed one unless given.
        self._style_packs = style_packs

    # -- protected topology ---------------------------------------------------------------

    def register_topology(self, contract: TopologyContract) -> StyleVersion:
        """Register an immutable topology contract and make its digest current.

        This method is intentionally not exposed by the HTTP router.  It is the seam a reviewed
        world-composition workflow calls after its reachability and evidence checks.  Reusing a
        digest for different regions or source bindings is refused rather than overwritten.
        Classification runs before history insert; a refuse writes nothing.
        """
        with self.connection.transaction():
            self.connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
                (self.workspace_id, 880_024),
            )
            state = self._state(for_update=True)
            style_ref = (
                None if state is None else StyleVersionRef(state["current_style_version_id"])
            )
            decision = self._require_structure_style_compatibility(
                intent=CompatibilityIntent.REGISTER_TOPOLOGY,
                style=style_ref,
                composed=ComposedTopologyRef(contract.topology_digest),
                proposed=contract,
            )
            if decision.outcome != "compatible":
                raise ProtectedTopologyConflict(decision.token.replace("_", " "))
            self.register_topology_history(contract)
            if state is None:
                default = self.registry.default_reference
                binding, capability_mapping = self._binding_for_reference(default)
                row = self.connection.execute(
                    "insert into world_style_version "
                    "(workspace_id,world_id,revision,topology_digest,global_profile_id,"
                    "global_profile_version,global_parameters,provenance_schema_version,"
                    "recipe_binding,capability_mapping) "
                    "values (%s,%s,0,%s,%s,%s,%s,1,%s,%s) "
                    "returning *",
                    (
                        self.workspace_id,
                        self.world_id,
                        contract.topology_digest,
                        default.profile_id,
                        default.profile_version,
                        Jsonb(dict(default.parameters)),
                        Jsonb(binding),
                        Jsonb(capability_mapping),
                    ),
                ).fetchone()
                assert row is not None
                self.connection.execute(
                    "insert into world_style_state "
                    "(workspace_id,world_id,current_topology_digest,current_style_version_id) "
                    "values (%s,%s,%s,%s)",
                    (self.workspace_id, self.world_id, contract.topology_digest, row["version_id"]),
                )
                return self._row_to_version(row)
            if state["current_topology_digest"] != contract.topology_digest:
                current = self._version_by_id(state["current_style_version_id"])
                try:
                    self._validate_reference_compatibility(
                        current.global_style, contract.topology_digest
                    )
                except InvalidStyleData as exc:
                    raise ProtectedTopologyConflict(
                        "the current global style is incompatible with the proposed topology "
                        "contract"
                    ) from exc
                self.connection.execute(
                    "update world_style_state set current_topology_digest=%s, updated_at=now() "
                    "where workspace_id=%s and world_id=%s",
                    (contract.topology_digest, self.workspace_id, self.world_id),
                )
            return self._filter_version_regions(
                self._version_by_id(state["current_style_version_id"]),
                contract.topology_digest,
            )

    def register_topology_history(self, contract: TopologyContract) -> None:
        """Register immutable history without activating it or writing appearance state.

        Structural bootstrap uses this for the snapshot's digest-bound foreign key while
        retaining the exact composed contract as current. Ordinary composition calls
        register_topology, which classifies first and shares this writer only after a
        compatible decision.
        """
        self._validate_topology_contract(contract)
        with self.connection.transaction():
            # Serialize composer handoff with structural bootstrap and deletion invalidation.
            self.connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
                (self.workspace_id, 880_024),
            )
            inserted = self.connection.execute(
                "insert into world_topology_contract "
                "(workspace_id,world_id,topology_digest,compatibility_key) values (%s,%s,%s,%s) "
                "on conflict do nothing returning topology_digest",
                (
                    self.workspace_id,
                    self.world_id,
                    contract.topology_digest,
                    contract.compatibility_key,
                ),
            ).fetchone()
            if inserted is not None:
                for region_id in sorted(contract.region_ids):
                    self.connection.execute(
                        "insert into world_topology_region "
                        "(workspace_id, world_id, topology_digest, region_id) values (%s,%s,%s,%s)",
                        (self.workspace_id, self.world_id, contract.topology_digest, region_id),
                    )
                for source in sorted(contract.source_slots, key=lambda value: str(value.source_id)):
                    try:
                        self.connection.execute(
                            "insert into world_topology_source "
                            "(source_id,workspace_id,world_id,topology_digest,region_id,slot_key,"
                            "evidence_span_id,missing_reason) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                source.source_id,
                                self.workspace_id,
                                self.world_id,
                                contract.topology_digest,
                                source.region_id,
                                source.slot_key,
                                source.evidence_span_id,
                                source.missing_reason,
                            ),
                        )
                    except psycopg.errors.ForeignKeyViolation as exc:
                        raise ProtectedTopologyConflict(
                            f"source slot {source.slot_key} does not name authorised evidence "
                            "from this topology workspace"
                        ) from exc
            else:
                self._assert_existing_topology_matches(contract)

    # -- reads ---------------------------------------------------------------------------

    def current(self) -> StyleVersion:
        state = self._require_state()
        return self._filter_version_regions(
            self._version_by_id(state["current_style_version_id"]),
            state["current_topology_digest"],
        )

    def current_topology_digest(self) -> str:
        return str(self._require_state()["current_topology_digest"])

    def current_topology_contract(self) -> TopologyContract:
        """Read only the current contract, including exact source identities and bindings."""
        digest = self.current_topology_digest()
        parameters = (self.workspace_id, self.world_id, digest)
        regions = self.connection.execute(
            "select region_id from world_topology_region where workspace_id=%s "
            "and world_id=%s and topology_digest=%s order by region_id",
            parameters,
        ).fetchall()
        sources = self.connection.execute(
            "select source_id,slot_key,region_id,evidence_span_id,missing_reason "
            "from world_topology_source where workspace_id=%s and world_id=%s "
            "and topology_digest=%s order by source_id",
            parameters,
        ).fetchall()
        contract = self.connection.execute(
            "select compatibility_key from world_topology_contract where workspace_id=%s "
            "and world_id=%s and topology_digest=%s",
            parameters,
        ).fetchone()
        return TopologyContract(
            digest,
            tuple(row["region_id"] for row in regions),
            tuple(TopologySourceSlot(**row) for row in sources),
            compatibility_key=contract["compatibility_key"],
            world_id=self.world_id,
        )

    def versions(self) -> tuple[StyleVersion, ...]:
        rows = self.connection.execute(
            "select * from world_style_version where workspace_id=%s and world_id=%s "
            "order by revision",
            (self.workspace_id, self.world_id),
        ).fetchall()
        return tuple(self._row_to_version(row) for row in rows)

    def proposal(self, proposal_id: uuid.UUID) -> StyleProposalRecord:
        """One proposal and where its lifecycle stands.

        A proposal whose preview outlived ``OPEN_PREVIEW_LIFETIME`` reads as ``expired`` before
        any write has closed it, by the predicate Apply refuses it by: this read runs on a
        connection that cannot write, and must never call waiting what Apply would refuse.
        """
        row = self.connection.execute(
            "select p.*,(p.status='previewed' and v.status='open' and "
            + _PAST_LIFETIME
            + ") as past_lifetime from world_style_proposal p left join world_style_preview v "
            "on v.workspace_id=p.workspace_id and v.world_id=p.world_id "
            "and v.proposal_id=p.proposal_id "
            "where p.workspace_id=%s and p.world_id=%s and p.proposal_id=%s",
            (OPEN_PREVIEW_LIFETIME, self.workspace_id, self.world_id, proposal_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such world style proposal")
        proposal = StyleProposal(
            proposal_id=row["proposal_id"],
            provenance=_provenance_from_row(row),
            scope=StyleScope(row["scope_kind"], row["scope_region_id"]),
            base_style_version_id=row["base_style_version_id"],
            base_topology_digest=row["base_topology_digest"],
            profile=StyleReference(row["profile_id"], row["profile_version"], row["parameters"]),
            reference_ids=tuple(row["reference_ids"]),
            model_id=row["model_id"],
            prompt_version=row["prompt_version"],
            refines_proposal_id=row["refines_proposal_id"],
            appearance_basis=row.get("appearance_basis"),
            **_stated_style_pack(row.get("style_pack")),
        )
        proposal = replace(proposal, style_pack=self._resolved_pack(proposal.style_pack))
        return StyleProposalRecord(
            proposal=proposal,
            recipe_binding=row["recipe_binding"],
            capability_mapping=row["capability_mapping"],
            status="expired" if row["past_lifetime"] else row["status"],
            validation_issues=tuple(row["validation_issues"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def open_previews(self) -> OpenStylePreviews:
        """The newest ``OPEN_PREVIEWS_READ`` of this world's open previews a page may take up,
        newest first, and how many of those it could not read.

        What a page reads back when it opens, so a proposal it staged before a reload or a world
        switch is still the person's to apply or discard: the server holds a preview until a
        decision closes it or it outlives ``OPEN_PREVIEW_LIFETIME``, and a page's memory does not.
        Only a proposal from another origin than Settings, over the whole world and younger than
        the lifetime, is read, and the filter runs before the limit: origin and scope are on the
        proposal, so the statement joins it rather than reading rows it would throw away. Best
        effort by design: a row this code cannot read, such as a preview made before the reviewed
        recipe-binding contract (0023), is counted and skipped rather than refused, because what it
        serves is a convenience on opening a world and must never stand in the way of the opening.
        """
        rows = self.connection.execute(
            "select v.preview_id,v.proposal_id,v.candidate,v.created_at "
            "from world_style_preview v join world_style_proposal p "
            "on p.workspace_id=v.workspace_id and p.world_id=v.world_id "
            "and p.proposal_id=v.proposal_id "
            "where v.workspace_id=%s and v.world_id=%s and v.status='open' "
            "and p.origin<>%s and p.scope_kind=%s and not (" + _PAST_LIFETIME + ") "
            "order by v.created_at desc, v.preview_id desc limit %s",
            (
                self.workspace_id,
                self.world_id,
                _TAKEN_UP_ORIGIN_EXCLUDED,
                _TAKEN_UP_SCOPE,
                OPEN_PREVIEW_LIFETIME,
                OPEN_PREVIEWS_READ,
            ),
        ).fetchall()
        readable: list[tuple[StylePreview, StyleProposalRecord]] = []
        unreadable = 0
        for row in rows:
            try:
                record = self.proposal(row["proposal_id"])
                candidate = self._candidate_from_document(row["candidate"])
                candidate = replace(candidate, style_pack=self._resolved_pack(candidate.style_pack))
            except _UNREADABLE_PREVIEW:
                unreadable += 1
                continue
            readable.append(
                (
                    StylePreview(row["preview_id"], record.proposal, candidate, row["created_at"]),
                    record,
                )
            )
        return OpenStylePreviews(readable=tuple(readable), unreadable=unreadable)

    # -- proposal lifecycle --------------------------------------------------------------

    @contextmanager
    def _style_write(self) -> Iterator[None]:
        """One write to this world's look, as its own transaction, that waits for each lock it takes
        at most :data:`STYLE_WRITE_LOCK_WAIT_MS` and is refused as :class:`StyleWriteBusy` after it.

        Refused on a connection already inside a transaction, as ``final_read_check`` refuses one
        (:class:`~exulanica.db.read_check.ConnectionNotIdle`): there the write would be a savepoint,
        and the wait it sets would outlive it and cap every later wait of the caller's transaction,
        the asset read lock's included."""
        if self.connection.info.transaction_status != TransactionStatus.IDLE:
            raise ConnectionNotIdle(
                "a write to a world's look is its own transaction; commit or roll back first"
            )
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"set local lock_timeout = '{int(STYLE_WRITE_LOCK_WAIT_MS)}ms'"
                )
                yield
        except psycopg.errors.LockNotAvailable as held:
            raise StyleWriteBusy(
                f"another change held a lock this write needs for more than "
                f"{STYLE_WRITE_LOCK_WAIT_MS} ms; nothing was written"
            ) from held

    def preview(self, proposal: StyleProposal) -> StylePreview:
        """Validate and persist one isolated preview, auditing refusals as proposals too."""
        self._validate_proposal_provenance(proposal)
        rejected: Exception | None = None
        result: StylePreview | None = None
        with self._style_write():
            state = self._state(for_update=True)
            if state is None:
                raise WorldNotConfigured("no protected world topology is registered")
            # Where a world's open previews grow, so where they are bounded: under the lock that
            # every Apply and new preview of this world takes first.
            self._close_expired()
            current = self._filter_version_regions(
                self._version_by_id(state["current_style_version_id"]),
                state["current_topology_digest"],
            )
            reference: StyleReference | None = None
            try:
                self._check_concurrency(
                    proposal.base_style_version_id, proposal.base_topology_digest
                )
                self._validate_refinement(proposal)
                self._validate_scope(proposal, state["current_topology_digest"])
                reference = self.registry.validate_reference(proposal.profile)
                self._validate_reference_compatibility(reference, state["current_topology_digest"])
                self._validate_proposal_style_pack(proposal)
            except (
                InvalidStyleData,
                ProtectedTopologyConflict,
                StaleStyleVersion,
                UnknownWorldResource,
            ) as exc:
                rejected = exc

            status = (
                "stale"
                if isinstance(rejected, StaleStyleVersion | ProtectedTopologyConflict)
                else "rejected"
                if rejected is not None
                else "previewed"
            )
            self._insert_proposal(proposal, status, rejected)
            if rejected is not None:
                self._audit(
                    "proposal_rejected",
                    proposal.provenance,
                    proposal_id=proposal.proposal_id,
                    details={
                        "error": _error_code(rejected),
                        "detail": str(rejected),
                    },
                )
            else:
                assert reference is not None
                candidate = self._candidate(current, proposal, reference)
                preview_id = uuid.uuid4()
                row = self.connection.execute(
                    "insert into world_style_preview "
                    "(preview_id,workspace_id,world_id,proposal_id,candidate) "
                    "values (%s,%s,%s,%s,%s) returning created_at",
                    (
                        preview_id,
                        self.workspace_id,
                        self.world_id,
                        proposal.proposal_id,
                        Jsonb(_version_document(candidate)),
                    ),
                ).fetchone()
                assert row is not None
                self._audit(
                    "preview_created",
                    proposal.provenance,
                    proposal_id=proposal.proposal_id,
                    preview_id=preview_id,
                )
                result = StylePreview(preview_id, proposal, candidate, row["created_at"])
        if rejected is not None:
            raise rejected
        assert result is not None
        # The proposal and its candidate state an own look as a version read states it: its base
        # and whether it may be worn now.
        return replace(
            result,
            proposal=replace(
                result.proposal, style_pack=self._resolved_pack(result.proposal.style_pack)
            ),
            candidate=replace(
                result.candidate, style_pack=self._resolved_pack(result.candidate.style_pack)
            ),
        )

    def apply(
        self,
        preview_id: uuid.UUID,
        *,
        base_style_version_id: uuid.UUID,
        base_topology_digest: str,
        applied_by: uuid.UUID,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[StyleVersion], None] | None = None,
    ) -> StyleVersion:
        failure: Exception | None = None
        applied: StyleVersion | None = None
        with self._style_write():
            if before_write is not None:
                before_write()
            state = self._require_state(for_update=True)
            preview = self._preview_row(preview_id, for_update=True)
            expired = ExpiredPreview(f"world preview {preview_id} expired without a decision")
            if preview["status"] == "expired":
                raise expired
            if preview["status"] != "open":
                raise InvalidPreviewState(
                    f"world preview {preview_id} is {preview['status']}, not open"
                )
            provenance = _provenance_from_row(preview)
            # Refused by its age before its base: past its lifetime, a preview is expired whatever
            # the world did since, and says so by name, closed or not.
            if preview["past_lifetime"]:
                self._close_expired(preview_id=preview_id)
                failure = expired
            else:
                try:
                    self._check_concurrency(base_style_version_id, base_topology_digest)
                    if (
                        preview["base_style_version_id"] != base_style_version_id
                        or preview["base_topology_digest"] != base_topology_digest
                    ):
                        self._check_concurrency(
                            preview["base_style_version_id"],
                            preview["base_topology_digest"],
                        )
                except (
                    InvalidStyleData,
                    ProtectedTopologyConflict,
                    StaleStyleVersion,
                    UnknownWorldResource,
                ) as exc:
                    failure = exc
                if failure is not None:
                    self._close_stale(preview, provenance, failure)
            if failure is None:
                proposed_reference = StyleReference(
                    preview["profile_id"], preview["profile_version"], preview["parameters"]
                )
                expected_binding, expected_mapping = self._binding_for_reference(proposed_reference)
                if (
                    preview["recipe_binding"] != expected_binding
                    or preview["capability_mapping"] != expected_mapping
                ):
                    raise InvalidStyleData(
                        "the reviewed frontend recipe binding changed after preview; create a "
                        "new proposal"
                    )
                candidate = self._candidate_from_document(preview["candidate"])
                # Registry support may have changed after preview creation.  New state never
                # silently applies a fallback; fallback is only for reading immutable history.
                global_style = self.registry.validate_reference(candidate.global_style)
                self._validate_reference_compatibility(
                    global_style, state["current_topology_digest"]
                )
                region_styles = {
                    region_id: self.registry.validate_reference(reference)
                    for region_id, reference in candidate.region_styles.items()
                }
                for reference in region_styles.values():
                    self._validate_reference_compatibility(
                        reference, state["current_topology_digest"]
                    )
                # The library may have changed since the preview, as the registry may: new state
                # never takes a pack this host does not hold.
                if candidate.style_pack is not None:
                    self._require_pack(candidate.style_pack)
                current = self._version_by_id(state["current_style_version_id"])
                version_id = uuid.uuid4()
                basis = preview.get("appearance_basis")
                pack_columns, pack_values = _style_pack_columns(candidate.style_pack)
                row = self.connection.execute(
                    "insert into world_style_version "
                    "(version_id,workspace_id,world_id,revision,parent_version_id,topology_digest,"
                    "global_profile_id,global_profile_version,global_parameters,"
                    "applied_from_proposal_id,origin,actor,origin_reference,"
                    "provenance_schema_version,reference_ids,model_id,prompt_version,"
                    "refines_proposal_id,recipe_binding,capability_mapping"
                    + ("" if basis is None else ",appearance_basis")
                    + pack_columns
                    + ") values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s"
                    + ("" if basis is None else ",%s")
                    + ",%s" * len(pack_values)
                    + ") returning *",
                    (
                        version_id,
                        self.workspace_id,
                        self.world_id,
                        current.revision + 1,
                        current.version_id,
                        state["current_topology_digest"],
                        global_style.profile_id,
                        global_style.profile_version,
                        Jsonb(dict(global_style.parameters)),
                        preview["proposal_id"],
                        provenance.origin.value,
                        provenance.actor,
                        provenance.origin_reference,
                        preview["reference_ids"],
                        preview["model_id"],
                        preview["prompt_version"],
                        preview["refines_proposal_id"],
                        Jsonb(preview["recipe_binding"]),
                        Jsonb(preview["capability_mapping"]),
                        *(() if basis is None else (basis,)),
                        *pack_values,
                    ),
                ).fetchone()
                assert row is not None
                self._insert_regions(version_id, state["current_topology_digest"], region_styles)
                self.connection.execute(
                    "update world_style_state set current_style_version_id=%s, updated_at=now() "
                    "where workspace_id=%s and world_id=%s",
                    (version_id, self.workspace_id, self.world_id),
                )
                self.connection.execute(
                    "update world_style_preview set status='applied',closed_at=now() "
                    "where workspace_id=%s and world_id=%s and preview_id=%s",
                    (self.workspace_id, self.world_id, preview_id),
                )
                self.connection.execute(
                    "update world_style_proposal set status='applied',updated_at=now() "
                    "where workspace_id=%s and world_id=%s and proposal_id=%s",
                    (self.workspace_id, self.world_id, preview["proposal_id"]),
                )
                self._audit(
                    "preview_applied",
                    provenance,
                    proposal_id=preview["proposal_id"],
                    preview_id=preview_id,
                    style_version_id=version_id,
                    details={"applied_by": str(applied_by)},
                )
                applied = self._row_to_version(row)
                if after_write is not None:
                    after_write(applied)
        if failure is not None:
            raise failure
        assert applied is not None
        return applied

    def close_stale_preview(
        self, preview_id: uuid.UUID, failure: Exception, *, error_code: str | None = None
    ) -> None:
        """Close an open preview after a saved entry check refused its Apply.

        The failed Apply transaction has rolled back. This follow-up takes the preview lock and
        changes only a still-open preview; another decision that closed it first remains intact.
        """
        with self._style_write():
            try:
                preview = self._preview_row(preview_id, for_update=True)
            except UnknownWorldResource:
                return
            if preview["status"] != "open":
                return
            self._close_stale(
                preview, _provenance_from_row(preview), failure, error_code=error_code
            )

    def discard(self, preview_id: uuid.UUID, *, discarded_by: uuid.UUID) -> None:
        with self._style_write():
            preview = self._preview_row(preview_id, for_update=True)
            if preview["status"] in ("discarded", "expired"):
                return
            if preview["status"] != "open":
                raise InvalidPreviewState(
                    f"world preview {preview_id} is {preview['status']}, not open"
                )
            # Past its lifetime a preview had already expired, and the proposal read already said
            # so: it closes as expired, not as a person's discard.
            if preview["past_lifetime"]:
                self._close_expired(preview_id=preview_id)
                return
            provenance = _provenance_from_row(preview)
            self.connection.execute(
                "update world_style_preview set status='discarded',closed_at=now() "
                "where workspace_id=%s and world_id=%s and preview_id=%s",
                (self.workspace_id, self.world_id, preview_id),
            )
            self.connection.execute(
                "update world_style_proposal set status='discarded',updated_at=now() "
                "where workspace_id=%s and world_id=%s and proposal_id=%s",
                (self.workspace_id, self.world_id, preview["proposal_id"]),
            )
            self._audit(
                "preview_discarded",
                provenance,
                proposal_id=preview["proposal_id"],
                preview_id=preview_id,
                details={"discarded_by": str(discarded_by)},
            )

    def rollback(
        self,
        target_version_id: uuid.UUID,
        *,
        base_style_version_id: uuid.UUID,
        base_topology_digest: str,
        provenance: ProposalProvenance,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[StyleVersion], None] | None = None,
    ) -> StyleVersion:
        if provenance.origin is ProposalOrigin.COMPANION:
            raise InvalidStyleData(
                "Companion rollback requires a new explicit proposal with model provenance"
            )
        self._validate_provenance(provenance)
        with self._style_write():
            if before_write is not None:
                before_write()
            state = self._require_state(for_update=True)
            self._check_concurrency(base_style_version_id, base_topology_digest)
            current = self._version_by_id(state["current_style_version_id"])
            target = self._raw_version_by_id(target_version_id)
            current_regions = {
                row["region_id"]
                for row in self.connection.execute(
                    "select region_id from world_topology_region where workspace_id=%s "
                    "and world_id=%s and topology_digest=%s",
                    (self.workspace_id, self.world_id, state["current_topology_digest"]),
                ).fetchall()
            }
            target_regions = {
                region_id: reference
                for region_id, reference in target.region_styles.items()
                if region_id in current_regions
            }
            binding, capability_mapping = self._binding_for_reference(target.global_style)
            # The version rolled back to names a pack this host must still hold: a rollback is
            # new state, and new state never takes a stand-in.
            if target.style_pack is not None:
                self._require_pack(target.style_pack)
            pack_columns, pack_values = _style_pack_columns(target.style_pack)
            version_id = uuid.uuid4()
            row = self.connection.execute(
                "insert into world_style_version "
                "(version_id,workspace_id,world_id,revision,parent_version_id,topology_digest,"
                "global_profile_id,global_profile_version,global_parameters,"
                "rollback_target_version_id,origin,actor,origin_reference,"
                "provenance_schema_version,recipe_binding,capability_mapping"
                + pack_columns
                + ") values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s"
                + ",%s" * len(pack_values)
                + ") returning *",
                (
                    version_id,
                    self.workspace_id,
                    self.world_id,
                    current.revision + 1,
                    current.version_id,
                    state["current_topology_digest"],
                    target.global_style.profile_id,
                    target.global_style.profile_version,
                    Jsonb(dict(target.global_style.parameters)),
                    target_version_id,
                    provenance.origin.value,
                    provenance.actor,
                    provenance.origin_reference,
                    Jsonb(binding),
                    Jsonb(capability_mapping),
                    *pack_values,
                ),
            ).fetchone()
            assert row is not None
            self._insert_regions(version_id, state["current_topology_digest"], target_regions)
            self.connection.execute(
                "update world_style_state set current_style_version_id=%s,updated_at=now() "
                "where workspace_id=%s and world_id=%s",
                (version_id, self.workspace_id, self.world_id),
            )
            self._audit(
                "style_rolled_back",
                provenance,
                style_version_id=version_id,
                details={
                    "target_version_id": str(target_version_id),
                    "omitted_regions": sorted(set(target.region_styles) - current_regions),
                },
            )
            version = self._row_to_version(row)
            if after_write is not None:
                after_write(version)
            return version

    # -- source media -------------------------------------------------------------------

    # -- internals ----------------------------------------------------------------------

    def _state(self, *, for_update: bool = False) -> Mapping[str, Any] | None:
        query = "select * from world_style_state where workspace_id=%s and world_id=%s" + (
            " for update" if for_update else ""
        )
        return self.connection.execute(query, (self.workspace_id, self.world_id)).fetchone()

    def _require_state(self, *, for_update: bool = False) -> Mapping[str, Any]:
        state = self._state(for_update=for_update)
        if state is None:
            raise WorldNotConfigured("no protected world topology is registered")
        return state

    def _version_by_id(self, version_id: uuid.UUID) -> StyleVersion:
        return self._read_version(version_id, resolve=True)

    def _raw_version_by_id(self, version_id: uuid.UUID) -> StyleVersion:
        return self._read_version(version_id, resolve=False)

    def _read_version(self, version_id: uuid.UUID, *, resolve: bool) -> StyleVersion:
        row = self.connection.execute(
            "select * from world_style_version where workspace_id=%s and world_id=%s "
            "and version_id=%s",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such world style version")
        return self._row_to_version(row, resolve=resolve)

    def _row_to_version(self, row: Mapping[str, Any], *, resolve: bool = True) -> StyleVersion:
        region_rows = self.connection.execute(
            "select region_id,profile_id,profile_version,parameters "
            "from world_region_style_version where workspace_id=%s and world_id=%s "
            "and version_id=%s order by region_id",
            (self.workspace_id, self.world_id, row["version_id"]),
        ).fetchall()
        raw_global = StyleReference(
            row["global_profile_id"], row["global_profile_version"], row["global_parameters"]
        )
        raw_regions = {
            region["region_id"]: StyleReference(
                region["profile_id"], region["profile_version"], region["parameters"]
            )
            for region in region_rows
        }
        warnings: list[str] = []
        if resolve:
            global_style, global_warnings = self.registry.resolve_reference(raw_global)
            warnings.extend(global_warnings)
            region_styles: dict[str, StyleReference] = {}
            for region_id, reference in raw_regions.items():
                profile = self.registry.profiles.get(
                    (reference.profile_id, reference.profile_version)
                )
                if profile is None or not self.registry.is_available(profile):
                    warnings.append(
                        f"Unknown or unavailable regional style {reference.profile_id}@"
                        f"{reference.profile_version} on {region_id}; override ignored."
                    )
                    continue
                try:
                    region_styles[region_id] = self.registry.validate_reference(reference)
                except InvalidStyleData:
                    warnings.append(
                        f"Invalid stored regional style on {region_id}; override ignored."
                    )
        else:
            global_style = raw_global
            region_styles = raw_regions
        provenance = None
        if row["origin"] is not None:
            provenance = ProposalProvenance(
                ProposalOrigin(row["origin"]), row["actor"], row["origin_reference"]
            )
        # Absent from a read that names its columns and from a row written before 0141: no pack.
        # Absent from one written before a world could wear its own look, or naming the library: a
        # library pack.
        style_pack = (
            None
            if row.get("style_pack_id") is None
            else StylePackBinding(
                row["style_pack_id"],
                row["style_pack_version"],
                row["style_pack_manifest_sha256"],
                row.get("style_pack_source") or "library",
                # Absent from a row written before a world could state a setting: none.
                setting=_setting_text(row.get("style_pack_setting")),
            )
        )
        if style_pack is not None and style_pack.source == "workspace":
            style_pack = self._own_pack(style_pack, resolve=resolve)
            if resolve and not style_pack.wearable:
                warnings.append(
                    f"The world's own look {style_pack.pack_id} version {style_pack.version} may "
                    "no longer be worn; the world is drawn in "
                    + (
                        "the look it was drawn on."
                        if style_pack.base is not None
                        else "the default look."
                    )
                )
        elif resolve and style_pack is not None and not self._library_holds(style_pack):
            warnings.append(
                f"Style pack {style_pack.pack_id} version {style_pack.version} is not in this "
                "host's library; the world is drawn without it."
            )
        return StyleVersion(
            version_id=row["version_id"],
            revision=row["revision"],
            parent_version_id=row["parent_version_id"],
            topology_digest=row["topology_digest"],
            global_style=global_style,
            region_styles=region_styles,
            applied_from_proposal_id=row["applied_from_proposal_id"],
            rollback_target_version_id=row["rollback_target_version_id"],
            provenance=provenance,
            created_at=row["created_at"],
            warnings=tuple(warnings),
            recipe_binding=row["recipe_binding"],
            capability_mapping=row["capability_mapping"],
            reference_ids=tuple(row["reference_ids"]),
            model_id=row["model_id"],
            prompt_version=row["prompt_version"],
            refines_proposal_id=row["refines_proposal_id"],
            # Absent from a history read that names its columns: such a row predates no rule,
            # it simply did not ask, and a version it builds is not a Companion one.
            appearance_basis=row.get("appearance_basis"),
            style_pack=style_pack,
        )

    def _preview_row(self, preview_id: uuid.UUID, *, for_update: bool) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select p.*,v.preview_id,v.candidate,v.status as preview_status,v.created_at as "
            "preview_created_at," + _PAST_LIFETIME + " as past_lifetime "
            "from world_style_preview v join world_style_proposal p "
            "on p.workspace_id=v.workspace_id and p.world_id=v.world_id "
            "and p.proposal_id=v.proposal_id where v.workspace_id=%s and v.world_id=%s "
            "and v.preview_id=%s" + (" for update of v" if for_update else ""),
            (OPEN_PREVIEW_LIFETIME, self.workspace_id, self.world_id, preview_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such world preview")
        # Both joined rows have a status.  Alias the preview value to the key lifecycle code uses.
        return {**row, "status": row["preview_status"]}

    def _candidate(
        self, current: StyleVersion, proposal: StyleProposal, reference: StyleReference
    ) -> StyleVersion:
        global_style = current.global_style
        regions = dict(current.region_styles)
        if proposal.scope.kind == "global":
            global_style = reference
        else:
            assert proposal.scope.region_id is not None
            regions[proposal.scope.region_id] = reference
        return StyleVersion(
            version_id=uuid.uuid4(),
            revision=current.revision,
            parent_version_id=current.version_id,
            topology_digest=proposal.base_topology_digest,
            global_style=global_style,
            region_styles=regions,
            applied_from_proposal_id=proposal.proposal_id,
            rollback_target_version_id=None,
            provenance=proposal.provenance,
            created_at=dt.datetime.now(dt.UTC),
            recipe_binding=self.registry.recipe_binding(reference),
            capability_mapping={
                key: definition.capability
                for key, definition in self.registry.profiles[
                    (reference.profile_id, reference.profile_version)
                ].controls.items()
            },
            reference_ids=proposal.reference_ids,
            model_id=proposal.model_id,
            prompt_version=proposal.prompt_version,
            refines_proposal_id=proposal.refines_proposal_id,
            appearance_basis=proposal.appearance_basis,
            # A proposal that names no pack keeps its base's: the base is the current version,
            # checked under the state lock this preview holds.
            style_pack=(
                proposal.style_pack
                if proposal.style_pack_stated
                else _inherited(current.style_pack)
            ),
        )

    def _candidate_from_document(self, value: Mapping[str, Any]) -> StyleVersion:
        required = {
            "recipe_binding",
            "capability_mapping",
            "reference_ids",
            "model_id",
            "prompt_version",
            "refines_proposal_id",
        }
        if not required.issubset(value):
            raise InvalidPreviewState(
                "preview predates the reviewed recipe-binding contract; create a new preview"
            )
        return StyleVersion(
            version_id=uuid.UUID(value["version_id"]),
            revision=int(value["revision"]),
            parent_version_id=uuid.UUID(value["parent_version_id"]),
            topology_digest=value["topology_digest"],
            global_style=_reference_from_document(value["global"]),
            region_styles={
                region_id: _reference_from_document(reference)
                for region_id, reference in value["regions"].items()
            },
            applied_from_proposal_id=uuid.UUID(value["applied_from_proposal_id"]),
            rollback_target_version_id=None,
            provenance=None,
            created_at=dt.datetime.fromisoformat(value["created_at"]),
            recipe_binding=value["recipe_binding"],
            capability_mapping=value["capability_mapping"],
            reference_ids=tuple(value["reference_ids"]),
            model_id=value["model_id"],
            prompt_version=value["prompt_version"],
            refines_proposal_id=(
                None
                if value["refines_proposal_id"] is None
                else uuid.UUID(value["refines_proposal_id"])
            ),
            appearance_basis=value.get("appearance_basis"),
            # A candidate made before 0141 names none: no world had a pack then.
            style_pack=_style_pack_from_document(value.get("style_pack")),
        )

    def _insert_proposal(
        self, proposal: StyleProposal, status: str, error: Exception | None
    ) -> None:
        binding, capability_mapping = self._proposal_binding(proposal.profile)
        # The basis column is written only by a proposal that states one (0128), so every other
        # proposal is written exactly as it was before the column existed.
        basis = proposal.appearance_basis
        # Likewise the pack, written only by a proposal that names one (0141), as it named it.
        stated = (
            (Jsonb({"pack": _style_pack_document(proposal.style_pack)}),)
            if proposal.style_pack_stated
            else ()
        )
        try:
            self.connection.execute(
                "insert into world_style_proposal "
                "(proposal_id,workspace_id,world_id,origin,actor,origin_reference,scope_kind,"
                "scope_region_id,base_style_version_id,base_topology_digest,profile_id,"
                "profile_version,parameters,status,validation_issues,provenance_schema_version,"
                "reference_ids,model_id,prompt_version,refines_proposal_id,recipe_binding,"
                "capability_mapping"
                + ("" if basis is None else ",appearance_basis")
                + ("" if not stated else ",style_pack")
                + ") values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s"
                + ("" if basis is None else ",%s")
                + ("" if not stated else ",%s")
                + ")",
                (
                    proposal.proposal_id,
                    self.workspace_id,
                    self.world_id,
                    proposal.provenance.origin.value,
                    proposal.provenance.actor,
                    proposal.provenance.origin_reference,
                    proposal.scope.kind,
                    proposal.scope.region_id,
                    proposal.base_style_version_id,
                    proposal.base_topology_digest,
                    proposal.profile.profile_id,
                    proposal.profile.profile_version,
                    Jsonb(dict(proposal.profile.parameters)),
                    status,
                    Jsonb([] if error is None else [_error_code(error)]),
                    list(proposal.reference_ids),
                    proposal.model_id,
                    proposal.prompt_version,
                    proposal.refines_proposal_id,
                    Jsonb(binding),
                    Jsonb(capability_mapping),
                    *(() if basis is None else (basis,)),
                    *stated,
                ),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise InvalidStyleData(f"proposal id {proposal.proposal_id} was already used") from exc

    def _insert_regions(
        self,
        version_id: uuid.UUID,
        topology_digest: str,
        regions: Mapping[str, StyleReference],
    ) -> None:
        for region_id, reference in sorted(regions.items()):
            self.connection.execute(
                "insert into world_region_style_version "
                "(workspace_id,world_id,version_id,topology_digest,region_id,profile_id,"
                "profile_version,parameters) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    version_id,
                    topology_digest,
                    region_id,
                    reference.profile_id,
                    reference.profile_version,
                    Jsonb(dict(reference.parameters)),
                ),
            )

    def _audit(
        self,
        event_type: str,
        provenance: ProposalProvenance,
        *,
        proposal_id: uuid.UUID | None = None,
        preview_id: uuid.UUID | None = None,
        style_version_id: uuid.UUID | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            "insert into world_style_audit_event "
            "(workspace_id,world_id,event_type,origin,actor,origin_reference,proposal_id,"
            "preview_id,style_version_id,details) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                event_type,
                provenance.origin.value,
                provenance.actor,
                provenance.origin_reference,
                proposal_id,
                preview_id,
                style_version_id,
                Jsonb(dict(details or {})),
            ),
        )

    def _close_stale(
        self,
        preview: Mapping[str, Any],
        provenance: ProposalProvenance,
        failure: Exception,
        *,
        error_code: str | None = None,
    ) -> None:
        self.connection.execute(
            "update world_style_preview set status='stale',closed_at=now() "
            "where workspace_id=%s and world_id=%s and preview_id=%s",
            (self.workspace_id, self.world_id, preview["preview_id"]),
        )
        self.connection.execute(
            "update world_style_proposal set status='stale',updated_at=now() "
            "where workspace_id=%s and world_id=%s and proposal_id=%s",
            (self.workspace_id, self.world_id, preview["proposal_id"]),
        )
        self._audit(
            "preview_stale",
            provenance,
            proposal_id=preview["proposal_id"],
            preview_id=preview["preview_id"],
            details={"error": error_code or _error_code(failure), "detail": str(failure)},
        )

    def _close_expired(self, *, preview_id: uuid.UUID | None = None) -> None:
        """Close this world's open previews past ``OPEN_PREVIEW_LIFETIME`` as expired.

        Each closes with its proposal and one ``preview_expired`` event carrying the proposal's
        own provenance, as every other lifecycle event does. ``preview`` and ``apply`` call it
        holding the world's state row; ``discard`` calls it for its one preview (``preview_id``)
        holding only that preview's row. Either way each closing takes the preview's row lock and
        re-reads that it is still open, so no preview is closed, or recorded, twice.
        """
        one = "" if preview_id is None else " and v.preview_id=%s"
        self.connection.execute(
            "with expired as (update world_style_preview v set status='expired',closed_at=now() "
            "where v.workspace_id=%s and v.world_id=%s and v.status='open' and "
            + _PAST_LIFETIME
            + one
            + " returning v.proposal_id,v.preview_id), "
            "closed as (update world_style_proposal p set status='expired',updated_at=now() "
            "from expired e where p.workspace_id=%s and p.world_id=%s "
            "and p.proposal_id=e.proposal_id "
            "returning p.proposal_id,p.origin,p.actor,p.origin_reference) "
            "insert into world_style_audit_event (workspace_id,world_id,event_type,origin,actor,"
            "origin_reference,proposal_id,preview_id,details) "
            "select %s,%s,'preview_expired',c.origin,c.actor,c.origin_reference,c.proposal_id,"
            "e.preview_id,%s from expired e join closed c on c.proposal_id=e.proposal_id",
            (
                self.workspace_id,
                self.world_id,
                OPEN_PREVIEW_LIFETIME,
                *(() if preview_id is None else (preview_id,)),
                self.workspace_id,
                self.world_id,
                self.workspace_id,
                self.world_id,
                Jsonb({"lifetime_seconds": int(OPEN_PREVIEW_LIFETIME.total_seconds())}),
            ),
        )

    def _check_concurrency(
        self,
        base_style_version_id: uuid.UUID,
        base_topology_digest: str,
    ) -> StructureStyleCompatibility:
        return self._require_structure_style_compatibility(
            intent=CompatibilityIntent.APPEARANCE_WRITE,
            style=StyleVersionRef(base_style_version_id),
            composed=ComposedTopologyRef(base_topology_digest),
        )


def _reference_from_document(value: Mapping[str, Any]) -> StyleReference:
    return StyleReference(
        value["profile_id"], int(value["profile_version"]), value.get("parameters", {})
    )


def _reference_document(value: StyleReference) -> dict[str, Any]:
    return {
        "profile_id": value.profile_id,
        "profile_version": value.profile_version,
        "parameters": dict(value.parameters),
    }


def _version_document(value: StyleVersion) -> dict[str, Any]:
    return {
        "version_id": str(value.version_id),
        "revision": value.revision,
        "parent_version_id": str(value.parent_version_id),
        "topology_digest": value.topology_digest,
        "global": _reference_document(value.global_style),
        "regions": {
            region_id: _reference_document(reference)
            for region_id, reference in sorted(value.region_styles.items())
        },
        "applied_from_proposal_id": str(value.applied_from_proposal_id),
        "recipe_binding": dict(value.recipe_binding),
        "capability_mapping": dict(value.capability_mapping),
        "reference_ids": list(value.reference_ids),
        "model_id": value.model_id,
        "prompt_version": value.prompt_version,
        "refines_proposal_id": (
            None if value.refines_proposal_id is None else str(value.refines_proposal_id)
        ),
        "appearance_basis": value.appearance_basis,
        "created_at": value.created_at.isoformat(),
        # Only when the candidate names a pack, so a candidate naming none is the document it was.
        **(
            {}
            if value.style_pack is None
            else {"style_pack": _style_pack_document(value.style_pack)}
        ),
    }


def _inherited(pack: StylePackBinding | None) -> StylePackBinding | None:
    """The pack a proposal that names none keeps: the current one, unless it is the world's own
    look and may no longer be worn, when its library base (or no pack, when the library no longer
    holds that base) is what the world is drawn in and what the next version names."""
    if pack is None or pack.source == "library" or pack.wearable is not False:
        return pack
    base = pack.base
    return (
        None
        if base is None
        else StylePackBinding(
            base.pack_id, base.version, base.manifest_sha256, setting=pack.setting
        )
    )


def _style_pack_document(value: StylePackBinding | None) -> dict[str, Any] | None:
    if value is None:
        return None
    # A library pack's document is as it was before a world could wear its workspace's own pack.
    return {
        "pack_id": value.pack_id,
        "version": value.version,
        "manifest_sha256": value.manifest_sha256,
        **({} if value.source == "library" else {"source": value.source}),
        # Only when the pack is drawn in a setting, so a document naming none is as it was.
        **({} if value.setting is None else {"setting": json.loads(value.setting)}),
    }


def _style_pack_from_document(value: Mapping[str, Any] | None) -> StylePackBinding | None:
    if value is None:
        return None
    return StylePackBinding(
        str(value["pack_id"]),
        int(value["version"]),
        str(value["manifest_sha256"]),
        str(value.get("source", "library")),
        setting=_setting_text(value.get("setting")),
    )


def _setting_text(value: Any) -> str | None:
    """A stored setting as the canonical JSON a binding holds, or None for none."""
    return None if value is None else canonical_json(value)


def _stated_style_pack(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """A proposal row's request: no pack named (SQL null), or ``{"pack": null or a pack}``."""
    if value is None:
        return {}
    return {"style_pack_stated": True, "style_pack": _style_pack_from_document(value["pack"])}


def _style_pack_columns(value: StylePackBinding | None) -> tuple[str, tuple[object, ...]]:
    """The columns and values naming a version's pack: none for a version that names no pack."""
    if value is None:
        return "", ()
    # Written only for a pack drawn in a setting, so every other version is written as before.
    columns, values = (
        ("", ())
        if value.setting is None
        else (",style_pack_setting", (Jsonb(json.loads(value.setting)),))
    )
    if value.source == "library":
        return (
            f",style_pack_id,style_pack_version,style_pack_manifest_sha256{columns}",
            (value.pack_id, value.version, value.manifest_sha256, *values),
        )
    return (
        f",style_pack_id,style_pack_version,style_pack_manifest_sha256,style_pack_source{columns}",
        (value.pack_id, value.version, value.manifest_sha256, value.source, *values),
    )


def _provenance_from_row(row: Mapping[str, Any]) -> ProposalProvenance:
    return ProposalProvenance(ProposalOrigin(row["origin"]), row["actor"], row["origin_reference"])


def _error_code(error: Exception) -> str:
    if isinstance(error, StaleStyleVersion):
        return "stale_style_version"
    if isinstance(error, ProtectedTopologyConflict):
        return "protected_topology_conflict"
    if isinstance(error, UnknownWorldResource):
        return "unknown_reference"
    return "invalid_style_data"
