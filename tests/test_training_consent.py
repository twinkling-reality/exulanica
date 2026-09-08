"""Exact licensing terms never borrow a presentation grant or resurrect a withdrawal."""

import datetime as dt
import uuid
from dataclasses import replace

import pytest
from exulanica.consent.training import TrainingReceipt, TrainingTerms, training_is_granted
from psycopg.types.json import Jsonb

from pg_harness import migrated_schema

NOW = dt.datetime(2026, 9, 8, tzinfo=dt.UTC)
TERMS = TrainingTerms(
    "package", "licensee", ("world-model",), NOW, NOW + dt.timedelta(days=30), "a" * 64
)
ACTOR = str(uuid.UUID(int=1))


def receipt(decision="granted", sequence=0):
    return TrainingReceipt("person", TERMS, decision, ACTOR, sequence, NOW)


def test_an_empty_log_and_a_different_licensee_never_grant_training():
    assert not training_is_granted((), subject_id="person", terms=TERMS, at=NOW)
    assert not training_is_granted(
        (receipt(),), subject_id="person", terms=replace(TERMS, licensee="other"), at=NOW
    )
    assert training_is_granted((receipt(),), subject_id="person", terms=TERMS, at=NOW)


def test_withdrawal_dominates_later_grants_and_a_new_term():
    newer = replace(TERMS, terms_sha256="b" * 64)
    log = (receipt(), receipt("withdrawn", 1), replace(receipt(sequence=2), terms=newer))
    assert not training_is_granted(log, subject_id="person", terms=newer, at=NOW)
    assert not training_is_granted(
        (receipt(),), subject_id="person", terms=TERMS, at=NOW, withdrawn=True
    )


def test_future_decisions_expired_terms_and_revocations_do_not_grant():
    assert not training_is_granted(
        (replace(receipt(), decided_at=NOW + dt.timedelta(days=1)),),
        subject_id="person",
        terms=TERMS,
        at=NOW,
    )
    assert not training_is_granted(
        (receipt(),), subject_id="person", terms=TERMS, at=TERMS.valid_until
    )
    assert not training_is_granted(
        (receipt(), receipt("revoked", 1)), subject_id="person", terms=TERMS, at=NOW
    )
    assert training_is_granted(
        (receipt(), receipt("revoked", 1), receipt(sequence=2)),
        subject_id="person",
        terms=TERMS,
        at=NOW,
    )


def test_serialized_receipts_round_trip_without_changing_the_digest():
    assert TrainingReceipt.from_dict(receipt().as_dict()).digest == receipt().digest
    with pytest.raises(ValueError):
        TrainingTerms.from_dict({**TERMS.as_dict(), "model_classes": "world-model"})


@pytest.mark.postgres
def test_training_receipts_are_immutable_and_bind_their_indexed_subject():
    with migrated_schema() as (psycopg, conn):
        ws = uuid.uuid4()
        conn.execute("select set_config('exulanica.workspace_id', %s, true)", (str(ws),))
        r = receipt()
        values = (
            uuid.uuid4(),
            ws,
            r.subject_id,
            TERMS.package_id,
            TERMS.licensee,
            0,
            r.decision,
            bytes.fromhex(TERMS.digest),
            Jsonb(r.as_dict()),
            r.canonical,
            bytes.fromhex(r.digest),
            ACTOR,
            NOW,
        )
        sql = (
            "insert into training_use_consent "
            "(receipt_id,workspace_id,subject_id,package_id,licensee,sequence,decision,"
            "terms_digest,receipt_record,receipt_canonical,receipt_digest,actor,decided_at) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        )
        conn.execute(sql, values)
        assert conn.execute("select count(*) from training_use_consent").fetchone()[0] == 1
        with pytest.raises(psycopg.IntegrityError), conn.transaction():
            conn.execute("update training_use_consent set decision='revoked'")
        with pytest.raises(psycopg.IntegrityError), conn.transaction():
            conn.execute("delete from training_use_consent")
        with pytest.raises(psycopg.IntegrityError), conn.transaction():
            conn.execute(sql, (uuid.uuid4(), ws, "someone-else", *values[3:]))


@pytest.mark.postgres
def test_a_source_mutation_waits_for_an_export_in_its_workspace_only():
    """Execute the trigger under a held export lock, with a bounded wait and another workspace."""
    with migrated_schema() as (psycopg, conn):
        schema = conn.execute("select current_schema()").fetchone()[0]
        conn.commit()
        workspace = uuid.uuid4()
        with psycopg.connect(conn.info.dsn) as writer:
            writer.execute(f'SET search_path TO "{schema}", public')
            writer.commit()
            with conn.transaction():
                conn.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (f"training-source:{workspace}",),
                )
                with writer.transaction():
                    writer.execute("set local lock_timeout = '100ms'")
                    # A mutation in a different workspace is not delayed by this export.
                    writer.execute(
                        "insert into person_subject(subject_id,workspace_id,created_by) "
                        "values (%s,%s,%s)",
                        (uuid.uuid4(), uuid.uuid4(), uuid.UUID(ACTOR)),
                    )
                with pytest.raises(psycopg.errors.LockNotAvailable), writer.transaction():
                    writer.execute("set local lock_timeout = '100ms'")
                    writer.execute(
                        "insert into person_subject(subject_id,workspace_id,created_by) "
                        "values (%s,%s,%s)",
                        (uuid.uuid4(), workspace, uuid.UUID(ACTOR)),
                    )
            # The same insert succeeds once the export transaction releases its exclusive lock.
            with writer.transaction():
                writer.execute(
                    "insert into person_subject(subject_id,workspace_id,created_by) "
                    "values (%s,%s,%s)",
                    (uuid.uuid4(), workspace, uuid.UUID(ACTOR)),
                )
