"""A deployment that cannot make a world says so before anyone asks it to, and refuses before work.

The judge deployment's database role may read every world and register none (``world_identity`` is
off its allowlist). Every route that makes a world probes that one grant first
(:func:`exulanica.world.worlds.may_register_worlds`), so the creation read lists each creation as
unavailable ``worlds_read_only`` and each creation route answers 403 ``worlds_read_only`` before a
town is generated or a starter composed. The positive control is the creation read of a role that
may register worlds, which lists them available
(``test_what_a_workspace_may_make_follows_what_it_holds`` in ``test_world_capabilities_api.py``);
a probe that always passed would leave the judge with the generic ``database_privilege_refused``
after the work, as ``tests/test_database_privilege_refusal.py`` shows.
"""

from __future__ import annotations

import pytest
from exulanica.orchestration.judge_seed import JUDGE_WRITE_TABLES
from exulanica.world.worlds import may_register_worlds

from test_database_privilege_refusal import judge_api as judge_api

pytestmark = pytest.mark.postgres


def _creation(judge_api):
    response = judge_api.get("/worlds/capabilities")
    assert response.status_code == 200, response.text
    return {row["kind"]: row["create"] for row in response.json()["kinds"]}


def test_the_probe_reads_the_roles_own_grant(judge_api):
    assert "world_identity" not in JUDGE_WRITE_TABLES
    with judge_api.client.app.state.services.database.unscoped() as connection:
        assert may_register_worlds(connection) is False


def test_the_creation_read_says_the_judge_makes_no_world(judge_api):
    creation = _creation(judge_api)
    for kind in ("authored-starter", "generated"):
        assert (creation[kind]["state"], creation[kind]["code"]) == (
            "unavailable",
            "worlds_read_only",
        ), kind


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/world-entries/starter", {"title": "My world"}),
        ("/worlds/generated", {"recipe": "small_town", "title": "Our town", "values": {}}),
    ],
)
def test_each_creation_route_refuses_before_any_work(judge_api, path, body):
    response = judge_api.post(path, body)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "worlds_read_only"
    listed = judge_api.get("/world-entries")
    assert listed.status_code == 200 and listed.json() == []
