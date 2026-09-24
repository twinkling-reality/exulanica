"""The planner's and the composer's requests, byte for byte, as their call sites build them.

What the Companion sends a model is a product fact: two system prompts, the catalogue and packet
renderings, the response schema, the token budget and the repair messages. Moving the code that
builds them must not change one byte, so the requests are built here from fixed inputs, with a
policy that admits every text unchanged, and compared whole with the golden file beside this test.
Each sequence has a refused first reply, so the repair message is pinned as well.

A deliberate change to what is sent regenerates the file, reviewed in the same diff:

    uv run python tests/test_selection_request_goldens.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.epistemics.saved_names import SavedName
from exulanica.evidence import BlobId, EvidenceAddress
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.packet import ConfirmedPlace, EvidenceItem, EvidencePacket, ValueReference
from exulanica.selection.plan import EntitySelector, Intent, SelectionPlan
from exulanica.selection.question import EntityChoice, _without_names, compose_answer, propose_plan
from exulanica.selection.request_names import RequestNames

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_fakes import FakeTransport, RecordingPolicy, chat_body

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "selection-requests" / "requests.json"

PERSON = SavedName(uuid.UUID("00000000-0000-4000-8000-000000000001"), "person", "Maria Estrada")
PLACE = SavedName(uuid.UUID("00000000-0000-4000-8000-000000000002"), "place", "Lantern House")
CATALOGUE = (
    EntityChoice(PERSON.entity_id, "person", PERSON.name),
    EntityChoice(PLACE.entity_id, "place", PLACE.name),
)
NOW = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
QUESTION = f"Is {PERSON.name} wearing the running club shirt outside {PLACE.name}?"


def _reply(body: str) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(body)))


def _client(replies: list[HttpResponse]) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(replies)
    client = ModelClient(api_key="test-key-not-real", transport=transport, policy=RecordingPolicy())
    return client, transport


def _sent(transport: FakeTransport) -> list[dict[str, Any]]:
    return [{"url": r["url"], "payload": r["payload"]} for r in transport.requests]


def planner_requests() -> list[dict[str, Any]]:
    """A refused plan (mode 'all' over one id), its repair, and the accepted plan."""
    valid = SelectionPlan(
        intent=Intent.CAPTURES,
        entities=EntitySelector(ids=[PERSON.entity_id, PLACE.entity_id], mode="all"),
        semantic_query="running club shirt",
    ).model_dump(mode="json")
    refused = json.loads(json.dumps(valid))
    refused["entities"]["ids"] = [str(PERSON.entity_id)]
    client, transport = _client([_reply(json.dumps(refused)), _reply(json.dumps(valid))])
    propose_plan(client, QUESTION, CATALOGUE, names=RequestNames([PERSON, PLACE]), now=NOW)
    return _sent(transport)


def _packet() -> EvidencePacket:
    photograph = EvidenceAddress.photograph(BlobId.from_hex("ab" * 32))
    return EvidencePacket(
        items=(
            EvidenceItem(
                token="A6EF9VWNT6",
                span_id=uuid.UUID(int=11),
                assertion_id=None,
                address=photograph,
                capture_id=uuid.UUID(int=21),
                captured_at="2026-08-14T10:20:00+00:00",
                text=None,
                trust="capture_supported",
                confirmed_places=(ConfirmedPlace(PLACE.entity_id),),
            ),
            EvidenceItem(
                token="B7GHK3MNP4",
                span_id=uuid.UUID(int=12),
                assertion_id=uuid.UUID(int=31),
                address=photograph,
                capture_id=uuid.UUID(int=21),
                captured_at="2026-08-14T10:20:00+00:00",
                text="MARIA ESTRADA RUNNING CLUB at LANTERN HOUSE",
                trust="model_inference",
            ),
        ),
        values=(
            ValueReference("capture_count", "1", "how many captures the Selection matched"),
            ValueReference("shown_count", "1", "how many of them are in this packet"),
            ValueReference("date_0", "2026-08-14", "a capture date inside the Selection"),
        ),
        total_matched=1,
        citable=True,
    )


def composer_requests() -> list[dict[str, Any]]:
    """An answer citing a token the packet lacks, its repair, and the accepted answer."""
    refused = Answer(
        clauses=[
            AnswerClause(
                text="You were outside that place.",
                type=ClauseType.HISTORICAL,
                citations=["ZZZZZZZZZZ"],
            )
        ]
    )
    accepted = Answer(
        clauses=[
            AnswerClause(
                text="This photograph was taken there.",
                type=ClauseType.HISTORICAL,
                citations=["A6EF9VWNT6"],
            )
        ]
    )
    client, transport = _client(
        [_reply(refused.model_dump_json()), _reply(accepted.model_dump_json())]
    )
    names = RequestNames([PERSON, PLACE])
    asked = names.sendable(QUESTION)
    sent = _without_names(_packet(), names)
    compose_answer(client, asked, sent, placeholders=names.placeholders)
    return _sent(transport)


def build() -> dict[str, Any]:
    return {"planner": planner_requests(), "composer": composer_requests()}


@pytest.mark.parametrize("path", ["planner", "composer"])
def test_the_requests_are_the_ones_the_golden_file_holds(path):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    built = json.loads(json.dumps(build()[path]))
    assert built == golden[path], (
        f"the {path}'s requests changed; if that is intended, regenerate {GOLDEN.name} with "
        "`uv run python tests/test_selection_request_goldens.py` and review the diff"
    )


def test_the_golden_file_holds_two_requests_for_each_path():
    """The control: each sequence reached its repair, so the golden pins the repair message too."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert [len(golden[path]) for path in ("planner", "composer")] == [2, 2]


if __name__ == "__main__":
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(
        json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote tests/fixtures/selection-requests/{GOLDEN.name}")
