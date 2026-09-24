"""Two personal-source worlds in one account stay fully separate.

The shipped policy allows one personal-source world per workspace. This file raises it to two
inside each test, which is all a later release has to do, creates two worlds with minted ids in
one workspace, gives each its own structure and version, and then writes into one and reads
through the other: objects, appearance, character appearance, interaction settings, the evidence
the Companion may cite, World Read regions, package export, the society and the routes. Nothing
written into one world is visible, addressable or exported through the other, and code that
means "the personal-source world" refuses to pick one of two.

Neither id is the legacy ``atlas:default``, so nothing here passes because of that value.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.graph.world_read import world_read_bundle
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.selection.proposal import source_catalogue
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    AuthoredObject,
    ObjectOrigin,
    ProposalOrigin,
    ProposalProvenance,
    SavedWorldEntryRepository,
    SourceAttachmentSelection,
    StyleProposal,
    StyleReference,
    StyleScope,
    Transform,
    UnknownWorldResource,
    WorldObjectRepository,
    WorldStructureRepository,
    WorldStyleRepository,
    seed_reviewed_assets,
)
from exulanica.world import worlds as world_registry
from exulanica.world.character_appearance import CharacterSubject
from exulanica.world.character_appearance_repository import CharacterAppearanceRepository
from exulanica.world.interaction_repository import WorldInteractionPolicyRepository
from exulanica.world.society import UnknownSociety
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.worlds import (
    PERSONAL_SOURCE,
    SeveralPersonalSourceWorlds,
    WorldLimitReached,
    ensure_personal_source_world,
    new_world_id,
    register_world,
    resolve_personal_source_world,
    workspace_worlds,
)
from exulanica.world_package import authored, project_world_package

from character_appearance_fixtures import family, recipe
from conftest import write_photo
from test_api import deployment as deployment
from test_interaction_policy_postgres import apply_patch
from test_saved_world_entries_api import _reviewed_source
from test_world_read_bundle import _published_scene
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres

#: A reviewed CC0 marker every store seeded by ``seed_reviewed_assets`` holds.
CUBE = "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9"


@dataclass(frozen=True)
class World:
    world_id: str
    objects: WorldObjectRepository
    styles: WorldStyleRepository
    snapshot_id: uuid.UUID
    version_id: uuid.UUID


@dataclass(frozen=True)
class TwoWorlds:
    connection: object
    workspace_id: uuid.UUID
    actor: uuid.UUID
    span_id: uuid.UUID
    store: LocalContentAddressedStore
    first: World
    second: World


def _policy_allowing(limit: int) -> world_registry.WorldCountPolicy:
    """The shipped policy with more personal-source worlds allowed, as its next version would be."""
    shipped = world_registry.WORLD_COUNT_POLICY
    return dataclasses.replace(
        shipped,
        version=shipped.version + 1,
        limits=MappingProxyType({**shipped.limits, PERSONAL_SOURCE: limit}),
    )


def _apply(structures: WorldStructureRepository, candidate, actor: uuid.UUID):
    preview = structures.preview(candidate, proposed_by=actor)
    return structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )


@pytest.fixture
def two_worlds(repository, tmp_path, photo_dir, monkeypatch) -> TwoWorlds:
    monkeypatch.setattr(world_registry, "WORLD_COUNT_POLICY", _policy_allowing(2))
    connection, workspace = repository.connection, repository.workspace_id
    actor = uuid.uuid4()
    store = LocalContentAddressedStore(tmp_path / "store")
    seed_reviewed_assets(store)
    outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "shared-source.jpg")
    )
    assert outcome.error is None, outcome.error
    span_id = connection.execute(
        "select span_id from evidence_span where workspace_id=%s order by span_id limit 1",
        (workspace,),
    ).fetchone()["span_id"]

    made = []
    for index in range(2):
        world_id = register_world(
            connection,
            workspace,
            world_id=new_world_id(PERSONAL_SOURCE),
            kind=PERSONAL_SOURCE,
            created_by=actor,
            reason="two-world isolation",
        ).world_id
        # Only the first world binds the photograph to a region, so an evidence reference in
        # the second can only have come from the first.
        snapshot = _apply(
            WorldStructureRepository(connection, workspace, world_id=world_id),
            structural_candidate(
                world_id=world_id,
                graph=f"graph-{index}",
                evidence_span_id=span_id if index == 0 else None,
            ),
            actor,
        )
        objects = WorldObjectRepository(connection, workspace, world_id=world_id, store=store)
        version = objects.create_version(
            source_snapshot_id=snapshot.snapshot_id, title=f"World {index}", created_by=actor
        )
        made.append(
            World(
                world_id=world_id,
                objects=objects,
                styles=WorldStyleRepository(connection, workspace, world_id=world_id),
                snapshot_id=snapshot.snapshot_id,
                version_id=version.version_id,
            )
        )
    return TwoWorlds(connection, workspace, actor, span_id, store, made[0], made[1])


# -- which world is meant -----------------------------------------------------------------------


def test_both_worlds_are_listed_and_the_personal_source_world_is_never_guessed(two_worlds):
    listed = workspace_worlds(two_worlds.connection, two_worlds.workspace_id)
    assert [(w.world_id, w.kind) for w in listed] == [
        (two_worlds.first.world_id, PERSONAL_SOURCE),
        (two_worlds.second.world_id, PERSONAL_SOURCE),
    ]
    assert "atlas:default" not in {w.world_id for w in listed}
    with pytest.raises(SeveralPersonalSourceWorlds):
        resolve_personal_source_world(two_worlds.connection, two_worlds.workspace_id)
    # Composing personal sources needs "the" personal-source world, and with two it refuses
    # rather than composing into whichever it found first.
    with pytest.raises(SeveralPersonalSourceWorlds):
        ensure_personal_source_world(
            two_worlds.connection,
            two_worlds.workspace_id,
            created_by=two_worlds.actor,
            reason="compose",
        )
    with pytest.raises(WorldLimitReached):
        register_world(
            two_worlds.connection,
            two_worlds.workspace_id,
            world_id=new_world_id(PERSONAL_SOURCE),
            kind=PERSONAL_SOURCE,
            created_by=two_worlds.actor,
            reason="a third",
        )


# -- what one world holds, the other does not ----------------------------------------------------


def test_an_object_placed_in_one_world_is_not_in_the_other_and_its_version_is_unaddressable(
    two_worlds,
):
    first, second = two_worlds.first, two_worlds.second
    version = first.objects.version(first.version_id)
    placed = first.objects.add_object(
        first.version_id,
        AuthoredObject(
            object_id="object:only-in-the-first",
            asset_sha256=CUBE,
            region_id="region-a",
            transform=Transform(1_000, 0, 0, 0, 1_000),
            origin=ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=version.state_sha256,
        actor=two_worlds.actor,
    )
    assert [o.object_id for o in placed.objects] == ["object:only-in-the-first"]
    assert second.objects.version(second.version_id).objects == ()
    assert [v.version_id for v in second.objects.versions()] == [second.version_id]
    assert [v.version_id for v in first.objects.versions()] == [first.version_id]
    with pytest.raises(UnknownWorldResource):
        second.objects.version(first.version_id)
    with pytest.raises(UnknownWorldResource):
        second.objects.add_object(
            first.version_id,
            AuthoredObject(
                object_id="object:reaching-across",
                asset_sha256=CUBE,
                region_id="region-a",
                transform=Transform(0, 0, 0, 0, 1_000),
                origin=ObjectOrigin("authored", "fictional"),
            ),
            base_state_sha256=placed.state_sha256,
            actor=two_worlds.actor,
        )


def test_an_appearance_applied_in_one_world_leaves_the_other_s_as_it_was(two_worlds):
    first, second = two_worlds.first, two_worlds.second
    before = second.styles.current()
    current = first.styles.current()
    preview = first.styles.preview(
        StyleProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(ProposalOrigin.USER, two_worlds.actor),
            scope=StyleScope("global", None),
            base_style_version_id=current.version_id,
            base_topology_digest=first.styles.current_topology_digest(),
            profile=StyleReference("origin-landscape", 1, {"vitality": 0.25}),
        )
    )
    applied = first.styles.apply(
        preview.preview_id,
        base_style_version_id=current.version_id,
        base_topology_digest=first.styles.current_topology_digest(),
        applied_by=two_worlds.actor,
    )
    assert first.styles.current().version_id == applied.version_id
    assert second.styles.current() == before
    assert applied.version_id not in {v.version_id for v in second.styles.versions()}
    with pytest.raises(UnknownWorldResource):
        second.styles.proposal(preview.proposal.proposal_id)


def test_a_character_appearance_saved_in_one_world_is_not_read_in_the_other(two_worlds):
    subject = CharacterSubject(kind="avatar", subject_id=two_worlds.actor)

    def appearance(world: World) -> CharacterAppearanceRepository:
        return CharacterAppearanceRepository(
            two_worlds.connection,
            two_worlds.workspace_id,
            two_worlds.actor,
            families=(family(),),
            authorize_family=lambda definition: True,
            world_id=world.world_id,
        )

    first, second = appearance(two_worlds.first), appearance(two_worlds.second)
    saved = first.save(two_worlds.first.version_id, subject, recipe(), base_revision=0)
    assert saved["revision"] == 1
    assert second.read(two_worlds.second.version_id, subject) == {"revision": 0, "current": None}
    with pytest.raises(UnknownWorldResource):
        second.read(two_worlds.first.version_id, subject)


def test_interaction_settings_applied_in_one_world_leave_the_other_at_its_defaults(two_worlds):
    def policies(world: World) -> WorldInteractionPolicyRepository:
        return WorldInteractionPolicyRepository(
            two_worlds.connection, two_worlds.workspace_id, world_id=world.world_id
        )

    applied = apply_patch(policies(two_worlds.first), {"comfort.vignette": "strong"})
    assert policies(two_worlds.first).state().current.version_id == applied.version_id
    second = policies(two_worlds.second).state()
    assert second.current is None
    assert second.base_structure_snapshot_id == two_worlds.second.snapshot_id
    assert policies(two_worlds.second).versions() == ()


def test_the_companion_may_cite_only_the_evidence_the_named_world_binds(two_worlds, repository):
    """``POST /selection/appearance`` drafts against one world's evidence catalogue: the slots
    its topology binds, then the reviewed photographs attached to its own saved entry."""
    entries = SavedWorldEntryRepository(
        two_worlds.connection, two_worlds.workspace_id, two_worlds.store
    )
    attached = {}
    for minute, world in enumerate((two_worlds.first, two_worlds.second), start=1):
        entry = entries.create(
            world_id=world.world_id,
            title=f"World {minute}",
            authored_version_id=world.version_id,
            style_version_id=world.styles.current().version_id,
            created_by=two_worlds.actor,
        )
        source = _reviewed_source(
            repository,
            SimpleNamespace(store=two_worlds.store, actor=two_worlds.actor),
            minute=minute,
        )
        [attachment] = entries.attach_sources(
            entry.entry_id,
            operation_id=uuid.uuid4(),
            base_revision=entry.revision,
            authored_version_id=entry.authored_version_id,
            authored_state_sha256=entry.authored_state_sha256,
            authored_edit_seq=entry.authored_edit_seq,
            style_version_id=entry.style_version_id,
            sources=(
                SourceAttachmentSelection(
                    uuid.UUID(source["capture_id"]), uuid.UUID(source["evidence_span_id"])
                ),
            ),
            attached_by=two_worlds.actor,
        ).source_attachments
        attached[world.world_id] = attachment.attachment_id

    def cited(world: World) -> list:
        return [
            (choice.source_id, choice.evidence_span_id)
            for choice in source_catalogue(
                two_worlds.connection,
                two_worlds.workspace_id,
                world_id=world.world_id,
                store=two_worlds.store,
            )
        ]

    (_slot, slot_span), *first = cited(two_worlds.first)
    assert slot_span == two_worlds.span_id
    assert [source for source, _span in first] == [attached[two_worlds.first.world_id]]
    assert [source for source, _span in cited(two_worlds.second)] == [
        attached[two_worlds.second.world_id]
    ]


def test_a_package_of_one_world_exports_none_of_the_other(two_worlds, tmp_path):
    def export(world: World) -> dict:
        output = tmp_path / world.world_id.replace(":", "-")
        project_world_package(
            two_worlds.connection,
            workspace_id=two_worlds.workspace_id,
            actor=two_worlds.actor,
            output=output,
            private_key=Ed25519PrivateKey.generate(),
            world_id=world.world_id,
            extensions=(authored.EXTENSION_KEY,),
        )
        return json.loads((Path(output) / authored.VERSIONS_PATH).read_bytes())

    exported = {world.world_id: export(world) for world in (two_worlds.first, two_worlds.second)}
    # A package names versions by its own opaque ids, so each world's is told by its title.
    for world, title in ((two_worlds.first, "World 0"), (two_worlds.second, "World 1")):
        document = exported[world.world_id]
        assert [version["title"] for version in document["items"]] == [title]
        assert len(document["source_snapshots"]) == 1
    recorded = two_worlds.connection.execute(
        "select world_id from world_package_export where workspace_id=%s order by exported_at",
        (two_worlds.workspace_id,),
    ).fetchall()
    assert [row["world_id"] for row in recorded] == [
        two_worlds.first.world_id,
        two_worlds.second.world_id,
    ]


def test_world_read_places_a_scene_in_the_regions_of_the_world_it_names(
    repository, tmp_path, monkeypatch
):
    """The same photographs, bound to a region in one world and to none in the other."""
    monkeypatch.setattr(world_registry, "WORLD_COUNT_POLICY", _policy_allowing(2))
    store, captures, scene_id = _published_scene(repository, tmp_path, registered=3, spacing=5)
    connection, workspace, actor = repository.connection, repository.workspace_id, uuid.uuid4()
    capture_id = captures[0]
    span_id = connection.execute(
        "select s.span_id from evidence_span s join capture c on c.workspace_id=s.workspace_id "
        "and c.blob_sha256=s.blob_sha256 where c.capture_id=%s and s.modality='still_image' "
        "and s.track_key='img' and s.region is null",
        (capture_id,),
    ).fetchone()["span_id"]
    snapshots = {}
    for binds in (True, False):
        world_id = register_world(
            connection,
            workspace,
            world_id=new_world_id(PERSONAL_SOURCE),
            kind=PERSONAL_SOURCE,
            created_by=actor,
            reason="world read isolation",
        ).world_id
        snapshots[world_id] = _apply(
            WorldStructureRepository(connection, workspace, world_id=world_id),
            structural_candidate(
                world_id=world_id,
                graph=f"graph-{binds}",
                evidence_span_id=span_id if binds else None,
            ),
            actor,
        ).snapshot_id
    bound, unbound = snapshots

    graphs = {
        world_id: world_read_bundle(connection, workspace, scene_id, store, world_id=world_id)[
            "bundle"
        ]["region_graph"]
        for world_id in snapshots
    }
    for world_id, graph in graphs.items():
        assert (graph["state"], graph["world_id"]) == ("available", world_id)
        assert graph["snapshot_id"] == str(snapshots[world_id])
    holding = {
        world_id: [r["region_id"] for r in graph["regions"] if r["holds_this_scene"]]
        for world_id, graph in graphs.items()
    }
    assert holding == {bound: ["region-a"], unbound: []}
    [region_a] = [r for r in graphs[bound]["regions"] if r["region_id"] == "region-a"]
    assert region_a["member_capture_ids"] == [str(capture_id)]


def _society_in(two_worlds: TwoWorlds, world: World) -> dict:
    """A society that reads no input, living in ``world``'s version at a place of its own."""
    place = uuid.uuid4()
    two_worlds.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)", (two_worlds.workspace_id, place)
    )
    return SocietyRepository(
        two_worlds.connection, two_worlds.workspace_id, world_id=world.world_id
    ).create(
        world.version_id,
        place_id=place,
        region_id="region-a",
        seed="7a" * 32,
        actor=two_worlds.actor,
        profile="exulanica-society/v1",
    )


def test_a_society_lives_in_its_own_world_and_is_unknown_from_the_other(two_worlds):
    first, second = two_worlds.first, two_worlds.second
    created = _society_in(two_worlds, first)

    def repositories(world: World):
        scope = (two_worlds.connection, two_worlds.workspace_id)
        return (
            SocietyRepository(*scope, world_id=world.world_id),
            SocietyActionRepository(*scope, world_id=world.world_id),
            SocietyControlRepository(*scope, world_id=world.world_id),
        )

    societies, _actions, controls = repositories(first)
    assert societies.snapshot(first.version_id)["society_id"] == created["society_id"]
    assert str(controls.read(first.version_id)["society_id"]) == str(created["society_id"])
    # The other world holds the same workspace's version id nowhere, and its own version no society.
    for crossed in (
        lambda: repositories(second)[0].snapshot(first.version_id),
        lambda: repositories(second)[0].events(first.version_id),
        lambda: repositories(second)[1].history(first.version_id),
        lambda: repositories(second)[2].read(first.version_id),
        lambda: repositories(second)[0].snapshot(second.version_id),
    ):
        with pytest.raises(UnknownSociety):
            crossed()


# -- the routes answer for the world they name --------------------------------------------------


def test_every_route_reads_and_writes_only_the_world_it_names(two_worlds, deployment):
    first, second = two_worlds.first, two_worlds.second

    def get(path: str, world: World):
        return deployment.as_owner("GET", f"{path}?world_id={world.world_id}")

    listed = deployment.as_owner("GET", "/worlds").json()["worlds"]
    assert {w["world_id"] for w in listed} == {first.world_id, second.world_id}
    for world, other in ((first, second), (second, first)):
        versions = get("/world/versions", world)
        assert [v["version_id"] for v in versions.json()] == [str(world.version_id)]
        crossed = get(f"/world/versions/{other.version_id}", world)
        assert (crossed.status_code, crossed.json()["code"]) == (404, "unknown_reference")
        style = get("/world/styles/current", world).json()
        assert style["current"]["version_id"] == str(world.styles.current().version_id)
        interaction = get("/world/interactions/current", world).json()
        assert interaction["base_structure_snapshot_id"] == str(world.snapshot_id)

    # A society is read only in the world its version belongs to.
    _society_in(two_worlds, first)
    society = f"/world/versions/{first.version_id}/society"
    assert get(society, first).status_code == 200
    crossed = get(society, second)
    assert (crossed.status_code, crossed.json()["code"]) == (404, "unknown_reference")
