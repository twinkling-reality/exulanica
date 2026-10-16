"""A placing's preview gives the verdict the placing then gives, and writes nothing
(``POST .../things/preview``).

On the farm of ``tests/test_thing_landing_postgres.py`` (the fixture kind under a fixed identity,
its duck pond and barn read from its own records), through the routes as a deployment serves them:

*   a well placed in the pond, inside the barn, past the edge or in the air: the preview is
    blocked with the placing's code, sentence and ``where``, and neither writes anything;
*   a well on open ground: the preview is ready, says where it stood was checked, and its ``after``
    is the document the placing then records;
*   a creature made from words: ready, its spot unchecked, as the placing checks nothing there;
*   the placing's own checks: an id already placed, a stale base, a digest the workspace holds no
    kind at and a version holding as many things as it may are blocked by the codes the placing
    answers.
"""

from __future__ import annotations

from typing import Any

import pytest
from exulanica.world import object_repository
from exulanica.world.thing_store import ThingStore

from test_society_made_kinds import canary_creature
from test_society_made_world import made as imported_made  # noqa: F401
from test_thing_landing_postgres import (
    WELL,
    _farm,
    _open_ground,
    _place,
    _pond,
    _pose,
    _recorded_after,
    _refused_cases,
    _root,
    _scope,
    _the_same_farm_on_every_run,  # noqa: F401
    _version,
)

pytestmark = pytest.mark.postgres

CASES = ["into the duck pond", "inside the barn", "past the farm's edge", "a metre into the air"]


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


def _preview(  # type: ignore[no-untyped-def]
    api, entry: dict, thing_id: str, kind: dict, pose: dict, base: str | None = None
):
    return api.post(
        _root(entry) + "/things/preview" + _scope(entry),
        {
            "base_state_sha256": base or _version(api, entry)["state_sha256"],
            "thing_id": thing_id,
            "kind": kind,
            "region_id": "region:generated",
            "pose": pose,
            "origin_role": "fictional",
        },
    )


def _verdict(response) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.mark.parametrize("case", CASES)
def test_a_refused_placing_s_preview_names_the_same_refusal_and_neither_writes(made, case):
    api = made
    entry, records = _farm(api)
    before = _version(api, entry)
    pose, _expected = _refused_cases(entry, records)[case]

    verdict = _verdict(_preview(api, entry, "well", WELL, pose))
    assert _version(api, entry) == before
    placed = _place(api, entry, "well", WELL, pose)

    assert placed.status_code == 422, placed.text
    assert verdict["availability"] == "blocked"
    assert verdict["blocked_reason"] == placed.json()["code"]
    assert verdict["blocked_detail"] == placed.json()["detail"]
    assert verdict["landing"] == {"checked": True, "where": placed.json()["where"]}
    assert verdict["would_change"]["kind"] == "add_thing"
    assert verdict["would_change"]["after"] is None
    assert _version(api, entry) == before


def test_a_well_on_open_ground_is_placed_as_its_preview_said(made):
    api = made
    entry, _records = _farm(api)
    before = _version(api, entry)
    pose = _pose(*_open_ground(entry))

    verdict = _verdict(_preview(api, entry, "well", WELL, pose))
    assert (verdict["availability"], verdict["landing"]) == ("ready", {"checked": True})
    assert verdict["would_change"]["subject_id"] == "well"
    assert verdict["would_change"]["before"] is None
    assert _version(api, entry) == before

    placed = _place(api, entry, "well", WELL, pose)
    assert placed.status_code == 201, placed.text
    assert placed.json()["edits"][-1]["kind"] == "add_thing"
    assert verdict["would_change"]["after"] == _recorded_after(api, placed.json()["edits"][-1])


def test_a_creature_made_from_words_previews_ready_where_its_maker_puts_it_unchecked(made):
    api = made
    entry, records = _farm(api)
    creature = canary_creature("crocodile", hands=True)
    with api.database.session(api.repository.workspace_id) as session:
        ThingStore(session, api.repository.workspace_id, api.store).keep_creature(
            creature, created_by=api.actor
        )
    kind = {"source": "workspace", "sha256": creature.kind.sha256}

    verdict = _verdict(_preview(api, entry, "creature:0000aaaa", kind, _pose(*_pond(records))))

    assert (verdict["availability"], verdict["landing"]) == ("ready", {"checked": False})


def test_the_placing_s_own_checks_block_its_preview_by_the_placing_s_codes(made, monkeypatch):
    api = made
    entry, _records = _farm(api)
    x, z = _open_ground(entry)
    placed = _place(api, entry, "well", WELL, _pose(x, z))
    assert placed.status_code == 201, placed.text
    elsewhere = _pose(x + 4_000, z)

    taken = _verdict(_preview(api, entry, "well", WELL, elsewhere))
    assert taken["blocked_reason"] == "invalid_object_state"
    assert _place(api, entry, "well", WELL, elsewhere).json()["code"] == "invalid_object_state"

    stale = _verdict(_preview(api, entry, "second-well", WELL, elsewhere, "0" * 64))
    assert stale["blocked_reason"] == "stale_object_base"

    unknown = {"source": "workspace", "sha256": "1" * 64}
    unheld = _verdict(_preview(api, entry, "creature:0000bbbb", unknown, elsewhere))
    assert unheld["blocked_reason"] == "invalid_thing_placement"
    assert _place(api, entry, "creature:0000bbbb", unknown, elsewhere).json()["code"] == (
        "invalid_thing_placement"
    )

    monkeypatch.setattr(object_repository, "PLACED_THINGS_MAXIMUM", 1)
    full = _verdict(_preview(api, entry, "second-well", WELL, elsewhere))
    assert full["blocked_reason"] == "thing_limit_reached"
    refused = _place(api, entry, "second-well", WELL, elsewhere)
    assert (refused.status_code, refused.json()["code"]) == (409, "thing_limit_reached")
