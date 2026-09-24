"""The model rights a person may grant from the app, and the exact words each is granted against.

``exulanica/ingest/model-right-uses.v1.json`` declares the hosted roles a grounded Companion answer
needs: vision, which is sent the photograph; embedding, which is sent the descriptions made from it;
and reasoning_cheap, the composer, which is sent the descriptions and dates of the photographs a
question finds. ``GET /personal-admission`` states each of them, depth first, with its notice, and
``POST /personal-admission`` grants one only against those exact words.

The last test is the path a person takes in the app, through the routes the app calls: grant, get
an answer composed, stop the composer's right, and see the next answer refuse it by name. The
composer is a scripted transport; no hosted model is called.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid

import pytest
from exulanica.api.composer_rights import composer_rights_check
from exulanica.ingest.model_rights import grant_model_right
from exulanica.ingest.personal_admission import (
    DEPTH_MODEL_NOTICE,
    MODEL_RIGHT_USES,
    MODEL_RIGHT_USES_PATH,
    load_model_right_uses,
    model_right_offers,
    parse_model_right_uses,
    role_handoff,
    role_notices,
)
from exulanica.ingest.privacy import authorize_personal_capture
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection import Session
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.plan import Intent, SelectionPlan
from exulanica.selection.question import answer_question

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_intake_upload import upload as upload
from test_personal_admission_route import batch, post

pytestmark = pytest.mark.postgres

#: The requests that name a photograph, and so need a personal model right for their role:
#: docs/companion-question.md, "Every hosted request passes one boundary".
PHOTOGRAPH_ROLES = ("vision", "embedding", "reasoning_cheap")


def _raw() -> dict:
    return json.loads(MODEL_RIGHT_USES_PATH.read_text(encoding="utf-8"))


# -- the uses file ---------------------------------------------------------------------------------


def test_every_request_that_names_a_photograph_has_an_offered_right():
    assert tuple(use.role for use in MODEL_RIGHT_USES.uses) == PHOTOGRAPH_ROLES
    assert tuple(role_notices()) == ("depth", *PHOTOGRAPH_ROLES)
    assert role_notices()["depth"] == DEPTH_MODEL_NOTICE


@pytest.mark.parametrize("role", PHOTOGRAPH_ROLES)
def test_a_hosted_notice_names_the_host_and_every_model_of_the_chain_in_order(role):
    notice = role_notices()[role]
    handoff = role_handoff(role)
    assert "outside Exulanica" in notice
    assert "api.tokenfactory.nebius.com" in notice
    named = [notice.index(identity.model_id) for identity in handoff.identities]
    assert named == sorted(named) and len(handoff.identities) >= 1
    assert chr(0x2014) not in notice  # no em dash in a notice a person reads


def test_no_hosted_notice_says_people_are_hidden_before_the_model_sees_them():
    """The vision copy is the unmasked rendition: the vision model is what finds the people."""
    for role in PHOTOGRAPH_ROLES:
        assert "hidden before" not in role_notices()[role]
    assert "not hidden from this model" in role_notices()["vision"]


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (lambda raw: raw.update(extra=1), "exactly the keys"),
        (lambda raw: raw.update(profile="exulanica.model-right-uses/v2"), "declares"),
        (lambda raw: raw.update(notice=raw["notice"].replace("{kept}", "")), "fills exactly"),
        (lambda raw: raw["uses"][0].update(extra=1), "exactly the keys"),
        (lambda raw: raw["uses"][0].update(role="depth"), "no hosted model role"),
        (lambda raw: raw["uses"][0].update(role="clairvoyance"), "no hosted model role"),
        (lambda raw: raw["uses"][1].update(role=raw["uses"][0]["role"]), "each hosted role once"),
        (lambda raw: raw["uses"][0].update(offered_with="upload"), "detect or review"),
        (lambda raw: raw["uses"][0].update(label=" padded"), "trimmed"),
        (lambda raw: raw["uses"][0].update(stop="line\nbreak"), "control character"),
        (lambda raw: raw.update(uses=[]), "at least one use"),
    ],
)
def test_the_uses_file_is_refused_whole_on_anything_it_does_not_know(change, refusal):
    raw = _raw()
    assert parse_model_right_uses(raw) == load_model_right_uses()  # positive control
    change(raw)
    with pytest.raises(ValueError, match=refusal):
        parse_model_right_uses(raw)


# -- the status read states the offers -------------------------------------------------------------


def test_the_status_read_states_every_offer_with_its_exact_words(upload):
    offers = upload.get("/personal-admission").json()["model_right_offers"]
    assert [offer["role"] for offer in offers] == ["depth", *PHOTOGRAPH_ROLES]
    for offer, stated in zip(offers, model_right_offers(), strict=True):
        assert offer == stated.as_record()
        assert offer["notice"] == role_notices()[offer["role"]]
        assert offer["models"] == [
            identity.as_record() for identity in role_handoff(offer["role"]).identities
        ]
        assert offer["label"] and offer["short"] and offer["stop"]
    assert {offer["role"]: offer["offered_with"] for offer in offers} == {
        "depth": "review",
        **dict.fromkeys(PHOTOGRAPH_ROLES, "detect"),
    }


def _grant_all(upload, count=1):
    """One detection admission granting every photograph role against the stated words."""
    body = batch(upload, count=count)
    until = body["authority"]["valid_until"]
    notices = role_notices()
    body["model_rights"] = [
        {"role": role, "valid_until": until, "notice": notices[role]} for role in PHOTOGRAPH_ROLES
    ]
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    return response.json(), until


def _source(upload, capture_id):
    status = upload.get("/personal-admission").json()
    return next(s for s in status["sources"] if s["capture_id"] == capture_id)


def test_a_grant_against_the_stated_words_is_recorded_and_listed_as_granted_against_them(upload):
    admitted, until = _grant_all(upload)
    receipt = admitted["receipts"][0]
    expected = [
        identity.as_record()
        for role in PHOTOGRAPH_ROLES
        for identity in role_handoff(role).identities
    ]
    assert [right["model"] for right in receipt["model_rights"]] == expected
    listed = _source(upload, receipt["capture_id"])["model_rights"]
    assert sorted((r["model"]["role"], r["model"]["model_id"]) for r in listed) == sorted(
        (m["role"], m["model_id"]) for m in expected
    )
    assert {(r["state"], r["notice_current"]) for r in listed} == {("current", True)}
    # The words the person was shown are fixed into the authority the screening receipt hashes.
    (scope,) = upload.rows("select authorization_scope from capture_reconstruction_authorization")
    assert scope["authorization_scope"]["model_rights"] == [
        {"role": role, "valid_until": until, "notice": role_notices()[role]}
        for role in sorted(PHOTOGRAPH_ROLES)
    ]


def test_a_role_the_app_does_not_offer_is_still_granted_only_without_words(upload):
    """The local segmentation roles are granted through the route with no notice, as before."""
    body = batch(upload, count=1)
    until = body["authority"]["valid_until"]
    body["model_rights"] = [{"role": "object_segmentation", "valid_until": until}]
    granted = post(upload, "/personal-admission", body)
    assert granted.status_code == 202, granted.text
    (receipt,) = granted.json()["receipts"]
    assert [right["model"] for right in receipt["model_rights"]] == [
        identity.as_record() for identity in role_handoff("object_segmentation").identities
    ]
    listed = _source(upload, receipt["capture_id"])["model_rights"]
    assert {(r["state"], r["notice_current"]) for r in listed} == {("current", False)}


# -- a right granted before these words existed --------------------------------------------


def test_a_right_granted_before_its_role_had_words_is_carried_and_says_so(upload):
    """Carried: its own row's terms still decide every read, and the list says it had no words.

    Before this file existed a hosted role was granted with no notice, and the admission recorded
    ``{"role", "valid_until", "notice": None}`` in the authority scope. That authority is built
    here exactly that way, and the vision rights granted under it, for the photograph an ordinary
    admission with no rights uploaded.
    """
    body = batch(upload, count=1)
    body["model_rights"] = []
    receipt = post(upload, "/personal-admission", body).json()["receipts"][0]
    capture_id = uuid.UUID(receipt["capture_id"])
    (holder,) = upload.rows(
        "select authorized_by from capture_reconstruction_authorization where capture_id=%s",
        capture_id,
    )
    actor = holder["authorized_by"]
    now = dt.datetime.now(dt.UTC)
    until = now + dt.timedelta(hours=1)
    earlier = authorize_personal_capture(
        upload.repository,
        capture_id=capture_id,
        actor=actor,
        account_authority_basis="I own these test photographs",
        authorization_scope={
            "purpose": "Inspect my photographs",
            "model_rights": [{"role": "vision", "valid_until": until.isoformat(), "notice": None}],
        },
        purpose="Inspect my photographs",
        authorized_at=now - dt.timedelta(minutes=1),
        valid_until=until,
    )
    handoff = role_handoff("vision")
    for identity in handoff.identities:
        grant_model_right(
            upload.repository,
            capture_id=capture_id,
            authorization_id=earlier.authorization_id,
            identity=identity,
            destination=handoff.destination,
            granted_by=actor,
            purpose="Inspect my photographs",
            valid_until=until,
        )
    upload.repository.connection.commit()

    listed = _source(upload, str(capture_id))["model_rights"]
    assert {(r["model"]["role"], r["state"], r["notice_current"]) for r in listed} == {
        ("vision", "current", False)
    }
    # Carried, not lapsed: the photograph still reaches the vision chain the right names.
    upload.drain(screened=False)
    assert upload.vision.calls == 1
    # And no new right can be recorded that way.
    body["model_rights"] = [{"role": "vision", "valid_until": body["authority"]["valid_until"]}]
    refused = post(upload, "/personal-admission", body)
    assert refused.status_code == 409, refused.text
    assert "granted against this server's own notice" in refused.json()["detail"]


# -- the path a person takes: grant, answer, stop, refused by name ---------------------------


def _client(responses):
    transport = FakeTransport(responses)
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        policy=RecordingPolicy(),
    )
    return client, transport


def _ask(upload, client):
    # A supplied plan, so the planner makes no call and the composer's is the only one possible.
    # The query matches the sign the vision double transcribes, so the packet is not empty.
    return answer_question(
        upload.repository.connection,
        client,
        "What does the sign say?",
        Session(workspace_id=upload.workspace_id, actor=uuid.uuid4()),
        plan=SelectionPlan(intent=Intent.CAPTURES, semantic_query="gullfoss"),
        store=upload.store,
        # A captures plan reads photographs, which belong to the workspace and not to a world.
        world_id=None,
        before_compose=composer_rights_check(upload.repository.connection, upload.workspace_id),
    )


def test_stopping_the_composer_right_refuses_the_next_answer_by_name(upload):
    receipt = _grant_all(upload)[0]["receipts"][0]
    upload.drain(screened=False)
    assert upload.vision.calls == 1

    reply = Answer(clauses=[AnswerClause(text="The sign reads Gullfoss.", type=ClauseType.META)])
    client, transport = _client(
        [HttpResponse(status_code=200, text=json.dumps(chat_body(reply.model_dump_json())))]
    )
    composed = _ask(upload, client)
    assert composed.packet is not None and not composed.packet.is_empty
    assert transport.call_count >= 1
    assert not any(r.startswith("model_right_refused") for r in composed.rejections)

    stopped = [
        right["right_id"]
        for right in _source(upload, receipt["capture_id"])["model_rights"]
        if right["model"]["role"] == "reasoning_cheap"
    ]
    assert len(stopped) == len(role_handoff("reasoning_cheap").identities)
    for right_id in stopped:
        withdrawn = post(upload, f"/personal-admission/model-rights/{right_id}/withdraw", {})
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["state"] == "ended"

    client, transport = _client([RuntimeError("the composer was called after its right ended")])
    refused = _ask(upload, client)
    assert transport.call_count == 0
    assert refused.deterministic is True
    (reason,) = refused.rejections
    assert re.match(r"model_right_refused: capture [0-9a-f-]{36}: the model right for ", reason)
    assert reason.endswith("was withdrawn")
    listed = _source(upload, receipt["capture_id"])["model_rights"]
    assert {r["state"] for r in listed if r["model"]["role"] == "reasoning_cheap"} == {"ended"}
    assert {r["state"] for r in listed if r["model"]["role"] != "reasoning_cheap"} == {"current"}
