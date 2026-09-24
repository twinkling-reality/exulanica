"""Adding later reviewed photographs to a made world, on the person's confirmation.

``GET /worlds/personal-source`` offers ``add_photographs`` for a made and saved world whose newly
reviewed photographs have a place in it, with a preview of what adding them does, and writes
nothing. ``POST`` adds them only for exactly that preview: the next structural snapshot, the saved
world's version carried onto it, and the saved entry moved, in one transaction. The application
connects as provisioned runtime roles (``personal_world_support``); photographs go through the
intake the upload route runs and the grouping the scene worker runs.

The rule for which region a photograph is a slot of is pure, and the first tests hold it over the
groupings grouping was measured to leave: every earlier group stays live beside a later one.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.consent.regions import Silhouette
from exulanica.environment.repository import EnvironmentRepository
from exulanica.graph import personal_sources as personal_sources_module
from exulanica.graph.payload import SceneGroupRow
from exulanica.graph.personal_sources import personal_sources
from exulanica.ingest.model_rights import (
    LOCAL_PROCESS,
    ModelHandoff,
    ModelIdentity,
    grant_model_right,
    withdraw_model_right,
)
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages.segmentation import DEPTH_ROLE
from exulanica.reconstruction.testing import FlatDepthModel
from exulanica.world.composed import composed_candidate
from exulanica.world.edit_kinds import EditSubject
from exulanica.world.errors import InvalidStructuralData, StaleObjectBase
from exulanica.world.object_repository import CarryOutcome, StayReason, WorldObjectRepository
from exulanica.world.objects import ElementOverride
from exulanica.world.personal_composition import (
    _KIND_WORDS,
    _STAYS_BECAUSE,
    VERSION_TABLES,
    ComposedSource,
    LiveSceneGroup,
    MadeWorld,
    PersonalSources,
    ReviewedPhotograph,
    arrange,
    personal_composition_record,
)
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.reviewed_sources import ReviewedSource, reviewed_personal_sources
from exulanica.world.structure_repository import WorldStructureRepository

from personal_world_support import (
    CUBE,
    PATH,
    STRANGER_TOKEN,
    avatar_look,
    binding,
    compose,
    group,
    make_world,
    personal_world_api,
    photograph,
    place_object,
    region_appearance,
    source_media,
    world_appearance,
)
from world_package_rich_world import _admit_environment

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "personal-composition" / "single-run.json"
#: The reason a world's source slot gives when its personal photograph is no longer allowed.
LAPSED = "its personal authorization or human review is no longer current"


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from personal_world_api(tmp_path, repository, spine_schema)


# -- the rule, pure ----------------------------------------------------------------------------


def test_one_grouping_run_composes_exactly_as_it_did_before_places_were_connected(monkeypatch):
    """A never-made world's regions, order and digest, byte for byte, through the real reader."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    facts = golden["facts"]
    at = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.UTC)
    reviewed = tuple(
        ReviewedSource(
            capture_id=uuid.UUID(item["capture_id"]),
            evidence_span_id=uuid.UUID(item["evidence_span_id"]),
            source_sha256=bytes.fromhex(item["source_sha256"]),
            authorization_id=uuid.uuid5(uuid.NAMESPACE_URL, "authorization:" + item["capture_id"]),
            screening_id=uuid.uuid5(uuid.NAMESPACE_URL, "screening:" + item["capture_id"]),
            authorized_at=at,
            screened_at=at,
            viewer_available=item["viewer_available"],
        )
        for item in facts["reviewed"]
    )
    rows = [
        SceneGroupRow(
            rung=None,
            rung_capture_count=0,
            group_id=uuid.UUID(row["group_id"]),
            ordinal=row["ordinal"],
            capture_ids=[uuid.UUID(capture) for capture in row["capture_ids"]],
            first_utc=None,
            last_utc=None,
            member_count=len(row["capture_ids"]),
            positioned_member_count=0,
            radius_m=None,
            centroid_lat_e7=None,
            centroid_lon_e7=None,
        )
        for row in facts["groups"]
    ]
    monkeypatch.setattr(
        personal_sources_module, "reviewed_personal_sources", lambda *a, **k: reviewed
    )
    monkeypatch.setattr(personal_sources_module, "scene_group_rows", lambda *a, **k: rows)
    workspace = uuid.UUID(facts["workspace_id"])
    composition = arrange(
        personal_sources(None, workspace, reviewed_for=uuid.UUID(facts["actor"]), store=None)
    )
    record = personal_composition_record(workspace, composition)
    assert list(composition.region_ids) == golden["region_ids"]
    assert [
        {
            "capture_id": str(source.capture_id),
            "source_sha256": source.source_sha256,
            "evidence_span_id": str(source.evidence_span_id),
            "region_id": source.region_id,
        }
        for source in composition.sources
    ] == golden["sources"]
    assert (composition.reviewed, composition.outside_scene_groups) == (
        golden["reviewed"],
        golden["outside_scene_groups"],
    )
    assert record == golden["record"]
    assert sha256_of_canonical(record).hex() == golden["topology_digest"]


def _capture(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"capture:{name}")


def _photo(name: str) -> ReviewedPhotograph:
    return ReviewedPhotograph(
        _capture(name), sha256_of_canonical(name).hex(), uuid.uuid5(uuid.NAMESPACE_URL, name)
    )


def _row(group_id: str, ordinal: int, *names: str) -> LiveSceneGroup:
    return LiveSceneGroup(group_id, ordinal, frozenset(_capture(name) for name in names))


def _made(**regions: str) -> MadeWorld:
    """A made world: each keyword is a region id, its value the photographs it was made with."""
    sources = tuple(
        ComposedSource(photo.capture_id, photo.source_sha256, photo.evidence_span_id, region)
        for region, names in regions.items()
        for photo in sorted((_photo(name) for name in names), key=lambda p: p.capture_id)
    )
    snapshot = SimpleNamespace(snapshot_id=uuid.uuid4())
    return MadeWorld(snapshot, tuple(regions), sources)  # type: ignore[arg-type]


def _regions(composition) -> dict[str, set[uuid.UUID]]:
    placed: dict[str, set[uuid.UUID]] = {}
    for source in composition.sources:
        placed.setdefault(source.region_id, set()).add(source.capture_id)
    return placed


def test_a_photograph_of_a_made_place_joins_it_however_its_groups_overlap():
    made = _made(R="ABC")
    # Measured: after D joined the place, both rows stayed live, each with ordinal 0.
    rows = (_row("R", 0, "A", "B", "C"), _row("G1", 0, "A", "B", "C", "D"))
    composition = arrange(PersonalSources(tuple(map(_photo, "ABCD")), rows), made)
    assert _regions(composition) == {"R": {_capture(name) for name in "ABCD"}}
    assert [source.capture_id for source in composition.added] == [_capture("D")]
    # Measured: a photograph between two members moved the centroid and split the group; the
    # old row stayed live, so the place still holds both halves.
    split = arrange(
        PersonalSources(
            tuple(map(_photo, "ABD")),
            (_row("R", 0, "A", "B"), _row("S1", 0, "A", "D"), _row("S2", 1, "B")),
        ),
        _made(R="AB"),
    )
    assert _regions(split) == {"R": {_capture(name) for name in "ABD"}}


def test_a_place_with_no_made_photograph_is_a_new_region_named_by_its_largest_group():
    rows = (
        _row("R", 0, "A"),
        _row("E1", 1, "E"),
        _row("E2", 1, "E", "F"),
        _row("Z0", 0, "Z"),
    )
    composition = arrange(PersonalSources(tuple(map(_photo, "AEFZ")), rows), _made(R="A"))
    assert composition.region_ids == ("R", "Z0", "E2")
    assert _regions(composition)["E2"] == {_capture("E"), _capture("F")}
    assert composition.made_region_ids == frozenset({"R"})


def test_a_photograph_that_would_join_two_made_places_is_left_out_and_counted():
    # Measured: a bridging photograph merged two places into one group, old rows still live.
    rows = (
        _row("P", 0, "A", "B"),
        _row("X", 1, "X"),
        _row("M", 0, "A", "B", "F", "X"),
        _row("N", 2, "N"),
    )
    composition = arrange(
        PersonalSources(tuple(map(_photo, "ABFXNL")), rows),
        _made(P="AB", X="X"),
    )
    assert composition.between_places == 1
    assert composition.outside_scene_groups == 1
    assert {source.capture_id for source in composition.added} == {_capture("N")}
    assert _regions(composition)["P"] == {_capture("A"), _capture("B")}


def test_made_photographs_never_move():
    # A no longer reviewed (lapsed) and C in no live row: both stay where the world made them.
    rows = (_row("R", 0, "B", "D"),)
    composition = arrange(PersonalSources(tuple(map(_photo, "BD")), rows), _made(R="ABC"))
    assert _regions(composition) == {"R": {_capture(name) for name in "ABCD"}}
    assert composition.made_outside_groups == frozenset({_capture("A"), _capture("C")})
    assert composition.reviewed_slots == 2


def test_a_group_named_by_a_made_region_is_that_place():
    # The made photograph is gone from every live row, but the row the region is named by still
    # holds another photograph, and a new one grouped with it belongs to the same place.
    rows = (_row("R", 0, "X"), _row("G", 0, "X", "Y"))
    composition = arrange(PersonalSources((_photo("Y"),), rows), _made(R="A"))
    assert _regions(composition) == {"R": {_capture("A"), _capture("Y")}}


def test_every_subject_carries_by_a_rule_and_every_kind_and_reason_has_words():
    rules = WorldObjectRepository._CARRY_RULES
    assert set(rules) == set(EditSubject)
    for judge, write in rules.values():
        assert callable(getattr(WorldObjectRepository, judge))
        assert callable(getattr(WorldObjectRepository, write))
    assert set(_KIND_WORDS) == set(EditSubject)
    assert set(_STAYS_BECAUSE) == set(StayReason)


# -- through the routes, as runtime roles -------------------------------------------------------


def _counts(api) -> dict[str, int]:
    """How many rows each table an addition writes holds, read as the schema owner."""
    connection = api.repository.connection
    return {
        table: connection.execute(
            f"select count(*) as n from {table} where workspace_id=%s",
            (api.repository.workspace_id,),
        ).fetchone()["n"]
        for table in (
            "world_structure_snapshot",
            "world_structure_preview",
            "world_structure_audit_event",
            "world_structure_placement_migration",
            "world_topology_contract",
            "world_alternate_version",
            "world_alternate_version_edit",
            "world_character_appearance_revision",
        )
    }


@pytest.mark.postgres
def test_the_version_tables_are_every_table_that_names_a_version(api):
    rows = api.repository.connection.execute(
        "select distinct c.conrelid::regclass::text as name from pg_constraint c "
        "where c.contype='f' and c.confrelid='world_alternate_version'::regclass"
    ).fetchall()
    assert {row["name"].split(".")[-1] for row in rows} == set(VERSION_TABLES)


@pytest.mark.postgres
def test_nothing_new_is_current(api):
    photograph(api, minute=0)
    group(api)
    make_world(api)
    read = api.read()
    assert read["action"] is None and read["preview"] is None
    assert read["refusal"] == {
        "code": "personal_world_current",
        "detail": "Your world from your photographs already holds every photograph you have "
        "reviewed, and it is saved. Open it from your worlds.",
    }


@pytest.mark.postgres
def test_adding_photographs_keeps_every_place_and_everything_made_in_them(api):
    first = photograph(api, minute=0)
    second = photograph(api, minute=3)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    entry = place_object(api, entry, region)
    entry = region_appearance(api, entry, region)
    look = avatar_look(api, entry)
    made_version = api.version(entry)
    made_media = source_media(api, entry)
    joining = photograph(api, minute=6)
    elsewhere = photograph(api, minute=0, hour=15)
    group(api)

    before = _counts(api)
    read = api.read()
    # The read writes nothing.
    assert _counts(api) == before
    assert read["action"] == "add_photographs" and read["refusal"] is None
    preview = read["preview"]
    assert preview["sentences"] == [
        "2 photographs you reviewed since will be added to your world's places.",
        "1 joins 1 place already in it.",
        "1 makes 1 new place.",
        "Its appearance and everything you made in it carry over: 1 object you placed, the "
        "appearance you gave 1 place, your avatar's appearance.",
        "Take back still reaches the changes you made before this step.",
        "Your world as it is now stays saved as its previous version.",
    ]
    assert preview["counts"] == {
        "photographs_added": 2,
        "photographs_joining_places": 1,
        "places_growing": 1,
        "new_places": 1,
        "photographs_in_new_places": 1,
        "left_out_in_no_place": 0,
        "left_out_between_places": 0,
        "kept_not_allowed": 0,
        "kept_in_no_place": 0,
        "carried": {"object": 1, "element": 0, "environment_instance": 0, "point_map_instance": 0},
        "carried_removals": 0,
        "region_appearances": 1,
        "avatar_revisions": 1,
        "stays_behind": [],
        "society_staying": False,
        "changes_carried": 1,
    }

    added = compose(api, read["topology_digest"], preview["preview_sha256"])
    assert added.status_code == 200, added.text
    assert added.json()["action"] == "add_photographs"
    assert added.json()["saved_entry_id"] == entry["entry_id"]
    moved = api.entry(entry["entry_id"])
    assert moved["availability"] == "available"
    assert moved["revision"] == entry["revision"] + 1
    assert moved["style_version_id"] == entry["style_version_id"]
    assert moved["source_snapshot_id"] != entry["source_snapshot_id"]

    # Every place keeps its id; the made place grew and the new place is its live group.
    media = source_media(api, moved)
    by_capture = {slot["capture_ids"][0]: slot for slot in media}
    assert set(by_capture) == {str(c) for c in (first, second, joining, elsewhere)}
    assert {by_capture[str(c)]["region_id"] for c in (first, second, joining)} == {region}
    assert by_capture[str(elsewhere)]["region_id"] != region
    assert all(slot["state"] == "available" for slot in media)
    # Photographs the world was made with keep their slots exactly.
    for slot in made_media:
        assert {k: v for k, v in by_capture[slot["capture_ids"][0]].items()} == slot

    # The carried version holds the same delta and change list, and Take back reaches through.
    carried = api.version(moved)
    assert carried["parent_version_id"] == made_version["version_id"]
    assert carried["state_sha256"] == made_version["state_sha256"]
    assert carried["edit_seq"] == made_version["edit_seq"] == 1
    assert carried["objects"] == made_version["objects"]
    assert [edit["kind"] for edit in carried["edits"]] == ["add_object"]
    appearance = api.get(
        f"/world/versions/{moved['authored_version_id']}/characters/avatar/{api.actor}/appearance"
        f"?world_id={moved['world_id']}"
    ).json()
    assert appearance["revision"] == 1
    assert appearance["current"]["document"]["recipe"] == look["current"]["document"]["recipe"]
    style = api.get(f"/world/styles/current?world_id={moved['world_id']}").json()
    assert style["current"]["version_id"] == moved["style_version_id"]
    [regional] = style["current"]["region_styles"]
    assert (regional["region_id"], regional["parameters"]["vitality"]) == (region, 0.25)
    assert not any("outside the current topology" in w for w in style["current"]["warnings"])
    assert style["current_topology_digest"] == added.json()["topology_digest"]

    # The previous version is intact and readable, on the snapshot it was made on.
    previous = api.version(entry, made_version["version_id"])
    assert previous == made_version
    assert source_media(api, entry) == made_media

    # Who confirmed, when, and exactly which preview.
    connection = api.repository.connection
    [audit] = connection.execute(
        "select actor,occurred_at,details from world_structure_audit_event "
        "where workspace_id=%s and snapshot_id=%s and event_type='preview_applied'",
        (api.repository.workspace_id, moved["source_snapshot_id"]),
    ).fetchall()
    assert audit["actor"] == api.actor and audit["occurred_at"] is not None
    assert audit["details"]["confirmed_preview_sha256"] == preview["preview_sha256"]
    [migration] = connection.execute(
        "select region_id,approved_by,reason from world_structure_placement_migration "
        "where workspace_id=%s and snapshot_id=%s",
        (api.repository.workspace_id, moved["source_snapshot_id"]),
    ).fetchall()
    assert (migration["region_id"], migration["approved_by"]) == (region, api.actor)
    assert preview["preview_sha256"] in migration["reason"]
    snapshot = connection.execute(
        "select revision,parent_snapshot_id from world_structure_snapshot "
        "where workspace_id=%s and snapshot_id=%s",
        (api.repository.workspace_id, moved["source_snapshot_id"]),
    ).fetchone()
    assert (snapshot["revision"], snapshot["parent_snapshot_id"]) == (
        1,
        uuid.UUID(entry["source_snapshot_id"]),
    )

    taken_back = api.post(
        f"/world/versions/{moved['authored_version_id']}/objects/undo?world_id={moved['world_id']}",
        {"base_state_sha256": carried["state_sha256"], "saved_entry": binding(moved)},
    )
    assert taken_back.status_code == 200, taken_back.text
    assert api.version(moved)["objects"] == []
    assert api.version(entry, made_version["version_id"])["objects"] == made_version["objects"]
    assert api.read()["refusal"]["code"] == "personal_world_current"


#: A person region's outline covering the whole frame, in the millionths a silhouette is stored in.
_WHOLE_FRAME = Silhouette(((0, 0), (1_000_000, 0), (1_000_000, 1_000_000), (0, 1_000_000)))


def _review_no_longer_current(api, capture: uuid.UUID) -> None:
    """A reviewer adds a person region after the review, as the drawer's region edit does.

    The review describes the photograph as it was screened, so it no longer describes it: the
    photograph has no current review until it is reviewed again.
    """
    edited = api.post(
        f"/person-regions/{capture}/edits",
        {
            "edits": [
                {
                    "region_key": "ab" * 32,
                    "action": "add",
                    "silhouette": _WHOLE_FRAME.as_digest_input(),
                }
            ]
        },
    )
    assert edited.status_code == 201, edited.text


@pytest.mark.postgres
def test_photographs_no_longer_allowed_or_in_no_place_stay_where_they_were(api):
    lapsing = photograph(api, minute=0)
    kept = photograph(api, minute=1)
    later_place = photograph(api, minute=0, hour=15)
    group(api)
    entry = make_world(api)
    _review_no_longer_current(api, lapsing)
    joining = photograph(api, minute=2)
    group(api)
    # A grouping whose inputs changed goes stale, so that photograph is in no live place.
    api.repository.connection.execute(
        "update derived_artifact set stale=true where workspace_id=%s and kind='scene_group' "
        "and %s=any(source_ids)",
        (api.repository.workspace_id, later_place),
    )
    api.repository.connection.commit()
    read = api.read()
    assert read["action"] == "add_photographs", read
    preview = read["preview"]
    assert preview["sentences"][:3] == [
        "1 photograph you reviewed since will be added to your world's places.",
        "1 joins 1 place already in it.",
        "1 of its photographs is no longer allowed in it (deleted, withdrawn or without a "
        "current review from you), so the world does not show it; it stays in its place and "
        "shows again after a new review.",
    ]
    assert preview["sentences"][3] == (
        "1 of its photographs is no longer in any place and stays where it was placed."
    )
    assert (preview["counts"]["kept_not_allowed"], preview["counts"]["kept_in_no_place"]) == (1, 1)
    added = compose(api, read["topology_digest"], preview["preview_sha256"])
    assert added.status_code == 200, added.text
    moved = api.entry(entry["entry_id"])
    shown = {
        slot["capture_ids"][0]: (slot["region_id"], slot["state"], slot["reason"])
        for slot in source_media(api, moved)
    }
    made = {slot["capture_ids"][0]: slot["region_id"] for slot in source_media(api, entry)}
    assert shown == {
        str(lapsing): (made[str(lapsing)], "unavailable_asset", LAPSED),
        str(kept): (made[str(kept)], "available", None),
        str(later_place): (made[str(later_place)], "available", None),
        str(joining): (made[str(kept)], "available", None),
    }


@pytest.mark.postgres
def test_a_preview_that_changed_is_refused_and_nothing_is_written(api):
    photograph(api, minute=0)
    group(api)
    created = api.read()
    # A preview confirms an addition only; given for anything else it is refused.
    wrong = compose(api, created["topology_digest"], "0" * 64)
    assert wrong.status_code == 409 and wrong.json()["code"] == "personal_world_preview_changed"
    assert api.worlds() == []
    entry = make_world(api)
    photograph(api, minute=3)
    group(api)
    shown = api.read()
    photograph(api, minute=5)
    group(api)
    before = _counts(api)
    style = api.get(f"/world/styles/current?world_id={entry['world_id']}").json()
    stale = compose(api, shown["topology_digest"], shown["preview"]["preview_sha256"])
    assert stale.status_code == 409
    assert stale.json() == {
        "code": "personal_world_preview_changed",
        "detail": "Your world or your photographs changed after you looked, so nothing was "
        "added. Look again, then confirm.",
    }
    current = api.read()
    unconfirmed = compose(api, current["topology_digest"])
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["code"] == "personal_world_preview_changed"
    assert _counts(api) == before
    assert api.entry(entry["entry_id"]) == entry
    assert api.get(f"/world/styles/current?world_id={entry['world_id']}").json() == style
    confirmed = compose(api, current["topology_digest"], current["preview"]["preview_sha256"])
    assert confirmed.status_code == 200, confirmed.text


class _Depth(FlatDepthModel):
    """The flat depth double, naming the checkpoint the right below names."""

    identity = ModelIdentity.local(DEPTH_ROLE, "test/plane-depth", "1" * 40)

    def __init__(self) -> None:
        super().__init__()
        self.model_handoff = ModelHandoff.local(self.identity)


def _placed_estimate(api, entry: dict, capture: uuid.UUID, region: str) -> tuple[dict, object]:
    """Attach ``capture`` to the saved world, make its estimate and place it; returns the entry."""
    [reviewed] = reviewed_personal_sources(
        api.repository.connection,
        api.repository.workspace_id,
        reviewed_for=api.actor,
        store=None,
        capture_id=capture,
    )
    attached = api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments",
        {
            "operation_id": str(uuid.uuid4()),
            "base_revision": entry["revision"],
            "authored_version_id": entry["authored_version_id"],
            "authored_state_sha256": entry["authored_state_sha256"],
            "authored_edit_seq": entry["authored_edit_seq"],
            "style_version_id": entry["style_version_id"],
            "sources": [
                {"capture_id": str(capture), "evidence_span_id": str(reviewed.evidence_span_id)}
            ],
        },
    )
    assert attached.status_code == 200, attached.text
    entry = attached.json()
    now = api.repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    right = grant_model_right(
        api.repository,
        capture_id=capture,
        authorization_id=reviewed.authorization_id,
        identity=_Depth.identity,
        destination=LOCAL_PROCESS,
        granted_by=api.actor,
        purpose="place a 3D estimate of my own photograph in my own world",
        valid_until=now + dt.timedelta(hours=1),
        granted_at=now,
    )
    outcome = PhotoIngestPipeline(api.repository, api.store, depth=_Depth()).ingest_derivatives(
        capture, privacy_screening_id=reviewed.screening_id
    )
    assert outcome.error is None, outcome.error
    api.repository.connection.commit()
    version = api.version(entry)
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/compositions/photo-point-maps/apply"
        f"?world_id={entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "source": {
                "kind": "photo_point_map",
                "entry_id": entry["entry_id"],
                "attachment_id": entry["source_attachments"][0]["attachment_id"],
            },
            "placement": {
                "subject_id": "point-map:courtyard",
                "region_id": region,
                "transform": {
                    "x_mm": 1200,
                    "y_mm": 0,
                    "z_mm": -450,
                    "yaw_microradians": 0,
                    "scale_milli": 1000,
                },
                "origin_role": "personal",
            },
            "saved_entry": binding(entry),
        },
    )
    assert placed.status_code == 201, placed.text
    return api.entry(entry["entry_id"]), right


@pytest.mark.postgres
def test_a_removed_estimate_that_cannot_be_written_stays_and_take_back_starts_at_the_addition(api):
    capture = photograph(api, minute=0)
    photograph(api, minute=3)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    entry, right = _placed_estimate(api, entry, capture, region)
    # The person stops the depth right and takes the estimate out: a stored removal of a
    # placement that pins a right that will never stand again. No route removes a placed
    # estimate, so the repository does, connected as the runtime role the routes use.
    stopped = api.post(f"/personal-admission/model-rights/{right.right_id}/withdraw", {})
    assert stopped.status_code == 200, stopped.text
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"], store=api.store
        )
        stored = objects.version(uuid.UUID(entry["authored_version_id"]))
        objects.remove_point_map(
            stored.version_id,
            "point-map:courtyard",
            base_state_sha256=stored.state_sha256,
            actor=api.actor,
        )
    removed = api.version(entry)
    adopted = api.put(
        f"/world-entries/{entry['entry_id']}",
        {
            "base_revision": entry["revision"],
            "authored_version_id": entry["authored_version_id"],
            "expected_authored_state_sha256": removed["state_sha256"],
            "expected_authored_edit_seq": removed["edit_seq"],
            "style_version_id": entry["style_version_id"],
        },
    )
    assert adopted.status_code == 200, adopted.text
    entry = adopted.json()
    photograph(api, minute=6)
    group(api)

    read = api.read()
    assert read["action"] == "add_photographs", read
    preview = read["preview"]
    assert preview["counts"]["stays_behind"] == [
        {"kind": "point_map_instance", "reason": "right_ended", "count": 1}
    ]
    assert preview["counts"]["changes_carried"] == 0
    assert preview["sentences"][-3:] == [
        "1 photograph depth estimate stays only in the previous version, because its depth "
        "right has ended.",
        "Take back starts from this step, because not everything in your world carries over.",
        "Your world as it is now stays saved as its previous version.",
    ]
    added = compose(api, read["topology_digest"], preview["preview_sha256"])
    assert added.status_code == 200, added.text
    moved = api.entry(entry["entry_id"])
    carried = api.version(moved)
    assert carried["point_map_instances"] == []
    assert (carried["edits"], carried["edit_seq"]) == ([], 0)
    previous = api.version(entry, entry["authored_version_id"])
    assert [placed["removed"] for placed in previous["point_map_instances"]] == [True]
    assert [edit["kind"] for edit in previous["edits"]] == ["add_point_map", "remove_point_map"]
    nothing = api.post(
        f"/world/versions/{moved['authored_version_id']}/objects/undo?world_id={moved['world_id']}",
        {"base_state_sha256": carried["state_sha256"], "saved_entry": binding(moved)},
    )
    assert nothing.status_code == 409
    assert nothing.json()["detail"] == "this version has no edit left to undo"


#: The engine that keeps where inhabitants are, and one that does not
#: (``exulanica/world/society-engines.v1.json``).
_KEEPS_PRESENCE = "exulanica-society/v2"
_NO_PRESENCE = "exulanica-society/v3"


def _society(
    api,
    entry: dict,
    *,
    presence: str | None,
    inhabitants: int = 1,
    engine: str = _KEEPS_PRESENCE,
) -> None:
    """A society on the saved world's version, planted: no product path gives a personal-source
    world inhabitants, and this is the one cause an addition refuses until the person acts."""
    connection = api.repository.connection
    place = uuid.uuid4()
    connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (api.repository.workspace_id, place),
    )
    state: dict = {"inhabitants": [{"id": str(uuid.uuid4())} for _ in range(inhabitants)]}
    if presence is not None:
        state["presence"] = {"status": presence}
    connection.execute(
        "insert into world_society(workspace_id,world_id,version_id,place_id,region_id,"
        "engine_version,seed,population_size,tick_seconds,state,state_sha256,created_by) "
        "values(%s,%s,%s,%s,%s,%s,%s,1,60,%s,%s,%s)",
        (
            api.repository.workspace_id,
            entry["world_id"],
            entry["authored_version_id"],
            place,
            "region:society",
            engine,
            "ab" * 32,
            json.dumps(state),
            sha256_of_canonical(state).hex(),
            api.actor,
        ),
    )
    connection.commit()


@pytest.mark.postgres
def test_inhabitants_who_are_here_refuse_the_addition_and_the_refusal_names_the_fix(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    _society(api, entry, presence="here")
    photograph(api, minute=3)
    group(api)
    read = api.read()
    assert read["action"] is None
    assert read["refusal"] == {
        "code": "personal_world_edit_cannot_carry",
        "detail": "1 photograph you reviewed since can be added to your world, but its "
        "inhabitants are here, and inhabitants do not move to the world with the added "
        "photographs. Send the inhabitants away first, then add the photographs.",
    }
    refused = compose(api, read["topology_digest"], "0" * 64)
    assert refused.json() == read["refusal"]


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("society", "said"),
    [
        (
            {"presence": "away"},
            "Its inhabitants, who are away, and their history stay only in the previous version.",
        ),
        (
            {"presence": "here", "inhabitants": 0},
            "Its society, which has no inhabitants, and its history stay only in the previous "
            "version.",
        ),
        (
            {"presence": None, "engine": _NO_PRESENCE},
            "Its inhabitants and their history stay only in the previous version.",
        ),
    ],
    ids=["away", "no-inhabitants", "presence-not-kept"],
)
def test_a_society_stays_in_the_previous_version_and_the_preview_says_only_what_is_known(
    api, society, said
):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    _society(api, entry, **society)
    photograph(api, minute=3)
    group(api)
    read = api.read()
    assert read["action"] == "add_photographs", read
    assert said in read["preview"]["sentences"]
    assert (
        sum("stay only in the previous version." in line for line in read["preview"]["sentences"])
        == 1
    )
    assert read["preview"]["counts"]["society_staying"] is True
    added = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert added.status_code == 200, added.text
    moved = api.entry(entry["entry_id"])
    held = api.repository.connection.execute(
        "select version_id from world_society where workspace_id=%s and world_id=%s",
        (api.repository.workspace_id, entry["world_id"]),
    ).fetchall()
    assert [row["version_id"] for row in held] == [uuid.UUID(entry["authored_version_id"])]
    assert moved["authored_version_id"] != entry["authored_version_id"]


@pytest.mark.postgres
def test_a_made_world_whose_photograph_was_deleted_is_refused_by_name(api):
    capture = photograph(api, minute=0)
    group(api)
    make_world(api)
    photograph(api, minute=3)
    group(api)
    api.repository.insert_tombstone(
        scope="capture", capture_id=capture, requested_by=api.actor, reason="the person deleted it"
    )
    api.repository.connection.commit()
    read = api.read()
    assert read["refusal"] == {
        "code": "personal_world_source_deleted",
        "detail": "A photograph your world from your photographs was made with was deleted, so "
        "it cannot be opened or added to. This app does not rebuild a world from the "
        "photographs that remain.",
    }


@pytest.mark.postgres
def test_a_stranger_can_neither_see_nor_add_to_the_owners_world(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    photograph(api, minute=3)
    group(api)
    read = api.read()
    stranger = api.get(PATH, token=STRANGER_TOKEN).json()
    assert stranger["world_id"] is None and stranger["preview"] is None
    refused = api.post(
        PATH,
        {
            "topology_digest": read["topology_digest"],
            "preview_sha256": read["preview"]["preview_sha256"],
        },
        token=STRANGER_TOKEN,
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "no_reviewed_personal_sources"
    assert api.entry(entry["entry_id"]) == entry


@pytest.mark.postgres
def test_an_addition_is_applied_only_confirmed_and_only_as_the_composed_candidate(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    world = entry["world_id"]
    with api.database.session(api.repository.workspace_id) as connection:
        structures = WorldStructureRepository(
            connection, api.repository.workspace_id, world_id=world
        )
        contract = WorldStyleRepository(
            connection, api.repository.workspace_id, world_id=world
        ).current_topology_contract()
        made = structures.current()
        candidate = composed_candidate(contract, "1" * 64, "2" * 64)
        preview = structures.preview(candidate, proposed_by=api.actor)
        base = {
            "base_snapshot_id": preview.base_snapshot_id,
            "base_graph_sha256": preview.base_graph_sha256,
            "base_reconstruction_sha256": preview.base_reconstruction_sha256,
            "committed_by": api.actor,
        }
        with pytest.raises(InvalidStructuralData, match="only with the preview the person"):
            structures.apply(
                preview.preview_id,
                **base,
                advanced_composed_topology_digest=contract.topology_digest,
            )
        # A candidate that is not the composed candidate of the current composed topology.
        other = candidate.topology["regions"][0]["region_id"]
        tampered = composed_candidate(
            type(contract)(
                contract.topology_digest,
                (*contract.region_ids, f"{other}-elsewhere"),
                contract.source_slots,
                world_id=world,
            ),
            "1" * 64,
            "2" * 64,
        )
        wrong = structures.preview(tampered, proposed_by=api.actor)
        with pytest.raises(InvalidStructuralData, match="an addition must preserve the exact"):
            structures.apply(
                wrong.preview_id,
                **base,
                advanced_composed_topology_digest=contract.topology_digest,
                confirmed_preview_sha256="3" * 64,
            )
        connection.rollback()
        assert structures.current().snapshot_id == made.snapshot_id


@pytest.mark.postgres
def test_a_version_that_moved_after_its_carry_was_read_is_not_carried(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection,
            api.repository.workspace_id,
            world_id=entry["world_id"],
            store=api.store,
        )
        version_id = uuid.UUID(entry["authored_version_id"])
        plan = objects.carry_plan(version_id)
        connection.commit()
    place_object(api, entry, region)
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection,
            api.repository.workspace_id,
            world_id=entry["world_id"],
            store=api.store,
        )
        snapshot = uuid.UUID(entry["source_snapshot_id"])
        with pytest.raises(StaleObjectBase):
            objects.carry_version(plan, source_snapshot_id=snapshot, created_by=api.actor)


@pytest.mark.postgres
def test_a_made_world_holding_a_slot_not_composed_here_is_refused_by_name(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    other = photograph(api, minute=3)
    group(api)
    [reviewed] = reviewed_personal_sources(
        api.repository.connection,
        api.repository.workspace_id,
        reviewed_for=api.actor,
        store=None,
        capture_id=other,
    )
    connection = api.repository.connection
    topology = connection.execute(
        "select topology_sha256 from world_structure_snapshot where workspace_id=%s "
        "and snapshot_id=%s",
        (api.repository.workspace_id, entry["source_snapshot_id"]),
    ).fetchone()["topology_sha256"]
    # A slot whose source id no photograph's own source id answers for, as a world composed by
    # another writer would hold.
    connection.execute(
        "insert into world_topology_source (source_id,workspace_id,world_id,topology_digest,"
        "region_id,slot_key,evidence_span_id,missing_reason) values (%s,%s,%s,%s,%s,%s,%s,null)",
        (
            uuid.uuid4(),
            api.repository.workspace_id,
            entry["world_id"],
            topology,
            region,
            "source.planted-elsewhere",
            reviewed.evidence_span_id,
        ),
    )
    connection.commit()
    read = api.read()
    assert read["action"] is None and read["preview"] is None
    assert read["refusal"] == {
        "code": "personal_world_not_composed",
        "detail": "Your world from your photographs holds places this app did not compose from "
        "your reviewed photographs, so it cannot add photographs to it.",
    }


@pytest.mark.postgres
@pytest.mark.parametrize("failure", [StaleObjectBase("moved"), RuntimeError("the disk went away")])
def test_an_addition_that_fails_part_way_writes_nothing_and_the_world_still_opens(
    api, monkeypatch, failure
):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    photograph(api, minute=3)
    group(api)
    read = api.read()
    before = _counts(api)
    style = api.get(f"/world/styles/current?world_id={entry['world_id']}").json()

    # The carry runs after the next snapshot is appended and the composition registered.
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(WorldObjectRepository, "carry_version", fail)
    if isinstance(failure, StaleObjectBase):
        refused = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
        assert refused.status_code == 409
        assert refused.json()["code"] == "personal_world_preview_changed"
    else:
        with pytest.raises(RuntimeError):
            compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert _counts(api) == before
    assert api.get(f"/world/styles/current?world_id={entry['world_id']}").json() == style
    kept = api.entry(entry["entry_id"])
    assert kept == entry and kept["availability"] == "available"
    assert api.read()["preview"] == read["preview"]


@pytest.mark.postgres
def test_a_carry_whose_rows_would_carry_differently_now_is_not_carried(api):
    """The version's state has not moved, but a depth right it pins has ended since the plan."""
    capture = photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    entry, right = _placed_estimate(api, entry, capture, region)
    version_id = uuid.UUID(entry["authored_version_id"])
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"], store=api.store
        )
        plan = objects.carry_plan(version_id)
        connection.commit()
    assert [part.outcome for part in plan.parts] == [CarryOutcome.CARRIED]
    withdraw_model_right(api.repository, right_id=right.right_id, withdrawn_by=api.actor)
    api.repository.connection.commit()
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"], store=api.store
        )
        assert objects.version(version_id).state_sha256 == plan.state_sha256
        with pytest.raises(StaleObjectBase, match="what carries from it"):
            objects.carry_version(
                plan,
                source_snapshot_id=uuid.UUID(entry["source_snapshot_id"]),
                created_by=api.actor,
            )


# -- the saved world's own version, and the carry's last question --------------------------------


def _move_entry(api, entry: dict, version: dict) -> dict:
    """Point the saved world at ``version`` through PUT /world-entries, which takes any version."""
    moved = api.put(
        f"/world-entries/{entry['entry_id']}",
        {
            "base_revision": entry["revision"],
            "authored_version_id": version["version_id"],
            "expected_authored_state_sha256": version["state_sha256"],
            "expected_authored_edit_seq": version["edit_seq"],
            "style_version_id": entry["style_version_id"],
        },
    )
    assert moved.status_code == 200, moved.text
    return moved.json()


@pytest.mark.postgres
def test_a_saved_world_on_an_earlier_version_is_refused_until_it_opens_the_latest(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    made = api.version(entry)
    photograph(api, minute=3)
    group(api)
    first = api.read()
    assert (
        compose(api, first["topology_digest"], first["preview"]["preview_sha256"]).status_code
        == 200
    )
    latest = api.entry(entry["entry_id"])
    back = _move_entry(api, latest, made)
    assert back["availability"] == "available"
    assert back["source_snapshot_id"] == entry["source_snapshot_id"]
    photograph(api, minute=6)
    group(api)

    before = _counts(api)
    read = api.read()
    assert read["action"] is None and read["preview"] is None
    assert read["refusal"] == {
        "code": "personal_world_not_latest",
        "detail": "Your saved world opens an earlier version of your world from your photographs, "
        "and photographs are added only to its latest version. Move your saved world to the "
        "latest version, then add them.",
    }
    refused = compose(api, read["topology_digest"], "0" * 64)
    assert refused.status_code == 409 and refused.json() == read["refusal"]
    assert _counts(api) == before
    assert api.entry(entry["entry_id"]) == back

    # Moved to the latest version again, the saved world takes the photograph.
    forward = _move_entry(api, back, api.version(latest))
    read = api.read()
    assert read["action"] == "add_photographs", read
    added = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert added.status_code == 200, added.text
    assert api.entry(entry["entry_id"])["revision"] == forward["revision"] + 1


@pytest.mark.postgres
def test_a_saved_world_changed_elsewhere_is_refused_by_name(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    # An edit that names no saved world moves the version under it.
    unbound = api.post(
        f"/world/versions/{entry['authored_version_id']}/objects?world_id={entry['world_id']}",
        {
            "base_state_sha256": api.version(entry)["state_sha256"],
            "object_id": "object:unbound",
            "asset_sha256": CUBE,
            "region_id": region,
            "transform": {
                "x_mm": 0,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            },
            "origin_role": "fictional",
        },
    )
    assert unbound.status_code == 201, unbound.text
    drifted = api.entry(entry["entry_id"])
    assert drifted["unavailable_reason"] == "authored_version_changed"
    photograph(api, minute=3)
    group(api)
    read = api.read()
    assert read["action"] is None and read["preview"] is None
    assert read["refusal"] == {
        "code": "personal_world_changed_elsewhere",
        "detail": "Your world from your photographs was changed after it was last saved. Open it "
        "from your worlds and choose whether to use the latest changes, then add your "
        "photographs.",
    }
    refused = compose(api, read["topology_digest"], "0" * 64)
    assert refused.status_code == 409 and refused.json() == read["refusal"]
    assert api.entry(entry["entry_id"]) == drifted


def _withdraw_elsewhere(api, right_id: uuid.UUID, *, lock_timeout: str) -> str:
    """Stop a depth right from another session, as the withdraw route does, while one runs here.

    Returns ``"withdrawn"`` when it committed, or the SQLSTATE it was refused with; the lock
    timeout is how long it may wait for a lock the other session holds.
    """
    with api.database.session(api.repository.workspace_id) as connection:
        connection.execute(f"set lock_timeout = '{lock_timeout}'")
        try:
            withdraw_model_right(
                IngestRepository(connection, api.repository.workspace_id),
                right_id=right_id,
                withdrawn_by=api.actor,
            )
        except psycopg.Error as error:
            return str(error.sqlstate)
    return "withdrawn"


def _end_in_this_transaction(connection, api, right_id: uuid.UUID) -> None:
    """End a right inside the addition's own transaction.

    Stands in for a right passing its end between two statements of the addition, which a test
    cannot time: nothing another session does can end it there, because a withdrawal waits for
    the addition (see the next test). The addition rolls back, and this with it.
    """
    withdraw_model_right(
        IngestRepository(connection, api.repository.workspace_id),
        right_id=right_id,
        withdrawn_by=api.actor,
    )


def _world_with_a_placed_estimate_and_a_new_photograph(api):
    capture = photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    entry, right = _placed_estimate(api, entry, capture, region)
    photograph(api, minute=3)
    group(api)
    return entry, right


@pytest.mark.postgres
def test_a_right_withdrawn_elsewhere_during_the_addition_waits_for_it(api, monkeypatch):
    """A withdrawal waits on the locks the addition's reads of rights take, so it commits after.

    Measured, not built here: the withdrawal's own trigger takes the workspace's privacy
    currency lock, which the addition holds from its first read of a right.
    """
    entry, right = _world_with_a_placed_estimate_and_a_new_photograph(api)
    read = api.read()
    tried = []
    carry = WorldObjectRepository._carry_point_map

    def withdrawn_while_written(self, *args):
        tried.append(_withdraw_elsewhere(api, right.right_id, lock_timeout="1s"))
        return carry(self, *args)

    monkeypatch.setattr(WorldObjectRepository, "_carry_point_map", withdrawn_while_written)
    added = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert added.status_code == 200, added.text
    # 55P03: it waited for a lock the addition held until the wait was given up.
    assert tried == ["55P03"]
    moved = api.entry(entry["entry_id"])
    carried = api.version(moved)["point_map_instances"]
    assert [placed["instance_id"] for placed in carried] == ["point-map:courtyard"]
    assert _withdraw_elsewhere(api, right.right_id, lock_timeout="10s") == "withdrawn"


@pytest.mark.postgres
@pytest.mark.parametrize(
    "where",
    [
        # Before the carry's last question: it asks the plan again and sees the right ended.
        (WorldStructureRepository, "apply"),
        # After it, as the carried estimate is written: the binding trigger refuses the row.
        (WorldObjectRepository, "_carry_point_map"),
    ],
    ids=["before-the-last-question", "as-the-row-is-written"],
)
def test_a_right_that_ends_during_the_addition_refuses_it_with_nothing_written(
    api, monkeypatch, where
):
    entry, right = _world_with_a_placed_estimate_and_a_new_photograph(api)
    read = api.read()
    before = _counts(api)
    owner, name = where
    original = getattr(owner, name)

    def ended_first(self, *args, **kwargs):
        _end_in_this_transaction(self.connection, api, right.right_id)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(owner, name, ended_first)
    refused = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "personal_world_preview_changed"
    assert _counts(api) == before
    assert api.entry(entry["entry_id"]) == entry
    monkeypatch.undo()
    # The right ended only inside the addition that was undone, so it still stands.
    assert api.read()["preview"] == read["preview"]


# -- every kind of row carries, and one that cannot stays ------------------------------------------


def _carries_whole(before: dict, after: dict, section: str) -> None:
    """``after`` carries ``before``'s rows of ``section`` and its change list, row for row."""
    assert after[section] and after[section] == before[section]
    assert after["state_sha256"] == before["state_sha256"]
    assert [edit["kind"] for edit in after["edits"]] == [edit["kind"] for edit in before["edits"]]
    assert after["parent_version_id"] == before["version_id"]


def _add_what_the_read_offers(api, entry: dict) -> dict:
    read = api.read()
    assert read["action"] == "add_photographs", read
    added = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert added.status_code == 200, added.text
    return api.version(api.entry(entry["entry_id"]))


@pytest.mark.postgres
def test_a_placed_estimate_carries_with_its_change_list(api):
    entry, _right = _world_with_a_placed_estimate_and_a_new_photograph(api)
    placed = api.version(entry)
    counts = api.read()["preview"]["counts"]
    assert counts["carried"]["point_map_instance"] == 1 and counts["stays_behind"] == []
    _carries_whole(placed, _add_what_the_read_offers(api, entry), "point_map_instances")


@pytest.mark.postgres
def test_an_element_override_carries_with_its_change_list(api):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [slot] = source_media(api, entry)
    version_id = uuid.UUID(entry["authored_version_id"])
    # No route writes an element override; the repository does, as the runtime role, and the
    # saved world then takes its version's state, as the list of saved worlds offers.
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"], store=api.store
        )
        objects.set_element_override(
            version_id,
            ElementOverride(f"element:source:{slot['source_id']}", suppressed=True),
            base_state_sha256=objects.version(version_id).state_sha256,
            actor=api.actor,
        )
    entry = _move_entry(api, entry, api.version(entry))
    overridden = api.version(entry)
    photograph(api, minute=3)
    group(api)
    sentences = api.read()["preview"]["sentences"]
    assert (
        "Its appearance and everything you made in it carry over: 1 change to a place's "
        "structure." in sentences
    )
    _carries_whole(overridden, _add_what_the_read_offers(api, entry), "element_overrides")


def _placed_environment(api, entry: dict, region: str, tmp_path):
    """Admit an environment source as the product admits one, and place it in ``region``."""
    with api.database.session(api.repository.workspace_id) as connection:
        environment = _admit_environment(
            IngestRepository(connection, api.repository.workspace_id), api.store, tmp_path, "yard"
        )
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/environment-instances"
        f"?world_id={entry['world_id']}",
        {
            "base_state_sha256": entry["authored_state_sha256"],
            "instance_id": "environment:yard",
            "admission_id": str(environment.source.admission_id),
            "render_asset_id": str(environment.render.asset_id),
            "publication_id": None,
            "selection": {"kind": "whole_asset"},
            "source_anchor": {
                "frame_name": "nyc-grid",
                "coordinate_scale": 1000,
                "coordinates": [10, 20, 0],
            },
            "region_id": region,
            "transform": {
                "x_mm": 0,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1000,
            },
            "origin_role": "personal",
            "saved_entry": binding(entry),
        },
    )
    assert placed.status_code == 201, placed.text
    return api.entry(entry["entry_id"]), environment


def _world_with_a_placed_environment_and_a_new_photograph(api, tmp_path):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    entry, environment = _placed_environment(api, entry, region, tmp_path)
    photograph(api, minute=3)
    group(api)
    return entry, environment


def _withdraw_environment_elsewhere(api, admission_id: uuid.UUID) -> str:
    """Withdraw an environment source from another session; ``"withdrawn"`` or the SQLSTATE."""
    with api.database.session(api.repository.workspace_id) as connection:
        connection.execute("set lock_timeout = '10s'")
        try:
            EnvironmentRepository(connection, api.repository.workspace_id, api.store).withdraw(
                "source", admission_id
            )
        except psycopg.Error as error:
            return str(error.sqlstate)
    return "withdrawn"


@pytest.mark.postgres
def test_an_environment_piece_carries_with_its_change_list(api, tmp_path):
    entry, _environment = _world_with_a_placed_environment_and_a_new_photograph(api, tmp_path)
    placed = api.version(entry)
    counts = api.read()["preview"]["counts"]
    assert counts["carried"]["environment_instance"] == 1 and counts["stays_behind"] == []
    _carries_whole(placed, _add_what_the_read_offers(api, entry), "environment_instances")


@pytest.mark.postgres
def test_an_environment_piece_whose_source_was_withdrawn_stays_in_the_previous_version(
    api, tmp_path
):
    entry, environment = _world_with_a_placed_environment_and_a_new_photograph(api, tmp_path)
    placed = api.version(entry)
    assert _withdraw_environment_elsewhere(api, environment.source.admission_id) == "withdrawn"
    preview = api.read()["preview"]
    assert preview["counts"]["stays_behind"] == [
        {"kind": "environment_instance", "reason": "source_withdrawn", "count": 1}
    ]
    assert preview["sentences"][-3:] == [
        "1 environment piece stays only in the previous version, because its source was withdrawn.",
        "Take back starts from this step, because not everything in your world carries over.",
        "Your world as it is now stays saved as its previous version.",
    ]
    carried = _add_what_the_read_offers(api, entry)
    assert carried["environment_instances"] == [] and carried["edits"] == []
    assert api.version(entry, placed["version_id"]) == api.version(entry)


@pytest.mark.postgres
def test_an_environment_source_withdrawn_while_the_addition_writes_cannot_commit_before_it(
    api, tmp_path, monkeypatch
):
    """The carry holds the asset read lock from its last question until it commits."""
    entry, environment = _world_with_a_placed_environment_and_a_new_photograph(api, tmp_path)
    read = api.read()
    tried = []
    carry = WorldObjectRepository._carry_environment

    def withdrawn_while_written(self, *args):
        tried.append(_withdraw_environment_elsewhere(api, environment.source.admission_id))
        return carry(self, *args)

    monkeypatch.setattr(WorldObjectRepository, "_carry_environment", withdrawn_while_written)
    added = compose(api, read["topology_digest"], read["preview"]["preview_sha256"])
    assert added.status_code == 200, added.text
    # Refused as retryable while the addition held the lock, so it never ended under it.
    assert tried == ["40001"]
    carried = api.version(api.entry(entry["entry_id"]))["environment_instances"]
    assert [placed["instance_id"] for placed in carried] == ["environment:yard"]
    assert _withdraw_environment_elsewhere(api, environment.source.admission_id) == "withdrawn"


# -- a base the preview was read from moves, and nothing the person reads changes -----------------


def _rename(api, entry: dict, title: str) -> dict:
    version = api.version(entry)
    renamed = api.put(
        f"/world-entries/{entry['entry_id']}",
        {
            "base_revision": entry["revision"],
            "authored_version_id": entry["authored_version_id"],
            "expected_authored_state_sha256": version["state_sha256"],
            "expected_authored_edit_seq": version["edit_seq"],
            "style_version_id": entry["style_version_id"],
            "title": title,
        },
    )
    assert renamed.status_code == 200, renamed.text
    return renamed.json()


@pytest.mark.postgres
@pytest.mark.parametrize(
    "move",
    [
        lambda api, entry: _rename(api, entry, "Renamed"),
        lambda api, entry: world_appearance(api, entry),
    ],
    ids=["entry-revision", "style-version"],
)
def test_a_preview_whose_bases_moved_without_changing_a_count_is_refused(api, move):
    photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    photograph(api, minute=3)
    group(api)
    shown = api.read()
    moved = move(api, entry)
    again = api.read()
    # Nothing the person reads changed: only a base the preview names moved.
    assert again["preview"]["counts"] == shown["preview"]["counts"]
    assert again["preview"]["sentences"] == shown["preview"]["sentences"]
    before = _counts(api)
    stale = compose(api, shown["topology_digest"], shown["preview"]["preview_sha256"])
    assert stale.status_code == 409
    assert stale.json()["code"] == "personal_world_preview_changed"
    assert _counts(api) == before
    assert api.entry(entry["entry_id"]) == moved
    confirmed = compose(api, again["topology_digest"], again["preview"]["preview_sha256"])
    assert confirmed.status_code == 200, confirmed.text
