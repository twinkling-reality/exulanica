"""Prepared character bodies over HTTP: requested, prepared by the queue, saved, drawn and refused.

The application runs as a provisioned runtime role (A2's ``workspace_asset_support``), with the
character runtime this host builds and the committed catalogs published on the owner connection.
The preparer runs a stand-in for Blender (the pattern of ``tests/test_character_preparation.py``)
that writes the committed body, so everything around the build is the product's: the pins a
request records, the queue's claim, the record step's recheck and the write, the binding a saved
look stores, the bytes route and each refusal. The real build is measured separately.
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from exulanica.api.services import _character_appearance_runtime
from exulanica.world.asset_preparation import AssetPreparationWorker
from exulanica.world.character_catalog_publication import (
    catalog_documents,
    catalog_imports,
    publish_catalogs,
    withdraw_catalog,
)
from exulanica.world.character_catalogs import read_publication_document
from exulanica.world.character_parametric import (
    PREPARER_ID,
    PREPARER_VERSION,
    declared_family,
)
from exulanica.world.character_preparation import CharacterBodyPreparer, PreparerHost

from workspace_asset_support import AssetsApi, assets_api

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).parents[1]
CHARACTERS = ROOT / "assets/characters"
FAMILY_ROOT = CHARACTERS / "makehuman-parametric-v1"
BODY = FAMILY_ROOT / "human-default.glb"
SCALE = json.loads((FAMILY_ROOT / "default.look.json").read_text())["descriptor"]["unitScale"]

# The stand-in's inputs: its identity is whatever generation the test writes beside it.
INPUTS = """
from pathlib import Path

HERE = Path(__file__).parent


def verify_inputs(source, blender, family_root):
    return {"tool": "stand-in", "generation": (HERE / "generation").read_text()}


def preparation_identity(inputs, family_root):
    return {"inputs": inputs}
"""
BLENDER = """#!{python}
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[-1]).read_text())
Path(config["output"]).write_bytes(Path("{body}").read_bytes())
Path(config["metadata"]).write_text(json.dumps({{"scale": {scale}}}))
"""


@dataclass
class Bodies:
    api: AssetsApi
    version: dict[str, Any]
    preparer: CharacterBodyPreparer
    layered: dict[str, Any]
    parametric: dict[str, Any]
    generation: Path

    def at(self, suffix: str = "", who: str = "owner") -> str:
        actor = self.api.actor
        return (
            f"/world/versions/{self.version['version_id']}/characters/avatar/{actor}/appearance"
            f"{suffix}?" + urlencode({"world_id": self.api.world_id})
        )

    def recipe(self, **changes: int | str) -> dict[str, Any]:
        """A recipe over the published parametric family: the reviewed body's values, changed."""
        family = self.family()
        (reviewed,) = declared_family(
            self.parametric, family["family"]["family_id"]
        ).representations
        return {
            "family_id": family["family"]["family_id"],
            "family_sha256": family["family_sha256"],
            "parameters": {**reviewed.values, **changes},
            "seed": 0,
        }

    def family(self) -> dict[str, Any]:
        families = self.api.get(self.at("/families")).json()
        return next(f for f in families if f["kind"] == "parametric-body")

    def request(self, recipe: dict[str, Any], who: str = "owner"):
        return self.api.post(self.at("/preparations"), {"recipe": recipe}, who=who)

    def worker(self, **limits: int) -> AssetPreparationWorker:
        return AssetPreparationWorker(
            self.api.database,
            self.api.stores,
            frozenset({self.api.owner}),
            preparers={(PREPARER_ID, PREPARER_VERSION): self.preparer},
            **limits,
        )

    def save(self, representation_id: str):
        current = self.api.get(self.at()).json()
        recipe = self.recipe(muscle=600) | {"representation_id": representation_id}
        return self.api.client.put(
            self.at(),
            json={"base_revision": current["revision"], "recipe": recipe},
            headers=self.api.headers(),
        )


@pytest.fixture
def bodies(repository, spine_schema, tmp_path):
    scripts = tmp_path / "stand-in"
    scripts.mkdir()
    (scripts / "inputs.py").write_text(INPUTS)
    (scripts / "blender_build.py").write_text("# the stand-in never runs this\n")
    (scripts / "generation").write_text("pinned")
    blender = scripts / "blender"
    blender.write_text(BLENDER.format(python=sys.executable, body=BODY, scale=repr(SCALE)))
    blender.chmod(blender.stat().st_mode | stat.S_IXUSR)
    host = PreparerHost(
        blender=blender, source=tmp_path / "source", family_root=FAMILY_ROOT, scripts=scripts
    )
    preparer = CharacterBodyPreparer(hosts=lambda _family: host, identity_seconds=0)
    for api in assets_api(repository, spine_schema, tmp_path):
        runtime = replace(
            _character_appearance_runtime(api.store, {}, api.stores), preparer=preparer
        )
        services = api.client.app.state.services
        api.client.app.state.services = replace(services, character_appearance=runtime)
        layered, parametric = catalog_documents(CHARACTERS)
        imported = sorted(
            {i.manifest.asset_key for d in (layered, parametric) for i in catalog_imports(d)}
        )
        with repository.connection.transaction():
            publish_catalogs(repository.connection, api.store, [layered, parametric])
        repository.connection.commit()
        made = api.client.post(
            f"/world/versions?{urlencode({'world_id': api.world_id})}",
            headers=api.headers(),
            json={"title": "Bodies", "source_snapshot_id": str(api.snapshot_id)},
        )
        assert made.status_code == 201, made.text
        yield Bodies(api, made.json(), preparer, layered, parametric, scripts / "generation")
        with repository.connection.transaction():
            repository.connection.execute(
                "delete from world_reviewed_asset where asset_key = any(%s)", (imported,)
            )
        repository.connection.commit()


def _withdraw(repository, document) -> None:
    with repository.connection.transaction():
        withdraw_catalog(
            repository.connection, read_publication_document(document).catalog_sha256, "test"
        )
    repository.connection.commit()


def test_a_body_is_requested_prepared_once_saved_and_drawn(bodies: Bodies) -> None:
    recipe = bodies.recipe(muscle=600)
    first = bodies.request(recipe)
    assert first.status_code == 202, first.text
    view = first.json()
    assert (view["state"], view["representation_id"], view["output"]) == ("requested", None, None)
    # An identical request is the same preparation, not another run.
    again = bodies.request(recipe)
    assert (again.status_code, again.json()["preparation_id"]) == (202, view["preparation_id"])
    named = f"preparation:{view['preparation_id']}"
    early = bodies.save(named)
    assert (early.status_code, early.json()["code"]) == (409, "representation_not_prepared")

    outcome = bodies.worker().drain()
    assert (outcome.prepared, outcome.failed, outcome.errors) == (1, 0, [])
    read = bodies.api.get(bodies.at(f"/preparations/{view['preparation_id']}")).json()
    payload = BODY.read_bytes()
    assert (read["state"], read["representation_id"]) == ("prepared", named)
    assert read["output"] == {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "present": True,
    }
    assert read["descriptor"]["unitScaleMillionths"] == 1130365
    assert read["catalog_sha256"] == read_publication_document(bodies.parametric).catalog_sha256
    # Asked again once prepared: answered from the queue, with no further run.
    cached = bodies.request(recipe)
    assert (cached.status_code, cached.json()["attempts"]) == (200, read["attempts"])
    assert bodies.worker().drain().handled == 0

    saved = bodies.save(named)
    assert saved.status_code == 200, saved.text
    current = saved.json()["current"]
    assert current["render_status"] == "available"
    assert current["render"]["representation_id"] == named
    assert current["render"]["dependencies"] == [
        {
            "asset_key": named,
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "byte_size": len(payload),
            "state": "available",
        }
    ]
    delivered = bodies.api.get(bodies.at(f"/preparations/{view['preparation_id']}/bytes"))
    assert delivered.status_code == 200
    assert delivered.content == payload
    assert delivered.headers["etag"] == f'"{hashlib.sha256(payload).hexdigest()}"'


def test_the_reviewed_body_is_answered_without_preparing_anything(bodies: Bodies) -> None:
    answered = bodies.request(bodies.recipe())
    assert answered.status_code == 200, answered.text
    view = answered.json()
    assert (view["preparation_id"], view["representation_id"]) == (
        None,
        "reviewed:makehuman.parametric.default.v1",
    )
    assert bodies.api.counts()["workspace_preparation"] == 0


def test_a_cancelled_preparation_makes_nothing_and_a_new_request_queues_it_again(
    bodies: Bodies,
) -> None:
    view = bodies.request(bodies.recipe(muscle=600)).json()
    path = f"/preparations/{view['preparation_id']}"
    cancelled = bodies.api.post(bodies.at(path + "/cancel"))
    assert (cancelled.status_code, cancelled.json()["state"]) == (200, "cancelled")
    assert cancelled.json()["failure"]["class"] == "cancelled"
    assert bodies.worker().drain().handled == 0
    assert bodies.api.namespace_files() == []
    refused = bodies.save(f"preparation:{view['preparation_id']}")
    assert (refused.status_code, refused.json()["code"]) == (409, "representation_not_prepared")

    requeued = bodies.request(bodies.recipe(muscle=600))
    assert (requeued.status_code, requeued.json()["state"]) == (202, "requested")
    assert requeued.json()["preparation_id"] == view["preparation_id"]
    assert bodies.worker().drain().prepared == 1
    finished = bodies.api.post(bodies.at(path + "/cancel"))
    assert (finished.status_code, finished.json()["code"]) == (409, "preparation_finished")


def test_a_body_whose_family_stops_being_served_fails_stale_and_writes_nothing(
    bodies: Bodies, repository
) -> None:
    recipe = bodies.recipe(muscle=600)
    view = bodies.request(recipe).json()
    _withdraw(repository, bodies.parametric)
    outcome = bodies.worker().drain()
    assert (outcome.prepared, outcome.failed) == (0, 1)
    read = bodies.api.get(bodies.at(f"/preparations/{view['preparation_id']}")).json()
    assert read["state"] == "failed"
    assert read["failure"]["class"] == "stale"
    assert bodies.api.namespace_files() == []
    # The family is no longer served, so asking again is refused, not re-run.
    again = bodies.request(recipe)
    assert (again.status_code, again.json()["code"]) == (424, "appearance_unavailable")


def test_inputs_that_change_after_the_request_fail_the_preparation_stale(bodies: Bodies) -> None:
    view = bodies.request(bodies.recipe(muscle=600)).json()
    bodies.generation.write_text("changed")
    outcome = bodies.worker().drain()
    assert (outcome.prepared, outcome.failed) == (0, 1)
    read = bodies.api.get(bodies.at(f"/preparations/{view['preparation_id']}")).json()
    assert (read["failure"]["class"], read["failure"]["code"]) == (
        "stale",
        "preparation_identity_changed",
    )
    # A deterministic failure is answered as it is; the new identity is a new preparation.
    answered = bodies.request(bodies.recipe(muscle=600)).json()
    assert answered["preparation_id"] != view["preparation_id"]
    assert answered["state"] == "requested"


def test_missing_or_corrupt_bytes_read_unavailable_and_a_new_request_prepares_again(
    bodies: Bodies,
) -> None:
    view = bodies.request(bodies.recipe(muscle=600)).json()
    assert bodies.worker().drain().prepared == 1
    named = f"preparation:{view['preparation_id']}"
    assert bodies.save(named).status_code == 200
    (stored,) = bodies.api.namespace_files()
    original = stored.read_bytes()
    stored.chmod(0o644)  # the store writes read-only files; this test plays a damaged disk

    stored.write_bytes(original[:-4] + b"\0\0\0\0")
    assert (
        bodies.api.get(bodies.at()).json()["current"]["render_status"]
        == "asset_integrity_unavailable"
    )
    corrupt = bodies.api.get(bodies.at(f"/preparations/{view['preparation_id']}/bytes"))
    assert (corrupt.status_code, corrupt.json()["code"]) == (409, "prepared_bytes_corrupt")

    stored.unlink()
    assert (
        bodies.api.get(bodies.at()).json()["current"]["render_status"] == "asset_bytes_unavailable"
    )
    missing = bodies.api.get(bodies.at(f"/preparations/{view['preparation_id']}/bytes"))
    assert (missing.status_code, missing.json()["code"]) == (409, "prepared_bytes_missing")
    requeued = bodies.request(bodies.recipe(muscle=600))
    assert (requeued.status_code, requeued.json()["state"]) == (202, "requested")
    assert bodies.worker().drain().prepared == 1
    assert bodies.api.get(bodies.at()).json()["current"]["render_status"] == "available"
    assert stored.read_bytes() == original


def test_the_capability_read_describes_a_body_as_the_preparation_routes_answer(
    bodies: Bodies, repository
) -> None:
    """Requesting and cancelling a body are described as those routes answer: available with a
    queue, a preparer and inputs that verify for a served parametric family; preparer_unavailable
    without; appearance_unavailable once no family is served."""
    appearance = "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"
    preparations = f"{appearance}/preparations"
    requesting, cancelling = (
        f"POST {preparations}",
        f"POST {preparations}/{{preparation_id}}/cancel",
    )
    capabilities = f"/world/versions/{bodies.version['version_id']}/capabilities?" + urlencode(
        {"world_id": bodies.api.world_id}
    )

    def described(operation: str) -> dict[str, Any]:
        read = bodies.api.get(capabilities)
        assert read.status_code == 200, read.text
        (row,) = [r for r in read.json()["operations"] if r["operation"] == operation]
        return row

    offered = described(requesting)
    assert (offered["state"], offered["code"]) == ("available", None)
    assert [effect["on"] for effect in offered["effects"]] == ["preparation"]
    assert offered["options"] == [f"GET {appearance}/families"]
    assert (described(cancelling)["state"], described(cancelling)["code"]) == ("available", None)

    services = bodies.api.client.app.state.services
    runtime = services.character_appearance
    # A preparer whose inputs do not verify here: the read says so before a request is refused.
    unverified = CharacterBodyPreparer(hosts=lambda _family: None)
    bodies.api.client.app.state.services = replace(
        services, character_appearance=replace(runtime, preparer=unverified)
    )
    assert described(requesting)["code"] == "preparer_unavailable"
    refused = bodies.request(bodies.recipe(muscle=700))
    assert (refused.status_code, refused.json()["code"]) == (503, "preparer_unavailable")
    assert described(cancelling)["state"] == "available", "the queue still answers a cancel"
    bodies.api.client.app.state.services = replace(
        services, character_appearance=replace(runtime, preparations=None)
    )
    assert described(requesting)["code"] == "preparer_unavailable"
    assert described(cancelling)["code"] == "preparer_unavailable"
    bodies.api.client.app.state.services = services

    _withdraw(repository, bodies.layered)
    _withdraw(repository, bodies.parametric)
    assert described(requesting)["code"] == "appearance_unavailable"


def test_a_body_over_the_workspace_retained_bytes_fails_by_name(bodies: Bodies) -> None:
    """A prepared body counts against the workspace's retained bytes as every output does: one byte
    over the limit fails the preparation quota_exceeded and records nothing, and a body that
    reaches the limit exactly is prepared. The worker's own limit is used, because the setting
    refuses values this small."""
    size = BODY.stat().st_size
    over = bodies.request(bodies.recipe(muscle=610)).json()
    assert bodies.worker(retained_bytes_limit=size - 1).drain().failed == 1
    failed = bodies.api.get(bodies.at(f"/preparations/{over['preparation_id']}")).json()
    assert failed["state"] == "failed" and failed["output"] is None
    assert (failed["failure"]["class"], failed["failure"]["code"]) == (
        "quota_exceeded",
        "workspace_asset_quota_exceeded",
    )
    assert f"retained-bytes limit of {size - 1} bytes" in failed["failure"]["message"]
    exact = bodies.request(bodies.recipe(muscle=620)).json()
    assert bodies.worker(retained_bytes_limit=size).drain().prepared == 1
    prepared = bodies.api.get(bodies.at(f"/preparations/{exact['preparation_id']}")).json()
    assert prepared["state"] == "prepared" and prepared["output"]["byte_size"] == size


def test_requests_this_host_cannot_take_are_refused_by_name(bodies: Bodies) -> None:
    families = bodies.api.get(bodies.at("/families")).json()
    people = next(f for f in families if f["kind"] == "layered-people")
    layered = {
        "family_id": people["family"]["family_id"],
        "family_sha256": people["family_sha256"],
        "parameters": {p["key"]: p["default"] for p in people["family"]["parameters"]},
        "seed": people["family"]["default_seed"],
    }
    not_applicable = bodies.request(layered)
    assert (not_applicable.status_code, not_applicable.json()["code"]) == (
        422,
        "preparation_not_applicable",
    )
    named = bodies.recipe(muscle=600) | {"representation_id": "reviewed:anything"}
    assert bodies.request(named).json()["code"] == "invalid_appearance"
    out_of_range = bodies.request(bodies.recipe(muscle=5000))
    assert out_of_range.json()["code"] == "invalid_appearance"
    unknown = bodies.api.get(bodies.at(f"/preparations/{'0' * 8}-0000-0000-0000-{'0' * 12}"))
    assert (unknown.status_code, unknown.json()["code"]) == (404, "unknown_reference")
    view = bodies.request(bodies.recipe(muscle=600)).json()
    foreign = bodies.api.get(bodies.at(f"/preparations/{view['preparation_id']}"), who="stranger")
    assert foreign.status_code == 404

    services = bodies.api.client.app.state.services
    bodies.api.client.app.state.services = replace(
        services, character_appearance=replace(services.character_appearance, preparer=None)
    )
    unavailable = bodies.request(bodies.recipe(muscle=700))
    assert (unavailable.status_code, unavailable.json()["code"]) == (503, "preparer_unavailable")


def test_the_preparation_fixtures_are_captured_from_the_application(bodies: Bodies) -> None:
    """Every preparation fixture the experience owner and F1 read is an answer the app gave.

    Written to ``EXULANICA_C7_FIXTURES`` when that names a directory, as the catalog fixtures are
    (``tests/test_character_catalog_api.py``); otherwise only checked. Development data, never a
    production success mode.
    """
    import os

    captured: dict[str, dict[str, Any]] = {}

    def keep(name: str, case: str, response) -> dict[str, Any]:
        captured[name] = {
            "fixture": "exulanica.capability-fixture/v1",
            "label": "development data, not a production response",
            "case": case,
            "captured_by": "tests/test_character_body_preparation_api.py against the application",
            "pending": None,
            "status": response.status_code,
            "response": response.json(),
        }
        return captured[name]["response"]

    keep(
        "c7-11-reviewed-body-answered.json",
        "a request whose values the publication already reviews: answered, nothing queued",
        bodies.request(bodies.recipe()),
    )
    # Before any body exists: the stand-in builds the same bytes for every recipe, and bytes the
    # workspace already holds add nothing to its retained bytes.
    over = bodies.request(bodies.recipe(muscle=660)).json()
    assert bodies.worker(retained_bytes_limit=1).drain().failed == 1
    keep(
        "c7-22-preparation-failed-quota.json",
        "a body over the workspace's retained bytes: failed quota_exceeded, nothing kept",
        bodies.api.get(bodies.at(f"/preparations/{over['preparation_id']}")),
    )
    requested = keep(
        "c7-12-preparation-requested.json",
        "a request for a body over new values: queued (202)",
        bodies.request(bodies.recipe(muscle=600)),
    )
    named = f"preparation:{requested['preparation_id']}"
    keep(
        "c7-13-look-names-a-body-not-yet-prepared.json",
        "saving a look that names a body still being prepared",
        bodies.save(named),
    )
    assert bodies.worker().drain().prepared == 1
    path = f"/preparations/{requested['preparation_id']}"
    keep(
        "c7-14-preparation-prepared.json",
        "the preparation once prepared, with its render descriptor",
        bodies.api.get(bodies.at(path)),
    )
    keep(
        "c7-15-look-saved-with-a-prepared-body.json",
        "a look saved naming the prepared body: bound to its digest and receipt",
        bodies.save(named),
    )
    keep(
        "c7-16-cancel-after-prepared.json",
        "cancelling a preparation that already finished",
        bodies.api.post(bodies.at(path + "/cancel")),
    )
    other = bodies.request(bodies.recipe(muscle=700)).json()
    keep(
        "c7-17-preparation-cancelled.json",
        "a preparation cancelled before any worker ran it",
        bodies.api.post(bodies.at(f"/preparations/{other['preparation_id']}/cancel")),
    )
    third = bodies.request(bodies.recipe(muscle=800)).json()
    bodies.generation.write_text("changed")
    assert bodies.worker().drain().failed == 1
    keep(
        "c7-18-preparation-failed-stale.json",
        "the preparer's inputs changed after the request: failed stale, nothing written",
        bodies.api.get(bodies.at(f"/preparations/{third['preparation_id']}")),
    )
    (stored,) = bodies.api.namespace_files()
    stored.chmod(0o644)
    stored.unlink()
    keep(
        "c7-19-prepared-bytes-missing.json",
        "the bytes route when the prepared output's bytes are gone",
        bodies.api.get(bodies.at(path + "/bytes")),
    )
    families = bodies.api.get(bodies.at("/families")).json()
    people = next(f for f in families if f["kind"] == "layered-people")
    keep(
        "c7-20-preparation-not-applicable.json",
        "a request over a family whose looks need no prepared body",
        bodies.request(
            {
                "family_id": people["family"]["family_id"],
                "family_sha256": people["family_sha256"],
                "parameters": {p["key"]: p["default"] for p in people["family"]["parameters"]},
                "seed": people["family"]["default_seed"],
            }
        ),
    )
    services = bodies.api.client.app.state.services
    bodies.api.client.app.state.services = replace(
        services, character_appearance=replace(services.character_appearance, preparer=None)
    )
    keep(
        "c7-21-preparer-unavailable.json",
        "a host whose preparer inputs are not configured or do not verify",
        bodies.request(bodies.recipe(muscle=650)),
    )
    assert [captured[name]["status"] for name in sorted(captured)] == [
        200,
        202,
        409,
        200,
        200,
        409,
        200,
        200,
        409,
        422,
        503,
        200,
    ]
    target = os.environ.get("EXULANICA_C7_FIXTURES")
    if target:
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        for name, fixture in captured.items():
            (directory / name).write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n")
