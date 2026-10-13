"""Offline cleanup commit/readback boundaries with no real connection or witness file."""

from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cleanup_adapters import CleanupAdapters
from pilot_guard import Identity, PilotStop, TargetBinding, code_schema_version


@pytest.fixture
def cleanup(tmp_path):
    identity = Identity(
        uuid4(),
        "world:clone",
        uuid4(),
        uuid4(),
        "duck",
        "nebius_token_factory",
        "nano",
        "a" * 64,
        "b" * 64,
        1,
    )
    root = tmp_path / "clone"
    binding = TargetBinding(
        root,
        root / "data",
        root / "data",
        root / "store",
        root / "store",
        (tmp_path / "primary",),
        "postgresql://localhost:20030/test",
        "http://localhost:20031",
        "http://localhost:20032",
        "c" * 64,
        code_schema_version(),
        "durable",
        uuid4(),
        Decimal(".25"),
        100,
        tmp_path / "witness",
        tmp_path / "witness",
    )
    grant, directory = uuid4(), uuid4()
    state = SimpleNamespace(
        events=[],
        fail_commit=False,
        fail_read=False,
        fail_revoke=False,
        unconfirmed=False,
        paused=False,
        revoke_calls=0,
        witnesses=0,
    )
    row = dict(
        authority_id=binding.authority_id,
        workspace_id=identity.workspace_id,
        grant_id=grant,
        parent_grant_id=None,
        provider=identity.provider,
        witnessed=True,
        ceiling_usd=Decimal(".25"),
        max_calls=100,
        sequence=7,
        head_sha256="f" * 64,
        witness_directory_id=directory,
        revoked=False,
    )
    entry = dict(
        provider=identity.provider,
        grant={"grant_id": str(grant), "state": "active"},
        unresolved={"count": 1, "usd": "0.01"},
        in_flight_usd="0.02",
        committed_usd="0.03",
    )
    witness_doc = dict(
        status="live",
        confirmed=True,
        authority_id=str(binding.authority_id),
        directory_id=str(directory),
        sequence=7,
        head_sha256="f" * 64,
        revoked=[],
    )

    class Connection:
        def __init__(self, number):
            self.number, self.pending = number, False

        @contextmanager
        def transaction(self):
            state.events.append(("begin", self.number))
            yield
            if state.fail_commit:
                raise OSError("commit failed")
            if self.pending:
                state.paused = True
            state.events.append(("commit", self.number))

        def execute(self, sql, parameters):
            assert parameters == (identity.workspace_id, grant, binding.authority_id)
            return SimpleNamespace(fetchone=lambda: deepcopy(row))

    class Database:
        url = binding.database_url
        counter = 0

        @contextmanager
        def session(self, workspace):
            assert workspace == identity.workspace_id
            self.counter += 1
            conn = Connection(self.counter)
            state.events.append(("open", conn.number))
            try:
                yield conn
            finally:
                state.events.append(("close", conn.number))

    database = Database()

    class Repository:
        def __init__(self, connection, workspace, *, world_id):
            assert workspace == identity.workspace_id and world_id == identity.world_id
            self.connection = connection

        def read(self, version, **kwargs):
            assert version == identity.version_id
            state.events.append(("read", self.connection.number))
            if state.fail_read and state.paused:
                raise OSError("fresh read failed")
            return {
                "society_id": str(identity.society_id),
                "revision": 2,
                "mode": "paused" if state.paused else "playing",
                "lease_expires_at": None if state.paused else "later",
            }

        def configure(self, version, **kwargs):
            assert kwargs["base_revision"] == 2 and kwargs["mode"] == "paused"
            self.connection.pending = True
            state.events.append(("configure", self.connection.number))

    @contextmanager
    def hold(authority):
        assert authority == binding.authority_id
        state.witnesses += 1
        state.events.append(("witness", "held"))
        yield SimpleNamespace(document=deepcopy(witness_doc))

    witness = SimpleNamespace(directory=binding.witness_path, hold=hold)

    def revoke(authority, **kwargs):
        assert authority == binding.authority_id
        assert kwargs["workspace_id"] == identity.workspace_id and kwargs["grant_id"] == grant
        state.revoke_calls += 1
        if state.fail_revoke:
            raise OSError("revocation failed")
        row["revoked"] = True
        entry["grant"]["state"] = "revoked"
        witness_doc["revoked"] = [f"grant:{identity.workspace_id}/{grant}"]
        witness_doc["confirmed"] = not state.unconfirmed
        return "revoked"

    operator = SimpleNamespace(database=database, witness=witness, revoke=revoke)

    def status_reader(connection, workspace, *, providers):
        assert providers == (identity.provider,) and workspace == identity.workspace_id
        assert state.witnesses == 1
        return {"workspace_id": str(workspace), "providers": [deepcopy(entry)]}

    adapter = CleanupAdapters(
        database=database,
        operator=operator,
        binding=binding,
        identity=identity,
        actor=uuid4(),
        grant_id=grant,
        repository_factory=Repository,
        status_reader=status_reader,
    )
    state.adapter, state.row, state.entry, state.operator = adapter, row, entry, operator
    return state


def test_pause_is_committed_then_read_in_separate_session(cleanup):
    result = cleanup.adapter.pause()
    assert result["commit_verified"] is True and result["mode"] == "paused"
    events = cleanup.events
    assert events.index(("commit", 1)) < events.index(("close", 1)) < events.index(("open", 2))
    assert ("read", 2) in events


@pytest.mark.parametrize("failure", ["fail_commit", "fail_read"])
def test_failed_commit_or_fresh_read_cannot_confirm_pause(cleanup, failure):
    setattr(cleanup, failure, True)
    with pytest.raises(OSError):
        cleanup.adapter.pause()
    if failure == "fail_commit":
        assert not cleanup.paused and ("open", 2) not in cleanup.events


def test_revoke_confirms_exact_grant_witness_and_retains_liability(cleanup):
    before = deepcopy(cleanup.entry["unresolved"])
    result = cleanup.adapter.revoke()
    assert result["scope"] == "workspace_grant" and result["witness_confirmed"]
    assert result["status"]["unresolved"] == before
    assert result["liability_reconciliation_required"] is True
    assert cleanup.events.index(("witness", "held")) < cleanup.events.index(("open", 2))
    assert cleanup.revoke_calls == 1


@pytest.mark.parametrize("failure", ["fail_revoke", "unconfirmed"])
def test_failed_revoke_or_witness_never_confirms_or_erases_liability(cleanup, failure):
    before = deepcopy(cleanup.entry["unresolved"])
    setattr(cleanup, failure, True)
    with pytest.raises((OSError, PilotStop)):
        cleanup.adapter.revoke()
    assert cleanup.entry["unresolved"] == before
    assert cleanup.revoke_calls == 1  # no retry after potentially committed mutation


def test_wrong_grant_authority_refuses_before_revoke(cleanup):
    cleanup.row["authority_id"] = uuid4()
    with pytest.raises(PilotStop, match="cleanup_grant_differs"):
        cleanup.adapter.revoke()
    assert cleanup.revoke_calls == 0


def test_wrong_actual_database_refuses_before_any_session(cleanup):
    cleanup.operator.database.url = "postgresql://localhost:19950/main"
    with pytest.raises(PilotStop, match="cleanup_database_differs"):
        cleanup.adapter.pause()
    assert not cleanup.events
