"""The place name routes: read each use, allow it against the words shown, and stop it.

What is held here is the HTTP half: which credential reaches which route, that a stranger cannot
tell another workspace's place from an invented id, that a grant is recorded only against the
exact notice the server states and only for the account holder who named the place, and that a
refusal says which it is in the application's ``{code, detail}`` shape. The rule itself is
``tests/test_place_names.py`` and the stored right ``tests/test_place_name_rights.py``.
"""

from __future__ import annotations

import copy
import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.consent.place_names import load_place_name_uses
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import tile_store
from fastapi.testclient import TestClient

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo
from tests_support_api import EVERY_PERMISSION, scratch_database

OWNER = "place-name-owner-token-long-enough-to-be-accepted"
#: Every use the shipped registry offers, in its own order, which is the order a place reads them.
OFFERED = [use.role.value for use in load_place_name_uses().uses]
READER = "place-name-reader-token-long-enough-to-be-accepted"
HOUSEMATE = "place-name-housemate-token-long-enough-to-be-accepted"
STRANGER = "place-name-stranger-token-long-enough-to-be-accepted"


class Site:
    def __init__(self, client, repository, place, person) -> None:
        self.client = client
        self.repository = repository
        self.place = place
        self.person = person

    def call(self, token: str, method: str, path: str, **kwargs):
        return self.client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )

    def events(self) -> list[dict]:
        return self.repository.connection.execute(
            "select event,model_role,sequence from place_name_right_event order by model_role,"
            "model_id,sequence"
        ).fetchall()


@pytest.fixture
def site(tmp_path, photo_dir, repository, spine_schema, monkeypatch):
    """A place and a person named by the owner, and four credentials for the one workspace or none.

    ``READER`` may read consent and not write it. ``HOUSEMATE`` may do everything the owner may in
    the same workspace, under another actor: somebody who did not name the place.
    """
    _, scratch = spine_schema
    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "house.jpg"))
    assert outcome.error is None, outcome.error
    workspace = repository.workspace_id
    actor = uuid.uuid4()
    named = {}
    for occurrence_class, name in (("place", "Lantern House"), ("person", "Maria Estrada")):
        occurrence = repository.connection.execute(
            "select occurrence_id from occurrence where class=%s order by occurrence_id limit 1",
            (occurrence_class,),
        ).fetchone()
        named[occurrence_class] = name_occurrence(
            IdentityRepository(repository.connection, workspace),
            AssertionWriter(repository.connection, workspace),
            occurrence_id=occurrence["occurrence_id"],
            display_name=name,
            actor=actor,
        ).entity_id

    def grant(workspace_id, who, permissions):
        return {"workspace_id": str(workspace_id), "actor": str(who), "permissions": permissions}

    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                OWNER: grant(workspace, actor, EVERY_PERMISSION),
                READER: grant(workspace, actor, ["consent.read"]),
                HOUSEMATE: grant(workspace, uuid.uuid4(), EVERY_PERMISSION),
                STRANGER: grant(uuid.uuid4(), uuid.uuid4(), EVERY_PERMISSION),
            }
        ),
    )
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
        environment_admission_root=tmp_path,
        tiles=tile_store(tmp_path / "tiles"),
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield Site(client, repository, named["place"], named["person"])


def _use(body: dict, use: str) -> dict:
    return next(each for each in body["uses"] if each["use"] == use)


def _allow(site: Site, token: str, use: str, notice: str | None = None):
    if notice is None:
        read = site.call(OWNER, "GET", f"/place-name-rights/{site.place}").json()
        notice = _use(read, use)["notice"]
    return site.call(
        token,
        "POST",
        f"/place-name-rights/{site.place}/grants",
        json={"use": use, "notice": notice},
    )


def test_a_place_reads_every_use_as_not_allowed_with_the_words_to_allow_it(site):
    response = site.call(OWNER, "GET", f"/place-name-rights/{site.place}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entity_id"] == str(site.place) and body["name"] == "Lantern House"
    assert [each["use"] for each in body["uses"]] == OFFERED
    for each in body["uses"]:
        assert each["state"] == "not_allowed" and each["allowed"] is False
        assert each["since"] is None and each["changed_at"] is None
        assert each["notice"] and each["purpose"] in each["notice"]
        for model in each["models"]:
            assert model["model"]["model_id"] in each["notice"]
            assert model["state"] == "not_allowed"
    assert site.call(OWNER, "GET", "/place-name-rights").json() == {"places": []}


def test_allowing_and_stopping_one_use_is_recorded_as_decisions_and_read_back(site):
    allowed = _allow(site, OWNER, "embedding")
    assert allowed.status_code == 201, allowed.text
    embedding = _use(allowed.json(), "embedding")
    assert embedding["state"] == "allowed" and embedding["since"] and embedding["until"]
    # One use allowed, and every other still not: a decision is for one use.
    assert {each["use"]: each["state"] for each in allowed.json()["uses"]} == {
        use: "allowed" if use == "embedding" else "not_allowed" for use in OFFERED
    }
    listed = site.call(OWNER, "GET", "/place-name-rights").json()["places"]
    assert [place["entity_id"] for place in listed] == [str(site.place)]

    stopped = site.call(
        OWNER, "POST", f"/place-name-rights/{site.place}/withdrawals", json={"use": "embedding"}
    )
    assert stopped.status_code == 201, stopped.text
    assert _use(stopped.json(), "embedding")["state"] == "withdrawn"
    assert [(e["event"], e["sequence"]) for e in site.events()] == [
        ("granted", 0),
        ("withdrawn", 1),
    ]


@pytest.mark.parametrize(
    ("use", "notice", "code"),
    [
        ("embedding", "Words nobody was shown.", "notice_changed"),
        ("vision", "Anything.", "not_offered"),
        # A role whose requests do not honour a release is never offered.
        ("reasoning_mid", "Anything.", "not_offered"),
    ],
)
def test_a_grant_the_server_did_not_offer_in_those_words_is_refused(site, use, notice, code):
    response = _allow(site, OWNER, use, notice)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == code
    assert site.events() == []


def test_only_the_account_holder_who_named_the_place_may_allow_it_and_anyone_may_stop_it(site):
    refused = _allow(site, HOUSEMATE, "embedding")
    assert refused.status_code == 409 and refused.json()["code"] == "not_yours"
    assert site.events() == []

    assert _allow(site, OWNER, "embedding").status_code == 201
    stopped = site.call(
        HOUSEMATE, "POST", f"/place-name-rights/{site.place}/withdrawals", json={"use": "embedding"}
    )
    assert stopped.status_code == 201
    assert _use(stopped.json(), "embedding")["state"] == "withdrawn"


def test_no_body_names_who_decided(site):
    read = site.call(OWNER, "GET", f"/place-name-rights/{site.place}").json()
    response = site.call(
        OWNER,
        "POST",
        f"/place-name-rights/{site.place}/grants",
        json={
            "use": "embedding",
            "notice": _use(read, "embedding")["notice"],
            "actor": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 422
    assert site.events() == []


def test_a_person_or_a_stranger_gets_what_an_invented_id_gets(site):
    """404 and never 403: a person's id, another workspace's place and nothing all answer alike."""
    assert _allow(site, OWNER, "embedding").status_code == 201, "the positive control"
    invented = uuid.uuid4()
    expected = {"code": "unknown_reference", "detail": "no such place"}
    for token, entity in ((OWNER, site.person), (OWNER, invented), (STRANGER, site.place)):
        read = site.call(token, "GET", f"/place-name-rights/{entity}")
        assert (read.status_code, read.json()) == (404, expected)
        stop = site.call(
            token, "POST", f"/place-name-rights/{entity}/withdrawals", json={"use": "embedding"}
        )
        assert (stop.status_code, stop.json()) == (404, expected)
    assert site.call(STRANGER, "GET", "/place-name-rights").json() == {"places": []}
    assert [e["event"] for e in site.events()] == ["granted"], "the stranger stopped nothing"


def test_reading_needs_consent_read_and_deciding_needs_consent_write(site):
    assert site.call(READER, "GET", f"/place-name-rights/{site.place}").status_code == 200
    assert site.call(READER, "GET", "/place-name-rights").status_code == 200
    refused = _allow(site, READER, "embedding")
    assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
    stop = site.call(
        READER, "POST", f"/place-name-rights/{site.place}/withdrawals", json={"use": "embedding"}
    )
    assert stop.status_code == 404
    assert site.events() == []


def test_a_decision_made_while_a_name_is_being_checked_is_refused_and_can_be_sent_again(
    site, ingest_spine
):
    assert _allow(site, OWNER, "embedding").status_code == 201
    _, open_another = ingest_spine
    reader = open_another().connection
    with reader.transaction():
        reader.execute("select asset_read_lock()")
        busy = site.call(
            OWNER, "POST", f"/place-name-rights/{site.place}/withdrawals", json={"use": "embedding"}
        )
    assert (busy.status_code, busy.json()["code"]) == (409, "busy")
    assert [e["event"] for e in site.events()] == ["granted"]
    again = site.call(
        OWNER, "POST", f"/place-name-rights/{site.place}/withdrawals", json={"use": "embedding"}
    )
    assert again.status_code == 201
