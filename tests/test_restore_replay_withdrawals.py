"""A restore keeps every withdrawal a person made, measured through a real restore.

A withdrawal that is not a tombstone lives in the row it ends or in a row of its own: a stopped
model right is ``personal_model_right.withdrawn_at`` (migration 0073), a withdrawn consent is the
next decision in its chain. A backup taken before the withdrawal holds the thing as current, so a
restore that replayed only tombstones brought it back. ``withdraw_model_right`` promises the
opposite: a withdrawn right is never restored, only granted again.

Each test below makes one kind current, takes an actual ``pg_dump`` backup, withdraws it the way
the product does, seals the checkpoint and writes the marker with the restore command, restores
the dump with ``psql`` and replays with the command, and asks whether the thing is withdrawn
again. The catalog of kinds is ``exulanica/deletion/withdrawals.v1.json``; the kinds a real
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
from exulanica.deletion.restore import main as restore_command
from exulanica.deletion.withdrawals import CATALOG
from exulanica.ingest.person_review import create_subject, record_consent
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.training_rights import grant_training_right, withdraw_training_right
from exulanica.models.manifest import Role
from exulanica.world.companion_memory import AnswerCitation, CompanionMemoryRepository
from exulanica.world_package.training_store import record_training_decision

from test_companion_memory import _answer
from test_material_recipes import BRICK, _small
from test_material_recipes import materials as materials
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


def test_an_event_withdrawal_that_cannot_follow_its_backup_is_refused_by_name(
    named, purged, commands, tmp_path
):
    """The database refuses a decision out of its chain, and the replay says which kind it was."""
    _grant_place_name(named, "structured_extraction")
    dump, blobs = _backup(purged, tmp_path)
    _withdraw_place_name(named, "structured_extraction")
    source, marker = _checkpoint_only(tmp_path)

    def out_of_its_chain(record) -> None:
        for item in record["withdrawals"]:
            if item["kind"] == "place_name_right":
                item["row"]["sequence"] = 7

    _edited(source, out_of_its_chain)
    _prepare(source, marker)
    _restore(purged, dump, blobs)
    with pytest.raises(RestoreRefused, match="place_name_right withdrawal cannot follow"):
        _replay(source, marker)
    assert _place_name_state(named, "structured_extraction") != "withdrawn"
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)
