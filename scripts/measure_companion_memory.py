"""Measure the Companion composer against its own declared fallback, at two token ceilings.

    EXULANICA_BUDGET_USD=0.50 EXULANICA_BUDGET_MAX_CALLS=120 \
      uv run python scripts/measure_companion_memory.py \
        --cap-usd 0.50 --max-calls 120 --out /tmp/companion-memory/measurement.json

    uv run python scripts/measure_companion_memory.py \
        --cap-usd 0.50 --max-calls 120 --skip-live --out /tmp/companion-memory/scripted.json

THIS SCRIPT SPENDS MONEY unless `--skip-live` is given. It refuses to start a live run unless the
operator's ceiling is stated TWICE, once in the environment where ``BudgetGuard`` reads it and
once on the command line where a person typed it, and the two agree exactly. The same is required
of the call ceiling. A single statement would let an accidental default look like an
authorisation, and the guard's own default ceiling is five dollars, ten times what this
measurement needs. The refusal is a function rather than an inline block so that `--skip-live`
can call it and record that it still refuses; a guard nobody exercises is a guard nobody has.

The sibling this grew out of is `scripts/measure_companion_questions.py`, which measured the
whole question path once. This one measures one call inside it, thirty-six to sixty times.

WHAT IT MEASURES, AND WHY EACH AXIS IS THERE

*   **Two models on the same packet.** `nvidia/Nemotron-3_5-Lightning` holds
    `Role.REASONING_CHEAP` and `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` is its declared fallback.
    `docs/evaluation/2026-09-09-companion-question.json` recorded the fallback answering two of
    the same packets in a quarter of the time, and then running away on a third. That is the open
    question and this is the axis that answers it.
*   **Three passes.** The record's own limitation list says composer latency is unstable: "the
    same two questions measured between 17.7 s and 54.5 s on packets of the same size". One pass
    per cell would measure that instability and report it as a difference between cells.
*   **Two ceilings**, argued below.
*   **The five recorded questions**, with the Selections they actually produced, replayed from
    the artifacts rather than re-planned. Re-planning would vary two things and would spend a
    role this run is not measuring.

WHY THE SECOND CEILING IS 16384, AND NOT A NUMBER SOMEBODY LIKED

`COMPOSER_MAX_TOKENS` is 32768 and its own comment says the ceiling "is set well above the
largest observed rather than at it", which is the right principle and says nothing about the
multiple. The record has four artifact-backed completion counts for the reasoning core on
10-item packets, and the answer is a rounding error inside every one of them:

    when       6490 completion, 6428 reasoning     62 tokens of answer
    how_many   5903 completion, 5850 reasoning      53 tokens of answer
    who        2301 completion, 2248 reasoning      53 tokens of answer
    unrelated  1446 completion, 1402 reasoning      44 tokens of answer

An earlier pass in the same record reads 4354 of 4416 and 5673 of 5731, both inside that range.
So the ceiling is not sizing an answer, it is sizing inline reasoning that cannot be switched
off, and the largest reasoning spend ever archived on this call is 6428 tokens.

Against that stands one observation in `COMPOSER_MAX_TOKENS`'s own comment, with no artifact
behind it: the composer "conformed at 16384 on a 24-item packet and TRUNCATED at the same ceiling
on an 8-item one". That is the strongest reason not to go lower, and it is exactly why 16384 is
the number worth measuring. It is the largest ceiling at which this call has ever been observed
to fail. Halving the constant is the smallest step that can answer the question the constant
cannot answer for itself, and the run resolves either way:

*   the truncation reproduces, and a note with no artifact behind it becomes evidence, and the
    second half of the ceiling is doing work;
*   or twenty-four Lightning calls at 16384 all conform, and the note is one unarchived
    observation, and the second half of the ceiling is buying only a longer runaway.

A runaway is the cost that is not hypothetical. The record has the Nano spending all 32768
completion tokens on the `who` packet and producing no answer: at the manifest's $0.24 per
million output tokens that is 7864 micro-dollars and the wall clock of generating 32768 tokens,
for a deterministic fallback the request would have reached from 16384 just as surely and in half
the time. A ceiling is not a spend, as the constant says. It is, however, exactly what a runaway
spends.

Two numbers deliberately NOT chosen. 8192 clears the largest archived completion count by 26%
and is below a ceiling already measured to truncate on this very prompt, so a run there would
measure how often the deterministic floor is reached rather than whether the ceiling is needed;
that is a different experiment and a worse one to run first. And the arithmetic 6490-plus-headroom
is a ceiling set at the largest observed SO FAR, on a spend the record says is not stable.

**This script does not change `COMPOSER_MAX_TOKENS`.** It measures at two values and leaves the
constant where it is, the way the predecessor measured a role change and did not make one.

HOW THE CEILING IS OVERRIDDEN, GIVEN THAT question.py IS READ ONLY

`compose_answer` reads the module-level `COMPOSER_MAX_TOKENS` at call time, so this script
rebinds that one name on the imported module object inside a context manager and restores it in a
`finally`. No source file is edited, nothing on disk moves, and the function under measurement is
byte-for-byte the function the product runs, which is the same argument `tests/model_fakes.py`
makes for a scripted transport: substitute the seam, never the code. It is the sibling of the way
the predecessor pins a role, which replaces one binding on an in-memory `dataclasses.replace`
copy of the manifest and leaves `models.manifest.json` and `pipeline_version` alone. Both pins are
here, and both are checked rather than asserted: `--skip-live` reads the `max_tokens` the fake
transport actually received and reports it, because "the override worked" is a claim about a
request that was sent, not about a variable that was set.

**Cost is read off the budget guard's ledger rather than off the call log**, because the call
this experiment most needs to price is the one the call log cannot see. A truncated reply raises
inside `ModelClient.structured` before any result reaches `compose_answer`, so a runaway appears
in `CallLog` as nothing at all and a cost summed from there reports it as free; the ledger is
written before that raise. The predecessor's record lists the gap as its first known limitation,
and a ledger slice taken around each call is what closes it. Both figures are in the record.

The response cache would defeat this measurement, so no client here is given one. `cache_key`
digests the whole payload, `max_tokens` included, so the two ceilings could not collide, but the
three passes within one cell would: pass two and pass three would be served pass one's body and
report a latency of zero. `NullResponseCache` is the client's default and it is left alone.

TIME TO FIRST TOKEN, AND THE THREE NUMBERS THAT ARE NOT ONE NUMBER

`ModelClient` cannot stream. `Transport` is a `post_json`/`get_json` protocol returning a fully
materialised `HttpResponse`, and teaching it to stream would mean editing `exulanica/models/`,
which this task may not do. The endpoint does stream: `stream: true` returns `text/event-stream`
and `stream_options: {"include_usage": true}` puts the usage object, `reasoning_tokens` included,
in the final chunk. So the streamed measurement is this script's OWN direct call, made beside the
`ModelClient` path and never confused with it. It is a SECOND request with its own tokens and its
own bill, and it is counted as one.

Reasoning arrives in a separate `reasoning_content` delta and the answer arrives in `content`,
reasoning first, so three different instants get three different names here:

    first_sse_chunk_ms          the connection produced anything at all
    first_reasoning_delta_ms    the model started thinking out loud
    first_answer_content_ms     the first character of the ANSWER

**Only the third one answers "do the first words appear early".** Already probed live against
this endpoint on a small json_schema request to Lightning: first chunk at 752 ms, first reasoning
delta at 752 ms, first answer content at 2096 ms, done at 2441 ms, 419 of 522 completion tokens
being reasoning. Reporting that as a 750 ms first token would be a claim about an answer whose
first word arrived 1.3 seconds later, and on a 10-item packet where the record has the same model
spending 6428 reasoning tokens, the same conflation would report 750 ms for an answer that starts
tens of seconds in. The parser that separates the three is a pure function over lines, so
`--skip-live` drives it with the probed transcript above and a fake clock, and no socket.

WHAT --skip-live ACTUALLY EXERCISES

Everything that spends nothing, driven by `tests.model_fakes.FakeTransport`: the full matrix
through the real `compose_answer`, the real `ModelClient`, the real chain, the real budget guard
and the real answer validator, with scripted bodies in place of the network. It also runs the
things a live run would never get to check, because they are the things a live run assumes: that
the double-statement refusal still refuses, that the ceiling reached the wire and was restored
afterwards, that the manifest pin did not touch the process-wide manifest, that a token count
absent from a provider's usage object arrives as null rather than zero, and that the record
carries no float anywhere.

**Every number in a `--skip-live` record is transcribed or invented, never measured**, and the
record says so in its own top-level field. The scripted usage counts come from the recorded run
and each one names where it came from; where the record covers no such pair, the fixture says the
number is invented and covers nothing.

Nothing here writes. The live half opens the retained workspace through the read-only executor
role, reads the workspace id from the reference runtime state and never the bearer token, since
this script makes no request to the API at all. The model credential is read only for the streamed
call, and is never printed, never written to the output and never put in a URL.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from exulanica.db import Database  # noqa: E402
from exulanica.evidence import BlobId, EvidenceAddress  # noqa: E402
from exulanica.models.budget import BudgetGuard  # noqa: E402
from exulanica.models.client import ModelClient  # noqa: E402
from exulanica.models.credentials import api_key_from_env  # noqa: E402
from exulanica.models.manifest import Manifest, Role, load_manifest  # noqa: E402
from exulanica.models.schema import response_format_for  # noqa: E402
from exulanica.models.usage import CallUsage  # noqa: E402
from exulanica.selection import (  # noqa: E402
    SelectionPlan,
    Session,
    build_packet,
    execute,
    validate,
)
from exulanica.selection import question as composer  # noqa: E402
from exulanica.selection.answer import Answer  # noqa: E402
from exulanica.selection.packet import (  # noqa: E402
    EvidenceItem,
    EvidencePacket,
    ValueReference,
)
from exulanica.selection.question import PROMPT_VERSION, CallLog, compose_answer  # noqa: E402
from tests.model_fakes import FakeTransport, chat_body  # noqa: E402
from exulanica.models.transport import HttpResponse  # noqa: E402

#: The one database this experiment is permitted to read, stated rather than configurable, and
#: opened through the read-only executor role exactly as the API's own read dependency does.
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
READONLY = DATABASE + "?options=-crole%3Dexulanica_ro"
STATE = ROOT / ".exulanica/reference-baseline/runtime"

#: A micro-dollar. Costs are integers of this unit because an evaluation record in this
#: repository carries no floats: a float rewrites its own last digits on a JSON round trip.
MICRO = Decimal("0.000001")

#: The composer's declared ceiling, read off the module at import so the override can prove it
#: put the constant back. Read, never written to source.
DECLARED_CEILING = composer.COMPOSER_MAX_TOKENS

#: The second value. The whole argument for it is in the module docstring; the one-line form is
#: that it is the largest ceiling at which this call has ever been observed to fail.
LOWER_CEILING = 16384

CEILINGS: tuple[int, ...] = (DECLARED_CEILING, LOWER_CEILING)

#: Three, because the record says composer latency on packets of the same size varied between
#: 17.7 s and 54.5 s. One pass per cell would report that instability as a difference between
#: cells.
PASSES = 3

#: The role holder and its own declared fallback. A measurement script names identifiers where
#: the package may not: a role cannot express "the fallback specifically", and the fallback is
#: the thing under measurement. The manifest is still the source of every price and every floor.
LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
COMPOSERS: tuple[str, ...] = (LIGHTNING, NANO)

#: The five, in the order they were asked, with the reason each is in the set. Copied verbatim
#: from `scripts/measure_companion_questions.py` because a comparison across two records that
#: quietly reworded a question would be a comparison of two question sets.
QUESTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "when",
        "When were these photographs taken?",
        "Answerable. The captures carry captured_at, and the packet mints date value references "
        "for it, so an answer can name a date without inventing one.",
    ),
    (
        "how_many",
        "How many photographs are there?",
        "Answerable. capture_count is a value reference computed from the query result, which is "
        "the only way a number may appear in an answer at all.",
    ),
    (
        "what_place",
        "What is this place?",
        "MUST ABSTAIN or decline to name it. The workspace holds no place entity and no caption, "
        "so there is nothing an answer could cite for a name.",
    ),
    (
        "who",
        "Who is in these photographs?",
        "MUST ABSTAIN. Zero entities, so the planner catalogue is empty and nobody has been "
        "named. An answer that named somebody would be the failure the whole path exists against.",
    ),
    (
        "unrelated",
        "What is the current exchange rate for the pound?",
        "MUST ABSTAIN. Nothing in a photograph library answers it, and the honest reply is that "
        "there is no evidence rather than a guess from general knowledge.",
    ),
)

#: The Selections the planner actually produced on 2026-09-09, read out of the archived response
#: bodies under `docs/evaluation/artifacts/2026-09-09-companion-question/ask-*.response.json`.
#:
#: **Replayed rather than re-planned, and that is the point of the axis.** This run varies the
#: composer and its ceiling. Asking the planner again would vary the Selection too, would spend
#: `structured_extraction` on a role nothing here measures, and would make a packet difference
#: indistinguishable from a composer difference. The planner half of this path already has its
#: record; this is the other half.
RECORDED_PLANS: Mapping[str, dict[str, Any]] = {
    "when": {
        "intent": "captures", "entities": None, "time": [], "place": None, "capture": None,
        "epistemic": "confirmed", "semantic_query": None, "limit": 10,
    },
    "how_many": {
        "intent": "captures", "entities": None, "time": [], "place": None, "capture": None,
        "epistemic": "confirmed", "semantic_query": None, "limit": 10,
    },
    "what_place": {
        "intent": "entities", "entities": None, "time": [], "place": None, "capture": None,
        "epistemic": "confirmed", "semantic_query": "What is this place?", "limit": 10,
    },
    "who": {
        "intent": "entities", "entities": None, "time": [], "place": None, "capture": None,
        "epistemic": "confirmed", "semantic_query": None, "limit": 10,
    },
    "unrelated": {
        "intent": "entities", "entities": None, "time": [], "place": None, "capture": None,
        "epistemic": "confirmed", "semantic_query": None, "limit": 10,
    },
}


# -- money ---------------------------------------------------------------------------------------


def micro_usd(value: Decimal) -> int:
    """A cost as whole micro-dollars, rounded up. Never a float, and never rounded down."""
    return int((value / MICRO).to_integral_value(rounding="ROUND_CEILING"))


def cost_of(manifest: Manifest, model_id: str, prompt: int | None, completion: int | None) -> int:
    """What one call cost, from the reported usage and the manifest's published prices.

    A call whose usage object reported neither count costs nothing HERE, which is a statement
    about what was reported and not a claim that the endpoint billed nothing.
    """
    if prompt is None and completion is None:
        return 0
    spec = manifest.spec(model_id)
    return micro_usd(spec.cost_usd(prompt_tokens=prompt or 0, completion_tokens=completion or 0))


# -- the refusal ----------------------------------------------------------------------------------


def refuse_unless_stated_twice(
    *, cap_usd: str, max_calls: int, environ: Mapping[str, str]
) -> None:
    """Refuse a live run whose ceiling was stated once. Raises ``SystemExit`` or returns None.

    Copied in substance from `scripts/measure_companion_questions.py`, which states the argument
    plainly: the cap is stated twice on purpose, because a default that nobody typed is not an
    authorisation, and `BudgetGuard`'s own default is five dollars.

    A function rather than an inline block, for one reason worth the indirection: `--skip-live`
    is the mode that gets run, and a refusal that only the paid mode reaches is a refusal nobody
    has exercised since the day it was written. It is called with three environments below, and
    what it did is in the record.

    Unparseable values are refused rather than raised through. `EXULANICA_BUDGET_USD=fifty cents`
    is the same operator mistake as a mismatch and deserves the same sentence, not a traceback
    from inside `Decimal`.
    """
    stated_cap = environ.get("EXULANICA_BUDGET_USD", "")
    stated_calls = environ.get("EXULANICA_BUDGET_MAX_CALLS", "")
    try:
        environment_cap = Decimal(stated_cap or "-1")
        command_line_cap = Decimal(cap_usd)
    except InvalidOperation as exc:
        raise SystemExit(
            f"EXULANICA_BUDGET_USD={stated_cap!r} and --cap-usd {cap_usd!r} do not both parse as "
            f"decimal amounts ({exc}). The cap is stated twice on purpose and neither statement "
            "may be a guess."
        ) from exc
    if environment_cap != command_line_cap:
        raise SystemExit(
            f"EXULANICA_BUDGET_USD={stated_cap!r} does not match --cap-usd {cap_usd!r}. The cap "
            "is stated twice on purpose: a default that nobody typed is not an authorisation, "
            "and the guard's own default ceiling is five dollars."
        )
    try:
        environment_calls = int(stated_calls or -1)
    except ValueError as exc:
        raise SystemExit(
            f"EXULANICA_BUDGET_MAX_CALLS={stated_calls!r} is not a whole number of calls."
        ) from exc
    if environment_calls != max_calls:
        raise SystemExit(
            f"EXULANICA_BUDGET_MAX_CALLS={stated_calls!r} does not match --max-calls "
            f"{max_calls}. This run makes up to {len(COMPOSERS) * len(CEILINGS) * PASSES * 4} "
            "composer calls before repairs, so the call ceiling is the one that catches a loop."
        )
    if not environ.get("NEBIUS_API_KEY"):
        raise SystemExit("NEBIUS_API_KEY is not set, so there is nothing to measure.")


# -- the two in-memory pins -----------------------------------------------------------------------


@contextlib.contextmanager
def composer_ceiling(value: int) -> Iterator[int]:
    """Rebind ``COMPOSER_MAX_TOKENS`` on the imported module for the duration of one call.

    `exulanica/selection/question.py` is read-only to this task and is not edited. `compose_answer`
    resolves `COMPOSER_MAX_TOKENS` out of its module globals at call time, so rebinding the name
    on the module object is enough, and restoring it in a `finally` is what keeps a measurement
    from leaking into the next one.

    The declared value is checked on the way in. If somebody has edited the constant, this run's
    "32768 versus 16384" would silently become something else, and a record whose axis is not
    what it says it is is worse than no record.
    """
    if composer.COMPOSER_MAX_TOKENS != DECLARED_CEILING:
        raise SystemExit(
            f"COMPOSER_MAX_TOKENS is {composer.COMPOSER_MAX_TOKENS} and this run was built "
            f"against {DECLARED_CEILING}. Rebuild the ceilings from the constant rather than "
            "measuring an axis whose endpoint moved."
        )
    composer.COMPOSER_MAX_TOKENS = value
    try:
        yield value
    finally:
        composer.COMPOSER_MAX_TOKENS = DECLARED_CEILING


def pinned_manifest(manifest: Manifest, model_id: str) -> Manifest:
    """The same manifest with the composer role pointed at one named model, in memory only.

    `exulanica/models/models.manifest.json` is not edited and `pipeline_version` does not move.
    The fallback is dropped as well as the primary replaced: a chain that could fail over would
    let a withdrawal turn "the Nano was slower" into a sentence about the wrong model, and
    `ChatResult.served_model_id` is recorded here precisely so that cannot pass unnoticed.
    """
    binding = manifest[Role.REASONING_CHEAP]
    pinned = dataclasses.replace(binding, primary=manifest.spec(model_id), fallback=None)
    roles = dict(manifest.roles)
    roles[Role.REASONING_CHEAP] = pinned
    return dataclasses.replace(manifest, roles=roles)


# -- the streamed half: three instants, not one ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreamTiming:
    """What one streamed call did, in whole milliseconds and reported token counts.

    Three arrival times because they are three different events, and the third is the only one
    that answers "do the first words appear early". Each is ``None`` when the stream never
    produced that kind of delta at all, which is a fact about the response rather than a zero.
    """

    first_sse_chunk_ms: int | None
    first_reasoning_delta_ms: int | None
    first_answer_content_ms: int | None
    total_ms: int
    chunks: int
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    reasoning_chars: int
    answer_chars: int
    answer_parses_as_json: bool

    def as_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _reported(usage: Mapping[str, Any], key: str) -> int | None:
    """A count the provider actually reported, or ``None``. Never a substituted zero.

    The same rule `exulanica.selection.question.ModelCall` states: a zero is a measurement and an
    absence is not. The Nano's answers in the recorded run carry no `reasoning_tokens` at all,
    and reporting that as 0 would assert it did no inline reasoning.
    """
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def read_stream(
    lines: Iterable[str], *, now: Callable[[], float], started: float | None = None
) -> StreamTiming:
    """Consume one `text/event-stream` body and time the three arrivals separately.

    A pure function over lines and a clock, which is what makes it checkable without a socket:
    `--skip-live` feeds it the transcript of the live probe already taken against this endpoint
    and a clock that advances to each line's recorded arrival.

    `reasoning_content` and `content` are read as separate delta fields because that is how this
    endpoint sends them, reasoning first. A parser that treated any delta as the answer would
    report the reasoning's start time under the answer's name.

    **`started` is the instant the REQUEST left, and the caller passes it.** Defaulting it to
    entry here would silently move the origin: `httpx.Client.stream` sends the request and reads
    the response headers before it yields, so a clock started on the first line of this function
    would report time to first chunk measured from after the endpoint had already answered. The
    number would be small, plausible, and about nothing.
    """
    started = now() if started is None else started
    first_chunk: float | None = None
    first_reasoning: float | None = None
    first_answer: float | None = None
    chunks = 0
    finish_reason: str | None = None
    usage: Mapping[str, Any] = {}
    reasoning_chars = 0
    answer = []
    for raw in lines:
        line = raw.strip()
        if not line or not line.startswith("data:"):
            continue
        body = line[len("data:") :].strip()
        if body == "[DONE]":
            break
        try:
            chunk = json.loads(body)
        except json.JSONDecodeError:
            # A malformed chunk is recorded by its absence from the counts rather than raised.
            # The measurement is about arrival times, and one unparseable frame does not make
            # the ones around it untrue.
            continue
        if not isinstance(chunk, Mapping):
            continue
        chunks += 1
        at = now()
        if first_chunk is None:
            first_chunk = at
        reported = chunk.get("usage")
        if isinstance(reported, Mapping):
            usage = reported
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        finish_reason = choice.get("finish_reason") or finish_reason
        delta = choice.get("delta") or {}
        thought = delta.get("reasoning_content")
        if isinstance(thought, str) and thought:
            if first_reasoning is None:
                first_reasoning = at
            reasoning_chars += len(thought)
        text = delta.get("content")
        if isinstance(text, str) and text:
            if first_answer is None:
                first_answer = at
            answer.append(text)
    finished = now()
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, Mapping) else {}
    written = "".join(answer)
    try:
        json.loads(written)
        parses = True
    except (json.JSONDecodeError, ValueError):
        parses = False
    return StreamTiming(
        first_sse_chunk_ms=None if first_chunk is None else round((first_chunk - started) * 1000),
        first_reasoning_delta_ms=(
            None if first_reasoning is None else round((first_reasoning - started) * 1000)
        ),
        first_answer_content_ms=(
            None if first_answer is None else round((first_answer - started) * 1000)
        ),
        total_ms=round((finished - started) * 1000),
        chunks=chunks,
        finish_reason=finish_reason,
        prompt_tokens=_reported(usage, "prompt_tokens"),
        completion_tokens=_reported(usage, "completion_tokens"),
        reasoning_tokens=_reported(details, "reasoning_tokens"),
        reasoning_chars=reasoning_chars,
        answer_chars=len(written),
        answer_parses_as_json=parses and bool(written),
    )


def composer_messages(question: str, packet: EvidencePacket) -> list[dict[str, Any]]:
    """The exact messages `compose_answer` builds, reached through its own private names.

    Two private names on purpose. A paraphrase of the composer prompt would measure a different
    request, and time to first token on a different request is not the number anybody asked for.
    Reading them is not editing them, and `exulanica/selection/question.py` is unchanged.
    """
    return [
        {"role": "system", "content": composer._COMPOSER_SYSTEM},
        {"role": "user", "content": f"{composer._render_packet(packet)}\n\nQuestion: {question}"},
    ]


def stream_probe(
    *,
    manifest: Manifest,
    guard: BudgetGuard,
    api_key: str,
    model_id: str,
    question: str,
    packet: EvidencePacket,
    ceiling: int,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """One streamed call, made by this script and not by `ModelClient`, which cannot stream.

    It is a SECOND request. Nothing about it is shared with the `ModelClient` measurements above
    and its tokens are its own, which is why it is reserved and recorded against the same budget
    guard rather than treated as free observation.
    """
    messages = composer_messages(question, packet)
    spec = manifest.spec(model_id)
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": ceiling,
        "temperature": 0.0,
        "response_format": response_format_for(Answer),
        "stream": True,
        # Without this the final chunk carries no usage and every token count below would be
        # null, which would be honest and useless.
        "stream_options": {"include_usage": True},
    }
    guard.reserve(
        spec,
        role=Role.REASONING_CHEAP,
        prompt_chars=sum(len(str(m)) for m in messages),
        max_tokens=ceiling,
    )
    url = f"{manifest.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    with httpx.Client(timeout=timeout) as client, client.stream(
        "POST", url, headers=headers, json=payload
    ) as response:
        if response.status_code != 200:
            response.read()
            return {
                "model_id": model_id,
                "composer_max_tokens": ceiling,
                "question_key": None,
                "http_status": response.status_code,
                "refused": response.text[:400],
            }
        timing = read_stream(response.iter_lines(), now=time.monotonic)
    usage = CallUsage.from_response(
        role=Role.REASONING_CHEAP,
        spec=spec,
        usage={
            "prompt_tokens": timing.prompt_tokens or 0,
            "completion_tokens": timing.completion_tokens or 0,
            "completion_tokens_details": {"reasoning_tokens": timing.reasoning_tokens or 0},
        },
        latency_s=timing.total_ms / 1000,
    )
    guard.record(usage)
    return {
        "model_id": model_id,
        "composer_max_tokens": ceiling,
        "http_status": 200,
        "scripted": False,
        **timing.as_json(),
        "cost_micro_usd": cost_of(
            manifest, model_id, timing.prompt_tokens, timing.completion_tokens
        ),
    }


#: The live probe already taken against this endpoint, as (arrival in ms, SSE line). Kept so the
#: parser can be exercised on the real shape rather than on an invented one: a small json_schema
#: request to Lightning, first chunk at 752 ms, first reasoning delta at 752 ms, first ANSWER
#: content at 2096 ms, total 2441 ms, 419 of 522 completion tokens reasoning.
PROBED_TRANSCRIPT: tuple[tuple[int, str], ...] = (
    (752, 'data: {"choices":[{"index":0,"delta":{"reasoning_content":"The user wants "}}]}'),
    (1103, 'data: {"choices":[{"index":0,"delta":{"reasoning_content":"a cited clause. "}}]}'),
    (1740, 'data: {"choices":[{"index":0,"delta":{"reasoning_content":"Only one date."}}]}'),
    (2096, 'data: {"choices":[{"index":0,"delta":{"content":"{\\"clauses\\": ["}}]}'),
    (2298, 'data: {"choices":[{"index":0,"delta":{"content":"{\\"text\\": \\"ok\\"}]}"}}]}'),
    (2441, 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":'
           '{"prompt_tokens":311,"completion_tokens":522,'
           '"completion_tokens_details":{"reasoning_tokens":419}}}'),
    (2441, "data: [DONE]"),
)


class ScriptedClock:
    """A clock that is advanced by whoever is feeding the lines. Monotonic by construction."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


def scripted_lines(
    transcript: tuple[tuple[int, str], ...], clock: ScriptedClock
) -> Iterator[str]:
    """Yield each line with the clock already advanced to the instant it arrived."""
    for arrived_ms, line in transcript:
        clock.seconds = arrived_ms / 1000
        yield line


# -- the scripted packets, for the mode that spends nothing ----------------------------------------

#: Ten items, one date, 51 matched: the shape of the packets the recorded run composed, read off
#: `docs/evaluation/artifacts/2026-09-09-companion-question/packet-probe.response.json`. The
#: tokens are fixed rather than random because a fixture is not evidence and a deterministic
#: fixture makes two `--skip-live` records diffable; `build_packet` mints its own per request and
#: is what the live half uses.
SCRIPTED_TOKENS: tuple[str, ...] = (
    "SJ5NGWJUBP", "62D54FVDS8", "DTEWDSZFK2", "45GGCHY49V", "HNPQ4RTU7W",
    "K2MXY9BCDF", "Q7RSTV3W4X", "Z8B9CDFGHJ", "M4NPQRSTUV", "W5XYZ23456",
)


def scripted_packet(key: str) -> EvidencePacket:
    """A packet shaped like the recorded one. Empty for the question whose Selection matched none.

    `what_place` matched nothing on 2026-09-09, its packet was empty, and the composer was
    therefore never called on it. The fixture reproduces that rather than smoothing it away: the
    matrix has to have a cell where the honest outcome is "no model was asked", or `--skip-live`
    would not exercise the branch that reports one.
    """
    if key == "what_place":
        return EvidencePacket(items=(), values=(), total_matched=0, citable=True)
    items = []
    for ordinal, token in enumerate(SCRIPTED_TOKENS):
        blob = BlobId.of_bytes(f"scripted-{key}-{ordinal}".encode())
        items.append(
            EvidenceItem(
                token=token,
                span_id=uuid.UUID(int=0x5EED0000 + ordinal),
                assertion_id=None,
                address=EvidenceAddress.photograph(blob),
                capture_id=uuid.UUID(int=0xCA9700000 + ordinal),
                captured_at=f"2026-02-01T09:16:{49 + ordinal:02d}+00:00",
                text=None,
                trust="capture_supported",
            )
        )
    values = (
        ValueReference(
            key="capture_count", text="51", label="how many captures the Selection matched"
        ),
        ValueReference(key="shown_count", text="10", label="how many of them are in this packet"),
        ValueReference(
            key="date_0", text="2026-02-01", label="a capture date inside the Selection"
        ),
    )
    return EvidencePacket(items=tuple(items), values=values, total_matched=51, citable=True)


#: The answers the recorded run got, verbatim, so the fixture's clauses are the ones the
#: validator actually passed rather than ones written to pass it.
SCRIPTED_ANSWERS: Mapping[str, dict[str, Any]] = {
    "when": {
        "text": "These photographs were taken on 2026-02-01",
        "type": "historical",
        "value_refs": ["date_0"],
        "cites": True,
    },
    "how_many": {
        "text": "Your photographs number 51.",
        "type": "historical",
        "value_refs": ["capture_count"],
        "cites": True,
    },
    "who": {
        "text": "Your photographs contain no describable information about people, so the "
                "evidence does not indicate who is in them.",
        "type": "meta",
        "value_refs": [],
        "cites": False,
    },
    "unrelated": {
        "text": "Your photographs do not contain any information about currency exchange rates.",
        "type": "meta",
        "value_refs": [],
        "cites": False,
    },
}


@dataclass(frozen=True, slots=True)
class ScriptedUsage:
    """One scripted response's token counts, and where each number came from.

    ``source`` is not decoration. A `--skip-live` record has to be unmistakable for a
    measurement, and the cheapest way to make it unmistakable is for every number in it to say,
    in the record itself, that it was transcribed from an earlier run or invented for the fixture.
    """

    prompt_tokens: int
    completion_tokens: int | None
    reasoning_tokens: int | None
    source: str
    runaway: bool = False


TRANSCRIBED = "transcribed from docs/evaluation/2026-09-09-companion-question.json"
INVENTED = "invented for this fixture; no recorded number covers this model and this question"

SCRIPTED_USAGE: Mapping[tuple[str, str], ScriptedUsage] = {
    (LIGHTNING, "when"): ScriptedUsage(1318, 6490, 6428, TRANSCRIBED),
    (LIGHTNING, "how_many"): ScriptedUsage(1324, 5903, 5850, TRANSCRIBED),
    (LIGHTNING, "who"): ScriptedUsage(1329, 2301, 2248, TRANSCRIBED),
    (LIGHTNING, "unrelated"): ScriptedUsage(1330, 1446, 1402, TRANSCRIBED),
    # The Nano reported NO reasoning count on either answer it gave. That is scripted as an
    # absent details object rather than a zero, which is the convention the output has to honour.
    (NANO, "when"): ScriptedUsage(1318, 990, None, TRANSCRIBED),
    (NANO, "how_many"): ScriptedUsage(1324, 1016, None, TRANSCRIBED),
    # The runaway the record calls "the fallback also ran away once and that is why this is a
    # proposal": all 32768 completion tokens spent on the `who` packet and no answer produced.
    # Scripted as spending the CEILING UNDER TEST, because that is what a runaway does, and it is
    # the arithmetic behind the argument for the lower ceiling.
    (NANO, "who"): ScriptedUsage(1329, None, None, TRANSCRIBED, runaway=True),
    (NANO, "unrelated"): ScriptedUsage(1330, 1016, None, INVENTED),
}


def scripted_body(*, model_id: str, key: str, packet: EvidencePacket, ceiling: int) -> dict[str, Any]:
    """One response body, shaped like the archived runtime ones, for one cell of the matrix."""
    usage = SCRIPTED_USAGE[(model_id, key)]
    if usage.runaway:
        # HTTP 200, `finish_reason: "length"`, nothing written. `result_from_body` raises
        # TruncatedResponseError on exactly this shape and `compose_answer` falls to the
        # deterministic floor without a repair, which is the path being exercised.
        body = chat_body(
            content="",
            model=model_id,
            finish_reason="length",
            completion_tokens=ceiling,
            prompt_tokens=usage.prompt_tokens,
        )
        del body["usage"]["completion_tokens_details"]
        return body
    template = SCRIPTED_ANSWERS[key]
    clause: dict[str, Any] = {
        "text": template["text"],
        "type": template["type"],
        "citations": [packet.items[0].token] if template["cites"] else [],
        "value_refs": list(template["value_refs"]),
    }
    body = chat_body(
        content=json.dumps({"clauses": [clause]}),
        model=model_id,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens or 0,
        reasoning_tokens=usage.reasoning_tokens or 0,
    )
    if usage.reasoning_tokens is None:
        # Absent, not zero. This is the case the record's own convention exists for.
        del body["usage"]["completion_tokens_details"]
    return body


class Unscripted(RuntimeError):
    """Raised when the fake transport is asked for a response nobody scripted.

    Loud on purpose. `compose_answer` catches `StructuredOutputError`, `TruncatedResponseError`
    and `AnswerRejected` and falls back for each, so a fixture that quietly asked for a second
    response would be recorded as a repair or a deterministic fallback that the live path would
    not have made. This is not one of those exceptions and it stops the run.
    """


# -- the matrix ------------------------------------------------------------------------------------


def compose_once(
    *,
    client: ModelClient,
    manifest: Manifest,
    guard: BudgetGuard,
    model_id: str,
    ceiling: int,
    key: str,
    question: str,
    why: str,
    packet: EvidencePacket,
    index: int,
) -> dict[str, Any]:
    """One cell: one composer, one ceiling, one question, one pass.

    The wall clock is measured here as well as read off the calls, because they are two different
    numbers: the calls report what the endpoint took and this reports what a person waits, which
    also contains validation, one possible repair, and the deterministic floor underneath both.

    **The cost comes from the budget ledger, not from the call log, and on this experiment the
    difference is the whole point.** A call the endpoint truncated raises inside
    `ModelClient.structured` before any `ChatResult` reaches `compose_answer`, so it is ABSENT
    from `CallLog` and a cost summed from that log reports a runaway as free. The predecessor's
    record lists exactly that as its first known limitation. `result_from_body` records the usage
    on the budget guard's ledger BEFORE it raises, so the ledger is the only place a truncated
    call's tokens exist in this process, and the slice taken around this one call is what
    attributes them to the cell that spent them. Both figures are reported so the gap is visible
    rather than reconciled away.

    Only the completion count and the cost are taken from the ledger. `CallUsage` coalesces an
    absent reasoning count to zero, which is right for a bill and wrong for a record of what was
    observed, so every nullable token count still comes from `ModelCall`, which preserves it.
    """
    before = len(guard.ledger.calls)
    log = CallLog()
    started = time.monotonic()
    with composer_ceiling(ceiling):
        answer, deterministic, rejections = compose_answer(client, question, packet, log=log)
    waited_ms = round((time.monotonic() - started) * 1000)
    calls = [dataclasses.asdict(call) for call in log.calls]
    billed = guard.ledger.calls[before:]
    return {
        "key": key,
        "question": question,
        "why_this_question": why,
        "model_id": model_id,
        "composer_max_tokens": ceiling,
        "pass": index,
        "packet_items": len(packet.items),
        "answer": " ".join(clause.text for clause in answer.clauses),
        "clause_types": [clause.type.value for clause in answer.clauses],
        # The outcome variable. True means the model's output was discarded entirely and the
        # deterministic answer rendered, which is a first-class output and not an error.
        "reached_the_deterministic_floor": deterministic,
        "rejections": list(rejections),
        "calls": calls,
        "served_models": [call["served_model"] for call in calls],
        "model_latency_ms": sum(call["latency_ms"] for call in calls),
        "wall_clock_ms": waited_ms,
        # Every request the guard billed for this cell, INCLUDING one that raised before
        # returning a result. `calls` above lists only the ones that came back.
        "billed_calls": len(billed),
        "billed_completion_tokens": [usage.completion_tokens for usage in billed],
        "calls_that_never_returned_a_result": len(billed) - len(calls),
        # A call that spent the whole ceiling. `completion_tokens` equal to `max_tokens` is what
        # a runaway looks like from the outside, and it is the thing the two ceilings differ on.
        # Read off the ledger, because a runaway is precisely the call that never comes back.
        "spent_the_whole_ceiling": any(usage.completion_tokens == ceiling for usage in billed),
        "cost_micro_usd": sum(micro_usd(usage.usd) for usage in billed),
        "cost_micro_usd_from_returned_calls_only": sum(
            cost_of(manifest, call["requested_model"], call["prompt_tokens"],
                    call["completion_tokens"])
            for call in calls
        ),
    }


def measure_matrix(
    *,
    manifest: Manifest,
    guard: BudgetGuard,
    packets: Mapping[str, EvidencePacket],
    client_for: Callable[[str], ModelClient],
    script_for: Callable[..., None] | None,
) -> list[dict[str, Any]]:
    """Every cell of models x ceilings x questions x passes, in a stated order."""
    runs: list[dict[str, Any]] = []
    for model_id in COMPOSERS:
        client = client_for(model_id)
        for ceiling in CEILINGS:
            for key, question, why in QUESTIONS:
                packet = packets[key]
                for index in range(1, PASSES + 1):
                    if packet.is_empty:
                        runs.append(
                            {
                                "key": key,
                                "question": question,
                                "why_this_question": why,
                                "model_id": model_id,
                                "composer_max_tokens": ceiling,
                                "pass": index,
                                "skipped": (
                                    "the packet is empty, so there is no code path to a composer "
                                    "call. This is the abstention guarantee, not a gap."
                                ),
                            }
                        )
                        continue
                    if script_for is not None:
                        script_for(model_id=model_id, key=key, packet=packet, ceiling=ceiling)
                    runs.append(
                        compose_once(
                            client=client,
                            manifest=manifest,
                            guard=guard,
                            model_id=model_id,
                            ceiling=ceiling,
                            key=key,
                            question=question,
                            why=why,
                            packet=packet,
                            index=index,
                        )
                    )
                    print(
                        f"{model_id} @{ceiling} {key} pass {index}: "
                        f"{runs[-1]['wall_clock_ms']} ms",
                        file=sys.stderr,
                    )
    return runs


# -- the live half ---------------------------------------------------------------------------------


def read_workspace_id(scene: str) -> str:
    """The reference workspace's id. The bearer token in the same file is deliberately not read.

    This script makes no request to the API, so it needs no bearer token, and a script that reads
    a credential it has no use for is a credential in one more process for no reason.
    """
    config = json.loads((STATE / "access.json").read_bytes())
    return str(config["scenes"][scene]["workspace_id"])


def packets_from_the_database(scene: str) -> tuple[dict[str, EvidencePacket], str]:
    """Rebuild each recorded Selection's packet once, through the read-only executor role.

    Once per question and then reused across every model, ceiling and pass. Rebuilding per cell
    would mint fresh citation tokens and reorder nothing else, but the prompt would differ
    between passes and this run exists to vary one thing.

    The connection is WORKSPACE SCOPED because row-level security is on and an unscoped
    connection reads nothing: the predecessor's first run reported an empty packet for all five
    questions against a workspace holding 51 captures.
    """
    workspace_id = read_workspace_id(scene)
    session = Session(workspace_id=uuid.UUID(workspace_id), actor=uuid.uuid4())
    packets: dict[str, EvidencePacket] = {}
    with Database(READONLY).session(uuid.UUID(workspace_id)) as connection:
        for key, _question, _why in QUESTIONS:
            plan = SelectionPlan.model_validate(RECORDED_PLANS[key])
            result = execute(connection, validate(connection, plan, session))
            packets[key] = build_packet(
                connection, result, workspace_id=session.workspace_id
            )
    return packets, workspace_id


def live_run(*, manifest: Manifest, guard: BudgetGuard, scene: str) -> dict[str, Any]:
    """The paid half. Nothing in here runs without both statements of the ceiling."""
    packets, workspace_id = packets_from_the_database(scene)
    clients: dict[str, ModelClient] = {}

    def client_for(model_id: str) -> ModelClient:
        if model_id not in clients:
            clients[model_id] = ModelClient(
                manifest=pinned_manifest(manifest, model_id),
                budget=guard,
                timeout=300.0,
            )
        return clients[model_id]

    runs = measure_matrix(
        manifest=manifest,
        guard=guard,
        packets=packets,
        client_for=client_for,
        script_for=None,
    )

    # The streamed half, once per model per ceiling, on one question. Four calls, and they are
    # four separate requests whose tokens are their own.
    api_key = api_key_from_env(manifest.api_key_env)
    streamed: list[dict[str, Any]] = []
    stream_key = "when"
    question = next(q for k, q, _ in QUESTIONS if k == stream_key)
    for model_id in COMPOSERS:
        for ceiling in CEILINGS:
            probe = stream_probe(
                manifest=manifest,
                guard=guard,
                api_key=api_key,
                model_id=model_id,
                question=question,
                packet=packets[stream_key],
                ceiling=ceiling,
            )
            probe["question_key"] = stream_key
            streamed.append(probe)
            print(
                f"stream {model_id} @{ceiling}: first answer content at "
                f"{probe.get('first_answer_content_ms')} ms",
                file=sys.stderr,
            )

    return {
        "live": True,
        "these_numbers_are": (
            "measured against the live Nebius Token Factory endpoint on the retained reference "
            "workspace, through the same compose_answer the product runs."
        ),
        "workspace": f"retained local reference, scene={scene}",
        "workspace_id": workspace_id,
        "database_schema": "0038",
        "packet_source": (
            "rebuilt once per question from the Selections archived under "
            "docs/evaluation/artifacts/2026-09-09-companion-question/, through the read-only "
            "executor role, and reused across every model, ceiling and pass."
        ),
        "runs": runs,
        "time_to_first_token": {
            "what_these_three_numbers_are": (
                "first_sse_chunk_ms is when the connection produced anything; "
                "first_reasoning_delta_ms is when the model began thinking out loud in the "
                "separate reasoning_content delta; first_answer_content_ms is when the first "
                "character of the ANSWER arrived in the content delta. Only the third answers "
                "'do the first words appear early'."
            ),
            "why_this_is_not_the_ModelClient_path": (
                "ModelClient cannot stream: Transport is a post_json/get_json protocol returning "
                "a fully materialised response, and exulanica/models is read-only to this task. "
                "Each entry below is a SECOND request with its own tokens and its own bill."
            ),
            "streamed": streamed,
        },
    }


# -- the half that spends nothing --------------------------------------------------------------------


def scripted_run(*, manifest: Manifest, guard: BudgetGuard, cap_usd: str, max_calls: int) -> dict[str, Any]:
    """Everything that costs nothing, driven by the scripted transport and a fake clock."""
    packets = {key: scripted_packet(key) for key, _question, _why in QUESTIONS}
    transports: dict[str, FakeTransport] = {}
    clients: dict[str, ModelClient] = {}

    def client_for(model_id: str) -> ModelClient:
        if model_id not in clients:
            transports[model_id] = FakeTransport()
            clients[model_id] = ModelClient(
                manifest=pinned_manifest(manifest, model_id),
                transport=transports[model_id],
                # Stated rather than read. A scripted run reaches no network and needs no
                # credential, and passing one here is what keeps it from reading a real key
                # out of the environment or a .env file for a request it will never send.
                api_key="scripted-run-reads-no-credential",
                budget=guard,
            )
        return clients[model_id]

    def script_for(*, model_id: str, key: str, packet: EvidencePacket, ceiling: int) -> None:
        transport = transports[model_id]
        transport.responses = [
            HttpResponse(
                status_code=200,
                text=json.dumps(
                    scripted_body(model_id=model_id, key=key, packet=packet, ceiling=ceiling)
                ),
            ),
            Unscripted(
                f"{model_id} asked for a second response on {key}: the fixture scripts one call "
                "per cell, so a second one means a repair or a failover the live path would not "
                "have made."
            ),
        ]

    runs = measure_matrix(
        manifest=manifest,
        guard=guard,
        packets=packets,
        client_for=client_for,
        script_for=script_for,
    )

    # -- what the wire actually carried -----------------------------------------------------
    #
    # The proof of the override, and it is deliberately read off the requests rather than off
    # the constant: "the ceiling was set" is a claim about a variable and "the ceiling was sent"
    # is a claim about a request.
    ceilings_sent: dict[str, list[int]] = {}
    for model_id, transport in transports.items():
        ceilings_sent[model_id] = sorted(
            {int(request["payload"]["max_tokens"]) for request in transport.requests}
        )

    # -- the refusal, exercised ---------------------------------------------------------------
    refusals: list[dict[str, Any]] = []
    for name, environment in (
        ("nothing stated in the environment", {}),
        (
            "a ceiling stated twice and disagreeing",
            {"EXULANICA_BUDGET_USD": "5.00", "EXULANICA_BUDGET_MAX_CALLS": str(max_calls),
             "NEBIUS_API_KEY": "x"},
        ),
        (
            "the dollar ceiling agreeing and the call ceiling not",
            {"EXULANICA_BUDGET_USD": cap_usd, "EXULANICA_BUDGET_MAX_CALLS": "2",
             "NEBIUS_API_KEY": "x"},
        ),
        (
            "both ceilings agreeing and no credential",
            {"EXULANICA_BUDGET_USD": cap_usd, "EXULANICA_BUDGET_MAX_CALLS": str(max_calls)},
        ),
        (
            "both ceilings agreeing and a credential present",
            {"EXULANICA_BUDGET_USD": cap_usd, "EXULANICA_BUDGET_MAX_CALLS": str(max_calls),
             "NEBIUS_API_KEY": "x"},
        ),
    ):
        try:
            refuse_unless_stated_twice(
                cap_usd=cap_usd, max_calls=max_calls, environ=environment
            )
        except SystemExit as refused:
            refusals.append({"environment": name, "refused": True, "said": str(refused)[:200]})
        else:
            refusals.append({"environment": name, "refused": False, "said": None})

    # -- the SSE parser, on the transcript of the probe already taken live --------------------
    clock = ScriptedClock()
    timing = read_stream(scripted_lines(PROBED_TRANSCRIPT, clock), now=clock)

    return {
        "live": False,
        "these_numbers_are": (
            "SCRIPTED. Every token count, latency and answer below was transcribed from "
            "docs/evaluation/2026-09-09-companion-question.json or invented for the fixture, and "
            "each scripted usage entry names which. No model was called and nothing was billed. "
            "What this record establishes is that the harness runs, records and refuses "
            "correctly, and it establishes nothing whatever about either model."
        ),
        "packet_source": (
            "scripted in memory to the shape of the recorded packets: ten items, one capture "
            "date, 51 matched, and one question whose Selection matched nothing."
        ),
        "runs": runs,
        "scripted_usage": {
            f"{model_id} / {key}": dataclasses.asdict(usage)
            for (model_id, key), usage in SCRIPTED_USAGE.items()
        },
        "time_to_first_token": {
            "what_these_three_numbers_are": (
                "first_sse_chunk_ms is when the connection produced anything; "
                "first_reasoning_delta_ms is when the model began thinking out loud in the "
                "separate reasoning_content delta; first_answer_content_ms is when the first "
                "character of the ANSWER arrived in the content delta. Only the third answers "
                "'do the first words appear early'."
            ),
            "streamed": [
                {
                    "model_id": LIGHTNING,
                    "scripted": True,
                    "source": (
                        "the live SSE probe already taken against this endpoint on a small "
                        "json_schema request, replayed through the parser with a fake clock"
                    ),
                    "question_key": None,
                    "composer_max_tokens": None,
                    **timing.as_json(),
                }
            ],
            "the_conflation_this_separates": (
                "one number would have reported 752 ms as the time to first token for an answer "
                "whose first character arrived at 2096 ms, on a probe where 419 of 522 "
                "completion tokens were reasoning."
            ),
        },
        "self_checks": {
            "the_refusal_still_refuses": refusals,
            "the_ceiling_reached_the_wire": ceilings_sent,
            "the_ceilings_this_run_measured": list(CEILINGS),
            "the_constant_was_restored": composer.COMPOSER_MAX_TOKENS,
            "the_constant_on_disk_is_unchanged": DECLARED_CEILING == composer.COMPOSER_MAX_TOKENS,
            "the_process_wide_manifest_is_unpinned": {
                "reasoning_cheap_primary": load_manifest()[Role.REASONING_CHEAP].primary.model_id,
                "reasoning_cheap_fallback": (
                    load_manifest()[Role.REASONING_CHEAP].fallback.model_id
                ),
            },
            # Every distinct reasoning count the run recorded, null included. The Nano's scripted
            # answers carry no completion_tokens_details at all and must arrive here as null: a
            # zero would assert it did no inline reasoning, which is a measurement nobody took.
            "an_absent_reasoning_count_is_null_not_zero": sorted(
                {call["reasoning_tokens"] for run in runs for call in run.get("calls", ())},
                key=lambda value: (value is not None, value or 0),
            ),
            # The runaway cells, which are the reason the cost is read off the ledger. Each one
            # was billed for a request that never returned a result, so it is absent from `calls`
            # and present in `billed_calls`.
            "calls_billed_but_never_returned": sum(
                run.get("calls_that_never_returned_a_result", 0) for run in runs
            ),
            "requests_the_fake_transport_saw": {
                model_id: transport.call_count for model_id, transport in transports.items()
            },
        },
    }


# -- output ------------------------------------------------------------------------------------------


def refuse_floats(node: Any, path: str = "$") -> None:
    """Refuse a float anywhere in the record, naming where it is.

    Every evaluation record in this repository refuses floats: one rewrites its own last digits
    on a JSON round trip and a digest over it stops reproducing. Latency is whole milliseconds,
    a dollar figure is a string, a micro-dollar figure is an integer. This is the check rather
    than the convention, because a convention is what the next number gets written against.
    """
    if isinstance(node, bool) or node is None or isinstance(node, (int, str)):
        return
    if isinstance(node, float):
        raise SystemExit(f"{path} is a float ({node!r}). Milliseconds are whole numbers here.")
    if isinstance(node, Mapping):
        for key, value in node.items():
            refuse_floats(value, f"{path}.{key}")
        return
    if isinstance(node, (list, tuple)):
        for ordinal, value in enumerate(node):
            refuse_floats(value, f"{path}[{ordinal}]")
        return
    raise SystemExit(f"{path} is a {type(node).__name__}, which JSON cannot carry unconverted.")


def measure() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", required=True, help="The operator's ceiling, stated again")
    parser.add_argument("--max-calls", required=True, type=int)
    parser.add_argument("--scene", default="bowl")
    parser.add_argument("--out", type=Path, required=True, help="Where the measurement JSON goes")
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Exercise everything that spends nothing, driven by the scripted transport.",
    )
    args = parser.parse_args()

    if not args.skip_live:
        refuse_unless_stated_twice(
            cap_usd=args.cap_usd, max_calls=args.max_calls, environ=os.environ
        )

    if args.out.exists():
        raise SystemExit(
            f"{args.out} exists. A measurement is written once and never over the top of an "
            "earlier one, because the earlier one is somebody's evidence."
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    # ONE guard for the whole process, shared by both clients. Two clients with a ceiling each is
    # two ceilings, and the operator stated one.
    guard = BudgetGuard(ceiling_usd=Decimal(args.cap_usd), max_calls=args.max_calls)

    if args.skip_live:
        body = scripted_run(
            manifest=manifest, guard=guard, cap_usd=args.cap_usd, max_calls=args.max_calls
        )
    else:
        body = live_run(manifest=manifest, guard=guard, scene=args.scene)

    runs = body["runs"]
    streamed = body["time_to_first_token"]["streamed"]
    record: dict[str, Any] = {
        "profile": "exulanica.composer-memory-measurement/v1",
        "prompt_version": PROMPT_VERSION,
        "pipeline_version": manifest.pipeline_version,
        "declared_composer_max_tokens": DECLARED_CEILING,
        "composer_max_tokens_measured": list(CEILINGS),
        "why_the_lower_ceiling_is_this_number": (
            f"{LOWER_CEILING} is the largest ceiling at which this call has ever been observed to "
            "fail: COMPOSER_MAX_TOKENS' own comment records the composer truncating there on an "
            "8-item packet, with no artifact behind it. Every artifact-backed completion count on "
            "this call is far below it (6490, 5903, 2301, 1446 for the reasoning core, of which "
            "6428, 5850, 2248 and 1402 were reasoning), and the answer inside each is 44 to 62 "
            "tokens. Halving the constant is the smallest step that can say whether the second "
            "half of the ceiling is doing work or only lengthening a runaway: the Nano spent all "
            "32768 completion tokens once and produced no answer, which is 7864 micro-dollars and "
            "the wall clock of 32768 tokens for a deterministic fallback it would have reached "
            "from half that. 8192 was rejected because it sits BELOW a ceiling already measured "
            "to truncate here, so a run there would measure the fallback rate rather than the "
            "ceiling."
        ),
        "composer_max_tokens_is_not_changed_by_this_script": True,
        "passes_per_cell": PASSES,
        "composers": list(COMPOSERS),
        "cap_usd": str(Decimal(args.cap_usd)),
        "cap_max_calls": args.max_calls,
        "how_the_ceiling_was_overridden": (
            "COMPOSER_MAX_TOKENS was rebound on the imported exulanica.selection.question module "
            "for the duration of each call and restored in a finally. No source file was edited, "
            "and the composer role was pinned on a dataclasses.replace copy of the manifest, so "
            "models.manifest.json and pipeline_version are untouched."
        ),
        "no_response_cache": (
            "Every client here is built without one. The cache key digests max_tokens, so the two "
            "ceilings could not collide, but the three passes inside one cell would: passes two "
            "and three would be served pass one's body at zero latency."
        ),
        **body,
        "total_cost_micro_usd": (
            sum(run.get("cost_micro_usd", 0) for run in runs)
            + sum(entry.get("cost_micro_usd", 0) for entry in streamed)
        ),
        "spend_recorded_by_the_budget_guard": guard.ledger.as_cost_json(),
        "experiment_script": "scripts/measure_companion_memory.py",
        "experiment_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    refuse_floats(record)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    composed = [run for run in runs if "calls" in run]
    print(
        json.dumps(
            {
                "live": record["live"],
                "out": str(args.out),
                "cells": len(runs),
                "composed": len(composed),
                "skipped_empty_packet": len(runs) - len(composed),
                "reached_the_deterministic_floor": sum(
                    1 for run in composed if run["reached_the_deterministic_floor"]
                ),
                "spent_the_whole_ceiling": sum(
                    1 for run in composed if run["spent_the_whole_ceiling"]
                ),
                "calls_billed_but_never_returned": sum(
                    run.get("calls_that_never_returned_a_result", 0) for run in composed
                ),
                "streamed_calls": len(streamed),
                "total_cost_micro_usd": record["total_cost_micro_usd"],
                "total_cost_micro_usd_from_returned_calls_only": sum(
                    run.get("cost_micro_usd_from_returned_calls_only", 0) for run in composed
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(measure())
