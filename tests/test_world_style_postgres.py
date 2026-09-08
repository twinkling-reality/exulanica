"""Transactional world-style behavior against the schema that carries the guarantees."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.ingest.person_review import record_region_edits
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    STYLE_REGISTRY,
    InvalidPreviewState,
    InvalidStyleData,
    ProposalOrigin,
    ProposalProvenance,
    ProtectedTopologyConflict,
    SourceMediaState,
    StaleStyleVersion,
    StyleProposal,
    StyleReference,
    StyleScope,
    TopologyContract,
    TopologySourceSlot,
    UnavailableAsset,
    WorldStyleRepository,
)

from conftest import write_photo

pytestmark = pytest.mark.postgres


def topology(digest="topology-a", *, sources=(), regions=("region-a", "region-b")):
    return TopologyContract(digest, tuple(regions), tuple(sources))


def proposal(
    current,
    *,
    topology_digest="topology-a",
    proposal_id=None,
    origin=ProposalOrigin.USER,
    origin_reference=None,
    scope=None,
    parameters=None,
    reference_ids=None,
    model_id=None,
    prompt_version=None,
    refines_proposal_id=None,
):
    if origin is ProposalOrigin.COMPANION:
        if reference_ids is None:
            reference_ids = ("design-reference:test",)
        if model_id is None:
            model_id = "test-style-proposer/v1"
        if prompt_version is None:
            prompt_version = "test-style-prompt/v1"
    return StyleProposal(
        proposal_id=proposal_id or uuid.uuid4(),
        provenance=ProposalProvenance(origin, uuid.uuid4(), origin_reference),
        scope=scope or StyleScope("global"),
        base_style_version_id=current.version_id,
        base_topology_digest=topology_digest,
        profile=StyleReference("origin-landscape", 1, parameters or {"vitality": 0.25}),
        reference_ids=tuple(reference_ids or ()),
        model_id=model_id,
        prompt_version=prompt_version,
        refines_proposal_id=refines_proposal_id,
    )


def test_migration_registry_matches_the_validated_runtime_registry(repository):
    capabilities = {
        row["capability_key"]
        for row in repository.connection.execute(
            "select capability_key from world_style_capability_registry"
        ).fetchall()
    }
    profiles = {
        (row["profile_id"], row["profile_version"])
        for row in repository.connection.execute(
            "select profile_id,profile_version from world_art_profile_registry"
        ).fetchall()
    }
    assert capabilities == set(STYLE_REGISTRY.capabilities)
    assert profiles == set(STYLE_REGISTRY.profiles)
    modules = {
        row["module_id"]: {
            value["capability_key"]
            for value in repository.connection.execute(
                "select capability_key from world_style_module_capability where module_id=%s",
                (row["module_id"],),
            ).fetchall()
        }
        for row in repository.connection.execute(
            "select module_id from world_style_module_registry"
        ).fetchall()
    }
    assert modules == {
        key: set(value.capabilities) for key, value in STYLE_REGISTRY.modules.items()
    }


def test_new_rows_cannot_opt_out_through_the_historical_provenance_version(repository):
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="recipe provenance"):
        repository.connection.execute(
            "insert into world_style_proposal "
            "(proposal_id,workspace_id,world_id,origin,actor,scope_kind,"
            "base_style_version_id,base_topology_digest,profile_id,profile_version,parameters,"
            "status,provenance_schema_version) "
            "values (%s,%s,'atlas:default','user',%s,'global',%s,'topology-a',"
            "'origin-landscape',1,'{}','rejected',0)",
            (
                uuid.uuid4(),
                repository.workspace_id,
                uuid.uuid4(),
                uuid.uuid4(),
            ),
        )


def test_preview_isolation_atomic_apply_discard_and_immutable_rollback(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    initial = styles.register_topology(topology())

    discarded = styles.preview(proposal(initial, parameters={"vitality": 0.15}))
    assert styles.current() == initial
    styles.discard(discarded.preview_id, discarded_by=uuid.uuid4())
    assert styles.current() == initial

    preview = styles.preview(
        proposal(
            initial,
            scope=StyleScope("region", "region-a"),
            parameters={"vitality": 0.35},
        )
    )
    assert styles.current().region_styles == {}
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_style_preview set candidate='{}' where preview_id=%s",
            (preview.preview_id,),
        )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_style_proposal set actor=%s where proposal_id=%s",
            (uuid.uuid4(), preview.proposal.proposal_id),
        )
    applied = styles.apply(
        preview.preview_id,
        base_style_version_id=initial.version_id,
        base_topology_digest="topology-a",
        applied_by=uuid.uuid4(),
    )
    assert applied.revision == 1
    assert applied.parent_version_id == initial.version_id
    assert applied.region_styles["region-a"].parameters["vitality"] == 0.35
    with pytest.raises(InvalidPreviewState):
        styles.apply(
            preview.preview_id,
            base_style_version_id=applied.version_id,
            base_topology_digest="topology-a",
            applied_by=uuid.uuid4(),
        )

    rolled_back = styles.rollback(
        initial.version_id,
        base_style_version_id=applied.version_id,
        base_topology_digest="topology-a",
        provenance=ProposalProvenance(ProposalOrigin.USER, uuid.uuid4()),
    )
    assert rolled_back.revision == 2
    assert rolled_back.parent_version_id == applied.version_id
    assert rolled_back.rollback_target_version_id == initial.version_id
    assert rolled_back.region_styles == {}
    assert [version.revision for version in styles.versions()] == [0, 1, 2]

    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        repository.connection.execute(
            "update world_style_version set revision=99 where version_id=%s",
            (initial.version_id,),
        )


def test_two_previews_cannot_both_apply_from_one_base_version(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    initial = styles.register_topology(topology())
    first = styles.preview(proposal(initial, parameters={"vitality": 0.2}))
    second = styles.preview(proposal(initial, parameters={"vitality": 0.4}))

    applied = styles.apply(
        first.preview_id,
        base_style_version_id=initial.version_id,
        base_topology_digest="topology-a",
        applied_by=uuid.uuid4(),
    )
    with pytest.raises(StaleStyleVersion):
        styles.apply(
            second.preview_id,
            base_style_version_id=initial.version_id,
            base_topology_digest="topology-a",
            applied_by=uuid.uuid4(),
        )
    assert styles.current().version_id == applied.version_id
    assert (
        repository.connection.execute(
            "select status from world_style_preview where preview_id=%s", (second.preview_id,)
        ).fetchone()["status"]
        == "stale"
    )


def test_a_topology_change_invalidates_but_does_not_mutate_an_open_preview(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    initial = styles.register_topology(topology())
    preview = styles.preview(proposal(initial))
    styles.register_topology(topology("topology-b"))

    with pytest.raises(ProtectedTopologyConflict):
        styles.apply(
            preview.preview_id,
            base_style_version_id=initial.version_id,
            base_topology_digest="topology-a",
            applied_by=uuid.uuid4(),
        )
    assert styles.current().version_id == initial.version_id
    assert styles.current_topology_digest() == "topology-b"


def test_a_new_topology_drops_removed_region_overrides_before_the_next_apply(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    initial = styles.register_topology(topology())
    preview = styles.preview(
        proposal(initial, scope=StyleScope("region", "region-b"), parameters={"vitality": 0.3})
    )
    applied = styles.apply(
        preview.preview_id,
        base_style_version_id=initial.version_id,
        base_topology_digest="topology-a",
        applied_by=uuid.uuid4(),
    )

    styles.register_topology(topology("topology-b", regions=("region-a",)))
    current = styles.current()
    assert current.region_styles == {}
    assert any("region-b" in warning for warning in current.warnings)

    next_preview = styles.preview(proposal(applied, topology_digest="topology-b"))
    reapplied = styles.apply(
        next_preview.preview_id,
        base_style_version_id=applied.version_id,
        base_topology_digest="topology-b",
        applied_by=uuid.uuid4(),
    )
    assert reapplied.region_styles == {}


def test_user_settings_and_companion_proposals_keep_distinct_audit_provenance(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    initial = styles.register_topology(topology())
    for origin, reference in (
        (ProposalOrigin.USER, None),
        (ProposalOrigin.SETTINGS, "appearance-panel"),
        (ProposalOrigin.COMPANION, "turn:17"),
    ):
        preview = styles.preview(proposal(initial, origin=origin, origin_reference=reference))
        styles.discard(preview.preview_id, discarded_by=uuid.uuid4())

    rows = repository.connection.execute(
        "select event_type,origin,origin_reference from world_style_audit_event "
        "order by occurred_at,event_id"
    ).fetchall()
    assert {row["origin"] for row in rows} == {"user", "settings", "companion"}
    assert {row["origin_reference"] for row in rows if row["origin"] != "user"} == {
        "appearance-panel",
        "turn:17",
    }


def test_companion_recipe_refinement_persists_only_inert_binding_and_provenance(repository):
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    initial = styles.register_topology(topology())
    with pytest.raises(InvalidStyleData, match="require model"):
        styles.preview(
            proposal(
                initial,
                origin=ProposalOrigin.COMPANION,
                origin_reference="conversation:1",
                model_id="",
                prompt_version="",
                reference_ids=(),
            )
        )

    draft = styles.preview(
        proposal(
            initial,
            origin=ProposalOrigin.COMPANION,
            origin_reference="conversation:2",
        )
    )
    refined = styles.preview(
        proposal(
            initial,
            origin=ProposalOrigin.COMPANION,
            origin_reference="conversation:3",
            parameters={"surface-finish": "clear-lens", "world-tempo": 1.2},
            refines_proposal_id=draft.proposal.proposal_id,
        )
    )
    record = styles.proposal(refined.proposal.proposal_id)
    assert record.status == "previewed"
    assert record.proposal.refines_proposal_id == draft.proposal.proposal_id
    assert record.proposal.model_id == "test-style-proposer/v1"
    assert record.recipe_binding["modules"] == [
        "aeroheart-optics-v1",
        "registered-surface-v1",
        "bounded-tempo-v1",
    ]
    assert record.capability_mapping["surface-finish"] == "surface.finish"
    serialized = str(record.recipe_binding).lower()
    for forbidden in ("css", "javascript", "shader", "markup", "https://", "layout"):
        assert forbidden not in serialized


def test_missing_source_evidence_is_a_state_and_requiring_it_is_an_asset_error(
    repository, tmp_path
):
    source_id = uuid.uuid4()
    source = TopologySourceSlot(
        source_id=source_id,
        region_id="region-a",
        slot_key="hero-memory",
        evidence_span_id=None,
        missing_reason="no source was recorded for this region",
    )
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(topology(sources=(source,)))
    store = LocalContentAddressedStore(tmp_path / "blobs")

    [metadata] = styles.source_media(store)
    assert metadata.state is SourceMediaState.MISSING_EVIDENCE
    assert metadata.capture_ids == ()
    assert metadata.evidence_path is None
    with pytest.raises(UnavailableAsset):
        styles.require_source_media(source_id, store)


def test_available_source_metadata_comes_only_from_authorised_local_evidence(
    repository, tmp_path, photo_dir
):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "source.jpg")
    )
    assert outcome.error is None
    span_id = repository.connection.execute(
        "select span_id from evidence_span where workspace_id=%s order by created_at limit 1",
        (repository.workspace_id,),
    ).fetchone()["span_id"]
    source_id = uuid.uuid4()
    source = TopologySourceSlot(
        source_id=source_id,
        region_id="region-a",
        slot_key="hero-memory",
        evidence_span_id=span_id,
        missing_reason=None,
    )
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(topology(sources=(source,)))

    metadata = styles.require_source_media(source_id, store)
    assert metadata.state is SourceMediaState.AVAILABLE
    assert metadata.evidence_path == f"/evidence/{span_id}"
    assert metadata.media_type == "image/jpeg"
    assert metadata.width == 160 and metadata.height == 100
    assert "http" not in metadata.evidence_path

    capture_id = repository.connection.execute(
        "select capture_id from capture where workspace_id=%s and deleted_at is null limit 1",
        (repository.workspace_id,),
    ).fetchone()["capture_id"]
    assert metadata.capture_ids == (capture_id,)
    record_region_edits(
        repository, capture_id=capture_id, actor=uuid.uuid4(),
        edits=[{"region_key": "aa" * 32, "action": "add", "shape": "box",
                "silhouette": {"kind": "polygon", "points": [
                    [100000, 100000], [400000, 100000], [400000, 800000], [100000, 800000],
                ]}}],
    )
    [pending] = styles.source_media(store)
    assert pending.state is SourceMediaState.UNAVAILABLE_ASSET
    assert pending.capture_ids == (capture_id,)
    assert pending.evidence_path is None
    with pytest.raises(UnavailableAsset):
        styles.require_source_media(source_id, store)
    repository.insert_tombstone(
        scope="capture",
        capture_id=capture_id,
        requested_by=uuid.uuid4(),
        reason="the user deleted this source",
    )
    [deleted] = styles.source_media(store)
    assert deleted.state is SourceMediaState.UNAVAILABLE_ASSET
    assert deleted.reason == "source evidence was deleted"
    assert deleted.evidence_path is None
    assert deleted.capture_ids == ()
