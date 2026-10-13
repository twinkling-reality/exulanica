"""A restarted polling process never serves a kind draft after its result is erased."""

from __future__ import annotations

import pytest
from exulanica.world.kind_draft_jobs import KindDraftRepository
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.erasure import erase_kind
from exulanica.world.kinds.samples import check_samples
from exulanica.world.world_draft_jobs import WorldDraftRefused
from fastapi.testclient import TestClient

from test_purge import purged as purged
from test_world_kind_erasure_postgres import _context
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres


def test_polling_durable_draft_distinguishes_pending_kind_from_erased_kind(purged):
    app, headers, workspace, actor = _context(purged)
    kind = read_kind(_uploaded("farm"))
    report = check_samples(kind)
    with purged.database().session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        ident = repo.submit(
            actor=actor,
            description="A private place description",
            guest=False,
            starts_maximum=12,
            workspace_maximum=1,
            deadline_seconds=600,
            manifest_sha256="a" * 64,
            prompt_version="private-fixture",
        )
        claimed = repo.claim()
        assert claimed is not None
    path = f"/worlds/kinds/drafts/{ident}"
    with TestClient(app) as client:
        pending = client.get(path, headers=headers)
        assert pending.status_code == 200, pending.text
        assert pending.json()["state"] == "drafting"
        assert pending.json()["description"] == "A private place description"
        with purged.database().session(workspace) as connection:
            KindDraftRepository(connection, workspace).publish(
                claimed,
                kind,
                report,
                calls=[],
                model_id=None,
            )
        ready = client.get(path, headers=headers)
        assert ready.status_code == 200 and ready.json()["state"] == "ready"
        assert ready.json()["description"] == ""
        # Erasure commits in another process, without touching this reader's local holder.
        with purged.database().session(workspace) as connection:
            erase_kind(connection, workspace, kind.sha256, erased_by=actor)
        assert client.get(path, headers=headers).status_code == 404
        assert not client.get("/worlds/kinds/drafts", headers=headers).json()["drafts"]
        with (
            purged.database().session(workspace) as connection,
            pytest.raises(WorldDraftRefused, match="lease_lost"),
        ):
            KindDraftRepository(connection, workspace).publish(
                claimed,
                kind,
                report,
                calls=[],
                model_id=None,
            )
