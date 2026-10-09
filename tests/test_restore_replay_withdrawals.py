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
from exulanica.api import creator_grants
from exulanica.api.account_repository import AccountRejected, AccountRepository, secret_digest
from exulanica.canonical import canonical_json
from exulanica.consent.training import TrainingTerms
from exulanica.db.session import set_workspace
from exulanica.deletion.restore import RestoreRefused, verify_restore
from exulanica.deletion.withdrawals import CATALOG, read_withdrawals
from exulanica.evidence.blob import BlobId
from exulanica.identity import rename_entity
from exulanica.ingest.person_review import create_subject, record_consent
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.training_rights import grant_training_right, withdraw_training_right
from exulanica.models.manifest import Role
from exulanica.orchestration.restore import main as restore_command
from exulanica.selection import creature_drafts
from exulanica.store.configured import local_content_stores
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.creatures import assemble_creature
from exulanica.world.character_catalog_publication import (
    catalog_documents,
    catalog_imports,
    publish_catalogs,
    withdraw_catalog,
)
from exulanica.world.character_catalogs import CatalogRegistry, read_publication_document
from exulanica.world.companion_memory import (
    AnswerCitation,
    CompanionMemoryRepository,
    SimulationCitation,
)
from exulanica.world.society_erasure import erase_society
from exulanica.world.thing_store import ThingStore, admitted_look
from exulanica.world_package.training_store import record_training_decision

from test_companion_memory import _answer
from test_creature_bodies import BY, _form, _recipe
from test_material_recipes import BRICK, _small
from test_material_recipes import materials as materials
from test_place_name_rights import _events as _place_name_events
from test_place_name_rights import _grant as _grant_place_name
from test_place_name_rights import _state as _place_name_state
from test_place_name_rights import _withdraw as _withdraw_place_name
from test_place_name_rights import named as named
from test_purge import purged as purged
from test_reference_withdrawal import Pictured
from test_reference_withdrawal import _delete as _delete_picture
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_scene_training_right import GPU, TRAINING_PURPOSE
from test_search_entries_on_stop import ACCOUNT, _as_runtime, _authorize, _stop
from test_search_entries_on_stop import indexed as indexed
from test_society_authored_world_postgres import create_society, place_object
from test_society_authored_world_postgres import saved_world as saved_world
from test_workspace_style_packs_postgres import Packs, admitted

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


def test_a_look_withdrawn_after_the_backup_stays_withdrawn(purged, commands, tmp_path):
    """A workspace's withdrawal of its own look (migration 0159) is final, so a restore may not
    admit it again."""
    creature = assemble_creature(_form(_recipe("ten_legs"), label="restored ten legs"), by=BY)
    actor = uuid.uuid4()
    with purged.database().session(purged.workspace_id) as connection:
        ThingStore(
            connection, purged.workspace_id, LocalContentAddressedStore(tmp_path / "looks")
        ).keep_creature(creature, created_by=actor)

    def current() -> bool:
        with purged.database().session(purged.workspace_id) as connection:
            found = admitted_look(connection, purged.workspace_id, creature.sketch.reference())
        return found is not None

    def withdraw() -> None:
        with purged.database().session(purged.workspace_id) as connection:
            ThingStore(connection, purged.workspace_id, None).withdraw_look(
                creature.sketch.look, creature.sketch.version, "no longer worn", withdrawn_by=actor
            )

    assert not _through_a_restore(purged, tmp_path, withdraw=withdraw, current=current)


def test_notes_from_a_picture_stopped_after_the_backup_are_withdrawn_again(
    purged, commands, tmp_path
):
    # Excluded from the catalog by name: the stop's own trigger withdraws them, and the replayed
    # stop runs it again (migration 0160).
    pictured = Pictured(purged)
    read = pictured.finished()
    web_only = pictured.finished(pictures=())
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: _stop(purged, pictured.rights[0].right_id),
        current=lambda: pictured.request(read).status == "complete",
    )
    assert pictured.request(read).bundle is None
    assert pictured.request(web_only).status == "complete", "a request naming no picture stays"


def test_notes_from_a_picture_deleted_after_the_backup_are_withdrawn_again(
    purged, commands, tmp_path
):
    pictured = Pictured(purged)
    read = pictured.finished()

    def delete() -> None:
        with pictured.runtime() as connection:
            _delete_picture(connection, pictured.workspace_id, pictured.capture_id)

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=delete,
        current=lambda: pictured.request(read).status == "complete",
    )
    assert pictured.request(read).bundle is None


def _kept_creature(purged, tmp_path, label: str):
    """A creature kept in the looks namespace the restore command's own stores read."""
    creature = assemble_creature(_form(_recipe("ten_legs"), label=label), by=BY)
    actor = uuid.uuid4()
    looks = local_content_stores(tmp_path).looks.for_workspace(purged.workspace_id)
    with purged.database().session(purged.workspace_id) as connection:
        ThingStore(connection, purged.workspace_id, looks).keep_creature(creature, created_by=actor)
    return creature, actor, looks


def _creature_held(purged, creature) -> bool:
    """Whether the workspace holds the creature, whole: it is held whole or not at all."""
    with purged.database().session(purged.workspace_id) as connection:
        store = ThingStore(connection, purged.workspace_id, None)
        [row] = connection.execute(
            "select (select count(*) from body_recipe_version where sha256 = %s) "
            "+ (select count(*) from body_plan_version where sha256 = %s) "
            "+ (select count(*) from thing_kind_version where sha256 = %s) "
            "+ (select count(*) from look_version where sha256 = %s) as held",
            (
                creature.recipe_sha256,
                creature.plan.sha256,
                creature.kind.sha256,
                creature.sketch.sha256,
            ),
        ).fetchall()
        assert row["held"] in (0, 4), "a creature is held whole or not at all"
        readable = store.look_by_digest(creature.sketch.sha256, include_withdrawn=True)
        assert (readable is not None) is (row["held"] == 4)
    return row["held"] == 4


def _erase(purged, creature, actor) -> None:
    with purged.database().session(purged.workspace_id) as connection:
        ThingStore(connection, purged.workspace_id, None).erase_creature(
            creature.kind.sha256, erased_by=actor
        )


def test_a_creature_erased_after_the_backup_stays_erased(purged, commands, tmp_path):
    """A workspace's erasure of a creature drafted from a person's words (migration 0172) is carried
    by a restore: the backup holds the creature, the replayed erasure deletes its kind, plan,
    recipe and sketch again, and the replayed creature tombstone purges its container from the
    looks namespace, which a restore does not roll back."""
    creature, actor, looks = _kept_creature(purged, tmp_path, "restored ten legs")
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: _erase(purged, creature, actor),
        current=lambda: _creature_held(purged, creature),
    )
    container = creature.sketch.document["container"]["sha256"]
    assert not looks.exists(BlobId.from_hex(container)), "the replay purged the container"
    [row] = purged.rows(
        "select count(*) filter (where scope::text = 'creature') as tombstones, "
        "(select count(*) from thing_erasure) as erasures from tombstone"
    )
    # The checkpoint's tombstone and its replay copy, and the one erasure the restore carried.
    assert (row["tombstones"], row["erasures"]) == (2, 1)


def test_a_restore_of_a_creature_erased_and_kept_again_leaves_its_file_held(
    purged, commands, tmp_path
):
    """A backup taken after a creature was erased and kept again from the same document holds the
    look again, naming the file the erasure enqueued. The replayed creature tombstone's job waits
    unclaimed as the original's does, so the replay completes and names the container left open,
    held by that look, rather than refusing; the file and the creature stay."""
    creature, actor, looks = _kept_creature(purged, tmp_path, "kept again ten legs")
    container = creature.sketch.document["container"]["sha256"]
    _erase(purged, creature, actor)
    with purged.database().session(purged.workspace_id) as connection:
        ThingStore(connection, purged.workspace_id, looks).keep_creature(creature, created_by=actor)
    assert _creature_held(purged, creature), "the positive control: kept again before the backup"
    dump, blobs = _backup(purged, tmp_path)
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    assert _creature_held(purged, creature)
    assert looks.exists(BlobId.from_hex(container))
    [anchor] = purged.rows("select tombstone_id from thing_erasure")
    assert json.loads(marker.read_text())["left_open"] == {
        str(anchor["tombstone_id"]): [f"look:{container}"]
    }
    # The original's job and its replay copy's, both waiting on the file the look holds.
    jobs = purged.rows(
        "select pj.state, pj.target_ref from purge_job pj join tombstone t "
        "on t.tombstone_id = pj.tombstone_id where t.scope::text = 'creature'"
    )
    assert [(job["state"], job["target_ref"]) for job in jobs] == [("queued", container)] * 2


def test_a_creature_erased_after_a_backup_holding_its_withdrawn_sketch_stays_erased(
    purged, commands, tmp_path
):
    """A sketch withdrawn before the backup is deleted by the creature's later erasure, so no
    checkpoint sealed after it carries that withdrawal; the restored database holds it, and the
    stale check passes it by because the checkpoint's own erasure deletes it on replay."""
    creature, actor, _looks = _kept_creature(purged, tmp_path, "withdrawn ten legs")
    with purged.database().session(purged.workspace_id) as connection:
        ThingStore(connection, purged.workspace_id, None).withdraw_look(
            creature.sketch.look, creature.sketch.version, "no longer worn", withdrawn_by=actor
        )
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: _erase(purged, creature, actor),
        current=lambda: _creature_held(purged, creature),
    )
    assert not purged.rows("select 1 from look_withdrawal")


def test_a_workspace_erased_after_a_backup_holding_a_withdrawn_look_is_restored(
    purged, commands, tmp_path
):
    """The same for a workspace's own erasure: its tombstone deletes the withdrawal the backup
    holds, and the restore replays the tombstone rather than refusing the checkpoint."""
    creature, actor, _looks = _kept_creature(purged, tmp_path, "withdrawn ten legs")
    with purged.database().session(purged.workspace_id) as connection:
        ThingStore(connection, purged.workspace_id, None).withdraw_look(
            creature.sketch.look, creature.sketch.version, "no longer worn", withdrawn_by=actor
        )

    def erase_the_workspace() -> None:
        purged.repository.insert_tombstone(
            scope="workspace", requested_by=actor, reason="the person left"
        )

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=erase_the_workspace,
        current=lambda: _creature_held(purged, creature),
    )
    assert not purged.rows("select 1 from look_withdrawal")


def test_a_workspace_erased_after_the_backup_has_its_creature_drafts_cancelled(
    purged, commands, tmp_path
):
    """A draft queued when the backup was taken holds its words in its job. The workspace's
    tombstone, written after the backup, is replayed by the restore as the owner, and its trigger
    cancels the draft and blanks the words again (exulanica/selection/creature_drafts.py)."""
    workspace = uuid.uuid4()
    words = "a gentle horse that walks the hills"
    with purged.database().session(workspace) as connection:
        draft = creature_drafts.create_draft(
            connection,
            workspace,
            offered_to={workspace},
            owner_actor_id=uuid.uuid4(),
            words=words,
            sent=words,
            placeholders={},
        )

    def current() -> bool:
        [row] = purged.rows(
            "select d.status, j.state, j.payload from creature_draft d "
            "join job j on j.job_id = d.job_id where d.draft_id = %s",
            draft.draft_id,
        )
        held = row["payload"].get("sent") == words
        assert (row["status"] == "queued") is held and (row["state"] == "queued") is held
        assert held or (row["status"], row["state"]) == ("cancelled", "cancelled")
        return held

    def erase() -> None:
        with purged.database().session(workspace) as connection:
            connection.execute(
                "insert into tombstone (workspace_id, scope, requested_by, reason) "
                "values (%s, 'workspace', %s, 'the person left')",
                (workspace, uuid.uuid4()),
            )

    assert not _through_a_restore(purged, tmp_path, withdraw=erase, current=current)


def test_a_character_catalog_withdrawn_after_the_backup_stays_withdrawn(purged, commands, tmp_path):
    """The host's withdrawal is final (migration 0131), so a restore may not serve it again."""
    connection = purged.repository.connection
    layered = catalog_documents()[0]
    digest = read_publication_document(layered).catalog_sha256
    keys = sorted({item.manifest.asset_key for item in catalog_imports(layered)})
    held = {
        row["asset_key"]
        for row in purged.rows(
            "select asset_key from world_reviewed_asset where asset_key = any(%s)", keys
        )
    }
    registry = CatalogRegistry()
    with connection.transaction():
        publish_catalogs(connection, LocalContentAddressedStore(tmp_path / "people"), [layered])
    connection.commit()

    def withdraw() -> None:
        with connection.transaction():
            assert withdraw_catalog(connection, digest, "licence_withdrawn") == "withdrawn"
        connection.commit()

    def current() -> bool:
        return digest in {p.catalog_sha256 for p in registry.served(connection).publications}

    try:
        assert not _through_a_restore(purged, tmp_path, withdraw=withdraw, current=current)
    finally:
        # world_reviewed_asset is kept between tests; the keys this test added leave with it.
        with connection.transaction():
            connection.execute(
                "delete from world_reviewed_asset where asset_key = any(%s)",
                (sorted(set(keys) - held),),
            )
        connection.commit()


def test_a_character_catalog_published_and_withdrawn_after_the_backup_stays_withdrawn(
    purged, commands, tmp_path
):
    """The backup predates the publication, so the restored database holds nothing the withdrawal
    ends. Replay writes it all the same (0135, "absent": "carry"), and the catalogs job's next
    publish records the image's copy as withdrawn instead of serving it again."""
    connection = purged.repository.connection
    layered = catalog_documents()[0]
    digest = read_publication_document(layered).catalog_sha256
    keys = sorted({item.manifest.asset_key for item in catalog_imports(layered)})
    held = {
        row["asset_key"]
        for row in purged.rows(
            "select asset_key from world_reviewed_asset where asset_key = any(%s)", keys
        )
    }
    registry = CatalogRegistry()
    store = LocalContentAddressedStore(tmp_path / "people")

    def publish() -> str:
        """What the catalogs job runs on every start."""
        with connection.transaction():
            [outcome] = publish_catalogs(connection, store, [layered])
        connection.commit()
        return outcome.state

    def served() -> bool:
        return digest in {p.catalog_sha256 for p in registry.served(connection).publications}

    try:
        dump, blobs = _backup(purged, tmp_path)
        assert publish() == "published" and served(), "the positive control: served at the source"
        with connection.transaction():
            assert withdraw_catalog(connection, digest, "licence_withdrawn") == "withdrawn"
        connection.commit()
        assert not served(), "the withdrawal took effect at the source"
        carried = read_withdrawals(connection)
        source, marker = _seal(tmp_path)
        _restore(purged, dump, blobs)
        assert purged.rows("select 1 from character_catalog_publication") == [], (
            "the backup holds no publication of it"
        )
        _replay(source, marker)
        verify_restore(purged.database(), marker)
        assert [
            r["catalog_sha256"]
            for r in purged.rows("select catalog_sha256 from character_catalog_withdrawal")
        ] == [digest], "replay wrote the withdrawal with nothing to end"
        assert publish() == "withdrawn", "the next start records it and keeps it withdrawn"
        assert not served()
        # The custody rule asks the same question of every export after this restore.
        from exulanica.deletion.withdrawals import open_withdrawals

        assert open_withdrawals(connection, carried) == []
    finally:
        with connection.transaction():
            connection.execute(
                "delete from world_reviewed_asset where asset_key = any(%s)",
                (sorted(set(keys) - held),),
            )
        connection.commit()


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


def test_a_creator_grant_revoked_after_the_backup_stays_revoked(purged, commands, tmp_path):
    """A revocation is written again, so a restore never hands a creator's uploads back."""
    token, user = _signed_in(purged)
    connection = purged.repository.connection
    accounts = AccountRepository(connection)
    assert creator_grants.grant(connection, user, reason="invited_creator", operator="ops")
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: creator_grants.revoke(
            connection, user, reason="creator_left", operator="ops"
        ),
        current=lambda: accounts.session(token).creator,
    )


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

    class stopped:
        """However replay builds its worker, the purge never starts."""

        def __init__(self, *args, **kwargs):
            raise Interrupted("the purge never started")

        @classmethod
        def over(cls, *args, **kwargs):
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


def test_a_style_pack_withdrawn_after_the_backup_stays_withdrawn(purged, commands, tmp_path):
    packs = Packs(purged, tmp_path)
    pack = admitted()
    try:
        packs.ready(pack)
    finally:
        packs.close()

    def repository(connection):
        return Packs.repository_on(connection, packs)

    def current() -> bool:
        with purged.database().session(purged.workspace_id) as connection:
            row = connection.execute(
                "select workspace_style_pack_wearable(%s, %s) as wearable",
                (purged.workspace_id, pack.manifest_sha256),
            ).fetchone()
        return bool(row["wearable"])

    def withdraw() -> None:
        with packs.runtime.session(purged.workspace_id) as connection:
            assert repository(connection).withdraw(pack.manifest_sha256)

    assert not _through_a_restore(purged, tmp_path, withdraw=withdraw, current=current)


def _wearable(purged, manifest_sha256: str) -> bool:
    with purged.database().session(purged.workspace_id) as connection:
        row = connection.execute(
            "select workspace_style_pack_wearable(%s, %s) as wearable",
            (purged.workspace_id, manifest_sha256),
        ).fetchone()
    return bool(row["wearable"])


def _base_and_dependent(*, base_sorts_first: bool):
    """A base pack and a pack drawn on it, chosen so their digests sort as asked: the restore
    replays a kind's rows in an order of its own, and both orders must carry."""
    from test_workspace_style_packs_postgres import admitted, base_of

    for salt in range(64):
        base = admitted("maker.barn", salt=str(salt))
        dependent = admitted("maker.barn-night", salt=str(salt), base=base_of(base))
        if (base.manifest_sha256 < dependent.manifest_sha256) == base_sorts_first:
            return base, dependent
    raise AssertionError("no salt gave the digest order asked for")


@pytest.mark.parametrize("base_sorts_first", [True, False], ids=["base first", "dependent first"])
def test_a_base_and_the_pack_drawn_on_it_withdrawn_after_the_backup_stay_withdrawn(
    purged, commands, tmp_path, base_sorts_first
):
    base, dependent = _base_and_dependent(base_sorts_first=base_sorts_first)
    packs = Packs(purged, tmp_path)
    try:
        packs.ready(base)
        packs.ready(dependent)
    finally:
        packs.close()

    def withdraw() -> None:
        # The dependent first, as the guard requires of the product too.
        with packs.runtime.session(purged.workspace_id) as connection:
            repository = Packs.repository_on(connection, packs)
            assert repository.withdraw(dependent.manifest_sha256)
            assert repository.withdraw(base.manifest_sha256)

    def current() -> bool:
        return _wearable(purged, base.manifest_sha256) or _wearable(
            purged, dependent.manifest_sha256
        )

    assert not _through_a_restore(purged, tmp_path, withdraw=withdraw, current=current)
    withdrawn = purged.rows(
        "select manifest_sha256 from workspace_style_pack_withdrawal order by manifest_sha256"
    )
    assert [row["manifest_sha256"] for row in withdrawn] == sorted(
        [base.manifest_sha256, dependent.manifest_sha256]
    )


def test_a_base_withdrawn_after_its_dependent_was_refused_stays_withdrawn(
    purged, commands, tmp_path
):
    base, dependent = _base_and_dependent(base_sorts_first=True)
    packs = Packs(purged, tmp_path)
    try:
        packs.ready(base)
        packs.repository().record(dependent)  # still waiting for its check at the backup
    finally:
        packs.close()

    def withdraw() -> None:
        with packs.runtime.session(purged.workspace_id) as connection:
            repository = Packs.repository_on(connection, packs)
            claimed = repository.claim("test-worker", 60)
            assert claimed is not None and claimed[0] == dependent.manifest_sha256
            repository.finish_failed(claimed[0], claimed[1], "refused", "a stray colour", {})
            # A refused dependent does not hold its base, so the base may be withdrawn.
            assert repository.withdraw(base.manifest_sha256)

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=withdraw,
        current=lambda: _wearable(purged, base.manifest_sha256),
    )
    # The restored database held the dependent as waiting; the replay cancelled it, as its check
    # would have ended had it run after the base was withdrawn.
    [state] = purged.rows(
        "select state, failure_class from workspace_style_pack_preparation "
        "where manifest_sha256 = %s",
        dependent.manifest_sha256,
    )
    assert (state["state"], state["failure_class"]) == ("cancelled", "base_unavailable")


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_society_erased_after_the_backup_stays_erased(purged, saved_world, commands, tmp_path):
    """A workspace's erasure of a world's society (migration "a society is erased whole") is carried
    by a restore: the backup holds the society and a Companion answer that cited its version; the
    carried erasure deletes the society's rows again, and the society tombstone replayed after it
    withdraws the answer again, by the version the erasure names, since the society's rows are gone
    by then (the catalog carries only a person's own withdrawal of an answer)."""
    world, binding = saved_world, saved_world["binding"]
    set_workspace(world["connection"], world["workspace"])
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, _document = create_society(world)
    world["connection"].commit()
    with purged.database().session(purged.workspace_id) as connection:
        answer = CompanionMemoryRepository(connection, purged.workspace_id, ACCOUNT).record_answer(
            _answer(
                question="Who is resting?",
                answer_text="Nobody is resting.",
                world_id=binding.world_id,
                simulation_citations=(
                    SimulationCitation(
                        ordinal=0,
                        result_kind="synthetic_inhabitant",
                        version_id=binding.version_id,
                        inhabitant_id=uuid.uuid4(),
                        event_id=None,
                        tick=0,
                    ),
                ),
            )
        )

    def held() -> bool:
        [row] = purged.rows(
            "select count(*) as n from world_society where workspace_id = %s and society_id = %s",
            purged.workspace_id,
            society["society_id"],
        )
        return row["n"] == 1

    def erase() -> None:
        with purged.database().session(purged.workspace_id) as connection:
            erase_society(
                connection,
                purged.workspace_id,
                binding.world_id,
                binding.version_id,
                erased_by=ACCOUNT,
            )

    assert not _through_a_restore(purged, tmp_path, withdraw=erase, current=held)
    [row] = purged.rows(
        "select a.status::text as status, t.scope::text as scope, "
        "(select count(*) from society_erasure) as erasures, "
        "(select count(*) from world_society_input where society_id = %s) as inputs "
        "from companion_answer a left join tombstone t on t.tombstone_id = a.withdrawn_by "
        "where a.answer_id = %s",
        society["society_id"],
        answer.answer_id,
    )
    # The answer withdrawn again by the society's tombstone, the one erasure carried, and none of
    # the society's records left.
    assert (row["status"], row["scope"], row["erasures"], row["inputs"]) == (
        "withdrawn",
        "society",
        1,
        0,
    )
