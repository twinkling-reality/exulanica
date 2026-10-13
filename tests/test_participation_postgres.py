"""Human invitation lifecycle and default-deny participant reads on a private database."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from exulanica.api.participation import ParticipationRuntime
from exulanica.api.society_making import SocietyHooks
from exulanica.participation.contracts import notice_reference
from exulanica.selection.validation import Session
from exulanica.things.kinds import shipped_thing_kinds

from test_site_society_of_things_postgres import (  # noqa: F401
    V7,
    _made_alias,
    _place,
    _site,
    _the_same_site_on_every_run,
    imported_made,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def invited_world(made):
    entry, route, _ = _site(made, "farm", "fixture_farm", "small_farm")
    kind = next(k for k in shipped_thing_kinds().values() if k.kind == "knight")
    east, _, south = entry["generated_site"]["arrival_mm"]
    _place(made, entry, "invitation-knight", kind.reference(), east, south)
    result = made.post(route, {"region_id": "region:generated", "profile": V7})
    assert result.status_code in (200, 201), result.text
    owner = Session(made.repository.workspace_id, made.actor)
    visitor = Session(uuid.uuid4(), uuid.uuid4())
    stranger = Session(uuid.uuid4(), uuid.uuid4())
    sessions = {"owner": owner, "visitor": visitor, "stranger": stranger}

    class Accounts:
        def browser_session(self, request):
            name = request.headers.get("x-test-user", "owner")
            return SimpleNamespace(
                session=sessions[name], role="owner" if name == "owner" else "guest", creator=False
            )

        def owned_workspace_active(self, workspace):
            return workspace == owner.workspace_id

    state = made.client.app.state
    state.services = dataclasses.replace(state.services, accounts=Accounts())
    runtime = ParticipationRuntime(state.services, SocietyHooks.of_app(made.client.app))
    runtime.verify()
    state.participation = runtime
    return made, entry, sessions


def _issue(api, entry):
    response = api.client.post(
        "/world/invitations",
        params={"world_id": entry["world_id"]},
        json={
            "idempotency_key": str(uuid.uuid4()),
            "version_id": entry["authored_version_id"],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "world_words": "A garden to observe",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _redeem(api, invitation, user="visitor"):
    return api.client.post(
        "/participation/redeem",
        headers={"x-test-user": user},
        json={
            "invitation": invitation["invitation"],
            "notice_sha256": notice_reference()["sha256"],
        },
    )


def test_owner_invites_one_browser_and_revoke_ends_every_read(invited_world):
    api, entry, _ = invited_world
    invite = _issue(api, entry)
    response = _redeem(api, invite)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "bound"
    root = "/participation/" + invite["grant_id"]
    headers = {"x-test-user": "visitor"}
    world = api.client.get(root + "/world", headers=headers)
    assert world.status_code == 200, world.text
    assert world.json()["world_id"] == entry["world_id"]
    society = api.client.get(root + "/society", headers=headers)
    assert society.status_code == 200, society.text
    assert society.json()["inhabitants"]
    assert _redeem(api, invite, "stranger").status_code == 404
    assert api.client.get(root, headers={"x-test-user": "stranger"}).status_code == 404
    revoked = api.client.post("/world/invitations/" + invite["grant_id"] + "/revoke")
    assert revoked.status_code == 200, revoked.text
    ended = api.client.get(root + "/society", headers=headers)
    unknown = api.client.get("/participation/" + str(uuid.uuid4()) + "/society", headers=headers)
    assert ended.status_code == unknown.status_code == 404
    assert ended.json() == unknown.json()


def test_browser_floor_rejects_bearers_guests_and_disabled_composition_before_body(invited_world):
    from personal_world_support import OWNER_TOKEN

    api, _, _ = invited_world
    route = "/world/invitations"
    for headers in ({"Authorization": "Bearer " + OWNER_TOKEN}, {"x-test-user": "visitor"}):
        response = api.client.post(route, content=b"not json", headers=headers)
        assert response.status_code == 403, response.text
    runtime = api.client.app.state.participation
    api.client.app.state.participation = None
    try:
        response = api.client.post(route, content=b"not json")
        assert response.status_code == 403, response.text
        assert api.client.get("/participation/notice").status_code == 403
    finally:
        api.client.app.state.participation = runtime


def test_invitation_is_one_time_secret_with_exact_retry_and_closed_input(invited_world):
    api, entry, _ = invited_world
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "version_id": entry["authored_version_id"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "world_words": "Garden",
    }
    params = {"world_id": entry["world_id"]}
    first = api.client.post("/world/invitations", params=params, json=body)
    assert first.status_code == 200, first.text
    assert "no-store" in first.headers["cache-control"]
    retry = api.client.post("/world/invitations", params=params, json=body)
    assert retry.status_code == 200 and retry.json()["invitation"] is None
    assert retry.json()["grant_id"] == first.json()["grant_id"]
    changed = api.client.post(
        "/world/invitations", params=params, json=body | {"world_words": "Different"}
    )
    assert changed.status_code == 409
    for extra in (
        {"may_act": True},
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"world_words": "bad\nline"},
    ):
        response = api.client.post(
            "/world/invitations",
            params=params,
            json=body | {"idempotency_key": str(uuid.uuid4())} | extra,
        )
        assert response.status_code == 422, response.text
    with api.database.unscoped() as connection:
        stored = connection.execute(
            "select secret_sha256 from world_grant_entry where grant_id=%s",
            (first.json()["grant_id"],),
        ).fetchone()["secret_sha256"]
    assert stored != first.json()["invitation"] and len(stored) == 64


def test_leave_removes_the_binding_and_entry_even_when_sources_stop_serving(
    invited_world, monkeypatch
):
    from exulanica.participation.repository import ParticipationRefused

    api, entry, sessions = invited_world
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    root = "/participation/" + invite["grant_id"]
    headers = {"x-test-user": "visitor"}
    monkeypatch.setattr(
        ParticipationRuntime, "eligible", lambda *_: (_ for _ in ()).throw(ParticipationRefused())
    )
    assert api.client.get(root + "/world", headers=headers).status_code == 404
    assert api.client.post(root + "/leave", headers=headers).status_code == 204
    with api.database.session(sessions["owner"].workspace_id) as connection:
        for table in ("world_grant_principal", "world_grant_entry"):
            assert (
                connection.execute(
                    f"select 1 from {table} where grant_id=%s", (invite["grant_id"],)
                ).fetchone()
                is None
            )
        assert connection.execute(
            "select 1 from world_grant_departure where grant_id=%s", (invite["grant_id"],)
        ).fetchone()
    assert api.client.get(root, headers=headers).status_code == 404
    assert _redeem(api, invite).status_code == 404


def test_two_accounts_racing_one_invitation_bind_exactly_one(invited_world):
    from concurrent.futures import ThreadPoolExecutor

    api, entry, sessions = invited_world
    invite = _issue(api, entry)
    runtime = api.client.app.state.participation
    from exulanica.participation.repository import ParticipationRefused

    def try_redeem(name):
        try:
            runtime.redeem(sessions[name], invite["invitation"], notice_reference()["sha256"])
            return name
        except ParticipationRefused:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = [name for name in executor.map(try_redeem, ("visitor", "stranger")) if name]
    assert len(winners) == 1
    assert runtime.open(uuid.UUID(invite["grant_id"]), sessions[winners[0]].actor)


def test_restricted_role_has_no_private_tables_writes_or_unbound_rows(invited_world):
    import psycopg
    from exulanica.db.participant_role import assert_participant_role, participant_connection

    api, entry, sessions = invited_world
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    scope = api.client.app.state.participation.open(
        uuid.UUID(invite["grant_id"]), sessions["visitor"].actor
    )

    def scoped(**changes):
        return participant_connection(
            api.database,
            workspace_id=changes.get("workspace", scope.workspace_id),
            grant_id=changes.get("grant", scope.grant_id),
            principal_sha256=changes.get("principal", scope.principal_sha256),
        )

    with api.database.unscoped() as connection:
        assert_participant_role(connection)
    with scoped() as connection:
        assert (
            connection.execute("select world_id from participant_world").fetchone()["world_id"]
            == entry["world_id"]
        )
        state = connection.execute("select state from participant_society").fetchone()["state"]
        assert set(state) == {"inhabitants"}
        assert all(
            set(person) == {"id", "kind", "location", "position_mm", "motion_path_mm"}
            for person in state["inhabitants"]
        )
    for changes in (
        {"workspace": sessions["stranger"].workspace_id},
        {"grant": uuid.uuid4()},
        {"principal": "0" * 64},
    ):
        with scoped(**changes) as connection:
            assert connection.execute("select * from participant_world").fetchall() == []
            assert connection.execute("select * from participant_society").fetchall() == []
    for statement in (
        "select * from world_society",
        "select * from world_grant_principal",
        "update world_grant_principal set principal_sha256='changed'",
    ):
        with (
            pytest.raises(
                (psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)
            ),
            scoped() as connection,
        ):
            connection.execute(statement)


def test_refusal_limit_is_account_local_and_not_bypassable_with_concurrent_attempts(invited_world):
    from concurrent.futures import ThreadPoolExecutor

    from exulanica.participation.repository import (
        REFUSALS_PER_MINUTE,
        ParticipationRefused,
        RedemptionLimited,
    )

    api, _, sessions = invited_world
    runtime = api.client.app.state.participation

    def attempt(_):
        try:
            runtime.redeem(sessions["visitor"], "unknown", notice_reference()["sha256"])
        except RedemptionLimited:
            return 429
        except ParticipationRefused:
            return 404

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(REFUSALS_PER_MINUTE + 4)))
    assert results.count(404) == REFUSALS_PER_MINUTE
    assert results.count(429) == 4
    with pytest.raises(ParticipationRefused):
        runtime.redeem(sessions["stranger"], "unknown", notice_reference()["sha256"])


@pytest.mark.parametrize("scope", ["world", "workspace"])
def test_lifecycle_erases_invitation_children_before_world_identity(invited_world, scope):
    api, entry, sessions = invited_world
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    workspace = sessions["owner"].workspace_id
    with api.database.session(workspace) as connection:
        if scope == "workspace":
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'workspace',%s,'erase')",
                (workspace, sessions["owner"].actor),
            )
        else:
            from exulanica.world.world_erasure import erase_world

            erase_world(connection, workspace, entry["world_id"], erased_by=sessions["owner"].actor)
    with api.database.session(workspace) as connection:
        for table in (
            "world_grant",
            "world_grant_revision",
            "world_grant_principal",
            "world_grant_entry",
            "world_grant_revocation",
            "world_grant_departure",
        ):
            assert (
                connection.execute(
                    f"select 1 from {table} where workspace_id=%s", (workspace,)
                ).fetchone()
                is None
            )
    assert (
        api.client.get(
            "/participation/" + invite["grant_id"], headers={"x-test-user": "visitor"}
        ).status_code
        == 404
    )


def test_world_tile_delivery_rechecks_revocation_after_store_read(
    invited_world, tmp_path, monkeypatch
):
    from exulanica.participation.repository import InvitationRepository, ParticipationRefused
    from exulanica.store.namespaces import tile_store
    from exulanica.world import saved_entries
    from exulanica.world.baked_tiles import BakedTileRepository

    from test_generated_worlds import _baker, _town

    api, entry, sessions = invited_world
    monkeypatch.setattr(
        saved_entries,
        "new_world_id",
        lambda kind: "world:generated:00000000-0000-4000-8000-00000000f002",
    )
    entry = _town(api, "Observe a town")
    east, _, south = entry["generated_ground"]["arrival_mm"]
    kind = next(k for k in shipped_thing_kinds().values() if k.kind == "knight")
    _place(api, entry, "town-knight", kind.reference(), east, south)
    result = api.post(
        f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}",
        {"region_id": "region:generated", "profile": V7},
    )
    assert result.status_code in (200, 201), result.text
    store = tile_store(tmp_path / "tiles")
    runtime = dataclasses.replace(
        api.client.app.state.participation,
        services=dataclasses.replace(api.client.app.state.services, tiles=store),
    )
    api.client.app.state.participation = runtime
    outcomes = _baker(api, store, tmp_path, monkeypatch).drain([sessions["owner"].workspace_id])
    assert outcomes and all(outcome.status == "baked" for outcome in outcomes)
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    scope = runtime.open(uuid.UUID(invite["grant_id"]), sessions["visitor"].actor)
    tile = runtime.world(scope)["tiles"][0]
    tile_id = uuid.UUID(tile["baked_tile_id"])
    data, media = runtime.tile(scope, tile_id)
    assert data and media == "application/vnd.exulanica.owd"
    with pytest.raises(ParticipationRefused):
        runtime.tile(scope, uuid.uuid4())
    original = BakedTileRepository.serve_to_its_world

    def revoke_during_read(repository, identity):
        served = original(repository, identity)
        with api.database.session(scope.workspace_id) as connection:
            InvitationRepository(connection, scope.workspace_id).revoke(
                scope.grant_id, sessions["owner"].actor
            )
        return served

    monkeypatch.setattr(BakedTileRepository, "serve_to_its_world", revoke_during_read)
    with pytest.raises(ParticipationRefused):
        runtime.tile(scope, tile_id)


def test_carried_departure_removes_a_restored_binding_and_seal_refuses_new_withdrawals(
    invited_world,
):
    import psycopg
    from exulanica.deletion.withdrawals import Carried, read_withdrawals, reapply
    from exulanica.orchestration.restore import WRITERS
    from exulanica.participation.repository import InvitationRepository

    api, entry, sessions = invited_world
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    workspace = sessions["owner"].workspace_id
    admin = api.repository.connection
    # Model the older backup within one rolled-back transaction, using the actual carry writer.
    with admin.transaction(force_rollback=True):
        admin.execute("select set_config('exulanica.workspace_id',%s,true)", (str(workspace),))
        admin.execute(
            "insert into restore_control(checkpoint_id,checkpoint_sha256,state,restore_id) "
            "values(%s,%s,'replaying',%s)",
            (uuid.uuid4(), "a" * 64, uuid.uuid4()),
        )
        carried = Carried(
            "world_grant_departure",
            {
                "workspace_id": str(workspace),
                "grant_id": invite["grant_id"],
                "tombstone_id": str(uuid.uuid4()),
                "departed_at": datetime.now(UTC).isoformat(),
            },
        )
        assert reapply(admin, carried, WRITERS) == "carried"
        assert not admin.execute(
            "select 1 from world_grant_principal where grant_id=%s", (invite["grant_id"],)
        ).fetchone()
        assert not admin.execute(
            "select 1 from world_grant_entry where grant_id=%s", (invite["grant_id"],)
        ).fetchone()
        assert any(row.kind == "world_grant_departure" for row in read_withdrawals(admin))
    with admin.transaction(force_rollback=True):
        admin.execute("select set_config('exulanica.workspace_id',%s,true)", (str(workspace),))
        admin.execute(
            "insert into restore_control(checkpoint_id,checkpoint_sha256,state) "
            "values(%s,%s,'sealed')",
            (uuid.uuid4(), "b" * 64),
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            InvitationRepository(admin, workspace).revoke(
                uuid.UUID(invite["grant_id"]), sessions["owner"].actor
            )
    with admin.transaction(force_rollback=True):
        # A production backup set omits entries: a restored principal alone grants nothing.
        from exulanica.orchestration.installation.backup_set import EPHEMERAL_TABLES

        assert "world_grant_entry" in EPHEMERAL_TABLES
        admin.execute("select set_config('exulanica.workspace_id',%s,true)", (str(workspace),))
        admin.execute("set local role exulanica_definer")
        admin.execute("delete from world_grant_entry where grant_id=%s", (invite["grant_id"],))
        repository = InvitationRepository(admin, workspace)
        assert repository.state(repository.row(uuid.UUID(invite["grant_id"]))) == "void"


def test_prune_removes_only_ended_bindings_after_one_day_and_preserves_revocations(invited_world):
    from exulanica.canonical import sha256_of_canonical
    from exulanica.participation.contracts import revision_document
    from exulanica.participation.identity import principal_sha256
    from exulanica.participation.repository import InvitationRepository
    from psycopg.types.json import Jsonb

    api, entry, sessions = invited_world
    workspace, actor = sessions["owner"].workspace_id, sessions["visitor"].actor
    now = datetime.now(UTC)
    ids = {}
    with api.database.session(workspace) as connection:
        for name, expiry, revoked, bound in (
            ("expired", now - timedelta(days=2), None, True),
            ("revoked", now + timedelta(days=2), now - timedelta(days=2), True),
            ("recent", now - timedelta(hours=1), None, True),
            ("active", now + timedelta(days=2), None, True),
            ("unused", now - timedelta(days=2), None, False),
        ):
            grant = ids[name] = uuid.uuid4()
            document = revision_document(
                grant, uuid.UUID(entry["authored_version_id"]), expiry, "Garden"
            )
            connection.execute(
                "insert into world_grant(workspace_id,grant_id,world_id,issued_by) "
                "values(%s,%s,%s,%s)",
                (workspace, grant, entry["world_id"], sessions["owner"].actor),
            )
            connection.execute(
                "insert into world_grant_revision(workspace_id,grant_id,grant_seq,version_id,"
                "expires_at,document,document_sha256,recorded_by) values(%s,%s,1,%s,%s,%s,%s,%s)",
                (
                    workspace,
                    grant,
                    entry["authored_version_id"],
                    expiry,
                    Jsonb(document),
                    sha256_of_canonical(document).hex(),
                    sessions["owner"].actor,
                ),
            )
            connection.execute(
                "insert into world_grant_entry(workspace_id,grant_id,"
                "secret_sha256,expires_at,used_at) "
                "values(%s,%s,%s,%s,%s)",
                (workspace, grant, grant.hex * 2, expiry, now if bound else None),
            )
            if bound:
                connection.execute(
                    "insert into world_grant_principal(workspace_id,grant_id,"
                    "principal_sha256,notice_sha256) "
                    "values(%s,%s,%s,%s)",
                    (
                        workspace,
                        grant,
                        principal_sha256(grant, actor),
                        notice_reference()["sha256"],
                    ),
                )
            if revoked:
                connection.execute(
                    "insert into world_grant_revocation(workspace_id,grant_id,"
                    "revoked_by,revoked_at) "
                    "values(%s,%s,%s,%s)",
                    (workspace, grant, sessions["owner"].actor, revoked),
                )
        assert connection.execute("select participation_prune(1) as n").fetchone()["n"] <= 3
        connection.execute("select participation_prune(1000)")
        principals = {
            row["grant_id"]
            for row in connection.execute("select grant_id from world_grant_principal").fetchall()
        }
        assert principals == {ids["recent"], ids["active"]}
        assert connection.execute(
            "select 1 from world_grant_entry where grant_id=%s", (ids["revoked"],)
        ).fetchone()
        assert not connection.execute(
            "select 1 from world_grant_entry where grant_id=%s", (ids["unused"],)
        ).fetchone()
        repository = InvitationRepository(connection, workspace)
        assert repository.state(repository.row(ids["expired"])) == "expired"
        assert repository.state(repository.row(ids["revoked"])) == "revoked"


def test_personal_addition_closes_an_existing_invitation_and_prevents_new_ones(invited_world):
    api, entry, _ = invited_world
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    version = entry["authored_version_id"]
    world = entry["world_id"]
    base = api.get(f"/world/versions/{version}?world_id={world}").json()["state_sha256"]
    east, _, south = entry["generated_site"]["arrival_mm"]
    personal = api.post(
        f"/world/versions/{version}/things?world_id={world}",
        {
            "base_state_sha256": base,
            "thing_id": "personal-knight",
            "kind": next(
                k for k in shipped_thing_kinds().values() if k.kind == "knight"
            ).reference(),
            "region_id": "region:generated",
            "pose": {"x_mm": east, "y_mm": 0, "z_mm": south, "yaw_microradians": 0},
            "origin_role": "personal",
        },
    )
    assert personal.status_code == 201, personal.text
    headers = {"x-test-user": "visitor"}
    root = "/participation/" + invite["grant_id"]
    assert api.client.get(root + "/world", headers=headers).status_code == 404
    assert api.client.get(root + "/society", headers=headers).status_code == 404
    response = api.client.post(
        "/world/invitations",
        params={"world_id": world},
        json={
            "idempotency_key": str(uuid.uuid4()),
            "version_id": version,
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "world_words": "Garden",
        },
    )
    assert response.status_code == 404, response.text
    # Leaving does not need the now-refused personal sources.
    assert api.client.post(root + "/leave", headers=headers).status_code == 204


def test_host_disabled_and_unset_role_context_reveal_nothing(invited_world, monkeypatch):
    from exulanica.db.participant_role import PARTICIPANT_VIEWS

    api, entry, sessions = invited_world
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    with (
        api.database.session(sessions["owner"].workspace_id) as connection,
        connection.transaction(),
    ):
        connection.execute("set local role exulanica_participant")
        for view in PARTICIPANT_VIEWS:
            assert connection.execute(f"select * from {view}").fetchall() == []
    from exulanica.participation.repository import ParticipationRefused

    runtime = api.client.app.state.participation
    scope = runtime.open(uuid.UUID(invite["grant_id"]), sessions["visitor"].actor)
    accounts = runtime.services.accounts
    monkeypatch.setattr(accounts, "owned_workspace_active", lambda _: False)
    for read in (runtime.grant, runtime.world, runtime.society):
        with pytest.raises(ParticipationRefused):
            read(scope)
    root = "/participation/" + invite["grant_id"]
    for suffix in ("", "/world", "/society"):
        assert api.client.get(root + suffix, headers={"x-test-user": "visitor"}).status_code == 404


def test_only_current_inhabitants_reference_look_bytes_and_read_rechecks_end(
    invited_world, monkeypatch
):
    from exulanica.participation.repository import InvitationRepository, ParticipationRefused
    from exulanica.world.thing_store import ThingStore

    from test_society_made_kinds import canary_creature

    api, entry, sessions = invited_world
    workspace = sessions["owner"].workspace_id
    creature = canary_creature("crocodile", hands=True)
    with api.database.session(workspace) as connection:
        ThingStore(connection, workspace, api.store).keep_creature(creature, created_by=api.actor)
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    original_runtime = api.client.app.state.participation
    runtime = dataclasses.replace(
        original_runtime,
        services=dataclasses.replace(
            original_runtime.services,
            content_stores=SimpleNamespace(
                looks=SimpleNamespace(for_workspace=lambda _: api.store)
            ),
        ),
    )
    scope = runtime.open(uuid.UUID(invite["grant_id"]), sessions["visitor"].actor)
    look = creature.sketch
    digest = look.document["container"]["sha256"]

    def choice(thing_id):
        with api.database.session(workspace) as connection:
            connection.execute(
                "insert into world_thing_look(workspace_id,world_id,version_id,thing_id,look,"
                "look_version,look_sha256,chosen_by,actor,source) "
                "values(%s,%s,%s,%s,%s,%s,%s,'owner',%s,'workspace')",
                (
                    workspace,
                    entry["world_id"],
                    entry["authored_version_id"],
                    thing_id,
                    None,
                    None,
                    bytes.fromhex(look.sha256),
                    api.actor,
                ),
            )

    # Historical choices can outlive their former inhabitants. Such an otherwise valid kept
    # asset must not enter the observer's file inventory or authorize its bytes.
    choice(uuid.uuid4())
    assert runtime.world(scope)["files"] == []
    with pytest.raises(ParticipationRefused):
        runtime.file(scope, digest)
    person = runtime.society(scope)["inhabitants"][0]
    choice(uuid.UUID(person["id"]))
    assert {item["sha256"] for item in runtime.world(scope)["files"]} == {digest}
    data, media = runtime.file(scope, digest)
    assert data == creature.sketch_container and media == "model/gltf-binary"
    original_get = api.store.get

    def leave_during_read(blob):
        data = original_get(blob)
        with api.database.session(workspace) as connection:
            InvitationRepository(connection, workspace).leave(
                scope.grant_id, sessions["visitor"].actor, eligible=lambda *_: None
            )
        return data

    monkeypatch.setattr(api.store, "get", leave_during_read)
    with pytest.raises(ParticipationRefused):
        runtime.file(scope, digest)


def test_source_authorization_refusal_is_closed_and_leaving_remains_available(invited_world):
    from exulanica.participation.repository import ParticipationRefused
    from exulanica.world.society import UnavailableSocietyInput

    api, entry, sessions = invited_world
    invite = _issue(api, entry)
    assert _redeem(api, invite).status_code == 200
    runtime = api.client.app.state.participation
    scope = runtime.open(uuid.UUID(invite["grant_id"]), sessions["visitor"].actor)
    original = runtime.hooks.input_authorizer
    checked = []

    def withdrawn_source(connection, session, document):
        original(connection, session, document)
        checked.append(document["input_seq"])
        raise UnavailableSocietyInput("private dependency was withdrawn")

    runtime = dataclasses.replace(
        runtime, hooks=dataclasses.replace(runtime.hooks, input_authorizer=withdrawn_source)
    )
    api.client.app.state.participation = runtime
    root = "/participation/" + invite["grant_id"]
    headers = {"x-test-user": "visitor"}
    for suffix in ("/world", "/society"):
        response = api.client.get(root + suffix, headers=headers)
        assert response.status_code == 404, response.text
        assert "private dependency" not in response.text
    # A scope captured before withdrawal is not sufficient authority at final serving time.
    with pytest.raises(ParticipationRefused):
        runtime.world(scope)
    with pytest.raises(ParticipationRefused):
        runtime.society(scope)
    assert checked
    assert api.client.post(root + "/leave", headers=headers).status_code == 204
