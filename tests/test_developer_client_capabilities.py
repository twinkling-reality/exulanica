"""The developer client reads what each kind of world supports and makes an edit it was told of.

The client in ``clients/python`` runs as a separate process with no site-packages, against the real
application served on a loopback socket as a deployment runs it (a runtime role, row-level security
on, the society runtime built). Its token holds ``world.read`` and ``world.write`` only. It reads
both capability routes for a starter world, a generated town and a world made from photographs,
checks every route they name against the server's own OpenAPI document, and in each world makes the
edit the read calls available: an arrangement previewed and applied where one is, otherwise a
reviewed object in a listed region. It sends the same request again against the base it replaced,
which the server refuses by name, and reads the base again. The result is held to the repository.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.world import WorldObjectRepository

import personal_world_support as personal
import test_world_traffic_route as traffic
from test_developer_client import CLIENT_GRANT, CLIENT_ROOT, _serving
from test_society_made_world import made as imported_made  # noqa: F401
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres
_presets_try_every_candidate = traffic._presets_try_every_candidate


def test_the_client_is_told_what_each_kind_supports_and_edits_by_it(request, tmp_path):
    api = request.getfixturevalue("imported_made")
    starter = api.post("/world-entries/starter", {"title": "Starter"})
    assert starter.status_code == 200, starter.text
    town = traffic._made(api, "Town")
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    made = personal.make_world(api)

    client_token = f"client-{uuid.uuid4().hex}"
    grants = {
        personal.OWNER_TOKEN: {
            "workspace_id": str(api.repository.workspace_id),
            "actor": str(api.actor),
            "permissions": EVERY_PERMISSION,
        },
        client_token: {
            "workspace_id": str(api.repository.workspace_id),
            "actor": str(uuid.uuid4()),
            "permissions": CLIENT_GRANT,
        },
    }
    services = dataclasses.replace(
        api.client.app.state.services,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
    )
    transcript = tmp_path / "capabilities.json"
    with _serving(create_app(services, verify=False)) as url:
        run = subprocess.run(
            [
                sys.executable,
                "-S",
                "-s",
                "-E",
                "-m",
                "exulanica_client",
                "capabilities",
                "--base-url",
                url,
                "--exercise",
                "--origin-role",
                "fictional",
                "--transcript",
                str(transcript),
            ],
            cwd=CLIENT_ROOT,
            env={"EXULANICA_TOKEN": client_token, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=300,
        )
    assert run.returncode == 0, run.stdout + run.stderr
    record = json.loads(transcript.read_text())
    assert record["result"] == "confirmed"
    assert all(check["holds"] for check in record["checks"]), record["checks"]
    assert client_token not in transcript.read_text()

    kinds = {row["kind"]: row for row in record["capabilities"]["creation"]["kinds"]}
    # This token may not read admission, so whether a world can be made from photographs is not
    # known to it; it is told so rather than told yes or no.
    assert kinds["personal-source"]["create"]["state"] == "unknown"
    assert kinds["personal-source"]["create"]["permitted"] is False
    worlds = {world["world_id"]: world for world in record["capabilities"]["worlds"]}
    assert set(worlds) == {starter.json()["world_id"], town["world_id"], made["world_id"]}
    assert {world["capabilities"]["kind"] for world in worlds.values()} == {
        "authored-starter",
        "generated",
        "personal-source",
    }
    for world in worlds.values():
        for descriptor in world["capabilities"]["operations"]:
            if "model.invoke" in descriptor["requires"]:
                assert descriptor["permitted"] is False, descriptor["operation"]

    exercised = {done["kind"]: done for done in record["exercised"]}
    assert exercised["authored-starter"]["applied"] == (
        "POST /world/versions/{version_id}/arrangements/apply"
    )
    assert exercised["authored-starter"]["stale"] == {
        "status": 409,
        "code": "arrangement_refused",
        "detail": "stale_base",
    }
    # A town's people walk its own records, so no arrangement: the client placed an object instead.
    assert exercised["generated"]["applied"] == "POST /world/versions/{version_id}/objects"
    assert exercised["generated"]["stale"]["code"] == "stale_object_base"
    assert exercised["personal-source"]["stale"]["status"] == 409

    # Held against the repository, not the client's own account of what happened.
    for world_id, entry in (
        (town["world_id"], town),
        (made["world_id"], made),
    ):
        stored = WorldObjectRepository(
            api.repository.connection, api.repository.workspace_id, world_id=world_id
        ).version(uuid.UUID(entry["authored_version_id"]))
        assert stored.objects, world_id
        listed = worlds[world_id]["capabilities"]["regions"]["region_ids"]
        assert {obj.region_id for obj in stored.objects} <= set(listed)
