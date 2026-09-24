"""An answer leaves the server citing each photograph in the one form every client reads.

The packet renders each photograph as ``[A6EF9VWNT6]`` and a composer told to cite the bracketed
token copies the brackets. The validator accepts that, because ``EvidencePacket.resolve`` strips
them; the route keys ``citations`` by the bare token. Measured in the rehearsal of the personal
path: the answer cited ``[2EXZHVS3UA]``, the map held ``2EXZHVS3UA``, the page offered no chip,
and the answer it remembered kept no citation at all.
"""

from __future__ import annotations

import json
import re

from exulanica.api.composer_rights import composer_rights_check
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection import Intent, SelectionPlan
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.question import answer_question, compose_answer

from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_selection_answer import _answer_body, _budget
from test_selection_answer import answered as answered

#: A token as the packet renders it for the composer.
_RENDERED = re.compile(r"\[([A-Z0-9]{10})\]")


class BracketCitingComposer(FakeTransport):
    """A composer that cites the first photograph it was shown, brackets and all, twice over."""

    def post_json(self, url, *, headers, payload, timeout) -> HttpResponse:
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        # The packet is in the user's message; the system prompt carries an example token.
        shown = " ".join(
            str(message["content"]) for message in payload["messages"] if message["role"] == "user"
        )
        token = _RENDERED.search(shown).group(1)
        answer = Answer(
            clauses=[
                AnswerClause(
                    text="You were beside a waterfall.",
                    type=ClauseType.HISTORICAL,
                    citations=[f"[{token}]", token],
                )
            ]
        )
        return HttpResponse(
            status_code=200,
            text=json.dumps(chat_body(answer.model_dump_json(), model=str(payload["model"]))),
        )


def test_a_bracketed_citation_is_returned_as_the_token_it_resolved_to(answered):
    packet = answered.packet()
    real = packet.items[0].token
    cited = Answer(
        clauses=[
            AnswerClause(
                text="You were beside a waterfall.",
                type=ClauseType.HISTORICAL,
                citations=[f"[{real}]", real, f" [{real}] "],
            )
        ]
    )
    answer, deterministic, _ = compose_answer(
        answered.client([_answer_body(cited)]), "where was I?", packet
    )
    assert not deterministic, "the model's answer was accepted, not replaced"
    assert answer.clauses[0].citations == [real]


def test_every_clause_the_route_returns_cites_a_key_of_its_citation_map(answered):
    """End to end through ``answer_question``, with the tokens the request itself minted."""
    transport = BracketCitingComposer()
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=_budget(),
        policy=RecordingPolicy(),
    )
    outcome = answer_question(
        answered.repository.connection,
        client,
        "where was I?",
        answered.session,
        world_id=None,
        plan=SelectionPlan(intent=Intent.CAPTURES, semantic_query="waterfall"),
        before_compose=composer_rights_check(
            answered.repository.connection, answered.session.workspace_id
        ),
    )
    assert transport.call_count == 1
    assert not outcome.deterministic
    # What `POST /selection/ask` returns as `citations`, built the way the route builds it.
    citations = {item.token: item.uri for item in outcome.packet.items}
    cited = [token for clause in outcome.answer.clauses for token in clause.citations]
    assert cited, "the composer cited a photograph"
    assert all(token in citations for token in cited), cited
    assert not any("[" in token or "]" in token for token in cited)
