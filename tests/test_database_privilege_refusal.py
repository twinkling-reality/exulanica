"""A statement the API's database role may not run is refused by name, never answered as a crash.

The judge deployment's API connects as ``exulanica_judge``, which may read everything and write
only :data:`~exulanica.orchestration.judge_seed.JUDGE_WRITE_TABLES`. The judge's token still
permits routes whose writes fall outside that allowlist: making the starter world writes
``world_identity``, which the role may not. PostgreSQL refuses with SQLSTATE 42501, and before
``exulanica.api.app`` mapped it, that refusal reached the page as a bare 500.

So the application is run here as the judge role itself, provisioned by the deployment's own
:func:`~exulanica.orchestration.judge_seed.provision_judge_role` on a throwaway schema, with the
judge's own token permissions, and asked to make the starter world. The role name is suffixed,
because a role is a CLUSTER object (``tests/test_judge_seed.py`` gives the full reason).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.migrate import provision_workspace
from exulanica.orchestration.judge_seed import (
    JUDGE_PERMISSIONS,
    JUDGE_ROLE,
    JUDGE_WRITE_TABLES,
    provision_judge_role,
)
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from conftest import scratch_role_database
from pg_harness import migrated_schema

pytestmark = pytest.mark.postgres

#: Suffixed, because a role is a CLUSTER object; see the module docstring.
_JUDGE = f"{JUDGE_ROLE}_privilege_suite"
_TOKEN = "judge-privilege-refusal-token-long-enough-to-be-accepted"


@dataclass(frozen=True)
class JudgeApi:
    client: TestClient

    def post(self, path: str, body: object):
        return self.client.post(path, headers={"Authorization": f"Bearer {_TOKEN}"}, json=body)

    def get(self, path: str):
        return self.client.get(path, headers={"Authorization": f"Bearer {_TOKEN}"})


@pytest.fixture
def judge_api(tmp_path, monkeypatch) -> Iterator[JudgeApi]:
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        workspace = uuid.uuid4()
        admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
        provision_workspace(admin, workspace)
        provision_judge_role(admin, role=_JUDGE)
        admin.commit()
        monkeypatch.setenv(
            "EXULANICA_API_TOKENS",
            json.dumps(
                {
                    _TOKEN: {
                        "workspace_id": str(workspace),
                        "actor": str(uuid.uuid4()),
                        "permissions": list(JUDGE_PERMISSIONS),
                    }
                }
            ),
        )
        database = scratch_role_database(scratch, _JUDGE)
        services = Services(
            database=database,
            readonly_database=database,
            store=LocalContentAddressedStore(tmp_path / "blobs"),
            tokens=load_token_directory(),
            executor_shares_the_write_role=True,
            model_client=None,
        )
        with TestClient(create_app(services, verify=False)) as client:
            yield JudgeApi(client)


def test_the_judge_asking_for_a_starter_world_is_refused_by_name(judge_api, caplog, monkeypatch):
    # The precondition that makes this a grant gap rather than a permitted write: the table the
    # starter writes first is off the judge's allowlist. Should the allowlist grow to take it,
    # this test needs another route the judge's token permits and its role may not write.
    assert "world_identity" not in JUDGE_WRITE_TABLES
    # The creation routes now refuse such a role before any work (worlds_read_only,
    # tests/test_world_creation_guard.py). That probe reads one grant; a role holding it and
    # lacking a later table still reaches the database's refusal, which is what this holds.
    from exulanica.api.routes import world_entries

    monkeypatch.setattr(world_entries, "require_world_registration", lambda connection: None)

    with caplog.at_level(logging.ERROR, logger="exulanica.api.app"):
        response = judge_api.post("/world-entries/starter", {"title": "My world"})

    assert response.status_code == 403, response.text
    assert response.json() == {
        "code": "database_privilege_refused",
        "detail": "this instance's database role may not do what this request asked",
    }
    # A grant gap is a defect somewhere, so an operator is told which statement was refused.
    logged = [record for record in caplog.records if record.name == "exulanica.api.app"]
    assert [record.levelno for record in logged] == [logging.ERROR]
    message = logged[0].getMessage()
    assert "POST /world-entries/starter" in message
    assert "42501" in message
    assert "permission denied for table" in message
    # Nothing was made, so the page's next read still finds no world rather than half of one.
    listed = judge_api.get("/world-entries")
    assert listed.status_code == 200, listed.text
    assert listed.json() == []
