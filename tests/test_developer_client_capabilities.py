"""The developer client reads what each kind of world supports and makes an edit it was told of.

The client in ``clients/python`` runs as a separate process with no site-packages, against the real
application served on a loopback socket as a deployment runs it (a runtime role, row-level security
on, the society runtime built). Its token holds ``world.read`` and ``world.write`` only. The
workspace already holds a starter world, a generated town and a world made from photographs; the
client reads both capability routes for them and checks every route they name against the server's
own OpenAPI document.

With ``--exercise`` it makes a world of its own (a generated town, since the workspace holds saved
worlds) and makes there the edit the read calls available, bound to that world's saved entry. It
sends the same request again against the base it replaced, which the server refuses by name, and
reads the base again. Every saved world that was there before still opens as it did. With
``--world`` naming the starter, it edits that world instead: an arrangement previewed and applied.
It warns that the starter's saved entry then needs its new version adopted, and the entries read
says so. The results are held to the repository and the entries read, not to the client's account.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import uuid
from pathlib import Path

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


def _capabilities(url: str, token: str, transcript: Path, *extra: str):
    """The client's capabilities command with --exercise, as a separate process."""
    return subprocess.run(
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
            *extra,
            "--transcript",
            str(transcript),
        ],
        cwd=CLIENT_ROOT,
        env={"EXULANICA_TOKEN": token, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=300,
    )


def _entries(api) -> dict[str, dict]:
    """The workspace's saved worlds as the entries read serves them, by world."""
    response = api.get("/world-entries")
    assert response.status_code == 200, response.text
    return {entry["world_id"]: entry for entry in response.json()}


def test_the_client_is_told_what_each_kind_supports_and_edits_by_it(request, tmp_path):
    api = request.getfixturevalue("imported_made")
    starter = api.post("/world-entries/starter", {"title": "Starter"}).json()
    town = traffic._made(api, "Town")
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    made = personal.make_world(api)
    before = _entries(api)
    assert {entry["availability"] for entry in before.values()} == {"available"}

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
    own, named = tmp_path / "capabilities.json", tmp_path / "named-world.json"
    with _serving(create_app(services, verify=False)) as url:
        run = _capabilities(url, client_token, own)
        between = _entries(api)
        naming = _capabilities(url, client_token, named, "--world", starter["world_id"])
    after = _entries(api)

    assert run.returncode == 0, run.stdout + run.stderr
    record = json.loads(own.read_text())
    assert record["result"] == "confirmed"
    assert all(check["holds"] for check in record["checks"]), record["checks"]
    assert client_token not in own.read_text()

    kinds = {row["kind"]: row for row in record["capabilities"]["creation"]["kinds"]}
    # This token may not read admission, so whether a world can be made from photographs is not
    # known to it; it is told so rather than told yes or no.
    assert kinds["personal-source"]["create"]["state"] == "unknown"
    assert kinds["personal-source"]["create"]["permitted"] is False
    worlds = {world["world_id"]: world for world in record["capabilities"]["worlds"]}
    assert set(worlds) == {starter["world_id"], town["world_id"], made["world_id"]}
    assert {world["capabilities"]["kind"] for world in worlds.values()} == {
        "authored-starter",
        "generated",
        "personal-source",
    }
    for world in worlds.values():
        for descriptor in world["capabilities"]["operations"]:
            if "model.invoke" in descriptor["requires"]:
                assert descriptor["permitted"] is False, descriptor["operation"]

    # A workspace that holds saved worlds takes no starter, so the run made a town of its own and
    # edited that world alone. A town's people walk its own records, so no arrangement: an object.
    own_world = record["made"]["world_id"]
    assert record["made"]["source_kind"] == "generated"
    (done,) = record["exercised"]
    assert done["kind"] == "generated"
    assert done["applied"] == "POST /world/versions/{version_id}/objects"
    assert done["stale"]["code"] == "stale_object_base"
    # Every saved world that was there before opens as it did; the run's own world opens where its
    # bound edit left it.
    for world_id, entry in before.items():
        assert between[world_id]["availability"] == "available", entry["title"]
        assert between[world_id]["revision"] == entry["revision"], entry["title"]
    assert between[own_world]["availability"] == "available"
    # Held against the repository: the object is in the run's own world, in a region its source
    # holds.
    objects = WorldObjectRepository(
        api.repository.connection, api.repository.workspace_id, world_id=own_world
    )
    version = uuid.UUID(between[own_world]["authored_version_id"])
    stored = objects.version(version)
    assert stored.objects
    assert {obj.region_id for obj in stored.objects} <= objects.source_facts(version).region_ids

    # Named, an existing world is edited, unbound, with a warning; its saved entry then needs its
    # new version adopted, exactly as the warning says. The other saved worlds are untouched.
    assert naming.returncode == 0, naming.stdout + naming.stderr
    named_record = json.loads(named.read_text())
    assert named_record["result"] == "confirmed"
    assert named_record["made"] is None
    assert "'Starter'" in named_record["warning"] and "adopted" in named_record["warning"]
    assert f"warning: {named_record['warning']}" in naming.stdout
    (edited,) = named_record["exercised"]
    assert edited["kind"] == "authored-starter"
    assert edited["applied"] == "POST /world/versions/{version_id}/arrangements/apply"
    assert edited["stale"] == {
        "status": 409,
        "code": "arrangement_refused",
        "detail": "stale_base",
    }
    assert (
        after[starter["world_id"]]["availability"],
        after[starter["world_id"]]["unavailable_reason"],
    ) == ("unavailable", "authored_version_changed")
    for world_id in (town["world_id"], made["world_id"], own_world):
        assert after[world_id]["availability"] == "available", world_id
