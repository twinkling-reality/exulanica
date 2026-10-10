"""The actions a person may take on a world and what is in it, as one catalog of stable ids.

An action is something a person does to a world, a being, a thing or a placed object: placing a
bench, choosing who decides for a knight, letting the town run. Each has one id that every
surface uses for it, so the list a page draws, the step a Companion plans and the set of actions a
role grants are the same list. The catalog is data
(``assets/catalogs/actions/actions.v<N>.json``): for each id its words, what it acts on, the route
that performs it and the word the planner drafts it by, what it costs the one who acts and the
world, what it destroys, and whether every role must hold it.

What this module holds by construction:

*   **An id is never renamed or reused.** Roles and published experiences store ids. A later
    version of the catalog holds every id an earlier one held; an id no longer offered stays,
    marked retired, and a retired id is never offered again (:func:`_succession`).
*   **Nothing that spends or destroys is sent from a list.** An offered entry that costs anything,
    or destroys anything, runs as a plan step under a yes: it names the planner's word for it, and
    the plan's sheet states the cost or the loss first. No other way through is accepted, since no
    route serves both a preview and a confirmation outside a plan.
*   **A reserved id is named and never served.** It fixes the spelling of an action whose route
    does not exist yet, so the id cannot be invented twice; it carries no route and no plan word.
*   **Permission is the route's own.** The catalog names a route and never a permission, so what
    an action requires cannot disagree with what its route checks.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

__all__ = [
    "COST_CLASSES",
    "DIRECTORY",
    "FAMILIES",
    "PROFILE",
    "STATUSES",
    "SUBJECTS",
    "Action",
    "ActionCatalogError",
    "actions",
    "load",
    "offered",
    "read",
]

_ROOT: Final = Path(__file__).resolve().parents[2]
DIRECTORY: Final = _ROOT / "assets/catalogs/actions"
PROFILE: Final = "exulanica.action-catalog/v1"
#: An id's standing: served and planned; named before its route exists; or no longer offered.
OFFERED: Final = "offered"
RESERVED: Final = "reserved"
RETIRED: Final = "retired"
STATUSES: Final = (OFFERED, RESERVED, RETIRED)
#: How an action runs: a person changing or running a world; a person acting as a being; a
#: person being in a world (watching, leaving, reporting).
FAMILIES: Final = ("workshop", "being", "visit")
#: What an action acts on.
SUBJECTS: Final = ("workspace", "world", "being", "thing", "object", "part")
#: What an action costs the one who acts: nothing; model calls, bounded by a sheet served before
#: the yes; or generation, served with its time and cost first.
COST_CLASSES: Final = ("none", "model_calls", "generation")
#: What an action may cost the world it is taken in, apart from the one who acts.
WORLD_COST_CLASSES: Final = ("none", "model_ask_brought_forward")
_ID: Final = re.compile(r"[a-z]+(?:-[a-z]+)*\.[a-z]+(?:-[a-z]+)*")
_FILE: Final = re.compile(r"actions\.v([1-9][0-9]*)\.json")
_MEMBERS: Final = frozenset(
    {"key", "id", "status", "family", "subjects", "words", "route", "bind", "plan_word"}
    | {"cost_class", "world_cost_class", "destroys", "protected", "reason"}
)


class ActionCatalogError(ValueError):
    """A catalog of actions that cannot be read as one."""


@dataclass(frozen=True, slots=True)
class Action:
    """One action: its id and everything the catalog states of it."""

    id: str
    status: str
    family: str
    subjects: tuple[str, ...]
    label: str
    hint: str
    #: The route that performs it, as a capability read names routes ("POST /world/..."), and
    #: the bind values that pick this action where one route performs several; None where the
    #: id is reserved or retired.
    route: str | None
    bind: Mapping[str, str]
    #: The word the Companion's planner drafts this action by, or None where it plans none.
    plan_word: str | None
    cost_class: str
    world_cost_class: str
    destroys: tuple[str, ...]
    #: An action every role holds: no creator's role may leave it out.
    protected: bool

    @property
    def spends_or_destroys(self) -> bool:
        return self.cost_class != "none" or bool(self.destroys)

    def view(self) -> dict[str, Any]:
        """The action as a read serves it, with nothing of any caller in it."""
        return {
            "id": self.id,
            "family": self.family,
            "subjects": list(self.subjects),
            "words": {"label": self.label, "hint": self.hint},
            "cost_class": self.cost_class,
            "world_cost_class": self.world_cost_class,
            "destroys": list(self.destroys),
            "protected": self.protected,
            "runs_by": {
                "route": self.route,
                "bind": dict(self.bind),
                "plan_step": self.plan_word,
            },
        }


def _entry(raw: Any, where: str) -> Action:
    if not isinstance(raw, Mapping) or set(raw) != _MEMBERS:
        raise ActionCatalogError(f"{where}: an entry states exactly {sorted(_MEMBERS)}")
    ident = raw["id"]
    if not isinstance(ident, str) or _ID.fullmatch(ident) is None or raw["key"] != ident:
        raise ActionCatalogError(f"{where}: {ident!r} is no action id, or its key is another")
    words = raw["words"]
    texts = (
        [words.get("label"), words.get("hint")]
        if isinstance(words, Mapping) and set(words) == {"label", "hint"}
        else [None]
    )
    subjects = raw["subjects"]
    bind = raw["bind"]
    destroys = raw["destroys"]
    plain = (
        raw["status"] in STATUSES
        and raw["family"] in FAMILIES
        and isinstance(subjects, list)
        and bool(subjects)
        and all(subject in SUBJECTS for subject in subjects)
        and len(set(subjects)) == len(subjects)
        and all(isinstance(text, str) and text.strip() for text in texts)
        and (raw["route"] is None or isinstance(raw["route"], str))
        and isinstance(bind, Mapping)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in bind.items())
        and (raw["plan_word"] is None or isinstance(raw["plan_word"], str))
        and raw["cost_class"] in COST_CLASSES
        and raw["world_cost_class"] in WORLD_COST_CLASSES
        and isinstance(destroys, list)
        and all(isinstance(code, str) and code for code in destroys)
        and isinstance(raw["protected"], bool)
    )
    if not plain:
        raise ActionCatalogError(f"{where}: {ident} states a member this catalog cannot hold")
    action = Action(
        id=ident,
        status=raw["status"],
        family=raw["family"],
        subjects=tuple(subjects),
        label=texts[0],
        hint=texts[1],
        route=raw["route"],
        bind=dict(bind),
        plan_word=raw["plan_word"],
        cost_class=raw["cost_class"],
        world_cost_class=raw["world_cost_class"],
        destroys=tuple(destroys),
        protected=raw["protected"],
    )
    if action.status == OFFERED:
        if action.route is None:
            raise ActionCatalogError(f"{where}: {ident} is offered and names no route")
        if action.spends_or_destroys and action.plan_word is None:
            # Nothing that spends or destroys is sent from a list: it runs under a plan's yes.
            raise ActionCatalogError(
                f"{where}: {ident} spends or destroys and runs as no plan step"
            )
    elif action.route is not None or action.plan_word is not None or action.bind:
        raise ActionCatalogError(
            f"{where}: {ident} is {action.status} and still names a way to run"
        )
    return action


def read(document: Any, where: str = "the catalog") -> tuple[Action, ...]:
    """The actions ``document`` states, in its order; refused by name where it is no catalog of
    actions, an id is stated twice, or two offered ids are drafted by one plan word."""
    if (
        not isinstance(document, Mapping)
        or document.get("profile") != PROFILE
        or not isinstance(document.get("entries"), list)
    ):
        raise ActionCatalogError(f"{where}: not a catalog of profile {PROFILE}")
    found = tuple(_entry(raw, where) for raw in document["entries"])
    ids = [action.id for action in found]
    if len(set(ids)) != len(ids):
        raise ActionCatalogError(f"{where}: an id is stated twice")
    words = [action.plan_word for action in found if action.plan_word is not None]
    if len(set(words)) != len(words):
        raise ActionCatalogError(f"{where}: two actions are drafted by one plan word")
    return found


def _succession(earlier: Sequence[Action], later: Sequence[Action], where: str) -> None:
    """Refuse a ``later`` version that drops an id ``earlier`` held, or offers again one it
    retired: an id, once shipped, names one action for good."""
    after = {action.id: action for action in later}
    for action in earlier:
        kept = after.get(action.id)
        if kept is None:
            raise ActionCatalogError(
                f"{where}: {action.id} was in an earlier version and is gone; an id no longer "
                "offered stays, marked retired"
            )
        if action.status == RETIRED and kept.status != RETIRED:
            raise ActionCatalogError(f"{where}: {action.id} was retired and is used again")


def load(directory: Path) -> tuple[Action, ...]:
    """The newest version of the catalog in ``directory``, after every version there is read and
    each is held to the one before it. Versions are ``actions.v1.json``, ``actions.v2.json`` and so
    on, with none missing."""
    versions: dict[int, Path] = {}
    for path in directory.iterdir():
        match = _FILE.fullmatch(path.name)
        if match is not None:
            versions[int(match.group(1))] = path
    if not versions or sorted(versions) != list(range(1, len(versions) + 1)):
        raise ActionCatalogError(f"{directory}: its versions are not 1 to {len(versions)}")
    earlier: tuple[Action, ...] = ()
    for number in sorted(versions):
        path = versions[number]
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("catalog_version") != number:
            raise ActionCatalogError(f"{path.name}: its catalog_version is not {number}")
        later = read(document, path.name)
        _succession(earlier, later, path.name)
        earlier = later
    return earlier


@cache
def actions() -> tuple[Action, ...]:
    """Every action the shipped catalog states, whatever its standing."""
    return load(DIRECTORY)


def offered() -> tuple[Action, ...]:
    """The actions a read may serve and a plan may hold: the offered ones."""
    return tuple(action for action in actions() if action.status == OFFERED)
