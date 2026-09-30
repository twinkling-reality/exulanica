"""A write to a world's look waits for another writer's hold a named while, then says busy.

Every preview, Apply, discard and rollback is one transaction that locks the world's style state
(``WorldStyleRepository._style_write`` in ``exulanica/world/repository.py``). It waits for another
writer's hold at most ``STYLE_WRITE_LOCK_WAIT_MS`` and is then refused as ``StyleWriteBusy`` with
nothing written, which the API answers as 409 ``busy``, rather than holding the request for as
long as the other hold lasts.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Final

import psycopg
import pytest
from exulanica.db.read_check import ConnectionNotIdle
from exulanica.world import StyleWriteBusy, WorldStyleRepository
from exulanica.world.repository import STYLE_WRITE_LOCK_WAIT_MS

from test_saved_world_entries_api import _create_entry
from test_selection_proposal_route import WORLD, proposal_api, reply
from test_world_objects_api import objects_api
from test_world_style_postgres import fixture_styles, proposal, topology

pytestmark = pytest.mark.postgres

__all__ = ["objects_api", "proposal_api"]


def _previews(repository, styles) -> int:
    row = repository.connection.execute(
        "select count(*) n from world_style_preview where workspace_id=%s and world_id=%s",
        (repository.workspace_id, styles.world_id),
    ).fetchone()
    return int(row["n"])


def test_a_style_write_waits_at_most_its_named_wait(repository, monkeypatch):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    seen: list[str] = []
    read = WorldStyleRepository._state

    def reading(self, **kwargs):
        seen.append(self.connection.execute("show lock_timeout").fetchone()["lock_timeout"])
        return read(self, **kwargs)

    monkeypatch.setattr(WorldStyleRepository, "_state", reading)
    styles.preview(proposal(initial, parameters={"vitality": 0.15}))

    # Every read of the state inside the write waits at most the named wait.
    assert seen and set(seen) == {f"{STYLE_WRITE_LOCK_WAIT_MS // 1000}s"}
    # Local to the write: the connection's own setting is back after it.
    assert repository.connection.execute("show lock_timeout").fetchone()["lock_timeout"] == "0"


def test_a_held_style_state_refuses_the_write_as_busy_and_writes_nothing(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    repository.connection.commit()
    before = _previews(repository, styles)
    search_path = repository.connection.execute("show search_path").fetchone()["search_path"]
    with psycopg.connect(repository.connection.info.dsn, autocommit=False) as other:
        other.execute(f"set search_path = {search_path}")
        other.execute(
            "select 1 from world_style_state where workspace_id=%s and world_id=%s for update",
            (repository.workspace_id, styles.world_id),
        )
        with pytest.raises(StyleWriteBusy, match="nothing was written"):
            styles.preview(proposal(initial, parameters={"vitality": 0.15}))
        other.rollback()
    assert _previews(repository, styles) == before
    # Positive control: with the other hold gone, the same write is made.
    styles.preview(proposal(initial, parameters={"vitality": 0.15}, proposal_id=uuid.uuid4()))
    assert _previews(repository, styles) == before + 1


def test_a_style_write_inside_an_open_transaction_is_refused_and_writes_nothing(repository):
    """Inside another transaction the write would be a savepoint, and the wait it sets would outlive
    it and cap every later wait of that transaction, the asset read lock's included."""
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    repository.connection.commit()
    before = _previews(repository, styles)
    with (
        repository.connection.transaction(),
        pytest.raises(ConnectionNotIdle, match="its own transaction"),
    ):
        styles.preview(proposal(initial, parameters={"vitality": 0.15}))
    assert _previews(repository, styles) == before
    # Positive control: from an idle connection, the same write is made.
    styles.preview(proposal(initial, parameters={"vitality": 0.15}))
    assert _previews(repository, styles) == before + 1


def test_the_route_answers_a_held_world_as_busy(repository, proposal_api):
    """What the page is told: 409 ``busy``, which it says in words, after the named wait."""
    proposal_api.script(reply({"kind": "appearance"}), reply(proposal_api.draft()))
    drawn = proposal_api.utter("softer horizon please").json()["proposal"]
    body = proposal_api.preview_body(drawn)
    repository.connection.commit()
    search_path = repository.connection.execute("show search_path").fetchone()["search_path"]
    with psycopg.connect(repository.connection.info.dsn, autocommit=False) as other:
        other.execute(f"set search_path = {search_path}")
        other.execute(
            "select 1 from world_style_state where workspace_id=%s and world_id=%s for update",
            (repository.workspace_id, WORLD),
        )
        held = proposal_api.post("/world/styles/previews", body)
        other.rollback()
    assert held.status_code == 409, held.text
    assert held.json()["code"] == "busy"
    # Positive control: the same request, the hold gone, is made.
    made = proposal_api.post("/world/styles/previews", {**body, "proposalId": str(uuid.uuid4())})
    assert made.status_code == 201, made.text


#: A statement that may wait for another transaction's hold.
_WAITS: Final = re.compile(r"for update|for share|pg_advisory_xact_lock|lock table", re.IGNORECASE)
_APP = Path(__file__).resolve().parents[1] / "web/packages/app/src"


def _page_request_deadline_ms() -> int:
    found = re.search(
        r"^const WORLD_STYLE_REQUEST_TIMEOUT_MS = ([0-9_]+);$",
        (_APP / "world-style-api.ts").read_text(),
        re.MULTILINE,
    )
    assert found is not None
    return int(found.group(1).replace("_", ""))


@pytest.mark.postgres
def test_every_wait_of_an_apply_on_a_saved_world_fits_in_the_page_s_request_deadline(
    objects_api, repository, monkeypatch
):
    """``lock_timeout`` bounds each wait, not the write: an Apply on a saved world waits for every
    lock it takes, each at most ``STYLE_WRITE_LOCK_WAIT_MS``. Counted on a real Apply through the
    route, their sum stays under the page's deadline, so the page hears the server's answer."""
    entry, _version, _style = _create_entry(objects_api, repository)
    current = objects_api.get(objects_api.in_world("/world/styles/current")).json()
    preview = objects_api.post(
        objects_api.in_world("/world/styles/previews"),
        {
            "proposal_id": str(uuid.uuid4()),
            "origin": "settings",
            "origin_reference": "appearance-panel",
            "scope": {"kind": "global"},
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
            "profile": {
                "profile_id": "origin-landscape",
                "profile_version": 1,
                "parameters": {"vitality": 0.25},
            },
        },
    )
    assert preview.status_code == 201, preview.text
    waits: list[str] = []
    execute = psycopg.Cursor.execute

    def counting(self, query, *args, **kwargs):
        text = query if isinstance(query, str) else str(query)
        if _WAITS.search(text):
            waits.append(text)
        return execute(self, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", counting)
    applied = objects_api.post(
        objects_api.in_world(f"/world/styles/previews/{preview.json()['preview_id']}/apply"),
        {
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
            "saved_entry": {
                "entry_id": entry["entry_id"],
                "base_revision": entry["revision"],
                "authored_state_sha256": entry["authored_state_sha256"],
                "authored_edit_seq": entry["authored_edit_seq"],
                "style_version_id": entry["style_version_id"],
            },
        },
    )
    monkeypatch.undo()
    assert applied.status_code == 200, applied.text
    assert waits, "the positive control: an Apply takes the world's style lock"
    assert len(waits) * STYLE_WRITE_LOCK_WAIT_MS < _page_request_deadline_ms(), waits
