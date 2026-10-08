"""A reference job reading a person's own pictures, on a migrated database, all else scripted.

The picture reader answers through the real model client over a scripted transport, the policy is
the product's WorkspaceRequestPolicy with a picture check that records what it was asked, and the
picture source is a stand-in handing over bytes and right ids, or refusing by code.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.references import store
from exulanica.references.bundle import read_bundle
from exulanica.references.pictures import PictureUnavailable, ReferencePicture
from exulanica.references.worker import ReferenceWorker

from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_reference_worker import ACTOR, _Database, _Gate, _Spending

pytestmark = pytest.mark.postgres

PICTURE = uuid.UUID("3f6c1a2b-9d8e-4f70-8a61-52b3c4d5e6a1")
OTHER = uuid.UUID("3f6c1a2b-9d8e-4f70-8a61-52b3c4d5e6a2")
RIGHT = uuid.UUID("3f6c1a2b-9d8e-4f70-8a61-52b3c4d5e6b1")
#: A picture whose bytes cannot be read, and one the product already found a person in.
BROKEN = uuid.UUID("3f6c1a2b-9d8e-4f70-8a61-52b3c4d5e6a3")
PEOPLED = uuid.UUID("3f6c1a2b-9d8e-4f70-8a61-52b3c4d5e6a4")
IMAGE = b"\xff\xd8 a rendition's bytes"
READER = load_manifest()[Role.REFERENCE_VISION].primary.model_id


def _reading(value: dict) -> HttpResponse:
    return HttpResponse(200, json.dumps(chat_body(json.dumps(value), model=READER)))


@pytest.fixture
def scene(repository):
    connection, workspace_id = repository.connection, repository.workspace_id
    models = FakeTransport()
    asked: list[tuple[frozenset, str]] = []
    refuse_right: list[bool] = [False]

    def picture_right(_connection, _workspace, captures, handoff):
        asked.append((frozenset(captures), str(handoff.identities[0].role)))
        if refuse_right[0]:
            raise PrivacyAdmissionError("no right names this chain")

    def policy_for(workspace):
        return WorkspaceRequestPolicy(
            workspace,
            connection=borrowing(connection),
            photograph_right=picture_right,
            released_places=no_place_released,
        )

    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=models,
        budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=20),
        policy=RecordingPolicy(),
    )

    def source(workspace, capture, requester):
        assert (workspace, requester) == (workspace_id, ACTOR)
        if capture == OTHER:
            raise PictureUnavailable("picture_not_admitted")
        if capture == PEOPLED:
            raise PictureUnavailable("shows_people")
        if capture == BROKEN:
            raise OSError("the rendition's bytes are gone")
        return ReferencePicture(IMAGE, (RIGHT,))

    def worker(**changes):
        arguments = dict(
            client=client,
            policy_for=policy_for,
            spending=_Spending(_Gate()),
            adapter_for=lambda source: pytest.fail("no web source is asked"),
            workspaces=lambda: (workspace_id,),
            picture_source=source,
        )
        arguments.update(changes)
        return ReferenceWorker(_Database(repository), **arguments)

    def request(*pictures: uuid.UUID):
        made, _ = store.create_request(
            connection,
            workspace_id,
            offered_to=(workspace_id,),
            owner_actor_id=ACTOR,
            purpose="kind",
            web=False,
            description="a harbour town",
            withheld_words=["Rosalind"],
            prompts_sha256="e" * 64,
            pictures=pictures,
        )
        return made

    def finished(made):
        return store.read_request(connection, workspace_id, made.reference_id)

    return workspace_id, models, asked, refuse_right, worker, request, finished


def test_a_picture_is_read_into_notes_under_its_right(scene) -> None:
    workspace_id, models, asked, _refuse, worker, request, finished = scene
    models.default = _reading(
        {
            "refuse": None,
            "notes": [
                {"aspect": "buildings", "text": "white cube houses with blue doors"},
                {"aspect": "buildings", "text": "a woman sweeping a doorstep"},
            ],
        }
    )
    made = request(PICTURE)
    assert worker().run_once(workspace_id) == "complete"
    done = finished(made)
    bundle = read_bundle(done.bundle)
    assert [(note.text, note.basis, note.picture_id) for note in bundle.notes] == [
        ("white cube houses with blue doors", "own_picture", PICTURE)
    ]
    (picture,) = bundle.pictures
    assert (picture.picture_id, picture.model_right_ids) == (PICTURE, (RIGHT,))
    assert picture.model == ("nebius_token_factory", "reference_vision", READER)
    (step,) = [item for item in done.steps if item["step"] == "read_picture"]
    assert step == {
        "step": "read_picture",
        "capture_id": str(PICTURE),
        "state": "done",
        "kept": 1,
        "dropped": 1,
    }
    # The picture went out as the reading's one image, declared to the policy for its own role.
    assert asked == [(frozenset({PICTURE}), "reference_vision")]
    content = models.requests[0]["payload"]["messages"][1]["content"]
    assert [part["type"] for part in content] == ["text", "image_url"]


def test_a_refused_picture_keeps_only_its_reason(scene) -> None:
    workspace_id, models, _asked, _refuse, worker, request, finished = scene
    models.default = _reading(
        {"refuse": "shows_people", "notes": [{"aspect": "buildings", "text": "white houses"}]}
    )
    made = request(PICTURE)
    assert worker().run_once(workspace_id) == "complete"
    done = finished(made)
    bundle = read_bundle(done.bundle)
    assert bundle.notes == ()
    assert [picture.picture_id for picture in bundle.pictures] == [PICTURE]  # it was sent
    (step,) = [item for item in done.steps if item["step"] == "read_picture"]
    assert (step["state"], step["reason"]) == ("refused", "shows_people")


def test_a_picture_the_source_will_not_hand_over_is_missed_and_nothing_is_sent(scene) -> None:
    workspace_id, models, asked, _refuse, worker, request, finished = scene
    made = request(OTHER)
    assert worker().run_once(workspace_id) == "partial"
    done = finished(made)
    assert read_bundle(done.bundle).missed == ("pictures",)
    (step,) = [item for item in done.steps if item["step"] == "read_picture"]
    assert (step["state"], step["reason"]) == ("missed", "picture_not_admitted")
    assert models.requests == [] and asked == []


def test_a_picture_without_a_right_for_the_reader_is_never_sent(scene) -> None:
    workspace_id, models, asked, refuse, worker, request, finished = scene
    refuse[0] = True
    made = request(PICTURE)
    assert worker().run_once(workspace_id) == "partial"
    done = finished(made)
    (step,) = [item for item in done.steps if item["step"] == "read_picture"]
    assert (step["state"], step["reason"]) == ("missed", "policy_refused")
    assert models.requests == [] and asked == [(frozenset({PICTURE}), "reference_vision")]
    assert read_bundle(done.bundle).pictures == ()


def test_a_process_that_reads_no_pictures_says_so(scene) -> None:
    workspace_id, models, _asked, _refuse, worker, request, finished = scene
    made = request(PICTURE)
    assert worker(picture_source=None).run_once(workspace_id) == "partial"
    (step,) = [item for item in finished(made).steps if item["step"] == "read_picture"]
    assert (step["state"], step["reason"]) == ("missed", "pictures_not_read_here")
    assert models.requests == []


def test_a_claim_hands_the_worker_its_pictures_in_order(scene, repository) -> None:
    workspace_id, _models, _asked, _refuse, _worker, request, _finished = scene
    made = request(PICTURE, OTHER)
    claimed = store.claim(repository.connection, workspace_id, worker="test")
    assert claimed is not None and claimed.pictures == (PICTURE, OTHER)
    with pytest.raises(ValueError, match="at most 4 pictures, each once"):
        request(PICTURE, PICTURE)
    assert made.reference_id == claimed.request.reference_id


def test_a_note_carrying_a_withheld_word_or_a_saved_name_is_dropped(scene, monkeypatch) -> None:
    from exulanica.epistemics.saved_names import SavedName
    from exulanica.references import worker as worker_module

    workspace_id, models, _asked, _refuse, worker, request, finished = scene
    saved = (SavedName(uuid.uuid4(), "person", "Mara"),)
    monkeypatch.setattr(worker_module, "saved_names", lambda connection, workspace: saved)
    models.default = _reading(
        {
            "refuse": None,
            "notes": [
                {"aspect": "buildings", "text": "white cube houses with blue doors"},
                {"aspect": "buildings", "text": "a gate painted for rosalind"},
                {"aspect": "buildings", "text": "Mara keeps a blue gate by the well"},
            ],
        }
    )
    made = request(PICTURE)
    assert worker().run_once(workspace_id) == "complete"
    done = finished(made)
    assert [note.text for note in read_bundle(done.bundle).notes] == [
        "white cube houses with blue doors"
    ]
    (step,) = [item for item in done.steps if item["step"] == "read_picture"]
    assert (step["kept"], step["dropped"]) == (1, 2)


def test_a_picture_the_policy_let_through_is_named_though_no_answer_came_back(scene) -> None:
    workspace_id, models, asked, _refuse, worker, request, finished = scene
    models.default = HttpResponse(200, json.dumps(chat_body("not a form", model=READER)))
    made = request(PICTURE)
    assert worker().run_once(workspace_id) == "partial"
    done = finished(made)
    (picture,) = read_bundle(done.bundle).pictures
    assert (picture.picture_id, picture.model_right_ids) == (PICTURE, (RIGHT,))
    assert picture.model == ("nebius_token_factory", "reference_vision", READER)
    assert asked == [(frozenset({PICTURE}), "reference_vision")]
    (step,) = [item for item in done.steps if item["step"] == "read_picture"]
    assert step["state"] == "missed"


def test_a_picture_whose_bytes_cannot_be_read_is_a_missed_step(scene) -> None:
    workspace_id, models, asked, _refuse, worker, request, finished = scene
    made = request(BROKEN)
    assert worker().run_once(workspace_id) == "partial"
    (step,) = [item for item in finished(made).steps if item["step"] == "read_picture"]
    assert (step["state"], step["reason"]) == ("missed", "picture_unreadable")
    assert models.requests == [] and asked == []


def test_a_picture_the_product_found_a_person_in_is_refused_before_sending(scene) -> None:
    workspace_id, models, asked, _refuse, worker, request, finished = scene
    made = request(PEOPLED)
    worker().run_once(workspace_id)
    done = finished(made)
    (step,) = [item for item in done.steps if item["step"] == "read_picture"]
    assert (step["state"], step["reason"]) == ("refused", "shows_people")
    assert models.requests == [] and asked == []
    assert read_bundle(done.bundle).pictures == ()
