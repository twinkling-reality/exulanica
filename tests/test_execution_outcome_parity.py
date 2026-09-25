"""The page reads the execution record with the server's own words for an attempt.

The server's record says how each attempt ended and whether its cost is known
(``AttemptOutcome`` and ``CallCost`` in ``exulanica/selection/calls.py``), and the page finds the
composer by the role it runs as (``web/packages/app/src/companion-ask-api.ts``). Neither language
reads the other, so each list is written twice and held to one text here. The composer's role is
read from a call ``compose_answer`` actually makes, not from a copy of it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from exulanica.models.transport import HttpResponse
from exulanica.selection.answer import Answer, AnswerClause
from exulanica.selection.calls import AttemptOutcome, CallCost, CallLog
from exulanica.selection.question import compose_answer

from model_fakes import RecordingPolicy, chat_body
from test_companion_acceptance import retained_packet
from test_consent_wording_is_one_text import typescript_constant

__all__ = ["retained_packet"]

SOURCE = Path(__file__).resolve().parents[1] / "web/packages/app/src/companion-ask-api.ts"


def _typescript_list(name: str, source: str) -> list[str]:
    """The strings of ``export const <name> = [...] as const;`` in ``source``, in order."""
    match = re.search(rf"^export const {name} = \[(.*?)\] as const;", source, re.MULTILINE | re.S)
    assert match is not None, f"{name} is not exported from {SOURCE.name} as a literal list"
    return re.findall(r"'([^']*)'", match.group(1))


def test_the_page_names_every_outcome_the_server_writes():
    source = SOURCE.read_text(encoding="utf-8")
    assert _typescript_list("CALL_OUTCOMES", source) == [member.value for member in AttemptOutcome]
    assert _typescript_list("CALL_COSTS", source) == [member.value for member in CallCost]


def test_the_page_finds_the_composer_by_the_role_it_runs_as(client, transport, retained_packet):
    answer = Answer(clauses=[AnswerClause(text="Nothing.", type="meta")]).model_dump_json()
    transport.responses.append(HttpResponse(status_code=200, text=json.dumps(chat_body(answer))))
    log = CallLog()
    compose_answer(client.with_policy(RecordingPolicy()), "What is it?", retained_packet, log=log)

    (call,) = log.calls
    assert typescript_constant("COMPOSER_ROLE", SOURCE.read_text(encoding="utf-8")) == call.role
