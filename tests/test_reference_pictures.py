"""Notes from a person's own picture: the reading call and what each note must pass.

No database and no network: the reading call goes to a scripted transport through a recording
policy, so what was asked of which model, for which picture, is read from the request itself.
"""

from __future__ import annotations

import ast
import json
import shutil
import uuid
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.models.transport import HttpResponse
from exulanica.references.catalogs import CATALOG_DIRECTORY, load_reference_catalogs
from exulanica.references.drafting import reference_prompts
from exulanica.references.notes import DraftedNote
from exulanica.references.pictures import (
    PICTURE_ROLE,
    picture_user_text,
    read_picture,
    screen_picture_notes,
)

from model_fakes import FakeTransport, RecordingPolicy, chat_body

ROOT = Path(__file__).resolve().parents[1]
AS_RUN = (
    ROOT
    / "docs/evaluation/artifacts/2026-10-07-reference-vision-latency"
    / "measure_reference_vision_latency-as-run.py.txt"
)
CAPTURE = uuid.UUID("6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")
KEPT = DraftedNote("buildings", "whitewashed cube houses with blue doors")


def _kept(*notes: DraftedNote) -> tuple[str, ...]:
    return tuple(note.text for note in screen_picture_notes(notes).kept)


def _dropped(note: DraftedNote) -> dict[str, int]:
    screened = screen_picture_notes((KEPT, note))
    assert screened.kept == (KEPT,)  # positive control: the plain note beside it is kept
    return dict(screened.dropped)


@pytest.mark.parametrize(
    ("note", "reason"),
    [
        (DraftedNote("clothing", "embroidered wool cloaks"), "aspect_closed"),
        (DraftedNote("buildings", "a woman at a blue door"), "person_word"),
        (DraftedNote("scale", "houses twice a child's height"), "person_word"),
        (DraftedNote("buildings", "a sign over the door reads Lantern House"), "lettering"),
        (DraftedNote("buildings", 'a shop sign saying "bakery"'), "lettering"),
        (DraftedNote("buildings", "x" * 79 + "y"), "cut_word"),
        (DraftedNote("buildings", "plans at www.example.test"), "link_or_contact"),
    ],
    ids=["clothing", "person", "possessive-person", "capital", "quote", "cut", "link"],
)
def test_a_picture_note_is_dropped_by_reason(note: DraftedNote, reason: str) -> None:
    assert _dropped(note) == {reason: 1}


def test_a_sentence_may_begin_with_a_capital_and_a_word_may_have_an_apostrophe() -> None:
    notes = (
        DraftedNote("buildings", "Domed chapels. Narrow lanes between them."),
        DraftedNote("vehicles_and_boats", "fishermen's boats tied at a stone quay"),
        DraftedNote("buildings", "x" * 79 + "."),
    )
    assert _kept(*notes) == tuple(note.text for note in notes)


def test_clothing_is_closed_to_pictures_and_open_to_web_notes() -> None:
    catalogs = load_reference_catalogs()
    assert "clothing" in catalogs.aspects
    assert "clothing" not in catalogs.picture_aspects
    assert set(catalogs.picture_aspects) == set(catalogs.aspects) - {"clothing"}


def test_a_picture_screen_closing_an_unknown_aspect_is_refused(tmp_path: Path) -> None:
    shutil.copytree(CATALOG_DIRECTORY, tmp_path, dirs_exist_ok=True)
    path = tmp_path / "reference-picture-screen.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["entries"][0]["closes_aspects"] = ["weather"]
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CatalogError, match="closes 'weather', which is no aspect"):
        load_reference_catalogs(tmp_path)


def test_the_picture_prompt_is_the_one_the_timeout_basis_measured() -> None:
    """The role's timeout rests on calls made with these words; a change to them is re-measured."""
    tree = ast.parse(AS_RUN.read_text(encoding="utf-8"))
    measured = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "INSTRUCTIONS" for target in node.targets
        )
    )
    assert reference_prompts().picture == measured
    assert picture_user_text(load_reference_catalogs()) == (
        "The aspects:\n"
        + "\n".join(f"- {key}" for key in load_reference_catalogs().picture_aspects)
        + "\nThe picture:"
    )


def _client(answer: dict) -> tuple[ModelClient, FakeTransport, RecordingPolicy]:
    transport = FakeTransport()
    model = ModelClient(api_key="test-key-not-real", transport=transport).manifest[PICTURE_ROLE]
    transport.default = HttpResponse(
        200, json.dumps(chat_body(json.dumps(answer), model=model.primary.model_id))
    )
    policy = RecordingPolicy()
    client = ModelClient(api_key="test-key-not-real", transport=transport, policy=policy)
    return client, transport, policy


def test_a_reading_declares_its_picture_to_the_policy_and_asks_the_picture_role() -> None:
    answer = {"refuse": None, "notes": [{"aspect": "buildings", "text": "white cube houses"}]}
    client, transport, policy = _client(answer)
    read = read_picture(client, b"\xff\xd8 not really a jpeg", capture_id=CAPTURE)
    assert read.notes == (DraftedNote("buildings", "white cube houses"),)
    assert read.refused is None and read.call is not None
    (request,) = policy.requests
    assert request.role == Role.REFERENCE_VISION
    assert request.photographs == frozenset({CAPTURE})
    assert request.images == 1
    sent = transport.requests[0]["payload"]
    assert sent["model"] == "openbmb/MiniCPM-V-4_5"
    assert sent["messages"][0]["content"] == reference_prompts().picture


def test_a_refused_picture_keeps_nothing_but_its_reason() -> None:
    answer = {
        "refuse": "shows_people",
        "notes": [{"aspect": "buildings", "text": "white cube houses"}],
    }
    client, _transport, _policy = _client(answer)
    read = read_picture(client, b"\xff\xd8", capture_id=CAPTURE)
    assert (read.notes, read.refused) == ((), "shows_people")


def test_a_reading_with_a_field_for_anything_else_is_refused_whole() -> None:
    answer = {"refuse": None, "notes": [], "place": "Santorini"}
    client, _transport, _policy = _client(answer)
    read = read_picture(client, b"\xff\xd8", capture_id=CAPTURE)
    assert (read.notes, read.refused) == ((), "read_refused")
