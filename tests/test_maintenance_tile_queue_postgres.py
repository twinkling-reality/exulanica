"""Maintenance's tile queue age counts a changed version's bakes as well as a town's public ones.

The tile worker claims both kinds (``exulanica/ingest/generated_tiles.py``), so a version bake
left waiting is a tile queue that is late. Against PostgreSQL, on a small town made through the
API whose version's change queued its bakes (the fixture of ``test_version_tiles_postgres``).
"""

from __future__ import annotations

import datetime

import pytest
from exulanica.orchestration.installation.maintenance import QUEUE_QUERIES

from test_society_made_world import made as imported_made  # noqa: F401
from test_version_tiles_postgres import _town  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


def test_the_tile_queue_age_counts_a_version_s_waiting_bakes(town):
    assert town.queue()
    # The version's bakes waited ten minutes; the town's public bakes, if any wait, are newer.
    assert town.owner_rows(
        "update job set run_after = now() - interval '10 minutes' "
        "where kind = 'bake_version_tile' and state = 'queued' returning job_id"
    )
    [now] = town.owner_rows("select now() as at")
    [queue] = town.owner_rows(QUEUE_QUERIES["generated_tiles"])
    assert queue["oldest"] is not None
    assert now["at"] - queue["oldest"] >= datetime.timedelta(minutes=9)
