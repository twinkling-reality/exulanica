"""Whether a place's saved name may go to a model: what is offered, what is said, and the rule.

A name exists in this product only because the account holder typed it. Their rules are that a
person's name never goes to a hosted model, with or without a right, and that a place's name goes
only where they have allowed it, asked for each place. The right itself is stored by
:mod:`exulanica.consent.place_name_rights`; this module holds everything about it that needs no
database, so the rule has one statement and a test can hold it to every case.

**What may be allowed is declared, not assumed.** ``place-name-uses.v1.json`` beside this module
lists the uses a place name may be offered to, one per hosted model role, each with the purpose a
person reads. A role absent from it is never offered and never receives a name. The models are
not listed there: they are the manifest's chain for the role, read when a notice is written, so a
manifest change reaches every notice at once.

**A grant is a grant of exactly what was said.** Following rule P6 of
``docs/privacy-consent-threat-model.md``, the notice a person is shown names every model of the
role's chain, the host the name travels to, the purpose and the term, and the grant stores that
text. A grant counts only while the product would show the same text: a changed chain, host,
purpose or term is a statement nobody has agreed to yet, so it reads as ``notice_changed`` until the
account holder allows it again.

**The rule, stated once.** :func:`model_state` says what one model's last decision means at an
instant, and :func:`read_use` folds a role's chain into what a screen shows. A name may go to a
hand-over only when every model it can reach reads ``allowed``: a request to a role can reach its
fallback as well as its primary, so allowing one of them releases nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import string
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Final, Literal

from exulanica.models.handoff import LOCAL_PROCESS, ModelHandoff, ModelIdentity
from exulanica.models.manifest import Manifest, Role

__all__ = [
    "DECISION_PROFILE",
    "PLACE_NAME_USES_PROFILE",
    "DecisionKind",
    "LastDecision",
    "ModelState",
    "PlaceNameUse",
    "PlaceNameUses",
    "UseReading",
    "UseState",
    "load_place_name_uses",
    "model_state",
    "parse_place_name_uses",
    "read_use",
]

PLACE_NAME_USES_PROFILE: Final = "exulanica.place-name-uses/v1"
#: The profile every stored decision's receipt carries; migration 0097 checks it.
DECISION_PROFILE: Final = "exulanica.place-name-right-event/v1"

DecisionKind = Literal["granted", "withdrawn"]

#: What one model's last decision means at an instant.
#:
#: ``not_allowed``: nothing was ever decided. ``withdrawn``: the last decision is a withdrawal.
#: ``ended``: the grant's term has passed. ``name_changed``: the naming the grant rested on no
#: longer names a live place (renamed, merged, deleted or unnamed). ``notice_changed``: the product
#: would now describe this use in words the grant was not made against.
ModelState = Literal[
    "allowed", "not_allowed", "withdrawn", "ended", "name_changed", "notice_changed"
]

#: What a role's whole chain means: a model state, or ``models_changed`` when some of its models are
#: allowed and others were never asked, which is what a chain that gained a model looks like.
UseState = Literal[
    "allowed",
    "not_allowed",
    "withdrawn",
    "ended",
    "name_changed",
    "notice_changed",
    "models_changed",
]

#: The order a chain's non-allowed states are reported in when its models disagree: the one a
#: person most needs to know first. Every non-allowed state is named, so the fold has no default.
_REPORTED_FIRST: Final[tuple[ModelState, ...]] = (
    "withdrawn",
    "name_changed",
    "notice_changed",
    "ended",
    "not_allowed",
)

_NOTICE_FIELDS: Final = frozenset({"models", "host", "purpose", "term_days"})
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
#: The longest notice migration 0097 stores.
_NOTICE_LIMIT: Final = 2000
_USE_KEYS: Final = frozenset({"role", "purpose", "used_by", "honoured_by"})
#: ``module.path:function``, the one spelling of a request path in the registry.
_REQUEST_PATH: Final = re.compile(r"^exulanica(\.[a-z_][a-z0-9_]*)+:[a-z_][a-z0-9_]*$")
_REGISTRY_KEYS: Final = frozenset(
    {"profile", "note", "notice", "fallback_joiner", "term_days", "term_basis", "uses"}
)


def _instant(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a place name right instant must carry a UTC offset")
    return value.astimezone(dt.UTC)


def _sentence(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{what} is a trimmed, non-empty string")
    if _CONTROL.search(value):
        raise ValueError(f"{what} carries a control character")
    return value


@dataclass(frozen=True, slots=True)
class PlaceNameUse:
    """One role a place name may be allowed to go to, and what the product uses it for."""

    role: Role
    purpose: str
    #: Every module in the ``exulanica`` package that names this role, sorted.
    used_by: tuple[str, ...]
    #: The request paths that honour a release, as ``module:function``: each sends this place's
    #: name to the role's models when, and only when, the resolver releases it. Never empty.
    honoured_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlaceNameUses:
    """The declared uses, the notice template, and the term a grant lasts."""

    notice_template: str
    fallback_joiner: str
    term_days: int
    term_basis: str
    uses: tuple[PlaceNameUse, ...]

    @property
    def term(self) -> dt.timedelta:
        return dt.timedelta(days=self.term_days)

    def use(self, role: str) -> PlaceNameUse | None:
        """The use declared for ``role``, or None: an undeclared role is never offered."""
        return next((use for use in self.uses if use.role.value == role), None)

    def handoff(self, use: PlaceNameUse, manifest: Manifest) -> ModelHandoff:
        """Every model the role reaches, at the manifest's endpoint: what a grant covers."""
        return ModelHandoff.hosted(manifest, use.role)

    def notice(self, use: PlaceNameUse, handoff: ModelHandoff) -> str:
        """The exact words a person is shown before allowing ``use``, and that a grant stores.

        Names every model of the chain, primary first, and the host the name travels to. The place's
        own name is not in it, so a stored grant does not keep the name alive.
        """
        if handoff.destination == LOCAL_PROCESS:
            raise ValueError("a place name is offered only to a hosted model")
        if any(identity.role != use.role.value for identity in handoff.identities):
            raise ValueError(f"the hand-over does not belong to the {use.role.value} role")
        text = self.notice_template.format(
            models=self.fallback_joiner.join(identity.model_id for identity in handoff.identities),
            host=urllib.parse.urlsplit(handoff.destination).netloc,
            purpose=use.purpose,
            term_days=self.term_days,
        )
        if len(text) > _NOTICE_LIMIT:
            raise ValueError(f"a place name notice is at most {_NOTICE_LIMIT} characters")
        return _sentence(text, "a place name notice")


def parse_place_name_uses(raw: Mapping[str, Any]) -> PlaceNameUses:
    """The declared uses, refused whole on anything this module does not know."""
    if not isinstance(raw, Mapping) or set(raw) - _REGISTRY_KEYS:
        raise ValueError(f"a place name uses registry has only the keys {sorted(_REGISTRY_KEYS)}")
    if raw.get("profile") != PLACE_NAME_USES_PROFILE:
        raise ValueError(f"a place name uses registry declares {PLACE_NAME_USES_PROFILE}")
    template = _sentence(raw.get("notice"), "the notice template")
    fields = {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}
    if fields != _NOTICE_FIELDS:
        raise ValueError(f"the notice template fills exactly {sorted(_NOTICE_FIELDS)}")
    joiner = raw.get("fallback_joiner")
    if not isinstance(joiner, str) or not joiner.strip() or _CONTROL.search(joiner):
        raise ValueError("the fallback joiner is printable text")
    term_days = raw.get("term_days")
    if type(term_days) is not int or term_days < 1:
        raise ValueError("a place name right lasts a whole, positive number of days")
    basis = _sentence(raw.get("term_basis"), "the term's basis")
    uses = raw.get("uses")
    if not isinstance(uses, list) or not uses:
        raise ValueError("a place name uses registry declares at least one use")
    parsed: list[PlaceNameUse] = []
    for entry in uses:
        if not isinstance(entry, Mapping) or set(entry) != _USE_KEYS:
            raise ValueError(f"a place name use has exactly the keys {sorted(_USE_KEYS)}")
        role = Role(entry["role"])
        used_by = entry["used_by"]
        if (
            not isinstance(used_by, list)
            or not used_by
            or any(not isinstance(item, str) or not item.endswith(".py") for item in used_by)
            or used_by != sorted(set(used_by))
        ):
            raise ValueError(f"the {role.value} use lists its modules once each, sorted")
        honoured_by = entry["honoured_by"]
        if (
            not isinstance(honoured_by, list)
            or not honoured_by
            or any(
                not isinstance(item, str) or not _REQUEST_PATH.fullmatch(item)
                for item in honoured_by
            )
            or honoured_by != sorted(set(honoured_by))
        ):
            raise ValueError(
                f"the {role.value} use names at least one request path that honours a release, "
                "as module:function, once each, sorted"
            )
        parsed.append(
            PlaceNameUse(
                role=role,
                purpose=_sentence(entry["purpose"], f"the {role.value} purpose"),
                used_by=tuple(used_by),
                honoured_by=tuple(honoured_by),
            )
        )
    if len({use.role for use in parsed}) != len(parsed):
        raise ValueError("a role is offered at most once")
    return PlaceNameUses(
        notice_template=template,
        fallback_joiner=joiner,
        term_days=term_days,
        term_basis=basis,
        uses=tuple(parsed),
    )


@lru_cache(maxsize=1)
def load_place_name_uses() -> PlaceNameUses:
    """The registry this package ships, parsed once."""
    raw = files("exulanica.consent").joinpath("place-name-uses.v1.json").read_text("utf-8")
    return parse_place_name_uses(json.loads(raw))


@dataclass(frozen=True, slots=True)
class LastDecision:
    """The last decision recorded for one model and destination of a place, read at one instant.

    ``naming_holds`` is a fact about the place at that instant, read beside the decision: whether
    the naming a grant rests on is still the active naming of a live, unmerged place, stated by the
    account holder who granted it. It is false for a withdrawal, which rests on nothing.
    """

    identity: ModelIdentity
    destination: str
    event: DecisionKind
    decided_at: dt.datetime
    valid_until: dt.datetime | None
    notice: str | None
    naming_holds: bool

    def __post_init__(self) -> None:
        _instant(self.decided_at)
        if self.event not in ("granted", "withdrawn"):
            raise ValueError(f"{self.event!r} is not a place name decision")
        carries = (self.valid_until is not None, self.notice is not None)
        if carries != ((True, True) if self.event == "granted" else (False, False)):
            raise ValueError("a grant carries its notice and its term, and a withdrawal neither")
        if self.valid_until is not None:
            _instant(self.valid_until)
        if self.event == "withdrawn" and self.naming_holds:
            raise ValueError("a withdrawal rests on no naming")


def model_state(decision: LastDecision | None, *, notice: str, at: dt.datetime) -> ModelState:
    """What one model's last decision means at ``at``, against the notice shown for it now."""
    at = _instant(at)
    if decision is None:
        return "not_allowed"
    if decision.event == "withdrawn":
        return "withdrawn"
    if not decision.naming_holds:
        return "name_changed"
    if decision.notice != notice:
        return "notice_changed"
    if decision.valid_until is None or decision.valid_until <= at:
        return "ended"
    return "allowed"


@dataclass(frozen=True, slots=True)
class UseReading:
    """One use of a place's name as a screen presents it, read at one instant."""

    use: PlaceNameUse
    handoff: ModelHandoff
    notice: str
    state: UseState
    #: Each model of the chain, in the chain's order, with its own state.
    models: tuple[tuple[ModelIdentity, ModelState], ...]
    #: When the grants now allowing it were made, and when the first of them ends. Allowed only.
    since: dt.datetime | None
    until: dt.datetime | None
    #: When the last decision about any model of the chain was recorded, or None if never.
    changed_at: dt.datetime | None

    @property
    def allowed(self) -> bool:
        return self.state == "allowed"


def read_use(
    use: PlaceNameUse,
    handoff: ModelHandoff,
    *,
    notice: str,
    decisions: Mapping[tuple[ModelIdentity, str], LastDecision],
    at: dt.datetime,
) -> UseReading:
    """Fold a role's chain into one reading. Allowed only when every model of it is allowed.

    ``decisions`` maps a model and destination to its last decision; a model with none was never
    asked. Decisions for anything outside ``handoff`` are ignored: they cannot reach this use.
    """
    at = _instant(at)
    found = [decisions.get((identity, handoff.destination)) for identity in handoff.identities]
    states = tuple(model_state(decision, notice=notice, at=at) for decision in found)
    if all(state == "allowed" for state in states):
        state: UseState = "allowed"
    elif "allowed" in states and "not_allowed" in states:
        state = "models_changed"
    else:
        state = next(each for each in _REPORTED_FIRST if each in states)
    recorded = [decision for decision in found if decision is not None]
    allowed = state == "allowed"
    return UseReading(
        use=use,
        handoff=handoff,
        notice=notice,
        state=state,
        models=tuple(zip(handoff.identities, states, strict=True)),
        since=min(d.decided_at for d in recorded) if allowed else None,
        until=min(d.valid_until for d in recorded if d.valid_until) if allowed else None,
        changed_at=max((d.decided_at for d in recorded), default=None),
    )
