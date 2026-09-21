"""Plane-typed structure/style compatibility: pure decisions and PostgreSQL closed checks."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from exulanica.world import (
    CompatibilityIntent,
    ComposedTopologyRef,
    InvalidStyleData,
    ProtectedTopologyConflict,
    SourceAttachmentRef,
    StaleStyleVersion,
    StructuralSnapshotRef,
    StyleStructureFacts,
    StyleVersionRef,
    TopologyContract,
    TopologySourceSlot,
    UnknownWorldResource,
    WorldStyleRepository,
    classify_structure_style_compatibility,
    raise_for_incompatible_structure_style,
)
from exulanica.world.bootstrap import bootstrap_world
from exulanica.world.starter import create_starter_authorities

from test_saved_world_entries_api import _attachment_body, _create_starter, _reviewed_source
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from test_world_style_postgres import proposal, topology

FAMILY = "atlas-topology-v1"
STYLE = uuid.UUID("00000000-0000-0000-0000-000000000001")
LIVE_STYLE = uuid.UUID("00000000-0000-0000-0000-000000000002")
SNAPSHOT = uuid.UUID("00000000-0000-0000-0000-000000000003")
OTHER_SNAPSHOT = uuid.UUID("00000000-0000-0000-0000-000000000004")
COMPOSED = "a" * 64
STRUCTURAL = "b" * 64
COLLIDING = "c" * 64


def facts(**overrides) -> StyleStructureFacts:
    values = dict(
        intent=CompatibilityIntent.CLASSIFY,
        world_id="atlas:default",
        live_style_version_id=LIVE_STYLE,
        live_composed_digest=COMPOSED,
        live_composed_compatibility_key=FAMILY,
        named_style_version_id=LIVE_STYLE,
        named_style_is_current=True,
        named_style_bound_digest=COMPOSED,
        named_style_compatibility_key=FAMILY,
        named_composed_digest=COMPOSED,
    )
    values.update(overrides)
    return StyleStructureFacts(**values)


def bootstrappable_topology(digest, regions=("region-a",)):
    """A composed contract whose candidate has a region-owned unplaced element."""

    return topology(
        digest,
        sources=(
            TopologySourceSlot(
                uuid.uuid4(), "photo-slot", regions[0], None, "no evidence recorded"
            ),
        ),
        regions=regions,
    )


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def test_key_or_digest_equality_is_never_the_compatible_reason():
    family_only = classify_structure_style_compatibility(
        facts(
            named_style_version_id=STYLE,
            named_style_is_current=False,
            named_style_bound_digest="other-composed",
            named_composed_digest="other-composed",
            named_snapshot_id=SNAPSHOT,
            named_snapshot_topology_sha256=STRUCTURAL,
        )
    )
    assert family_only.outcome == "preview_required"
    assert family_only.token == "style_topology_drift"
    assert "profile_family" in family_only.planes_named

    collision = classify_structure_style_compatibility(
        facts(
            named_composed_digest=COLLIDING,
            named_snapshot_id=SNAPSHOT,
            named_snapshot_topology_sha256=COLLIDING,
            named_style_version_id=STYLE,
            named_style_is_current=False,
            named_style_bound_digest=COLLIDING,
        )
    )
    assert collision == classify_structure_style_compatibility(
        facts(
            named_composed_digest=COLLIDING,
            named_snapshot_id=SNAPSHOT,
            named_snapshot_topology_sha256=COLLIDING,
            named_style_version_id=STYLE,
            named_style_is_current=False,
            named_style_bound_digest=COLLIDING,
        )
    )
    assert collision.outcome == "refuse"
    assert collision.token == "cross_plane_digest_equality"
    assert "composed_topology" in collision.planes_named
    assert "structural_snapshot" in collision.planes_named

    starter_same_hex = classify_structure_style_compatibility(
        facts(
            world_id="world:authored:example",
            live_composed_digest=COLLIDING,
            named_composed_digest=COLLIDING,
            named_style_bound_digest=COLLIDING,
            named_snapshot_id=SNAPSHOT,
            named_snapshot_topology_sha256=COLLIDING,
            authored_source_snapshot_id=SNAPSHOT,
        )
    )
    assert starter_same_hex.outcome == "compatible"
    assert starter_same_hex.token == "live_authorities_agree"


def test_unknown_style_write_base_is_unknown_reference():
    unknown = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.APPEARANCE_WRITE,
            named_style_version_id=STYLE,
            named_style_known=False,
            named_style_is_current=False,
        )
    )
    assert unknown.outcome == "refuse"
    assert unknown.token == "unknown_reference"
    with pytest.raises(UnknownWorldResource):
        raise_for_incompatible_structure_style(unknown)


def test_first_register_family_mismatch_is_profile_family_incompatible():
    decision = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.REGISTER_TOPOLOGY,
            live_style_version_id=None,
            live_composed_digest=None,
            live_composed_compatibility_key=None,
            named_style_version_id=None,
            named_style_compatibility_key=FAMILY,
            named_composed_digest=None,
            proposed_digest="first-mismatch",
            proposed_compatibility_key="other-family",
        )
    )
    assert decision.outcome == "refuse"
    assert decision.token == "profile_family_incompatible"
    with pytest.raises(ProtectedTopologyConflict, match="profile family incompatible"):
        raise_for_incompatible_structure_style(decision)


def test_historical_style_write_and_topology_bases_refuse():
    write = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.APPEARANCE_WRITE,
            named_style_version_id=STYLE,
            named_style_is_current=False,
        )
    )
    assert write.outcome == "refuse"
    assert write.token == "historical_style_write_base"
    with pytest.raises(StaleStyleVersion, match="historical style is not a write base"):
        raise_for_incompatible_structure_style(write)

    topology_base = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.APPEARANCE_WRITE,
            named_composed_digest="style-bound-historical",
            named_style_bound_digest="style-bound-historical",
        )
    )
    assert topology_base.outcome == "refuse"
    assert topology_base.token == "historical_style_topology_apply_base"
    with pytest.raises(ProtectedTopologyConflict, match="historical style topology apply base"):
        raise_for_incompatible_structure_style(topology_base)


def test_bootstrap_names_typed_planes_even_when_hexes_collide():
    decision = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.BOOTSTRAP,
            named_composed_digest=COLLIDING,
            live_composed_digest=COLLIDING,
            named_snapshot_id=SNAPSHOT,
            named_snapshot_topology_sha256=COLLIDING,
        )
    )
    assert decision.outcome == "compatible"
    assert decision.token == "bootstrap_reuse"


def test_register_topology_family_match_is_composer_handoff():
    decision = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.REGISTER_TOPOLOGY,
            proposed_digest="family-matched-successor",
            proposed_compatibility_key=FAMILY,
        )
    )
    assert decision.outcome == "compatible"
    assert decision.token == "register_topology"


def test_non_authored_world_id_with_sourced_slots_is_not_starter_refuse():
    sourced = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.REGISTER_TOPOLOGY,
            world_id="atlas:default",
            proposed_digest="sourced-handoff",
            proposed_compatibility_key=FAMILY,
            proposed_has_sourced_slots=True,
        )
    )
    assert sourced.outcome == "compatible"
    assert sourced.token == "register_topology"

    prefix_without_origin = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.REGISTER_TOPOLOGY,
            world_id="world:authored:example",
            starter_world=False,
            proposed_digest="sourced-handoff",
            proposed_compatibility_key=FAMILY,
            proposed_has_sourced_slots=True,
        )
    )
    assert prefix_without_origin.outcome == "compatible"
    assert prefix_without_origin.token == "register_topology"


def test_attachments_cannot_enter_compose_and_expired_members_refuse():
    compose = classify_structure_style_compatibility(
        facts(intent=CompatibilityIntent.COMPOSE, attachments_named=True)
    )
    assert compose.outcome == "refuse"
    assert compose.token == "attachment_is_not_composition"

    expired = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.COMPOSE,
            attachments_named=True,
            attachments_expired=True,
        )
    )
    assert expired.outcome == "refuse"
    assert expired.token == "expired_source_not_composable"

    attach = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.ATTACH,
            named_style_version_id=STYLE,
            named_style_is_current=False,
            named_snapshot_id=SNAPSHOT,
            authored_source_snapshot_id=SNAPSHOT,
            attachments_named=True,
        )
    )
    assert attach.outcome == "compatible"
    assert attach.token == "attachment_membership_only"


def test_starter_sourced_activation_and_unknown_snapshot_refuse():
    sourced = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.REGISTER_TOPOLOGY,
            world_id="world:authored:00000000-0000-0000-0000-000000000099",
            proposed_digest="sourced-overlay",
            proposed_compatibility_key=FAMILY,
            proposed_has_sourced_slots=True,
        )
    )
    assert sourced.outcome == "refuse"
    assert sourced.token == "starter_sourced_activation"

    overlay = classify_structure_style_compatibility(
        facts(
            intent=CompatibilityIntent.REGISTER_TOPOLOGY,
            world_id="world:authored:00000000-0000-0000-0000-000000000099",
            proposed_digest="different-starter-digest",
            proposed_compatibility_key=FAMILY,
        )
    )
    assert overlay.outcome == "refuse"
    assert overlay.token == "starter_overlay"

    unknown = classify_structure_style_compatibility(
        facts(named_snapshot_id=OTHER_SNAPSHOT, named_snapshot_known=False)
    )
    assert unknown.outcome == "refuse"
    assert unknown.token == "unknown_reference"


@pytest.mark.postgres
def test_colliding_hex_across_planes_does_not_unify(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(bootstrappable_topology("composed-live"))
    opened = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        base_topology_digest="composed-live",
    )
    snapshot = repository.connection.execute(
        "select snapshot_id,topology_sha256 from world_structure_snapshot "
        "where workspace_id=%s and snapshot_id=%s",
        (repository.workspace_id, uuid.UUID(opened["snapshot_id"])),
    ).fetchone()
    assert snapshot["topology_sha256"] != "composed-live"
    decision = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.CLASSIFY,
        style=StyleVersionRef(styles.current().version_id),
        composed=ComposedTopologyRef(snapshot["topology_sha256"]),
        snapshot=StructuralSnapshotRef(snapshot["snapshot_id"]),
    )
    assert decision.outcome == "refuse"
    assert decision.token == "cross_plane_digest_equality"


@pytest.mark.postgres
def test_starter_overlay_and_sourced_activation_refuse(repository):
    actor = uuid.uuid4()
    world_id = f"world:authored:{uuid.uuid4()}"
    with repository.connection.transaction():
        create_starter_authorities(
            repository.connection,
            workspace_id=repository.workspace_id,
            actor=actor,
            title="Starter",
            world_id=world_id,
        )
    styles = WorldStyleRepository(repository.connection, repository.workspace_id, world_id=world_id)
    live = styles.current_topology_digest()
    sourced = TopologyContract(
        "sourced-overlay",
        ("region:starter",),
        (
            TopologySourceSlot(
                uuid.uuid4(), "photo-slot", "region:starter", None, "no evidence recorded"
            ),
        ),
        world_id=world_id,
    )
    with pytest.raises(ProtectedTopologyConflict, match="starter sourced activation"):
        styles.register_topology(sourced)
    overlay = TopologyContract("plain-overlay", ("region:starter",), (), world_id=world_id)
    with pytest.raises(ProtectedTopologyConflict, match="starter overlay"):
        styles.register_topology(overlay)
    assert styles.current_topology_digest() == live
    assert (
        repository.connection.execute(
            "select count(*) as n from world_topology_contract "
            "where workspace_id=%s and world_id=%s and topology_digest=%s",
            (repository.workspace_id, world_id, "sourced-overlay"),
        ).fetchone()["n"]
        == 0
    )


@pytest.mark.postgres
def test_historical_style_write_refuses_and_rollback_uses_live_topology(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    initial = styles.register_topology(topology())
    preview = styles.preview(proposal(initial, parameters={"vitality": 0.4}))
    live = styles.apply(
        preview.preview_id,
        base_style_version_id=initial.version_id,
        base_topology_digest="topology-a",
        applied_by=uuid.uuid4(),
    )
    write = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.APPEARANCE_WRITE,
        style=StyleVersionRef(initial.version_id),
        composed=ComposedTopologyRef("topology-a"),
    )
    assert write.token == "historical_style_write_base"
    with pytest.raises(StaleStyleVersion, match="historical style is not a write base"):
        styles.preview(proposal(initial, parameters={"vitality": 0.5}))
    unknown = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.APPEARANCE_WRITE,
        style=StyleVersionRef(uuid.uuid4()),
        composed=ComposedTopologyRef("topology-a"),
    )
    assert unknown.token == "unknown_reference"
    with pytest.raises(UnknownWorldResource):
        styles.preview(replace(proposal(live), base_style_version_id=uuid.uuid4()))
    styles.register_topology(topology("topology-b"))
    topology_base = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.APPEARANCE_WRITE,
        style=StyleVersionRef(live.version_id),
        composed=ComposedTopologyRef("topology-a"),
    )
    assert topology_base.token == "historical_style_topology_apply_base"
    with pytest.raises(ProtectedTopologyConflict, match="historical style topology apply base"):
        styles.preview(proposal(live, topology_digest="topology-a", parameters={"vitality": 0.6}))
    open_preview = styles.preview(
        proposal(live, topology_digest="topology-b", parameters={"vitality": 0.7})
    )
    with pytest.raises(StaleStyleVersion, match="historical style is not a write base"):
        styles.apply(
            open_preview.preview_id,
            base_style_version_id=initial.version_id,
            base_topology_digest="topology-b",
            applied_by=uuid.uuid4(),
        )
    rolled = styles.rollback(
        initial.version_id,
        base_style_version_id=live.version_id,
        base_topology_digest="topology-b",
        provenance=preview.proposal.provenance,
    )
    assert rolled.topology_digest == "topology-b"
    assert rolled.rollback_target_version_id == initial.version_id
    assert styles.current().version_id == rolled.version_id


@pytest.mark.postgres
def test_unknown_style_write_base_stores_unknown_reference(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    live = styles.register_topology(topology())
    rejected = replace(proposal(live), base_style_version_id=uuid.uuid4())
    with pytest.raises(UnknownWorldResource):
        styles.preview(rejected)
    record = styles.proposal(rejected.proposal_id)
    assert record.status == "rejected"
    assert record.validation_issues == ("unknown_reference",)
    audit = repository.connection.execute(
        "select details from world_style_audit_event "
        "where workspace_id=%s and proposal_id=%s and event_type='proposal_rejected'",
        (repository.workspace_id, rejected.proposal_id),
    ).fetchone()
    assert audit is not None
    assert audit["details"]["error"] == "unknown_reference"


@pytest.mark.postgres
def test_unknown_and_cross_world_snapshot_is_unknown_reference(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(bootstrappable_topology("topology-a"))
    opened = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        base_topology_digest="topology-a",
    )
    missing = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.CLASSIFY,
        snapshot=StructuralSnapshotRef(uuid.uuid4()),
    )
    assert missing.outcome == "refuse"
    assert missing.token == "unknown_reference"
    with pytest.raises(UnknownWorldResource):
        styles._require_structure_style_compatibility(
            intent=CompatibilityIntent.CLASSIFY,
            snapshot=StructuralSnapshotRef(uuid.uuid4()),
        )
    other = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id="world:other"
    )
    foreign = other.classify_structure_style_compatibility(
        intent=CompatibilityIntent.CLASSIFY,
        snapshot=StructuralSnapshotRef(uuid.UUID(opened["snapshot_id"])),
    )
    assert foreign.outcome == "refuse"
    assert foreign.token == "unknown_reference"


@pytest.mark.postgres
def test_bootstrap_reuse_keeps_snapshot_regions_and_creates_no_contracts(
    repository,
):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(bootstrappable_topology("composed-live", regions=("region-a",)))
    first = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        base_topology_digest="composed-live",
    )
    assert first["regions"] == ["region-a"]
    styles.register_topology(
        bootstrappable_topology("composed-later", regions=("region-a", "region-extra"))
    )
    before = repository.connection.execute(
        "select count(*) as n from world_topology_contract where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["n"]
    reused = bootstrap_world(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        base_topology_digest="composed-later",
    )
    after = repository.connection.execute(
        "select count(*) as n from world_topology_contract where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["n"]
    assert reused["snapshot"] == "reused"
    assert reused["snapshot_id"] == first["snapshot_id"]
    assert reused["regions"] == ["region-a"]
    assert "region-extra" not in reused["regions"]
    assert after == before


@pytest.mark.postgres
def test_non_starter_sourced_register_is_composer_handoff(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(topology())
    sourced = TopologyContract(
        "sourced-handoff",
        ("region-a", "region-b"),
        (TopologySourceSlot(uuid.uuid4(), "photo-slot", "region-a", None, "no evidence recorded"),),
    )
    decision = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.REGISTER_TOPOLOGY,
        proposed=sourced,
    )
    assert decision.outcome == "compatible"
    assert decision.token == "register_topology"
    styles.register_topology(sourced)
    assert styles.current_topology_digest() == "sourced-handoff"


@pytest.mark.postgres
def test_register_topology_refuses_before_history_insert(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(topology())
    live = styles.current()
    mismatched = TopologyContract(
        "family-mismatch",
        ("region-a", "region-b"),
        compatibility_key="other-family",
    )
    decision = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.REGISTER_TOPOLOGY,
        style=StyleVersionRef(live.version_id),
        proposed=mismatched,
    )
    assert decision.token == "profile_family_incompatible"
    with pytest.raises(ProtectedTopologyConflict, match="profile family incompatible"):
        styles.register_topology(mismatched)
    assert styles.current_topology_digest() == live.topology_digest
    assert (
        repository.connection.execute(
            "select count(*) as n from world_topology_contract "
            "where workspace_id=%s and topology_digest=%s",
            (repository.workspace_id, "family-mismatch"),
        ).fetchone()["n"]
        == 0
    )


@pytest.mark.postgres
def test_first_register_family_mismatch_inserts_no_contract(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    mismatched = TopologyContract(
        "first-family-mismatch",
        ("region-a", "region-b"),
        compatibility_key="other-family",
    )
    decision = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.REGISTER_TOPOLOGY,
        proposed=mismatched,
    )
    assert decision.token == "profile_family_incompatible"
    with pytest.raises(ProtectedTopologyConflict, match="profile family incompatible"):
        styles.register_topology(mismatched)
    assert (
        repository.connection.execute(
            "select count(*) as n from world_topology_contract "
            "where workspace_id=%s and topology_digest=%s",
            (repository.workspace_id, "first-family-mismatch"),
        ).fetchone()["n"]
        == 0
    )
    assert (
        repository.connection.execute(
            "select count(*) as n from world_style_state where workspace_id=%s",
            (repository.workspace_id,),
        ).fetchone()["n"]
        == 0
    )


@pytest.mark.postgres
def test_attach_is_membership_only_and_compose_stays_latent(objects_api, repository):
    entry = _create_starter(objects_api)
    source = _reviewed_source(repository, objects_api)
    before_contracts = repository.connection.execute(
        "select count(*) as n from world_topology_contract where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["n"]
    before_styles = repository.connection.execute(
        "select current_style_version_id,current_topology_digest from world_style_state "
        "where workspace_id=%s and world_id=%s",
        (repository.workspace_id, entry["world_id"]),
    ).fetchone()
    attached = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments",
        _attachment_body(entry, source),
    )
    assert attached.status_code == 200, attached.text
    body = attached.json()
    assert body["source_snapshot_id"] == entry["source_snapshot_id"]
    assert body["style_version_id"] == entry["style_version_id"]
    assert body["authored_state_sha256"] == entry["authored_state_sha256"]
    assert body["revision"] == entry["revision"] + 1
    after_contracts = repository.connection.execute(
        "select count(*) as n from world_topology_contract where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["n"]
    after_styles = repository.connection.execute(
        "select current_style_version_id,current_topology_digest from world_style_state "
        "where workspace_id=%s and world_id=%s",
        (repository.workspace_id, entry["world_id"]),
    ).fetchone()
    assert after_contracts == before_contracts
    assert after_styles == before_styles

    expired = _reviewed_source(repository, objects_api, expired=True, minute=1)
    refused = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments",
        _attachment_body(body, expired),
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "invalid_source_attachment"
    # Admission refuses expired sources before membership is written. That is not a
    # stored-member COMPOSE pin.
    reread = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert reread["source_attachments"] == body["source_attachments"]
    assert reread["revision"] == body["revision"]

    attachment_id = uuid.UUID(body["source_attachments"][0]["attachment_id"])
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=entry["world_id"]
    )
    compose = styles.classify_structure_style_compatibility(
        intent=CompatibilityIntent.COMPOSE,
        attachments=(SourceAttachmentRef(attachment_id),),
    )
    assert compose.outcome == "refuse"
    assert compose.token == "attachment_is_not_composition"


@pytest.mark.postgres
def test_dual_source_addresses_still_refuse_through_the_classifier(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(topology())
    with pytest.raises(InvalidStyleData, match="conflicting plane addresses"):
        styles.source_media(
            store=None,  # type: ignore[arg-type]
            topology_digest="topology-a",
            source_snapshot_id=uuid.uuid4(),
        )
