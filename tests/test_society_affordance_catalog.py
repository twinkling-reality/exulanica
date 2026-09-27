"""What the society records and says of each kind of activity is its catalogs', not code.

``assets/catalogs/society/society-affordance.v1.json`` states, for rest, visit, stand and talk,
the reason a goal carries and the outcome a finished stay records, and names the purposeful routine
versions it serves. The planner and the action route read it; a published version is frozen by its
digest, because stored societies record its codes and a replay must produce them unchanged. What is
said of each kind is ``society-words/society-activity-words.v1.json``'s, which the Companion's words
and the page read and which is corrected in place, because words are not replayed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pytest
from exulanica.api.routes import society_actions as action_routes
from exulanica.grammar.catalogs import catalog_digest, load_catalog
from exulanica.grammar.errors import CatalogError
from exulanica.selection import inhabitant_words
from exulanica.selection.inhabitant_words import (
    ACTIVITY_WORDS,
    ACTIVITY_WORDS_PATH,
    WordsCatalogRefused,
    _activity_words,
)
from exulanica.world import society_catalogs, society_planner
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import ActionIntent, UnknownAffordance, build_action_request
from exulanica.world.society_catalogs import (
    AFFORDANCE_CATALOG,
    ROUTINE_DIRECTORY,
    SCHEMAS,
    ActivityKind,
    _published_activity_kinds,
    _settings_by_kind,
    load_purposeful_routine,
    purposeful_routine,
)
from exulanica.world.society_planner import (
    UNRECORDED_ROUTINE,
    advance_purposeful_society,
    initial_purposeful_society,
)

import test_society_runtime as runtime_helpers
from society_fixtures import SEED, SOCIETY, VERSION, society_input
from test_society_controls_api import control_api
from test_society_controls_postgres import create

runtime_world = runtime_helpers.runtime_world
__all__ = ["control_api", "runtime_world"]

PUBLISHED = ROUTINE_DIRECTORY / f"{AFFORDANCE_CATALOG}.v1.json"


def _copy(tmp_path: Path) -> Path:
    directory = tmp_path / "society"
    shutil.copytree(ROUTINE_DIRECTORY, directory)
    return directory


def _edited(tmp_path: Path, edit) -> Path:
    directory = _copy(tmp_path)
    target = directory / PUBLISHED.name
    document = json.loads(target.read_text(encoding="utf-8"))
    edit({entry["key"]: entry for entry in document["entries"]}, document)
    target.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return directory


def test_every_routine_version_resolves_each_of_its_activities_to_one_entry():
    assert set(UNRECORDED_ROUTINE.kinds) == {"rest", "visit"}
    assert set(purposeful_routine().kinds) == {"rest", "visit", "stand", "talk"}
    assert UNRECORDED_ROUTINE.kind("rest").nearest_reason == "restore_need"
    assert purposeful_routine().kind("visit").drawn_reason == "looking_around"
    with pytest.raises(CatalogError, match="offers no activity 'fly'"):
        purposeful_routine().kind("fly")


def test_a_society_run_records_what_it_recorded_when_the_codes_were_code():
    """Three hundred minutes of a nearest-place society, every state and event, hashed as main
    produced them before the codes left the planner (d7d3b2f1, 2026-09-26). The drawn routine's
    runs are held byte for byte by the comparison goldens (tests/snapshots)."""
    document = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, document)
    run = hashlib.sha256()
    for _ in range(300):
        state, events = advance_purposeful_society(state, SEED, [document])
        run.update(society_state_sha256(state).encode())
        for event in events:
            run.update(json.dumps(event.document, sort_keys=True).encode())
    assert run.hexdigest() == "89dc9ccade74ca379f4b2a6f4dddb7e03616735af48a4df5eb051d309a9caceb"


def _republished(tmp_path: Path, monkeypatch, edit) -> Path:
    """A copy of the society catalogs with v1 edited and its edit published under v1's digest, so
    the loader's checks behind the digest are reached."""
    directory = _edited(tmp_path, edit)
    edited = load_catalog(directory / PUBLISHED.name, SCHEMAS[(AFFORDANCE_CATALOG, 1)])
    monkeypatch.setitem(society_catalogs.AFFORDANCE_DIGESTS, 1, catalog_digest([edited]))
    return directory


def test_a_published_version_edited_in_place_is_refused(tmp_path):
    """Editing a code in v1 would change what a replay of a stored society records."""

    def edit(entries, _document):
        entries["rest"]["drawn_reason"] = "sitting_for_a_bit"

    with pytest.raises(CatalogError, match="is published and stored societies record its codes"):
        load_purposeful_routine(_edited(tmp_path, edit))


def test_a_routine_offering_an_activity_no_published_entry_serves_is_refused(tmp_path, monkeypatch):
    def edit(entries, _document):
        entries["stand"]["routine_versions"] = ["3"]

    directory = _republished(tmp_path, monkeypatch, edit)
    with pytest.raises(CatalogError, match=r"purposeful routine v2 offers .* states"):
        load_purposeful_routine(directory)


def test_an_activity_a_need_prefers_states_why_it_is_needed(tmp_path, monkeypatch):
    def edit(entries, _document):
        entries["rest"]["needed_reason"] = "none"

    directory = _republished(tmp_path, monkeypatch, edit)
    with pytest.raises(
        CatalogError, match="rest is preferred at a need, and rest states no needed"
    ):
        load_purposeful_routine(directory)


def test_every_activity_at_an_object_states_its_nearest_reason(tmp_path):
    """The planner sends somebody to the nearest place under any routine when a goal policy names
    no preferred target, so a drawn routine's object activity needs it as a nearest one's does."""

    def edit(entries, _document):
        entries["visit"]["nearest_reason"] = "none"

    directory = _edited(tmp_path, edit)
    with pytest.raises(CatalogError, match="exactly an object activity states a nearest reason"):
        load_catalog(directory / PUBLISHED.name, SCHEMAS[(AFFORDANCE_CATALOG, 1)])


def test_two_published_versions_may_not_set_one_activity_differently(tmp_path, monkeypatch):
    kinds = [
        ActivityKind("stand", "open", (2,), "stopping_a_while", None, None, "stand_completed"),
        ActivityKind("stand", "pair", (3,), "stopping_a_while", None, None, "stand_completed"),
    ]
    monkeypatch.setattr(society_catalogs, "_published_activity_kinds", lambda _: tuple(kinds))
    with pytest.raises(CatalogError, match="two society-affordance versions set 'stand'"):
        _settings_by_kind(tmp_path)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda entries: entries.pop(), "no words for the activities"),
        (lambda entries: entries.append({**entries[0], "key": "fly"}), "words for 'fly'"),
        (lambda entries: entries[0].update(verb="none"), "exactly an activity at an object"),
    ],
    ids=["missing", "unrecorded", "page-words-off-an-object"],
)
def test_the_words_catalog_words_exactly_the_recorded_activities(tmp_path, edit, message):
    document = json.loads(ACTIVITY_WORDS_PATH.read_text(encoding="utf-8"))
    edit(document["entries"])
    edited = tmp_path / ACTIVITY_WORDS_PATH.name
    edited.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(WordsCatalogRefused, match=message):
        _activity_words(edited)


def test_a_perform_request_for_an_activity_the_routine_lacks_is_refused_by_name():
    document = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, document)
    with pytest.raises(UnknownAffordance) as refused:
        build_action_request(
            state,
            document,
            request_id=uuid.uuid5(VERSION, "fly"),
            requested_by=uuid.uuid5(VERSION, "actor"),
            subject_id=uuid.UUID(state["inhabitants"][0]["id"]),
            intent=ActionIntent("perform", "authored:bench:rest", "fly"),
        )
    assert refused.value.code == "unknown_affordance"


def _string_constants(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _objects() -> set[str]:
    return {kind.key for kind in ACTIVITY_WORDS.values() if kind.setting == "object"}


def _recorded() -> set[str]:
    kinds = _published_activity_kinds(ROUTINE_DIRECTORY)
    return {
        code
        for kind in kinds
        for code in (kind.drawn_reason, kind.needed_reason, kind.nearest_reason)
        if code is not None
    } | {kind.completed_outcome for kind in kinds}


def _said() -> set[str]:
    return {
        code
        for kind in ACTIVITY_WORDS.values()
        for code in (kind.heading_doing, kind.under_way_doing, kind.finished_doing)
    }


@pytest.mark.parametrize(
    ("module", "catalogued"),
    [
        (society_planner, lambda: _objects() | _recorded()),
        (inhabitant_words, lambda: _objects() | _said()),
        (action_routes, _objects),
    ],
    ids=["planner", "inhabitant-words", "action-route"],
)
def test_no_module_restates_what_the_catalog_says_of_an_activity(module, catalogued):
    """The special case this catalog replaced was a module spelling an object activity, the codes
    the planner records for a kind of activity or the words said of one."""
    assert _string_constants(module) & catalogued() == set()


def test_the_scan_sees_a_module_that_spells_an_activity(tmp_path):
    """Positive control: the scan above reads string constants, so a restated code is found."""
    planted = tmp_path / "planted.py"
    planted.write_text('REASON = "sitting_a_while"\n', encoding="utf-8")
    module = type("Planted", (), {"__file__": str(planted)})
    assert "sitting_a_while" in _string_constants(module)


@pytest.mark.postgres
def test_the_action_route_refuses_an_unknown_activity_by_name(runtime_world, control_api):
    world, api = runtime_world, control_api
    snapshot = create(world, "exulanica-society/v3")
    world["connection"].commit()
    api.client.app.state.society_input_authorizer = world["runtime"].authorize
    path = api.in_world(f"/world/versions/{world['binding'].version_id}/society/actions")
    target = next(
        target for target in runtime_helpers.initial(world)["targets"] if target["enabled"]
    )
    refused = api.post(
        path,
        {
            "idempotency_key": str(uuid.uuid4()),
            "base_tick": snapshot["current_tick"],
            "base_state_sha256": snapshot["state_sha256"],
            "subject_id": snapshot["state"]["inhabitants"][0]["id"],
            "intent": {"kind": "perform", "target_id": target["target_id"], "affordance": "fly"},
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "unknown_affordance"
