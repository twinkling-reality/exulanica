"""One decision path for every role: requests, receipts, their checks and the minute loop.

Whatever a role decides for, the path is the same, parameterised by the role's registry entry and
adapter (:mod:`exulanica.world.decision_roles`):

*   **A request** is sealed over the subject's options in one state and input: the options the
    adapter reads from the engine's state, those the ask may send (``offer``), and the observation
    the adapter builds from them, bounded by the contract's ``context_bytes_maximum``. Fewer than
    :data:`~exulanica.world.decision_roles.FEWEST_OPTIONS` options, or nothing but the role's idle
    action, asks nothing. The request records the role's own profile, so its bytes say which role
    asked and a stored request of any role is read by the role that wrote it.
*   **A receipt** records the answer, bound to its request: one of the options it offered, exactly,
    or none with a reason the role records, and the call in the stated fields.
*   **What a minute does with receipts** is each hosted role's adapter's to say, in turn over the
    engine's seam (:func:`apply_receipts`), and every receipt it consumed appends its events.
*   **A run of minutes** asks through an :class:`Asking` port, and :func:`replay_minutes` answers
    from what a run stored, with no client at all, holding every rebuilt request and receipt to
    the stored bytes and every minute's state to its recorded digest. A run stopped part way goes
    on with :func:`resume_minutes`: the minutes it stored are answered from what it stored, as a
    replay answers them, and only the minutes after them are asked.

The model is asked elsewhere, through one hosted call path (:mod:`exulanica.api.decision_host`).
Nothing here reads or writes a database.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Callable, Container, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from exulanica.canonical import canonical_json
from exulanica.models.manifest import AnsweringMechanism
from exulanica.things.lines import LineRefused, check_line, names_listener
from exulanica.world.deciders import (
    EXTERNAL_REASONS,
    PERSON_REASONS,
    DeciderRefused,
    check_external_config,
    check_external_record,
    check_person_config,
    check_person_record,
    is_external,
    is_person_ask,
)
from exulanica.world.decision_roles import (
    FEWEST_OPTIONS,
    DecisionContract,
    DecisionRole,
    RoleOption,
)
from exulanica.world.society import holding_states, society_state_sha256
from exulanica.world.society_planner import input_sha256

__all__ = [
    "ANSWER_BY",
    "ANSWER_WITH_LINE_BY",
    "PROVIDER_CONFIG",
    "PROVIDER_RECORD",
    "RECEIPT_STATUSES",
    "REQUEST_FIELDS",
    "RESULT_BYTES",
    "Asking",
    "DecisionDisposition",
    "Finish",
    "PlayedMinutes",
    "ReplayMismatch",
    "append_role_events",
    "apply_receipts",
    "check_envelope",
    "check_role_request",
    "check_role_result",
    "consumed_receipts",
    "context_bytes",
    "names_its_listener",
    "play_minutes",
    "replay_minutes",
    "resume_minutes",
    "role_receipt",
    "role_request",
    "seal",
    "sealed_receipt",
    "stored_through",
    "validate_role_receipt",
    "validate_role_request",
    "written_messages",
]

#: Every field a decision request states, whatever its profile.
REQUEST_FIELDS: Final = frozenset(
    {
        "profile",
        "request_id",
        "subject_id",
        "branch_id",
        "base_tick",
        "base_state_sha256",
        "input_seq",
        "input_sha256",
        "context",
        "context_sha256",
        "provider_config",
        "document_sha256",
    }
)
#: The request fields a receipt restates, so it is bound to the state and input it was asked over.
_BOUND_FIELDS: Final = (
    "subject_id",
    "branch_id",
    "base_tick",
    "base_state_sha256",
    "input_seq",
    "input_sha256",
    "context_sha256",
)
#: How a receipt may end: an answer, a refusal, no answer, or an answer over another state.
RECEIPT_STATUSES: Final = ("accepted", "rejected", "unavailable", "stale")
#: The most a request's canonical JSON may hold, and a receipt's result. Declared ceilings, not
#: measurements: both came with the first recorded society decisions, the social society's
#: (migration 0055), and no derivation of either figure is recorded. A request holds a context the
#: decision policy bounds by ``context_bytes_maximum`` (12,000 bytes in
#: ``society-decision-policy.v2.json``); the result bound keeps provider metadata bounded without
#: admitting arbitrary output.
_REQUEST_BYTES: Final = 70_000
RESULT_BYTES: Final = 16_000
#: What a request records about the model it asked: which, how, under which contract. A request
#: that asked an outside program records :data:`~exulanica.world.deciders.EXTERNAL_CONFIG` in the
#: same field instead, which names its kind; a model's never does, so every stored one reads as it
#: was written.
PROVIDER_CONFIG: Final = frozenset(
    {
        "provider",
        "model_id",
        "mechanism",
        "choice_seq",
        "manifest_sha256",
        "prompt_version",
        "contract",
        "deadline_ms",
    }
)
#: What a receipt records about the call: the model, how it was asked, every attempt it paid for
#: in the execution record's words, what it cost and how long it took. An outside program's answer
#: records :data:`~exulanica.world.deciders.EXTERNAL_RECORD` in the same field instead.
PROVIDER_RECORD: Final = frozenset(
    {
        "provider",
        "model_id",
        "served_model_id",
        "mechanism",
        "prompt_version",
        "messages_sha256",
        "answers_asked",
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        "cost_known",
        "latency_ms",
    }
)
#: How a model is told to answer, by the mechanism it is asked by: fixed product text naming the
#: fixed function and argument every choice is asked by (``exulanica.models.choice``).
ANSWER_BY: Final = {
    AnsweringMechanism.TOOL_CALL: "Choose one by calling act.",
    AnsweringMechanism.JSON_SCHEMA: 'Answer with a JSON object whose "action" is one of them.',
}
#: How a model is told to answer a choice that takes a line, naming its second fixed argument.
ANSWER_WITH_LINE_BY: Final = {
    AnsweringMechanism.TOOL_CALL: (
        "Choose one by calling act, with the line it says as line when it says something, "
        "and null as line otherwise."
    ),
    AnsweringMechanism.JSON_SCHEMA: (
        'Answer with a JSON object whose "action" is one of them and whose "line" is the line '
        "it says when it says something, and null otherwise."
    ),
}


@dataclass(frozen=True, slots=True)
class DecisionDisposition:
    """What one receipt did to one minute, and why."""

    decision_seq: int
    request_id: str
    subject_id: str
    disposition: str
    reason: str
    decision_sha256: str


class ReplayMismatch(ValueError):
    """A stored run does not replay to what it recorded."""

    code: Final = "run_replay_mismatch"

    def __init__(self, detail: str, *, minute: int | None = None) -> None:
        where = "" if minute is None else f" at minute {minute}"
        super().__init__(f"run_replay_mismatch{where}: {detail}")
        self.minute = minute


def seal(document: dict) -> dict:
    document["document_sha256"] = input_sha256(document)
    return document


def context_bytes(context: Mapping[str, Any]) -> int:
    return len(canonical_json(dict(context)))


def check_envelope(document: Mapping[str, Any], profiles: Container[str]) -> None:
    """A sealed request of one of ``profiles``: exactly its fields, its digests its own, bounded."""
    if (
        set(document) != REQUEST_FIELDS
        or document["profile"] not in profiles
        or input_sha256(dict(document)) != document["document_sha256"]
        or society_state_sha256(document["context"]) != document["context_sha256"]
        or len(canonical_json(dict(document))) > _REQUEST_BYTES
    ):
        raise ValueError("invalid recorded decision request")


def sealed_receipt(
    profile: str, request: Mapping[str, Any], sequence: int, result: Mapping[str, Any]
) -> dict:
    """A receipt of ``profile`` for ``request``: its answer, bound to what it was asked over."""
    return seal(
        {
            "profile": profile,
            "decision_seq": sequence,
            "request_id": request["request_id"],
            "request_sha256": request["document_sha256"],
            **{key: request[key] for key in _BOUND_FIELDS},
            **{key: result[key] for key in ("status", "reason", "proposal", "provider")},
        }
    )


def validate_role_request(role: DecisionRole, document: Mapping[str, Any]) -> None:
    """A stored or rebuilt request of ``role``, held to the envelope and the role's own parts."""
    check_envelope(document, (role.request_profile,))
    check_role_request(role, document)


def role_receipt(
    role: DecisionRole, request: Mapping[str, Any], sequence: int, result: Mapping[str, Any]
) -> dict:
    validate_role_request(role, request)
    return sealed_receipt(role.receipt_profile, request, sequence, result)


def validate_role_receipt(
    role: DecisionRole, document: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    """A receipt of ``role`` for ``request``: a stated status, one of the options it offered or
    none for a reason the role records, and exactly the receipt its request and result make."""
    result = {key: document[key] for key in ("status", "reason", "proposal", "provider")}
    if result["status"] not in RECEIPT_STATUSES:
        raise ValueError("invalid decision status")
    check_role_result(role, result, request)
    if dict(document) != role_receipt(role, request, document["decision_seq"], result):
        raise ValueError("decision receipt request binding mismatch")
    # Provider metadata stays serializable and bounded without admitting arbitrary output.
    if len(json.dumps(result)) > RESULT_BYTES:
        raise ValueError("decision result exceeds bound")


def written_messages(
    role: DecisionRole,
    situation: Sequence[str],
    context: Mapping[str, Any],
    mechanism: AnsweringMechanism,
) -> list[dict[str, str]]:
    """The instruction of the terms the request is asked under, then the subject's situation,
    their options and how to answer: with a line, where an option says something."""
    lines = [
        *situation,
        "What you can do now:",
        *(f"- {option['label']}" for option in context["options"]),
        (ANSWER_WITH_LINE_BY if role.takes_line(context) else ANSWER_BY)[mechanism],
    ]
    return [
        {"role": "system", "content": role.terms_of(context).instruction},
        {"role": "user", "content": "\n".join(lines)},
    ]


def role_request(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    *,
    request_id: uuid.UUID,
    contract: DecisionContract,
    seed: str,
    provider_config: Mapping[str, Any],
    offer: Callable[[Sequence[RoleOption]], Sequence[RoleOption]] | None = None,
    withhold: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    options: Sequence[RoleOption] | None = None,
) -> tuple[dict | None, str]:
    """A subject's sealed request over the options they have in ``state``, asked over ``source``.

    Pure: the host's reservation and a run of minutes build a request here, and so does a replay,
    which rebuilds it to the byte. ``offer`` keeps the options that may be offered, in their order.
    ``withhold`` takes out of the observation what the one asked may not be shown (an outside
    program is never shown a heard line carrying a saved name), before it is sealed. ``(None,
    "nothing_to_choose")`` when fewer than the fewest options are left or nothing but the role's
    idle action, and ``(None, "context_limit_exceeded")`` when the observation is larger than the
    contract's bound; otherwise the request and ``"in_progress"``. ``options``, where given, are
    the subject's options in ``state`` as the role's adapter built them for these same arguments,
    so a run of minutes that built them to ask what may be offered builds them once.
    """
    if options is None:
        options = role.adapter.options(role, state, source, subject_id, contract, seed=seed)
    if offer is not None and options:
        options = tuple(offer(options))
    if len(options) < FEWEST_OPTIONS or all(
        option.kind == role.adapter.IDLE_KIND for option in options
    ):
        return None, "nothing_to_choose"
    context = role.adapter.context(role, state, source, subject_id, options)
    if withhold is not None:
        context = withhold(context)
    if context_bytes(context) > contract.value("context_bytes_maximum"):
        return None, "context_limit_exceeded"
    request = seal(
        {
            "profile": role.request_profile,
            "request_id": str(request_id),
            "subject_id": subject_id,
            "branch_id": state["branch_id"],
            "base_tick": state["tick"],
            "base_state_sha256": society_state_sha256(state),
            "input_seq": source["input_seq"],
            "input_sha256": source["document_sha256"],
            "context": context,
            "context_sha256": society_state_sha256(context),
            "provider_config": dict(provider_config),
        }
    )
    validate_role_request(role, request)
    return request, "in_progress"


def check_role_request(role: DecisionRole, document: Mapping[str, Any]) -> None:
    """The role's parts of a request: its observation, its options and the model it asked."""
    context = document["context"]
    config = document["provider_config"]
    if (
        not isinstance(context, dict)
        or context.get("profile") != role.context_profile
        or context.get("subject_id") != document["subject_id"]
        or context.get("branch_id") != document["branch_id"]
        or context.get("tick") != document["base_tick"]
        or not isinstance(context.get("options"), list)
        or len(context["options"]) < FEWEST_OPTIONS
    ):
        raise ValueError(f"invalid {role.key} decision context")
    labels = [role.adapter.option_from_record(option).label for option in context["options"]]
    if len(set(labels)) != len(labels):
        raise ValueError(f"a {role.key} decision offers each label once")
    if is_external(config):
        try:
            check_external_config(config)
        except DeciderRefused as exc:
            raise ValueError(
                f"a {role.key} decision request names the program it asked: {exc}"
            ) from exc
    elif is_person_ask(config):
        try:
            check_person_config(config)
        except DeciderRefused as exc:
            raise ValueError(
                f"a {role.key} decision request names the person playing: {exc}"
            ) from exc
    elif not isinstance(config, dict) or set(config) != PROVIDER_CONFIG:
        raise ValueError(f"a {role.key} decision request names the model it asked, and how")


def names_its_listener(
    role: DecisionRole, request: Mapping[str, Any], option: Mapping[str, Any], line: str
) -> bool:
    """Whether a model's ``line`` for ``option`` breaks the rule its request's terms hold lines
    to: under terms that state ``names_no_listener`` (found by the prompt version the request
    records), a line said to one being ends with that being's name or description, as the option's
    words name them (:func:`~exulanica.things.lines.names_listener`). An outside program's line,
    and one asked under terms that state no such rule, an earlier prompt's among them, never does.
    """
    config = request["provider_config"]
    if is_external(config) or is_person_ask(config):
        return False
    terms = role.terms_with_prompt(config.get("prompt_version"))
    listener_of = getattr(role.adapter, "line_listener", None)
    if terms is None or "names_no_listener" not in terms.line_rules or listener_of is None:
        return False
    listener = listener_of(option, role.contract(config["contract"]["catalog_versions"]))
    return listener is not None and names_listener(line, listener)


def check_role_result(
    role: DecisionRole, result: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    """An answer names one of the options its request offered, exactly, or none, for a reason the
    role records; and the call in the stated fields."""
    if result["reason"] not in role.reasons:
        raise ValueError(f"a {role.key} decision records no reason {result['reason']!r}")
    proposal = result["proposal"]
    if proposal is not None:
        offered = request["context"]["options"]
        option = proposal.get("option")
        takes_line = isinstance(option, Mapping) and option.get("kind") in getattr(
            role.adapter, "LINE_KINDS", frozenset()
        )
        # A walk to a spot a person chose names the node the decision host took for it.
        takes_point = isinstance(option, Mapping) and option.get("kind") in getattr(
            role.adapter, "POINT_KINDS", frozenset()
        )
        fields = {"label", "option"} | ({"line"} if takes_line else set())
        fields |= {"node_id"} if takes_point else set()
        if set(proposal) != fields or option not in offered or proposal["label"] != option["label"]:
            raise ValueError(f"a {role.key} decision proposes one of the options it offered")
        if takes_point and not (isinstance(proposal["node_id"], str) and proposal["node_id"]):
            raise ValueError(f"a {role.key} decision's walk names the node it walks to")
        if takes_line:
            # The line an option says, held to the line rule at the bound its request states.
            try:
                checked = check_line(
                    proposal["line"], maximum=request["context"]["line_characters_maximum"]
                )
            except LineRefused as exc:
                raise ValueError(f"a {role.key} decision's line breaks the line rule") from exc
            if checked != proposal["line"]:
                raise ValueError(f"a {role.key} decision states its line as the line rule reads it")
            if names_its_listener(role, request, option, checked):
                raise ValueError(
                    f"a {role.key} decision's line names or describes the one it is said to"
                )
    if (result["status"] == "accepted") != (proposal is not None):
        raise ValueError(f"exactly an accepted {role.key} decision carries a proposal")
    provider = result["provider"]
    if is_person_ask(request["provider_config"]):
        # A person playing the being answers: their answer, or, where they posted none, the idle
        # option, recorded in its own fields with no account and no cost. A minute that could not
        # take it records why, as for any decider.
        if provider is None:
            if result["status"] == "accepted":
                raise ValueError(f"an accepted {role.key} decision records the person's answer")
            return
        try:
            check_person_record(provider)
        except DeciderRefused as exc:
            raise ValueError(f"a {role.key} decision records the person's answer: {exc}") from exc
        if result["status"] == "accepted" and (result["reason"] in PERSON_REASONS) != (
            provider["answer_sha256"] is None
        ):
            raise ValueError(
                f"a {role.key} decision for a played being takes the person's answer, or carries on"
            )
        return
    if is_external(request["provider_config"]):
        if provider is None:
            # A request an outside program never answered ends for a reason only an outside ask
            # gives, so its receipt, and the event its minute writes, say who was asked; and an
            # accepted answer always carries the program's record.
            if result["status"] == "accepted" or result["reason"] not in EXTERNAL_REASONS:
                raise ValueError(
                    f"a {role.key} decision an outside program did not answer ends for an outside "
                    "reason"
                )
            return
        # Whoever a request asked is whoever its receipt names as answering: an outside program's
        # answer is recorded as one, in its own fields, and never as a model's call.
        try:
            check_external_record(provider)
        except DeciderRefused as exc:
            raise ValueError(f"a {role.key} decision records the program's answer: {exc}") from exc
        if any(
            provider[key] != request["provider_config"][key]
            for key in ("bridge", "grant_id", "grant_seq", "mapping_sha256")
        ):
            raise ValueError(f"a {role.key} decision's answer came from the program it asked")
    elif provider is not None and (
        not isinstance(provider, dict) or set(provider) != PROVIDER_RECORD
    ):
        raise ValueError(f"a {role.key} decision records its call in the stated fields")


def _by_role(
    roles: Sequence[DecisionRole], receipts: Sequence[Mapping[str, Any]]
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {role.key: [] for role in roles}
    by_profile = {role.receipt_profile: role.key for role in roles}
    for receipt in receipts:
        key = by_profile.get(receipt.get("profile"))  # type: ignore[arg-type]
        if key is None:
            raise ValueError(
                f"a receipt of profile {receipt.get('profile')!r} is not one this engine's roles "
                "record"
            )
        grouped[key].append(receipt)
    return grouped


def apply_receipts(
    roles: Sequence[DecisionRole],
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    seam: Any,
) -> tuple[Any, tuple[Any, ...]]:
    """The engine's seam for the minute after every role applied its receipts, and what each
    receipt did, in decision order.

    Each role, in key order, takes its own receipts in decision order and the seam the roles
    before it left; a receipt of no role the engine hosts is refused by name.
    """
    grouped = _by_role(roles, receipts)
    dispositions: list[Any] = []
    for role in roles:
        seam, done = role.adapter.apply(role, state, source, grouped[role.key], seam)
        dispositions.extend(done)
    return seam, tuple(sorted(dispositions, key=lambda disposition: disposition.decision_seq))


def consumed_receipts(
    receipts: Sequence[Mapping[str, Any]], dispositions: Sequence[Any]
) -> list[tuple[Mapping[str, Any], Any]]:
    """Each receipt a minute consumed with what the minute did with it, in decision order: what an
    engine's own phase after the roles' (a society of things' lines, leaving and hands) reads."""
    by_request = {str(disposition.request_id): disposition for disposition in dispositions}
    return [
        (receipt, by_request[str(receipt["request_id"])])
        for receipt in receipts
        if str(receipt["request_id"]) in by_request
    ]


def append_role_events(
    roles: Sequence[DecisionRole],
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    dispositions: Sequence[Any],
    events: tuple[Any, ...],
) -> tuple[Any, ...]:
    """The minute's events with each role's events for the receipts it consumed appended, role by
    role in key order."""
    grouped = _by_role(roles, receipts)
    by_sequence = {disposition.decision_seq: disposition for disposition in dispositions}
    for role in roles:
        own = grouped[role.key]
        events = role.adapter.events(
            role,
            previous_state,
            next_state,
            source,
            own,
            [by_sequence[receipt["decision_seq"]] for receipt in own],
            events,
        )
    return events


class Asking(Protocol):
    """What a run of minutes asks of the world outside it, minute by minute."""

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[RoleOption]]
    ) -> Mapping[str, frozenset[str]]:
        """For each subject due at ``tick``, with the options they have, the labels that may be
        offered to them. Asked once a minute, for every subject due in it."""
        ...

    def answers(self, requests: Sequence[dict[str, Any]]) -> Sequence[dict[str, Any]]:
        """One result per request, in the same order: ``{status, reason, proposal, provider}``,
        as a receipt records it."""
        ...


#: How an engine advances one minute: from a state, its seed, the inputs the minute consumes and
#: the seam the roles left, to the next state and the minute's events.
Step = Callable[[Mapping[str, Any], str, list[Mapping[str, Any]], Any], tuple[Any, tuple[Any, ...]]]
#: An engine's phase after the roles' events: from the state a minute began in, the state and
#: events so far, the input it consumed last and the receipts it consumed with what it did with
#: each (:func:`consumed_receipts`), the minute's state and events.
Finish = Callable[
    [
        Mapping[str, Any],
        Any,
        Mapping[str, Any],
        tuple[Any, ...],
        list[tuple[Mapping[str, Any], Any]],
    ],
    tuple[Any, tuple[Any, ...]],
]


@dataclass(slots=True)
class PlayedMinutes:
    """What a run did: every minute's state after it, its events, requests and receipts, and how
    many minutes each subject began at a choice point. ``digests`` are the states' digests, each
    taken when its minute ended, which the run never changes after."""

    states: list[dict[str, Any]] = field(default_factory=list)
    events: list[Any] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    choice_points: Counter[str] = field(default_factory=Counter)
    digests: list[str] = field(default_factory=list)

    @property
    def minute_digests(self) -> list[str]:
        if len(self.digests) == len(self.states):
            return list(self.digests)
        return [society_state_sha256(state) for state in self.states]


def _only(labels: frozenset[str]) -> Callable[[Sequence[RoleOption]], list[RoleOption]]:
    def offered(options: Sequence[RoleOption]) -> list[RoleOption]:
        return [option for option in options if option.label in labels]

    return offered


def play_minutes(
    roles: Sequence[DecisionRole],
    role: DecisionRole,
    *,
    start: dict[str, Any],
    sources: Sequence[Mapping[str, Any]],
    seed: str,
    ticks: int,
    step: Step,
    config_for: Callable[[str], Mapping[str, Any] | None],
    request_id_for: Callable[[str, int], uuid.UUID],
    asking: Asking,
    seam: Callable[[Mapping[str, Any], Sequence[str]], Any],
    contract: DecisionContract | None = None,
    on_minute: Callable[[int, Sequence[dict[str, Any]], Sequence[dict[str, Any]]], None]
    | None = None,
    first_sequence: int = 0,
    finish: Finish | None = None,
) -> PlayedMinutes:
    """Play ``ticks`` minutes from ``start``, asking ``asking`` for ``role``'s subjects.

    The minute that leaves the genesis, at tick 0, consumes every input of ``sources``, and every
    later one the last, as a step consumes queued inputs, so a run played on from a later state
    consumes what that minute of the whole run would. Each minute, every subject at a choice point
    for whom ``config_for`` names a model is asked, with the options the ask may offer, and each
    answer is a receipt; the roles an engine hosts (``roles``) then apply the minute's receipts
    over the seam ``seam`` starts from, and ``step`` advances it. ``on_minute(tick, requests,
    receipts)`` is called after each minute's answers are receipted and before the minute
    advances. ``first_sequence`` is the decision sequence of the last receipt recorded before
    ``start``, from which the receipts of minutes played on from a later state are numbered.
    ``finish``, where an engine has a phase after the roles' events (a society of things'), ends
    each minute as the engine's own minute does.

    Each minute's state is digested once, as the minute begins, wherever the minute names it
    (:func:`~exulanica.world.society.holding_states`), and each subject's options are built once
    a minute, for the ask and its request alike.
    """
    with holding_states() as hold:
        return _play_minutes(
            roles,
            role,
            hold,
            start=start,
            sources=sources,
            seed=seed,
            ticks=ticks,
            step=step,
            config_for=config_for,
            request_id_for=request_id_for,
            asking=asking,
            seam=seam,
            contract=contract or role.contract(),
            on_minute=on_minute,
            first_sequence=first_sequence,
            finish=finish,
        )


def _play_minutes(
    roles: Sequence[DecisionRole],
    role: DecisionRole,
    hold: Callable[[Mapping[str, Any]], str],
    *,
    start: dict[str, Any],
    sources: Sequence[Mapping[str, Any]],
    seed: str,
    ticks: int,
    step: Step,
    config_for: Callable[[str], Mapping[str, Any] | None],
    request_id_for: Callable[[str, int], uuid.UUID],
    asking: Asking,
    seam: Callable[[Mapping[str, Any], Sequence[str]], Any],
    contract: DecisionContract,
    on_minute: Callable[[int, Sequence[dict[str, Any]], Sequence[dict[str, Any]]], None] | None,
    first_sequence: int,
    finish: Finish | None,
) -> PlayedMinutes:
    state = start
    played = PlayedMinutes()
    latest = sources[-1]
    sequence = first_sequence
    for _minute in range(ticks):
        hold(state)
        consumed = list(sources) if state["tick"] == 0 else [latest]
        due = [s for s in sorted(role.adapter.subjects(state)) if role.adapter.due(state, s)]
        played.choice_points.update(due)
        asked: dict[str, Sequence[RoleOption]] = {}
        for subject in due:
            if config_for(subject) is None:
                continue
            options = role.adapter.options(role, state, latest, subject, contract, seed=seed)
            if options:
                asked[subject] = options
        kept = asking.offerable(state["tick"], asked) if asked else {}
        requests = []
        for subject in sorted(asked):
            request, _status = role_request(
                role,
                state,
                latest,
                subject,
                request_id=request_id_for(subject, state["tick"]),
                contract=contract,
                seed=seed,
                provider_config=dict(config_for(subject) or {}),
                offer=_only(kept.get(subject, frozenset())),
                options=asked[subject],
            )
            if request is not None:
                requests.append(request)
        results = list(asking.answers(requests)) if requests else []
        if len(results) != len(requests):
            raise ValueError("every request of a minute gets exactly one result")
        receipts = []
        for request, result in zip(requests, results, strict=True):
            sequence += 1
            receipt = role_receipt(role, request, sequence, dict(result))
            validate_role_receipt(role, receipt, request)
            receipts.append(receipt)
        if on_minute is not None:
            on_minute(state["tick"] + 1, requests, receipts)
        applied, decided = apply_receipts(roles, state, latest, receipts, seam(state, due))
        after, events = step(state, seed, consumed, applied)
        events = append_role_events(roles, state, after, latest, receipts, decided, events)
        if finish is not None:
            after, events = finish(
                state, after, latest, events, consumed_receipts(receipts, decided)
            )
        played.states.append(after)
        played.digests.append(hold(after))
        played.events.extend(events)
        played.requests.extend(requests)
        played.receipts.extend(receipts)
        state = after
    return played


@dataclass(frozen=True, slots=True)
class _Stored:
    """Answers from what a run stored: the options each stored request offered, and its receipt."""

    requests: Mapping[tuple[str, int], dict[str, Any]]
    receipts: Mapping[str, dict[str, Any]]
    used: set[str]

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[RoleOption]]
    ) -> dict[str, frozenset[str]]:
        # A subject the run asked was offered exactly the options their stored request records;
        # one it did not ask was offered too few, and is offered none again.
        return {
            subject: frozenset(
                option["label"]
                for option in self.requests.get((subject, tick), {"context": {"options": []}})[
                    "context"
                ]["options"]
            )
            for subject in due
        }

    def answers(self, requests: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for request in requests:
            minute = request["base_tick"] + 1
            stored = self.requests.get((request["subject_id"], request["base_tick"]))
            receipt = self.receipts.get(request["request_id"])
            if stored is None or receipt is None:
                raise ReplayMismatch("a rebuilt request has no stored answer", minute=minute)
            if stored != request or receipt["request_sha256"] != request["document_sha256"]:
                raise ReplayMismatch("a rebuilt request is not the one stored", minute=minute)
            self.used.add(request["request_id"])
            results.append(
                {key: receipt[key] for key in ("status", "reason", "proposal", "provider")}
            )
        return results


def replay_minutes(
    stored: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    minute_digests: Sequence[str],
    play: Callable[[Asking], PlayedMinutes],
) -> PlayedMinutes:
    """Play again from the requests and receipts a run stored, asking nothing, and hold it to its
    record.

    ``stored`` is every request the run recorded with its receipt, in decision order,
    ``minute_digests`` the state digest it recorded after each minute, and ``play`` the run's own
    minutes played with an asking port. A rebuilt request that is not the stored one, a receipt
    that is not rebuilt to the same bytes, a stored receipt no minute asks for, or a minute that
    ends in another state: each is a :class:`ReplayMismatch`.
    """
    requests = {(str(r["subject_id"]), int(r["base_tick"])): dict(r) for r, _ in stored}
    receipts = {str(receipt["request_id"]): dict(receipt) for _, receipt in stored}
    if len(requests) != len(stored) or len(receipts) != len(stored):
        raise ReplayMismatch("a subject is asked twice in one minute, or a request answered twice")
    answering = _Stored(requests, receipts, set())
    played = play(answering)
    if len(played.states) != len(minute_digests):
        raise ReplayMismatch("the run recorded another number of minutes")
    for state, found, recorded in zip(
        played.states, played.minute_digests, minute_digests, strict=True
    ):
        if found != recorded:
            raise ReplayMismatch("the minute ends in another state", minute=int(state["tick"]))
    if [dict(receipt) for _, receipt in stored] != played.receipts:
        raise ReplayMismatch("a stored receipt is not the one its request rebuilds")
    if answering.used != set(receipts):
        raise ReplayMismatch("a stored receipt answers no request the run asks")
    return played


def stored_through(stored: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> int | None:
    """The tick of the last minute whose receipts ``stored`` holds, or None for none: the minute
    a run that stopped had asked and recorded last. A minute's receipts are recorded together, in
    one transaction, so every minute up to it is whole."""
    return max((int(request["base_tick"]) for request, _receipt in stored), default=None)


@dataclass(frozen=True, slots=True)
class _Resumed:
    """Answers a run played on after it stopped: every minute through ``through`` from what it
    stored, every later one from ``live``."""

    stored: _Stored
    live: Asking
    through: int | None

    def _replayed(self, tick: int) -> bool:
        return self.through is not None and tick <= self.through

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[RoleOption]]
    ) -> Mapping[str, frozenset[str]]:
        if self._replayed(tick):
            return self.stored.offerable(tick, due)
        return self.live.offerable(tick, due)

    def answers(self, requests: Sequence[dict[str, Any]]) -> Sequence[dict[str, Any]]:
        ticks = {int(request["base_tick"]) for request in requests}
        if len(ticks) != 1:
            raise ValueError("a minute's requests are asked over one tick")
        if self._replayed(ticks.pop()):
            return self.stored.answers(requests)
        return self.live.answers(requests)


def resume_minutes(
    stored: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    live: Asking,
    play: Callable[[Asking], PlayedMinutes],
) -> PlayedMinutes:
    """Play on from where a run stopped, asking only what it did not record.

    ``stored`` is every request the run recorded with its receipt since the state ``play`` starts
    from, in decision order, and ``play`` the run's minutes from that state, numbering receipts
    from the last one recorded before it. Every minute through the last one ``stored`` answers
    (:func:`stored_through`) is answered from it, as :func:`replay_minutes` answers, each rebuilt
    request held to its stored bytes; every later minute asks ``live``. So nothing the run already
    paid for and recorded is asked again. A rebuilt request that is not the stored one, a stored
    receipt that is not rebuilt to the same bytes or that no minute asks for: each is a
    :class:`ReplayMismatch`, and the run cannot go on under the receipts it holds.
    """
    requests = {(str(r["subject_id"]), int(r["base_tick"])): dict(r) for r, _ in stored}
    receipts = {str(receipt["request_id"]): dict(receipt) for _, receipt in stored}
    if len(requests) != len(stored) or len(receipts) != len(stored):
        raise ReplayMismatch("a subject is asked twice in one minute, or a request answered twice")
    replayed = _Stored(requests, receipts, set())
    played = play(_Resumed(replayed, live, stored_through(stored)))
    if [dict(receipt) for _, receipt in stored] != played.receipts[: len(stored)]:
        raise ReplayMismatch("a stored receipt is not the one its request rebuilds")
    if replayed.used != set(receipts):
        raise ReplayMismatch("a stored receipt answers no request the run asks")
    return played
