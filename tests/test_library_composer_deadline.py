"""The composer of an answer about photographs is waited for one deadline, then the fixed words.

``compose_answer`` in ``exulanica/selection/question.py`` is made once the answer's fixed words are
ready, so a composer that does not answer in time costs the person a bounded wait and never the
answer: the deadline is read from the manifest (:func:`library_composer_wait_seconds`), shared by
the primary, any fallback and the repair, and a call it ends, a timeout or a failed call gives the
fixed words led by a sentence saying so. Every client here has a clock that stands still, so each
wait the transport is handed is exactly what was left of the deadline.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ManifestError, TransportError
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection import question as question_module
from exulanica.selection.answer import Answer, AnswerClause, ClauseType, render_deterministic_answer
from exulanica.selection.calls import CallLog
from exulanica.selection.question import (
    LIBRARY_COMPOSER_ROLE,
    compose_answer,
    library_composer_wait_seconds,
)
from exulanica.selection.society_question import repair_needs_seconds

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_selection_request_goldens import _packet


class _Waits(FakeTransport):
    """A scripted transport that also keeps the wait each request was given."""

    def __init__(self, responses) -> None:
        super().__init__(responses)
        self.waits: list[float] = []

    def post_json(self, url, *, headers, payload, timeout) -> HttpResponse:
        self.waits.append(timeout)
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


def _client(*responses, manifest=None) -> tuple[ModelClient, _Waits]:
    transport = _Waits(list(responses))
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        clock=lambda: 0.0,
        **({} if manifest is None else {"manifest": manifest}),
    ).with_policy(RecordingPolicy())
    return client, transport


def _answer(answer: Answer) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(answer.model_dump_json())))


ACCEPTED = Answer(
    clauses=[
        AnswerClause(
            text="This photograph was taken there.",
            type=ClauseType.HISTORICAL,
            citations=["A6EF9VWNT6"],
        )
    ]
)
INVENTED = Answer(
    clauses=[
        AnswerClause(
            text="This photograph was taken there.",
            type=ClauseType.HISTORICAL,
            citations=["ZZZZZZZZZZ"],
        )
    ]
)


def _still() -> float:
    """A clock that stands still, as the client's does."""
    return 0.0


def _times(*readings):
    """A clock that reads each of ``readings`` in turn, then the last one for ever."""
    queue = list(readings)
    return lambda: queue.pop(0) if len(queue) > 1 else queue[0]


def _deadline_sentence(manifest) -> str:
    seconds = -(-library_composer_wait_seconds(manifest) // 1)
    return (
        f"The model that writes this answer did not answer within {seconds:g} seconds, so here is "
        "what was found."
    )


@pytest.mark.parametrize(
    ("ended", "outcome"),
    [
        (
            TransportError("no whole response", timed_out=True, reached_provider=None),
            "deadline_ended",
        ),
        (TransportError("HTTP 503 from the provider", reached_provider=True), "failed"),
    ],
    ids=["deadline_ended", "failed"],
)
def test_a_composer_that_does_not_answer_gives_the_fixed_words_and_says_so(ended, outcome):
    """Before the deadline, a timeout went out of ``answer_question`` and failed a question whose
    answer was in hand: the browser was told the question failed. A wait the deadline cut short
    is recorded as ended by it, since the deadline is shorter than the role's timeout."""
    client, transport = _client(ended)
    log = CallLog()
    answer, deterministic, rejections = compose_answer(
        client.with_attempts(log.attempt), "Where was this?", _packet(), log=log, clock=_still
    )

    assert deterministic
    assert rejections == ("composer_unanswered: TransportError",)
    sentence = {
        "deadline_ended": _deadline_sentence(client.manifest),
        "failed": "The model that writes this answer did not answer, so here is what was found.",
    }[outcome]
    assert [answer.clauses[0].text, answer.clauses[0].type] == [sentence, ClauseType.META]
    assert answer.clauses[1:] == render_deterministic_answer(_packet()).clauses
    assert len(transport.requests) == 1
    assert [call.outcome for call in log.calls] == [outcome]


def test_a_timeout_at_the_role_s_own_timeout_is_said_as_not_in_time():
    """When the recorded 99th percentile is past the role's timeout, the deadline is the timeout,
    and a wait it ends is the role's own timeout."""
    manifest = load_manifest()
    timeout = manifest[LIBRARY_COMPOSER_ROLE].timeout_seconds
    client, _ = _client(
        TransportError("no whole response", timed_out=True, reached_provider=None),
        manifest=_with_basis(manifest, p99_ms=int(timeout * 1000) + 5000),
    )
    answer, deterministic, _ = compose_answer(client, "Where was this?", _packet(), clock=_still)
    assert deterministic
    assert answer.clauses[0].text == (
        "The model that writes this answer did not answer in time, so here is what was found."
    )


def test_the_composer_waits_the_deadline_its_manifest_records_not_its_role_s_timeout():
    client, transport = _client(_answer(ACCEPTED))
    answer, deterministic, rejections = compose_answer(
        client, "Where was this?", _packet(), clock=_still
    )

    wait = library_composer_wait_seconds(client.manifest)
    assert transport.waits == [wait]
    assert wait < client.manifest[LIBRARY_COMPOSER_ROLE].timeout_seconds
    assert not deterministic and not rejections
    assert answer.clauses[0].citations == ["A6EF9VWNT6"]


def test_a_refused_answer_is_asked_again_within_what_is_left_of_the_deadline():
    client, transport = _client(_answer(INVENTED), _answer(ACCEPTED))
    wait = library_composer_wait_seconds(client.manifest)
    spent = wait - repair_needs_seconds(client.manifest, LIBRARY_COMPOSER_ROLE) - 0.5
    answer, deterministic, rejections = compose_answer(
        client, "Where was this?", _packet(), clock=_times(0.0, 0.0, spent)
    )

    assert transport.waits == [wait, wait - spent]
    assert not deterministic
    assert rejections and "ZZZZZZZZZZ" in rejections[0]
    assert answer.clauses[0].citations == ["A6EF9VWNT6"]


def test_a_refused_answer_gives_the_fixed_words_at_once_when_too_little_is_left():
    client, transport = _client(_answer(INVENTED), _answer(ACCEPTED))
    wait = library_composer_wait_seconds(client.manifest)
    spent = wait - repair_needs_seconds(client.manifest, LIBRARY_COMPOSER_ROLE) + 0.5
    answer, deterministic, rejections = compose_answer(
        client, "Where was this?", _packet(), clock=_times(0.0, 0.0, spent)
    )

    assert len(transport.requests) == 1
    assert deterministic and rejections
    # The fixed words with no note: an answer came in time and was refused.
    assert answer == render_deterministic_answer(_packet())


def _with_basis(manifest, **changes):
    roles = dict(manifest.roles)
    role = roles[LIBRARY_COMPOSER_ROLE]
    basis = {k: v for k, v in {**role.timeout_basis, **changes}.items() if v is not None}
    roles[LIBRARY_COMPOSER_ROLE] = dataclasses.replace(role, timeout_basis=basis)
    return dataclasses.replace(manifest, roles=roles)


def test_the_deadline_is_the_99th_percentile_the_role_s_timeout_rests_on():
    manifest = load_manifest()
    p99 = manifest[LIBRARY_COMPOSER_ROLE].timeout_basis["p99_ms"]
    assert library_composer_wait_seconds(manifest) == p99 / 1000
    moved = _with_basis(manifest, p99_ms=p99 - 4000)
    assert library_composer_wait_seconds(moved) == (p99 - 4000) / 1000
    client, transport = _client(_answer(ACCEPTED), manifest=moved)
    compose_answer(client, "Where was this?", _packet(), clock=_still)
    assert transport.waits == [(p99 - 4000) / 1000]


def test_the_deadline_is_never_longer_than_the_role_s_timeout():
    manifest = load_manifest()
    timeout = manifest[LIBRARY_COMPOSER_ROLE].timeout_seconds
    longer = _with_basis(manifest, p99_ms=int(timeout * 1000) + 5000)
    assert library_composer_wait_seconds(longer) == timeout


def test_a_basis_with_no_99th_percentile_is_refused_by_name():
    unmeasured = _with_basis(load_manifest(), p99_ms=None)
    with pytest.raises(ManifestError, match="records no p99_ms"):
        library_composer_wait_seconds(unmeasured)


def test_no_note_carries_a_digit_other_than_the_deadline_or_a_bracketed_label():
    """The page draws a bracketed label as a person or a place, and a note's only figure is the
    deadline it was given."""
    for text in question_module._COMPOSER_UNANSWERED.values():
        assert not re.search(r"\[[^\]]*\]", text)
        assert not re.search(r"\d", text.replace("{seconds}", ""))
