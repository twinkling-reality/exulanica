"""An application over the spine with two workspaces and declared capacity limits, for R1's tests.

Built as the other API tests build theirs: a hand-constructed ``Services`` over the harness's
throwaway schema, bearer grants in ``EXULANICA_API_TOKENS``, and no lifespan unless a test enters a
``TestClient``. The raw-ASGI tests call the application directly, so nothing is started beside it.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from exulanica.api.admission import AdmissionSettings
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.session import Database
from exulanica.store.local import LocalContentAddressedStore

from tests_support_api import EVERY_PERMISSION, scratch_database

__all__ = ["FIRST_TOKEN", "SECOND_TOKEN", "Served", "auth", "serve"]

FIRST_TOKEN = "capacity-first-workspace-token-long-enough"
SECOND_TOKEN = "capacity-second-workspace-token-long-enough"


def auth(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode())]


@dataclass
class Served:
    """What a capacity test needs: the two workspaces, the database, and an application factory."""

    first: uuid.UUID
    second: uuid.UUID
    database: Database
    store_root: Path
    repository: Any
    apps: list[Any] = field(default_factory=list)

    def app(self, **limits: int) -> Any:
        services = Services(
            database=self.database,
            readonly_database=self.database,
            store=LocalContentAddressedStore(self.store_root),
            tokens=load_token_directory(),
            executor_shares_the_write_role=True,
            model_client=None,
            admission=AdmissionSettings(**limits),
        )
        app = create_app(services, verify=False)
        self.apps.append(app)
        return app

    def upload(self, app: Any, token: str = FIRST_TOKEN, count: int = 1) -> dict[str, Any]:
        """``POST /intake`` of ``count`` distinct photographs, through a client of its own."""
        from fastapi.testclient import TestClient

        from conftest import photo_bytes

        parts = [
            ("files", (f"p{index}.jpg", photo_bytes(size=(160 + index, 100)), "image/jpeg"))
            for index in range(count)
        ]
        response = TestClient(app).post(
            "/intake", files=parts, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 202, response.text
        return response.json()

    def drain(self) -> None:
        """Screen every capture as synthetic, then run the derivative worker to exhaustion."""
        from exulanica.ingest.privacy import (
            authorize_synthetic_capture,
            record_synthetic_exemption,
        )
        from exulanica.ingest.worker import DerivativeWorker

        from conftest import CountingVisionModel

        rows = self.repository.connection.execute(
            "select capture_id from capture where deleted_at is null"
        ).fetchall()
        for row in rows:
            authorization = authorize_synthetic_capture(
                self.repository,
                capture_id=row["capture_id"],
                actor=uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720"),
                generator_manifest={
                    "profile": "exulanica.synthetic-test-corpus/v1",
                    "notice": "SYNTHETIC TEST FIXTURE",
                },
                authorization_scope={"purpose": "runtime capacity test"},
            )
            record_synthetic_exemption(
                self.repository, authorization_id=authorization.authorization_id
            )
        DerivativeWorker(
            self.database,
            LocalContentAddressedStore(self.store_root),
            frozenset({self.first}),
            vision=CountingVisionModel(),
            name="capacity-drain",
        ).drain()

    def backends(self) -> int:
        """Client connections open on this database right now, the harness's own included."""
        with psycopg.connect(self.database.url) as connection:
            row = connection.execute(
                "select count(*) from pg_stat_activity "
                "where backend_type = 'client backend' and datname = current_database()"
            ).fetchone()
        assert row is not None
        return int(row[0])


def serve(tmp_path: Path, repository: Any, spine_schema: Any, monkeypatch: Any) -> Served:
    _psycopg, scratch = spine_schema
    first = repository.workspace_id
    second = uuid.uuid4()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {
                    "workspace_id": str(workspace),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                }
                for token, workspace in ((FIRST_TOKEN, first), (SECOND_TOKEN, second))
            }
        ),
    )
    return Served(
        first=first,
        second=second,
        database=scratch_database(scratch),
        store_root=tmp_path / "blobs",
        repository=repository,
    )
