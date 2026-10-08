#!/usr/bin/env python3
"""Does every open model a person's decisions are offered answer the choice that takes a line?

    uv run python scripts/measure_society_line_choice.py contexts
    uv run python scripts/measure_society_line_choice.py preregister
    uv run python scripts/measure_society_line_choice.py probe

**The question.** A society of things' people are asked under their engine's own terms: one
function, ``act``, whose ``action`` is one of the offered labels and whose ``line`` is a string of
at most the request's ``line_characters_maximum`` characters, or null, both arguments required
(``exulanica/models/choice.py``). The manifest says which models answer a choice and by which
mechanism from probes of the one-argument choice alone. Does each model the manifest offers a
person's decisions answer the two-argument one, by each mechanism its entry lists: does its
provider accept the schema (a ``maxLength`` among them), does it name an offered label, does it
give a line exactly where the label says something, and is that line within the line rule?

**The cases** are ``CASES`` requests of a knight in a society of things beside the people who hear
it, built in memory by ``contexts`` from the tests' own starter square, before any model is
asked: each offers saying something to one being, saying something to everyone near and the
routine's own options, under the terms v7 asks by.

**The probe** asks every offered model each case once by each mechanism, one call at a time,
through the product's client (``ModelClient.choose``) as the host asks, with the host's token bound
for the model and the contract's deadline, and the model's line held to the line rule
(``check_line``) as the host holds it. A provider that refuses the schema twice for a model and
mechanism stops that pair: that refusal is itself the finding.

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
    _offered,
    _read_record,
    _sha256,
    _tree,
    _write_new,
    _write_new_bytes,
)

from exulanica.canonical import canonical_json  # noqa: E402

#: Ignored and untracked: a per-model record of a hosted provider's models is published only once the
#: provider's terms allow it, so the probe writes beside the worktree, not under docs/evaluation.
OUTPUT: Final = ".exulanica/line-choice-probe"
PREREGISTRATION: Final = f"{OUTPUT}/preregistration.json"
RECORD: Final = f"{OUTPUT}/record.json"
ARTIFACTS: Final = OUTPUT
CONTEXTS: Final = f"{ARTIFACTS}/contexts.json"
RUN: Final = f"{ARTIFACTS}/probe-run.json"
SCRIPT: Final = "scripts/measure_society_line_choice.py"
SCRIPT_AS_RUN: Final = f"{ARTIFACTS}/measure_society_line_choice-as-run.py.txt"
ENGINE: Final = "exulanica-society/v7"
CASES: Final = 16
BOUND_USD: Final = Decimal("0.25")
#: One call for each of the 16 cases by each mechanism of each of the four offered models.
MAX_CALLS: Final = 128
#: A provider refusing the schema this many times for one model and mechanism stops that pair.
SCHEMA_REFUSALS_STOP: Final = 2
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
    "A recorded measurement asks each offered model a fixed set of synthetic requests built from "
    "the tests' own starter square; no person's data is in them."
)


# -- the cases ------------------------------------------------------------------------------------


def contexts() -> None:
    """``CASES`` requests of a knight beside hearers, under v7's terms, asking nothing."""
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
    for number in range(CASES):
        # A knight placed somewhere else on the square each time, and the people moved beside it.
        knight = thing("knight", "knight", 1, -6_000 + 800 * number, 3_000 - 300 * number)
        document = compose((gate, knight))
        state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
        placed = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
        near = [p for p in state["inhabitants"] if p["came_by"] == "populated"][: 1 + number % 3]
        for offset, person in enumerate(near, 1):
            person["position_mm"] = [
                placed["position_mm"][0] + 1_500 * offset,
                placed["position_mm"][1],
            ]
        options = choice_options(state, document, placed["id"], contract, seed=SEED)
        kinds = {option.kind for option in options}
        if not {"say_to", "say_all"} <= kinds:
            raise SystemExit(f"case {number + 1} offers nothing to say")
        cases.append(decision_context(state, document, placed["id"], options))
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
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    cases = json.loads(context_bytes)["cases"]
    manifest = load_manifest()
    _write_new(
        PREREGISTRATION,
        {
            "question": (
                "Does every model the manifest offers a person's decisions answer the choice that "
                "takes a line (action and line, the line a string of at most the request's bound "
                "or null), by each mechanism its manifest entry lists: does its provider accept "
                "the schema, does it name an offered label, does it give a line exactly where the "
                "label says something, and is that line within the line rule?"
            ),
            "written_before_this_measurement_asked_any_model": True,
            "models": {
                spec.model_id: sorted(m.value for m in spec.answering)
                for spec in _offered(manifest, contract)
            },
            "cases": [
                {
                    "options": len(case["options"]),
                    "kinds": dict(sorted(Counter(o["kind"] for o in case["options"]).items())),
                    "context_sha256": _sha256(canonical_json(case)),
                }
                for case in cases
            ],
            "contexts_artifact": CONTEXTS,
            "contexts_sha256": _sha256(context_bytes),
            "asked": (
                "each case once per mechanism a model's manifest entry lists, one call at a time, "
                "through ModelClient.choose with the role's messages and choice for the request's "
                "context, the host's token bound for the model (answer_tokens) and the contract's "
                "deadline; the line held to check_line at the request's bound"
            ),
            "measured": [
                "per call: the outcome (an offered label, a label not offered, a line where none "
                "is said or none where one is, a line breaking the rule, the provider refusing "
                "the request, a timeout), the label's kind, the line's length, tokens and time",
                "per model and mechanism: how many answered an offered label with a line exactly "
                "where it says something and within the rule; how many the provider refused",
            ],
            "stop_rule": (
                f"The whole probe stops at the bound. A model and mechanism stops after "
                f"{SCHEMA_REFUSALS_STOP} refusals of the request by its provider, the rest of its "
                "cases recorded as not asked."
            ),
            "bound_usd": str(BOUND_USD),
            "prompt_version": terms.prompt_version,
            "contract": contract.binding(),
            "manifest_sha256": _manifest_sha256(),
            "tree": _tree(),
            "files_sha256": {path: _sha256((ROOT / path).read_bytes()) for path in READS},
            "max_calls": MAX_CALLS,
            "record": RECORD,
            "not_covered": [
                f"{CASES} synthetic requests of one square, asked once each by each mechanism: how "
                "often an answer varies between identical asks is not measured.",
                "Whether a line is apt, kind or in character is not judged; only its shape is.",
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


def probe(as_run: bytes) -> None:
    from exulanica.api.society_person_decisions import answer_tokens
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.choice import ChoiceRefused
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.errors import (
        BudgetExceededError,
        ModelError,
        ProviderRefused,
        TransportError,
    )
    from exulanica.models.manifest import load_manifest
    from exulanica.models.policy import BenchmarkInputs
    from exulanica.world.society_decision_contract import LINE_KINDS, person_role

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
    manifest = load_manifest()
    role = person_role()
    terms = role.terms(ENGINE)
    contract = role.contract(terms.versions)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(manifest.bound_origins()))
    budget = BudgetGuard(ceiling_usd=bound, max_calls=MAX_CALLS)
    client = ModelClient(manifest=manifest, budget=budget).with_policy(
        BenchmarkInputs(BENCHMARK_REASON)
    )
    deadline = contract.value("decision_deadline_ms") / 1000
    calls: list[dict[str, Any]] = []
    for spec in _offered(manifest, contract):
        for mechanism in sorted(spec.answering, key=lambda m: m.value):
            refused = 0
            for number, case in enumerate(cases, 1):
                entry: dict[str, Any] = {
                    "model_id": spec.model_id,
                    "mechanism": mechanism.value,
                    "case": number,
                }
                if refused >= SCHEMA_REFUSALS_STOP:
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
                    raise SystemExit("the probe reached its bound; nothing is written") from None
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
                    raise SystemExit(
                        f"{spec.provider} is not reachable here: {exc.reason}"
                    ) from None
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
                    f"{spec.model_id} {mechanism.value} case {number}: {entry['outcome']}",
                    flush=True,
                )
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
            "findings": findings(calls),
            "spent_usd": str(budget.spent_usd),
            "bound_usd": str(bound),
            "within_bound": budget.spent_usd <= bound,
        },
    )


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
