"""Who decides for a world's beings, as a step of a Companion plan.

A person may ask for a mind in one sentence: an open model for one being, for every being of a
kind or a role, or for everyone, or their own routine back. The step is the request the models
route takes (``POST /world/versions/{version_id}/models/{role_key}``), with the same checks, so a
choice reached through the Companion is the choice sent directly.

What this module holds by construction:

*   **Groups are read from the society's own state.** Everyone here, each kind of being present
    and each role present, with how many each holds. Nothing names a kind or a role in code, so a
    world's groups are whatever its people are.
*   **A step is offered only where the route would take it.** The route has no preview, so its own
    checks run with no lock and nothing recorded (:class:`Minds`, which the actions route hands
    the planner): whoever a choice may not name is left out and counted by the route's own code,
    and a choice the route would refuse whole is ``blocked`` with that code.
*   **What a mind costs is said before the yes.** A model choice asks no model itself; playing the
    world then does. The step carries what the host would reserve for one answer, the world's own
    hourly ceilings, and whether this host asks models here at all.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.decision_roles import decision_roles

__all__ = [
    "EVERYONE",
    "MIND",
    "ROUTINE",
    "SUBJECTS_PER_CHOICE",
    "Group",
    "MindChoice",
    "Minds",
    "PreparedMind",
    "choice_key",
    "groups",
    "mind_value",
    "prepare",
    "said",
    "said_in_full",
    "said_minds",
    "subjects_of",
]

#: The route a choice of who decides is sent to, for the role that decides for people.
MIND: Final = "POST /world/versions/{version_id}/models/{role_key}"
#: The mind that asks no model: a being's own routine.
ROUTINE: Final = "routine"
#: The group that names every being here.
EVERYONE: Final = "everyone"
#: How many subjects one choice's body may name, as the models route's body states it
#: (``RoleChoiceBody.subjects``).
SUBJECTS_PER_CHOICE: Final = 512
#: The codes a choice naming one subject alone is refused by, in the order a step that names
#: nobody else says why nobody was chosen for.
_LEFT_OUT: Final = (
    "person_not_in_this_world",
    "decided_from_outside",
    "being_played",
    "decider_not_allowed",
    "subject_chosen_under_another_role",
)


@dataclass(frozen=True, slots=True)
class MindChoice:
    """One mind a being may be given: a model the server offers the people's role, as its read
    names it, with why this host asks nothing its provider serves when it asks nothing."""

    provider: str
    model_id: str
    name: str
    description: str
    refusal: str | None = None


@dataclass(frozen=True, slots=True)
class Group:
    """Some of a society's beings, by what they share: ``value`` is ``everyone``, ``kind:<key>``
    or ``role:<key>``, ``title`` the words a person would say, ``subjects`` their ids, and
    ``words`` the kind's or the role's own label (None for everyone)."""

    value: str
    title: str
    subjects: tuple[str, ...]
    words: str | None = None


class Minds(Protocol):
    """Who may decide for one version's beings, as the actions route hands it to the planner
    (``exulanica.api.mind_offer.WorldMinds``): the offered models, why this host asks none, what a
    choice would meet and what it would cost."""

    role_key: str

    def models(self) -> Sequence[MindChoice]: ...

    def host_refusal(self) -> str | None: ...

    def preview(
        self, subjects: Sequence[str], model: Mapping[str, str] | None
    ) -> Mapping[str, Any]: ...

    def cost(self, model: Mapping[str, str], subjects: int) -> Mapping[str, Any] | None: ...


def mind_value(provider: str, model_id: str) -> str:
    """A model as a typed step names it, beside :data:`ROUTINE`."""
    return f"model:{provider}/{model_id}"


def _kind_label(reference: Any) -> tuple[str, str] | None:
    """A being's kind as its state names it, by key and label; None for one the library does not
    ship (a kind a workspace made, or none)."""
    if not isinstance(reference, Mapping) or "kind" not in reference or "version" not in reference:
        return None
    found = shipped_thing_kinds().get((str(reference["kind"]), int(reference["version"])))
    return None if found is None else (found.kind, found.label)


def _role_label(role: Any) -> tuple[str, str] | None:
    """A person's role as its state names it: a key and a label, or the one word a society of
    things states; None where it states none."""
    if isinstance(role, Mapping) and role.get("key"):
        return str(role["key"]), str(role.get("label") or role["key"])
    if isinstance(role, str) and role:
        return role, role
    return None


def groups(state: Mapping[str, Any]) -> tuple[Group, ...]:
    """The groups this society holds, read from its state: everyone, then each kind present, then
    each role present, each in the order its first member stands in the state. A role whose people
    are exactly a kind's, or everyone, is the same group said twice and is listed once."""
    [role] = [found for found in decision_roles() if found.subject == "person"]
    present = set(role.adapter.subjects(state))
    people = [person for person in state.get("inhabitants", ()) if person.get("id") in present]
    if not people:
        return ()
    by_kind: dict[str, tuple[str, list[str]]] = {}
    by_role: dict[str, tuple[str, list[str]]] = {}
    for person in people:
        kind = _kind_label(person.get("kind"))
        if kind is not None:
            by_kind.setdefault(kind[0], (kind[1], []))[1].append(str(person["id"]))
        named = _role_label(person.get("role"))
        if named is not None:
            by_role.setdefault(named[0], (named[1], []))[1].append(str(person["id"]))
    everyone = tuple(str(person["id"]) for person in people)
    found = [Group(EVERYONE, "everyone here", everyone)]
    found += [
        Group(f"kind:{key}", f"every {label}", tuple(members), label)
        for key, (label, members) in by_kind.items()
    ]
    seen = {frozenset(group.subjects) for group in found}
    for key, (label, members) in by_role.items():
        if frozenset(members) not in seen:
            found.append(
                Group(f"role:{key}", f"everyone whose role is {label}", tuple(members), label)
            )
    return tuple(found)


def _plain(text: str) -> str:
    """``text`` in lower case with every run of anything but letters and digits as one space."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def said(words: str, utterance: str) -> bool:
    """Whether a person's ``utterance`` says ``words``, a kind's or a role's own label: the label
    is in it as written, whatever follows it (``baker`` in "the bakers")."""
    plain = _plain(words)
    return bool(plain) and f" {plain}" in f" {_plain(utterance)}"


def _name_words(name: str) -> frozenset[str]:
    """The words of a model's served name that could tell it from another: each holds a letter
    and is longer than one character ("nemotron", "nano", "30b", never "3")."""
    return frozenset(
        word for word in _plain(name).split() if len(word) > 1 and re.search(r"[a-z]", word)
    )


def said_in_full(utterance: str, model: MindChoice) -> bool:
    """Whether ``utterance`` holds every telling word of ``model``'s served name."""
    words = _name_words(model.name)
    return bool(words) and words <= set(_plain(utterance).split())


def said_minds(utterance: str, models: Sequence[MindChoice]) -> tuple[MindChoice, ...]:
    """The offered models a person's ``utterance`` names by the words of their served names:
    those with the most of their name's words in it, none where it holds no such word. One model
    is named by "Nemotron 3 Nano 30B" or by "Nano"; "Nemotron" alone names every Nemotron offered.
    The names are the manifest's, so nothing here names a model."""
    spoken = set(_plain(utterance).split())
    counts = [(len(_name_words(model.name) & spoken), model) for model in models]
    most = max((count for count, _ in counts), default=0)
    return () if most == 0 else tuple(model for count, model in counts if count == most)


def subjects_of(whom: str, found: Sequence[Group]) -> tuple[str, ...] | None:
    """The subjects a typed step's ``whom`` names: one being (``being:<id>``) or one of the
    society's groups; None for a group this society does not hold."""
    if whom.startswith("being:"):
        return (whom.removeprefix("being:"),)
    return next((group.subjects for group in found if group.value == whom), None)


def choice_key(
    world_id: str,
    version_id: uuid.UUID,
    choice_seq: int,
    index: int,
    subjects: Sequence[str],
    mind: str,
) -> uuid.UUID:
    """The key a planned choice is sent with: the same plan sent twice answers the choice it
    recorded, and the same words asked again after any other choice are a new one, since the
    society's newest choice is part of it."""
    named = hashlib.sha256("\n".join(sorted(subjects)).encode()).hexdigest()
    return uuid.uuid5(
        uuid.UUID(int=0), f"{world_id}|{version_id}|{choice_seq}|{index}|{named}|{mind}|mind"
    )


@dataclass(frozen=True, slots=True)
class PreparedMind:
    """A choice as a step states it: the request, or the code that blocks it, and what the sheet
    says before the yes."""

    body: dict[str, Any] | None
    code: str | None
    #: What the choice would come to: how many it names, who was left out and why by code, how
    #: many beings models run now and after, the bound, and why this host asks no model if so.
    facts: dict[str, Any]
    cost: dict[str, Any] | None
    spends: bool
    pins: dict[str, Any]


def prepare(
    minds: Minds,
    *,
    world_id: str,
    version_id: uuid.UUID,
    index: int,
    whom: str,
    mind: str,
    found: Sequence[Group],
) -> PreparedMind:
    """The choice ``mind`` for ``whom``, as the models route would take it now, or why not.

    Blocked with the route's own code when the whole choice is refused, or when everybody it
    names is left out (the first of their codes in the order a choice is refused by); with
    ``group_not_here`` for a group this society no longer holds, ``mind_not_offered`` for a model
    the server no longer offers, and ``too_many_subjects_for_one_choice`` past what one choice's
    body may name."""
    offered = {mind_value(model.provider, model.model_id): model for model in minds.models()}
    model = None if mind == ROUTINE else offered.get(mind)
    named = subjects_of(whom, found)
    facts: dict[str, Any] = {
        "subjects": 0,
        "left_out": {},
        "run_now": None,
        "run_after": None,
        "bound": None,
        "host_refusal": None,
        "model_refusal": None,
    }
    if named is None:
        return PreparedMind(None, "group_not_here", facts, None, False, {})
    if mind != ROUTINE and model is None:
        return PreparedMind(None, "mind_not_offered", facts, None, False, {})
    chosen = None if model is None else {"provider": model.provider, "model_id": model.model_id}
    read = minds.preview(named, chosen)
    taken = [str(subject) for subject in read["subjects"]]
    left = {str(code): len(ids) for code, ids in read["left_out"].items()}
    facts.update(
        {
            "subjects": len(taken),
            "left_out": left,
            "run_now": read["run_now"],
            "run_after": read["run_after"],
            "bound": read["bound"],
            "host_refusal": None if model is None else minds.host_refusal(),
            "model_refusal": None if model is None else model.refusal,
        }
    )
    pins = {"choice_seq": read["choice_seq"]}
    code = read["code"]
    if code is None and not taken:
        code = next((known for known in _LEFT_OUT if known in left), None) or next(iter(left))
    if code is None and len(taken) > SUBJECTS_PER_CHOICE:
        code = "too_many_subjects_for_one_choice"
    if code is not None:
        return PreparedMind(None, code, facts, None, False, pins)
    body = {
        "idempotency_key": str(
            choice_key(world_id, version_id, int(read["choice_seq"]), index, taken, mind)
        ),
        "subjects": sorted(taken),
        "model": chosen,
    }
    cost = None if chosen is None else minds.cost(chosen, len(taken))
    return PreparedMind(
        body, None, facts, None if cost is None else dict(cost), model is not None, pins
    )
