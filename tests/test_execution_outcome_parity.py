"""The page reads the execution record with the server's own words for an attempt.

The server's record says how each attempt ended and whether its cost is known
(``AttemptOutcome`` and ``CallCost`` in ``exulanica/selection/calls.py``), and the page finds the
composer by the role it runs as (``web/packages/app/src/companion-ask-api.ts``). Neither language
reads the other, so each list is written twice and held to one text here. The composers' roles are
read from calls ``compose_answer`` and ``compose_society_answer`` actually make, not from a copy.
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


def test_the_page_finds_each_composer_by_the_role_it_runs_as(client, transport, retained_packet):
    """One composer per answer path, the photographs' and the simulated people's, in that order."""
    from exulanica.selection.society_question import SocietyLineChoice, compose_society_answer

    from test_society_question import _happened_packet

    answer = Answer(clauses=[AnswerClause(text="Nothing.", type="meta")]).model_dump_json()
    transport.responses.append(HttpResponse(status_code=200, text=json.dumps(chat_body(answer))))
    photographs = CallLog()
    sending = client.with_policy(RecordingPolicy())
    compose_answer(sending, "What is it?", retained_packet, log=photographs)

    packet = _happened_packet()
    choice = SocietyLineChoice(lines=[packet.items[0].token]).model_dump_json()
    transport.responses.append(HttpResponse(status_code=200, text=json.dumps(chat_body(choice))))
    society = CallLog()
    compose_society_answer(
        sending, "What happened?", packet, log=society, saved=(), max_tokens=1000
    )

    (photograph_call,) = photographs.calls
    (society_call,) = society.calls
    written = _typescript_list("COMPOSER_ROLES", SOURCE.read_text(encoding="utf-8"))
    assert written == [photograph_call.role, society_call.role]
