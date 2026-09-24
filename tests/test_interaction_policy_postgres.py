"""Transactional interaction-policy behavior on the production PostgreSQL schema."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.world import (
    INTERACTION_POLICY_REGISTRY,
    InvalidInteractionData,
    ProposalOrigin,
    ProposalProvenance,
    StaleInteractionPolicy,
    WorldInteractionPolicyRepository,
    WorldStructureRepository,
)
from exulanica.world.interaction import InteractionProposal

from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres


def fixture_policies(repository) -> WorldInteractionPolicyRepository:
    """The interaction policy of the registered fixture world the structural candidates name."""
    world_id = registered_world(repository.connection, repository.workspace_id)
    return WorldInteractionPolicyRepository(
        repository.connection, repository.workspace_id, world_id=world_id
    )


def proposal(
    policies: WorldInteractionPolicyRepository,
    patch,
    *,
    origin=ProposalOrigin.SETTINGS,
    proposal_id=None,
    refines=None,
    invalid_base=False,
):
    state = policies.state()
    companion = origin is ProposalOrigin.COMPANION
    return InteractionProposal(
        proposal_id or uuid.uuid4(),
        ProposalProvenance(
            origin,
            uuid.uuid4(),
            None if origin is ProposalOrigin.USER else "turn:17" if companion else "options-panel",
        ),
        patch,
        uuid.uuid4()
        if invalid_base
        else None
        if state.current is None
        else state.current.version_id,
        state.base_structure_snapshot_id,
        state.base_topology_sha256,
        {"source": "accepted-choice", "control": sorted(patch)[0]},
        "This changes one reviewed interaction capability and no world structure.",
        ("turn:17",) if companion else ("options-panel",),
        "qwen/qwen3.5-122b-a10b" if companion else None,
        "interaction-suggestion-v1" if companion else None,
        refines,
    )


def apply_patch(policies, patch, *, origin=ProposalOrigin.SETTINGS):
    created = policies.preview(proposal(policies, patch, origin=origin))
    return policies.apply(
        created.preview_id,
        base_policy_version_id=created.proposal.base_policy_version_id,
        base_structure_snapshot_id=created.proposal.base_structure_snapshot_id,
        base_topology_sha256=created.proposal.base_topology_sha256,
        applied_by=uuid.uuid4(),
    )


def test_migration_registry_and_runtime_registry_are_exact(repository):
    rows = repository.connection.execute(
        "select capability_key,capability_version,category,value_kind,minimum_value,"
        "maximum_value,choice_values,default_value from interaction_capability_registry "
        "order by capability_key"
    ).fetchall()
    assert {row["capability_key"] for row in rows} == set(INTERACTION_POLICY_REGISTRY.capabilities)
    for row in rows:
        capability = INTERACTION_POLICY_REGISTRY.capabilities[row["capability_key"]]
        assert row["capability_version"] == capability.version
        assert row["category"] == capability.category
        assert row["value_kind"] == capability.kind
        assert row["default_value"] == capability.default
        assert tuple(row["choice_values"] or ()) == capability.choices


def test_same_candidate_is_deterministic_discard_is_neutral_and_apply_is_immutable(repository):
    policies = fixture_policies(repository)
    before = policies.state()
    assert before.current is None
    first = policies.preview(proposal(policies, {"comfort.vignette": "strong"}))
    second = policies.preview(proposal(policies, {"comfort.vignette": "strong"}))
    assert first.candidate_parameters == second.candidate_parameters
    assert first.candidate_sha256 == second.candidate_sha256

    policies.discard(first.preview_id, discarded_by=uuid.uuid4())
    assert policies.state() == before
    applied = policies.apply(
        second.preview_id,
        base_policy_version_id=None,
        base_structure_snapshot_id=None,
        base_topology_sha256=None,
        applied_by=uuid.uuid4(),
    )
    assert applied.revision == 0
    assert policies.state().parameters["comfort.vignette"] == "strong"
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_interaction_policy_version set revision=99 where version_id=%s",
            (applied.version_id,),
        )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_interaction_policy_proposal set status='previewed' "
            "where proposal_id=%s",
            (applied.applied_from_proposal_id,),
        )


def test_settings_and_companion_share_lifecycle_with_model_refinement_and_rejection_audit(
    repository,
):
    policies = fixture_policies(repository)
    settings = apply_patch(policies, {"navigation.turn-mode": "snap"})
    companion_proposal = proposal(
        policies,
        {"initiative.mode": "minimal"},
        origin=ProposalOrigin.COMPANION,
        refines=settings.applied_from_proposal_id,
    )
    preview = policies.preview(companion_proposal)
    companion = policies.apply(
        preview.preview_id,
        base_policy_version_id=settings.version_id,
        base_structure_snapshot_id=None,
        base_topology_sha256=None,
        applied_by=uuid.uuid4(),
    )
    assert companion.provenance.origin is ProposalOrigin.COMPANION
    row = repository.connection.execute(
        "select model_id,prompt_version,reference_ids,refines_proposal_id,status "
        "from world_interaction_policy_proposal where proposal_id=%s",
        (companion_proposal.proposal_id,),
    ).fetchone()
    assert row["model_id"] == "qwen/qwen3.5-122b-a10b"
    assert row["prompt_version"] == "interaction-suggestion-v1"
    assert row["reference_ids"] == ["turn:17"]
    assert row["refines_proposal_id"] == settings.applied_from_proposal_id
    assert row["status"] == "applied"

    bad = proposal(policies, {"comfort.unknown": "unsafe"})
    with pytest.raises(InvalidInteractionData, match="unknown interaction capability"):
        policies.preview(bad)
    rejected = repository.connection.execute(
        "select status,validation_issues from world_interaction_policy_proposal "
        "where proposal_id=%s",
        (bad.proposal_id,),
    ).fetchone()
    assert rejected["status"] == "rejected"
    assert "unknown interaction capability" in rejected["validation_issues"][0]
    event_types = {
        row["event_type"]
        for row in repository.connection.execute(
            "select event_type from world_interaction_policy_audit_event"
        ).fetchall()
    }
    assert "proposal_refined" in event_types and "proposal_rejected" in event_types


def test_stale_policy_and_structural_bases_fail_without_touching_world_structure(repository):
    policies = fixture_policies(repository)
    first = policies.preview(proposal(policies, {"comfort.vignette": "strong"}))
    stale = policies.preview(proposal(policies, {"navigation.turn-mode": "snap"}))
    applied = policies.apply(
        first.preview_id,
        base_policy_version_id=None,
        base_structure_snapshot_id=None,
        base_topology_sha256=None,
        applied_by=uuid.uuid4(),
    )
    with pytest.raises(StaleInteractionPolicy):
        policies.apply(
            stale.preview_id,
            base_policy_version_id=None,
            base_structure_snapshot_id=None,
            base_topology_sha256=None,
            applied_by=uuid.uuid4(),
        )
    assert policies.state().current.version_id == applied.version_id

    structures = WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=policies.world_id
    )
    structure_preview = structures.preview(structural_candidate(), proposed_by=uuid.uuid4())
    structure = structures.apply(
        structure_preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=uuid.uuid4(),
    )
    interaction = policies.preview(proposal(policies, {"initiative.mode": "off"}))
    next_structure = structures.preview(
        structural_candidate(graph="graph-b"), proposed_by=uuid.uuid4()
    )
    structures.apply(
        next_structure.preview_id,
        base_snapshot_id=structure.snapshot_id,
        base_graph_sha256=structure.candidate.graph_sha256,
        base_reconstruction_sha256=structure.candidate.reconstruction_sha256,
        committed_by=uuid.uuid4(),
    )
    with pytest.raises(StaleInteractionPolicy):
        policies.apply(
            interaction.preview_id,
            base_policy_version_id=applied.version_id,
            base_structure_snapshot_id=structure.snapshot_id,
            base_topology_sha256=structure.digests.topology_sha256,
            applied_by=uuid.uuid4(),
        )
    current_structure = structures.current()
    before = current_structure.snapshot_id
    apply_patch(policies, {"disclosure.provenance-detail": "expanded"})
    assert structures.current().snapshot_id == before


def test_rollback_appends_and_recommendations_never_write(repository):
    policies = fixture_policies(repository)
    strong_one = apply_patch(policies, {"comfort.vignette": "strong"})
    off = apply_patch(policies, {"comfort.vignette": "off"})
    strong_two = apply_patch(policies, {"comfort.vignette": "strong"})
    assert strong_two.revision == 2
    state = policies.state()
    rolled_back = policies.rollback(
        off.version_id,
        base_policy_version_id=state.current.version_id,
        base_structure_snapshot_id=state.base_structure_snapshot_id,
        base_topology_sha256=state.base_topology_sha256,
        provenance=ProposalProvenance(ProposalOrigin.SETTINGS, uuid.uuid4(), "interaction-history"),
    )
    assert rolled_back.revision == 3
    assert rolled_back.rollback_target_version_id == off.version_id
    count_before = len(policies.versions())
    [recommendation] = policies.recommendations()
    assert recommendation.capability_key == "comfort.vignette"
    assert recommendation.proposed_value == "strong"
    assert recommendation.accepted_observation_count == 2
    assert len(policies.versions()) == count_before
    assert policies.state().parameters["comfort.vignette"] == "off"
    assert strong_one.policy_sha256 == strong_two.policy_sha256
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_interaction_policy_state set current_version_id=%s "
            "where workspace_id=%s and world_id=%s",
            (off.version_id, repository.workspace_id, policies.world_id),
        )


def test_private_conversation_content_cannot_enter_durable_policy_input(repository):
    policies = fixture_policies(repository)
    value = proposal(policies, {"comfort.vignette": "strong"})
    value = InteractionProposal(
        value.proposal_id,
        value.provenance,
        value.capability_patch,
        value.base_policy_version_id,
        value.base_structure_snapshot_id,
        value.base_topology_sha256,
        {"transcript": "private words"},
        value.explanation,
        value.reference_ids,
        value.model_id,
        value.prompt_version,
        value.refines_proposal_id,
    )
    with pytest.raises(InvalidInteractionData, match="conversation content is excluded"):
        policies.preview(value)
    assert (
        repository.connection.execute(
            "select count(*) as n from world_interaction_policy_proposal"
        ).fetchone()["n"]
        == 0
    )
