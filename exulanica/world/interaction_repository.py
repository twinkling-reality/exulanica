"""Durable interaction-policy proposals shared by Settings and Companion."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.world.errors import (
    InvalidInteractionData,
    InvalidInteractionPreviewState,
    StaleInteractionPolicy,
    UnknownWorldResource,
)
from exulanica.world.interaction import (
    INTERACTION_POLICY_REGISTRY,
    InteractionPolicyRegistry,
    InteractionPolicyState,
    InteractionPolicyValue,
    InteractionPolicyVersion,
    InteractionPreview,
    InteractionProposal,
    InteractionProposalRecord,
    InteractionRecommendation,
    default_interaction_state,
)
from exulanica.world.models import DEFAULT_WORLD_ID, ProposalOrigin, ProposalProvenance

__all__ = ["WorldInteractionPolicyRepository"]

_WORKSPACE_LOCK_SEED: Final = 880_024
_PRIVATE_INPUT_KEYS: Final = frozenset(
    {"conversation", "messages", "raw_utterance", "transcript", "prompt_text"}
)


class WorldInteractionPolicyRepository:
    """Workspace-scoped, immutable policy history with one protected current pointer."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        registry: InteractionPolicyRegistry = INTERACTION_POLICY_REGISTRY,
        world_id: str = DEFAULT_WORLD_ID,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.registry = registry
        self.world_id = world_id

    def state(self) -> InteractionPolicyState:
        state = self._state(for_update=False)
        structure_id, topology = self._structure_base()
        if state is None:
            return default_interaction_state(
                structure_snapshot_id=structure_id, topology_sha256=topology
            )
        version = self._version(state["current_version_id"])
        return InteractionPolicyState(version, version.parameters, structure_id, topology)

    def versions(self) -> tuple[InteractionPolicyVersion, ...]:
        rows = self.connection.execute(
            "select * from world_interaction_policy_version "
            "where workspace_id=%s and world_id=%s order by revision",
            (self.workspace_id, self.world_id),
        ).fetchall()
        return tuple(self._row_to_version(row) for row in rows)

    def proposal_record(self, proposal_id: uuid.UUID) -> InteractionProposalRecord:
        row = self.connection.execute(
            "select * from world_interaction_policy_proposal "
            "where workspace_id=%s and world_id=%s and proposal_id=%s",
            (self.workspace_id, self.world_id, proposal_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such interaction policy proposal")
        proposal = InteractionProposal(
            row["proposal_id"],
            ProposalProvenance(
                ProposalOrigin(row["origin"]), row["actor"], row["origin_reference"]
            ),
            row["capability_patch"],
            row["base_policy_version_id"],
            row["base_structure_snapshot_id"],
            row["base_topology_sha256"],
            row["proposal_input"],
            row["explanation"],
            tuple(row["reference_ids"]),
            row["model_id"],
            row["prompt_version"],
            row["refines_proposal_id"],
        )
        return InteractionProposalRecord(
            proposal,
            row["status"],
            tuple(row["validation_issues"]),
            row["created_at"],
            row["updated_at"],
        )

    def preview(self, proposal: InteractionProposal) -> InteractionPreview:
        """Persist a deterministic isolated candidate or an inspectable rejection."""
        self._validate_provenance(proposal)
        rejected: Exception | None = None
        result: InteractionPreview | None = None
        with self.connection.transaction():
            self._lock_workspace()
            state = self._state(for_update=True)
            structure_id, topology = self._structure_base()
            current = (
                dict(self.registry.defaults)
                if state is None
                else dict(self._version(state["current_version_id"]).parameters)
            )
            actual_policy_id = None if state is None else state["current_version_id"]
            if proposal.base_policy_version_id != actual_policy_id:
                rejected = StaleInteractionPolicy(
                    "the interaction proposal was computed against another current policy"
                )
            elif (
                proposal.base_structure_snapshot_id != structure_id
                or proposal.base_topology_sha256 != topology
            ):
                rejected = StaleInteractionPolicy(
                    "the protected structural world changed after this interaction proposal"
                )
            else:
                try:
                    patch = self.registry.validate_patch(proposal.capability_patch)
                    candidate = self.registry.candidate(current, patch)
                    if candidate == current:
                        raise InvalidInteractionData(
                            "the interaction proposal changes no durable capability"
                        )
                    self._validate_refinement(proposal)
                except InvalidInteractionData as exc:
                    rejected = exc
            status = (
                "stale"
                if isinstance(rejected, StaleInteractionPolicy)
                else ("rejected" if rejected is not None else "previewed")
            )
            self._insert_proposal(proposal, status, rejected)
            if rejected is not None:
                self._audit(
                    "proposal_rejected",
                    proposal.provenance,
                    proposal_id=proposal.proposal_id,
                    details={"error": type(rejected).__name__, "detail": str(rejected)},
                )
            else:
                preview_id = uuid.uuid4()
                candidate_sha256 = self.registry.digest(candidate)
                row = self.connection.execute(
                    "insert into world_interaction_policy_preview "
                    "(preview_id,workspace_id,world_id,proposal_id,candidate_parameters,"
                    "candidate_sha256) values (%s,%s,%s,%s,%s,%s) returning created_at",
                    (
                        preview_id,
                        self.workspace_id,
                        self.world_id,
                        proposal.proposal_id,
                        Jsonb(candidate),
                        candidate_sha256,
                    ),
                ).fetchone()
                assert row is not None
                self._audit(
                    "preview_created",
                    proposal.provenance,
                    proposal_id=proposal.proposal_id,
                    preview_id=preview_id,
                    details={"candidate_sha256": candidate_sha256},
                )
                if proposal.refines_proposal_id is not None:
                    self._audit(
                        "proposal_refined",
                        proposal.provenance,
                        proposal_id=proposal.proposal_id,
                        preview_id=preview_id,
                        details={"refines_proposal_id": str(proposal.refines_proposal_id)},
                    )
                result = InteractionPreview(
                    preview_id,
                    proposal,
                    candidate,
                    candidate_sha256,
                    row["created_at"],
                )
        if rejected is not None:
            raise rejected
        assert result is not None
        return result

    def apply(
        self,
        preview_id: uuid.UUID,
        *,
        base_policy_version_id: uuid.UUID | None,
        base_structure_snapshot_id: uuid.UUID | None,
        base_topology_sha256: str | None,
        applied_by: uuid.UUID,
    ) -> InteractionPolicyVersion:
        failure: Exception | None = None
        applied: InteractionPolicyVersion | None = None
        with self.connection.transaction():
            self._lock_workspace()
            state = self._state(for_update=True)
            preview = self._preview_row(preview_id, for_update=True)
            if preview["preview_status"] != "open":
                raise InvalidInteractionPreviewState(
                    f"interaction preview {preview_id} is {preview['preview_status']}, not open"
                )
            actual_policy_id = None if state is None else state["current_version_id"]
            structure_id, topology = self._structure_base()
            supplied = (
                base_policy_version_id,
                base_structure_snapshot_id,
                base_topology_sha256,
            )
            proposed = (
                preview["base_policy_version_id"],
                preview["base_structure_snapshot_id"],
                preview["base_topology_sha256"],
            )
            actual = (actual_policy_id, structure_id, topology)
            if supplied != actual or proposed != actual:
                failure = StaleInteractionPolicy(
                    "the current interaction policy or protected structural world changed"
                )
                self._close_stale(preview, applied_by, actual)
            else:
                candidate = self.registry.validate_parameters(preview["candidate_parameters"])
                candidate_sha256 = self.registry.digest(candidate)
                if candidate_sha256 != preview["candidate_sha256"]:
                    raise InvalidInteractionData(
                        "persisted interaction preview digest does not match its candidate"
                    )
                parent = None if state is None else self._version(state["current_version_id"])
                revision = 0 if parent is None else parent.revision + 1
                version_id = uuid.uuid4()
                provenance = self._provenance_from_row(preview)
                row = self.connection.execute(
                    "insert into world_interaction_policy_version "
                    "(version_id,workspace_id,world_id,revision,parent_version_id,parameters,"
                    "policy_sha256,applied_from_proposal_id,origin,actor,origin_reference) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                    (
                        version_id,
                        self.workspace_id,
                        self.world_id,
                        revision,
                        None if parent is None else parent.version_id,
                        Jsonb(candidate),
                        candidate_sha256,
                        preview["proposal_id"],
                        provenance.origin.value,
                        provenance.actor,
                        provenance.origin_reference,
                    ),
                ).fetchone()
                assert row is not None
                if state is None:
                    self.connection.execute(
                        "insert into world_interaction_policy_state "
                        "(workspace_id,world_id,current_version_id) values (%s,%s,%s)",
                        (self.workspace_id, self.world_id, version_id),
                    )
                else:
                    self.connection.execute(
                        "update world_interaction_policy_state set current_version_id=%s,"
                        "updated_at=now() where workspace_id=%s and world_id=%s",
                        (version_id, self.workspace_id, self.world_id),
                    )
                self.connection.execute(
                    "update world_interaction_policy_preview set status='applied',closed_at=now() "
                    "where workspace_id=%s and world_id=%s and preview_id=%s",
                    (self.workspace_id, self.world_id, preview_id),
                )
                self.connection.execute(
                    "update world_interaction_policy_proposal set status='applied',"
                    "updated_at=now() "
                    "where workspace_id=%s and world_id=%s and proposal_id=%s",
                    (self.workspace_id, self.world_id, preview["proposal_id"]),
                )
                self._audit(
                    "preview_applied",
                    provenance,
                    proposal_id=preview["proposal_id"],
                    preview_id=preview_id,
                    version_id=version_id,
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
            if preview["preview_status"] == "discarded":
                return
            if preview["preview_status"] != "open":
                raise InvalidInteractionPreviewState(
                    f"interaction preview {preview_id} is {preview['preview_status']}, not open"
                )
            provenance = self._provenance_from_row(preview)
            self.connection.execute(
                "update world_interaction_policy_preview set status='discarded',closed_at=now() "
                "where workspace_id=%s and world_id=%s and preview_id=%s",
                (self.workspace_id, self.world_id, preview_id),
            )
            self.connection.execute(
                "update world_interaction_policy_proposal set status='discarded',updated_at=now() "
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
        base_policy_version_id: uuid.UUID,
        base_structure_snapshot_id: uuid.UUID | None,
        base_topology_sha256: str | None,
        provenance: ProposalProvenance,
    ) -> InteractionPolicyVersion:
        if provenance.origin is ProposalOrigin.COMPANION:
            raise InvalidInteractionData(
                "Companion rollback requires a new explicit proposal with model provenance"
            )
        self._validate_basic_provenance(provenance)
        with self.connection.transaction():
            self._lock_workspace()
            state = self._state(for_update=True)
            if state is None:
                raise StaleInteractionPolicy("there is no current interaction policy to roll back")
            structure_id, topology = self._structure_base()
            if (
                state["current_version_id"] != base_policy_version_id
                or structure_id != base_structure_snapshot_id
                or topology != base_topology_sha256
            ):
                raise StaleInteractionPolicy(
                    "the current interaction policy or protected structural world changed"
                )
            current = self._version(state["current_version_id"])
            target = self._version(target_version_id)
            version_id = uuid.uuid4()
            row = self.connection.execute(
                "insert into world_interaction_policy_version "
                "(version_id,workspace_id,world_id,revision,parent_version_id,parameters,"
                "policy_sha256,rollback_target_version_id,origin,actor,origin_reference) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                (
                    version_id,
                    self.workspace_id,
                    self.world_id,
                    current.revision + 1,
                    current.version_id,
                    Jsonb(dict(target.parameters)),
                    target.policy_sha256,
                    target.version_id,
                    provenance.origin.value,
                    provenance.actor,
                    provenance.origin_reference,
                ),
            ).fetchone()
            assert row is not None
            self.connection.execute(
                "update world_interaction_policy_state set current_version_id=%s,updated_at=now() "
                "where workspace_id=%s and world_id=%s",
                (version_id, self.workspace_id, self.world_id),
            )
            self._audit(
                "policy_rolled_back",
                provenance,
                version_id=version_id,
                details={"target_version_id": str(target.version_id)},
            )
            return self._row_to_version(row)

    def recommendations(self) -> tuple[InteractionRecommendation, ...]:
        """Read observed accepted choices; never create, preview, or apply a proposal."""
        current = self.state().parameters
        rows = self.connection.execute(
            "select origin,status,capability_patch from world_interaction_policy_proposal "
            "where workspace_id=%s and world_id=%s order by created_at,proposal_id",
            (self.workspace_id, self.world_id),
        ).fetchall()
        accepted: Counter[tuple[str, bytes]] = Counter()
        rejected: Counter[tuple[str, bytes]] = Counter()
        values: dict[tuple[str, bytes], InteractionPolicyValue] = {}
        for row in rows:
            for key, value in row["capability_patch"].items():
                identity = (key, canonical_json(value))
                values[identity] = value
                if row["status"] == "applied" and row["origin"] in {"user", "settings"}:
                    accepted[identity] += 1
                if row["status"] in {"rejected", "discarded"}:
                    rejected[identity] += 1
        result: list[InteractionRecommendation] = []
        for identity, count in sorted(accepted.items(), key=lambda item: item[0]):
            key, _encoded = identity
            value = values[identity]
            if count < 2 or rejected[identity] > 0 or current[key] == value:
                continue
            result.append(
                InteractionRecommendation(
                    key,
                    value,
                    count,
                    rejected[identity],
                    f"You explicitly chose this value {count} times; nothing has been changed.",
                )
            )
        return tuple(result)

    # -- internal validation and rows -----------------------------------------------------

    def _validate_provenance(self, proposal: InteractionProposal) -> None:
        self._validate_basic_provenance(proposal.provenance)
        if not proposal.explanation.strip():
            raise InvalidInteractionData("an interaction proposal needs an inspectable explanation")
        if any(not value.strip() or len(value) > 500 for value in proposal.reference_ids):
            raise InvalidInteractionData("interaction proposal reference ids must be non-empty")
        if proposal.provenance.origin is ProposalOrigin.COMPANION:
            if (
                not (proposal.model_id or "").strip()
                or not (proposal.prompt_version or "").strip()
                or not proposal.reference_ids
            ):
                raise InvalidInteractionData(
                    "Companion proposals require model, prompt version, and reference ids"
                )
        elif proposal.model_id is not None or proposal.prompt_version is not None:
            raise InvalidInteractionData(
                "only Companion proposals may carry model and prompt provenance"
            )
        try:
            canonical_json(proposal.proposal_input)
            canonical_json(proposal.capability_patch)
        except Exception as exc:
            raise InvalidInteractionData(f"proposal input is not canonical JSON: {exc}") from exc
        private = sorted(_private_keys(proposal.proposal_input) & _PRIVATE_INPUT_KEYS)
        if private:
            raise InvalidInteractionData(
                "conversation content is excluded from durable interaction policy input: "
                + ", ".join(private)
            )

    @staticmethod
    def _validate_basic_provenance(provenance: ProposalProvenance) -> None:
        if not isinstance(provenance.actor, uuid.UUID):
            raise InvalidInteractionData("interaction policy actor must be a UUID")
        if (
            provenance.origin is not ProposalOrigin.USER
            and not (provenance.origin_reference or "").strip()
        ):
            raise InvalidInteractionData("Settings and Companion require an origin reference")

    def _validate_refinement(self, proposal: InteractionProposal) -> None:
        if proposal.refines_proposal_id is None:
            return
        row = self.connection.execute(
            "select 1 from world_interaction_policy_proposal "
            "where workspace_id=%s and world_id=%s and proposal_id=%s",
            (self.workspace_id, self.world_id, proposal.refines_proposal_id),
        ).fetchone()
        if row is None:
            raise InvalidInteractionData("refinement names no prior authorised proposal")

    def _insert_proposal(
        self, proposal: InteractionProposal, status: str, rejected: Exception | None
    ) -> None:
        """Record the proposal under the caller's id, or refuse an id this workspace has used.

        The id is unique within the workspace (migration 0102), so only this workspace's own
        proposals can collide with it, and the refusal is the one a reused style proposal id gets.
        """
        try:
            self._write_proposal(proposal, status, rejected)
        except psycopg.errors.UniqueViolation as exc:
            raise InvalidInteractionData(
                f"proposal id {proposal.proposal_id} was already used"
            ) from exc

    def _write_proposal(
        self, proposal: InteractionProposal, status: str, rejected: Exception | None
    ) -> None:
        self.connection.execute(
            "insert into world_interaction_policy_proposal "
            "(proposal_id,workspace_id,world_id,origin,actor,origin_reference,model_id,"
            "prompt_version,proposal_input,reference_ids,explanation,capability_patch,"
            "base_policy_version_id,base_structure_snapshot_id,base_topology_sha256,"
            "refines_proposal_id,status,validation_issues) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                proposal.proposal_id,
                self.workspace_id,
                self.world_id,
                proposal.provenance.origin.value,
                proposal.provenance.actor,
                proposal.provenance.origin_reference,
                proposal.model_id,
                proposal.prompt_version,
                Jsonb(dict(proposal.proposal_input)),
                list(proposal.reference_ids),
                proposal.explanation,
                Jsonb(dict(proposal.capability_patch)),
                proposal.base_policy_version_id,
                proposal.base_structure_snapshot_id,
                proposal.base_topology_sha256,
                proposal.refines_proposal_id,
                status,
                Jsonb([] if rejected is None else [str(rejected)]),
            ),
        )

    def _state(self, *, for_update: bool) -> Mapping[str, Any] | None:
        return self.connection.execute(
            "select * from world_interaction_policy_state where workspace_id=%s and world_id=%s"
            + (" for update" if for_update else ""),
            (self.workspace_id, self.world_id),
        ).fetchone()

    def _structure_base(self) -> tuple[uuid.UUID | None, str | None]:
        row = self.connection.execute(
            "select st.current_snapshot_id,s.topology_sha256 "
            "from world_structure_state st join world_structure_snapshot s "
            "on s.workspace_id=st.workspace_id and s.world_id=st.world_id "
            "and s.snapshot_id=st.current_snapshot_id "
            "where st.workspace_id=%s and st.world_id=%s",
            (self.workspace_id, self.world_id),
        ).fetchone()
        return (None, None) if row is None else (row["current_snapshot_id"], row["topology_sha256"])

    def _version(self, version_id: uuid.UUID) -> InteractionPolicyVersion:
        row = self.connection.execute(
            "select * from world_interaction_policy_version "
            "where workspace_id=%s and world_id=%s and version_id=%s",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such interaction policy version")
        return self._row_to_version(row)

    def _preview_row(self, preview_id: uuid.UUID, *, for_update: bool) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select v.*,v.status as preview_status,p.origin,p.actor,p.origin_reference,"
            "p.proposal_id,p.base_policy_version_id,p.base_structure_snapshot_id,"
            "p.base_topology_sha256 from world_interaction_policy_preview v "
            "join world_interaction_policy_proposal p on p.workspace_id=v.workspace_id "
            "and p.world_id=v.world_id and p.proposal_id=v.proposal_id "
            "where v.workspace_id=%s and v.world_id=%s and v.preview_id=%s"
            + (" for update of v" if for_update else ""),
            (self.workspace_id, self.world_id, preview_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such interaction policy preview")
        return row

    @staticmethod
    def _row_to_version(row: Mapping[str, Any]) -> InteractionPolicyVersion:
        return InteractionPolicyVersion(
            row["version_id"],
            row["revision"],
            row["parent_version_id"],
            row["parameters"],
            row["policy_sha256"],
            row["applied_from_proposal_id"],
            row["rollback_target_version_id"],
            ProposalProvenance(
                ProposalOrigin(row["origin"]), row["actor"], row["origin_reference"]
            ),
            row["created_at"],
        )

    @staticmethod
    def _provenance_from_row(row: Mapping[str, Any]) -> ProposalProvenance:
        return ProposalProvenance(
            ProposalOrigin(row["origin"]), row["actor"], row["origin_reference"]
        )

    def _close_stale(
        self,
        preview: Mapping[str, Any],
        actor: uuid.UUID,
        actual: tuple[uuid.UUID | None, uuid.UUID | None, str | None],
    ) -> None:
        self.connection.execute(
            "update world_interaction_policy_preview set status='stale',closed_at=now() "
            "where workspace_id=%s and world_id=%s and preview_id=%s",
            (self.workspace_id, self.world_id, preview["preview_id"]),
        )
        self.connection.execute(
            "update world_interaction_policy_proposal set status='stale',updated_at=now() "
            "where workspace_id=%s and world_id=%s and proposal_id=%s",
            (self.workspace_id, self.world_id, preview["proposal_id"]),
        )
        self._audit(
            "preview_stale",
            self._provenance_from_row(preview),
            proposal_id=preview["proposal_id"],
            preview_id=preview["preview_id"],
            details={
                "applied_by": str(actor),
                "current_policy_version_id": None if actual[0] is None else str(actual[0]),
                "current_structure_snapshot_id": None if actual[1] is None else str(actual[1]),
                "current_topology_sha256": actual[2],
            },
        )

    def _audit(
        self,
        event_type: str,
        provenance: ProposalProvenance,
        *,
        details: Mapping[str, Any],
        proposal_id: uuid.UUID | None = None,
        preview_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> None:
        self.connection.execute(
            "insert into world_interaction_policy_audit_event "
            "(workspace_id,world_id,event_type,origin,actor,origin_reference,proposal_id,"
            "preview_id,version_id,details) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                event_type,
                provenance.origin.value,
                provenance.actor,
                provenance.origin_reference,
                proposal_id,
                preview_id,
                version_id,
                Jsonb(dict(details)),
            ),
        )

    def _lock_workspace(self) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
            (self.workspace_id, _WORKSPACE_LOCK_SEED),
        )


def _private_keys(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str):
                result.add(key.lower())
            result.update(_private_keys(nested))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for nested in value:
            result.update(_private_keys(nested))
    return result
