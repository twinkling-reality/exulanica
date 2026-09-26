"""What ``answer_question`` returns on every one of its exits, held whole to a golden document.

``answer_question`` has eighteen ways to return an :class:`AnsweredQuestion` and three to raise, and
the answer path's split keeps it where it is because tests replace its module globals. Each exit
is driven here through the product's own code over a workspace with a person and a place saved on
a photograph's sign, and what it returns is reduced to a document: the answer, the plan, what the
Selection and the packet held, the flags, the refusals, the calls and the names. Identifiers are
numbered in the order they first appear and packet tokens are drawn from a counter, so a document
says the same thing on every run. A split that moves code must leave every document as it was.

A deliberate change to an exit regenerates the documents, reviewed in the same diff:

    EXULANICA_EXIT_DOCUMENTS=write uv run pytest tests/test_answered_question_exits.py

Any other run only reads them.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import itertools
import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.composer_rights import composer_rights_check
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.epistemics.saved_names import SavedName
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.transport import HttpResponse
from exulanica.selection import packet as packet_module
from exulanica.selection import question as question_module
from exulanica.selection import society_question as society_module
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.plan import (
    ContentScope,
    ContentSelector,
    EntitySelector,
    EpistemicScope,
    Intent,
    PlaceSelector,
    SelectionPlan,
    SocietyAspect,
    SocietyScope,
    SocietySelector,
)
from exulanica.selection.question import AnsweredQuestion, answer_question
from exulanica.selection.society_question import SocietyRefusal, build_scene

from model_fakes import chat_body
from test_companion_saved_names import PERSON, PLACE, _client, named
from test_society_question import EVENTS, SNAPSHOT, STATE, TARGETS

pytestmark = pytest.mark.postgres

__all__ = ["named"]

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "answered-question" / "exits.json"
WRITE = os.environ.get("EXULANICA_EXIT_DOCUMENTS") == "write"
NOW = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
QUESTION = f"Is {PERSON} wearing the running club shirt outside {PLACE}?"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _reply(value: Any) -> HttpResponse:
    body = value if isinstance(value, str) else json.dumps(value)
    return HttpResponse(status_code=200, text=json.dumps(chat_body(body)))


def _answer(*clauses: AnswerClause) -> HttpResponse:
    return _reply(Answer(clauses=list(clauses)).model_dump_json())


_META = AnswerClause(text="Your photographs show a running club.", type=ClauseType.META)
_UNCITED = AnswerClause(text="You were there.", type=ClauseType.HISTORICAL)
#: A plan ``SelectionPlan`` refuses after the schema accepts it: mode 'all' over one id.
_REFUSED_PLAN = {
    **SelectionPlan(
        intent=Intent.CAPTURES,
        entities=EntitySelector(ids=[uuid.UUID(int=1), uuid.UUID(int=2)], mode="all"),
    ).model_dump(mode="json"),
    "entities": {"ids": [str(uuid.UUID(int=1))], "mode": "all"},
}


@dataclasses.dataclass
class Context:
    repository: Any
    store: Any
    session: Any
    entities: dict[str, uuid.UUID]
    monkeypatch: Any

    @property
    def connection(self):
        return self.repository.connection

    def ask(
        self,
        replies: list[HttpResponse],
        *,
        plan: SelectionPlan | None = None,
        before_compose: Callable | None = None,
        client: Any = "scripted",
        question: str = QUESTION,
        society: uuid.UUID | None = None,
        selected: uuid.UUID | None = None,
    ) -> AnsweredQuestion:
        chosen = _client(self.repository, replies)[0] if client == "scripted" else client
        return answer_question(
            self.connection,
            chosen,
            question,
            self.session,
            plan=plan,
            now=NOW,
            store=self.store,
            # Every exit reads captures or memories, which belong to the workspace and not to a
            # world, so no world's authored or simulated content is asked for.
            # A society exit names a world; its society is the small square's recorded run,
            # read through the replaced ``read_scene`` (``_square``).
            world_id=None if society is None else "world:exits",
            before_compose=before_compose
            or composer_rights_check(self.connection, self.repository.workspace_id),
            society_version_id=society,
            selected_inhabitant_id=selected,
        )


def _captures(query: str, **extra: Any) -> SelectionPlan:
    return SelectionPlan(intent=Intent.CAPTURES, semantic_query=query, **extra)


def _unlinked_place(context: Context) -> uuid.UUID:
    return context.connection.execute(
        "insert into entity (workspace_id,class) values (%s,'place') returning entity_id",
        (context.repository.workspace_id,),
    ).fetchone()["entity_id"]


def _refuse(captures, handoff) -> None:
    raise PrivacyAdmissionError("no personal model right names this model")


def _changed_during_composition(context: Context) -> AnsweredQuestion:
    original = question_module.compose_answer

    def compose_then_retract(client, question, packet, **kwargs):
        composed = original(client, question, packet, **kwargs)
        item = next(item for item in packet.items if item.assertion_id is not None)
        AssertionWriter(context.connection, context.repository.workspace_id).retract(
            item.assertion_id, retracted_by=context.session.actor, reason="changed while composing"
        )
        return composed

    context.monkeypatch.setattr(question_module, "compose_answer", compose_then_retract)
    return context.ask([_answer(_META)], plan=_captures("running club"))


def _square(context: Context, *, also_saved=(), refusal=None) -> None:
    """The society the page shows: the small square's recorded run, read as ``read_scene`` reads
    one, with any name ``also_saved`` saved beside the workspace's own."""

    def read(connection, workspace_id, world_id, society, *, authorize, question, saved):
        if refusal is not None:
            return refusal
        return build_scene(
            SNAPSHOT,
            targets=TARGETS,
            events=EVENTS,
            explaining=EVENTS,
            selected=society.inhabitant_id,
            question=question,
            saved=(*saved, *also_saved),
        )

    context.monkeypatch.setattr(question_module, "read_scene", read)


def _explained_person() -> uuid.UUID:
    return uuid.UUID(next(p["id"] for p in STATE["inhabitants"] if p["explanation"]["event_ids"]))


def _colliding(context: Context) -> AnsweredQuestion:
    person = STATE["inhabitants"][0]
    first = person["display_name"].split()[0]
    _square(context, also_saved=(SavedName(uuid.UUID(int=77), "person", f"{first} Cohen"),))
    return context.ask(
        [],
        question=f"Why is {first} there?",
        society=SNAPSHOT["version_id"],
        selected=uuid.UUID(person["id"]),
    )


def _shared_name(context: Context) -> AnsweredQuestion:
    first = STATE["inhabitants"][0]["display_name"].split()[0]
    _square(context, also_saved=(SavedName(uuid.UUID(int=78), "person", f"{first} Cohen"),))
    return context.ask(
        [],
        plan=_captures("harbour"),
        question=f"Show me photos of {first}",
        society=SNAPSHOT["version_id"],
    )


def _typed_label(context: Context) -> AnsweredQuestion:
    _square(context)
    return context.ask([], question="Why is [inhabitant B] there?", society=SNAPSHOT["version_id"])


def _people_unreadable(context: Context) -> AnsweredQuestion:
    _square(context, refusal=SocietyRefusal.UNAVAILABLE)
    return context.ask([], plan=_captures("ferris wheel"), society=SNAPSHOT["version_id"])


def _about_a_person(context: Context) -> AnsweredQuestion:
    _square(context)
    return context.ask(
        [],
        plan=SelectionPlan(
            intent=Intent.SOCIETY,
            society=SocietySelector(scope=SocietyScope.SELECTED, aspect=SocietyAspect.WHY),
        ),
        client=None,
        society=SNAPSHOT["version_id"],
        selected=_explained_person(),
    )


#: Each exit, and how to reach it. A value that raises is the exit's document.
EXITS: dict[str, Callable[[Context], AnsweredQuestion]] = {
    "the planner could not fill the form": lambda c: c.ask(
        [_reply(_REFUSED_PLAN), _reply(_REFUSED_PLAN)]
    ),
    "the planner named an entity nobody has": lambda c: c.ask(
        [
            _reply(
                SelectionPlan(
                    intent=Intent.CAPTURES, entities=EntitySelector(ids=[uuid.UUID(int=99)])
                ).model_dump_json()
            )
        ]
    ),
    "the planner referred to an entity the question does not name": lambda c: c.ask(
        [
            _reply(
                SelectionPlan(
                    intent=Intent.CAPTURES,
                    entities=EntitySelector(ids=[c.entities["person"]]),
                    semantic_query="running club",
                ).model_dump_json()
            )
        ],
        question=f"Who is wearing the running club shirt outside {PLACE}?",
    ),
    "a content Selection found nothing": lambda c: c.ask(
        [],
        plan=SelectionPlan(
            intent=Intent.CONTENT,
            place=PlaceSelector(ids=[_unlinked_place(c)]),
            content=ContentSelector(scope=ContentScope.MEMORIES_ONLY),
        ),
        client=None,
    ),
    "a content Selection found rows": lambda c: c.ask(
        [],
        plan=SelectionPlan(
            intent=Intent.CONTENT,
            place=PlaceSelector(ids=[c.entities["place"]]),
            content=ContentSelector(scope=ContentScope.MEMORIES_ONLY),
        ),
        client=None,
    ),
    "the packet was empty": lambda c: c.ask([], plan=_captures("zebra crossing")),
    "a name is both a saved person's and the selected inhabitant's": _colliding,
    "a name is a saved person's and an unselected inhabitant's": _shared_name,
    "a question carries a typed inhabitant label": _typed_label,
    "the world's people could not be read": _people_unreadable,
    "a society question answered from the society": _about_a_person,
    # A question about the world's simulated people asked where the page shows none: refused by
    # name, with no model asked and nothing searched.
    "a society question with no society in view": lambda c: c.ask(
        [],
        plan=SelectionPlan(
            intent=Intent.SOCIETY,
            society=SocietySelector(scope=SocietyScope.WORLD, aspect=SocietyAspect.RECENT),
        ),
        client=None,
    ),
    "the packet held guesses": lambda c: c.ask(
        [], plan=_captures("running club", epistemic=EpistemicScope.INCLUDE_PROPOSALS)
    ),
    "no right let the packet reach the composer": lambda c: c.ask(
        [], plan=_captures("running club"), before_compose=_refuse
    ),
    "the composer answered": lambda c: c.ask([_answer(_META)], plan=_captures("running club")),
    "the composer answered after one repair": lambda c: c.ask(
        [_answer(_UNCITED), _answer(_META)], plan=_captures("running club")
    ),
    "the composer failed twice": lambda c: c.ask(
        [_answer(_UNCITED), _answer(_UNCITED)], plan=_captures("running club")
    ),
    "the evidence changed while composing": _changed_during_composition,
    "raises: no before_compose check": lambda c: c.ask([], before_compose="not callable"),
    "raises: no client for a question in words": lambda c: c.ask([], client=None),
    "raises: a supplied plan names an entity nobody has": lambda c: c.ask(
        [],
        plan=SelectionPlan(
            intent=Intent.CAPTURES, entities=EntitySelector(ids=[uuid.UUID(int=98)])
        ),
    ),
}


def _numbered(value: Any) -> Any:
    """Every identifier numbered by first appearance, inside strings as well."""
    seen: dict[str, str] = {}

    def name(found: re.Match[str]) -> str:
        return seen.setdefault(found.group(0), f"<id {len(seen) + 1}>")

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        if isinstance(node, list | tuple):
            return [walk(item) for item in node]
        if isinstance(node, uuid.UUID):
            return name(_UUID.fullmatch(str(node)))
        if isinstance(node, str):
            return _UUID.sub(name, node)
        return node

    return walk(value)


def document(outcome: AnsweredQuestion) -> dict[str, Any]:
    result = outcome.result
    packet = outcome.packet
    content = outcome.content_packet
    return _numbered(
        {
            "answer": [clause.model_dump(mode="json") for clause in outcome.answer.clauses],
            "plan": None if outcome.plan is None else outcome.plan.model_dump(mode="json"),
            "result": None
            if result is None
            else {
                "intent": str(result.intent),
                "captures": [capture.capture_id for capture in result.captures],
                "content": [[row.result_kind, row.source_id] for row in result.content],
                "total_matched": result.total_matched,
                "includes_proposals": result.includes_proposals,
            },
            "packet": None
            if packet is None
            else {
                "citable": packet.citable,
                "total_matched": packet.total_matched,
                "items": [
                    {
                        "token": item.token,
                        "capture_id": item.capture_id,
                        "trust": item.trust,
                        "text": item.text,
                        "confirmed_places": [p.entity_id for p in item.confirmed_places],
                    }
                    for item in packet.items
                ],
                "values": [[value.key, value.text] for value in packet.values],
            },
            "society_packet": None
            if outcome.society_packet is None
            else {
                "items": [
                    [item.result_kind, item.tick, item.line]
                    for item in outcome.society_packet.items
                ],
                "inhabitants": [label for label, _ in outcome.society_packet.inhabitants],
            },
            "content_packet": None
            if content is None
            else {
                "total_matched": content.total_matched,
                "items": [
                    [item.token, item.truth_class, item.result_kind, item.label]
                    for item in content.items
                ],
            },
            "repaired": outcome.repaired,
            "deterministic": outcome.deterministic,
            "abstention": None if outcome.abstention is None else str(outcome.abstention),
            "rejections": list(outcome.rejections),
            "calls": [
                {
                    key: value
                    for key, value in dataclasses.asdict(call).items()
                    if key != "latency_ms"
                }
                for call in outcome.calls
            ],
            "names": [list(pair) for pair in outcome.names],
        }
    )


@pytest.fixture
def context(named, monkeypatch) -> Context:
    counter = itertools.count(1)
    monkeypatch.setattr(packet_module, "_token", lambda taken: f"TOKEN{next(counter):05d}")
    monkeypatch.setattr(society_module, "_token", lambda taken: f"TOKEN{next(counter):05d}")
    repository, store, session, entities = named
    return Context(repository, store, session, entities, monkeypatch)


def _run(exit_name: str, context: Context) -> dict[str, Any]:
    try:
        return document(EXITS[exit_name](context))
    except Exception as raised:  # The exception is the exit's document.
        return {"raises": type(raised).__name__, "message": _numbered(str(raised))}


@pytest.mark.parametrize("exit_name", sorted(EXITS))
def test_each_exit_returns_the_document_it_always_has(context, exit_name):
    found = _run(exit_name, context)
    if WRITE:
        golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
        golden[exit_name] = found
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(golden, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert found == golden[exit_name], f"{exit_name}: the answer path's exit changed"


def test_every_exit_is_a_different_document():
    """The control: twenty-one ways to leave the function, twenty-one things said."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(golden) == sorted(EXITS)
    documents = [json.dumps(golden[name], sort_keys=True) for name in sorted(golden)]
    assert len(set(documents)) == len(documents)
    abstentions = {
        golden[name].get("abstention") for name in golden if "raises" not in golden[name]
    }
    assert {
        "UNANSWERABLE_NOT_UNDERSTOOD",
        "UNANSWERABLE_NOT_CAPTURED",
        "UNANSWERABLE_AMBIGUOUS",
        None,
    } <= abstentions
