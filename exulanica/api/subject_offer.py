"""Read-only subject properties and catalog actions from the served authorities.

This builder receives values and the caller's grant explicitly. It has no session, database,
provider or writer, so an offer cannot authorize a write or initiate spending.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from exulanica.api.permissions import Permission
from exulanica.api.routes.capabilities import _actions
from exulanica.world.errors import UnknownWorldResource

PROFILE = "exulanica.subject-offer/v1"


@dataclass(frozen=True, slots=True)
class SubjectOfferContext:
    capabilities: Mapping[str, Any]
    read: Mapping[str, Any]
    facts: Mapping[str, str]
    card: Mapping[str, Any] | None = None
    placed_id: str | None = None
    play: Mapping[str, Any] | None = None
    control: Mapping[str, Any] | None = None
    budget: Mapping[str, Any] | None = None
    population: int | None = None
    budget_supported: bool = False


def subject_reference(ref: str) -> tuple[str, uuid.UUID | None]:
    if ref == "world":
        return "world", None
    kind, _, ident = ref.partition(":")
    if kind in {"being", "thing"}:
        try:
            found = uuid.UUID(ident)
        except ValueError:
            pass
        else:
            if str(found) == ident:
                return kind, found
    raise UnknownWorldResource("no served subject at this reference")


def _state(view: dict[str, Any], code: str | None) -> None:
    """Refine only an available or unprojected operation, leaving prior refusals intact."""
    if view["state"] not in {None, "available"}:
        return
    view.update(state="available" if code is None else "unavailable", code=code)


def subject_offer(
    context: SubjectOfferContext, ref: str, held: frozenset[Permission]
) -> dict[str, Any]:
    subject_type, ident = subject_reference(ref)
    cap = context.capabilities
    card = context.card
    if subject_type != "world":
        if card is None or card["thing_id"] != str(ident):
            raise UnknownWorldResource("no such subject in this version")
        actual = "being" if card["subject_id"] is not None else "thing"
        if actual != subject_type:
            raise UnknownWorldResource("no such subject in this version")
    actions = []
    for view in _actions(cap["operations"], held, facts=dict(context.facts)):
        if subject_type not in view["subjects"]:
            continue
        action_id = view["id"]
        bind = {"version_id": cap["version_id"], **view["runs_by"]["bind"]}
        if ident is not None:
            bind.update(subject_id=str(ident), thing_id=str(ident))
        if action_id in {"things.move", "things.remove"}:
            if context.placed_id is None:
                _state(view, "thing_not_placed")
            else:
                bind["thing_id"] = context.placed_id
        elif action_id == "things.look":
            _state(view, None if card and card["looks"] else "no_looks_available")
        elif action_id == "beings.play":
            play = context.play
            _state(
                view,
                "subject_fact_unavailable"
                if play is None
                else (play["code"] or ("no_change" if play["playing"] else None)),
            )
        elif action_id == "beings.give-back":
            _state(
                view,
                None if context.play and str(ident) in context.play["played"] else "not_played",
            )
        elif action_id == "minds.choose" and card is not None:
            decider = card["decider"]
            if decider is None or not decider["may_change"]:
                _state(view, (decider or {}).get("refusal") or "kind_keeps_its_decider")
        elif action_id == "minds.budget":
            _state(view, None if context.budget_supported else "budget_not_for_this_role")
        if view["state"] is None:
            _state(view, "operation_not_projected")
        view["runs_by"] = {**view["runs_by"], "bind": bind}
        actions.append(view)
    offered = {view["id"]: view for view in actions}
    properties = []

    def property_(
        key: str,
        type_: str,
        value: Any,
        label: str,
        by: tuple[str, ...] = (),
        fixed: str = "fixed",
        options: Any = None,
    ) -> None:
        ways = [offered[action] for action in by if action in offered]
        changeable = any(view["permitted"] and view["state"] == "available" for view in ways)
        code = (
            None
            if changeable
            else (
                "not_permitted"
                if ways and not any(view["permitted"] for view in ways)
                else next((view["code"] for view in ways if view["code"]), fixed)
            )
        )
        entry = dict(
            key=key,
            type=type_,
            value=value,
            words={"label": label},
            changeable=changeable,
            by=list(by),
            code=code,
        )
        if options is not None:
            entry["options"] = options
        properties.append(entry)

    if subject_type == "world":
        name = cap["kind"]
        kind = {"key": cap["kind"], "label": cap["kind"]}
        property_("kind", "kind", kind, "Kind")
        property_(
            "holds_people", "boolean", cap["society"]["held"], "People here", ("people.bring-in",)
        )
        if context.population is not None:
            property_("population", "integer", context.population, "People")
        if context.control is not None:
            property_(
                "play", "enum", context.control["mode"], "Playing", ("clock.play", "clock.pause")
            )
            property_("speed", "integer", context.control["speed"], "Speed", ("clock.speed",))
        if context.budget is not None:
            property_(
                "mind_budget", "budget", dict(context.budget), "Budget for minds", ("minds.budget",)
            )
    else:
        assert card is not None
        name = card["label"]
        kind = dict(card["kind"])
        property_("name", "text", name, "Name", fixed="not_built")
        property_("kind", "kind", kind, "Kind")
        property_(
            "decided_by",
            "decider",
            card["decider"],
            "Who decides",
            ("minds.choose", "beings.play", "beings.give-back")
            if ident and subject_type == "being"
            else (),
        )
        property_("look", "look", card["look"], "Look", ("things.look",), options=card["looks"])
        property_(
            "where",
            "place",
            card["where"],
            "Where",
            ("people.direct",) if subject_type == "being" else ("things.move",),
        )
        property_("holding", "things", card["holding"], "Holding")
        property_("can_do", "abilities", card["abilities"], "Can do")
        property_("offers", "offers", card["offers"], "Offers")
    return dict(
        profile=PROFILE,
        world_id=cap["world_id"],
        version_id=cap["version_id"],
        subject={"ref": ref, "type": subject_type, "kind": kind, "name": name},
        properties=properties,
        actions=actions,
        read=dict(context.read),
    )
