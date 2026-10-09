"""The hands request's migration over a database that already holds a person's direct requests.

A schema of this test's own is migrated with every migration below the hands request's (found by
its title, so renumbering it at landing changes nothing here) and given a saved world on a host
that offers societies of things: a well, a knight, a sword and a gate placed, a society of things
over them, and two of the owner's direct requests of the kinds every stored request is, go_to and
perform, each consumed by a minute. Then the migration runs on it as deployed, and every migration
after it, so a request made then binds as the code that composed the society writes it (a society of
things composed today runs hands v2, which a later migration binds). What is held:

*   every stored request row is byte for byte what it was, and the society replays verified;
*   0060's four request checks are gone and the migration's two stand in their place, valid over
    the stored rows;
*   a new request of each profile binds and is consumed: a go_to, and a hands act (pick_up);
*   the society replays verified again, its new minute included.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.migrations import migrations
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.assets import seed_reviewed_assets
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID, create_starter_authorities
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

import pg_harness
from society_seed_support import choose_society_seed
from tests_support_api import EVERY_PERMISSION, scratch_database

pytestmark = pytest.mark.postgres

TITLE = "_a_person_asks_a_being_for_a_hands_act.sql"
TOKEN = "hands-request-migration-owner-token-long-enough"
OWNER = {"Authorization": f"Bearer {TOKEN}"}
V7 = "exulanica-society/v7"
SEED = "d" * 64
#: 0060's four inline checks, by the names PostgreSQL gave them (read from a database at 0167).
OLD_CHECKS = {
    "world_society_action_request_document_check1",
    "world_society_action_request_document_check2",
    "world_society_action_request_check6",
    "world_society_action_request_document_check6",
}
NEW_CHECKS = {
    "world_society_action_request_profile_check",
    "world_society_action_request_intent_check",
}
THINGS = (
    ("gate", "gate", 1, 0, 9_000),
    ("knight", "knight", 1, 3_000, 3_000),
    ("sword", "sword", 2, 2_400, 2_600),
    ("well", "well", 2, -4_000, 2_000),
    # A second place to go, for the request made after the migration while the first is held.
    ("well-2", "well", 2, 8_000, -2_000),
)


def _checks(admin) -> set[str]:
    return {
        row[0]
        for row in admin.execute(
            "select conname from pg_constraint "
            "where conrelid='world_society_action_request'::regclass and contype='c'"
        )
    }


def _stored(admin) -> list[tuple]:
    return admin.execute(
        "select action_seq, request_id, document_sha256, document::text "
        "from world_society_action_request order by workspace_id, society_id, action_seq"
    ).fetchall()


class _World:
    """The saved world through the application, as its owner."""

    def __init__(self, client: TestClient, world_id: str, version_id: uuid.UUID) -> None:
        self.client = client
        self.scope = {"world_id": world_id}
        self.version = f"/world/versions/{version_id}"
        self.society = self.version + "/society"

    def read(self, path: str, **params):
        answered = self.client.get(path, headers=OWNER, params={**self.scope, **params})
        assert answered.status_code == 200, answered.text
        return answered.json()

    def post(self, path: str, body, status=(200, 201)):
        answered = self.client.post(path, headers=OWNER, params=self.scope, json=body)
        assert answered.status_code in status, answered.text
        return answered.json()

    def place(self, placed_id: str, kind: str, version: int, x_mm: int, z_mm: int) -> None:
        self.post(
            self.version + "/things",
            {
                "base_state_sha256": self.read(self.version)["state_sha256"],
                "thing_id": placed_id,
                "kind": {"kind": kind, "version": version},
                "region_id": AUTHORED_STARTER_REGION_ID,
                "pose": {"x_mm": x_mm, "y_mm": 0, "z_mm": z_mm, "yaw_microradians": 0},
                "origin_role": "fictional",
            },
            status=(201,),
        )

    def ask(self, subject: str, intent: dict, waits=("inhabitant_action_in_progress",)) -> dict:
        """A direct request at the current minute; while the route answers one of ``waits`` (the
        being in the middle of a walk, say), a minute at a time until it is taken (at most
        twenty)."""
        for _minutes in range(20):
            held = self.read(self.society)
            answered = self.client.post(
                self.society + "/actions",
                headers=OWNER,
                params=self.scope,
                json={
                    "idempotency_key": str(uuid.uuid4()),
                    "base_tick": held["current_tick"],
                    "base_state_sha256": held["state_sha256"],
                    "subject_id": subject,
                    "intent": intent,
                },
            )
            if answered.status_code == 200:
                return answered.json()
            assert answered.json().get("detail") in waits, answered.text
            self.step()
        raise AssertionError(f"{subject} could not be asked in twenty minutes")

    def step(self) -> dict:
        held = self.read(self.society)
        return self.post(
            self.society + "/steps",
            {"base_tick": held["current_tick"], "base_state_sha256": held["state_sha256"]},
            status=(200,),
        )

    def replayed(self) -> bool:
        return self.read(self.society + "/replay")["replay_verified"]


def test_the_hands_request_migration_holds_every_stored_request_and_binds_both_profiles(
    monkeypatch, tmp_path
):
    everything = list(migrations())
    [hands] = [m for m in everything if m.path.name.endswith(TITLE)]
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    world_id = f"world:authored:{uuid.uuid4()}"
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness,
            "migrations",
            lambda: iter(m for m in everything if m.version < hands.version),
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            scratch = admin.execute("select current_schema()").fetchone()[0]
            admin.commit()
            base = env_get("TEST_DATABASE_URL")
            assert base is not None
            database = Database(url=make_conninfo(base, options=f"-csearch_path={scratch},public"))
            with database.session(workspace) as connection:
                _snapshot, _authority, version_id = create_starter_authorities(
                    connection,
                    workspace_id=workspace,
                    actor=actor,
                    title="A world of my own",
                    world_id=world_id,
                )
                connection.execute(
                    "insert into place(workspace_id,place_id) values(%s,%s)",
                    (workspace, uuid.uuid4()),
                )
            monkeypatch.setenv(
                "EXULANICA_API_TOKENS",
                json.dumps(
                    {
                        TOKEN: {
                            "workspace_id": str(workspace),
                            "actor": str(actor),
                            "permissions": EVERY_PERMISSION,
                        }
                    }
                ),
            )
            store = LocalContentAddressedStore(tmp_path / "blobs")
            seed_reviewed_assets(store)
            served = scratch_database(scratch)
            app = create_app(
                Services(
                    database=served,
                    readonly_database=served,
                    store=store,
                    tokens=load_token_directory(),
                    executor_shares_the_write_role=True,
                    model_client=None,
                    society_runtime=SocietyRuntime(
                        store=store,
                        authored_bindings=[],
                        reviewed_affordances=reviewed_affordance_registry(),
                    ),
                ),
                verify=False,
            )
            app.state.services = dataclasses.replace(app.state.services, societies_of_things=True)
            choose_society_seed(app, SEED)
            with TestClient(app) as client:
                world = _World(client, world_id, version_id)
                for placed_id, kind, version, x_mm, z_mm in THINGS:
                    world.place(placed_id, kind, version, x_mm, z_mm)
                world.post(world.society, {"region_id": AUTHORED_STARTER_REGION_ID, "profile": V7})
                state = world.read(world.society)["state"]
                knight = next(p for p in state["inhabitants"] if p["placed_id"] == "knight")
                villager, other = [p for p in state["inhabitants"] if p["came_by"] == "populated"][
                    :2
                ]
                target = next(
                    t
                    for t in world.read(world.society, places="true")["places"]["targets"]
                    if t["enabled"]
                )
                # The owner's direct requests as the code before the migration records them, a
                # go_to and a perform, both at the first minute, which consumes them.
                world.ask(knight["id"], {"kind": "go_to", "target_id": target["target_id"]})
                world.ask(
                    villager["id"],
                    {
                        "kind": "perform",
                        "target_id": target["target_id"],
                        "affordance": target["affordance"],
                    },
                )
                world.step()
                before = _stored(admin)
                assert len(before) == 2
                assert _checks(admin) >= OLD_CHECKS and not _checks(admin) & NEW_CHECKS
                assert world.replayed() is True

                admin.execute(hands.sql)
                admin.commit()

                assert _stored(admin) == before
                assert not _checks(admin) & OLD_CHECKS and _checks(admin) >= NEW_CHECKS
                assert admin.execute(
                    "select bool_and(convalidated) from pg_constraint where conname = any(%s)",
                    (sorted(NEW_CHECKS),),
                ).fetchone() == (True,)
                assert world.replayed() is True
                for later in everything:
                    if later.version > hands.version:
                        admin.execute(later.sql)
                admin.commit()
                # A new request of each profile binds and is consumed.
                state = world.read(world.society)["state"]
                sword = next(t for t in state["things"] if t["placed_id"] == "sword")
                knight = next(p for p in state["inhabitants"] if p["id"] == knight["id"])
                # The knight may stand where the sword is out of its approach, or another being
                # may hold the one place within reach of it: asked again a minute later then.
                asked = world.ask(
                    knight["id"],
                    {"kind": "hands", "ability": "pick_up", "thing_id": sword["id"]},
                    waits=("inhabitant_action_in_progress", "act_not_offered"),
                )
                assert asked["request"]["profile"] == "exulanica.society-action-request/v2"
                # Another villager than the one staying at the well, which a request to go
                # where it already is would only begin again (inhabitant_already_there).
                elsewhere = next(
                    t
                    for t in world.read(world.society, places="true")["places"]["targets"]
                    if t["enabled"] and t["target_id"] != target["target_id"]
                )
                again = world.ask(
                    other["id"],
                    {"kind": "go_to", "target_id": elsewhere["target_id"]},
                    waits=("inhabitant_action_in_progress", "destination_full"),
                )
                assert again["request"]["profile"] == "exulanica.society-action-request/v1"
                world.step()
                events = world.read(world.society + "/events", limit=256)["events"]
                consumed = [e for e in events if e["event_kind"] == "user_action_requested"]
                assert len(consumed) == 4, [e["document"].get("reason") for e in consumed]
                assert world.replayed() is True
