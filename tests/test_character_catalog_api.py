"""Character catalog reads and two family kinds over HTTP, as an independent client meets them."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

import pytest
from exulanica.api.app import create_app
from exulanica.api.services import _character_appearance_runtime
from exulanica.world.character_appearance import designed_looks, recipe_from_look
from exulanica.world.character_catalog_publication import (
    catalog_documents,
    catalog_imports,
    publish_catalogs,
    withdraw_catalog,
)
from exulanica.world.character_catalogs import read_publication_document
from exulanica.world.character_parametric import declared_family
from fastapi.testclient import TestClient

from test_world_objects_api import objects_api as objects_api

pytestmark = pytest.mark.postgres

CHARACTERS = Path(__file__).parents[1] / "assets/characters"
CATALOG = json.loads((CHARACTERS / "catalog.json").read_text())
LOOKS = json.loads((CHARACTERS / "looks.json").read_text())


@pytest.fixture
def characters(objects_api, repository):
    """The API with this host's character runtime, and a publisher on the owner connection."""
    api = objects_api
    services = api.client.app.state.services
    api.client.app.state.services = replace(
        services, character_appearance=_character_appearance_runtime(api.store, {})
    )
    layered, parametric = catalog_documents(CHARACTERS)
    imported: set[str] = set()

    def publish(*documents):
        for document in documents:
            imported.update(item.manifest.asset_key for item in catalog_imports(document))
        with repository.connection.transaction():
            publish_catalogs(repository.connection, api.store, documents)
        repository.connection.commit()

    def withdraw(document):
        with repository.connection.transaction():
            withdraw_catalog(
                repository.connection, read_publication_document(document).catalog_sha256, "test"
            )
        repository.connection.commit()

    version = api.version()
    yield api, version, publish, withdraw, (layered, parametric)
    if imported:
        with repository.connection.transaction():
            repository.connection.execute(
                "delete from world_reviewed_asset where asset_key = any(%s)", (sorted(imported),)
            )
        repository.connection.commit()


def appearance(version, actor, suffix=""):
    return (
        f"/world/versions/{version['version_id']}/characters/avatar/{actor}/appearance{suffix}?"
        + urlencode({"world_id": version["world_id"]})
    )


def test_the_catalog_reads_serve_each_publication_by_its_digest(characters):
    api, _version, publish, withdraw, (layered, parametric) = characters
    assert api.client.get("/world/character-catalogs").status_code == 401
    empty = api.get("/world/character-catalogs")
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"profile": "exulanica.character-catalog-list/v1", "publications": []}

    publish(layered, parametric)
    listed = api.get("/world/character-catalogs").json()["publications"]
    assert [(p["catalog_id"], p["kind"], p["state"]) for p in listed] == [
        ("exulanica-characters", "layered-people", "current"),
        ("exulanica-parametric-characters", "parametric-body", "current"),
    ]
    for entry in listed:
        response = api.get(f"/world/character-catalogs/{entry['catalog_sha256']}")
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == entry["catalog_sha256"]
        assert "immutable" in response.headers["cache-control"]
        assert response.headers["etag"] == f'"{entry["catalog_sha256"]}"'
    unknown = api.get(f"/world/character-catalogs/{'e' * 64}")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "unknown_reference")
    assert api.get("/world/character-catalogs/not-a-digest").status_code == 422

    withdraw(layered)
    remaining = api.get("/world/character-catalogs").json()["publications"]
    assert [p["catalog_id"] for p in remaining] == ["exulanica-parametric-characters"]
    gone = api.get(f"/world/character-catalogs/{listed[0]['catalog_sha256']}")
    assert (gone.status_code, gone.json()["code"]) == (410, "withdrawn")


def test_a_client_discovers_two_family_kinds_and_saves_a_look_in_each(characters, repository):
    api, version, publish, _withdraw, (layered, parametric) = characters
    publish(layered, parametric)
    families = api.get(appearance(version, api.actor, "/families")).json()
    by_id = {entry["family"]["family_id"]: entry for entry in families}
    assert {entry["kind"] for entry in families} == {"layered-people", "parametric-body"}
    people = by_id["makehuman-people/v1/feminine"]
    body = by_id["makehuman-parametric/v1"]
    # Genuinely different capabilities, read from the served declarations.
    people_kinds = {p["kind"] for p in people["family"]["parameters"]}
    body_kinds = {p["kind"] for p in body["family"]["parameters"]}
    assert "choice" in people_kinds and "integer" in body_kinds
    assert people["family"]["family_revision"] != body["family"]["family_revision"]

    a = read_publication_document(layered)
    feminine = next(f for f in a.families if f.family_id == "makehuman-people/v1/feminine")
    look = designed_looks(CATALOG, LOOKS)["tailored-feminine"]["look"]
    first = api.client.put(
        appearance(version, api.actor),
        json={
            "base_revision": 0,
            "recipe": recipe_from_look(look, feminine).model_dump(mode="json"),
        },
        headers=api.headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["current"]["render_status"] == "available"

    (representation,) = declared_family(parametric, "makehuman-parametric/v1").representations
    recipe = {
        "family_id": body["family"]["family_id"],
        "family_sha256": body["family_sha256"],
        "parameters": representation.values,
        "seed": 0,
        "representation_id": representation.representationId,
    }
    second = api.client.put(
        appearance(version, api.actor),
        json={"base_revision": 1, "recipe": recipe},
        headers=api.headers,
    )
    assert second.status_code == 200, second.text
    current = second.json()["current"]
    assert (current["render_status"], current["render"]["kind"]) == ("available", "parametric-body")

    stale = api.client.put(
        appearance(version, api.actor),
        json={"base_revision": 1, "recipe": recipe},
        headers=api.headers,
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_appearance")

    # Another process over the same database and store reads the same looks.
    services = api.client.app.state.services
    fresh = replace(services, character_appearance=_character_appearance_runtime(api.store, {}))
    with TestClient(create_app(fresh, verify=False)) as restarted:
        reread = restarted.get(appearance(version, api.actor), headers=api.headers).json()
        history = restarted.get(appearance(version, api.actor, "/history"), headers=api.headers)
    assert reread["revision"] == 2
    assert reread["current"]["document"] == current["document"]
    assert [row["revision"] for row in history.json()] == [2, 1]
    assert history.json()[1]["render_status"] == "available"


def test_the_capability_fixtures_are_captured_from_the_application(characters):
    """Every C7 fixture the experience owner and F1 read is an answer this application gave.

    Written to ``EXULANICA_C7_FIXTURES`` when that names a directory, so a delivery carries what a
    run captured rather than anything typed by hand; otherwise only checked. Development data, never
    a production success mode.
    """
    import os

    from test_character_catalogs import catalog_b

    api, version, publish, withdraw, (layered, parametric) = characters
    captured: dict[str, dict] = {}

    def keep(name, case, response, body=None):
        captured[name] = {
            "fixture": "exulanica.capability-fixture/v1",
            "label": "development data, not a production response",
            "case": case,
            "captured_by": "tests/test_character_catalog_api.py against the application",
            "pending": None,
            "status": response.status_code,
            "response": response.json() if body is None else body,
        }

    keep(
        "c7-01-catalog-list-empty.json",
        "no character catalog published",
        api.get("/world/character-catalogs"),
    )
    publish(layered, parametric)
    families = api.get(appearance(version, api.actor, "/families"))
    keep(
        "c7-02-families-two-kinds.json",
        "families read: a layered people family and a parametric one",
        families,
    )
    by_id = {entry["family"]["family_id"]: entry for entry in families.json()}
    a = read_publication_document(layered)
    feminine = next(f for f in a.families if f.family_id.endswith("/feminine"))
    look = dict(designed_looks(CATALOG, LOOKS)["tailored-feminine"]["look"])
    look["parts"] = {**look["parts"], "hair": "feminine/hair/long01"}
    saved = api.client.put(
        appearance(version, api.actor),
        json={
            "base_revision": 0,
            "recipe": recipe_from_look(look, feminine).model_dump(mode="json"),
        },
        headers=api.headers,
    )
    keep(
        "c7-03-saved-look-available-authored.json",
        "saved catalog look, drawn from the publication it was authored against",
        saved,
    )
    stale = api.client.put(
        appearance(version, api.actor),
        json={
            "base_revision": 0,
            "recipe": recipe_from_look(look, feminine).model_dump(mode="json"),
        },
        headers=api.headers,
    )
    keep(
        "c7-04-refusal-stale-appearance.json",
        "save naming a base revision another write already moved",
        stale,
    )
    publish(catalog_b())
    keep(
        "c7-05-catalog-list-current-and-retained.json",
        "catalog A retained, catalog B current",
        api.get("/world/character-catalogs"),
    )
    withdraw(layered)
    keep(
        "c7-06-saved-look-family-unavailable.json",
        "saved look whose only publication was withdrawn",
        api.get(appearance(version, api.actor)),
    )
    reset = api.post(appearance(version, api.actor, "/reset"), {"base_revision": 1})
    keep(
        "c7-07-refusal-appearance-unavailable.json",
        "reset over a family no served publication derives",
        reset,
    )
    gone = api.get(f"/world/character-catalogs/{a.catalog_sha256}")
    keep("c7-08-refusal-catalog-withdrawn.json", "withdrawn catalog document", gone)
    unknown = api.get(f"/world/character-catalogs/{'e' * 64}")
    keep("c7-09-refusal-catalog-unknown.json", "catalog digest the host never published", unknown)
    body = by_id["makehuman-parametric/v1"]
    (representation,) = declared_family(parametric, "makehuman-parametric/v1").representations
    worn = api.client.put(
        appearance(version, api.actor),
        json={
            "base_revision": 1,
            "recipe": {
                "family_id": "makehuman-parametric/v1",
                "family_sha256": body["family_sha256"],
                "parameters": representation.values,
                "seed": 0,
                "representation_id": representation.representationId,
            },
        },
        headers=api.headers,
    )
    keep(
        "c7-10-saved-parametric-body.json",
        "saved parametric look worn with the published reviewed body",
        worn,
    )
    assert [entry["status"] for entry in captured.values()] == [
        200,
        200,
        200,
        409,
        200,
        200,
        424,
        410,
        404,
        200,
    ]
    assert captured["c7-06-saved-look-family-unavailable.json"]["response"]["current"][
        "render_status"
    ] == ("family_source_unavailable")
    assert captured["c7-10-saved-parametric-body.json"]["response"]["current"]["render"][
        "kind"
    ] == ("parametric-body")
    target = os.environ.get("EXULANICA_C7_FIXTURES")
    if target:
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        for name, fixture in captured.items():
            (directory / name).write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n")


def test_the_capability_read_offers_a_saved_look_only_while_a_family_is_served(characters):
    """The capability read answers as the appearance writes do: no served family, no saving."""
    api, version, publish, withdraw, (layered, parametric) = characters
    save = "PUT /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance"

    def described() -> dict:
        read = api.get(
            api.in_world(
                f"/world/versions/{version['version_id']}/capabilities", version["world_id"]
            )
        )
        assert read.status_code == 200, read.text
        (row,) = [r for r in read.json()["operations"] if r["operation"] == save]
        return row

    nothing = described()
    assert (nothing["state"], nothing["code"]) == ("unavailable", "appearance_unavailable")
    # A look over a family the host does not serve yet is refused as the read said it would be.
    feminine = next(
        f for f in read_publication_document(layered).families if f.family_id.endswith("/feminine")
    )
    look = designed_looks(CATALOG, LOOKS)["tailored-feminine"]["look"]
    refused = api.client.put(
        appearance(version, api.actor),
        json={
            "base_revision": 0,
            "recipe": recipe_from_look(look, feminine).model_dump(mode="json"),
        },
        headers=api.headers,
    )
    assert (refused.status_code, refused.json()["code"]) == (424, "appearance_unavailable")
    publish(layered, parametric)
    offered = described()
    assert (offered["state"], offered["code"]) == ("available", None)
    assert "GET /world/character-catalogs" in offered["options"]
    withdraw(layered)
    withdraw(parametric)
    assert described()["code"] == "appearance_unavailable"


def test_readiness_names_a_database_that_serves_no_people_catalog(characters):
    """A serving database nobody published to is a declared state with its cause and command."""
    api, _version, publish, withdraw, (layered, parametric) = characters

    def check() -> dict:
        return api.client.get("/readyz").json()["checks"]["character_catalogs"]

    unpublished = check()
    assert (unpublished["ok"], unpublished["state"]) == (True, "people_catalog_unpublished")
    assert "exulanica-character-catalog publish --apply" in unpublished["detail"]
    publish(layered, parametric)
    served = check()
    assert (served["ok"], served["state"]) == (True, "served")
    assert {entry["kind"] for entry in served["current"]} == {"layered-people", "parametric-body"}
    withdraw(layered)
    assert check()["state"] == "people_catalog_unpublished"
