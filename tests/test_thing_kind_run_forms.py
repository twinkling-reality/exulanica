"""What a society runs of a kind its workspace keeps holds no word a person wrote.

A run form (``exulanica.thing-kind-run/v1``, :mod:`exulanica.things.run_forms`) is built from a
kept kind, its drafted plan and that plan's recipe. Each fixture creature is assembled here with
nonsense words for everything a person's words reach (its label and key, its summary, its recipe's
appearance, the digest of the words), and none of them may be found in the run form. The expected
body names are written by hand from the fixtures' figures and the names catalog's entries; the
vocabulary every string is held to is read here from the catalogs' own files.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import body_grammar, read_body_recipe
from exulanica.things.creatures import assemble_creature
from exulanica.things.run_forms import (
    RUN_FORM_FIELDS,
    RUN_FORM_PROFILE,
    RunFormRefused,
    body_name,
    body_names,
    read_run_form,
    run_form,
)

from creature_support import FIXTURES, form_of

ROOT = Path(__file__).resolve().parent.parent
THINGS = ROOT / "assets" / "catalogs" / "things"
NAMES = sorted(FIXTURES["development"] | FIXTURES["held_out"])
#: Words no catalog holds, one for each place a person's words reach.
LABEL = "quorzle wibbet"
SUMMARY = "Zanthrefol mipwick durlow skenth, a vorplequist of the grennock."
APPEARANCE = "Brindlefex ovanthrel skimmerdusk plates over a jorrowmell hide."
WORDS_SHA256 = "ab" * 32
CANARIES = (
    "quorzle",
    "wibbet",
    "zanthrefol",
    "mipwick",
    "durlow",
    "skenth",
    "vorplequist",
    "grennock",
    "brindlefex",
    "ovanthrel",
    "skimmerdusk",
    "jorrowmell",
    WORDS_SHA256,
)
BY = {
    "kind": "model",
    "provider": "frobnitz_provider",
    "model_id": "frobnitz/model",
    "prompt_version": "frobnitz-prompt-1",
    "prompt_sha256": "cd" * 32,
    "words_sha256": WORDS_SHA256,
    "execution_sha256": None,
}
#: The name each fixture's body is given, by hand: at most two features in the catalog's rank
#: order (heads past one, wings, legs, tentacles, arms, fins, a long legless body), then the noun.
EXPECTED_NAMES = {
    "bat": "winged two legged creature",
    "centaur": "four legged two armed creature",
    "crocodile": "four legged creature",
    "dragon": "winged four legged creature",
    "floating_eight": "eight tentacled creature",
    "four_arms": "two legged four armed creature",
    "horse": "four legged creature",
    "raptor": "two legged two armed creature",
    "serpent": "long bodied creature",
    "spider": "eight legged creature",
    "ten_legs": "ten legged creature",
    "three_heads": "three headed four legged creature",
    "winged_horse": "winged four legged creature",
}


#: What a decider reads of four of the bodies, by hand from the fixtures' figures and the catalog's
#: sentence: metres to a tenth below ten, parts by count in rank order, a tail, moving, carrying.
EXPECTED_SUMMARIES = {
    "dragon": "A creature about 12 m long and 2.6 m high with one head, two wings, four legs and a "
    "tail. It moves over the ground. It carries a thing in its jaws.",
    "serpent": "A creature about 9.0 m long and 0.9 m high with one head. It moves over the "
    "ground. It carries a thing in its jaws.",
    "floating_eight": "A creature about 1.6 m long and 3.0 m high with one head and eight "
    "tentacles. It cannot move from where it is.",
    "four_arms": "A creature about 1.2 m long and 3.6 m high with one head, two legs and four "
    "arms. It moves over the ground. It carries things in its hands.",
}


def _creature(name: str) -> Any:
    form = form_of(name, label=LABEL, moves=[] if name == "floating_eight" else None)
    form["summary"] = SUMMARY
    form["appearance"] = APPEARANCE
    if name == "floating_eight":
        # A floating body does not move here, so it only waits and speaks.
        for ability in ("stand", "follow"):
            form[f"can_{ability}"] = False
            form[f"weight_{ability}"] = 0
    return assemble_creature(assembled_form(form, body_grammar()), by=BY)


def _run_form(name: str) -> dict[str, Any]:
    creature = _creature(name)
    recipe = read_body_recipe(dict(creature.recipe))
    return run_form(creature.kind, creature.plan, recipe)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [found for key, item in value.items() for found in (key, *_strings(item))]
    if isinstance(value, list):
        return [found for item in value for found in _strings(item)]
    return []


def _catalog_keys(stem: str) -> set[str]:
    return {entry["key"] for entry in json.loads((THINGS / f"{stem}.json").read_text())["entries"]}


def test_the_fixtures_and_the_expected_names_are_the_same_creatures():
    assert set(EXPECTED_NAMES) == set(NAMES)
    assert len(NAMES) == 13


@pytest.mark.parametrize("name", NAMES)
def test_a_run_form_holds_none_of_the_words_its_kind_was_drafted_with(name):
    creature = _creature(name)
    # The positive control: the kept documents do hold the words.
    kept = canonical_json(
        [dict(creature.kind.document), dict(creature.plan_document), dict(creature.recipe)]
    ).decode()
    for canary in CANARIES:
        assert canary in kept.lower(), canary
    form = _run_form(name)
    text = canonical_json(form).decode().lower()
    for canary in CANARIES:
        assert canary not in text, canary
    # Nor any of the drafting model's provenance, nor the recipe's digest, which covers the
    # appearance drafted from the words.
    provenance = [value for key, value in BY.items() if value and key != "kind"]
    for value in (*provenance, creature.recipe_sha256, creature.plan.title):
        assert str(value).lower() not in text, value


@pytest.mark.parametrize("name", NAMES)
def test_every_string_of_a_run_form_is_a_catalog_name_a_module_a_digest_or_a_figure_s_name(name):
    grammar = _catalog_keys("body-grammar.v1")
    names = json.loads((THINGS / "body-names.v1.json").read_text())["entries"]
    name_words = {word for entry in names for word in entry["words"].replace("{count}", "").split()}
    allowed = (
        grammar
        | _catalog_keys("abilities.v1")
        | _catalog_keys("offers.v1")
        | RUN_FORM_FIELDS
        | {RUN_FORM_PROFILE, "being", "workspace", "source", "sha256", "body-names/v1"}
        | {"plan_sha256", "extent_mm", "reach_mm", "posture", "upper_body", "spine", "heads"}
        | {"limbs", "tail", "holds_with", "colours", "sockets", "length", "width", "height", "span"}
        | {"neck", "jaw", "role", "count", "segments", "key", "holds", "length_mm_maximum"}
        | {"grip_section_mm_maximum", "module", "parameters", "weights", "follow_holders_of"}
        | {"default", "allowed", "routine", "model", "person", "none", "jaws", "hands"}
        | {"front_claws"}
        # The one figure a walking move may state: its pace (the gaits catalog).
        | {"pace_permille"}
    )
    # The movement modules a body may move by: those the body grammar's movements name.
    grammar_entries = json.loads((THINGS / "body-grammar.v1.json").read_text())["entries"]
    modules = {
        entry["spec"]["module"]
        for entry in grammar_entries
        if entry["group"] == "movement" and entry["spec"].get("module")
    }
    form = _run_form(name)
    for string in _strings(form):
        if string in allowed or re.fullmatch(r"[0-9a-f]{64}", string):
            continue
        if string in modules:
            continue
        if re.fullmatch(r"(mouth|hand|claw|float)(\.(left|right|head[1-9]))?", string):
            continue
        if string == form["label"]:
            assert set(string.split()) <= name_words, string
            continue
        if string == form["summary"]:
            sentence = next(e["spec"] for e in names if e["key"] == "summary")
            texts = [sentence[k] for k in ("lead", "with", "tail", "join")]
            texts += [*sentence["moves"].values(), *sentence["holds"].values()]
            texts += [e["spec"]["one"] for e in names if e["group"] == "part"]
            words = {w for text in texts for w in re.findall(r"[A-Za-z]+", text)} | name_words
            assert set(re.findall(r"[A-Za-z]+", string)) <= words | {"m"}, string
            continue
        raise AssertionError(f"{name}: {string!r} is in no vocabulary")


def test_every_count_the_grammar_admits_of_a_counted_part_has_a_number_to_be_named_by():
    """A counted feature names its count in a word, and a count with no word is passed over, so
    the body would be named without the feature. The names catalog holds a word for every count
    the body grammar admits of each part it counts: a grammar that grows past them fails here
    until the names do. The most of each part is read from the grammar's own file: single limbs
    for a part that comes in pairs."""
    directory = Path(__file__).resolve().parents[1] / "assets" / "catalogs" / "things"
    grammar = json.loads((directory / "body-grammar.v1.json").read_text(encoding="utf-8"))
    names = json.loads((directory / "body-names.v1.json").read_text(encoding="utf-8"))
    specs = {entry["key"]: entry["spec"] for entry in grammar["entries"]}
    most = {
        "heads": specs["head"]["count"]["maximum"],
        "legs": 2 * specs["leg"]["pairs"]["maximum"],
        "arms": 2 * specs["arm"]["pairs"]["maximum"],
        "tentacles": specs["tentacle"]["count"]["maximum"],
    }
    # By hand from the grammar: five heads, six pairs of legs, three of arms, twelve tentacles.
    assert most == {"heads": 5, "legs": 12, "arms": 6, "tentacles": 12}
    counted = {
        entry["spec"]["part"]: entry["spec"]["least"]
        for entry in names["entries"]
        if entry["group"] == "feature" and entry["spec"]["counted"]
    }
    assert set(counted) == set(most)
    numbers = {e["spec"]["value"] for e in names["entries"] if e["group"] == "number"}
    for part, least in counted.items():
        assert set(range(least, most[part] + 1)) <= numbers, part
    # And the reader names the largest of each: twelve legs, not a bare creature.
    loaded = body_names(1)
    body = {"heads": [{}], "spine": 4, "limbs": [{"role": "leg", "count": 12}]}
    assert body_name(body, loaded) == "twelve legged creature"
    body = {"heads": [{}], "spine": 4, "limbs": [{"role": "tentacle", "count": 12}]}
    assert body_name(body, loaded) == "twelve tentacled creature"


@pytest.mark.parametrize("name", NAMES)
def test_a_body_is_named_by_its_own_figures(name):
    form = _run_form(name)
    assert form["label"] == EXPECTED_NAMES[name]
    assert form["named_by"] == "body-names/v1"
    assert re.fullmatch(r"[a-z]+( [a-z]+)*", form["label"])
    assert body_name(form["body"], body_names(1)) == EXPECTED_NAMES[name]
    # Its summary is one plain line a decider reads, as a shipped kind's is.
    assert re.fullmatch(r"[A-Za-z0-9 .,]{1,200}", form["summary"]), form["summary"]
    if name in EXPECTED_SUMMARIES:
        assert form["summary"] == EXPECTED_SUMMARIES[name]


@pytest.mark.parametrize("name", NAMES)
def test_a_run_form_states_what_its_kind_and_plan_state_of_what_a_society_runs(name):
    creature = _creature(name)
    kind = creature.kind.document
    form = _run_form(name)
    assert set(form) == RUN_FORM_FIELDS
    assert form["reference"] == {"source": "workspace", "sha256": creature.kind.sha256}
    assert form["class"] == "being"
    assert form["abilities"] == [dict(a) for a in kind["abilities"]]
    assert form["offers"] == [dict(o) for o in kind["offers"]]
    assert form["deciders"] == {"default": "routine", "allowed": ["routine", "model", "person"]}
    assert form["routine"] == {"weights": dict(kind["routine"]["weights"]), "follow_holders_of": []}
    assert [move["module"] for move in form["moves"]] == list(kind["moves"])
    body = form["body"]
    assert body["plan_sha256"] == creature.plan.sha256 == kind["body"]["plan_sha256"]
    assert body["extent_mm"] == dict(kind["body"]["extent_mm"])
    # Its sockets are the plan document's own, less the bone each is on.
    assert body["sockets"] == [
        {key: value for key, value in socket.items() if key != "bone"}
        for socket in creature.plan_document["sockets"]
    ]
    # Its figures are the fixture recipe's own, read from the fixture file.
    recipe = (FIXTURES["development"] | FIXTURES["held_out"])[name]["recipe"]
    assert body["posture"] == recipe["posture"]
    assert body["spine"] == recipe["spine"] and body["tail"] == recipe["tail"]
    assert body["heads"] == [{"neck": h["neck"], "jaw": h["jaw"]} for h in recipe["heads"]]
    assert {limb["role"]: (limb["count"], limb["segments"]) for limb in body["limbs"]} == {
        limb["role"]: (limb["count"], limb["segments"]) for limb in recipe["limbs"]
    }
    assert body["holds_with"] == recipe["holds_with"]
    assert body["upper_body"] == (recipe["upper_body"] != "none")


def test_the_same_kind_gives_the_same_bytes_and_reads_back():
    first = canonical_json(_run_form("dragon"))
    assert first == canonical_json(_run_form("dragon"))
    assert read_run_form(json.loads(first)) == json.loads(first)


def _set(path: tuple[Any, ...], value: Any):
    def change(form: dict[str, Any]) -> None:
        target: Any = form
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value

    return change


def _extra(path: tuple[Any, ...]):
    def change(form: dict[str, Any]) -> None:
        target: Any = form
        for step in path:
            target = target[step]
        target["note"] = "quorzle wibbet"

    return change


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (_set(("label",), "quorzle wibbet"), "label"),
        (_set(("label",), "three headed creature"), "label"),
        (_set(("summary",), "Quorzle wibbet."), "summary"),
        (_set(("summary",), "A creature about 12 m long and 2.6 m high."), "summary"),
        (_set(("named_by",), "quorzle"), "named_by"),
        (_set(("named_by",), "body-names/v999"), "named_by"),
        (_set(("profile",), "exulanica.thing-kind/v1"), "profile"),
        (_set(("class",), "object"), "class"),
        (_set(("reference", "source"), "shipped"), "reference"),
        (_set(("reference", "sha256"), "quorzle"), "reference"),
        (_set(("body", "posture"), "quorzle"), "body.posture"),
        (_set(("body", "holds_with"), "quorzle"), "body.holds_with"),
        (_set(("body", "colours"), ["quorzle"]), "body.colours"),
        (_set(("body", "plan_sha256"), "quorzle/v1"), "body.plan_sha256"),
        (_set(("body", "sockets", 0, "key"), "quorzle"), "body.sockets[0].key"),
        (_set(("body", "limbs", 0, "role"), "quorzle"), "body.limbs[0].role"),
        (_set(("body", "spine"), "quorzle"), "body.spine"),
        (_set(("moves", 0, "module"), "quorzle wibbet"), "moves[0].module"),
        # A module's name in the registry's own shape that no movement of the grammar names.
        (
            _set(("moves", 0, "module"), "exulanica-movement/my-name-is-quorzle/v1"),
            "moves[0].module",
        ),
        (_set(("moves", 0, "parameters"), {"pace": "quorzle"}), "moves[0].parameters"),
        (_set(("moves", 0, "parameters"), {"Quorzle Wibbet": 1}), "moves[0].parameters"),
        # A lowercase name with a figure: no module, ability or offer declares it.
        (_set(("moves", 0, "parameters"), {"quorzle_wibbet": 1}), "moves[0].parameters"),
        (
            _set(("moves", 0, "parameters"), {"quorzle_wibbet_of_main_street": 1}),
            "moves[0].parameters",
        ),
        (_set(("abilities", 0, "parameters"), {"quorzle_wibbet": 1}), "abilities[0].parameters"),
        (_set(("offers", 0, "parameters"), {"quorzle_wibbet": 1}), "offers[0].parameters"),
        (_set(("body", "colours"), ["crimson"] * 5), "body.colours"),
        (_set(("abilities", 0, "key"), "quorzle"), "abilities[0].key"),
        (_set(("offers", 0, "key"), "quorzle"), "offers[0].key"),
        (_set(("routine", "weights"), {"quorzle": 5}), "routine.weights"),
        (_set(("routine", "follow_holders_of"), ["quorzle_wibbet"]), "routine.follow_holders_of"),
        (_set(("deciders", "allowed"), ["routine", "quorzle"]), "deciders"),
        (_extra(()), "run form"),
        (_extra(("body",)), "body"),
        (_extra(("routine",)), "routine"),
        (_extra(("reference",)), "reference"),
        (_extra(("body", "heads", 0)), "body.heads[0]"),
        (_extra(("abilities", 0)), "abilities[0]"),
    ],
)
def test_a_run_form_carrying_anything_that_could_be_words_is_refused_by_name(change, where):
    form = _run_form("dragon")
    read_run_form(copy.deepcopy(form))
    change(form)
    with pytest.raises(RunFormRefused) as refused:
        read_run_form(form)
    assert refused.value.where == where


def test_a_run_form_is_built_only_from_a_kind_its_plan_and_that_plan_s_recipe():
    dragon, horse = _creature("dragon"), _creature("horse")
    recipe = read_body_recipe(dict(dragon.recipe))
    with pytest.raises(RunFormRefused):
        run_form(dragon.kind, horse.plan, recipe)
    with pytest.raises(RunFormRefused):
        run_form(dragon.kind, dragon.plan, read_body_recipe(dict(horse.recipe)))


def test_a_moves_list_is_no_longer_than_the_modules_and_names_each_once():
    form = _run_form("dragon")
    twice = copy.deepcopy(form)
    twice["moves"] = [form["moves"][0], form["moves"][0]]
    with pytest.raises(RunFormRefused) as refused:
        read_run_form(twice)
    assert refused.value.where == "moves"
