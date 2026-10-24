"""The models a person's own runner holds, each checked once on this computer before a person may
choose one (L1).

A person's install with no key asks the models its runner serves on this computer (A2). Beyond the
one model the manifest ships for it, every model the runner holds may be offered, once a check on
this computer has measured that it answers a person's choice in the role's own form within the
role's deadline (DESIGN's ruling of 24 October, WORDS.md "L1, every model on this computer"; ROOT's
of 04:41 and 10:31):

- **What it holds** is read from the tag list the liveness read already keeps
  (``LocalLiveness.catalog``): each model by its digest, the tag it is served by now, its family,
  size and capabilities. Nothing more is read for the list.
- **What it reads at once** is read once per digest from the runner's ``/api/show``, at the
  provider's own origin through the client's egress-checked transport: its
  ``<family>.context_length``. One that reads less than a person is told here
  (:func:`role_context_tokens`) is not able.
- **The check** asks it the role's own requests (``assets/catalogs/local-check``, a person alone and
  one beside someone who hears them) through the runner's ``/api/chat``: the role's messages, its
  JSON schema as the format, the role's ``num_ctx`` and, for a model that reasons, reasoning off.
  One unrecorded ask loads it first; each case is then asked within the role's deadline. It is able
  where the host takes every answer (a ``Judge``, the role's own rule, which this layer is handed):
  an offered label, with a line exactly where that label says something, within the line's rule
  and naming no one it is said to.
- **Not able** has one reason: ``text`` (it does not read text), ``context`` (it reads less than a
  person is told here), ``slow`` (a case took longer than the deadline) or ``form`` (a case was not
  answered with an offered choice).
- **The record** of a check is the install's own runtime data, one file per digest in its own
  directory (``EXULANICA_LOCAL_CHECKS_DIR``), kept, and never an evaluation record. A record made
  under other cases, another contract or another context is stale and the model is checked again.
  Without the directory nothing is checked.
- **One check at a time**, in one background thread, begun the first time a list shows a digest;
  until it ends that model is being checked.
- **A runner model's id is** ``local/sha256-<digest>``: a choice, its receipts and a replay name the
  weights that decided, never the tag the runner serves them by now.

Nothing is pulled, created or removed on the runner: it is read, shown and asked.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.models.errors import StructuredOutputError, TransportError
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec, Provider
from exulanica.models.transport import Transport

__all__ = [
    "CHECKS_DIR_ENV",
    "CHECK_PROFILE",
    "REASONS",
    "CheckStore",
    "Judge",
    "LocalChecks",
    "RunnerModel",
    "able_specs",
    "chat_request",
    "check_cases",
    "check_model",
    "checked_ms",
    "role_context_tokens",
    "runner_answer",
    "runner_models",
    "runner_name",
    "runner_request",
    "runner_rows",
    "runner_spec",
    "with_runner_models",
]

#: The directory a person's install keeps its checks in; without it nothing is checked or offered.
CHECKS_DIR_ENV: Final = "EXULANICA_LOCAL_CHECKS_DIR"
#: How the host takes a model's answer to one case, its label and line: ``offered_label`` where it
#: takes it, or the rule that refuses it. The role's rule lives above this layer, so a check is
#: handed it (``exulanica.world.role_decisions.answer_outcome``, its contract versions bound).
Judge = Callable[[Mapping[str, Any], str, str | None], str]
CHECK_PROFILE: Final = "exulanica.local-check/v1"
CASES_PATH: Final = (
    Path(__file__).resolve().parents[2] / "assets/catalogs/local-check/local-check-cases.v1.json"
)
#: Why a model is not able, in the order a check finds them; ``error`` where the check itself failed
#: in a way nobody named, kept so the model is not checked again on every list.
REASONS: Final = ("text", "context", "slow", "form", "error")
#: What a check's answering record names: the kept check of the weights, never a docs record.
CHECK_RECORD_PREFIX: Final = "local-check:sha256-"
#: The fewest bytes one token of a request holds, read conservatively: English and its punctuation
#: run near four.
BYTES_PER_TOKEN: Final = 3
#: Room beside the observation for the role's instruction, its offered options and the answer.
ANSWER_ROOM_TOKENS: Final = 2_048
#: The most tokens an answer may hold: the shipped model's own bound (``default_max_tokens``).
ANSWER_TOKENS: Final = 512
#: How long the unrecorded first ask may take to load a model into memory.
LOAD_SECONDS: Final = 180.0
#: How long a ``/api/show`` read may take.
SHOW_SECONDS: Final = 5.0
#: How long a check that could not be made stands before the model is checked again.
ERROR_KEPT: Final = timedelta(hours=6)
#: The units a runner states a model's size in.
_SIZE_UNITS: Final = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
#: The most of a licence's first line a check keeps: its name, as the runner states it.
LICENCE_CHARACTERS: Final = 200
_DIGEST: Final = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunnerModel:
    """One model a runner holds: its weights' digest and what the runner says of it now."""

    digest: str
    #: The name the runner serves it by now: what it is asked by, never what a choice records.
    tag: str
    family: str | None
    parameter_size: str | None
    capabilities: tuple[str, ...]

    @property
    def model_id(self) -> str:
        """The identifier a choice records: the weights', whatever the runner calls them."""
        return f"local/sha256-{self.digest}"

    @property
    def reasons(self) -> bool:
        """Whether it reasons before it answers, so it is asked with reasoning off."""
        return "thinking" in self.capabilities


def runner_models(catalog: Any) -> tuple[RunnerModel, ...]:
    """The models an Ollama tag list holds, one per digest (the first tag in name order where
    several serve one), in name order. An entry without a sha256 digest is passed over: a model is
    known by its weights.
    """
    found: dict[str, RunnerModel] = {}
    entries = catalog.get("models") if isinstance(catalog, Mapping) else None
    for entry in sorted(
        (e for e in entries or () if isinstance(e, Mapping)), key=lambda e: str(e.get("name"))
    ):
        name, digest = entry.get("name"), _DIGEST.match(str(entry.get("digest") or ""))
        if not isinstance(name, str) or not name or digest is None or digest.group(1) in found:
            continue
        stated = entry.get("details")
        details: Mapping[str, Any] = stated if isinstance(stated, Mapping) else {}
        found[digest.group(1)] = RunnerModel(
            digest=digest.group(1),
            tag=name,
            family=_text(details.get("family")),
            parameter_size=_text(details.get("parameter_size")),
            capabilities=tuple(str(c) for c in entry.get("capabilities") or ()),
        )
    return tuple(found.values())


def role_context_tokens(contract: Any) -> int:
    """The most tokens a request of the role can hold, which a model must read at once and is asked
    with as its ``num_ctx``: the contract's bound on an observation, read at
    :data:`BYTES_PER_TOKEN`, with room for the instruction, the options and the answer, rounded up
    to a whole thousand and twenty-four.
    """
    tokens = (
        math.ceil(int(contract.value("context_bytes_maximum")) / BYTES_PER_TOKEN)
        + ANSWER_ROOM_TOKENS
    )
    return math.ceil(tokens / 1_024) * 1_024


def check_cases(path: Path = CASES_PATH) -> Mapping[str, Any]:
    """The requests a model is checked by, as their catalog states them."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("profile") != "exulanica.local-check-cases/v1"
        or len(document.get("cases") or ()) < 2
    ):
        raise ValueError(f"{path} is not the local check's cases")
    return document


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _endpoint(provider: Provider, path: str) -> str:
    return provider.origin.rstrip("/") + path


def read_show(
    provider: Provider, transport: Transport, model: RunnerModel
) -> tuple[int | None, str | None]:
    """What the runner's ``/api/show`` says of ``model``: the most tokens it reads at once, and the
    first line of the licence it states, quoted as stated and never classed here; each None where
    it states none.
    """
    response = transport.post_json(
        _endpoint(provider, "/api/show"),
        headers={"Accept": "application/json"},
        payload={"model": model.tag},
        timeout=SHOW_SECONDS,
    )
    if not response.ok:
        raise TransportError(f"HTTP {response.status_code}", reached_provider=True)
    body = response.json_body()
    info = body.get("model_info")
    lengths = [
        v
        for k, v in (info if isinstance(info, Mapping) else {}).items()
        if str(k).endswith(".context_length") and isinstance(v, int)
    ]
    stated = body.get("license")
    lines = (
        [line.strip() for line in stated.splitlines() if line.strip()]
        if isinstance(stated, str)
        else []
    )
    return (max(lengths) if lengths else None), (lines[0][:LICENCE_CHARACTERS] if lines else None)


def chat_request(
    tag: str,
    messages: Sequence[Mapping[str, Any]],
    schema: Mapping[str, Any],
    *,
    num_ctx: int,
    num_predict: int,
    temperature: float,
    reasoning_off: bool,
) -> dict[str, Any]:
    """The one request a runner's model is asked by, through the runner's own ``/api/chat``, by a
    check and by a person's choice alike: the messages, the choice's JSON schema as the format,
    the role's context and the answer's room, and, for a model that reasons, reasoning off where
    the runner allows it.
    """
    payload: dict[str, Any] = {
        "model": tag,
        "messages": [dict(message) for message in messages],
        "stream": False,
        "format": dict(schema),
        "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": temperature},
    }
    if reasoning_off:
        payload["think"] = False
    return payload


def runner_request(spec: ModelSpec, payload: Mapping[str, Any]) -> dict[str, Any]:
    """A chat-completions request to ``spec``, a runner's model, as its runner's ``/api/chat``
    takes it (:func:`chat_request`): the request its check asked. Only a choice by its strict
    JSON schema is asked of such a model, the one mechanism a check verifies.
    """
    response_format = payload.get("response_format")
    schema = (
        (response_format.get("json_schema") or {}).get("schema")
        if isinstance(response_format, Mapping) and response_format.get("type") == "json_schema"
        else None
    )
    if spec.served_as is None or not isinstance(schema, Mapping):
        raise ValueError(
            f"{spec.model_id} is a runner's model, asked only for a choice by its JSON schema"
        )
    return chat_request(
        spec.served_as,
        payload["messages"],
        schema,
        num_ctx=spec.context_window_tokens,
        num_predict=int(payload["max_tokens"]),
        temperature=float(payload.get("temperature", 0.0)),
        reasoning_off=spec.served_with_reasoning_off,
    )


def runner_answer(spec: ModelSpec, body: Mapping[str, Any]) -> dict[str, Any]:
    """A runner's ``/api/chat`` answer in the chat-completions shape the client reads: its text as
    the one choice, cut short where the runner says so, its token counts as usage, and the model
    named by its weights only where the runner answered for the name it was asked by.
    """
    said = body.get("message")
    message: Mapping[str, Any] = said if isinstance(said, Mapping) else {}
    prompt, completion = (int(body.get(key) or 0) for key in ("prompt_eval_count", "eval_count"))
    served = body.get("model")
    return {
        "model": spec.model_id if served == spec.served_as else str(served or ""),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": str(message.get("content") or "")},
                "finish_reason": "length" if body.get("done_reason") == "length" else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def _ask(
    provider: Provider,
    transport: Transport,
    model: RunnerModel,
    role: Any,
    case: Mapping[str, Any],
    num_ctx: int,
    timeout: float,
) -> tuple[str, str | None]:
    """Ask ``model`` one case as the role asks it, through ``/api/chat``, exactly as a person's
    choice will ask it (:func:`chat_request`); the label and line it answered.
    """
    choice = role.choice(case)
    response = transport.post_json(
        _endpoint(provider, "/api/chat"),
        headers={"Accept": "application/json"},
        payload=chat_request(
            model.tag,
            role.adapter.messages(role, case, AnsweringMechanism.JSON_SCHEMA),
            choice.schema(),
            num_ctx=num_ctx,
            num_predict=ANSWER_TOKENS,
            temperature=0.0,
            reasoning_off=model.reasons,
        ),
        timeout=timeout,
    )
    if not response.ok:
        raise TransportError(f"HTTP {response.status_code}", reached_provider=True)
    message = response.json_body().get("message") or {}
    try:
        arguments = json.loads(str(message.get("content") or ""))
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"the answer is not JSON: {exc}") from exc
    return choice.answer_with_line(arguments)


def _record(model: RunnerModel, contract: Any, cases: Mapping[str, Any]) -> dict[str, Any]:
    """What every check of ``model`` records before its verdict: the weights, what the runner says
    of them, and the terms it is checked under.
    """
    return {
        "profile": CHECK_PROFILE,
        "digest": model.digest,
        "model_id": model.model_id,
        "served_as": model.tag,
        "family": model.family,
        "parameter_size": model.parameter_size,
        "capabilities": list(model.capabilities),
        "role": cases["role"],
        "contract_versions": cases["contract_versions"],
        "cases_sha256": cases["cases_sha256"],
        "num_ctx": role_context_tokens(contract),
        "deadline_ms": int(contract.value("decision_deadline_ms")),
        "context_tokens": None,
        "licence": None,
        "cases": [],
    }


def check_model(
    provider: Provider,
    transport: Transport,
    model: RunnerModel,
    *,
    role: Any,
    contract: Any,
    cases: Mapping[str, Any],
    judge: Judge,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Check ``model`` once: whether it is able to decide for a person here, why not, and every
    case's outcome as ``judge`` reads its answer.
    """
    num_ctx = role_context_tokens(contract)
    deadline = int(contract.value("decision_deadline_ms")) / 1_000
    record = _record(model, contract, cases)

    def verdict(reason: str | None) -> dict[str, Any]:
        return {**record, "able": reason is None, "reason": reason, "checked_at": now().isoformat()}

    if "completion" not in model.capabilities:
        return verdict("text")
    record["context_tokens"], record["licence"] = read_show(provider, transport, model)
    if record["context_tokens"] is not None and record["context_tokens"] < num_ctx:
        return verdict("context")
    # One unrecorded ask loads the model into memory, as a warm runner holds it when people are
    # asked.
    with contextlib.suppress(TransportError, StructuredOutputError):
        _ask(provider, transport, model, role, cases["cases"][0], num_ctx, LOAD_SECONDS)
    reason: str | None = None
    for number, case in enumerate(cases["cases"], 1):
        started = clock()
        try:
            label, line = _ask(provider, transport, model, role, case, num_ctx, deadline)
            outcome = judge(case, label, line)
        except TransportError as exc:
            outcome = "timed_out" if exc.timed_out else "not_answered"
        except StructuredOutputError:
            outcome = "not_a_choice"
        latency_ms = round((clock() - started) * 1_000)
        if outcome == "offered_label" and latency_ms > deadline * 1_000:
            outcome = "late"
        record["cases"].append({"case": number, "outcome": outcome, "latency_ms": latency_ms})
        if outcome != "offered_label" and reason is None:
            # The runner answering an ask with an error is not a model failing the form: the
            # check could not be made, and is made again later.
            reason = (
                "slow"
                if outcome in {"timed_out", "late"}
                else "error"
                if outcome == "not_answered"
                else "form"
            )
    return verdict(reason)


class CheckStore:
    """Every check this install made, one JSON file per digest in its own directory, kept."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, digest: str) -> Path:
        return self._directory / f"sha256-{digest}.json"

    def read(self, digest: str) -> dict[str, Any] | None:
        try:
            return json.loads(self._path(digest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write(self, record: Mapping[str, Any]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path(str(record["digest"]))
        partial = path.with_suffix(".json.partial")
        partial.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(partial, path)


class LocalChecks:
    """Which of a runner's models are able to decide for a person here, checked one at a time in the
    background.

    :meth:`state` answers at once from the kept records: ``able``, ``not_able`` (with its reason) or
    ``checking``. A model with no current record is queued, and one thread checks the queue in
    order, one model at a time.
    """

    def __init__(
        self,
        provider: Provider,
        transport: Transport,
        store: CheckStore,
        *,
        role: Any,
        contract: Any,
        cases: Mapping[str, Any],
        judge: Judge,
        start: Callable[[Callable[[], None]], object] | None = None,
        check: Callable[..., dict[str, Any]] = check_model,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._provider = provider
        self._transport = transport
        self._store = store
        self._role = role
        self._contract = contract
        self._cases = cases
        self._judge = judge
        self._check = check
        self._now = now
        self._start = start or (
            lambda work: threading.Thread(target=work, daemon=True, name="local-checks").start()
        )
        self._lock = threading.Lock()
        self._queue: list[RunnerModel] = []
        self._working = False

    def _current(self, record: Mapping[str, Any] | None) -> bool:
        """Whether a kept record was made under these cases, this contract and this context, and,
        for a check that could not be made, within :data:`ERROR_KEPT` of now."""
        if not record:
            return False
        return (
            record.get("profile") == CHECK_PROFILE
            and record.get("cases_sha256") == self._cases["cases_sha256"]
            and record.get("contract_versions") == self._cases["contract_versions"]
            and record.get("num_ctx") == role_context_tokens(self._contract)
            and (record.get("reason") != "error" or self._recent(record))
        )

    def _recent(self, record: Mapping[str, Any]) -> bool:
        """Whether a kept record was made within :data:`ERROR_KEPT` of now. A time that cannot be
        read, or names no zone, counts as stale, so the model is checked again."""
        try:
            checked = datetime.fromisoformat(str(record["checked_at"]))
        except (KeyError, ValueError):
            return False
        return checked.tzinfo is not None and self._now() - checked < ERROR_KEPT

    @property
    def provider(self) -> Provider:
        """The provider whose runner these checks ask."""
        return self._provider

    @property
    def engine(self) -> str:
        """The engine whose terms the cases are asked under: a model is offered only there."""
        return str(self._cases["engine"])

    @property
    def scope(self) -> tuple[str, str]:
        """The role and the prompt version a checked model may answer, the ones it was checked
        under."""
        return str(self._cases["role"]), str(self._role.terms(self.engine).prompt_version)

    def kept(self, model_id: str) -> dict[str, Any] | None:
        """The check kept for the weights a runner model's identifier names, current or not; None
        where none is kept or the identifier names no runner's model."""
        digest = model_id.removeprefix("local/sha256-")
        if digest == model_id or not _DIGEST.match(digest):
            return None
        return self._store.read(digest)

    def name(self, model_id: str) -> str | None:
        """How a person reads a runner's model by the identifier a choice records, from its kept
        check, whether or not the runner still holds it; None where none is kept."""
        record = self.kept(model_id)
        if record is None:
            return None
        digest = model_id.removeprefix("local/sha256-")
        return runner_name(
            RunnerModel(
                digest=digest,
                tag=str(record.get("served_as") or model_id),
                family=_text(record.get("family")),
                parameter_size=_text(record.get("parameter_size")),
                capabilities=tuple(record.get("capabilities") or ()),
            )
        )

    def record(self, model: RunnerModel) -> dict[str, Any] | None:
        """``model``'s current kept check, or None; one with none is queued to be checked."""
        record = self._store.read(model.digest)
        if self._current(record):
            return record
        self.ensure((model,))
        return None

    def state(self, model: RunnerModel) -> tuple[str, str | None]:
        """``model``'s state now and, where not able, why; one with no current record is queued."""
        record = self.record(model)
        if record is None:
            return ("checking", None)
        return ("able", None) if record["able"] else ("not_able", str(record["reason"]))

    def ensure(self, models: Iterable[RunnerModel]) -> None:
        """Queue every model with no current record that is not queued already, and start the worker
        if idle.
        """
        begin = False
        with self._lock:
            for model in models:
                if model.digest in {queued.digest for queued in self._queue}:
                    continue
                if not self._current(self._store.read(model.digest)):
                    self._queue.append(model)
            # The smallest model first, so the list fills fastest; one stating no size last.
            self._queue.sort(key=_size)
            if self._queue and not self._working:
                self._working = begin = True
        if begin:
            self._start(self._work)

    def _work(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._working = False
                    return
                model = self._queue[0]
            try:
                self._keep(model)
            finally:
                with self._lock:
                    self._queue = [q for q in self._queue if q.digest != model.digest]

    def _keep(self, model: RunnerModel) -> None:
        """Check ``model`` and keep what the check found. Never raises, so the worker outlives any
        one check.
        """
        try:
            record = self._check(
                self._provider,
                self._transport,
                model,
                role=self._role,
                contract=self._contract,
                cases=self._cases,
                judge=self._judge,
            )
        except TransportError as exc:
            if not exc.reached_provider:
                # The runner went away before it answered: nothing is known of the model, so
                # nothing is kept, and it is checked again the next time a list shows it.
                return
            record = self._failed(model, exc)
        except Exception as exc:
            record = self._failed(model, exc)
        try:
            self._store.write(record)
        except Exception as exc:
            # Unkept, the model is checked again the next time a list shows it.
            _LOG.warning("a local check could not be kept: %s", type(exc).__qualname__)

    def _failed(self, model: RunnerModel, exc: BaseException) -> dict[str, Any]:
        """A check that failed in a way nobody named, kept as not able for that reason, so it is
        not checked again on every list; by the error's kind, never its text.
        """
        return {
            **_record(model, self._contract, self._cases),
            "able": False,
            "reason": "error",
            "error": type(exc).__qualname__,
            "checked_at": self._now().isoformat(),
        }


def checks_directory(environ: Mapping[str, str] | None = None) -> Path | None:
    """The install's check directory, or None where none is stated: then nothing is checked or
    offered.
    """
    value = (os.environ if environ is None else environ).get(CHECKS_DIR_ENV)
    return Path(value) if value else None


def ordered(models: Sequence[RunnerModel], shipped: Iterable[str]) -> tuple[RunnerModel, ...]:
    """The runner's models a list adds beside the manifest's own: every one whose tag the manifest
    does not ship.
    """
    names = {name.removesuffix(":latest") for name in shipped}
    return tuple(model for model in models if model.tag.removesuffix(":latest") not in names)


def _size(model: RunnerModel) -> float:
    """How many parameters a runner says a model holds ("1.2B", "134.52M"); a size it does not
    state counts as larger than any."""
    stated = re.fullmatch(r"([0-9.]+)\s*([KMBT])", model.parameter_size or "")
    if stated is None:
        return math.inf
    try:
        return float(stated.group(1)) * _SIZE_UNITS[stated.group(2)]
    except ValueError:
        return math.inf


def checked_ms(record: Mapping[str, Any] | None) -> int | None:
    """How long the slowest of a kept check's cases took to answer, in milliseconds; None where none
    was asked."""
    times = [c["latency_ms"] for c in (record or {}).get("cases") or () if "latency_ms" in c]
    return max(times) if times else None


def runner_name(model: RunnerModel) -> str:
    """How a person reads a runner's model: its family and size as the runner states them
    ("Llama · 1.2B"), or, where it states neither, the name its person gave it; never an alias
    standing for another maker's model.
    """
    family = model.family[:1].upper() + model.family[1:] if model.family else None
    stated = [part for part in (family, model.parameter_size) if part]
    return " · ".join(stated) if stated else model.tag.removesuffix(":latest")


def runner_spec(model: RunnerModel, record: Mapping[str, Any], *, provider: str) -> ModelSpec:
    """``model`` as a model a person may choose, from its kept check: free, asked by the name its
    runner serves its weights by now and in the context its check asked it in, and verified to
    answer by its strict JSON schema, the check its record names.
    """
    return ModelSpec(
        model_id=model.model_id,
        provider=provider,
        description=(
            f"{runner_name(model)}, a model on this computer that a check here found able to "
            "decide for a person."
        ),
        input_usd_per_mtok=Decimal(0),
        output_usd_per_mtok=Decimal(0),
        context_window_tokens=int(record["num_ctx"]),
        min_max_tokens=ANSWER_TOKENS,
        default_max_tokens=ANSWER_TOKENS,
        emits_inline_reasoning=False,
        supports_json_schema=True,
        catalog_type="text2text",
        catalog_use_cases=("text",),
        catalog_license="not stated here",
        region_informational="this computer",
        answering=MappingProxyType(
            {AnsweringMechanism.JSON_SCHEMA: f"{CHECK_RECORD_PREFIX}{model.digest}"}
        ),
        served_as=model.tag,
        served_with_reasoning_off=model.reasons,
    )


def with_runner_models(manifest: Manifest, specs: Iterable[ModelSpec]) -> Manifest:
    """``manifest`` with a runner's checked models beside its own models, never in place of one."""
    added = {spec.model_id: spec for spec in specs}
    if added.keys() & manifest.models.keys() or any(
        spec.served_as is None for spec in added.values()
    ):
        raise ValueError("a runner's models are added beside the manifest's, never in its place")
    return replace(manifest, models={**manifest.models, **added})


def able_specs(
    manifest: Manifest, catalog: Any, checks: LocalChecks, only: Iterable[str] | None = None
) -> tuple[ModelSpec, ...]:
    """Every model the runner serves now, beside the manifest's own, whose kept check finds it
    able: each asked by the name the runner serves its weights by now, so a model whose weights no
    name serves is not offered. One with no current check is queued and not yet offered. ``only``
    names the models asked about, where a caller asks about some (the ones a minute chose), so no
    other is queued.
    """
    provider = checks.provider.provider_id
    shipped = [key for key, spec in manifest.models.items() if spec.provider == provider]
    wanted = None if only is None else frozenset(only)
    found = []
    for model in ordered(runner_models(catalog), shipped):
        if wanted is not None and model.model_id not in wanted:
            continue
        record = checks.record(model)
        if record is not None and record["able"]:
            found.append(runner_spec(model, record, provider=provider))
    return tuple(found)


def runner_rows(manifest: Manifest, catalog: Any, checks: LocalChecks) -> list[dict[str, Any]]:
    """Every model the runner serves now beside the manifest's own, as a person's list shows it:
    its name, family and size, the name the runner serves it by, the licence the runner states,
    and whether it is able, being checked, or not able and why, with the numbers a reason is told
    by. A model with no current check is queued.
    """
    provider = checks.provider.provider_id
    shipped = [key for key, spec in manifest.models.items() if spec.provider == provider]
    rows = []
    for model in ordered(runner_models(catalog), shipped):
        state, reason = checks.state(model)
        record = checks.kept(model.model_id) if state != "checking" else None
        rows.append(
            {
                "provider": provider,
                "model_id": model.model_id,
                "name": runner_name(model),
                "family": model.family,
                "size": model.parameter_size,
                "served_as": model.tag,
                "licence": None if record is None else record.get("licence"),
                "state": state,
                "reason": reason,
                # The numbers a reason is told by: what it reads at once, and a person's deadline.
                "context_tokens": None if record is None else record.get("context_tokens"),
                "deadline_ms": None if record is None else record.get("deadline_ms"),
                "checked_ms": checked_ms(record),
            }
        )
    return rows
