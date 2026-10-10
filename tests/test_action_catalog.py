"""The action catalog against everything else that names an action.

One id names one action on every surface, so the catalog (``assets/catalogs/actions``) is held here
to the three places that already state actions, each read from its own source and never through
the catalog's reader: the page's registry (``web/packages/app/src/ui/actions/registry.ts`` and
``planned.ts``, read as text: this package edits neither), the planner's own tables
(``exulanica.selection.action_plan``) and the route table's permission rules. Then the reader's
rules, each broken once: an id is never dropped or reused, nothing that spends or destroys is
offered outside a plan step, and a reserved id names no way to run.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from exulanica.api.permissions import Permission, Requires, rule_for
from exulanica.api.routes import capabilities
from exulanica.selection import action_plan as plan
from exulanica.world import action_catalog
from exulanica.world.action_catalog import ActionCatalogError

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "web/packages/app/src/ui/actions/registry.ts"
PLANNED = ROOT / "web/packages/app/src/ui/actions/planned.ts"
CATALOG = action_catalog.DIRECTORY / "actions.v1.json"
#: The words of the planner's vocabulary the page sends as no action: an appearance is reviewed in
#: Design before it is applied, and ``other`` is the planner saying it cannot express a request.
NEVER_SENT = {"propose_appearance", "apply_appearance", "other"}


def _registry() -> dict[str, dict]:
    """The page's registry as data: each entry's words, its route key and bind, read as text."""
    source = REGISTRY.read_text(encoding="utf-8")
    routes = dict(re.findall(r"^const ([A-Z_]+) = '([^']+)';", source, flags=re.M))
    body = source[source.index("export const ACTIONS") :]
    found: dict[str, dict] = {}
    for ident, rest in re.findall(r"\{\s*id: '([a-z.-]+)'(.*?)\n  \},", body, flags=re.S):

        def text(key: str, rest: str = rest, ident: str = ident) -> str:
            match = re.search(key + r": '((?:[^'\\]|\\.)*)'", rest)
            assert match is not None, (ident, key)
            return match.group(1).replace("\\'", "'")

        operation = re.search(r"operation: ([A-Z_]+)", rest)
        bound = re.search(r"bind: \{([^}]*)\}", rest)
        bind = {}
        for key, value in re.findall(r"(\w+): ('[^']*'|[A-Z_]+)", bound.group(1) if bound else ""):
            bind[key] = value.strip("'") if value.startswith("'") else routes[value]
        found[ident] = {
            "label": text("label"),
            "hint": text("hint"),
            "route": None if operation is None else routes[operation.group(1)],
            "bind": bind,
            "spends_nothing": "spendsNothing: true" in rest,
        }
    return found


def _plan_words() -> dict[str, str | None]:
    """The planner's words and the registry id the page sends each as, read as text."""
    source = PLANNED.read_text(encoding="utf-8")
    table = source[source.index("PLAN_ACTIONS") :]
    table = table[: table.index("});")]
    return {
        word: None if ident == "null" else ident.strip("'")
        for word, ident in re.findall(r"^\s+([a-z_]+): ('[a-z.-]+'|null),", table, flags=re.M)
    }


def _document() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _write(directory: Path, version: int, document: dict) -> None:
    (directory / f"actions.v{version}.json").write_text(json.dumps(document), encoding="utf-8")


# -- the catalog against the page ----------------------------------------------------------------


def test_every_action_the_page_sends_by_a_route_is_an_entry_with_the_same_words_and_route():
    registry = _registry()
    routed = {ident: entry for ident, entry in registry.items() if entry["route"] is not None}
    # Counted from the page's own file, so a registry that changes shape fails here by name.
    assert len(registry) == 35 and len(routed) == 21
    offered = {action.id: action for action in action_catalog.offered()}
    assert set(offered) == set(routed)
    for ident, entry in routed.items():
        action = offered[ident]
        assert (action.label, action.hint) == (entry["label"], entry["hint"]), ident
        assert (action.route, dict(action.bind)) == (entry["route"], entry["bind"]), ident


def test_an_id_that_is_not_offered_is_reserved_and_names_no_way_to_run():
    registry = _registry()
    held_back = {a.id: a for a in action_catalog.actions() if a.status != action_catalog.OFFERED}
    assert set(held_back) == {
        "creatures.make",
        "world.draft",
        "world.observe",
        "beings.answer",
        "world.leave",
        "world.report",
    }
    for ident, action in held_back.items():
        assert action.status == action_catalog.RESERVED
        assert (action.route, action.plan_word, dict(action.bind)) == (None, None, {})
        # No reserved id is one the page sends by a route today.
        assert registry.get(ident, {"route": None})["route"] is None
    # The two actions every role holds, and no others.
    assert {a.id for a in action_catalog.actions() if a.protected} == {
        "world.leave",
        "world.report",
    }
    # The ids of the page that only open a panel are how the page works: none is an action here.
    panels = {ident for ident, entry in registry.items() if entry["route"] is None}
    assert panels - set(held_back) == {
        ident for ident in registry if ident.endswith(".open") or ident == "people.decides"
    }
    assert not (panels - {"creatures.make"}) & {a.id for a in action_catalog.actions()}


def test_the_plan_word_of_each_action_is_the_one_the_page_sends_it_as():
    sent_as = {word: ident for word, ident in _plan_words().items() if ident is not None}
    stated = {
        action.plan_word: action.id
        for action in action_catalog.offered()
        if action.plan_word is not None
    }
    assert stated == sent_as
    # Every routed action but making a world can be planned.
    assert [a.id for a in action_catalog.offered() if a.plan_word is None] == ["world.make"]


# -- the catalog against the planner -------------------------------------------------------------


def test_each_plan_word_is_the_planner_s_and_commits_by_the_action_s_route():
    edits = {operation.value: row.commit for operation, row in plan._MATRIX.items()}
    simulation = {action.value for action in plan.SimulationAction}
    simulation_routes = {
        plan.CONTROL,
        plan.CONTROL_STEP,
        plan.BRING_PEOPLE,
        plan.PRESENCE,
    }
    words = set()
    for action in action_catalog.offered():
        word = action.plan_word
        if word is None:
            continue
        words.add(word)
        if word in edits:
            assert edits[word] == action.route, action.id
        else:
            assert word in simulation and action.route in simulation_routes, action.id
    # Every word the planner can draft as a step is some action's, but ``other``, which is the
    # planner saying it cannot express a request; the page's table holds two words more, for an
    # appearance, which is another kind of plan and is sent as no action.
    planner = {operation.value for operation in plan.WorldEditOperation} | simulation
    assert planner - words == {"other"}
    assert set(_plan_words()) - planner == NEVER_SENT - {"other"}
    assert {word for word, ident in _plan_words().items() if ident is None} == NEVER_SENT


# -- the catalog against the route table ---------------------------------------------------------


def test_an_action_costs_the_one_who_acts_exactly_where_its_route_asks_a_model():
    registry = _registry()
    spending = set()
    for action in action_catalog.offered():
        method, _, path = action.route.partition(" ")
        rule = rule_for(method, path)
        assert isinstance(rule, Requires), action.id
        asks = Permission.MODEL_INVOKE in rule.permissions
        # A route that needs the right to ask a model and asks none (setting a budget) spends
        # nothing, as the page's registry already says of it.
        narrowed = registry[action.id]["spends_nothing"]
        assert (action.cost_class != "none") == (asks and not narrowed), action.id
        if action.cost_class != "none":
            spending.add(action.id)
    assert spending == {"pieces.request", "minds.choose"}


def test_everything_that_spends_or_destroys_runs_as_a_plan_step_under_a_yes():
    touched = {a.id: a for a in action_catalog.offered() if a.spends_or_destroys}
    assert set(touched) == {
        "pieces.request",
        "minds.choose",
        "objects.undo",
        "objects.remove",
        "things.remove",
    }
    assert all(action.plan_word is not None for action in touched.values())


# -- the reader's rules, each broken once --------------------------------------------------------


def _changed(ident: str, **members) -> dict:
    document = copy.deepcopy(_document())
    [entry] = [entry for entry in document["entries"] if entry["id"] == ident]
    entry.update(members)
    return document


@pytest.mark.parametrize(
    ("document", "said"),
    [
        (_changed("minds.choose", plan_word=None), "spends or destroys and runs as no plan step"),
        (_changed("things.remove", plan_word=None), "spends or destroys and runs as no plan step"),
        (_changed("clock.play", route=None), "is offered and names no route"),
        (_changed("world.leave", route="POST /somewhere"), "still names a way to run"),
        (_changed("clock.play", cost_class="a little"), "a member this catalog cannot hold"),
        (_changed("clock.play", subjects=[]), "a member this catalog cannot hold"),
        (_changed("clock.play", id="Clock.Play", key="Clock.Play"), "is no action id"),
        (_changed("clock.pause", id="clock.play", key="clock.play"), "an id is stated twice"),
        (_changed("clock.pause", plan_word="play"), "drafted by one plan word"),
    ],
)
def test_a_catalog_that_breaks_a_rule_is_refused_by_name(document, said):
    with pytest.raises(ActionCatalogError, match=said):
        action_catalog.read(document)


def test_a_later_version_holds_every_id_an_earlier_one_held(tmp_path):
    first = _document()
    _write(tmp_path, 1, first)
    assert [a.id for a in action_catalog.load(tmp_path)] == [e["id"] for e in first["entries"]]

    # An id is retired where it is no longer offered: it stays, with no way to run.
    retired = _changed("clock.advance", status="retired", route=None, plan_word=None)
    retired["catalog_version"] = 2
    _write(tmp_path, 2, retired)
    [kept] = [action for action in action_catalog.load(tmp_path) if action.id == "clock.advance"]
    assert kept.status == action_catalog.RETIRED

    # Dropped, it is refused: a role may still store it.
    dropped = copy.deepcopy(first)
    dropped["entries"] = [entry for entry in dropped["entries"] if entry["id"] != "clock.advance"]
    dropped["catalog_version"] = 2
    _write(tmp_path, 2, dropped)
    with pytest.raises(ActionCatalogError, match=r"clock\.advance was in an earlier version"):
        action_catalog.load(tmp_path)

    # Renamed is dropped and added: refused the same way.
    renamed = _changed("clock.advance", id="clock.step", key="clock.step")
    renamed["catalog_version"] = 2
    _write(tmp_path, 2, renamed)
    with pytest.raises(ActionCatalogError, match=r"clock\.advance was in an earlier version"):
        action_catalog.load(tmp_path)

    # A retired id is never used again.
    _write(tmp_path, 2, retired)
    again = copy.deepcopy(first)
    again["catalog_version"] = 3
    _write(tmp_path, 3, again)
    with pytest.raises(ActionCatalogError, match=r"clock\.advance was retired and is used again"):
        action_catalog.load(tmp_path)


def test_versions_are_numbered_from_one_with_none_missing(tmp_path):
    third = _document()
    third["catalog_version"] = 3
    _write(tmp_path, 1, _document())
    _write(tmp_path, 3, third)
    with pytest.raises(ActionCatalogError, match="its versions are not 1 to 2"):
        action_catalog.load(tmp_path)
    (tmp_path / "actions.v3.json").unlink()
    wrong = _document()
    wrong["catalog_version"] = 5
    _write(tmp_path, 1, wrong)
    with pytest.raises(ActionCatalogError, match="its catalog_version is not 1"):
        action_catalog.load(tmp_path)


# -- what the capability read serves of it -------------------------------------------------------


def test_an_action_is_served_with_its_route_s_permissions_and_its_operation_s_state():
    def described(route: str, state: str, code: str | None = None, **bind: str) -> dict:
        return {"operation": route, "bind": bind, "state": state, "code": code}

    operations = [
        described(plan.CONTROL, "unavailable", "society_unavailable"),
        # Another role's choice comes first: the action's own bind picks its operation.
        described(plan.MIND, "unsupported", "role_not_hosted", role_key="traffic_signal"),
        described(plan.MIND, "available", role_key="society_decision"),
    ]
    held = frozenset({Permission.WORLD_WRITE})
    served = {action["id"]: action for action in capabilities._actions(operations, held)}
    assert list(served) == [action.id for action in action_catalog.offered()]

    # One route performs three actions: each is served with that route's state.
    for ident in ("clock.play", "clock.pause", "clock.speed"):
        assert (served[ident]["projected"], served[ident]["state"], served[ident]["code"]) == (
            True,
            "unavailable",
            "society_unavailable",
        )
        assert served[ident]["requires"] == ["world.write"] and served[ident]["permitted"] is True
    mind = served["minds.choose"]
    assert (mind["projected"], mind["state"]) == (True, "available")
    # Its route also needs the right to ask a model, which this caller does not hold.
    assert mind["requires"] == ["model.invoke", "world.write"] and mind["permitted"] is False
    assert mind["runs_by"] == {
        "route": plan.MIND,
        "bind": {"role_key": "society_decision"},
        "plan_step": "choose_mind",
    }
    assert mind["cost_class"] == "model_calls"
    # An action no operation of the version projects says so and states no state: its route's
    # permissions are still its own.
    play = served["beings.play"]
    assert (play["projected"], play["state"], play["code"]) == (False, None, None)
    assert play["requires"] == ["world.write"] and play["permitted"] is True
    # Nothing of a reserved id is served.
    assert not {"world.leave", "world.report", "world.draft", "beings.answer"} & set(served)
    # A caller holding nothing is permitted nothing.
    assert not any(action["permitted"] for action in capabilities._actions(operations, frozenset()))
