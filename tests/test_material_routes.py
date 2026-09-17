"""The /materials routes, end to end over HTTP against real PostgreSQL.

The security floor, applied to a new route module: every route is declared, a read-only grant is
refused on every write, a stranger's view is a 404 and never a 403, the bytes route answers after
the final check with a private, uncached response that names the licence, and a bake request past
the workspace's quota is a 429. The rules themselves are the repository's and the migration's,
and ``tests/test_material_recipes.py`` holds those.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import ROUTE_RULES, Requires
from exulanica.api.services import Services
from exulanica.world.material_recipes import MaterialRuntime
from fastapi.testclient import TestClient

from test_material_recipes import BRICK, CATALOG, _small
from test_material_recipes import materials as materials
from test_purge import purged as purged
from tests_support_api import EVERY_PERMISSION

MATERIAL_ROUTES = sorted(key for key in ROUTE_RULES if key[1].startswith("/materials"))


class Client:
    def __init__(self, materials) -> None:
        self.tokens = {
            "owner": "materials-owner-" + uuid.uuid4().hex,
            "reader": "materials-reader-" + uuid.uuid4().hex,
            "stranger": "materials-stranger-" + uuid.uuid4().hex,
        }
        grants = {
            self.tokens["owner"]: {
                "workspace_id": str(materials.workspace_id),
                "actor": str(materials.actor),
                "permissions": EVERY_PERMISSION,
            },
            self.tokens["reader"]: {
                "workspace_id": str(materials.workspace_id),
                "actor": str(uuid.uuid4()),
                "permissions": ["world.read"],
            },
            self.tokens["stranger"]: {
                "workspace_id": str(uuid.uuid4()),
                "actor": str(uuid.uuid4()),
                "permissions": EVERY_PERMISSION,
            },
        }
        services = Services(
            database=materials.owner,
            readonly_database=materials.owner,
            store=materials.purged.store,
            tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
            executor_shares_the_write_role=True,
            model_client=None,
            materials=MaterialRuntime(catalog=CATALOG, stores=materials.stores),
        )
        self.client = TestClient(create_app(services, verify=False))

    def call(self, who: str, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self.tokens[who]}"}
        return self.client.request(method, path, headers=headers, **kwargs)


@pytest.fixture
def api(materials):
    client = Client(materials)
    with client.client:
        yield client


def test_every_material_route_is_declared_and_writes_need_world_write():
    assert len(MATERIAL_ROUTES) == 9
    for method, path in MATERIAL_ROUTES:
        rule = ROUTE_RULES[(method, path)]
        assert isinstance(rule, Requires)
        wanted = "world.read" if method == "GET" else "world.write"
        assert {str(permission) for permission in rule.permissions} == {wanted}, (method, path)


def test_a_person_varies_a_published_set_bakes_it_reads_it_and_withdraws_it(api, materials):
    makers = api.call("owner", "GET", "/materials/makers").json()["makers"]
    assert {(m["maker_id"], m["version"]) for m in makers} == set(CATALOG.makers)
    library = api.call("owner", "GET", "/materials/library").json()["sets"]
    brick = next(entry for entry in library if entry["set_id"] == BRICK)
    recipe = brick["recipe"]
    recipe["resolution"] = {"width": 16, "height": 16}
    recipe["parameters"]["mortar_colour"] = [120, 118, 110]

    created = api.call(
        "owner",
        "POST",
        "/materials/recipes",
        json={"recipe": recipe, "based_on": {"set_id": BRICK, "version": 1}, "label": "Dark"},
    )
    assert created.status_code == 201, created.text
    assert "no-store" in created.headers["cache-control"]
    view = created.json()
    recipe_id = view["recipe_id"]
    assert view["recipe"] == recipe and view["label"] == "Dark" and view["bake"] is None
    listed = api.call("owner", "GET", "/materials/recipes").json()["recipes"]
    assert [item["recipe_id"] for item in listed] == [recipe_id]

    assert api.call("owner", "GET", f"/materials/recipes/{recipe_id}/bake").status_code == 404
    queued = api.call("owner", "POST", f"/materials/recipes/{recipe_id}/bake")
    assert queued.status_code == 202, queued.text
    assert queued.json()["state"] == "requested"
    assert queued.json()["licence_id"] == "LicenseRef-Exulanica-Workspace-Private"
    not_ready = api.call("owner", "GET", f"/materials/recipes/{recipe_id}/bake/bytes")
    assert (not_ready.status_code, not_ready.json()["code"]) == (409, "bake_not_ready")

    container = materials.record_synthetic_bake(uuid.UUID(recipe_id))
    served = api.call("owner", "GET", f"/materials/recipes/{recipe_id}/bake/bytes")
    assert served.status_code == 200
    assert served.content == container
    assert served.headers["cache-control"] == "private, no-store"
    assert served.headers["x-exulanica-licence"] == "LicenseRef-Exulanica-Workspace-Private"
    assert served.headers["x-exulanica-set-id"] == f"ws.{uuid.UUID(recipe_id).hex}"
    assert served.headers["content-type"].startswith("application/vnd.exulanica.texture-set")
    again = api.call("owner", "POST", f"/materials/recipes/{recipe_id}/bake")
    assert again.status_code == 200 and again.json()["state"] == "baked"

    withdrawn = api.call("owner", "POST", f"/materials/recipes/{recipe_id}/withdraw")
    assert withdrawn.status_code == 200
    for method, suffix in (
        ("GET", ""),
        ("GET", "/bake"),
        ("GET", "/bake/bytes"),
        ("POST", "/bake"),
    ):
        gone = api.call("owner", method, f"/materials/recipes/{recipe_id}{suffix}")
        assert (gone.status_code, gone.json()["code"]) == (410, "withdrawn"), suffix
    assert api.call("owner", "GET", "/materials/recipes").json()["recipes"] == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda recipe: recipe["parameters"].update(courses=25), "even number"),
        (lambda recipe: recipe.update(resolution={"width": 15, "height": 16}), "power of two"),
    ],
)
def test_a_recipe_the_maker_refuses_is_a_422_that_says_why(api, change, reason):
    recipe = _small()
    change(recipe)
    refused = api.call("owner", "POST", "/materials/recipes", json={"recipe": recipe})
    assert refused.status_code == 422
    body = refused.json()
    assert body["code"] == "invalid_recipe"
    assert any(reason in problem for problem in body["problems"]), body


def test_a_recipe_that_is_not_integers_or_not_the_body_shape_is_a_422(api):
    floated = api.call(
        "owner", "POST", "/materials/recipes", json={"recipe": {**_small(), "seed": 1.5}}
    )
    assert (floated.status_code, floated.json()["code"]) == (422, "invalid_recipe")
    extra = api.call("owner", "POST", "/materials/recipes", json={"recipe": _small(), "x": 1})
    assert extra.status_code == 422


@pytest.mark.parametrize("origin", ["proposed", "photo_derived", "scanned"])
def test_a_client_states_only_that_a_person_authored_the_recipe(api, materials, origin):
    """A proposal or a photo-derived recipe carries its model, and no client can supply that."""
    refused = api.call(
        "owner", "POST", "/materials/recipes", json={"recipe": _small(), "origin": origin}
    )
    assert refused.status_code == 422
    assert materials.rows("select count(*) as n from material_recipe")[0]["n"] == 0
    stated = api.call(
        "owner", "POST", "/materials/recipes", json={"recipe": _small(), "origin": "authored"}
    )
    assert (stated.status_code, stated.json()["origin"]) == (201, "authored")


def test_a_read_only_grant_is_refused_on_every_write(api, materials):
    recipe_id = materials.repository().create_recipe(_small()).recipe_id
    for method, path in MATERIAL_ROUTES:
        filled = path.replace("{recipe_id}", str(recipe_id))
        kwargs = {"json": {"recipe": _small()}} if path == "/materials/recipes" else {}
        response = api.call("reader", method, filled, **kwargs)
        if method == "GET":
            assert response.status_code != 403, (method, path)
        else:
            assert response.status_code in (403, 404), (method, path, response.status_code)
    assert materials.rows("select count(*) as n from material_recipe")[0]["n"] == 1
    assert materials.rows("select count(*) as n from material_bake")[0]["n"] == 0
    assert materials.rows("select count(*) as n from material_recipe_withdrawal")[0]["n"] == 0


def test_a_stranger_sees_nothing_and_never_a_403(api, materials):
    recipe_id = materials.repository().create_recipe(_small()).recipe_id
    assert api.call("stranger", "GET", "/materials/recipes").json()["recipes"] == []
    for method, path in MATERIAL_ROUTES:
        if "{recipe_id}" not in path:
            continue
        for candidate in (recipe_id, uuid.uuid4()):
            response = api.call("stranger", method, path.replace("{recipe_id}", str(candidate)))
            assert response.status_code == 404, (method, path, response.text)
            assert response.json()["code"] == "unknown_reference"


def test_a_bake_request_past_the_quota_is_a_429(api, materials):
    materials.connection.execute(
        "insert into material_bake_quota (workspace_id, requests_per_day, pending_at_once, "
        "  declared_by) values (%s, 1, 1, %s)",
        (materials.workspace_id, materials.actor),
    )
    first = materials.repository().create_recipe(_small()).recipe_id
    second = materials.repository().create_recipe(_small(seed=3)).recipe_id
    assert api.call("owner", "POST", f"/materials/recipes/{first}/bake").status_code == 202
    refused = api.call("owner", "POST", f"/materials/recipes/{second}/bake")
    assert (refused.status_code, refused.json()["code"]) == (429, "bake_quota_exceeded")


def test_an_instance_without_the_catalog_says_so(materials):
    services = Services(
        database=materials.owner,
        readonly_database=materials.owner,
        store=materials.purged.store,
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        "materials-owner-token-without-catalog": {
                            "workspace_id": str(materials.workspace_id),
                            "actor": str(uuid.uuid4()),
                            "permissions": EVERY_PERMISSION,
                        }
                    }
                )
            }
        ),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    assert any("material catalog" in note for note in services.warnings)
    with TestClient(create_app(services, verify=False)) as client:
        response = client.get(
            "/materials/makers",
            headers={"Authorization": "Bearer materials-owner-token-without-catalog"},
        )
    assert (response.status_code, response.json()["code"]) == (503, "materials_unavailable")


def test_a_read_only_deployment_answers_writes_with_a_named_403(materials):
    from test_material_recipes import _read_only_database

    judge = _read_only_database(materials)
    token = "materials-judge-" + uuid.uuid4().hex
    services = Services(
        database=judge,
        readonly_database=judge,
        store=materials.purged.store,
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        token: {
                            "workspace_id": str(materials.workspace_id),
                            "actor": str(uuid.uuid4()),
                            "permissions": EVERY_PERMISSION,
                        }
                    }
                )
            }
        ),
        executor_shares_the_write_role=True,
        model_client=None,
        materials=MaterialRuntime(catalog=CATALOG, stores=materials.stores),
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(services, verify=False)) as client:
        assert client.get("/materials/recipes", headers=headers).status_code == 200
        for path, body in (
            ("/materials/recipes", {"recipe": _small()}),
            (f"/materials/recipes/{uuid.uuid4()}/bake", None),
            (f"/materials/recipes/{uuid.uuid4()}/withdraw", None),
        ):
            response = client.post(path, headers=headers, json=body)
            assert (response.status_code, response.json()["code"]) == (
                403,
                "materials_read_only",
            ), path
