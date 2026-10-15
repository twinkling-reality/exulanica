"""The checks a world's style proposal and its topology contract are held to.

A part of :class:`~exulanica.world.repository.WorldStyleRepository` (its methods read the
repository's connection, workspace, world, registry and current state): a proposal's scope against
the topology, whether a structure and a style are compatible, its references, the regions a version
keeps, its provenance and appearance basis (evidence or authored design), a refinement, and a
topology contract against the one already registered.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from typing import Any, Final

from exulanica.world.errors import (
    InvalidStyleData,
    ProtectedTopologyConflict,
)
from exulanica.world.models import (
    ProposalOrigin,
    ProposalProvenance,
    StyleProposal,
    StyleReference,
    StyleVersion,
    TopologyContract,
)
from exulanica.world.style_structure import (
    AuthoredVersionRef,
    CompatibilityIntent,
    ComposedTopologyRef,
    SourceAttachmentRef,
    StructuralSnapshotRef,
    StructureStyleCompatibility,
    StyleStructureFacts,
    StyleVersionRef,
    classify_structure_style_compatibility,
    raise_for_incompatible_structure_style,
)
from exulanica.world.worlds import world_kind

#: What a Companion appearance proposal is drawn from. ``evidence``: the world's own evidence,
#: named by reference id. ``authored_design``: a design choice, naming none.
EVIDENCE_BASIS: Final = "evidence"
AUTHORED_DESIGN_BASIS: Final = "authored_design"
APPEARANCE_BASES: Final = frozenset({EVIDENCE_BASIS, AUTHORED_DESIGN_BASIS})

_SLOT_KEY: Final = re.compile(r"^[a-z][a-z0-9.-]*$")


class StyleProposalChecks:
    """Proposal and topology checks of :class:`~exulanica.world.repository.WorldStyleRepository`."""

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

    def classify_structure_style_compatibility(
        self,
        *,
        intent: CompatibilityIntent,
        style: StyleVersionRef | None = None,
        composed: ComposedTopologyRef | None = None,
        snapshot: StructuralSnapshotRef | None = None,
        authored: AuthoredVersionRef | None = None,
        attachments: tuple[SourceAttachmentRef, ...] = (),
        proposed: TopologyContract | None = None,
        conflicting_addresses: bool = False,
    ) -> StructureStyleCompatibility:
        """Classify typed plane identities. This method writes nothing."""

        return classify_structure_style_compatibility(
            self._structure_style_facts(
                intent=intent,
                style=style,
                composed=composed,
                snapshot=snapshot,
                authored=authored,
                attachments=attachments,
                proposed=proposed,
                conflicting_addresses=conflicting_addresses,
            )
        )

    def _require_structure_style_compatibility(
        self,
        *,
        intent: CompatibilityIntent,
        style: StyleVersionRef | None = None,
        composed: ComposedTopologyRef | None = None,
        snapshot: StructuralSnapshotRef | None = None,
        authored: AuthoredVersionRef | None = None,
        attachments: tuple[SourceAttachmentRef, ...] = (),
        proposed: TopologyContract | None = None,
        conflicting_addresses: bool = False,
    ) -> StructureStyleCompatibility:
        decision = self.classify_structure_style_compatibility(
            intent=intent,
            style=style,
            composed=composed,
            snapshot=snapshot,
            authored=authored,
            attachments=attachments,
            proposed=proposed,
            conflicting_addresses=conflicting_addresses,
        )
        raise_for_incompatible_structure_style(decision)
        return decision

    def _structure_style_facts(
        self,
        *,
        intent: CompatibilityIntent,
        style: StyleVersionRef | None,
        composed: ComposedTopologyRef | None,
        snapshot: StructuralSnapshotRef | None,
        authored: AuthoredVersionRef | None,
        attachments: tuple[SourceAttachmentRef, ...],
        proposed: TopologyContract | None,
        conflicting_addresses: bool,
    ) -> StyleStructureFacts:
        state = self._state()
        live_style_version_id = None if state is None else state["current_style_version_id"]
        live_composed_digest = None if state is None else str(state["current_topology_digest"])
        live_key = None
        if live_composed_digest is not None:
            live_contract = self.connection.execute(
                "select compatibility_key from world_topology_contract where workspace_id=%s "
                "and world_id=%s and topology_digest=%s",
                (self.workspace_id, self.world_id, live_composed_digest),
            ).fetchone()
            if live_contract is not None:
                live_key = live_contract["compatibility_key"]

        named_style_version_id = None if style is None else style.version_id
        named_style_known = True
        named_style_is_current = False
        named_style_bound_digest = None
        named_style_key = None
        if style is not None:
            row = self.connection.execute(
                "select version_id,topology_digest,global_profile_id,global_profile_version "
                "from world_style_version where workspace_id=%s and world_id=%s "
                "and version_id=%s",
                (self.workspace_id, self.world_id, style.version_id),
            ).fetchone()
            if row is None:
                named_style_known = False
            else:
                named_style_is_current = row["version_id"] == live_style_version_id
                named_style_bound_digest = row["topology_digest"]
                profile = self.registry.profiles.get(
                    (row["global_profile_id"], row["global_profile_version"])
                )
                if profile is not None:
                    named_style_key = profile.compatibility_key
        elif intent is CompatibilityIntent.REGISTER_TOPOLOGY and state is None:
            # First register binds the default profile. Classify that family before history insert.
            named_style_key = self.registry.profiles[self.registry.default_key].compatibility_key

        named_snapshot_id = None if snapshot is None else snapshot.snapshot_id
        named_snapshot_known = True
        named_snapshot_topology = None
        if snapshot is not None:
            snap = self.connection.execute(
                "select topology_sha256 from world_structure_snapshot where workspace_id=%s "
                "and world_id=%s and snapshot_id=%s",
                (self.workspace_id, self.world_id, snapshot.snapshot_id),
            ).fetchone()
            if snap is None:
                named_snapshot_known = False
            else:
                named_snapshot_topology = snap["topology_sha256"]

        named_authored_id = None if authored is None else authored.version_id
        named_authored_known = True
        authored_source = None
        if authored is not None:
            version = self.connection.execute(
                "select source_snapshot_id from world_alternate_version "
                "where workspace_id=%s and world_id=%s and version_id=%s",
                (self.workspace_id, self.world_id, authored.version_id),
            ).fetchone()
            if version is None:
                named_authored_known = False
            else:
                authored_source = version["source_snapshot_id"]

        attachments_named = bool(attachments)
        attachments_known = True
        attachments_expired = False
        if attachments:
            ids = [item.attachment_id for item in attachments]
            rows = self.connection.execute(
                "select a.attachment_id,auth.valid_until as authorization_valid_until,"
                "p.valid_until as screening_valid_until,statement_timestamp() as evaluated_at "
                "from saved_world_source_attachment a "
                "join capture_reconstruction_authorization auth "
                "on auth.workspace_id=a.workspace_id and auth.authorization_id=a.authorization_id "
                "join reconstruction_privacy_screening p "
                "on p.workspace_id=a.workspace_id and p.screening_id=a.screening_id "
                "where a.workspace_id=%s and a.attachment_id=any(%s)",
                (self.workspace_id, ids),
            ).fetchall()
            found = {row["attachment_id"] for row in rows}
            if found != set(ids):
                attachments_known = False
            for row in rows:
                at = row["evaluated_at"]
                if (
                    row["authorization_valid_until"] is not None
                    and row["authorization_valid_until"] <= at
                ) or (
                    row["screening_valid_until"] is not None and row["screening_valid_until"] <= at
                ):
                    attachments_expired = True

        return StyleStructureFacts(
            intent=intent,
            world_id=self.world_id,
            live_style_version_id=live_style_version_id,
            live_composed_digest=live_composed_digest,
            live_composed_compatibility_key=live_key,
            named_style_version_id=named_style_version_id,
            named_style_known=named_style_known,
            named_style_is_current=named_style_is_current,
            named_style_bound_digest=named_style_bound_digest,
            named_style_compatibility_key=named_style_key,
            named_composed_digest=None if composed is None else composed.digest,
            named_snapshot_id=named_snapshot_id,
            named_snapshot_known=named_snapshot_known,
            named_snapshot_topology_sha256=named_snapshot_topology,
            named_authored_version_id=named_authored_id,
            named_authored_known=named_authored_known,
            authored_source_snapshot_id=authored_source,
            proposed_digest=None if proposed is None else proposed.topology_digest,
            proposed_compatibility_key=(None if proposed is None else proposed.compatibility_key),
            proposed_has_sourced_slots=(
                False
                if proposed is None
                else any(
                    slot.evidence_span_id is not None or slot.missing_reason is not None
                    for slot in proposed.source_slots
                )
            ),
            attachments_named=attachments_named,
            attachments_known=attachments_known,
            attachments_expired=attachments_expired,
            conflicting_addresses=conflicting_addresses,
            starter_world=(
                self._starter_world_fact()
                if intent is CompatibilityIntent.REGISTER_TOPOLOGY
                else None
            ),
        )

    def _starter_world_fact(self) -> bool | None:
        """Whether the world is source-independent, as its registered kind states
        (:data:`exulanica.world.worlds.WORLD_KINDS`); ``None`` only for a world the registry does
        not hold, which the classifier refuses. Every world is registered before any world table
        names it (migration 0099), so the registry is the one place a world's kind is read.
        """

        registered = self.connection.execute(
            "select kind from world_identity where workspace_id=%s and world_id=%s",
            (self.workspace_id, self.world_id),
        ).fetchone()
        return None if registered is None else world_kind(registered["kind"]).source_independent

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
            # Two bases, each with its own rule about evidence, and neither may borrow the
            # other's: a proposal drawn from evidence names it, and a design choice names none,
            # so it never presents a reference nothing was drawn from. Migration 0128's check
            # holds the same rule in the database.
            basis = proposal.appearance_basis or EVIDENCE_BASIS
            if basis not in APPEARANCE_BASES:
                raise InvalidStyleData(f"unknown appearance basis {basis!r}")
            if (
                not (proposal.model_id or "").strip()
                or not (proposal.prompt_version or "").strip()
                or (basis == EVIDENCE_BASIS and not proposal.reference_ids)
            ):
                raise InvalidStyleData(
                    "Companion style proposals require model, prompt version, and reference ids"
                )
            if basis == AUTHORED_DESIGN_BASIS and proposal.reference_ids:
                raise InvalidStyleData(
                    "an authored-design proposal is drawn from no evidence and names none"
                )
        elif proposal.model_id is not None or proposal.prompt_version is not None:
            raise InvalidStyleData(
                "only Companion style proposals may carry model and prompt provenance"
            )
        elif proposal.appearance_basis is not None:
            raise InvalidStyleData("only Companion style proposals state an appearance basis")
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
