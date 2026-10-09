#!/usr/bin/env python3
"""Do minds that notice and remember answer more coherently with their world?

    uv run python scripts/measure_society_minds.py contexts [--set held-out]
    uv run python scripts/measure_society_minds.py preregister [--set held-out]
    uv run python scripts/measure_society_minds.py probe [--set held-out]

**The question.** A being of a society of things that records the notice and memory modules is
shown what it notices around it and what it remembers. Asked a question whose answer only those
blocks hold, does the same model answer it correctly more often with them than without, by more
than the model's own variation between two identical asks, and without answering less validly?

**The cases** are built in memory by ``contexts``, before any model is asked. Each is a run of
scripted minutes of a society of things on the tests' own starter square: scripted receipts pick
things up, hand them over and say lines; the routine does the rest. It ends at one ask of the being
under test, the minute after another being asked it a question. Each case is one state, and its
arms differ only in what the being is shown:

* ``with``: the request as the host builds it, with ``surroundings`` and ``remembers``;
* ``without``: the same state with the notice and memory modules taken out of the society's record
  and every recollection removed, so the request is built exactly as before those modules;
* ``without_again``: the ``without`` request asked a second time: the same-model control, which
  measures how much a model's answer varies between identical asks.

**The families**, each with the words a correct answer holds, fixed by the builders before any ask.
The beings that speak are a knight, a lantern spirit and a traveller, and in every case the being
asked, the asker and any other being the question is about are of three different kinds, so a kind
named in an answer can only be the one meant:

* ``who_gave``: one being gave the asked being the thing it now holds; a third asks who gave it.
  Only the memory holds the giver.
* ``promised``: the asked being told another what it would bring, then said eight more lines to
  others, so that line left the lines it is shown; the other asks what it promised. Only the memory
  holds the line.
* ``holding``: a being near holds a thing; a third asks what that being holds. Only the
  surroundings hold another being's things. In a set that keeps words apart (:data:`SETS`), the
  holder is the knight or the traveller and holds the sword.
* ``earlier_place``: the asked being used at least two places; another asks where it was before its
  last stop. Only the memory holds a place before the last; ``last_activity`` already names the last.
* ``give_asked`` (no harm): a being asks the asked being, holding a thing, to give it to it. Both
  arms offer the give, and the line heard asks for it.

**The fixture.** Outside ``earlier_place``, whose asked being's routine must walk it to places,
every scripted being waits where it stands each minute it does nothing else, as its model chose,
and a scripted speaker also stays where it stands the minute it speaks, as a direct request to wait
would keep it: the beings of a case stay within hearing of each other, which the routine would
otherwise walk them out of. A being may speak only to the nearest few who hear it, so where the
routine's beings stand nearer to the asker than the being it asks, every mind waits a minute at a
time until it may ask, and the case states how many minutes (``asker_waited_minutes``).

**Scoring, by rule.** An answer is valid when the host would take it: the client accepted it (an
offered action, with a line exactly where that action says something), its line keeps the line rule
(``check_line`` at the request's bound) and, under terms that state ``names_no_listener``, does not
end by naming the one it is said to (``names_its_listener``). The host asks once more after such a
refusal; this measurement asks once in every arm and counts the answer invalid. A fact answer is
correct when it is valid, its action says something and its line, NFC-normalised and lower-cased,
holds one of the case's words. A ``give_asked`` answer is correct when it is valid and chooses the
give offered toward the asker.

**The verdict rule**, fixed here. Per model and arm: the share of fact answers correct over the four
fact families, the share of all answers valid, and the share of ``give_asked`` answers correct. The
blocks help a model when its ``with`` fact share exceeds its ``without`` fact share by more than the
absolute difference between its ``without`` and ``without_again`` fact shares plus
:data:`HELPS_BY`. They help overall when they help at least :data:`HELPED_MODELS_AT_LEAST` of the
models. They do no harm to a model when its ``with`` valid and give shares are each at least its
``without`` share less that same difference and :data:`NO_HARM_SLACK`.

**Spend.** The key is read from the environment and reaches only the client; the bound from
``EXULANICA_BUDGET_USD``, refused above the set's bound. Every record is written by this script
under the set's output directory (:data:`SETS`), which git ignores: per-model figures stay
unpublished until the provider's terms allow publishing them.

**What a record binds.** A pre-registration binds the tree it is written on (its HEAD and every
file that differs from it), this script's bytes and the contexts it asks; :func:`admitted` refuses
a probe on anything else before any model is asked. The two sets of :data:`SETS` are the ones
measured on 2026-10-08, on a tree that recorded the notice and memory modules; on another tree the
same builders build that tree's cases, so a new measurement is pre-registered as a set of its own.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
import unicodedata
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
# The tree this script measures, ahead of any installed copy of the package.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from measure_society_person_models import (  # noqa: E402
    _bound,
    _manifest_sha256,
    _measured,
    _read_record,
    _sha256,
    _tree,
    _write_new,
    _write_new_bytes,
)

from exulanica.canonical import canonical_json  # noqa: E402

SCRIPT: Final = "scripts/measure_society_minds.py"
ENGINE: Final = "exulanica-society/v7"
ARMS: Final = ("with", "without", "without_again")
FACT_FAMILIES: Final = ("who_gave", "promised", "holding", "earlier_place")
FAMILIES: Final = (*FACT_FAMILIES, "give_asked")
#: The open models asked: the models the manifest offers a person's decisions for lines.
MODELS: Final = (
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
)
HELPS_BY: Final = Decimal("0.15")
NO_HARM_SLACK: Final = Decimal("0.05")
HELPED_MODELS_AT_LEAST: Final = 4
#: This many failed calls in a row (refused, timed out, failed in transport) stop the measurement.
ERRORS_STOP: Final = 3
#: The words of a place an answer may name, by the routine activity it was used for.
PLACE_WORDS: Final = {
    "rest_bench": ("bench",),
    "rest_seating_planter": ("planter",),
    "rest_cafe_table": ("cafe", "café", "table"),
    "visit_market_stall": ("market", "stall"),
    "visit_planter_tree": ("tree",),
}
#: The words an answer may name for a being, by its kind.
KIND_WORDS: Final = {
    "knight": ("knight",),
    "lantern_spirit": ("spirit",),
    "traveller": ("traveller",),
}
#: What a promise is about in each case, its noun the word a correct answer holds.


@dataclass(frozen=True)
class CaseSet:
    """One set of cases: where its records go, the namespace its societies' ids are drawn in, where
    its speakers stand, how many cases each family holds, what is promised and the lines that push
    a promise out of the lines shown, and the bound its asks are held to."""

    name: str
    output: str
    namespace: str
    #: Whether each case's society draws its routine from a seed of its own (the namespace and the
    #: case's number); otherwise from the tests' one seed, as the development set ran.
    own_seeds: bool
    #: Whether a case's words are kept out of its question and out of other names. The lantern
    #: spirit holds only the lantern, whose word is inside the spirit's own name, so a holding
    #: case's holder is then the knight or the traveller, holding the sword.
    words_apart: bool
    origin_mm: tuple[int, int]
    across: int
    cases: Mapping[str, int]
    promises: tuple[tuple[str, str], ...]
    fillers: tuple[str, ...]
    bound_usd: Decimal
    #: The set whose record must be written before this one is pre-registered, or None.
    follows: str | None
    #: What a measurement of this set does not cover, before what no set covers.
    not_covered: tuple[str, ...]

    @property
    def max_calls(self) -> int:
        """One call for each case, arm and model, doubled for the client's one retry."""
        return 2 * sum(self.cases.values()) * len(ARMS) * len(MODELS)


#: Ignored and untracked: per-model figures of a hosted provider's models are published only once
#: the provider's terms allow it. The development set is as it ran on 2026-10-08; the held-out set
#: draws new societies at new places with new promises, and holds twice the give_asked cases.
SETS: Final = {
    "development": CaseSet(
        name="development",
        output=".exulanica/minds-measure",
        namespace="minds-measure",
        own_seeds=False,
        words_apart=False,
        origin_mm=(-4_000, 3_000),
        across=3,
        cases=dict.fromkeys(FAMILIES, 6),
        promises=(
            ("I will bring you the sword by the gate before noon.", "sword"),
            ("I will fetch you a basket of apples from the market.", "apples"),
            ("I will carry the lantern for you when it grows dark.", "lantern"),
            ("I will find you a map of the old road.", "map"),
            ("I will ring the bell for you at sunset.", "bell"),
            ("I will bring you fresh bread in the morning.", "bread"),
        ),
        fillers=(
            "Fine weather in the square today.",
            "Mind the cobbles by the stall.",
            "The benches are cool in the shade.",
            "Have you walked round the tree yet?",
            "It is a quiet hour for the market.",
            "The gate stands open, as always.",
            "Someone left a cup at the cafe table.",
            "The planters need water soon.",
        ),
        bound_usd=Decimal("0.60"),
        follows=None,
        not_covered=(
            "A development set: the held-out set is pre-registered after this one's result.",
        ),
    ),
    "held-out": CaseSet(
        name="held-out",
        output=".exulanica/minds-measure-held-out",
        namespace="minds-measure-held-out",
        own_seeds=True,
        words_apart=True,
        origin_mm=(-6_000, -1_000),
        across=4,
        cases={**dict.fromkeys(FACT_FAMILIES, 6), "give_asked": 12},
        promises=(
            ("I will bring you a coil of rope from the market.", "rope"),
            ("I will find you the old key to the gate.", "key"),
            ("I will light a candle for you at dusk.", "candle"),
            ("I will carry your letter to the well.", "letter"),
            ("I will fetch you a cloak before the rain.", "cloak"),
            ("I will bring you a jar of honey from the stall.", "honey"),
        ),
        fillers=(
            "The square is busy this morning.",
            "Watch the step by the planters.",
            "The tree gives good shade at noon.",
            "Have you seen the stall's new awning?",
            "The cafe tables are all taken.",
            "A cool wind comes through the gate.",
            "The benches still hold the night's damp.",
            "Someone is singing by the stall.",
        ),
        bound_usd=Decimal("0.70"),
        follows="development",
        not_covered=(
            "The held-out set, pre-registered after the development set's result (follows) and "
            "before any held-out ask: new societies drawn from seeds of their own at new places, "
            "with new promises and lines, twice the give_asked cases, and holding cases in which "
            "the knight or the traveller holds the sword, so that no question holds a word its "
            "answer is scored by (follows names the development cases whose question did); every "
            "rule is the development set's.",
        ),
    ),
}
#: The set this process measures, chosen from the command line before anything runs.
ACTIVE: CaseSet = SETS["development"]


def _paths() -> dict[str, str]:
    output = ACTIVE.output
    return {
        "preregistration": f"{output}/preregistration.json",
        "record": f"{output}/record.json",
        "contexts": f"{output}/contexts.json",
        "as_run": f"{output}/measure_society_minds-as-run.py.txt",
    }


BENCHMARK_REASON: Final = (
    "A recorded measurement asks open models fixed synthetic requests built from the tests' own "
    "starter square; no person's data is in them."
)
#: The three kinds that speak, placed on neighbouring nodes of the starter square's lattice.
SPEAKERS: Final = (
    ("knight", "knight", 2),
    ("spirit", "lantern_spirit", 1),
    ("traveller", "traveller", 2),
)


# -- scripted minutes ------------------------------------------------------------------------------


class _World:
    """A society of things on the starter square, played by scripted receipts."""

    def __init__(self, number: int, things: Sequence[Any], *, population: int = 4) -> None:
        from exulanica.world.society_decision_contract import person_role
        from exulanica.world.society_things import THINGS_PROFILE, initial_things_society

        from things_society_support import SEED, compose

        name = f"{ACTIVE.namespace}:{number}"
        self.seed = hashlib.sha256(name.encode()).hexdigest() if ACTIVE.own_seeds else SEED
        self.document = compose(things)
        society = uuid.uuid5(uuid.NAMESPACE_URL, name)
        self.state = copy.deepcopy(
            initial_things_society(society, self.seed, self.document, population=population)
        )
        role = person_role()
        self.contract = role.contract(role.terms(THINGS_PROFILE).versions)
        #: The minutes the asker waited before it could ask (see :func:`_ask`).
        self.waited = 0

    def placed(self, placed_id: str) -> dict[str, Any]:
        return next(p for p in self.state["inhabitants"] if p["placed_id"] == placed_id)

    def being(self, being_id: str) -> dict[str, Any]:
        return next(p for p in self.state["inhabitants"] if p["id"] == being_id)

    def thing(self, placed_id: str) -> dict[str, Any]:
        return next(t for t in self.state["things"] if t["placed_id"] == placed_id)

    def thing_by_id(self, thing_id: str) -> dict[str, Any]:
        return next(t for t in self.state["things"] if t["id"] == thing_id)

    def options(self, being_id: str) -> list[Any]:
        from exulanica.world.society_decision_contract import choice_options

        return choice_options(self.state, self.document, being_id, self.contract, seed=self.seed)

    def option(self, being_id: str, kind: str, **match: Any) -> Any:
        found = [
            o
            for o in self.options(being_id)
            if o.kind == kind and all(getattr(o, key) == value for key, value in match.items())
        ]
        if not found:
            raise SystemExit(f"no {kind} option {match} for {being_id}: the case does not hold")
        return found[0]

    def minute(
        self,
        chosen: Sequence[tuple[dict, Any, str | None]],
        minds: Sequence[str],
        *,
        still: bool = True,
    ) -> None:
        """One minute: each ``(being, option, line)`` answered as a model's applied choice. Every
        other being in ``minds`` waits where it is, as its model chose (or carries on with what is
        under way), where ``still``; otherwise, and where neither is offered, its model did not
        answer in time and the routine decides for it."""
        from exulanica.world.role_decisions import DecisionDisposition
        from exulanica.world.society_decision_contract import DecisionOption, option_goal_policy
        from exulanica.world.society_model_decisions import hands_goal_policy
        from exulanica.world.society_planner import advance_purposeful_society
        from exulanica.world.society_things import advance_things

        decisions, policies = [], {}
        for being, option, line in chosen:
            proposal = {"label": option.label, "option": option.as_record()}
            if line is not None:
                proposal["line"] = line
            receipt = {
                "subject_id": being["id"],
                "request_id": str(uuid.uuid4()),
                "status": "accepted",
                "reason": "validated_choice",
                "proposal": proposal,
                "provider": {"provider": "scripted", "model_id": "scripted"},
            }
            decisions.append((receipt, _disposition(DecisionDisposition, receipt, "applied")))
            if option.kind in ("pick_up", "put_down", "give", "take"):
                policy = hands_goal_policy(
                    self.state,
                    self.document,
                    being["id"],
                    DecisionOption.from_record(option.as_record()),
                    set(),
                )
                if isinstance(policy, str):
                    raise SystemExit(f"a scripted hands act does not hold: {policy}")
                policies[being["id"]] = policy
            elif option.kind == "wait":
                policies[being["id"]] = option_goal_policy(option, None)
            elif option.kind in ("say_to", "say_all") and still:
                # A case's fixture, stated here: a scripted speaker also stays where it stands
                # that minute, as a direct request to wait would keep it, so the beings of a case
                # stay within hearing of each other; the routine would otherwise walk it off.
                rest = next((o for o in self.options(being["id"]) if o.kind == "wait"), None)
                if rest is not None:
                    policies[being["id"]] = option_goal_policy(rest, None)
        decided = {receipt["subject_id"] for receipt, _ in decisions}
        resting = []
        for mind in sorted(minds):
            if mind in decided or not still:
                continue
            rest = next((o for o in self.options(mind) if o.kind in ("wait", "carry_on")), None)
            if rest is not None:
                resting.append((self.being(mind), rest, None))
        for being, option, _line in resting:
            if option.kind == "wait":
                # As the host applies a model's wait: the planner keeps the being where it is.
                policies[being["id"]] = option_goal_policy(option, None)
            proposal = {"label": option.label, "option": option.as_record()}
            receipt = {
                "subject_id": being["id"],
                "request_id": str(uuid.uuid4()),
                "status": "accepted",
                "reason": "validated_choice",
                "proposal": proposal,
                "provider": {"provider": "scripted", "model_id": "scripted"},
            }
            decisions.append((receipt, _disposition(DecisionDisposition, receipt, "applied")))
            decided.add(being["id"])
        for mind in sorted(minds):
            if mind not in decided:
                receipt = {
                    "subject_id": mind,
                    "request_id": str(uuid.uuid4()),
                    "status": "unavailable",
                    "reason": "no_answer_in_time",
                    "proposal": None,
                    "provider": None,
                }
                decisions.append(
                    (receipt, _disposition(DecisionDisposition, receipt, "unavailable"))
                )
        planned, events = advance_purposeful_society(
            self.state, self.seed, [self.document], goal_policy=policies
        )
        self.state, _, _ = advance_things(
            self.state, planned, self.seed, self.document, events, (), decisions=decisions
        )


def _disposition(kind: Any, receipt: Mapping[str, Any], disposition: str) -> Any:
    return kind(
        decision_seq=1,
        request_id=receipt["request_id"],
        subject_id=receipt["subject_id"],
        disposition=disposition,
        reason=receipt["reason"],
        decision_sha256="0" * 64,
    )


def _speakers(number: int, extra: Sequence[Any] = ()) -> _World:
    """The three speakers 2 m apart in a row, shifted by case, with ``extra`` things."""
    from things_society_support import thing

    x = ACTIVE.origin_mm[0] + 2_000 * (number % ACTIVE.across)
    placed = [
        thing(
            placed_id, kind, version, x + 2_000 * index, ACTIVE.origin_mm[1] + 2_000 * (number % 2)
        )
        for index, (placed_id, kind, version) in enumerate(SPEAKERS)
    ]
    return _World(number, (thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593), *placed, *extra))


def _kind(being: Mapping[str, Any]) -> str:
    return str(being["kind"]["kind"])


def _label(reference: Mapping[str, Any]) -> str:
    from exulanica.world.placed_things import ThingKindReference, shipped_kind

    return str(shipped_kind(ThingKindReference(**reference)).document["label"])


def _picks_up(world: _World, holder: dict, thing_id: str, minds: Sequence[str]) -> None:
    pick = world.option(holder["id"], "pick_up", target_id=thing_id)
    world.minute([(holder, pick, None)], minds)
    if world.thing_by_id(thing_id)["held_by"] != holder["id"]:
        raise SystemExit("a scripted pick-up did not happen: the case does not hold")


def _thing_for(holder: Mapping[str, Any], number: int) -> tuple[str, str, int]:
    """A thing ``holder``'s kind can hold: a lantern spirit holds only small things."""
    if _kind(holder) == "lantern_spirit" or number % 2 == 0:
        return ("lantern", "lantern", 1)
    return ("sword", "sword", 3)


#: How many minutes an asker waits where it stands for the being it asks to be among the nearest it
#: may speak to, which beings the routine walks nearer can leave it out of for a while.
ASK_WAIT_MINUTES: Final = 60


def _ask(world: _World, asker: dict, subject: dict, line: str, minds: Sequence[str]) -> None:
    """``asker`` says ``line`` to ``subject``; first, while ``subject`` is not among the beings it
    may speak to, every mind waits where it stands, a minute at a time (counted in the case)."""
    for _ in range(ASK_WAIT_MINUTES):
        if any(
            o.kind == "say_to" and o.addressee_id == subject["id"]
            for o in world.options(asker["id"])
        ):
            break
        world.minute([], minds)
        world.waited += 1
    said = world.option(asker["id"], "say_to", addressee_id=subject["id"])
    world.minute([(asker, said, line)], minds)


#: Which speaker plays which part in each case of a three-part family: every order of the three.
ORDERS: Final = ((0, 1, 2), (1, 2, 0), (2, 0, 1), (0, 2, 1), (2, 1, 0), (1, 0, 2))


def who_gave(number: int) -> dict[str, Any]:
    giver_at, subject_at, asker_at = ORDERS[number % len(ORDERS)]
    from things_society_support import thing

    world = _speakers(number)
    giver = world.placed(SPEAKERS[giver_at][0])
    subject = world.placed(SPEAKERS[subject_at][0])
    asker = world.placed(SPEAKERS[asker_at][0])
    placed_id, kind, version = _thing_for(giver, number)
    if _kind(subject) == "lantern_spirit":
        placed_id, kind, version = ("lantern", "lantern", 1)
    world = _speakers(number, (thing(placed_id, kind, version, *giver["position_mm"]),))
    giver, subject, asker = (world.placed(SPEAKERS[i][0]) for i in (giver_at, subject_at, asker_at))
    minds = [subject["id"], asker["id"]]
    held = world.thing(placed_id)
    _picks_up(world, giver, held["id"], minds)
    give = world.option(giver["id"], "give", target_id=held["id"], addressee_id=subject["id"])
    world.minute([(giver, give, None)], minds)
    if world.thing_by_id(held["id"])["held_by"] != subject["id"]:
        raise SystemExit("a scripted hand-over did not happen: the case does not hold")
    for _ in range(2 + number):
        world.minute([], minds)
    _ask(world, asker, subject, f"Who gave you the {_label(held['kind'])}?", minds)
    return _case(world, "who_gave", number, subject, asker, KIND_WORDS[_kind(giver)])


def promised(number: int) -> dict[str, Any]:
    subject_at, asker_at, other_at = ORDERS[number % len(ORDERS)]
    world = _speakers(number)
    subject = world.placed(SPEAKERS[subject_at][0])
    asker = world.placed(SPEAKERS[asker_at][0])
    other = world.placed(SPEAKERS[other_at][0])
    line, noun = ACTIVE.promises[number % len(ACTIVE.promises)]
    minds = [subject["id"], asker["id"], other["id"]]
    said = world.option(subject["id"], "say_to", addressee_id=asker["id"])
    world.minute([(subject, said, line)], minds)
    for filler in ACTIVE.fillers:
        to_other = world.option(subject["id"], "say_to", addressee_id=other["id"])
        world.minute([(subject, to_other, filler)], minds)
    if any(entry["line"] == line for entry in world.being(subject["id"]).get("said", ())):
        raise SystemExit("the promise is still among the lines shown: the case does not hold")
    _ask(world, asker, subject, "What did you promise me earlier?", minds)
    return _case(world, "promised", number, subject, asker, (noun,))


def holding(number: int) -> dict[str, Any]:
    orders = ORDERS
    if ACTIVE.words_apart:
        orders = tuple(order for order in ORDERS if SPEAKERS[order[2]][1] != "lantern_spirit")
    subject_at, asker_at, holder_at = orders[number % len(orders)]
    from things_society_support import thing

    world = _speakers(number)
    holder = world.placed(SPEAKERS[holder_at][0])
    if ACTIVE.words_apart:
        placed_id, kind, version = ("sword", "sword", 3)
    else:
        placed_id, kind, version = _thing_for(holder, number)
    world = _speakers(number, (thing(placed_id, kind, version, *holder["position_mm"]),))
    subject, asker, holder = (
        world.placed(SPEAKERS[i][0]) for i in (subject_at, asker_at, holder_at)
    )
    minds = [subject["id"], asker["id"], holder["id"]]
    held = world.thing(placed_id)
    _picks_up(world, holder, held["id"], minds)
    for _ in range(1 + number % 3):
        world.minute([], minds)
    _ask(world, asker, subject, f"What is the {_label(holder['kind'])} holding?", minds)
    return _case(world, "holding", number, subject, asker, (_label(held["kind"]),))


def earlier_place(number: int) -> dict[str, Any]:
    """The asked being is the knight or the traveller (the speakers that use places), its routine
    played until it has used places of two different words and then ``5 * number`` minutes more,
    and on until another speaker stands within hearing of it; that one asks."""
    world = _speakers(number)
    subject = world.placed(("knight", "traveller")[number % 2])
    others = [
        world.placed(placed_id) for placed_id, _, _ in SPEAKERS if placed_id != subject["placed_id"]
    ]
    minds = [subject["id"], *(other["id"] for other in others)]
    more = None
    for _ in range(480):
        world.minute([], minds, still=False)
        places = world.being(subject["id"]).get("recollection", {}).get("places", [])
        if more is None and len({p["words"] for p in places}) >= 2:
            more = 5 * number
        if more is not None:
            more -= 1
            near = [
                other
                for other in others
                if any(
                    o.kind == "say_to" and o.addressee_id == subject["id"]
                    for o in world.options(other["id"])
                )
            ]
            if more < 0 and near:
                asker = near[0]
                break
    else:
        raise SystemExit("no speaker came within hearing in eight hours: the case does not hold")
    places = sorted(
        world.being(subject["id"])["recollection"]["places"], key=lambda p: p["last_tick"]
    )
    last = places[-1]
    targets = {t["target_id"]: t for t in world.document["targets"]}
    words = {
        word
        for place in places[:-1]
        if place["words"] != last["words"]
        for word in PLACE_WORDS[targets[place["target_id"]]["activity"]]
    } - set(PLACE_WORDS[targets[last["target_id"]]["activity"]])
    _ask(world, asker, world.being(subject["id"]), "Where were you before your last stop?", minds)
    return _case(world, "earlier_place", number, world.being(subject["id"]), asker, tuple(words))


def give_asked(number: int) -> dict[str, Any]:
    subject_at, asker_at, _ = ORDERS[number % len(ORDERS)]
    from things_society_support import thing

    world = _speakers(number)
    subject = world.placed(SPEAKERS[subject_at][0])
    placed_id, kind, version = _thing_for(subject, number)
    asker_kind = SPEAKERS[asker_at][1]
    if asker_kind == "lantern_spirit":
        placed_id, kind, version = ("lantern", "lantern", 1)
    world = _speakers(number, (thing(placed_id, kind, version, *subject["position_mm"]),))
    subject, asker = (world.placed(SPEAKERS[i][0]) for i in (subject_at, asker_at))
    minds = [subject["id"], asker["id"]]
    held = world.thing(placed_id)
    _picks_up(world, subject, held["id"], minds)
    _ask(world, asker, subject, f"Please give me the {_label(held['kind'])}.", minds)
    case = _case(world, "give_asked", number, subject, asker, ())
    offered = [
        o
        for o in case["contexts"]["with"]["options"]
        if o["kind"] == "give" and o.get("addressee_id") == asker["id"]
    ]
    if not offered:
        raise SystemExit("the give toward the asker is not offered: the case does not hold")
    return case


BUILDERS: Final = {
    "who_gave": who_gave,
    "promised": promised,
    "holding": holding,
    "earlier_place": earlier_place,
    "give_asked": give_asked,
}


def _withheld(state: Mapping[str, Any]) -> dict[str, Any]:
    """``state`` as a society made before the notice and memory modules would hold it."""
    from exulanica.abilities.registry import NOTICE, REMEMBER

    earlier = copy.deepcopy(dict(state))
    earlier["modules"] = [m for m in earlier["modules"] if m not in (NOTICE, REMEMBER)]
    for person in earlier["inhabitants"]:
        person.pop("recollection", None)
    return earlier


def _case(
    world: _World,
    family: str,
    number: int,
    subject: Mapping[str, Any],
    asker: Mapping[str, Any],
    words: Sequence[str],
) -> dict[str, Any]:
    """One case: both requests' contexts, the words a correct answer holds and who asked."""
    from exulanica.world.society_decision_contract import decision_context

    offered = world.options(subject["id"])
    with_blocks = decision_context(world.state, world.document, subject["id"], offered)
    without = decision_context(_withheld(world.state), world.document, subject["id"], offered)
    if "surroundings" not in with_blocks or "surroundings" in without or "remembers" in without:
        raise SystemExit(f"{family} {number}: the arms do not differ as they must")
    heard = [line for line in with_blocks.get("heard", ()) if line["to_you"]]
    if not heard or heard[-1]["minutes_ago"] != 0:
        raise SystemExit(f"{family} {number}: the question was not the last line heard")
    if family != "give_asked" and not words:
        raise SystemExit(f"{family} {number}: no words a correct answer holds")
    if ACTIVE.words_apart and _shown(words, heard[-1]["line"]):
        raise SystemExit(f"{family} {number}: the question holds a word a correct answer holds")
    case = {
        "family": family,
        "number": number,
        "subject_id": subject["id"],
        "asker_id": asker["id"],
        "words": sorted(words),
        "contexts": {"with": with_blocks, "without": without},
    }
    if world.waited:
        case["asker_waited_minutes"] = world.waited
    return case


def contexts() -> None:
    """Every case of every family, built by scripted minutes, asking nothing."""
    cases = [
        BUILDERS[family](number) for family in FAMILIES for number in range(ACTIVE.cases[family])
    ]
    _write_new(
        _paths()["contexts"], {"engine": ENGINE, "set": ACTIVE.name, "cases": cases}, record=False
    )
    sizes = Counter()
    for case in cases:
        for arm, context in case["contexts"].items():
            sizes[arm] = max(sizes[arm], len(canonical_json(context)))
    print(f"{len(cases)} cases; the largest context with and without: {dict(sizes)}")


# -- the verdicts ---------------------------------------------------------------------------------


def _normal(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def correct(case: Mapping[str, Any], answer: Mapping[str, Any]) -> bool:
    """Whether an accepted answer holds the case's fact, by the rule the docstring states."""
    if case["family"] == "give_asked":
        option = answer.get("option") or {}
        return option.get("kind") == "give" and option.get("addressee_id") == case["asker_id"]
    line = answer.get("line")
    return bool(line) and any(_normal(word) in _normal(line) for word in case["words"])


def _share(hits: int, asked: int) -> Decimal:
    return (
        Decimal(0) if asked == 0 else (Decimal(hits) / Decimal(asked)).quantize(Decimal("0.0001"))
    )


def verdicts(calls: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per model, each arm's shares and the pre-registered verdicts; and the overall verdict."""
    found: dict[str, Any] = {}
    helped = 0
    for model in sorted({call["model_id"] for call in calls}):
        arms: dict[str, dict[str, Decimal]] = {}
        for arm in ARMS:
            mine = [c for c in calls if c["model_id"] == model and c["arm"] == arm]
            facts = [c for c in mine if c["family"] in FACT_FAMILIES]
            gives = [c for c in mine if c["family"] == "give_asked"]
            arms[arm] = {
                "fact": _share(sum(c["correct"] for c in facts), len(facts)),
                "valid": _share(sum(c["valid"] for c in mine), len(mine)),
                "give": _share(sum(c["correct"] for c in gives), len(gives)),
            }
        noise = abs(arms["without"]["fact"] - arms["without_again"]["fact"])
        helps = arms["with"]["fact"] - arms["without"]["fact"] > noise + HELPS_BY
        harmless = all(
            arms["with"][share] >= arms["without"][share] - noise - NO_HARM_SLACK
            for share in ("valid", "give")
        )
        helped += helps
        found[model] = {
            "shares": {arm: {k: str(v) for k, v in shares.items()} for arm, shares in arms.items()},
            "noise": str(noise),
            "helps": helps,
            "does_no_harm": harmless,
        }
    return {
        "models": found,
        "helped_models": helped,
        "overall_helps": helped >= HELPED_MODELS_AT_LEAST,
    }


# -- the pre-registration and the probe -------------------------------------------------------------


def preregister() -> None:
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import person_role

    paths = _paths()
    if (ROOT / paths["preregistration"]).exists():
        raise SystemExit(f"{paths['preregistration']} is already written")
    role = person_role()
    terms = role.terms(ENGINE)
    contract = role.contract(terms.versions)
    manifest = load_manifest()
    asked = {}
    for model_id in MODELS:
        mechanism = contract.mechanism_for(manifest.spec(model_id))
        if mechanism is None:
            raise SystemExit(f"{model_id} is not asked by this contract")
        asked[model_id] = mechanism.value
    context_bytes = (ROOT / paths["contexts"]).read_bytes()
    cases = json.loads(context_bytes)["cases"]
    follows = None
    if ACTIVE.follows is not None:
        earlier = SETS[ACTIVE.follows].output + "/record.json"
        if not (ROOT / earlier).exists():
            raise SystemExit(f"{earlier} is not written: the {ACTIVE.name} set follows it")
        earlier_cases = json.loads(
            (ROOT / SETS[ACTIVE.follows].output / "contexts.json").read_bytes()
        )["cases"]
        follows = {
            "set": ACTIVE.follows,
            "record": earlier,
            "record_sha256": _sha256(canonical_json(_read_record(earlier))),
            "cases_whose_question_holds_a_word": [
                [case["family"], case["number"]]
                for case in earlier_cases
                if _shown(case["words"], _question(case["contexts"]["with"]))
            ],
        }
    _write_new(
        paths["preregistration"],
        {
            "question": (
                "With what a being notices and remembers, does the same model answer a question "
                "whose answer only those blocks hold correctly more often than without them, by "
                "more than its own variation between identical asks, without answering less validly?"
            ),
            "written_before_this_measurement_asked_any_model": True,
            "models": asked,
            "arms": list(ARMS),
            "families": {
                family: [
                    {
                        "number": case["number"],
                        "words": case["words"],
                        "words_shown_without": _shown(case["words"], case["contexts"]["without"]),
                        "context_sha256": {
                            arm: _sha256(canonical_json(context))
                            for arm, context in case["contexts"].items()
                        },
                    }
                    for case in cases
                    if case["family"] == family
                ]
                for family in FAMILIES
            },
            "set": ACTIVE.name,
            "follows": follows,
            "cases_per_family": dict(ACTIVE.cases),
            "contexts_artifact": paths["contexts"],
            "contexts_sha256": _sha256(context_bytes),
            "scoring": (
                "a fact answer is correct when the chosen action says something and its line, "
                "NFC-normalised and lower-cased, holds one of the case's words; a give_asked answer "
                "is correct when it chooses the give offered toward the asker; an answer is valid "
                "when the client accepted it"
            ),
            "verdict_rule": {
                "helps": (
                    f"a model's with fact share exceeds its without fact share by more than "
                    f"|without - without_again| + {HELPS_BY}"
                ),
                "overall": f"the blocks help at least {HELPED_MODELS_AT_LEAST} of the models",
                "does_no_harm": (
                    f"a model's with valid and give shares are each at least its without share "
                    f"less |without - without_again| and {NO_HARM_SLACK}"
                ),
            },
            "stop_rule": (
                f"The whole measurement stops at the bound (USD {ACTIVE.bound_usd}, "
                f"{ACTIVE.max_calls} calls) or "
                f"after {ERRORS_STOP} failed calls in a row, writing what it asked and why it "
                "stopped."
            ),
            "bound_usd": str(ACTIVE.bound_usd),
            "max_calls": ACTIVE.max_calls,
            "prompt_version": terms.prompt_version,
            "contract": contract.binding(),
            "manifest_sha256": _manifest_sha256(),
            "tree": _tree(),
            "script_sha256": _sha256((ROOT / SCRIPT).read_bytes()),
            "record": paths["record"],
            "not_covered": [
                *ACTIVE.not_covered,
                "words_shown_without lists, for each case, the words a correct answer holds that "
                "its without context also shows somewhere (a being among the ones it may speak "
                "to, a place among the routine's): an answer without the blocks may guess from "
                "them.",
                "Questions are said by scripted beings in a small square; whether answers are apt "
                "or in character beyond the fact is not judged.",
                "One ask per arm and case; the control arm is the measure of variation.",
            ],
        },
    )


def _question(context: Mapping[str, Any]) -> str:
    """The question a case's being was asked: the last line it heard said to it."""
    return [line for line in context.get("heard", ()) if line["to_you"]][-1]["line"]


def _shown(words: Sequence[str], context: Any) -> list[str]:
    """The ``words`` that a string of ``context``, NFC-normalised and lower-cased, holds."""
    strings: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            strings.append(_normal(value))
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    walk(context)
    return sorted(word for word in words if any(_normal(word) in text for text in strings))


def _refused(role, terms, contract, context, option, line) -> str | None:
    """Why the host would not take an accepted answer's line, or None where it would."""
    from exulanica.things.lines import LineRefused, check_line
    from exulanica.world.role_decisions import names_its_listener

    if line is None:
        return None
    try:
        check_line(line, maximum=context["line_characters_maximum"])
    except LineRefused:
        return "line_breaks_rule"
    request = {
        "provider_config": {
            "prompt_version": terms.prompt_version,
            "contract": contract.binding(),
        }
    }
    if names_its_listener(role, request, option, line):
        return "line_names_its_listener"
    return None


def admitted(as_run: bytes) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """The pre-registration a probe of the active set is held to, the tree it runs on and the
    contexts it asks; or SystemExit, before any model is asked, where the tree, the running
    script's bytes or the contexts are not the ones it binds, or its record is already written."""
    tree = _tree()
    paths = _paths()
    registered = _read_record(paths["preregistration"])
    if _measured(tree) != _measured(registered["tree"]):
        raise SystemExit("the tree is not the pre-registered one")
    if _sha256(as_run) != registered["script_sha256"]:
        raise SystemExit("the bytes running are not the pre-registered script")
    context_bytes = (ROOT / paths["contexts"]).read_bytes()
    if _sha256(context_bytes) != registered["contexts_sha256"]:
        raise SystemExit("the contexts are not the ones the pre-registration binds")
    if (ROOT / paths["record"]).exists():
        raise SystemExit(f"{paths['record']} exists")
    return registered, tree, context_bytes


class _Stopped(Exception):
    """The stop rule ended the measurement: what it asked is still written, with why."""


def probe(as_run: bytes) -> None:
    from exulanica.api.society_person_decisions import answer_tokens
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.choice import ChoiceRefused
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.errors import BudgetExceededError, ModelError, TransportError
    from exulanica.models.manifest import load_manifest
    from exulanica.models.policy import BenchmarkInputs
    from exulanica.world.society_decision_contract import person_role

    registered, tree, context_bytes = admitted(as_run)
    paths = _paths()
    cases = json.loads(context_bytes)["cases"]
    bound = _bound(ACTIVE.bound_usd)
    manifest = load_manifest()
    role = person_role()
    terms = role.terms(ENGINE)
    contract = role.contract(terms.versions)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(manifest.bound_origins()))
    budget = BudgetGuard(ceiling_usd=bound, max_calls=ACTIVE.max_calls)
    client = ModelClient(manifest=manifest, budget=budget).with_policy(
        BenchmarkInputs(BENCHMARK_REASON)
    )
    deadline = contract.value("decision_deadline_ms") / 1000
    calls: list[dict[str, Any]] = []
    stopped = None
    failed_in_a_row = 0
    try:
        for model_id, mechanism_name in registered["models"].items():
            spec = manifest.spec(model_id)
            mechanism = next(m for m in spec.answering if m.value == mechanism_name)
            for case in cases:
                for arm in ARMS:
                    context = case["contexts"]["with" if arm == "with" else "without"]
                    entry: dict[str, Any] = {
                        "model_id": model_id,
                        "family": case["family"],
                        "number": case["number"],
                        "arm": arm,
                    }
                    heard: list[Any] = []
                    started = time.monotonic()
                    try:
                        chosen = client.with_attempts(heard.append).choose(
                            role.chosen,
                            model_id,
                            role.adapter.messages(role, context, mechanism),
                            role.choice(context),
                            mechanism=mechanism,
                            prompt_version=terms.prompt_version,
                            timeout=deadline,
                            max_tokens=answer_tokens(spec),
                        )
                    except BudgetExceededError:
                        raise _Stopped("the measurement reached its bound") from None
                    except ChoiceRefused:
                        entry.update(valid=False, correct=False, outcome="answer_not_a_choice")
                    except TransportError as exc:
                        entry.update(
                            valid=False,
                            correct=False,
                            outcome="timed_out" if exc.timed_out else "call_failed",
                        )
                    except ModelError as exc:
                        entry.update(valid=False, correct=False, outcome=type(exc).__name__)
                    else:
                        option = next(o for o in context["options"] if o["label"] == chosen.label)
                        answer = {"option": option, "line": chosen.line}
                        refused = _refused(role, terms, contract, context, option, chosen.line)
                        entry.update(
                            valid=refused is None,
                            correct=refused is None and correct(case, answer),
                            outcome="answered" if refused is None else refused,
                            chose_kind=option["kind"],
                            line=chosen.line,
                        )
                    entry["latency_ms"] = round((time.monotonic() - started) * 1000)
                    entry["attempts"] = [
                        {
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                            "usd": str(usage.usd),
                            "usd_known": usage.usd_known,
                        }
                        for usage in heard
                    ]
                    calls.append(entry)
                    print(
                        f"{model_id} {case['family']} {case['number']} {arm}: "
                        f"{entry['outcome']} correct={entry['correct']}",
                        flush=True,
                    )
                    failing = entry["outcome"] in {"timed_out", "call_failed"}
                    failed_in_a_row = failed_in_a_row + 1 if failing else 0
                    if failed_in_a_row >= ERRORS_STOP:
                        raise _Stopped(f"{ERRORS_STOP} failed calls in a row")
    except _Stopped as exc:
        stopped = str(exc)
    _write_new_bytes(paths["as_run"], as_run)
    _write_new(
        paths["record"],
        {
            "preregistration": paths["preregistration"],
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "script_as_run": paths["as_run"],
            "script_sha256": _sha256(as_run),
            "tree": tree,
            "manifest_sha256": _manifest_sha256(),
            "calls": calls,
            "stopped": stopped,
            "verdicts": verdicts(calls),
            "spent_usd": str(budget.spent_usd),
            "bound_usd": str(bound),
            "within_bound": budget.spent_usd <= bound,
        },
    )


def main(argv: Sequence[str] | None = None) -> None:
    global ACTIVE
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=("contexts", "preregister", "probe"))
    parser.add_argument("--set", choices=sorted(SETS), default="development")
    arguments = parser.parse_args(argv)
    ACTIVE = SETS[arguments.set]
    if arguments.step == "contexts":
        contexts()
    elif arguments.step == "preregister":
        preregister()
    else:
        probe(Path(__file__).read_bytes())


if __name__ == "__main__":
    main()
