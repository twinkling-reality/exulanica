#!/usr/bin/env python3
"""Can a candidate open model be a being's mind: does it answer a person's choice as the host asks?

    uv run python scripts/measure_society_mind_probe.py contexts
    uv run python scripts/measure_society_mind_probe.py preregister
    uv run python scripts/measure_society_mind_probe.py probe

**The question.** A model is offered to a person's decisions only when its manifest entry names a
mechanism a recorded probe verified it answers a choice by (``answering``), and it is offered for a
choice that takes a line unless its entry says why not (``not_offered_for_lines``). ``CANDIDATES``
are open models the manifest lists that no probe has asked yet. For each, by each mechanism the
client asks with, does it answer the choice a society of things' being is asked under its engine's
own terms: one of the offered labels, with a line of at most the request's bound exactly where the
label says something, within the host's token bound and the contract's deadline?

**The cases** are built in memory by ``contexts`` from the tests' own starter square before any
model is asked: ``PLAIN_CASES`` requests of a knight with nobody near enough to hear it, whose
choice takes no line, and ``LINE_CASES`` requests of a knight beside people who hear it, whose
choice takes a line (as ``scripts/measure_society_line_choice.py`` built them).

**The probe** asks every candidate each case once by each mechanism, one call at a time, through
the product's client (``ModelClient.choose``) as the host asks: the role's messages and choice for
the request, the host's token bound for the model (``answer_tokens``) and the contract's deadline,
the line held to the line rule (``check_line``). The client is given the manifest with each
candidate's ``answering`` naming every mechanism, which is what the probe decides; nothing else of
the manifest differs. A provider refusing the request ``REFUSALS_STOP`` times for a model and
mechanism stops that pair, and ``ERRORS_STOP`` failed calls in a row stop the whole probe.

**The verdicts**, by rule, per model and mechanism: it ``answers`` when at least
``PLAIN_VERIFIED_AT_LEAST`` of the plain cases' answers name an offered label, and it
``answers_lines`` when at least ``LINE_VERIFIED_AT_LEAST`` of the line cases' answers name an
offered label with a line exactly where that label says something, within the rule.

**Spend.** The key is read from the environment, ``KEY_VARIABLE`` only, and reaches nothing but the
client; the bound is read from ``BUDGET_VARIABLE`` and refused above ``BOUND_USD``. Every record is
written by this script and none is edited after, under ``OUTPUT``, which git ignores: its per-model
figures stay unpublished until the provider's terms allow publishing them.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
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

#: Ignored and untracked: a per-model record of a hosted provider's models is published only once the
#: provider's terms allow it, so the probe writes beside the worktree, not under docs/evaluation.
OUTPUT: Final = ".exulanica/mind-probe"
PREREGISTRATION: Final = f"{OUTPUT}/preregistration.json"
RECORD: Final = f"{OUTPUT}/record.json"
CONTEXTS: Final = f"{OUTPUT}/contexts.json"
SCRIPT: Final = "scripts/measure_society_mind_probe.py"
SCRIPT_AS_RUN: Final = f"{OUTPUT}/measure_society_mind_probe-as-run.py.txt"
ENGINE: Final = "exulanica-society/v7"
CANDIDATES: Final = (
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
)
PLAIN_CASES: Final = 6
LINE_CASES: Final = 16
PLAIN_VERIFIED_AT_LEAST: Final = 5
LINE_VERIFIED_AT_LEAST: Final = 14
BOUND_USD: Final = Decimal("0.50")
#: One call for each case by each of the two mechanisms of each candidate.
MAX_CALLS: Final = (PLAIN_CASES + LINE_CASES) * 2 * len(CANDIDATES)
#: A provider refusing the request this many times for one model and mechanism stops that pair.
REFUSALS_STOP: Final = 2
#: This many failed calls in a row (refused, timed out, failed in transport) stop the whole probe.
ERRORS_STOP: Final = 3
#: Where nobody is: every other being is moved this far from the knight, beyond any hearing.
FAR_MM: Final = 40_000
#: The committed files the probe reads beside the package's code, bound by digest in the
#: pre-registration so a reader without this tree can check them.
READS: Final = (
    SCRIPT,
    "scripts/measure_society_person_models.py",
    "assets/catalogs/roles/decision-roles.v6.json",
    "assets/catalogs/society/society-decision-action.v4.json",
    "assets/catalogs/society/society-decision-policy.v4.json",
    "exulanica/models/models.manifest.json",
    "tests/things_society_support.py",
)
BENCHMARK_REASON: Final = (
    "A recorded measurement asks each candidate model a fixed set of synthetic requests built from "
    "the tests' own starter square; no person's data is in them."
)
#: The outcomes that name an offered label.
NAMES_A_LABEL: Final = frozenset(
    {
        "offered_label",
        "offered_label_with_line",
        "line_where_none",
        "no_line_where_one",
        "line_breaks_rule",
    }
)
#: The outcomes that answer a choice exactly as the host takes it.
ANSWERS_EXACTLY: Final = frozenset({"offered_label", "offered_label_with_line"})


# -- the cases ------------------------------------------------------------------------------------


def contexts() -> None:
    """``PLAIN_CASES`` requests of a knight alone and ``LINE_CASES`` beside hearers, asking nothing."""
    from exulanica.world.society_decision_contract import (
        choice_options,
        decision_context,
        person_role,
    )
    from exulanica.world.society_things import initial_things_society

    from things_society_support import SEED, SOCIETY, compose, thing

    role = person_role()
    contract = role.contract(role.terms(ENGINE).versions)
    gate = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
    cases = []
    for number in range(PLAIN_CASES + LINE_CASES):
        plain = number < PLAIN_CASES
        place = number if plain else number - PLAIN_CASES
        # A knight placed somewhere else on the square each time, the people moved beside it or away.
        knight = thing("knight", "knight", 1, -6_000 + 800 * place, 3_000 - 300 * place)
        document = compose((gate, knight))
        state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
        placed = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
        others = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
        if plain:
            for offset, person in enumerate(others):
                person["position_mm"] = [
                    placed["position_mm"][0] + FAR_MM + 1_000 * offset,
                    placed["position_mm"][1] + FAR_MM,
                ]
        else:
            for offset, person in enumerate(others[: 1 + place % 3], 1):
                person["position_mm"] = [
                    placed["position_mm"][0] + 1_500 * offset,
                    placed["position_mm"][1],
                ]
        options = choice_options(state, document, placed["id"], contract, seed=SEED)
        context = decision_context(state, document, placed["id"], options)
        if role.takes_line(context) == plain:
            raise SystemExit(f"case {number + 1} is not the shape its place in the set names")
        cases.append(context)
    _write_new(CONTEXTS, {"engine": ENGINE, "cases": cases}, record=False)


# -- the pre-registration -------------------------------------------------------------------------


def preregister() -> None:
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import person_role

    if (ROOT / PREREGISTRATION).exists():
        raise SystemExit(f"{PREREGISTRATION} is already written")
    role = person_role()
    terms = role.terms(ENGINE)
    contract = role.contract(terms.versions)
    manifest = load_manifest()
    for model_id in CANDIDATES:
        if manifest.spec(model_id).answering:
            raise SystemExit(f"{model_id} is already verified; this probe asks only new candidates")
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    cases = json.loads(context_bytes)["cases"]
    _write_new(
        PREREGISTRATION,
        {
            "question": (
                "Can each candidate be a being's mind: by each mechanism the client asks with, "
                "does it answer a society of things' person's choice as the host asks it, naming "
                "an offered label, with a line of at most the request's bound exactly where the "
                "label says something, within the host's token bound and the contract's deadline?"
            ),
            "written_before_this_measurement_asked_any_model": True,
            "candidates": list(CANDIDATES),
            "mechanisms": ["json_schema", "tool_call"],
            "cases": [
                {
                    "takes_line": role.takes_line(case),
                    "options": len(case["options"]),
                    "kinds": dict(sorted(Counter(o["kind"] for o in case["options"]).items())),
                    "context_sha256": _sha256(canonical_json(case)),
                }
                for case in cases
            ],
            "contexts_artifact": CONTEXTS,
            "contexts_sha256": _sha256(context_bytes),
            "asked": (
                "each case once per mechanism per candidate, one call at a time, through "
                "ModelClient.choose with the role's messages and choice for the request's context, "
                "the host's token bound for the model (answer_tokens) and the contract's deadline "
                f"({contract.value('decision_deadline_ms')} ms); the line held to check_line at the "
                "request's bound; the client given the manifest with each candidate's answering "
                "naming both mechanisms, nothing else changed"
            ),
            "verdict_rule": {
                "answers": (
                    f"at least {PLAIN_VERIFIED_AT_LEAST} of the {PLAIN_CASES} plain cases' answers "
                    "name an offered label"
                ),
                "answers_lines": (
                    f"at least {LINE_VERIFIED_AT_LEAST} of the {LINE_CASES} line cases' answers name "
                    "an offered label with a line exactly where it says something, within the rule"
                ),
                "manifest": (
                    "a mechanism that answers joins the model's answering, naming the record; a "
                    "model none of whose answering mechanisms answers_lines gets a "
                    "not_offered_for_lines sentence; a model with no mechanism that answers is "
                    "left out of the answering set"
                ),
            },
            "measured": [
                "per call: the outcome (an offered label, a label not offered, a line where none "
                "is said or none where one is, a line breaking the rule, an answer that is not a "
                "choice, the provider refusing the request, a timeout, a failed call), the "
                "label's kind, the line's length, tokens, cost and time",
                "per model and mechanism: the verdicts above",
            ],
            "stop_rule": (
                f"The whole probe stops at the bound (USD {BOUND_USD}, {MAX_CALLS} calls) or after "
                f"{ERRORS_STOP} failed calls in a row, writing what it asked and why it stopped. A model and mechanism "
                f"stops after {REFUSALS_STOP} refusals of the request by its provider, the rest "
                "of its cases recorded as not asked."
            ),
            "bound_usd": str(BOUND_USD),
            "max_calls": MAX_CALLS,
            "prompt_version": terms.prompt_version,
            "contract": contract.binding(),
            "manifest_sha256": _manifest_sha256(),
            "tree": _tree(),
            "files_sha256": {path: _sha256((ROOT / path).read_bytes()) for path in READS},
            "record": RECORD,
            "not_covered": [
                f"{PLAIN_CASES + LINE_CASES} synthetic requests of one square, asked once each by "
                "each mechanism: how often an answer varies between identical asks is not measured.",
                "Whether a choice or a line is apt, kind or in character is not judged; only its "
                "shape is.",
                "Answer time is the provider's from this machine at the time of the probe.",
            ],
        },
    )


# -- the probe ------------------------------------------------------------------------------------


def _outcome(case: Mapping[str, Any], chosen: Any, line_kinds: frozenset[str]) -> dict[str, Any]:
    from exulanica.things.lines import LineRefused, check_line

    option = next((o for o in case["options"] if o["label"] == chosen.label), None)
    if option is None:
        return {"outcome": "label_not_offered"}
    says = option["kind"] in line_kinds
    found: dict[str, Any] = {"chose_kind": option["kind"]}
    if says != bool(chosen.line):
        return {**found, "outcome": "line_where_none" if chosen.line else "no_line_where_one"}
    if not says:
        return {**found, "outcome": "offered_label"}
    try:
        checked = check_line(chosen.line, maximum=case["line_characters_maximum"])
    except LineRefused as exc:
        return {**found, "outcome": "line_breaks_rule", "detail": str(exc)}
    return {**found, "outcome": "offered_label_with_line", "line_characters": len(checked)}


def _probe_manifest() -> Any:
    """The manifest with each candidate's ``answering`` naming both mechanisms, which the probe
    decides; every other field as the tree holds it."""
    from exulanica.models.manifest import MANIFEST_PATH, parse_manifest

    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    for model_id in CANDIDATES:
        document["models"][model_id]["answering"] = {
            mechanism: f"docs/evaluation/{Path(RECORD).name}"
            for mechanism in ("json_schema", "tool_call")
        }
    return parse_manifest(document)


def probe(as_run: bytes) -> None:
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.policy import BenchmarkInputs
    from exulanica.world.society_decision_contract import person_role

    tree = _tree()
    registered = _read_record(PREREGISTRATION)
    if _measured(tree) != _measured(registered["tree"]):
        raise SystemExit("the tree is not the pre-registered one")
    if _sha256(as_run) != registered["files_sha256"][SCRIPT]:
        raise SystemExit("the bytes running are not the pre-registered script")
    for path, digest in registered["files_sha256"].items():
        if _sha256((ROOT / path).read_bytes()) != digest:
            raise SystemExit(f"{path} is not the pre-registered file")
    if (ROOT / RECORD).exists():
        raise SystemExit(f"{RECORD} exists")
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    if _sha256(context_bytes) != registered["contexts_sha256"]:
        raise SystemExit("the contexts are not the ones the pre-registration binds")
    cases = json.loads(context_bytes)["cases"]
    bound = _bound(BOUND_USD)
    manifest = _probe_manifest()
    role = person_role()
    contract = role.contract(role.terms(ENGINE).versions)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(manifest.bound_origins()))
    budget = BudgetGuard(ceiling_usd=bound, max_calls=MAX_CALLS)
    client = ModelClient(manifest=manifest, budget=budget).with_policy(
        BenchmarkInputs(BENCHMARK_REASON)
    )
    deadline = contract.value("decision_deadline_ms") / 1000
    calls: list[dict[str, Any]] = []
    try:
        _ask(client, manifest, cases, deadline, calls)
        stopped = None
    except _Stopped as exc:
        stopped = str(exc)
    _write_new_bytes(SCRIPT_AS_RUN, as_run)
    _write_new(
        RECORD,
        {
            "preregistration": PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "script_as_run": SCRIPT_AS_RUN,
            "script_sha256": _sha256(as_run),
            "tree": tree,
            "manifest_sha256": _manifest_sha256(),
            "calls": calls,
            "stopped": stopped,
            "findings": findings(calls),
            "verdicts": verdicts(calls),
            "spent_usd": str(budget.spent_usd),
            "bound_usd": str(bound),
            "within_bound": budget.spent_usd <= bound,
        },
    )


class _Stopped(Exception):
    """The probe's stop rule ended it: what it asked is still written, with why it stopped."""


def _ask(
    client: Any,
    manifest: Any,
    cases: Sequence[Mapping[str, Any]],
    deadline: float,
    calls: list[dict[str, Any]],
) -> None:
    """Ask every candidate each case once by each mechanism, appending each call as it ends."""
    from exulanica.api.society_person_decisions import answer_tokens
    from exulanica.models.choice import ChoiceRefused
    from exulanica.models.errors import (
        BudgetExceededError,
        ModelError,
        ProviderRefused,
        TransportError,
    )
    from exulanica.world.society_decision_contract import LINE_KINDS, person_role

    role = person_role()
    terms = role.terms(ENGINE)
    failed_in_a_row = 0
    for model_id in CANDIDATES:
        spec = manifest.spec(model_id)
        for mechanism in sorted(spec.answering, key=lambda m: m.value):
            refused = 0
            for number, case in enumerate(cases, 1):
                entry: dict[str, Any] = {
                    "model_id": spec.model_id,
                    "mechanism": mechanism.value,
                    "case": number,
                    "takes_line": role.takes_line(case),
                }
                if refused >= REFUSALS_STOP:
                    calls.append({**entry, "outcome": "not_asked"})
                    continue
                heard: list[Any] = []
                sender = client.with_attempts(heard.append)
                started = time.monotonic()
                try:
                    chosen = sender.choose(
                        role.chosen,
                        spec.model_id,
                        role.adapter.messages(role, case, mechanism),
                        role.choice(case),
                        mechanism=mechanism,
                        prompt_version=terms.prompt_version,
                        timeout=deadline,
                        max_tokens=answer_tokens(spec),
                    )
                except BudgetExceededError:
                    raise _Stopped("the probe reached its bound") from None
                except ChoiceRefused as exc:
                    # Why, in the client's words: which argument the reply got wrong. The cases are
                    # synthetic, so the words quote nothing of anybody's.
                    cause = exc.__cause__
                    entry.update(
                        outcome="answer_not_a_choice",
                        detail=str(exc)[:400],
                        **({"cause": str(cause)[:400]} if cause is not None else {}),
                    )
                except ProviderRefused as exc:
                    # Refused before anything was sent: this process may not reach the provider.
                    raise _Stopped(f"{spec.provider} is not reachable here: {exc.reason}") from None
                except TransportError as exc:
                    if exc.reached_provider is True and not exc.retryable and not exc.timed_out:
                        # The provider understood the request and refused it: the schema, likely.
                        refused += 1
                        entry.update(outcome="provider_refused_request")
                    else:
                        entry.update(
                            outcome="timed_out" if exc.timed_out else "call_failed",
                            detail=type(exc).__name__,
                        )
                except ModelError as exc:
                    entry.update(outcome="model_error", detail=type(exc).__name__)
                else:
                    entry.update(_outcome(case, chosen, LINE_KINDS))
                    entry["served_model_id"] = chosen.call.served_model_id
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
                    f"{spec.model_id} {mechanism.value} case {number}: {entry['outcome']} "
                    f"{entry['latency_ms']} ms",
                    flush=True,
                )
                failing = entry["outcome"] in {
                    "provider_refused_request",
                    "timed_out",
                    "call_failed",
                    "model_error",
                }
                failed_in_a_row = failed_in_a_row + 1 if failing else 0
                if failed_in_a_row >= ERRORS_STOP:
                    raise _Stopped(f"{ERRORS_STOP} failed calls in a row")


def findings(calls: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """Per model and mechanism, how many calls ended each way."""
    found: dict[str, dict[str, Counter[str]]] = {}
    for call in calls:
        found.setdefault(call["model_id"], {}).setdefault(call["mechanism"], Counter())[
            call["outcome"]
        ] += 1
    return {
        model: {mechanism: dict(sorted(counts.items())) for mechanism, counts in sorted(by.items())}
        for model, by in sorted(found.items())
    }


def verdicts(calls: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Per model and mechanism, the pre-registered verdicts and the counts they are read from."""
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for call in calls:
        held = found.setdefault(call["model_id"], {}).setdefault(
            call["mechanism"],
            {"plain_asked": 0, "plain_named_a_label": 0, "line_asked": 0, "line_exact": 0},
        )
        if call["takes_line"]:
            held["line_asked"] += 1
            held["line_exact"] += call["outcome"] in ANSWERS_EXACTLY
        else:
            held["plain_asked"] += 1
            held["plain_named_a_label"] += call["outcome"] in NAMES_A_LABEL
    for by in found.values():
        for held in by.values():
            held["verified"] = held["plain_named_a_label"] >= PLAIN_VERIFIED_AT_LEAST
            held["answers_lines"] = held["line_exact"] >= LINE_VERIFIED_AT_LEAST
    return found


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=("contexts", "preregister", "probe"))
    step = parser.parse_args(argv).step
    if step == "contexts":
        contexts()
    elif step == "preregister":
        preregister()
    else:
        probe(Path(__file__).read_bytes())


if __name__ == "__main__":
    main()
