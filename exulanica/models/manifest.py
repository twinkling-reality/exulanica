"""The model manifest: the one place a model identifier is allowed to exist.

Every caller names a **role**. Roles are stable; identifiers are not. Two deprecation rounds
landed in roughly ten weeks before this was written, and the demo has to survive unattended from
the end of October to at least mid December. A call site that names an identifier is a call site
that breaks silently when that identifier is withdrawn, and nobody is watching in December.

Four consequences follow, and all four are enforced here rather than by convention:

*   Identifiers live in ``models.manifest.json`` beside this module, never in Python source.
    ``tests/test_models_manifest.py`` greps the package and fails if one leaks into code. A
    data file rather than a Python table is what makes that test possible at all, and it is what
    the model catalog preflight (`docs/deployment.md` section 7) reads.
*   Every role declares a fallback identifier, so a withdrawal degrades answer quality instead
    of killing the request. One role, embedding, genuinely has no same-tier fallback in the
    catalog; it declares ``null`` and the client raises rather than substituting a model from a
    different vector space, which would silently poison every stored vector.
*   ``pipeline_version`` lives in the manifest. Changing an identifier is required to bump it,
    which invalidates every stored caption vector and evaluation provenance keyed by the model
    being replaced. The response cache key names the provider and the model besides, so a
    cached answer is never served for another model.
*   Prices are read with ``json.loads(parse_float=Decimal)`` and stay ``Decimal`` all the way to
    the reported total. Money never becomes a float here: a float dollar amount accumulated over
    a corpus is a number nobody can reconcile against an invoice.

**Providers are data.** A provider states where its requests go, the one environment variable
its credential is read from and the catalog its models are checked against; every model names
its provider, and no code names one. The origin a provider's requests reach is derived from its
``base_url`` by :func:`exulanica.models.egress.declared_origin`, the egress allowlist's own
spelling, so it is never stated a second time, and a URL the allowlist could not declare is
refused here. A role's chain stays on one provider, because a hand-over names one destination.

**A chosen role has no model here, and no entry.** A world names a model for a decision role, a
person today, among the models the manifest offers the role. The roles themselves are declared as
data by the decision role registry above this package (``exulanica.world.decision_roles``), which
passes each role's requirements down as a :class:`ChosenRoleBinding`; this package names no
chosen role. A model is offered to a binding when its ``answering`` map names at least one
mechanism by which it was verified to answer a choice, each naming the record of the probe that
verified it, and its catalog use cases hold the binding's. A model with no verified mechanism is
offered to no chosen role.

**Casing is load bearing.** The catalog's human-readable ``name`` field differs from the callable
``model_id``, inconsistently across the reasoning line: one identifier doubles its vendor prefix,
another is entirely lowercase, a third uses an underscore where its display name uses a dot. The
manifest and the preflight both read ``flavors[].model_id`` and never ``name``. A typo here is a
silent 404-class failure.

**Every role declares how long a request to it may take**, as data with its measured basis:
``timeout_seconds`` beside a ``timeout_basis`` quoting the longest latency recorded for the role's
primary, and one ``timeout_rule`` saying how the first follows from the second. The parser derives
each timeout from its basis and refuses a manifest that states a different one, so a timeout can
not drift from the measurement it claims, and a changed primary cannot keep the old primary's
basis. The client reads the timeout from here; no second constant exists in code. A chosen role
states none: its caller bounds each call by its own contract.

**Region strings are informational.** Token Factory reports its public endpoints as Region
"Global" and warns the processing location can change without notice, so only the global base URL
is ever used and nothing in this codebase branches on a region.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.models.egress import declared_origin
from exulanica.models.errors import ManifestError

__all__ = [
    "MANIFEST_PATH",
    "AnsweringMechanism",
    "CatalogFormat",
    "ChosenRoleBinding",
    "DeclaredNumber",
    "Manifest",
    "ModelSpec",
    "Provider",
    "Role",
    "RoleBinding",
    "TimeoutRule",
    "load_manifest",
    "load_manifest_from",
    "parse_manifest",
]

MANIFEST_PATH: Final = Path(__file__).with_name("models.manifest.json")

#: A provider key, the same shape a model identity's provider takes (``exulanica.models.handoff``).
_PROVIDER_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
#: The variables a provider's credential may be read from: an API key's, and never one of this
#: application's own settings, so a manifest entry cannot send a database URL as a bearer token.
_KEY_VARIABLE: Final = re.compile(r"^(?!EXULANICA_)[A-Z][A-Z0-9_]{0,55}_API_KEY$")
#: Where a verified mechanism's evidence lives: a record under ``docs/evaluation``.
_RECORD_PATH: Final = re.compile(r"^docs/evaluation/[A-Za-z0-9._/-]+\.json$")
#: A judgement a policy admits models to make, named as the policy names it.
_JUDGEMENT: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class Role(StrEnum):
    """What a call site asks for. Never an identifier, never a vendor, never a size.

    Only the roles the manifest binds to a model. A role whose model a world chooses is a decision
    role, declared by the registry above this package and reaching it as a
    :class:`ChosenRoleBinding`.
    """

    REASONING_CHEAP = "reasoning_cheap"
    ANSWER_COMPOSER = "answer_composer"
    REASONING_MID = "reasoning_mid"
    REASONING_HARD = "reasoning_hard"
    VISION = "vision"
    STRUCTURED_EXTRACTION = "structured_extraction"
    SPECIFICATION_DRAFTER = "specification_drafter"
    CREATURE_DRAFTER = "creature_drafter"
    KIND_DRAFTER = "kind_drafter"
    LOOK_CHOOSER = "look_chooser"
    SETTING_CHOOSER = "setting_chooser"
    REFERENCE_DRAFTING = "reference_drafting"
    REFERENCE_VISION = "reference_vision"
    EMBEDDING = "embedding"


#: A chosen role's key: the name every call record of it carries, the same shape a model
#: identity's role takes (``exulanica.models.handoff``).
_CHOSEN_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class CatalogFormat(StrEnum):
    """How a provider's machine-readable catalog is read, by the shape of its document."""

    #: A JSON array of models, each with ``flavors[]`` naming ``model_id``, ``use_cases`` and
    #: prices per million tokens.
    MODEL_FLAVORS = "model_flavors"


class AnsweringMechanism(StrEnum):
    """How a model is asked for one choice among labelled options, when it was verified to answer.

    Each is a request the client builds itself. A manifest names a mechanism for a model only with
    the record of the probe that verified it; the client never asks a model by a mechanism its
    entry does not name.
    """

    #: One OpenAI-format function whose single argument is an enum of the options, forced by name.
    TOOL_CALL = "tool_call"
    #: ``response_format`` ``json_schema`` strict, whose single property is that enum.
    JSON_SCHEMA = "json_schema"


@dataclass(frozen=True, slots=True)
class Provider:
    """Where one provider's requests go, the variable its credential is read from, its catalog.

    ``origin`` and ``catalog_origin`` are derived in the egress allowlist's own spelling, the
    exact entries a deployment must declare, and never stated beside the URLs a second time.
    """

    provider_id: str
    base_url: str
    api_key_env: str
    catalog_url: str
    catalog_format: CatalogFormat
    catalog_retrieved_at: str
    description: str

    @property
    def origin(self) -> str:
        """The origin every request to this provider reaches."""
        return declared_origin(self.base_url)

    @property
    def catalog_origin(self) -> str:
        """The origin the preflight reaches for this provider's catalog."""
        return declared_origin(self.catalog_url)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One catalog identifier and the facts about it the client needs at runtime.

    ``min_max_tokens`` is the operationally important one. The reasoning models on this platform
    spend roughly 150 to 215 tokens thinking before emitting a single token of answer, on every
    call, and that cannot be disabled. A ``max_tokens`` under that floor returns HTTP 200 with
    ``finish_reason: "length"`` and an empty answer, which reads as a model failure and is not
    one. That mistake has already produced one false negative in this project's own verification
    harness, so the floor is data the client enforces rather than a comment nobody reads.
    """

    model_id: str
    #: The key of the provider serving this identifier, in the manifest's ``providers``.
    provider: str
    #: One plain sentence naming the model for a person choosing among models.
    description: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    context_window_tokens: int
    min_max_tokens: int | None
    default_max_tokens: int | None
    emits_inline_reasoning: bool
    supports_json_schema: bool
    catalog_type: str
    catalog_use_cases: tuple[str, ...]
    catalog_license: str
    region_informational: str
    embedding_dimensions: int | None = None
    note: str = ""
    #: Each mechanism this model was verified to answer a choice by, with the record of the probe
    #: that verified it. Empty for a model offered to no chosen role. Left out of the hash, which
    #: every other field supports: a mapping cannot be hashed.
    answering: Mapping[AnsweringMechanism, str] = field(
        default_factory=lambda: MappingProxyType({}), hash=False
    )
    #: The order this model is asked a choice by where a measurement found it answers better that
    #: way than in the order a caller's contract prefers: each mechanism once, each verified in
    #: ``answering``, with the record that measured it and why. Empty: the caller's own order.
    answering_order: tuple[AnsweringMechanism, ...] = ()
    answering_order_record: str | None = None
    answering_order_reason: str | None = None
    #: Why this model is not offered for a choice that takes a line (where an option says
    #: something, so the answer carries the line as a second argument), in a plain sentence; None
    #: where it is offered for every choice it is verified to answer.
    not_offered_for_lines: str | None = None
    #: Each judgement a policy may admit this model to make, with the record of the probe that
    #: measured it: ``sign_completeness`` is the place-proposal policy's sign judgement
    #: (``exulanica.ingest.place_proposal``). Empty for a model admitted to judge nothing. Left
    #: out of the hash, as ``answering`` is.
    judging: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}), hash=False)

    def cost_usd(self, *, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """Billable cost of one call, exactly.

        ``completion_tokens`` already contains ``reasoning_tokens`` on this platform (measured:
        154 completion of which 149 reasoning), so reasoning is charged here exactly once and is
        never added on top.

        Cached prompt tokens are billed at the full input price. The API reports
        ``prompt_cache_hit_tokens`` but publishes no discount for them, so the conservative
        reading is the one used: an estimate that is too low is worse than one that is too high.
        """
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ManifestError("token counts may not be negative")
        return (
            Decimal(prompt_tokens) * self.input_usd_per_mtok
            + Decimal(completion_tokens) * self.output_usd_per_mtok
        ) / Decimal(1_000_000)

    def model_ref(self, *, endpoint: str) -> dict[str, str]:
        """The ``model_ref`` shape the pipeline ledger stores: provider, id, endpoint.

        ``revision`` is deliberately absent. Token Factory exposes no per-model revision for
        serverless endpoints, and a field invented here would be a fact the ledger cannot
        support.
        """
        return {"provider": self.provider, "model_id": self.model_id, "endpoint": endpoint}

    @property
    def is_chat(self) -> bool:
        """Whether a chat request can be sent to it: a chat model declares a max_tokens floor."""
        return self.min_max_tokens is not None


@dataclass(frozen=True, slots=True)
class TimeoutRule:
    """How a role's timeout follows from the longest latency measured for its primary.

    ``headroom_factor`` covers a tail the recorded calls did not reach, and ``round_up_to_seconds``
    keeps one new measurement from moving the bound. Both are the manifest's, stated once.
    """

    headroom_factor: int
    round_up_to_seconds: int

    def timeout_for(self, longest_ms: int) -> int:
        """Whole seconds: ``longest_ms`` times the headroom, rounded up to the step. No floats."""
        step_ms = self.round_up_to_seconds * 1000
        return -(-longest_ms * self.headroom_factor // step_ms) * self.round_up_to_seconds


@dataclass(frozen=True, slots=True)
class DeclaredNumber:
    """A number the manifest states for a role, with the sentence saying why it is that number."""

    value: int
    basis: str


@dataclass(frozen=True, slots=True)
class RoleBinding:
    """A role, its primary model, the model tried when the primary is withdrawn, and its timeout."""

    role: Role
    primary: ModelSpec
    fallback: ModelSpec | None
    required_use_cases: tuple[str, ...]
    rationale: str
    #: How long one request to this role may take before it is abandoned, in whole seconds.
    #: Derived from ``timeout_basis`` by the manifest's :class:`TimeoutRule` in ``parse_manifest``.
    timeout_seconds: int
    #: The measurement the timeout rests on, as the manifest states it: the record it was read
    #: from, the primary it measured, and the longest latency recorded for that primary.
    timeout_basis: Mapping[str, Any]
    #: The completion ceiling this role's caller asks for, where the chain's default is too low
    #: for it, with the reason the manifest states; ``None`` where the default serves.
    max_tokens: DeclaredNumber | None = None
    #: The prompt tokens one image is reserved at before a call to this role, for the budget
    #: guard's reservation only (accounting reads the usage the provider reports); ``None`` for a
    #: role that is sent no image.
    image_prompt_tokens_reserved: DeclaredNumber | None = None

    @property
    def provider(self) -> str:
        """The key of the one provider serving the whole chain."""
        return self.primary.provider

    @property
    def chain(self) -> tuple[ModelSpec, ...]:
        """Primary first, then fallback. The order the client tries them in."""
        return (self.primary,) if self.fallback is None else (self.primary, self.fallback)

    @property
    def min_max_tokens(self) -> int:
        """The strictest reasoning floor in the chain.

        Deliberately the maximum over the chain rather than the primary's own floor. If the floor
        were checked against the primary only, a fallback with a larger reasoning overhead would
        begin truncating the moment it was reached, which is exactly the situation in which
        nobody is watching.
        """
        floors = [spec.min_max_tokens for spec in self.chain if spec.min_max_tokens is not None]
        if not floors:
            raise ManifestError(
                f"role {self.role} declares no max_tokens floor, so it is not a chat role"
            )
        return max(floors)

    def image_reservation(self, images: int) -> int:
        """The prompt tokens ``images`` images are reserved at before a call to this role."""
        if self.image_prompt_tokens_reserved is None:
            raise ManifestError(
                f"role {self.role} declares no image_prompt_tokens_reserved, so it is sent no image"
            )
        return self.image_prompt_tokens_reserved.value * images

    @property
    def default_max_tokens(self) -> int:
        """Used when a caller does not specify one. Never below the chain's floor."""
        defaults = [
            spec.default_max_tokens for spec in self.chain if spec.default_max_tokens is not None
        ]
        if not defaults:
            raise ManifestError(f"role {self.role} declares no default max_tokens")
        return max(max(defaults), self.min_max_tokens)


@dataclass(frozen=True, slots=True)
class ChosenRoleBinding:
    """A role whose model a world chooses, and what a model must declare to be offered it.

    Built by the decision role registry from a role's entry, never read from this manifest: its
    ``role`` is the role's key, which may not be a role the manifest binds.
    """

    role: str
    required_use_cases: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not _CHOSEN_KEY.fullmatch(self.role):
            raise ManifestError(f"{self.role!r} is not a chosen role's key")
        if self.role in {role.value for role in Role}:
            raise ManifestError(
                f"{self.role} is a role the manifest binds to a model, so no world chooses it"
            )
        if not self.required_use_cases or not all(
            isinstance(use_case, str) and use_case for use_case in self.required_use_cases
        ):
            raise ManifestError(f"chosen role {self.role} names the use cases a model needs")

    def offers(self, spec: ModelSpec) -> bool:
        """Whether ``spec`` may be chosen for this role: a chat model, verified to answer a
        choice by at least one mechanism, whose catalog use cases hold the role's."""
        return (
            spec.is_chat
            and bool(spec.answering)
            and all(use_case in spec.catalog_use_cases for use_case in self.required_use_cases)
        )


@dataclass(frozen=True, slots=True)
class Manifest:
    """The parsed manifest. Immutable, and the only source of identifiers in the process."""

    manifest_version: str
    pipeline_version: int
    providers: Mapping[str, Provider]
    models: Mapping[str, ModelSpec]
    roles: Mapping[Role, RoleBinding]
    timeout_rule: TimeoutRule

    def __getitem__(self, role: Role | str) -> RoleBinding:
        try:
            resolved = Role(role)
        except ValueError as exc:
            known = ", ".join(sorted(r.value for r in Role))
            raise ManifestError(
                f"no binding for role {role!r}; the manifest binds {known}. A role a world "
                "chooses a model for is asked with offered()"
            ) from exc
        try:
            return self.roles[resolved]
        except KeyError as exc:
            known = ", ".join(sorted(r.value for r in Role))
            raise ManifestError(
                f"no binding for role {role!r}; the manifest binds {known}"
            ) from exc

    def spec(self, model_id: str) -> ModelSpec:
        try:
            return self.models[model_id]
        except KeyError as exc:
            raise ManifestError(f"{model_id!r} is not declared in the manifest") from exc

    def judges(self, judgement: str) -> tuple[tuple[str, str], ...]:
        """Every model admitted to make ``judgement``, with the record that measured it, in the
        manifest's order."""
        return tuple(
            (model_id, spec.judging[judgement])
            for model_id, spec in self.models.items()
            if judgement in spec.judging
        )

    def credential_variables(self, roles: Iterable[Role]) -> frozenset[str]:
        """The variables the credentials of the providers serving ``roles`` are read from."""
        return frozenset(self.provider(self[role].provider).api_key_env for role in roles)

    def model_name(self, model_id: str) -> str:
        """The name a person reads for a model: its description up to its first comma, or its
        identifier when this manifest does not declare it.

        The one rule. ``GET /world/versions/{version_id}/society/models`` serves it as each
        offered model's ``name``, which the People panel shows, and the Companion names the model
        behind a person's decision by it (``exulanica/selection/society_question.py``), so one
        model is never called two things.
        """
        spec = self.models.get(model_id)
        if spec is None:
            return model_id
        comma = spec.description.find(",")
        return spec.description[:comma] if comma > 0 else spec.description

    def provider(self, provider_id: str) -> Provider:
        """The provider with this key, or a refusal naming what was asked for."""
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise ManifestError(f"no provider {provider_id!r} is declared in the manifest") from exc

    def offered_models(self, binding: ChosenRoleBinding) -> tuple[ModelSpec, ...]:
        """Every model a world may choose for a chosen role, in identifier order."""
        return tuple(spec for _, spec in sorted(self.models.items()) if binding.offers(spec))

    def offered(self, binding: ChosenRoleBinding, model_id: str) -> ModelSpec:
        """The model a world chose for a chosen role, or a refusal naming why it is not offered."""
        spec = self.spec(model_id)
        if not binding.offers(spec):
            raise ManifestError(
                f"{model_id!r} is not offered to {binding.role}: a chosen role takes a chat model "
                "verified to answer a choice by at least one mechanism whose catalog use cases "
                f"hold {sorted(binding.required_use_cases)}"
            )
        return spec

    @property
    def model_ids(self) -> frozenset[str]:
        """Every identifier the manifest declares, whether or not a role reaches it."""
        return frozenset(self.models)

    def bound_origins(self) -> frozenset[str]:
        """The origin of every provider serving a role the manifest binds to a model.

        What a deployment that serves those roles must declare in its egress allowlist, in the
        allowlist's own spelling: the one derivation a launcher or a rehearsal asks for, never a
        second reading of the manifest's JSON.
        """
        return frozenset(self.provider(b.provider).origin for b in self.roles.values())

    def referenced_model_ids(self) -> frozenset[str]:
        """Identifiers reachable through a role, bound or chosen. This is what the preflight checks.

        Fallbacks are included. A fallback that has itself been removed is a failover that fails,
        which is worse than no failover because it is only discovered under load. So is every
        chat model verified to answer a choice, since a chosen role may be offered it and a world
        may have chosen it: the manifest names no chosen role, so it counts every model one could
        be offered.
        """
        reachable: set[str] = set()
        for binding in self.roles.values():
            reachable.update(spec.model_id for spec in binding.chain)
        reachable.update(
            model_id for model_id, spec in self.models.items() if spec.is_chat and spec.answering
        )
        return frozenset(reachable)


def _need(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise ManifestError(f"{where}: manifest entry is missing {key!r}")
    return raw[key]


def _text(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = _need(raw, key, where)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where}: {key} must be a non-empty string")
    return value


def _key_variable(raw: Mapping[str, Any], where: str) -> str:
    name = _text(raw, "api_key_env", where)
    if not _KEY_VARIABLE.fullmatch(name):
        raise ManifestError(
            f"{where}: api_key_env {name!r} is not a provider's API key variable "
            "(NAME_API_KEY, never an EXULANICA_ setting)"
        )
    return name


def _provider_from(provider_id: str, raw: Any) -> Provider:
    where = f"provider {provider_id}"
    if not isinstance(provider_id, str) or not _PROVIDER_KEY.fullmatch(provider_id):
        raise ManifestError(f"{provider_id!r} is not a provider key")
    if not isinstance(raw, Mapping):
        raise ManifestError(f"{where} must be an object")
    fields = {
        "base_url",
        "api_key_env",
        "catalog_url",
        "catalog_format",
        "catalog_retrieved_at",
        "description",
    }
    if set(raw) != fields:
        raise ManifestError(f"{where} states exactly {sorted(fields)}, got {sorted(raw)}")
    try:
        catalog_format = CatalogFormat(raw["catalog_format"])
    except ValueError as exc:
        known = ", ".join(sorted(f.value for f in CatalogFormat))
        raise ManifestError(
            f"{where}: catalog_format {raw['catalog_format']!r} is not one this code reads "
            f"({known})"
        ) from exc
    provider = Provider(
        provider_id=provider_id,
        base_url=_text(raw, "base_url", where).rstrip("/"),
        api_key_env=_key_variable(raw, where),
        catalog_url=_text(raw, "catalog_url", where),
        catalog_format=catalog_format,
        catalog_retrieved_at=_text(raw, "catalog_retrieved_at", where),
        description=_text(raw, "description", where),
    )
    for name, url in (("base_url", provider.base_url), ("catalog_url", provider.catalog_url)):
        try:
            declared_origin(url)
        except ValueError as exc:
            raise ManifestError(
                f"{where}: {name} names no origin an allowlist declares: {exc}"
            ) from exc
    return provider


def _answering(model_id: str, raw: Any) -> Mapping[AnsweringMechanism, str]:
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, Mapping):
        raise ManifestError(f"{model_id}: answering maps a mechanism to its probe's record")
    answering: dict[AnsweringMechanism, str] = {}
    for mechanism, record in raw.items():
        try:
            key = AnsweringMechanism(mechanism)
        except ValueError as exc:
            known = ", ".join(sorted(m.value for m in AnsweringMechanism))
            raise ManifestError(
                f"{model_id}: answering names {mechanism!r}, which is not a mechanism the client "
                f"asks by ({known})"
            ) from exc
        if not isinstance(record, str) or not _RECORD_PATH.fullmatch(record):
            raise ManifestError(
                f"{model_id}: answering.{mechanism} names the probe record that verified it, a "
                f"docs/evaluation JSON path, not {record!r}"
            )
        answering[key] = record
    return MappingProxyType(answering)


def _not_offered_for_lines(model_id: str, raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or "\n" in raw:
        raise ManifestError(
            f"{model_id}: not_offered_for_lines says why in one plain sentence, or is left out"
        )
    return raw


def _judging(model_id: str, raw: Any) -> Mapping[str, str]:
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, Mapping) or not raw:
        raise ManifestError(f"{model_id}: judging maps a judgement to the record that measured it")
    for judgement, record in raw.items():
        if not isinstance(judgement, str) or not _JUDGEMENT.fullmatch(judgement):
            raise ManifestError(f"{model_id}: judging names {judgement!r}, not a lowercase key")
        if not isinstance(record, str) or not _RECORD_PATH.fullmatch(record):
            raise ManifestError(
                f"{model_id}: judging.{judgement} names the record that measured it, a "
                f"docs/evaluation JSON path, not {record!r}"
            )
    return MappingProxyType(dict(raw))


def _declared_number(role: Role, raw: Mapping[str, Any], key: str) -> DeclaredNumber | None:
    """A number a role states with its reason, or ``None`` where the role states none."""
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"value", "basis"}:
        raise ManifestError(f"role {role}: {key} states exactly its value and its basis")
    basis = value["basis"]
    if not isinstance(basis, str) or not basis.strip():
        raise ManifestError(f"role {role}: {key}.basis says why, in a sentence")
    return DeclaredNumber(_positive_whole(value["value"], f"role {role}: {key}.value"), basis)


def _answering_order(
    model_id: str, raw: Any, answering: Mapping[AnsweringMechanism, str]
) -> tuple[tuple[AnsweringMechanism, ...], str | None, str | None]:
    """A model's own answering order, its record and its reason; nothing where none is stated."""
    if raw is None:
        return (), None, None
    fields = {"mechanisms", "record", "reason"}
    if not isinstance(raw, Mapping) or set(raw) != fields:
        raise ManifestError(
            f"{model_id}: answering_order states exactly {sorted(fields)}: the mechanisms in the "
            "order the model is asked by, the record that measured them and why"
        )
    mechanisms = raw["mechanisms"]
    if not isinstance(mechanisms, list) or not mechanisms:
        raise ManifestError(f"{model_id}: answering_order names at least one mechanism")
    order: list[AnsweringMechanism] = []
    for mechanism in mechanisms:
        try:
            key = AnsweringMechanism(mechanism)
        except ValueError as exc:
            raise ManifestError(
                f"{model_id}: answering_order names {mechanism!r}, which is not a mechanism the "
                "client asks by"
            ) from exc
        if key not in answering:
            raise ManifestError(
                f"{model_id}: answering_order names {mechanism!r}, which its answering does not "
                "verify"
            )
        if key in order:
            raise ManifestError(f"{model_id}: answering_order names {mechanism!r} twice")
        order.append(key)
    record, reason = raw["record"], raw["reason"]
    if not isinstance(record, str) or not _RECORD_PATH.fullmatch(record):
        raise ManifestError(
            f"{model_id}: answering_order names the record that measured it, a docs/evaluation "
            f"JSON path, not {record!r}"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise ManifestError(f"{model_id}: answering_order says why, in a sentence")
    return tuple(order), record, reason


def _spec_from(
    model_id: str, raw: Mapping[str, Any], providers: Mapping[str, Provider]
) -> ModelSpec:
    def need(key: str) -> Any:
        return _need(raw, key, model_id)

    def as_decimal(key: str) -> Decimal:
        value = need(key)
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return Decimal(value)
        raise ManifestError(f"{model_id}: {key} must be a JSON number, got {type(value).__name__}")

    def as_optional_int(key: str) -> int | None:
        value = need(key)
        return None if value is None else int(value)

    provider = _text(raw, "provider", model_id)
    if provider not in providers:
        raise ManifestError(f"{model_id}: provider {provider!r} is not declared in providers")
    answering = _answering(model_id, raw.get("answering"))
    order, order_record, order_reason = _answering_order(
        model_id, raw.get("answering_order"), answering
    )
    return ModelSpec(
        model_id=model_id,
        provider=provider,
        description=_text(raw, "description", model_id),
        input_usd_per_mtok=as_decimal("input_usd_per_mtok"),
        output_usd_per_mtok=as_decimal("output_usd_per_mtok"),
        context_window_tokens=int(need("context_window_tokens")),
        min_max_tokens=as_optional_int("min_max_tokens"),
        default_max_tokens=as_optional_int("default_max_tokens"),
        emits_inline_reasoning=bool(need("emits_inline_reasoning")),
        supports_json_schema=bool(need("supports_json_schema")),
        catalog_type=str(need("catalog_type")),
        catalog_use_cases=tuple(str(u) for u in need("catalog_use_cases")),
        catalog_license=str(need("catalog_license")),
        region_informational=str(need("region_informational")),
        embedding_dimensions=(
            None if raw.get("embedding_dimensions") is None else int(raw["embedding_dimensions"])
        ),
        note=str(raw.get("note", "")),
        answering=answering,
        answering_order=order,
        answering_order_record=order_record,
        answering_order_reason=order_reason,
        judging=_judging(model_id, raw.get("judging")),
        not_offered_for_lines=_not_offered_for_lines(model_id, raw.get("not_offered_for_lines")),
    )


def _reject_unknown_roles(raw_roles: Mapping[str, Any]) -> None:
    """Reject a role name the Role enum does not know, naming the offender."""
    unknown = sorted(set(raw_roles) - {role.value for role in Role})
    if unknown:
        raise ManifestError(
            "manifest declares roles the code does not know: "
            + ", ".join(unknown)
            + ". Add them to Role, or remove them from the manifest."
        )


def _positive_whole(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{where} must be a positive whole number, got {value!r}")
    return value


def _timeout_rule(raw: Any) -> TimeoutRule:
    if not isinstance(raw, Mapping):
        raise ManifestError("manifest timeout_rule must be an object")
    return TimeoutRule(
        headroom_factor=_positive_whole(raw.get("headroom_factor"), "timeout_rule.headroom_factor"),
        round_up_to_seconds=_positive_whole(
            raw.get("round_up_to_seconds"), "timeout_rule.round_up_to_seconds"
        ),
    )


def _role_timeout(
    role: Role, raw: Mapping[str, Any], primary: ModelSpec, rule: TimeoutRule
) -> tuple[int, Mapping[str, Any]]:
    """The role's timeout and its basis, or ``ManifestError`` naming the disagreement."""
    stated = _positive_whole(raw.get("timeout_seconds"), f"role {role}: timeout_seconds")
    basis = raw.get("timeout_basis")
    if not isinstance(basis, Mapping):
        raise ManifestError(f"role {role}: timeout_basis must be an object naming its measurement")
    if basis.get("model") != primary.model_id:
        raise ManifestError(
            f"role {role}: timeout_basis measured {basis.get('model')!r}, but the primary is "
            f"{primary.model_id!r}. A timeout rests on the model it bounds: measure the primary "
            "and restate the basis."
        )
    if not isinstance(basis.get("record"), str) or not basis["record"]:
        raise ManifestError(f"role {role}: timeout_basis names no record")
    longest = _positive_whole(basis.get("longest_ms"), f"role {role}: timeout_basis.longest_ms")
    derived = rule.timeout_for(longest)
    if stated != derived:
        raise ManifestError(
            f"role {role}: timeout_seconds is {stated}, but its basis ({longest} ms longest) and "
            f"the timeout_rule give {derived}. Restate one of them; they may not disagree."
        )
    return stated, MappingProxyType(dict(basis))


def parse_manifest(document: Mapping[str, Any]) -> Manifest:
    """Validate a manifest document and freeze it. Raises ``ManifestError`` on anything wrong."""
    for key in ("providers", "models", "roles", "pipeline_version", "timeout_rule"):
        if key not in document:
            raise ManifestError(f"manifest is missing top-level key {key!r}")
    if "chosen_roles" in document:
        raise ManifestError(
            "manifest states chosen_roles, which the decision role registry declares "
            "(exulanica.world.decision_roles): a role a world chooses a model for has no entry here"
        )

    raw_providers: Mapping[str, Any] = document["providers"]
    if not isinstance(raw_providers, Mapping) or not raw_providers:
        raise ManifestError("manifest declares no provider")
    providers = {key: _provider_from(key, raw) for key, raw in raw_providers.items()}
    raw_models: Mapping[str, Any] = document["models"]
    raw_roles: Mapping[str, Any] = document["roles"]
    rule = _timeout_rule(document["timeout_rule"])
    specs = {model_id: _spec_from(model_id, raw, providers) for model_id, raw in raw_models.items()}

    _reject_unknown_roles(raw_roles)
    missing = {role.value for role in Role} - set(raw_roles)
    if missing:
        raise ManifestError(
            "manifest does not bind every role. Missing: " + ", ".join(sorted(missing))
        )

    bindings: dict[Role, RoleBinding] = {}
    for name, raw in raw_roles.items():
        role = Role(name)
        primary_id = raw["primary"]
        fallback_id = raw.get("fallback")
        if primary_id not in specs:
            raise ManifestError(f"role {role}: primary {primary_id!r} has no model entry")
        if fallback_id is not None and fallback_id not in specs:
            raise ManifestError(f"role {role}: fallback {fallback_id!r} has no model entry")
        if fallback_id == primary_id:
            raise ManifestError(
                f"role {role}: the fallback is the same identifier as the primary, which is not a "
                "fallback. Declare null if this role genuinely has none."
            )
        if fallback_id is not None and specs[fallback_id].provider != specs[primary_id].provider:
            raise ManifestError(
                f"role {role}: the primary is served by {specs[primary_id].provider} and the "
                f"fallback by {specs[fallback_id].provider}. A role's chain stays on one provider, "
                "because a hand-over names one destination."
            )
        timeout_seconds, timeout_basis = _role_timeout(role, raw, specs[primary_id], rule)
        bindings[role] = RoleBinding(
            role=role,
            primary=specs[primary_id],
            fallback=None if fallback_id is None else specs[fallback_id],
            required_use_cases=tuple(str(u) for u in raw.get("required_use_cases", ())),
            rationale=str(raw.get("rationale", "")),
            timeout_seconds=timeout_seconds,
            timeout_basis=timeout_basis,
            max_tokens=_declared_number(role, raw, "max_tokens"),
            image_prompt_tokens_reserved=_declared_number(
                role, raw, "image_prompt_tokens_reserved"
            ),
        )
    return Manifest(
        manifest_version=str(document.get("manifest_version", "0")),
        pipeline_version=int(document["pipeline_version"]),
        providers=MappingProxyType(providers),
        models=specs,
        roles=bindings,
        timeout_rule=rule,
    )


def load_manifest_from(path: Path) -> Manifest:
    """Load and validate a manifest from an explicit path. Not cached."""
    try:
        # parse_float=Decimal keeps prices exact from disk all the way to the reported total.
        document = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except FileNotFoundError as exc:
        raise ManifestError(f"no model manifest at {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"model manifest at {path} is not valid JSON: {exc}") from exc
    return parse_manifest(document)


@lru_cache(maxsize=1)
def load_manifest() -> Manifest:
    """The process-wide manifest. Cached, because it is read on every call site's first use."""
    return load_manifest_from(MANIFEST_PATH)
