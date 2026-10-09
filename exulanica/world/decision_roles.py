"""Roles as data: each kind of thing in a world that a chosen open model may decide for.

A decision role is a part of a world that changes and chooses at choice points of its own: a person
deciding what to do next is the first. A world's owner may hand a role's choices, for one of its
subjects or a group, to an open model the manifest offers it; with no choice nothing is asked and
the world's own rules decide. A role's contract is data and one adapter module; hosting a role
in a world also takes the engine, route, panel and comparison work that
``docs/decision-roles-contract.md`` lists:

*   **Its registry entry** in ``assets/catalogs/roles/decision-roles.v<N>.json``, with a licence
    and a reason like every catalog entry, states what the role decides for, the engines that host
    it, the use cases a model must declare to be offered it, the catalogs of its contract (its
    action vocabulary with its words, and the bounds on asking) and the versions a new request
    records, from which policy version a model is asked in its own measured answering order, the
    profiles of its request, receipt, choice and context documents, its prompt version and prompt
    texts, and the name of its adapter module. From registry version 5 an entry may also state, for
    an engine that hosts it, that engine's own terms: the catalog versions its new requests record
    and the prompt they are asked with, so one engine's people can be asked new questions while
    every other engine's are asked exactly as before. A new role is a new registry version beside
    the last, and the loader reads the newest: nothing stored records the registry's version, since
    a request records its role's own profile and contract, and its context the engine it was asked
    under.
*   **Its adapter module**, ``exulanica.world.roles.<name>`` and nowhere else, is the code only
    the role can have: which subjects it may decide for and which are at a choice point, the options
    the engine's state offers each and the fields its words fill, the observation a model reads and
    its wording, an option's record, and how the engine re-checks, promises and applies a validated
    choice through its seam, with the reasons it records. It declares the one role key it serves.
    The package is fixed in code; an entry names only a module in it, by a key, so catalog data
    never chooses an import path.

What this module does not do: ask a model, store anything or run a minute. The one generic path
that does takes a role from here (:mod:`exulanica.world.role_decisions`,
:mod:`exulanica.api.decision_host`). The model layer knows no role: a role's model requirements
reach it as a :class:`~exulanica.models.manifest.ChosenRoleBinding` built here.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache, partial
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Protocol

from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    FieldValue,
    catalog_digest,
    integer_field,
    key_list_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.documents import split_versioned_name
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.records import KEY_PATTERN
from exulanica.models.choice import ChoiceRequest
from exulanica.models.manifest import AnsweringMechanism, ChosenRoleBinding, ModelSpec
from exulanica.things.lines import LINE_RULES
from exulanica.world.role_catalogs import role_action_schema, role_policy_schema
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_engines import ENGINES

__all__ = [
    "ADAPTER_PACKAGE",
    "CHOICE_SUBJECT_FIELDS",
    "FEWEST_OPTIONS",
    "GENERIC_REASONS",
    "POLICY_KEYS",
    "PROFILE_PATTERNS",
    "REGISTRY_CATALOG",
    "REGISTRY_DIRECTORY",
    "ContractError",
    "DecisionContract",
    "DecisionRole",
    "RoleAdapter",
    "RoleOption",
    "RoleRefused",
    "RoleRegistry",
    "RoleTerms",
    "decision_roles",
    "load_decision_roles",
]

_ROOT: Final = Path(__file__).resolve().parents[2]
REGISTRY_CATALOG: Final = "decision-roles"
REGISTRY_DIRECTORY: Final = _ROOT / "assets" / "catalogs" / "roles"
#: The one package a production registry's adapters are imported from.
ADAPTER_PACKAGE: Final = "exulanica.world.roles"
#: The fewest options a subject is asked to choose among: the role's idle action and one thing
#: more. With fewer, or with nothing but the idle action, nobody is asked and the world decides.
FEWEST_OPTIONS: Final = 2
#: Every bound the generic path reads from a role's policy catalog, compared for exact equality
#: with the catalog's own keys together with the role's ``subjects_bound``: a key added to the
#: catalog and a key removed from it are both refused.
POLICY_KEYS: Final = frozenset(
    {
        "answer_attempts_maximum",
        "concurrent_calls_maximum",
        "context_bytes_maximum",
        "decision_deadline_ms",
        "decisions_per_world_hour_maximum",
        "options_maximum",
        "process_reserve_percent",
        "spend_per_world_hour_microusd",
        *(f"answer_rank_{mechanism.value}" for mechanism in AnsweringMechanism),
    }
)
#: The bounds that are at least one: a role that allows no answer, no call, no bytes, no time or no
#: subject asks nothing, which is stated by not being chosen rather than by a zero.
_AT_LEAST_ONE: Final = (
    "answer_attempts_maximum",
    "concurrent_calls_maximum",
    "context_bytes_maximum",
    "decision_deadline_ms",
    "options_maximum",
)
#: Every reason the generic path records on a receipt, or a minute on a consumed one, by code. A
#: role's adapter adds the reasons only its own checks give; the two sets never share a code.
GENERIC_REASONS: Final = frozenset(
    {
        # The model answered with one of the options, and it held when the minute ran.
        "validated_choice",
        # The model answered, but never with an offered option, as often as the policy allows.
        "answer_not_offered",
        # The line a chosen option says breaks the line rule, or the workspace's rules would
        # change it: it is not said, and the routine decides that turn.
        "line_out_of_bounds",
        "line_refused_by_rules",
        # The call itself.
        "model_timed_out",
        "model_call_failed",
        "model_unavailable",
        "request_refused",
        "provider_not_admitted",
        "provider_credential_absent",
        # The bounds, checked before a model is asked.
        "model_no_longer_offered",
        "world_hour_decisions_spent",
        "world_hour_spend_spent",
        "process_budget_spent",
        "process_share_spent",
        # The durable spending authority refused the ask before anything was sent, by its own
        # reason (exulanica.models.spending.SPENDING_REFUSALS): the workspace holds no live
        # allowance, it was revoked or has expired, a ceiling would be crossed, the authority is
        # held closed until an operator acts, it could not be asked, or the host's client was
        # composed without the workspace's spending.
        "spending_not_granted",
        "spending_revoked",
        "spending_expired",
        "spending_limit_reached",
        "spending_suspended",
        "spending_unavailable",
        "spending_scope_missing",
        # The minute left no time to ask before the playback lease ran out.
        "no_time_to_ask",
        # A host that stopped between reserving a request and recording its answer: the next
        # host minute closes the request by this name.
        "unanswered_in_its_minute",
        # When the answer is recorded.
        "decision_context_changed",
        "decision_sources_unavailable",
        "provider_configuration_changed",
        # When the minute consumes it: a second receipt for a subject already decided.
        "subject_already_decided",
        # An outside program asked for a subject under its grant gave no usable answer: its door
        # had no live connection, it did not answer by the deadline, the grant was revoked or had
        # expired, or nobody was there to act for the subject, so it passed and the routine
        # decides at once (exulanica.world.deciders.EXTERNAL_REASONS); or it was not asked, since
        # a name the account holder saved is among the words its request would send.
        "decider_disconnected",
        "no_answer_in_time",
        "grant_revoked",
        "grant_expired",
        "decider_passed",
        "saved_name_withheld",
        # A person playing the subject posted no answer for the minute, so it carried on, or waited
        # at a choice point: never the routine, never a model.
        "person_no_answer",
    }
)
#: The shape of each profile a role's documents carry, the shapes migration 0117 admits by the
#: same expressions (a parity test holds the two spellings together).
PROFILE_PATTERNS: Final = {
    "request_profile": r"exulanica\.[a-z][a-z0-9-]*-decision-request/v[1-9][0-9]{0,5}",
    "receipt_profile": r"exulanica\.[a-z][a-z0-9-]*-decision/v[1-9][0-9]{0,5}",
    "choice_profile": r"exulanica\.[a-z][a-z0-9-]*-model-choice/v[1-9][0-9]{0,5}",
    "context_profile": r"exulanica\.[a-z][a-z0-9-]*-context/v[1-9][0-9]{0,5}",
}
#: The fields a model choice may name its subjects under, the ones migration 0117 admits: the
#: person's first choices named them people, and a role's choices name them subjects.
CHOICE_SUBJECT_FIELDS: Final = ("people", "subjects")
_CATALOG_ID: Final = re.compile(r"[a-z][a-z0-9-]*")
_PROMPT_VERSION: Final = re.compile(r"[a-z][a-z0-9-]*/v[1-9][0-9]{0,5}")
#: Prompt text is instruction written for a model: printable ASCII, one line, bounded.
_PROMPT_TEXT: Final = re.compile(r"[ -~]{1,2000}")
#: A profile's version as every profile pattern spells it: a whole number with no leading zero.
_VERSION_TEXT: Final = re.compile(r"[1-9][0-9]{0,5}")
_PLACEHOLDER: Final = re.compile(r"\{([a-z_]+)\}")
#: The code an adapter module must hold, each by the name the generic path calls it by.
_ADAPTER_NAMES: Final = (
    "ROLE",
    "KINDS",
    "IDLE_KIND",
    "REASONS",
    "subjects",
    "due",
    "options",
    "context",
    "option_from_record",
    "messages",
    "apply",
    "events",
)


class RoleRefused(ValueError):
    """A registry, a role or an adapter this code will not use, by a code and a sentence."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class ContractError(ValueError):
    """A role's contract catalogs do not state a contract this code can keep."""


class RoleOption(Protocol):
    """One thing a subject may be asked to do: the label a model answers with, its kind, and the
    record a request keeps of it."""

    @property
    def label(self) -> str: ...

    @property
    def kind(self) -> str: ...

    def as_record(self) -> dict[str, Any]: ...


class RoleAdapter(Protocol):
    """The code one role needs and the generic path cannot hold: an ``exulanica.world.roles``
    module, read by the names below."""

    #: The one role key this module serves.
    ROLE: str
    #: Each action kind the adapter can apply, with the placeholders its words may name.
    KINDS: Mapping[str, frozenset[str]]
    #: The kind that changes nothing: offered only beside something else.
    IDLE_KIND: str
    #: The reasons only this role's own checks record.
    REASONS: frozenset[str]

    def subjects(self, state: Mapping[str, Any]) -> Sequence[str]: ...

    def due(self, state: Mapping[str, Any], subject_id: str) -> bool: ...

    def options(
        self,
        role: DecisionRole,
        state: Mapping[str, Any],
        source: Mapping[str, Any],
        subject_id: str,
        contract: DecisionContract,
        *,
        seed: str,
    ) -> tuple[RoleOption, ...]: ...

    def context(
        self,
        role: DecisionRole,
        state: Mapping[str, Any],
        source: Mapping[str, Any],
        subject_id: str,
        options: Sequence[RoleOption],
    ) -> dict[str, Any]: ...

    def option_from_record(self, record: Mapping[str, Any]) -> RoleOption: ...

    def messages(
        self, role: DecisionRole, context: Mapping[str, Any], mechanism: AnsweringMechanism
    ) -> list[dict[str, str]]: ...

    def apply(
        self,
        role: DecisionRole,
        state: Mapping[str, Any],
        source: Mapping[str, Any],
        receipts: Sequence[Mapping[str, Any]],
        seam: Any,
    ) -> tuple[Any, tuple[Any, ...]]: ...

    def events(
        self,
        role: DecisionRole,
        previous_state: Mapping[str, Any],
        next_state: Mapping[str, Any],
        source: Mapping[str, Any],
        receipts: Sequence[Mapping[str, Any]],
        dispositions: Sequence[Any],
        events: tuple[Any, ...],
    ) -> tuple[Any, ...]: ...


@dataclass(frozen=True, slots=True)
class DecisionContract:
    """One version of a role's contract, read from its catalogs."""

    #: Each action kind's words, with the placeholders the adapter fills.
    words: Mapping[str, str]
    #: The action catalog's key for each kind, recorded with an option.
    action_keys: Mapping[str, str]
    policy: Mapping[str, int]
    versions: Mapping[str, int]
    sha256: str
    #: Whether a model is asked in its own measured answering order before the policy's.
    asks_in_a_models_own_order: bool = False
    #: Whether an option this contract states says something, so an answer may carry a line.
    takes_lines: bool = False

    def binding(self) -> dict[str, object]:
        """What a decision request records about the contract it was asked under."""
        return {"catalog_versions": dict(sorted(self.versions.items())), "sha256": self.sha256}

    def value(self, key: str) -> int:
        return self.policy[key]

    @property
    def mechanism_order(self) -> tuple[AnsweringMechanism, ...]:
        """The mechanisms this contract accepts, first preferred first; rank 0 accepts none."""
        ranked = [
            (self.policy[f"answer_rank_{mechanism.value}"], mechanism)
            for mechanism in AnsweringMechanism
            if self.policy[f"answer_rank_{mechanism.value}"] > 0
        ]
        return tuple(mechanism for _, mechanism in sorted(ranked))

    def _own_order(self, spec: ModelSpec) -> list[AnsweringMechanism]:
        """The accepted part of the answering order ``spec``'s entry states, where this contract's
        version asks in a model's own order; empty otherwise."""
        return [
            m
            for m in (spec.answering_order if self.asks_in_a_models_own_order else ())
            if m in self.mechanism_order
        ]

    def answering_order(self, spec: ModelSpec) -> tuple[AnsweringMechanism, ...]:
        """The accepted mechanisms ``spec``'s manifest entry verifies, in the order it is asked
        by: the answering order its entry states when it states one this contract accepts (a
        measured order for that model) and this contract's version asks in it, and otherwise
        this contract's order. Empty: this contract cannot ask it, as for a contract that takes
        lines and a model its entry says is not offered for them."""
        if self.takes_lines and spec.not_offered_for_lines is not None:
            return ()
        return tuple(
            m for m in self._own_order(spec) or self.mechanism_order if m in spec.answering
        )

    def mechanism_for(self, spec: ModelSpec) -> AnsweringMechanism | None:
        """How ``spec`` is asked: the first of its :meth:`answering_order`."""
        return next(iter(self.answering_order(spec)), None)

    def answering(self, spec: ModelSpec) -> dict[str, object] | None:
        """How ``spec`` is asked, as a record states it: the mechanisms in order, the one it is
        asked by, whose order that is (``model``, measured for it, or ``contract``) and the record
        that measured a model's own order. None: this contract cannot ask it."""
        order = self.answering_order(spec)
        if not order:
            return None
        own = bool(self._own_order(spec))
        return {
            "order": [mechanism.value for mechanism in order],
            "mechanism": order[0].value,
            "source": "model" if own else "contract",
            "record": spec.answering_order_record if own else None,
        }


@dataclass(frozen=True, slots=True)
class RoleTerms:
    """What a role's request is asked under: the catalog versions a new request records and the
    prompt it is asked with, its version and its three texts. A role's own terms are its entry's;
    an engine hosting it may state its own."""

    versions: Mapping[str, int]
    prompt_version: str
    #: The one instruction a model is given, sent as written.
    instruction: str
    #: How the one function a model answers by is described, in every request.
    choice_description: str
    #: What a model is told when its answer was not one of the options, before it is asked again.
    not_offered: str
    #: The rules beside the line rule a model's lines are held to under these terms
    #: (:data:`~exulanica.things.lines.LINE_RULES`), from registry version 7: an answer whose line
    #: breaks one is not an answer to the choice, and is asked again.
    line_rules: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DecisionRole:
    """One registered role: its declaration, its adapter and its model requirements."""

    key: str
    #: What it decides for, by the word its subjects are known by.
    subject: str
    #: The society engines whose minutes consume its receipts; none for a role no society engine
    #: hosts.
    engines: tuple[str, ...]
    #: What a model must declare to be offered it, as the model layer reads it.
    chosen: ChosenRoleBinding
    catalog_directory: Path
    action_catalog: str
    policy_catalog: str
    #: The catalog versions a new request records.
    contract_versions: Mapping[str, int]
    #: From this policy version on, a model is asked in its own measured answering order.
    own_order_from_policy_version: int
    #: The policy key bounding how many of its subjects models may run at once.
    subjects_bound: str
    request_profile: str
    receipt_profile: str
    choice_profile: str
    #: The field of a choice document that names the subjects it is for.
    choice_subjects: str
    context_profile: str
    prompt_version: str
    #: The one instruction a model is given, sent as written.
    instruction: str
    #: How the one function a model answers by is described, in every request.
    choice_description: str
    #: What a model is told when its answer was not one of the options, before it is asked again.
    not_offered: str
    adapter: RoleAdapter
    #: The terms an engine hosting the role states for its own requests, by engine; an engine
    #: stating none is asked under the role's own terms.
    engine_terms: Mapping[str, RoleTerms] = field(default_factory=dict)
    _contracts: dict[tuple[tuple[str, int], ...], DecisionContract] = field(
        default_factory=dict, compare=False, hash=False, repr=False
    )

    @property
    def own_terms(self) -> RoleTerms:
        """The terms the role's entry states for every engine that states none of its own."""
        return RoleTerms(
            versions=dict(self.contract_versions),
            prompt_version=self.prompt_version,
            instruction=self.instruction,
            choice_description=self.choice_description,
            not_offered=self.not_offered,
        )

    def terms(self, engine: str | None = None) -> RoleTerms:
        """The terms a request of ``engine`` is asked under: the engine's own where the entry
        states them, the role's otherwise."""
        found = None if engine is None else self.engine_terms.get(engine)
        return self.own_terms if found is None else found

    def terms_of(self, context: Mapping[str, Any]) -> RoleTerms:
        """The terms a request was asked under, by the engine its context names; a context that
        names no engine was asked under the role's own."""
        engine = context.get("engine")
        return self.terms(engine if isinstance(engine, str) else None)

    def every_terms(self) -> tuple[RoleTerms, ...]:
        """The role's own terms, then each engine's, in engine order."""
        return (self.own_terms, *(self.engine_terms[e] for e in sorted(self.engine_terms)))

    def terms_with_prompt(self, prompt_version: object) -> RoleTerms | None:
        """The terms of this registry whose prompt is ``prompt_version``, the one a request
        records; None for a prompt no terms of it state now, one a request was asked under
        before."""
        return next(
            (terms for terms in self.every_terms() if terms.prompt_version == prompt_version), None
        )

    @property
    def reasons(self) -> frozenset[str]:
        """Every reason a receipt of this role, or the minute consuming it, records."""
        return GENERIC_REASONS | self.adapter.REASONS

    def hosted_by(self, engine: str) -> bool:
        return engine in self.engines

    def reads_choice(self, profile: str) -> bool:
        """Whether a choice of ``profile`` is this role's: the profile a new choice records, or an
        earlier version of it, which a role keeps reading after its new choices move on."""
        name, _, newest = self.choice_profile.rpartition("/v")
        stated, _, version = profile.rpartition("/v")
        return (
            stated == name
            and _VERSION_TEXT.fullmatch(version) is not None
            and int(version) <= int(newest)
        )

    def contract_for(self, engine: str | None) -> DecisionContract:
        """The contract a society on ``engine`` asks this role's subjects under: the engine's own
        terms where the entry states them, the role's otherwise (and for no engine)."""
        return self.contract(self.terms(engine).versions)

    def contract(self, versions: Mapping[str, int] | None = None) -> DecisionContract:
        """The contract of these catalog versions; left out, the one a new request records."""
        chosen = dict(self.contract_versions if versions is None else versions)
        key = tuple(sorted((str(k), int(v)) for k, v in chosen.items()))
        if key not in self._contracts:
            self._contracts[key] = _contract(self, chosen)
        return self._contracts[key]

    def idle_label(self, context: Mapping[str, Any]) -> str | None:
        """The label of the option a request offers that changes nothing, of the first of its
        adapter's idle kinds it offers (going on with what is under way, then waiting, for a
        person), or None where it offers none: what an outside program answers for a subject when
        nobody there acts for it, read from the request's own context."""
        kinds = getattr(self.adapter, "IDLE_KINDS", (self.adapter.IDLE_KIND,))
        offered: dict[Any, str] = {}
        for option in context["options"]:
            # The first offered option of each kind, in the request's own order.
            offered.setdefault(option.get("kind"), option["label"])
        return next((offered[kind] for kind in kinds if kind in offered), None)

    def line_labels(self, context: Mapping[str, Any]) -> tuple[str, ...]:
        """The labels of a request's options that say something, in its order, by the kinds the
        adapter states take a line: an answer naming one gives the line it says, and an answer
        naming any other gives none. Read from the request's own context, so a door needs no
        option kind of its own."""
        kinds = getattr(self.adapter, "LINE_KINDS", frozenset())
        return tuple(
            option["label"] for option in context["options"] if option.get("kind") in kinds
        )

    def takes_line(self, context: Mapping[str, Any]) -> bool:
        """Whether a request's options include one that says something: then its choice takes a
        line too, bounded as its context says."""
        return bool(self.line_labels(context))

    def choice(self, context: Mapping[str, Any]) -> ChoiceRequest:
        """The one choice a model answers, built from a request's options and its terms and
        nowhere else: with a line, bounded as its context states, when an option says something."""
        return ChoiceRequest(
            description=self.terms_of(context).choice_description,
            options=tuple(option["label"] for option in context["options"]),
            line_characters_maximum=(
                int(context["line_characters_maximum"]) if self.takes_line(context) else None
            ),
        )


@dataclass(frozen=True)
class RoleRegistry:
    """Every registered role, by key, from one registry version."""

    version: int
    roles: Mapping[str, DecisionRole]

    def __iter__(self) -> Iterator[DecisionRole]:
        return iter(self.roles.values())

    def role(self, key: str) -> DecisionRole:
        try:
            return self.roles[key]
        except KeyError as exc:
            raise RoleRefused(
                "role_not_registered",
                f"no role {key!r} is registered; the registry holds {sorted(self.roles)}",
            ) from exc

    def _by(self, field_name: str, profile: str) -> DecisionRole | None:
        return next((r for r in self if getattr(r, field_name) == profile), None)

    def for_request(self, profile: str) -> DecisionRole | None:
        """The role a request profile names, or None when no registered role writes it."""
        return self._by("request_profile", profile)

    def for_receipt(self, profile: str) -> DecisionRole | None:
        return self._by("receipt_profile", profile)

    def for_choice(self, profile: str) -> DecisionRole | None:
        """The role whose choices ``profile`` records, at the version a new choice records or an
        earlier one; None when no registered role writes it."""
        return next((role for role in self if role.reads_choice(profile)), None)

    def for_contract(self, binding: Mapping[str, Any]) -> DecisionRole:
        """The role a record's contract binding names: the one registered role whose contract,
        at the catalog versions the binding names, is exactly that binding, versions and digest.
        A record names the role it was asked under by the contract it recorded, so no second
        field states it; a binding no role's contract matches, or two roles' do, is refused."""
        versions = binding.get("catalog_versions")
        found = []
        for role in self:
            if not isinstance(versions, Mapping) or set(versions) != {
                role.action_catalog,
                role.policy_catalog,
            }:
                continue
            try:
                held = role.contract(versions).binding()
            except (CatalogError, ContractError):
                continue
            if held == dict(binding):
                found.append(role)
        if len(found) != 1:
            raise RoleRefused(
                "role_not_registered",
                f"{len(found)} registered roles hold the contract this record names",
            )
        return found[0]

    def hosted_by(self, engine: str) -> tuple[DecisionRole, ...]:
        """The roles an engine's minutes consume receipts of, in key order."""
        return tuple(role for role in self if role.hosted_by(engine))

    def deciding_for(self, subject: str) -> DecisionRole:
        """The one registered role deciding for ``subject``, the word its subjects are known by;
        a registry stating none or several is refused by name."""
        found = [role for role in self if role.subject == subject]
        if len(found) != 1:
            raise RoleRefused(
                "role_not_registered",
                f"the registry states {len(found)} roles deciding for a {subject}",
            )
        return found[0]

    @property
    def chosen(self) -> tuple[ChosenRoleBinding, ...]:
        """Every role's model requirements, as the model layer's preflight reads them."""
        return tuple(role.chosen for role in self)


def _key(where: str, value: object) -> FieldValue:
    if type(value) is not str or KEY_PATTERN.fullmatch(value) is None:
        raise CatalogError(f"{where} is a lowercase key, got {value!r}")
    return value


def _matching(pattern: re.Pattern[str], what: str) -> Callable[[str, object], FieldValue]:
    def check(where: str, value: object) -> FieldValue:
        if type(value) is not str or pattern.fullmatch(value) is None:
            raise CatalogError(f"{where} is {what}, got {value!r}")
        return value

    return check


def _choice_subjects(where: str, value: object) -> FieldValue:
    if value not in CHOICE_SUBJECT_FIELDS:
        raise CatalogError(f"{where} is one of {list(CHOICE_SUBJECT_FIELDS)}, got {value!r}")
    return str(value)


def _engines(where: str, value: object) -> FieldValue:
    """The society engines whose minutes consume a role's receipts, each one the engine table
    states; none for a role no society engine hosts, which runs only where its caller brings an
    engine of its own."""
    known = {engine.engine for engine in ENGINES}
    if not isinstance(value, list):
        raise CatalogError(f"{where} is a list of engines")
    for index, item in enumerate(value):
        if item not in known:
            raise CatalogError(f"{where}[{index}] is not an engine the engine table states")
    if len(set(value)) != len(value):
        raise CatalogError(f"{where} names an engine twice")
    return tuple(value)


def _directory(where: str, value: object) -> FieldValue:
    if (
        type(value) is not str
        or not value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
    ):
        raise CatalogError(f"{where} is a directory relative to the repository, got {value!r}")
    if not (_ROOT / value).is_dir():
        raise CatalogError(f"{where} names {value!r}, which is not a directory of the repository")
    return value


def _description(where: str, value: object) -> FieldValue:
    text = _matching(_PROMPT_TEXT, "one line of printable instruction text")(where, value)
    try:
        ChoiceRequest(description=str(text), options=("wait", "go"))
    except ValueError as exc:
        raise CatalogError(f"{where} is not a description a choice may carry: {exc}") from exc
    return text


_VERSION: Final = integer_field(1, 10_000)
#: The registry version from which an entry states each engine's own terms (``engine_terms``).
ENGINE_TERMS_FROM: Final = 5
#: The registry version from which an engine's terms may state the rules their lines are held to
#: beside the line rule (``line_rules``).
LINE_RULES_FROM: Final = 7
_TERM_FIELDS: Final = frozenset(
    {
        "engine",
        "action_version",
        "policy_version",
        "prompt_version",
        "instruction",
        "choice_description",
        "not_offered",
    }
)


def _engine_terms(where: str, value: object, *, line_rules: bool = False) -> FieldValue:
    """The terms each engine states for its own requests: a list of objects, one an engine, each
    naming an engine the engine table states, the two catalog versions its new requests record,
    and its prompt's version and three texts; from :data:`LINE_RULES_FROM` (``line_rules``), also
    the rules its lines are held to, where it states any."""
    if not isinstance(value, list):
        raise CatalogError(f"{where} is a list of an engine's terms")
    known = {engine.engine for engine in ENGINES}
    found: list[dict[str, object]] = []
    for index, item in enumerate(value):
        at = f"{where}[{index}]"
        stated = set(item) - {"line_rules"} if line_rules and isinstance(item, dict) else item
        if not isinstance(item, dict) or set(stated) != _TERM_FIELDS:
            raise CatalogError(f"{at} states exactly {sorted(_TERM_FIELDS)}")
        rules = item.get("line_rules", [])
        if (
            not isinstance(rules, list)
            or ("line_rules" in item and not rules)
            or len(set(rules)) != len(rules)
            or not set(rules) <= LINE_RULES
        ):
            raise CatalogError(f"{at}.line_rules names some of {sorted(LINE_RULES)}, each once")
        if item["engine"] not in known:
            raise CatalogError(f"{at}.engine is not an engine the engine table states")
        found.append(
            {
                "engine": item["engine"],
                "action_version": _VERSION(f"{at}.action_version", item["action_version"]),
                "policy_version": _VERSION(f"{at}.policy_version", item["policy_version"]),
                "prompt_version": _matching(_PROMPT_VERSION, "a prompt version")(
                    f"{at}.prompt_version", item["prompt_version"]
                ),
                "instruction": _matching(_PROMPT_TEXT, "one line of printable instruction text")(
                    f"{at}.instruction", item["instruction"]
                ),
                "choice_description": _description(
                    f"{at}.choice_description", item["choice_description"]
                ),
                "not_offered": _matching(_PROMPT_TEXT, "one line of printable instruction text")(
                    f"{at}.not_offered", item["not_offered"]
                ),
                "line_rules": tuple(sorted(rules)),
            }
        )
    engines = [item["engine"] for item in found]
    if len(set(engines)) != len(engines):
        raise CatalogError(f"{where} states one engine's terms twice")
    return tuple(found)  # type: ignore[arg-type]


def _registry_schema(version: int) -> CatalogSchema:
    return CatalogSchema(
        REGISTRY_CATALOG,
        version,
        (
            ("subject", _key),
            ("adapter", _key),
            ("engines", _engines),
            ("required_use_cases", key_list_field),
            ("catalog_directory", _directory),
            ("action_catalog", _matching(_CATALOG_ID, "a catalog id")),
            ("policy_catalog", _matching(_CATALOG_ID, "a catalog id")),
            ("action_version", _VERSION),
            ("policy_version", _VERSION),
            ("own_order_from_policy_version", _VERSION),
            ("subjects_bound", _key),
            *(
                (name, _matching(re.compile(pattern), f"a {name.replace('_', ' ')}"))
                for name, pattern in PROFILE_PATTERNS.items()
            ),
            ("choice_subjects", _choice_subjects),
            ("prompt_version", _matching(_PROMPT_VERSION, "a prompt version")),
            ("instruction", _matching(_PROMPT_TEXT, "one line of printable instruction text")),
            ("choice_description", _description),
            ("not_offered", _matching(_PROMPT_TEXT, "one line of printable instruction text")),
            *(
                (("engine_terms", partial(_engine_terms, line_rules=version >= LINE_RULES_FROM)),)
                if version >= ENGINE_TERMS_FROM
                else ()
            ),
            ("reason", text_field),
        ),
    )


def _whole(value: FieldValue) -> int:
    """A field its schema reads as a whole number, as the number it is."""
    if not isinstance(value, int):
        raise CatalogError(f"{value!r} is not a whole number")
    return value


def _newest(directory: Path) -> Path:
    """The registry's newest version in ``directory``: the one the loader reads."""
    found = {}
    for candidate in directory.glob(f"{REGISTRY_CATALOG}.v*.json"):
        stem, version = split_versioned_name(candidate)
        if stem == REGISTRY_CATALOG:
            found[version] = candidate
    if not found:
        raise RoleRefused(
            "role_registry_absent", f"{directory} holds no {REGISTRY_CATALOG} catalog version"
        )
    return found[max(found)]


def _adapter(entry_key: str, name: str, package: str) -> ModuleType:
    """The adapter module ``name`` in ``package``, holding what the generic path calls, and
    declaring that it serves ``entry_key``; anything else is refused by name."""
    module_name = f"{package}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise RoleRefused(
            "role_adapter_unknown",
            f"role {entry_key} names adapter {name!r}, which {package} does not hold",
        ) from exc
    missing = [attribute for attribute in _ADAPTER_NAMES if not hasattr(module, attribute)]
    if missing:
        raise RoleRefused(
            "role_adapter_incomplete", f"adapter {module_name} does not define {missing}"
        )
    if entry_key != module.ROLE:
        raise RoleRefused(
            "role_adapter_serves_another_role",
            f"adapter {module_name} serves {module.ROLE!r}, not {entry_key!r}",
        )
    kinds = module.KINDS
    if module.IDLE_KIND not in kinds or kinds[module.IDLE_KIND]:
        raise RoleRefused(
            "role_adapter_incomplete",
            f"adapter {module_name}'s idle kind is one of its kinds and its words name nothing",
        )
    if module.REASONS & GENERIC_REASONS:
        raise RoleRefused(
            "role_adapter_incomplete",
            f"adapter {module_name} restates generic reasons "
            f"{sorted(module.REASONS & GENERIC_REASONS)}",
        )
    return module


def load_decision_roles(
    directory: Path = REGISTRY_DIRECTORY, *, adapters: str = ADAPTER_PACKAGE
) -> RoleRegistry:
    """Read the newest registry version in ``directory``, each adapter from ``adapters``.

    ``adapters`` is a package name fixed by the caller's code: the production registry's is
    :data:`ADAPTER_PACKAGE`. A role's catalogs are read when its contract is first asked for.
    """
    path = _newest(directory)
    _stem, version = split_versioned_name(path)
    catalog: Catalog = load_catalog(path, _registry_schema(version))
    roles: dict[str, DecisionRole] = {}
    for entry in catalog.entries:
        values = dict(entry.values)
        adapter = _adapter(entry.key, str(values["adapter"]), adapters)
        action_catalog, policy_catalog = (
            str(values["action_catalog"]),
            str(values["policy_catalog"]),
        )
        engine_terms: dict[str, RoleTerms] = {}
        for stated in values.get("engine_terms", ()):  # type: ignore[union-attr]
            terms = dict(stated)  # type: ignore[call-overload]
            if terms["engine"] not in values["engines"]:  # type: ignore[operator]
                raise RoleRefused(
                    "role_terms_unhosted",
                    f"role {entry.key} states terms for {terms['engine']}, which does not host it",
                )
            engine_terms[str(terms["engine"])] = RoleTerms(
                versions={
                    action_catalog: int(terms["action_version"]),
                    policy_catalog: int(terms["policy_version"]),
                },
                prompt_version=str(terms["prompt_version"]),
                instruction=str(terms["instruction"]),
                choice_description=str(terms["choice_description"]),
                not_offered=str(terms["not_offered"]),
                line_rules=frozenset(terms["line_rules"]),
            )
        roles[entry.key] = DecisionRole(
            key=entry.key,
            subject=str(values["subject"]),
            engines=tuple(values["engines"]),  # type: ignore[arg-type]
            chosen=ChosenRoleBinding(
                role=entry.key,
                required_use_cases=tuple(values["required_use_cases"]),  # type: ignore[arg-type]
                rationale=str(values["reason"]),
            ),
            catalog_directory=_ROOT / str(values["catalog_directory"]),
            action_catalog=str(values["action_catalog"]),
            policy_catalog=str(values["policy_catalog"]),
            contract_versions={
                str(values["action_catalog"]): _whole(values["action_version"]),
                str(values["policy_catalog"]): _whole(values["policy_version"]),
            },
            own_order_from_policy_version=_whole(values["own_order_from_policy_version"]),
            subjects_bound=str(values["subjects_bound"]),
            request_profile=str(values["request_profile"]),
            receipt_profile=str(values["receipt_profile"]),
            choice_profile=str(values["choice_profile"]),
            choice_subjects=str(values["choice_subjects"]),
            context_profile=str(values["context_profile"]),
            prompt_version=str(values["prompt_version"]),
            instruction=str(values["instruction"]),
            choice_description=str(values["choice_description"]),
            not_offered=str(values["not_offered"]),
            adapter=adapter,  # type: ignore[arg-type]
            engine_terms=engine_terms,
        )
    for name in PROFILE_PATTERNS:
        stated = [getattr(role, name) for role in roles.values()]
        if len(set(stated)) != len(stated):
            raise RoleRefused(
                "role_profile_shared", f"two roles state one {name.replace('_', ' ')}"
            )
    # A prompt version names one prompt: no two roles, and no two terms of one role, share one.
    prompts = [terms.prompt_version for role in roles.values() for terms in role.every_terms()]
    if len(set(prompts)) != len(prompts):
        raise RoleRefused("role_profile_shared", "two roles or two terms state one prompt version")
    # A request's id is derived from its role's subject word, the subject and the minute, so two
    # roles deciding for one kind of subject would reserve one id and the second would be skipped.
    subjects = sorted(role.subject for role in roles.values())
    shared = sorted({subject for subject in subjects if subjects.count(subject) > 1})
    if shared:
        raise RoleRefused(
            "role_subject_shared", f"two roles decide for one kind of subject: {shared}"
        )
    return RoleRegistry(version=version, roles=dict(sorted(roles.items())))


@cache
def decision_roles() -> RoleRegistry:
    """The registry this process reads, once: the newest version in :data:`REGISTRY_DIRECTORY`,
    each adapter from :data:`ADAPTER_PACKAGE`. Every reader asks this one registry."""
    return load_decision_roles(REGISTRY_DIRECTORY, adapters=ADAPTER_PACKAGE)


def _catalog(role: DecisionRole, catalog_id: str, version: int, schema: Any) -> Catalog:
    return load_catalog(
        role.catalog_directory.joinpath(f"{catalog_id}.v{version}.json"),
        schema(catalog_id, version),
    )


def _adapter_policy_keys(role: DecisionRole, versions: Mapping[str, int]) -> frozenset[str]:
    """The keys only this role's policy holds at the policy version ``versions`` names, as its
    adapter states them (``POLICY_KEYS_FROM``: from a version on, those keys); none for an adapter
    that states none."""
    version = versions[role.policy_catalog]
    stated = getattr(role.adapter, "POLICY_KEYS_FROM", {})
    return frozenset(key for since, held in stated.items() if version >= since for key in held)


def _contract(role: DecisionRole, versions: Mapping[str, int]) -> DecisionContract:
    """One version of ``role``'s contract, read from its catalogs and held to its adapter."""
    if set(versions) != {role.action_catalog, role.policy_catalog}:
        raise ContractError(
            f"a {role.key} contract reads exactly "
            f"{sorted({role.action_catalog, role.policy_catalog})}"
        )
    actions = _catalog(role, role.action_catalog, versions[role.action_catalog], role_action_schema)
    policy_catalog = _catalog(
        role, role.policy_catalog, versions[role.policy_catalog], role_policy_schema
    )
    digest = catalog_digest([actions, policy_catalog])
    keys = POLICY_KEYS | {role.subjects_bound} | _adapter_policy_keys(role, versions)
    stated = {entry.key for entry in policy_catalog.entries}
    if stated != keys:
        raise ContractError(
            f"the {role.key} policy states {sorted(stated)}; it reads {sorted(keys)}"
        )
    kinds = [str(dict(entry.values)["kind"]) for entry in actions.entries]
    accepted = role.adapter.KINDS
    if len(set(kinds)) != len(kinds) or not set(kinds) <= set(accepted):
        raise ContractError(
            f"the {role.key} action catalog states each kind once, among {sorted(accepted)}"
        )
    if role.adapter.IDLE_KIND not in kinds:
        raise ContractError(f"the {role.key} action catalog states its idle kind")
    words: dict[str, str] = {}
    action_keys: dict[str, str] = {}
    for entry in actions.entries:
        values = dict(entry.values)
        kind, text = str(values["kind"]), str(values["words"])
        named = frozenset(_PLACEHOLDER.findall(text))
        alternative = getattr(role.adapter, "NAMED_KINDS", {}).get(kind)
        if named not in (accepted[kind], alternative) or text != text.lower():
            raise ContractError(
                f"action {entry.key}'s words name {sorted(named)}; a {kind} action names "
                f"{sorted(accepted[kind])}, in lowercase words"
            )
        words[kind], action_keys[kind] = text, entry.key
    policy = {entry.key: _whole(dict(entry.values)["value"]) for entry in policy_catalog.entries}
    for key, (low, high) in getattr(role.adapter, "POLICY_RANGES", {}).items():
        if key in policy and not low <= policy[key] <= high:
            raise ContractError(f"the {role.key} policy's {key} is {low} to {high}")
    if not policy["decision_deadline_ms"] < LEASE_SECONDS * 1000:
        raise ContractError("a decision's deadline ends inside the playback lease it is asked in")
    ranks = [policy[f"answer_rank_{m.value}"] for m in AnsweringMechanism]
    positive = [rank for rank in ranks if rank > 0]
    if not positive:
        raise ContractError(f"the {role.key} policy accepts no answering mechanism")
    if len(positive) != len(set(positive)):
        raise ContractError("two answering mechanisms share one rank")
    for key in (*_AT_LEAST_ONE, role.subjects_bound):
        if policy[key] < 1:
            raise ContractError(f"{key} is at least 1")
    if policy["options_maximum"] < FEWEST_OPTIONS:
        raise ContractError(
            f"options_maximum is at least {FEWEST_OPTIONS}: a subject is asked with its idle "
            "action and one thing more, or not at all"
        )
    if not 0 <= policy["process_reserve_percent"] < 100:
        raise ContractError("process_reserve_percent keeps part of the budget and never all of it")
    return DecisionContract(
        words=words,
        action_keys=action_keys,
        policy=policy,
        versions=dict(versions),
        sha256=digest,
        asks_in_a_models_own_order=(
            versions[role.policy_catalog] >= role.own_order_from_policy_version
        ),
        takes_lines=bool(set(words) & set(getattr(role.adapter, "LINE_KINDS", ()))),
    )
