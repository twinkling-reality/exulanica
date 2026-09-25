"""A restore keeps every withdrawal a person made, measured through a real restore.

A withdrawal that is not a tombstone lives in the row it ends or in a row of its own: a stopped
model right is ``personal_model_right.withdrawn_at`` (migration 0073), a withdrawn consent is the
next decision in its chain. A backup taken before the withdrawal holds the thing as current, so a
restore that replayed only tombstones brought it back. ``withdraw_model_right`` promises the
opposite: a withdrawn right is never restored, only granted again.

Each test below makes one kind current, takes an actual ``pg_dump`` backup, withdraws it the way
the product does, seals the checkpoint and writes the marker with the restore command, restores
the dump with ``psql`` and replays with the command, and asks whether the thing is withdrawn
again. The catalog of kinds is ``exulanica/deletion/withdrawals.v2.json``; the kinds a real
restore here does not reach are held by ``tests/test_restore_replay_withdrawal_catalog.py``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import uuid

import psycopg
import pytest
from exulanica.api.account_repository import AccountRejected, AccountRepository, secret_digest
from exulanica.canonical import canonical_json
from exulanica.consent.training import TrainingTerms
from exulanica.deletion.restore import RestoreRefused, verify_restore
from exulanica.deletion.withdrawals import CATALOG
from exulanica.identity import rename_entity
from exulanica.ingest.person_review import create_subject, record_consent
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.training_rights import grant_training_right, withdraw_training_right
from exulanica.models.manifest import Role
from exulanica.orchestration.restore import main as restore_command
from exulanica.world.companion_memory import AnswerCitation, CompanionMemoryRepository
from exulanica.world_package.training_store import record_training_decision

from test_companion_memory import _answer
from test_material_recipes import BRICK, _small
from test_material_recipes import materials as materials
from test_place_name_rights import _events as _place_name_events
from test_place_name_rights import _grant as _grant_place_name
from test_place_name_rights import _state as _place_name_state
from test_place_name_rights import _withdraw as _withdraw_place_name
from test_place_name_rights import named as named
from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_scene_training_right import GPU, TRAINING_PURPOSE
from test_search_entries_on_stop import ACCOUNT, _as_runtime, _authorize, _stop
from test_search_entries_on_stop import indexed as indexed

pytestmark = pytest.mark.postgres


def _replay(source, marker) -> None:
    assert restore_command(["replay", "--checkpoint", str(source), "--marker", str(marker)]) == 0


def _through_a_restore(fixture, tmp_path, *, withdraw, current) -> bool:
    """Back up while it is current, withdraw it, seal, restore the backup, replay: is it current?"""
    assert current(), "the positive control: current before the backup"
    dump, blobs = _backup(fixture, tmp_path)
    withdraw()
    assert not current(), "the withdrawal took effect at the source"
    source, marker = _seal(tmp_path)
    _restore(fixture, dump, blobs)
    assert current(), "the backup holds it as current"
    _replay(source, marker)
    verify_restore(fixture.database(), marker)
    return current()


def _model_right_current(fixture, role: Role) -> bool:
    [row] = fixture.rows(
        "select bool_or(personal_model_right_allows(workspace_id,right_id,capture_id,"
        "model_provider,model_role,model_id,model_revision,destination,clock_timestamp())) "
        "as current from personal_model_right where model_role=%s",
        role.value,
    )
    return bool(row["current"])


# -- the kinds ---------------------------------------------------------------------------------


def test_a_description_right_stopped_after_the_backup_stays_stopped(indexed, commands, tmp_path):
    fixture = indexed.fixture
    assert not _through_a_restore(
        fixture,
        tmp_path,
        withdraw=lambda: [_stop(fixture, r.right_id) for r in indexed.rights[Role.VISION]],
        current=lambda: _model_right_current(fixture, Role.VISION),
    )
    assert _model_right_current(fixture, Role.EMBEDDING), "the other right was never stopped"


def test_a_training_right_withdrawn_after_the_backup_stays_withdrawn(purged, commands, tmp_path):
    repository = purged.repository
    capture = purged.rows("select capture_id from capture")[0]["capture_id"]
    authorization = _authorize(repository, capture)
    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    right = grant_training_right(
        repository,
        capture_id=capture,
        authorization_id=authorization.authorization_id,
        destination=GPU,
        granted_by=ACCOUNT,
        purpose=TRAINING_PURPOSE,
        valid_until=now + dt.timedelta(hours=1),
    )

    def current() -> bool:
        return purged.rows(
            "select withdrawn_at is null as current from scene_training_right where right_id=%s",
            right.right_id,
        )[0]["current"]

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: withdraw_training_right(
            repository, right_id=right.right_id, withdrawn_by=ACCOUNT
        ),
        current=current,
    )


def test_a_companion_memory_deleted_after_the_backup_stays_deleted(purged, commands, tmp_path):
    repository = purged.repository
    memory = CompanionMemoryRepository(repository.connection, purged.workspace_id, ACCOUNT)
    answer = memory.record_answer(_answer())

    def current() -> bool:
        return purged.rows(
            "select status::text = 'active' as current from companion_answer where answer_id=%s",
            answer.answer_id,
        )[0]["current"]

    assert not _through_a_restore(
        purged, tmp_path, withdraw=lambda: memory.withdraw(answer.answer_id), current=current
    )
    [row] = purged.rows(
        "select withdrawn_by from companion_answer where answer_id=%s", answer.answer_id
    )
    assert row["withdrawn_by"] is None, "the person withdrew it, not a tombstone"


def test_a_memory_a_deletion_withdrew_after_the_backup_is_withdrawn_by_that_deletion_again(
    purged, commands, tmp_path
):
    """The two withdrawals of a memory stay apart: a deletion's names its tombstone (0043).

    The catalog carries only a person's own withdrawal of a memory (``withdrawn_by`` null); one a
    deleted photograph caused is written again by the replayed tombstone, which names itself.
    """
    [cited] = purged.rows(
        "select s.span_id, c.capture_id from evidence_span s join capture c "
        "on c.workspace_id = s.workspace_id and c.blob_sha256 = s.blob_sha256 "
        "where s.workspace_id = %s and s.modality = 'still_image' limit 1",
        purged.workspace_id,
    )
    memory = CompanionMemoryRepository(purged.repository.connection, purged.workspace_id, ACCOUNT)
    answer = memory.record_answer(
        _answer(
            citations=(
                AnswerCitation(span_id=cited["span_id"], capture_id=cited["capture_id"], ordinal=0),
            )
        )
    )

    def current() -> bool:
        return purged.rows(
            "select status::text = 'active' as current from companion_answer where answer_id=%s",
            answer.answer_id,
        )[0]["current"]

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: purged.tombstone_the_capture(cited["capture_id"]),
        current=current,
    )
    [row] = purged.rows(
        "select a.withdrawn_by, t.scope::text as scope from companion_answer a "
        "join tombstone t on t.tombstone_id = a.withdrawn_by where a.answer_id=%s",
        answer.answer_id,
    )
    assert row["scope"] == "capture", "the deletion withdrew it, and says so"


def test_a_checkpoint_holds_every_catalog_table_against_writes_while_it_reads(
    purged, commands, tmp_path, monkeypatch
):
    """The seal takes effect when the checkpoint commits, so until then the lock is what holds."""
    from exulanica.deletion import restore

    held = []
    read = restore.read_withdrawals

    def reading(connection):
        held.extend(
            connection.execute(
                "select relation::regclass::text as t, mode from pg_locks "
                "where pid = pg_backend_pid() and locktype = 'relation'"
            ).fetchall()
        )
        return read(connection)

    monkeypatch.setattr(restore, "read_withdrawals", reading)
    _seal(tmp_path)
    locked = {row["t"].split(".")[-1] for row in held if row["mode"] == "ExclusiveLock"}
    assert {kind.table for kind in CATALOG} <= locked


def test_a_place_name_right_withdrawn_after_the_backup_stays_withdrawn(
    named, purged, commands, tmp_path
):
    _grant_place_name(named, "structured_extraction")
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: _withdraw_place_name(named, "structured_extraction"),
        current=lambda: _place_name_state(named, "structured_extraction") != "withdrawn",
    )


def test_a_presentation_consent_withdrawn_after_the_backup_stays_withdrawn(
    purged, commands, tmp_path
):
    repository = purged.repository
    subject = create_subject(repository, actor=ACCOUNT)
    record_consent(
        repository, subject_id=subject, actor=ACCOUNT, consent_scope="likeness", decision="granted"
    )

    def current() -> bool:
        return purged.rows(
            "select decision = 'granted' as current from person_presentation_consent "
            "where subject_id=%s and consent_scope='likeness' order by sequence desc limit 1",
            subject,
        )[0]["current"]

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: record_consent(
            repository,
            subject_id=subject,
            actor=ACCOUNT,
            consent_scope="likeness",
            decision="withdrawn",
        ),
        current=current,
    )


def test_a_training_consent_withdrawn_after_the_backup_stays_withdrawn(purged, commands, tmp_path):
    repository = purged.repository
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    terms = TrainingTerms(
        package_id="package-restore-carries-withdrawals",
        licensee="a licensee",
        model_classes=("scene",),
        valid_from=now - dt.timedelta(days=1),
        valid_until=now + dt.timedelta(days=30),
        terms_sha256=hashlib.sha256(b"the terms a person agreed to").hexdigest(),
    )
    subject = "subject-restore-carries-withdrawals"

    def decide(decision: str) -> None:
        record_training_decision(
            repository, subject_id=subject, terms=terms, decision=decision, actor=ACCOUNT
        )

    decide("granted")

    def current() -> bool:
        return purged.rows(
            "select decision = 'granted' as current from training_use_consent "
            "where subject_id=%s order by sequence desc limit 1",
            subject,
        )[0]["current"]

    assert not _through_a_restore(
        purged, tmp_path, withdraw=lambda: decide("withdrawn"), current=current
    )


def test_a_recipe_withdrawn_after_the_backup_stays_withdrawn(materials, commands, tmp_path):
    record = materials.repository().create_recipe(_small(), based_on=(BRICK, 1), label="Mine")

    def current() -> bool:
        return [r.recipe_id for r in materials.repository().recipes()] == [record.recipe_id]

    assert not _through_a_restore(
        materials.purged,
        tmp_path,
        withdraw=lambda: materials.repository().withdraw_recipe(record.recipe_id),
        current=current,
    )


def _signed_in(purged) -> tuple[str, uuid.UUID]:
    """An account holder with one browser session, written as sign-in writes them."""
    token = secrets.token_urlsafe(32)
    user, workspace, state = uuid.uuid4(), purged.workspace_id, secrets.token_hex(32)
    connection = purged.repository.connection
    connection.execute(
        "insert into account_user (user_id, actor_id) values (%s, %s)", (user, ACCOUNT)
    )
    connection.execute(
        "insert into account_workspace (workspace_id, owner_user_id) values (%s, %s)",
        (workspace, user),
    )
    connection.execute(
        "insert into account_membership (workspace_id, user_id, membership_role) "
        "values (%s, %s, 'owner')",
        (workspace, user),
    )
    connection.execute(
        "insert into account_login_attempt (state_sha256, browser_sha256, config_sha256, "
        "callback_uri, return_uri, expires_at, outcome) values (%s, %s, %s, 'https://a.test/cb', "
        "'https://a.test/', now() + interval '1 hour', 'succeeded')",
        (state, secrets.token_hex(32), secrets.token_hex(32)),
    )
    connection.execute(
        "insert into account_browser_session (session_sha256, user_id, workspace_id, csrf_token, "
        "login_state_sha256, expires_at) values (%s, %s, %s, %s, %s, now() + interval '1 hour')",
        (secret_digest(token), user, workspace, secrets.token_urlsafe(32), state),
    )
    return token, user


def _session_current(accounts: AccountRepository, token: str) -> bool:
    try:
        accounts.session(token)
    except AccountRejected:
        return False
    return True


def test_a_session_logged_out_after_the_backup_stays_logged_out(purged, commands, tmp_path):
    """A token that logged out stays refused, so a restore never revives a stolen session."""
    token, _ = _signed_in(purged)
    accounts = AccountRepository(purged.repository.connection)
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: accounts.logout(token),
        current=lambda: _session_current(accounts, token),
    )


def test_an_account_disabled_after_the_backup_stays_disabled(purged, commands, tmp_path):
    token, user = _signed_in(purged)
    accounts = AccountRepository(purged.repository.connection)

    def current() -> bool:
        [row] = purged.rows(
            "select disabled_at is null as current from account_user where user_id=%s", user
        )
        return row["current"]

    assert not _through_a_restore(
        purged, tmp_path, withdraw=lambda: accounts.disable_account(user), current=current
    )
    assert not _session_current(accounts, token), "disabling revoked its session too"


# -- the seal, a stale checkpoint and a checkpoint the restored database disagrees with ------


def test_a_sealed_checkpoint_refuses_every_withdrawal(indexed, commands, tmp_path):
    fixture = indexed.fixture
    subject = create_subject(fixture.repository, actor=ACCOUNT)
    record_consent(
        fixture.repository,
        subject_id=subject,
        actor=ACCOUNT,
        consent_scope="likeness",
        decision="granted",
    )
    _seal(tmp_path)
    [vision] = indexed.rights[Role.VISION][:1]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"):
        _stop(fixture, vision.right_id)
    with (
        _as_runtime(fixture) as connection,
        pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"),
    ):
        record_consent(
            IngestRepository(connection, fixture.workspace_id),
            subject_id=subject,
            actor=ACCOUNT,
            consent_scope="likeness",
            decision="withdrawn",
        )
    assert _model_right_current(fixture, Role.VISION)


def test_a_checkpoint_older_than_its_backup_is_refused(indexed, commands, tmp_path):
    """The source sealed, resumed after a replay of its own, and withdrew more before the backup."""
    fixture = indexed.fixture
    old_source, old_marker = _seal(tmp_path / "first")
    _replay(old_source, old_marker)
    for right in indexed.rights[Role.VISION]:
        _stop(fixture, right.right_id)
    dump, blobs = _backup(fixture, tmp_path)
    marker = tmp_path / "second-control" / "restore.json"
    assert (
        restore_command(["prepare", "--checkpoint", str(old_source), "--marker", str(marker)]) == 0
    )
    _restore(fixture, dump, blobs)

    with pytest.raises(RestoreRefused, match="the checkpoint is older than the backup"):
        restore_command(["replay", "--checkpoint", str(old_source), "--marker", str(marker)])
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(fixture.database(), marker)


def _edited(source, change) -> None:
    """Change the sealed record and bind the digest again, as only an operator could."""
    envelope = json.loads(source.read_bytes())
    change(envelope["record"])
    envelope["record_sha256"] = hashlib.sha256(canonical_json(envelope["record"])).hexdigest()
    source.write_bytes(canonical_json(envelope))


def _checkpoint_only(tmp_path):
    source = tmp_path / "independent-journal" / "checkpoint.json"
    assert restore_command(["checkpoint", "--checkpoint", str(source)]) == 0
    return source, tmp_path / "independent-control" / "restore.json"


def _prepare(source, marker) -> None:
    assert restore_command(["prepare", "--checkpoint", str(source), "--marker", str(marker)]) == 0


def test_a_restored_withdrawal_the_checkpoint_records_otherwise_is_refused_as_stale(
    indexed, commands, tmp_path
):
    """A restored database whose withdrawal the checkpoint records differently is not its backup.

    The first attempt asks before it writes anything, so a disagreement refuses there; the check
    a later attempt's write makes for the same disagreement is held in
    ``tests/test_restore_replay_withdrawal_catalog.py``.
    """
    fixture = indexed.fixture
    for right in indexed.rights[Role.VISION]:
        _stop(fixture, right.right_id)
    source, marker = _checkpoint_only(tmp_path)

    def later(record) -> None:
        for item in record["withdrawals"]:
            if item["kind"] == "model_right":
                item["row"]["withdrawn_at"] = "2099-01-01T00:00:00+00:00"

    _edited(source, later)
    _prepare(source, marker)
    with pytest.raises(RestoreRefused, match="the checkpoint is older than the backup"):
        _replay(source, marker)
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(fixture.database(), marker)


def test_a_checkpoint_sealed_under_another_catalog_is_refused(purged, commands, tmp_path):
    source, marker = _checkpoint_only(tmp_path)
    _edited(source, lambda record: record["withdrawal_catalog"].update(sha256="0" * 64))
    with pytest.raises(RestoreRefused, match="another withdrawal catalog"):
        _prepare(source, marker)


def _regranted(named) -> None:
    """Grant, rename, and grant again: two grants in each chain, the second after the backup."""
    _, identity, assertions, actor, entities = named
    rename_entity(
        identity, assertions, entity_id=entities["place"], display_name="The Old Mill", actor=actor
    )
    assert _place_name_state(named, "structured_extraction") == "name_changed"
    _grant_place_name(named, "structured_extraction")


def _chains(named) -> dict[tuple[str, str], list[dict]]:
    """Each chain of the planner's models at its destination, its decisions in order."""
    chains: dict[tuple[str, str], list[dict]] = {}
    for event in _place_name_events(named):
        if event["model_role"] == "structured_extraction":
            chains.setdefault((event["model_id"], event["destination"]), []).append(event)
    return chains


def test_a_place_name_withdrawal_after_a_grant_the_backup_lacks_continues_its_chain(
    named, purged, commands, tmp_path
):
    """A rename ends a grant and a new grant follows it; the backup holds only the first.

    The carried withdrawal follows the second grant and cannot be written after the first, so the
    replay withdraws the chain the backup holds with a decision of its own: the same account
    holder, at the same time, as the next in that chain.
    """
    _grant_place_name(named, "structured_extraction")
    dump, blobs = _backup(purged, tmp_path)
    _regranted(named)
    _withdraw_place_name(named, "structured_extraction")
    source, marker = _seal(tmp_path)
    carried = {
        (event["model_id"], event["destination"]): event
        for chain in _chains(named).values()
        for event in chain
        if event["event"] == "withdrawn"
    }
    assert {event["sequence"] for event in carried.values()} == {2}, "after the second grant"
    _restore(purged, dump, blobs)
    assert _place_name_state(named, "structured_extraction") == "allowed", "the backup allows it"

    _replay(source, marker)
    verify_restore(purged.database(), marker)

    assert _place_name_state(named, "structured_extraction") == "withdrawn"
    chains = _chains(named)
    assert chains.keys() == carried.keys()
    for key, chain in chains.items():
        assert [event["event"] for event in chain] == ["granted", "withdrawn"], key
        continued = chain[-1]
        assert continued["sequence"] == 1
        assert bytes(continued["previous_sha256"]) == bytes(chain[0]["receipt_sha256"])
        assert continued["decided_by"] == carried[key]["decided_by"]
        assert continued["decided_at"] == carried[key]["decided_at"]
        assert continued["event_id"] != carried[key]["event_id"], "a decision of its own"


def test_a_continued_chain_is_continued_once_when_the_replay_resumes(
    named, purged, commands, tmp_path, monkeypatch
):
    """An attempt that stops after the withdrawals were written finds each chain withdrawn."""
    from exulanica.deletion import restore

    _grant_place_name(named, "structured_extraction")
    dump, blobs = _backup(purged, tmp_path)
    _regranted(named)
    _withdraw_place_name(named, "structured_extraction")
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)

    class Interrupted(RuntimeError):
        pass

    def stopped(*args, **kwargs):
        raise Interrupted("the purge never started")

    with monkeypatch.context() as patched:
        patched.setattr(restore, "PurgeWorker", stopped)
        with pytest.raises(Interrupted):
            _replay(source, marker)
    assert _place_name_state(named, "structured_extraction") == "withdrawn", "carried first"
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)

    _replay(source, marker)
    verify_restore(purged.database(), marker)
    for key, chain in _chains(named).items():
        assert [event["event"] for event in chain] == ["granted", "withdrawn"], key


def test_a_chain_the_writer_cannot_see_is_refused_rather_than_left_granted(
    named, purged, commands, tmp_path
):
    """A decision recorded ahead of the restore host's clock is not yet one to the writer.

    The replay sees the backup's grant as the chain's last decision, but the writer asks the chain
    at its own instant and finds nothing to withdraw. Replay checks the chain afterwards and
    refuses by name, so it never completes with the chain still ending in a grant.
    """
    _grant_place_name(named, "structured_extraction")
    dump, blobs = _backup(purged, tmp_path)
    _regranted(named)
    _withdraw_place_name(named, "structured_extraction")
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    # The backup's decisions, moved ahead of this host's clock as a clock running behind the
    # source's would see them. Only the schema owner can, with the append-only trigger idle.
    connection = purged.repository.connection
    with connection.transaction():
        connection.execute("set local session_replication_role = replica")
        moved = connection.execute(
            "update place_name_right_event set decided_at = clock_timestamp() + interval '1 day' "
            "where model_role = 'structured_extraction'"
        ).rowcount
    assert moved == len(_chains(named)), "one grant per chain in the backup"

    with pytest.raises(RestoreRefused, match="place_name_right withdrawal was not continued"):
        _replay(source, marker)
    for key, chain in _chains(named).items():
        assert [event["event"] for event in chain] == ["granted"], key
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)


def test_a_place_name_withdrawal_the_backups_chain_has_passed_is_refused_by_name(
    named, purged, commands, tmp_path
):
    """A carried decision at a position the restored chain already holds follows nothing here.

    A backup the checkpoint was sealed after never holds such a chain; the database refuses the
    write, and the replay names the kind rather than continuing a chain it cannot place.
    """
    _grant_place_name(named, "structured_extraction")
    dump, blobs = _backup(purged, tmp_path)
    _withdraw_place_name(named, "structured_extraction")
    source, marker = _checkpoint_only(tmp_path)

    def passed(record) -> None:
        for item in record["withdrawals"]:
            if item["kind"] == "place_name_right":
                item["row"]["sequence"] = 0

    _edited(source, passed)
    _prepare(source, marker)
    _restore(purged, dump, blobs)
    with pytest.raises(RestoreRefused, match="place_name_right withdrawal cannot follow"):
        _replay(source, marker)
    assert _place_name_state(named, "structured_extraction") != "withdrawn"
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)
