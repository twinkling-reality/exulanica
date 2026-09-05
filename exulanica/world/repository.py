"""PostgreSQL authority for protected world topology and appearance versions.

The public write methods each own one database transaction.  A preview is a candidate document,
never a current version; apply and rollback insert a new immutable version and move the pointer in
the same transaction.  Every optimistic check happens after locking that pointer.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.evidence import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.errors import (
    InvalidPreviewState,
    InvalidStyleData,
    ProtectedTopologyConflict,
    StaleStyleVersion,
    UnavailableAsset,
    UnknownWorldResource,
    WorldNotConfigured,
)
from exulanica.world.models import (
    DEFAULT_WORLD_ID,
    ProposalOrigin,
    ProposalProvenance,
    SourceMediaState,
    StylePreview,
    StyleProposal,
    StyleProposalRecord,
    StyleReference,
    StyleScope,
    StyleVersion,
    TopologyContract,
    WorldSourceMedia,
)
from exulanica.world.registry import STYLE_REGISTRY, StyleRegistry

__all__ = ["WorldStyleRepository"]

_SLOT_KEY: Final = re.compile(r"^[a-z][a-z0-9.-]*$")


class WorldStyleRepository:
    """A workspace-scoped world-style repository over an already scoped connection."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        registry: StyleRegistry = STYLE_REGISTRY,
        world_id: str = DEFAULT_WORLD_ID,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.registry = registry
        self.world_id = world_id

    # -- protected topology ---------------------------------------------------------------

    def register_topology(self, contract: TopologyContract) -> StyleVersion:
        """Register an immutable topology contract and make its digest current.

        This method is intentionally not exposed by the HTTP router.  It is the seam a reviewed
        world-composition workflow calls after its reachability and evidence checks.  Reusing a
        digest for different regions or source bindings is refused rather than overwritten.
        """
        self._validate_topology_contract(contract)
        with self.connection.transaction():
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

            state = self._state(for_update=True)
            if state is None:
                default = self.registry.default_reference
                self._validate_reference_compatibility(default, contract.topology_digest)
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

    # -- reads ---------------------------------------------------------------------------

    def current(self) -> StyleVersion:
        state = self._require_state()
        return self._filter_version_regions(
            self._version_by_id(state["current_style_version_id"]),
            state["current_topology_digest"],
        )

    def current_topology_digest(self) -> str:
        return str(self._require_state()["current_topology_digest"])

    def versions(self) -> tuple[StyleVersion, ...]:
        rows = self.connection.execute(
            "select * from world_style_version where workspace_id=%s and world_id=%s "
            "order by revision",
            (self.workspace_id, self.world_id),
        ).fetchall()
        return tuple(self._row_to_version(row) for row in rows)

    def proposal(self, proposal_id: uuid.UUID) -> StyleProposalRecord:
        row = self.connection.execute(
            "select * from world_style_proposal where workspace_id=%s and world_id=%s "
            "and proposal_id=%s",
            (self.workspace_id, self.world_id, proposal_id),
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
        )
        return StyleProposalRecord(
            proposal=proposal,
            recipe_binding=row["recipe_binding"],
            capability_mapping=row["capability_mapping"],
            status=row["status"],
            validation_issues=tuple(row["validation_issues"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -- proposal lifecycle --------------------------------------------------------------

    def preview(self, proposal: StyleProposal) -> StylePreview:
        """Validate and persist one isolated preview, auditing refusals as proposals too."""
        self._validate_proposal_provenance(proposal)
        rejected: Exception | None = None
        result: StylePreview | None = None
        with self.connection.transaction():
            state = self._state(for_update=True)
            if state is None:
                raise WorldNotConfigured("no protected world topology is registered")
            current = self._filter_version_regions(
                self._version_by_id(state["current_style_version_id"]),
                state["current_topology_digest"],
            )
            reference: StyleReference | None = None
            if proposal.base_style_version_id != current.version_id:
                rejected = StaleStyleVersion(
                    f"proposal targets {proposal.base_style_version_id}; current style is "
                    f"{current.version_id}"
                )
            elif proposal.base_topology_digest != state["current_topology_digest"]:
                rejected = ProtectedTopologyConflict(
                    "the protected topology changed after this proposal was created"
                )
            else:
                try:
                    self._validate_refinement(proposal)
                    self._validate_scope(proposal, state["current_topology_digest"])
                    reference = self.registry.validate_reference(proposal.profile)
                    self._validate_reference_compatibility(
                        reference, state["current_topology_digest"]
                    )
                except InvalidStyleData as exc:
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
        return result

    def apply(
        self,
        preview_id: uuid.UUID,
        *,
        base_style_version_id: uuid.UUID,
        base_topology_digest: str,
        applied_by: uuid.UUID,
    ) -> StyleVersion:
        failure: Exception | None = None
        applied: StyleVersion | None = None
        with self.connection.transaction():
            state = self._require_state(for_update=True)
            preview = self._preview_row(preview_id, for_update=True)
            if preview["status"] != "open":
                raise InvalidPreviewState(
                    f"world preview {preview_id} is {preview['status']}, not open"
                )
            provenance = _provenance_from_row(preview)
            if (
                base_style_version_id != state["current_style_version_id"]
                or preview["base_style_version_id"] != state["current_style_version_id"]
            ):
                failure = StaleStyleVersion(
                    f"preview targets {preview['base_style_version_id']}; current style is "
                    f"{state['current_style_version_id']}"
                )
            elif (
                base_topology_digest != state["current_topology_digest"]
                or preview["base_topology_digest"] != state["current_topology_digest"]
            ):
                failure = ProtectedTopologyConflict(
                    "the protected topology changed after this preview was created"
                )
            if failure is not None:
                self._close_stale(preview, provenance, failure)
            else:
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
                current = self._version_by_id(state["current_style_version_id"])
                version_id = uuid.uuid4()
                row = self.connection.execute(
                    "insert into world_style_version "
                    "(version_id,workspace_id,world_id,revision,parent_version_id,topology_digest,"
                    "global_profile_id,global_profile_version,global_parameters,"
                    "applied_from_proposal_id,origin,actor,origin_reference,"
                    "provenance_schema_version,reference_ids,model_id,prompt_version,"
                    "refines_proposal_id,recipe_binding,capability_mapping) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s) "
                    "returning *",
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
        if failure is not None:
            raise failure
        assert applied is not None
        return applied

    def discard(self, preview_id: uuid.UUID, *, discarded_by: uuid.UUID) -> None:
        with self.connection.transaction():
            preview = self._preview_row(preview_id, for_update=True)
            if preview["status"] == "discarded":
                return
            if preview["status"] != "open":
                raise InvalidPreviewState(
                    f"world preview {preview_id} is {preview['status']}, not open"
                )
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
    ) -> StyleVersion:
        if provenance.origin is ProposalOrigin.COMPANION:
            raise InvalidStyleData(
                "Companion rollback requires a new explicit proposal with model provenance"
            )
        self._validate_provenance(provenance)
        with self.connection.transaction():
            state = self._require_state(for_update=True)
            self._check_concurrency(state, base_style_version_id, base_topology_digest)
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
            version_id = uuid.uuid4()
            row = self.connection.execute(
                "insert into world_style_version "
                "(version_id,workspace_id,world_id,revision,parent_version_id,topology_digest,"
                "global_profile_id,global_profile_version,global_parameters,"
                "rollback_target_version_id,origin,actor,origin_reference,"
                "provenance_schema_version,recipe_binding,capability_mapping) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s) returning *",
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
            return self._row_to_version(row)

    # -- source media -------------------------------------------------------------------

    def source_media(self, store: ContentAddressedStore) -> tuple[WorldSourceMedia, ...]:
        state = self._require_state()
        rows = self._source_rows(state["current_topology_digest"])
        return tuple(self._source_from_row(row, store) for row in rows)

    def require_source_media(
        self, source_id: uuid.UUID, store: ContentAddressedStore
    ) -> WorldSourceMedia:
        state = self._require_state()
        rows = self._source_rows(state["current_topology_digest"], source_id=source_id)
        if not rows:
            raise UnknownWorldResource("no such world source slot")
        source = self._source_from_row(rows[0], store)
        if source.state is not SourceMediaState.AVAILABLE:
            raise UnavailableAsset(
                f"world source {source.slot_key} is {source.state.value}: {source.reason}"
            )
        return source

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
        )

    def _preview_row(self, preview_id: uuid.UUID, *, for_update: bool) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select p.*,v.preview_id,v.candidate,v.status as preview_status,v.created_at as "
            "preview_created_at from world_style_preview v join world_style_proposal p "
            "on p.workspace_id=v.workspace_id and p.world_id=v.world_id "
            "and p.proposal_id=v.proposal_id where v.workspace_id=%s and v.world_id=%s "
            "and v.preview_id=%s" + (" for update of v" if for_update else ""),
            (self.workspace_id, self.world_id, preview_id),
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
        )

    def _insert_proposal(
        self, proposal: StyleProposal, status: str, error: Exception | None
    ) -> None:
        binding, capability_mapping = self._proposal_binding(proposal.profile)
        try:
            self.connection.execute(
                "insert into world_style_proposal "
                "(proposal_id,workspace_id,world_id,origin,actor,origin_reference,scope_kind,"
                "scope_region_id,base_style_version_id,base_topology_digest,profile_id,"
                "profile_version,parameters,status,validation_issues,provenance_schema_version,"
                "reference_ids,model_id,prompt_version,refines_proposal_id,recipe_binding,"
                "capability_mapping) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s)",
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
            details={"error": _error_code(failure), "detail": str(failure)},
        )

    def _check_concurrency(
        self,
        state: Mapping[str, Any],
        base_style_version_id: uuid.UUID,
        base_topology_digest: str,
    ) -> None:
        if base_style_version_id != state["current_style_version_id"]:
            raise StaleStyleVersion(
                f"request targets {base_style_version_id}; current style is "
                f"{state['current_style_version_id']}"
            )
        if base_topology_digest != state["current_topology_digest"]:
            raise ProtectedTopologyConflict(
                "the protected topology changed after this request was created"
            )

    def _validate_scope(self, proposal: StyleProposal, topology_digest: str) -> None:
        if proposal.scope.kind == "global":
            if proposal.scope.region_id is not None:
                raise InvalidStyleData("global style scope cannot name a region")
            return
        if proposal.scope.kind != "region" or not proposal.scope.region_id:
            raise InvalidStyleData("style scope must be global or name one region")
        row = self.connection.execute(
            "select 1 from world_topology_region where workspace_id=%s and world_id=%s "
            "and topology_digest=%s and region_id=%s",
            (self.workspace_id, self.world_id, topology_digest, proposal.scope.region_id),
        ).fetchone()
        if row is None:
            raise InvalidStyleData(f"unknown region scope {proposal.scope.region_id}")

    def _validate_reference_compatibility(
        self, reference: StyleReference, topology_digest: str
    ) -> None:
        profile = self.registry.profiles[(reference.profile_id, reference.profile_version)]
        row = self.connection.execute(
            "select compatibility_key from world_topology_contract where workspace_id=%s "
            "and world_id=%s and topology_digest=%s",
            (self.workspace_id, self.world_id, topology_digest),
        ).fetchone()
        if row is None:
            raise ProtectedTopologyConflict("the protected topology contract is unavailable")
        if profile.compatibility_key != row["compatibility_key"]:
            raise InvalidStyleData(
                f"world profile {reference.profile_id}@{reference.profile_version} requires "
                f"{profile.compatibility_key}, but topology {topology_digest} requires "
                f"{row['compatibility_key']}"
            )

    def _filter_version_regions(self, version: StyleVersion, topology_digest: str) -> StyleVersion:
        current_regions = {
            row["region_id"]
            for row in self.connection.execute(
                "select region_id from world_topology_region where workspace_id=%s "
                "and world_id=%s and topology_digest=%s",
                (self.workspace_id, self.world_id, topology_digest),
            ).fetchall()
        }
        omitted = sorted(set(version.region_styles) - current_regions)
        if not omitted:
            return version
        return replace(
            version,
            region_styles={
                region_id: reference
                for region_id, reference in version.region_styles.items()
                if region_id in current_regions
            },
            warnings=version.warnings
            + tuple(
                f"Regional style on {region_id} is outside the current topology; override ignored."
                for region_id in omitted
            ),
        )

    @staticmethod
    def _validate_provenance(provenance: ProposalProvenance) -> None:
        if not isinstance(provenance.actor, uuid.UUID):
            raise InvalidStyleData("proposal actor must be a UUID")
        reference = (provenance.origin_reference or "").strip()
        if provenance.origin is not ProposalOrigin.USER and not reference:
            raise InvalidStyleData(
                f"{provenance.origin.value} proposals require an origin reference"
            )
        if len(reference) > 500:
            raise InvalidStyleData("proposal origin reference is too long")

    def _validate_proposal_provenance(self, proposal: StyleProposal) -> None:
        self._validate_provenance(proposal.provenance)
        if len(set(proposal.reference_ids)) != len(proposal.reference_ids) or any(
            not value.strip() or len(value) > 500 for value in proposal.reference_ids
        ):
            raise InvalidStyleData("style proposal reference ids must be unique and non-empty")
        if proposal.provenance.origin is ProposalOrigin.COMPANION:
            if (
                not (proposal.model_id or "").strip()
                or not (proposal.prompt_version or "").strip()
                or not proposal.reference_ids
            ):
                raise InvalidStyleData(
                    "Companion style proposals require model, prompt version, and reference ids"
                )
        elif proposal.model_id is not None or proposal.prompt_version is not None:
            raise InvalidStyleData(
                "only Companion style proposals may carry model and prompt provenance"
            )
        if len(proposal.model_id or "") > 300 or len(proposal.prompt_version or "") > 300:
            raise InvalidStyleData("style proposal model or prompt version is too long")

    def _validate_refinement(self, proposal: StyleProposal) -> None:
        if proposal.refines_proposal_id is None:
            return
        row = self.connection.execute(
            "select 1 from world_style_proposal where workspace_id=%s and world_id=%s "
            "and proposal_id=%s",
            (self.workspace_id, self.world_id, proposal.refines_proposal_id),
        ).fetchone()
        if row is None:
            raise InvalidStyleData("refinement names no prior authorised style proposal")

    def _binding_for_reference(
        self, reference: StyleReference
    ) -> tuple[dict[str, Any], dict[str, str]]:
        binding = self.registry.recipe_binding(reference)
        return binding, dict(binding["capabilityMapping"])

    def _proposal_binding(self, reference: StyleReference) -> tuple[dict[str, Any], dict[str, str]]:
        try:
            return self._binding_for_reference(reference)
        except InvalidStyleData:
            return (
                {
                    "schemaVersion": 1,
                    "state": "unregistered",
                    "profileId": reference.profile_id,
                    "profileVersion": reference.profile_version,
                    "modules": [],
                },
                {},
            )

    def _validate_topology_contract(self, contract: TopologyContract) -> None:
        if contract.world_id != self.world_id:
            raise ProtectedTopologyConflict(
                f"topology is for {contract.world_id}, repository is for {self.world_id}"
            )
        if not contract.topology_digest or len(contract.topology_digest) > 256:
            raise ProtectedTopologyConflict("topology digest must be 1 to 256 characters")
        if not contract.compatibility_key.strip() or len(contract.compatibility_key) > 200:
            raise ProtectedTopologyConflict(
                "topology compatibility key must be 1 to 200 characters"
            )
        if len(set(contract.region_ids)) != len(contract.region_ids) or any(
            not region or len(region) > 500 for region in contract.region_ids
        ):
            raise ProtectedTopologyConflict("topology region ids must be unique and non-empty")
        source_keys: set[tuple[str | None, str]] = set()
        source_ids: set[uuid.UUID] = set()
        regions = set(contract.region_ids)
        for source in contract.source_slots:
            if source.source_id in source_ids or (source.region_id, source.slot_key) in source_keys:
                raise ProtectedTopologyConflict("topology source ids and slots must be unique")
            source_ids.add(source.source_id)
            source_keys.add((source.region_id, source.slot_key))
            if source.region_id is not None and source.region_id not in regions:
                raise ProtectedTopologyConflict(
                    f"source slot {source.slot_key} names unknown region {source.region_id}"
                )
            if _SLOT_KEY.fullmatch(source.slot_key) is None:
                raise ProtectedTopologyConflict(f"invalid source slot key {source.slot_key}")
            if (source.evidence_span_id is None) == (source.missing_reason is None):
                raise ProtectedTopologyConflict(
                    f"source slot {source.slot_key} must name evidence or an honest missing reason"
                )
            if source.missing_reason is not None and not source.missing_reason.strip():
                raise ProtectedTopologyConflict(
                    f"source slot {source.slot_key} has an empty missing-evidence reason"
                )

    def _assert_existing_topology_matches(self, contract: TopologyContract) -> None:
        topology = self.connection.execute(
            "select compatibility_key from world_topology_contract where workspace_id=%s "
            "and world_id=%s and topology_digest=%s",
            (self.workspace_id, self.world_id, contract.topology_digest),
        ).fetchone()
        assert topology is not None
        regions = {
            row["region_id"]
            for row in self.connection.execute(
                "select region_id from world_topology_region where workspace_id=%s and world_id=%s "
                "and topology_digest=%s",
                (self.workspace_id, self.world_id, contract.topology_digest),
            ).fetchall()
        }
        sources = {
            (
                row["source_id"],
                row["region_id"],
                row["slot_key"],
                row["evidence_span_id"],
                row["missing_reason"],
            )
            for row in self.connection.execute(
                "select source_id,region_id,slot_key,evidence_span_id,missing_reason "
                "from world_topology_source where workspace_id=%s and world_id=%s "
                "and topology_digest=%s",
                (self.workspace_id, self.world_id, contract.topology_digest),
            ).fetchall()
        }
        expected = {
            (
                source.source_id,
                source.region_id,
                source.slot_key,
                source.evidence_span_id,
                source.missing_reason,
            )
            for source in contract.source_slots
        }
        if (
            topology["compatibility_key"] != contract.compatibility_key
            or regions != set(contract.region_ids)
            or sources != expected
        ):
            raise ProtectedTopologyConflict(
                "a topology digest cannot be reused for different compatibility, regions, "
                "or source bindings"
            )

    def _source_rows(
        self, topology_digest: str, *, source_id: uuid.UUID | None = None
    ) -> Sequence[Mapping[str, Any]]:
        source_filter = " and ws.source_id=%s" if source_id is not None else ""
        params: list[Any] = [self.workspace_id, self.world_id, topology_digest]
        if source_id is not None:
            params.append(source_id)
        return self.connection.execute(
            "select ws.source_id,ws.region_id,ws.slot_key,ws.evidence_span_id,ws.missing_reason,"
            "s.modality,b.blob_sha256,b.media_type,b.byte_size,b.storage_key,b.purged_at,"
            "t.disp_w,t.disp_h,t.coded_w,t.coded_h,a.utc_instant,a.uncertainty_ms,"
            "case when s.span_id is null then false else "
            "tombstone_blocks_any_span(ws.workspace_id,array[s.span_id]) end as tombstoned,"
            "exists(select 1 from capture c where c.workspace_id=ws.workspace_id "
            "and c.blob_sha256=s.blob_sha256 and c.deleted_at is null) as live_capture "
            ",array(select c.capture_id from capture c where c.workspace_id=ws.workspace_id "
            "and c.blob_sha256=s.blob_sha256 and c.deleted_at is null "
            "order by c.capture_id) as capture_ids "
            "from world_topology_source ws "
            "left join evidence_span s on s.workspace_id=ws.workspace_id "
            "and s.span_id=ws.evidence_span_id "
            "left join blob b on b.blob_sha256=s.blob_sha256 "
            "left join media_track t on t.blob_sha256=s.blob_sha256 and t.track_key=s.track_key "
            "left join lateral (select ca.utc_instant,ca.uncertainty_ms from clock_anchor ca "
            "where ca.track_id=t.track_id order by ca.uncertainty_ms,ca.anchor_id limit 1) a "
            "on true where ws.workspace_id=%s and ws.world_id=%s and ws.topology_digest=%s"
            + source_filter
            + " order by ws.region_id nulls first,ws.slot_key,ws.source_id",
            params,
        ).fetchall()

    @staticmethod
    def _source_from_row(row: Mapping[str, Any], store: ContentAddressedStore) -> WorldSourceMedia:
        state = SourceMediaState.AVAILABLE
        reason: str | None = None
        if row["evidence_span_id"] is None:
            state = SourceMediaState.MISSING_EVIDENCE
            reason = row["missing_reason"]
        elif row["tombstoned"]:
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source evidence was deleted"
        elif not row["live_capture"]:
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source capture was deleted"
        elif row["purged_at"] is not None or row["storage_key"] is None:
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source bytes were purged"
        elif row["blob_sha256"] is None or not store.exists(BlobId(bytes(row["blob_sha256"]))):
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source bytes are missing from storage"
        available = state is SourceMediaState.AVAILABLE
        return WorldSourceMedia(
            source_id=row["source_id"],
            slot_key=row["slot_key"],
            region_id=row["region_id"],
            state=state,
            reason=reason,
            evidence_span_id=row["evidence_span_id"],
            evidence_path=(f"/evidence/{row['evidence_span_id']}" if available else None),
            modality=row["modality"],
            media_type=row["media_type"],
            byte_size=row["byte_size"],
            width=row["disp_w"] or row["coded_w"],
            height=row["disp_h"] or row["coded_h"],
            captured_at=row["utc_instant"],
            captured_at_uncertainty_ms=row["uncertainty_ms"],
            capture_ids=tuple(row["capture_ids"]) if available else (),
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
        "created_at": value.created_at.isoformat(),
    }


def _provenance_from_row(row: Mapping[str, Any]) -> ProposalProvenance:
    return ProposalProvenance(ProposalOrigin(row["origin"]), row["actor"], row["origin_reference"])


def _error_code(error: Exception) -> str:
    if isinstance(error, StaleStyleVersion):
        return "stale_style_version"
    if isinstance(error, ProtectedTopologyConflict):
        return "protected_topology_conflict"
    return "invalid_style_data"
