"""Migration 0116: a comparison's second version is admitted beside its first, which loses nothing.

A schema of this test's own is migrated to just below 0116 with the migrations exactly as they are
on disk and given a first-version comparison: a definition, a run and a completed outcome. Then
0116 itself is applied. What is held: the first-version rows are as they were and a first-version
definition and outcome are still admitted; a second-version definition, refused before 0116, is
admitted after it only when it names its group and everybody else; an unknown profile is refused
by the check that admitted the first; and a completed outcome is admitted only under a definition
of its own version, either way round. A definition's own foreign keys are left out of the
arrangement (the society a real definition binds is not what 0116 changes); every other rule,
the checks and the triggers of runs and outcomes, runs as deployed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from exulanica.migrations import migrations
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import pg_harness

pytestmark = pytest.mark.postgres

MIGRATION = next(migration for migration in migrations() if migration.version == "0116")
WORKSPACE = uuid.UUID("7a9d6c2e-0b8f-4c1d-9a3e-5f2b1c0d4e6a")
WORLD = "world:authored:0116-migration"
SEED = "0116" * 16
DIGEST = hashlib.sha256(SEED.encode()).hexdigest()
FIRST, SECOND = "exulanica.society-comparison/v1", "exulanica.society-comparison/v2"
RUN_FIRST, RUN_SECOND = "exulanica.society-comparison-run/v1", "exulanica.society-comparison-run/v2"
#: The arms a definition here names: one run of each on the one seed.
ARMS = ("a", "b", "c", "d")


@contextmanager
def _below_0116(monkeypatch) -> Iterator[psycopg.Connection]:
    everything = list(migrations())
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < "0116")
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            admin.commit()
            admin.autocommit = True
            admin.row_factory = dict_row
            admin.execute(
                "select set_config('exulanica.workspace_id', %s, false)", (str(WORKSPACE),)
            )
            admin.execute(
                "insert into world_identity(workspace_id,world_id,kind,provenance,created_by) "
                "values(%s,%s,'authored-starter',%s,%s)",
                (WORKSPACE, WORLD, Jsonb({"origin": "test"}), uuid.uuid4()),
            )
            yield admin


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "document_sha256"}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {**body, "document_sha256": digest}


def _definition(admin: psycopg.Connection, profile: str, **fields: Any) -> uuid.UUID:
    """A definition row, its own foreign keys to the society left out of the arrangement."""
    comparison_id, version_id, society_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    document = _sealed(
        {
            "profile": profile,
            "world_id": WORLD,
            "version_id": str(version_id),
            "society_id": str(society_id),
            "input": {"input_seq": 1, "document_sha256": "1" * 64},
            "phase": "development",
            "seeds": [DIGEST],
            "arms": {key: {"role": "candidate"} for key in ARMS},
            "preregistration": None,
            **fields,
        }
    )
    admin.execute("set session_replication_role = replica")
    try:
        admin.execute(
            "insert into society_comparison(workspace_id,world_id,comparison_id,version_id,"
            "society_id,input_seq,input_sha256,document,document_sha256,created_by) "
            "values(%s,%s,%s,%s,%s,1,%s,%s,%s,%s)",
            (
                WORKSPACE,
                WORLD,
                comparison_id,
                version_id,
                society_id,
                "1" * 64,
                Jsonb(document),
                document["document_sha256"],
                uuid.uuid4(),
            ),
        )
    finally:
        admin.execute("set session_replication_role = origin")
    return comparison_id


def _definition_sha256(admin: psycopg.Connection, comparison_id: uuid.UUID) -> str:
    return admin.execute(
        "select document_sha256 from society_comparison where workspace_id=%s and world_id=%s "
        "and comparison_id=%s",
        (WORKSPACE, WORLD, comparison_id),
    ).fetchone()["document_sha256"]


def _run(admin: psycopg.Connection, comparison_id: uuid.UUID, arm: str) -> uuid.UUID:
    run_id = uuid.uuid4()
    admin.execute(
        "insert into society_comparison_run(workspace_id,world_id,comparison_id,run_id,arm,seed,"
        "seed_digest,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s)",
        (WORKSPACE, WORLD, comparison_id, run_id, arm, SEED, DIGEST, uuid.uuid4()),
    )
    return run_id


def _outcome(
    admin: psycopg.Connection,
    comparison_id: uuid.UUID,
    profile: str,
    *,
    arm: str,
    status: str = "completed",
) -> None:
    run_id = _run(admin, comparison_id, arm)
    document = _sealed(
        {
            "profile": profile,
            "status": status,
            "run_id": str(run_id),
            "definition_sha256": _definition_sha256(admin, comparison_id),
            "arm": arm,
            "seed_digest": DIGEST,
            "receipts": {"count": 0, "sha256": "2" * 64},
        }
    )
    admin.execute(
        "insert into society_comparison_outcome(workspace_id,world_id,comparison_id,run_id,"
        "status,document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s)",
        (
            WORKSPACE,
            WORLD,
            comparison_id,
            run_id,
            status,
            Jsonb(document),
            document["document_sha256"],
        ),
    )


GROUP = {
    "group": {
        "people": [{"id": str(uuid.uuid4()), "name": "A person"}],
        "source": {"kind": "named"},
    },
    "others": [],
}


def _refused_by(admin: psycopg.Connection, name: str, action) -> None:
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        action()
    assert refused.value.diag.constraint_name == name


def test_0116_admits_the_second_version_beside_the_first_and_drops_nothing(monkeypatch):
    with _below_0116(monkeypatch) as admin:
        first = _definition(admin, FIRST)
        _outcome(admin, first, RUN_FIRST, arm="a")
        # The arm before the migration: a second-version definition is refused, by 0113's check.
        _refused_by(
            admin, "society_comparison_document_check1", lambda: _definition(admin, SECOND, **GROUP)
        )
        before = admin.execute(
            "select comparison_id, document from society_comparison where workspace_id=%s "
            "and world_id=%s order by comparison_id",
            (WORKSPACE, WORLD),
        ).fetchall()
        outcomes = admin.execute(
            "select run_id, document from society_comparison_outcome where workspace_id=%s "
            "and world_id=%s order by run_id",
            (WORKSPACE, WORLD),
        ).fetchall()
        admin.execute(MIGRATION.sql)
        # The first-version rows are as they were.
        assert (
            before
            == admin.execute(
                "select comparison_id, document from society_comparison where workspace_id=%s "
                "and world_id=%s order by comparison_id",
                (WORKSPACE, WORLD),
            ).fetchall()
        )
        assert (
            outcomes
            == admin.execute(
                "select run_id, document from society_comparison_outcome where workspace_id=%s "
                "and world_id=%s order by run_id",
                (WORKSPACE, WORLD),
            ).fetchall()
        )
        # A first-version definition and outcome are still admitted.
        again = _definition(admin, FIRST)
        _outcome(admin, again, RUN_FIRST, arm="a")
        # A second-version one is admitted when it names its group and everybody else.
        second = _definition(admin, SECOND, **GROUP)
        _outcome(admin, second, RUN_SECOND, arm="a")
        _refused_by(admin, "society_comparison_names_its_group", lambda: _definition(admin, SECOND))
        _refused_by(
            admin,
            "society_comparison_names_its_group",
            lambda: _definition(admin, SECOND, group={"people": [], "source": {}}, others=[]),
        )
        _refused_by(
            admin,
            "society_comparison_document_check1",
            lambda: _definition(admin, "exulanica.society-comparison/v9", **GROUP),
        )


def test_a_completed_outcome_is_admitted_only_under_a_definition_of_its_own_version(monkeypatch):
    with _below_0116(monkeypatch) as admin:
        admin.execute(MIGRATION.sql)
        first = _definition(admin, FIRST)
        second = _definition(admin, SECOND, **GROUP)
        # The positive controls: each version's outcome under its own definition.
        _outcome(admin, first, RUN_FIRST, arm="a")
        _outcome(admin, second, RUN_SECOND, arm="a")
        for comparison_id, wrong in ((first, RUN_SECOND), (second, RUN_FIRST)):
            with pytest.raises(psycopg.errors.CheckViolation, match="outcome binding mismatch"):
                _outcome(admin, comparison_id, wrong, arm="b")
        # A failed outcome is the one failure profile under either version, as before.
        _outcome(admin, second, "exulanica.society-comparison-failure/v1", arm="c", status="failed")
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            _outcome(admin, second, RUN_SECOND, arm="d", status="failed")
        assert refused.value.diag.constraint_name == "society_comparison_outcome_check3"
