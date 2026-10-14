#!/usr/bin/env python3
"""Can an open model running on this computer be a being's mind, and how fast does it answer here?

    uv run python scripts/measure_laptop_mind_probe.py contexts
    uv run python scripts/measure_laptop_mind_probe.py preregister
    uv run python scripts/measure_laptop_mind_probe.py probe
    uv run python scripts/measure_laptop_mind_probe.py publish

**The question** is the candidate mind probe's (``scripts/measure_society_mind_probe.py``), asked of
open models an Ollama server on this computer serves: by each mechanism the client asks with, does
the candidate answer a society of things' being's choice as the host asks it, naming an offered
label, with a line of at most the request's bound exactly where the label says something, within
the host's token bound and the contract's deadline? The cases, the outcomes and the verdict rule
are that probe's, read from it, so the two probes hold every candidate to one rule.

**What differs** is where the model runs. Each candidate is a colon-free alias an Ollama server
serves (``CANDIDATES``), created from a library model with the context its recipe states, asked
at ``http://localhost:11434/v1`` through the product's client built to ask only a provider on this
computer (``ModelClient(local_only=True)``): no credential is read and the egress allowlist this
script hands the client names the laptop's origin alone, so no request can leave the machine and
nothing can be billed. Ollama does not honour ``tool_choice``, so the client's ``tool_call``
mechanism (one function forced by name) is not what a laptop model is asked by that name: its
outcomes are recorded, and the pre-registration admits it to no model's answering.

**Speed.** Each candidate is asked, after its model is unloaded, every case one at a time by each
mechanism (the first ask waits for the load), then every case by ``json_schema`` with eight asks
in flight at once, cold (after an unload) and again warm: the host asks up to eight beings at once
within one deadline. Every ask's time, outcome and completion tokens are recorded, and so is the
memory the loaded model holds and the server's version and model digests.

**No spend and no record of a person.** The cases are built from the tests' own starter square.
Everything is written by this script under ``OUTPUT`` (ignored) and copied unchanged into
``docs/evaluation`` by ``publish``, once the probe asked everything it pre-registered.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
# The tree this script measures, ahead of any installed copy of the package.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import measure_society_mind_probe as mind  # noqa: E402
from measure_society_person_models import (  # noqa: E402
    _manifest_sha256,
    _measured,
    _nearest_rank,
    _read_record,
    _sha256,
    _tree,
    _write_new,
    _write_new_bytes,
)

from exulanica.canonical import canonical_json  # noqa: E402

#: Ignored and untracked until ``publish`` copies the finished records into docs/evaluation.
OUTPUT: Final = ".exulanica/laptop-probe"
CONTEXTS: Final = f"{OUTPUT}/contexts.json"
PREREGISTRATION: Final = f"{OUTPUT}/preregistration.json"
RECORD: Final = f"{OUTPUT}/record.json"
SCRIPT: Final = "scripts/measure_laptop_mind_probe.py"
SCRIPT_AS_RUN: Final = f"{OUTPUT}/measure_laptop_mind_probe-as-run.py.txt"
PUBLISHED_PREREGISTRATION: Final = (
    "docs/evaluation/2026-10-13-laptop-mind-probe-preregistration.json"
)
PUBLISHED_RECORD: Final = "docs/evaluation/2026-10-13-laptop-mind-probe.json"
#: The provider every candidate is served by, as the manifest declares it.
PROVIDER: Final = "ollama_local"
SERVER: Final = "http://localhost:11434"
#: What every candidate's manifest entry states beside its description: no price, the context its
#: recipe gives it, an answer bound well above a choice's longest answer, a schema it answers by.
_ENTRY: Final[Mapping[str, Any]] = {
    "provider": PROVIDER,
    "input_usd_per_mtok": 0,
    "output_usd_per_mtok": 0,
    "context_window_tokens": 16384,
    "min_max_tokens": 256,
    "default_max_tokens": 512,
    "emits_inline_reasoning": False,
    "supports_json_schema": True,
    "catalog_type": "text2text",
    "catalog_use_cases": ["text"],
    "catalog_license": "apache-2.0",
    "region_informational": "this computer",
}
_QWEN: Final = (
    "Qwen3 4B Instruct, an open model from the Qwen team that runs on this computer and answers "
    "without reasoning first."
)
#: Each candidate: the alias the server serves, the recipe it was created by (the library model,
#: the context, and where a recipe names them the server's own renderer and parser for the
#: model's chat format), and the manifest entry it is asked under (``answering`` aside, which the
#: probe decides). The two Qwen recipes differ only in how the chat is written: the library
#: model's own, under which the server 0.34.4 reads the weights' embedded chat template as one
#: that thinks and lets the model write freely before a schema's answer; and the server's Qwen
#: chat renderer and parser, which do not.
CANDIDATES: Final[Mapping[str, Mapping[str, Any]]] = {
    "exulanica-qwen3-4b-instruct-2507": {
        "recipe": {"from": "qwen3:4b-instruct", "parameters": {"num_ctx": 16384}},
        "entry": {**_ENTRY, "description": _QWEN},
    },
    "exulanica-qwen3-4b-instruct-2507-nothink": {
        "recipe": {
            "from": "qwen3:4b-instruct",
            "parameters": {"num_ctx": 16384},
            "renderer": "qwen3-vl-instruct",
            "parser": "qwen3-vl-instruct",
        },
        "entry": {**_ENTRY, "description": _QWEN},
    },
    "exulanica-granite-4.1-8b": {
        "recipe": {"from": "granite4.1:8b", "parameters": {"num_ctx": 16384}},
        "entry": {
            **_ENTRY,
            "description": (
                "Granite 4.1 8B, an open model from IBM that runs on this computer and answers "
                "without reasoning first."
            ),
        },
    },
}
#: A provider refusing the request this many times for one model and mechanism stops that pair,
#: the rest of its cases recorded as not asked, as the hosted probe's rule does.
REFUSALS_STOP: Final = mind.REFUSALS_STOP
MECHANISMS: Final = ("json_schema", "tool_call")
#: The asks in flight at once in the concurrent phases: the host's concurrent_calls_maximum.
CONCURRENT: Final = 8
#: A failed call in a row this many times stops the probe, as the hosted probe's rule does.
ERRORS_STOP: Final = mind.ERRORS_STOP
#: The calls the process's budget admits: every pre-registered ask with room to spare. Every price
#: is zero, so no dollar figure can bind; the ceiling is stated only because a budget has one.
MAX_CALLS: Final = 400
BOUND_USD: Final = Decimal("0.01")
READS: Final = (
    SCRIPT,
    "scripts/measure_society_mind_probe.py",
    "scripts/measure_society_person_models.py",
    "exulanica/models/models.manifest.json",
    "exulanica/models/client.py",
    "exulanica/models/chain.py",
    "tests/things_society_support.py",
)
BENCHMARK_REASON: Final = (
    "A recorded measurement asks each candidate model on this computer a fixed set of synthetic "
    "requests built from the tests' own starter square; no person's data is in them."
)


# -- the server -------------------------------------------------------------------------------


def _server(path: str, payload: Mapping[str, Any] | None = None, timeout: float = 300) -> Any:
    """One call to the Ollama server's own API on this computer, outside the product's client."""
    import httpx

    with httpx.Client(timeout=timeout) as client:
        response = (
            client.get(f"{SERVER}{path}")
            if payload is None
            else client.post(f"{SERVER}{path}", json=dict(payload))
        )
        response.raise_for_status()
        return response.json()


def _unload_everything() -> None:
    """Unload every model the server holds, so the next ask waits for its model's load."""
    for loaded in _server("/api/ps").get("models", []):
        _server("/api/generate", {"model": loaded["name"], "keep_alive": 0})
    for _ in range(60):
        if not _server("/api/ps").get("models"):
            return
        time.sleep(0.5)
    raise SystemExit("the server did not unload its models")


def _served() -> dict[str, Any]:
    """The server's version and, for each candidate, its tag entry and recipe as served."""
    tags = {model["name"]: model for model in _server("/api/tags").get("models", [])}
    found: dict[str, Any] = {"version": _server("/api/version").get("version"), "candidates": {}}
    for model_id, candidate in CANDIDATES.items():
        tag = tags.get(f"{model_id}:latest")
        if tag is None:
            raise SystemExit(f"{model_id} is not served here: create it from its recipe")
        shown = _server("/api/show", {"model": model_id})
        source = tags.get(candidate["recipe"]["from"])
        found["candidates"][model_id] = {
            "digest": tag["digest"],
            "details": tag.get("details"),
            "capabilities": tag.get("capabilities"),
            "parameters": shown.get("parameters"),
            "recipe": candidate["recipe"],
            "from_digest": None if source is None else source["digest"],
        }
    return found


# -- the cases and the pre-registration ---------------------------------------------------------


def contexts() -> None:
    """The hosted probe's cases, built by its own code, written here instead of beside it."""
    mind.CONTEXTS = CONTEXTS
    mind.contexts()


def _candidate_manifest() -> Any:
    """The shipped manifest with each candidate added under the provider on this computer, its
    ``answering`` naming every mechanism, which the probe decides; nothing else differs."""
    from exulanica.models.manifest import MANIFEST_PATH, parse_manifest

    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    if PROVIDER not in document["providers"]:
        raise SystemExit(f"the manifest declares no provider {PROVIDER}")
    for model_id, candidate in CANDIDATES.items():
        if model_id in document["models"] and document["models"][model_id].get("answering"):
            raise SystemExit(f"{model_id} is already verified; this probe asks only new candidates")
        document["models"][model_id] = {
            **candidate["entry"],
            "answering": {
                mechanism: f"docs/evaluation/{Path(PUBLISHED_RECORD).name}"
                for mechanism in MECHANISMS
            },
        }
    return parse_manifest(document)


def preregister() -> None:
    from exulanica.world.society_decision_contract import person_role

    if (ROOT / PREREGISTRATION).exists():
        raise SystemExit(f"{PREREGISTRATION} is already written")
    role = person_role()
    terms = role.terms(mind.ENGINE)
    contract = role.contract(terms.versions)
    _candidate_manifest()
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    cases = json.loads(context_bytes)["cases"]
    deadline_ms = contract.value("decision_deadline_ms")
    _write_new(
        PREREGISTRATION,
        {
            "question": (
                "Can each candidate on this computer be a being's mind: by each mechanism the "
                "client asks with, does it answer a society of things' person's choice as the "
                "host asks it, naming an offered label, with a line of at most the request's bound "
                "exactly where the label says something, within the host's token bound and the "
                "contract's deadline; and how long does it take here, one ask at a time and eight "
                "at once?"
            ),
            "written_before_this_measurement_asked_any_model": True,
            "candidates": {
                model_id: {"recipe": candidate["recipe"], "entry": candidate["entry"]}
                for model_id, candidate in CANDIDATES.items()
            },
            "provider": PROVIDER,
            "server": SERVER,
            "mechanisms": list(MECHANISMS),
            "cases": [
                {
                    "takes_line": role.takes_line(case),
                    "options": len(case["options"]),
                    "context_sha256": _sha256(canonical_json(case)),
                }
                for case in cases
            ],
            "contexts_artifact": CONTEXTS,
            "contexts_sha256": _sha256(context_bytes),
            "asked": [
                "phase one_at_a_time: for each candidate, every model unloaded first, then each "
                "case once by each mechanism, one call at a time, through ModelClient.choose with "
                "the role's messages and choice for the case, the host's token bound for the "
                "model (answer_tokens) and the contract's deadline "
                f"({deadline_ms} ms); the line held to check_line at the request's bound",
                f"phase eight_cold: every model unloaded, then every case once by json_schema, "
                f"{CONCURRENT} asks in flight at once",
                f"phase eight_warm: the same again with the model loaded, {CONCURRENT} at once",
                "the client built with local_only=True over a transport whose egress allowlist "
                f"names {SERVER} alone; no credential is read and every price is zero",
            ],
            "verdict_rule": {
                "answers": (
                    f"at least {mind.PLAIN_VERIFIED_AT_LEAST} of the {mind.PLAIN_CASES} plain "
                    "cases' answers name an offered label"
                ),
                "answers_lines": (
                    f"at least {mind.LINE_VERIFIED_AT_LEAST} of the {mind.LINE_CASES} line cases' "
                    "answers name an offered label with a line exactly where it says something, "
                    "within the rule"
                ),
                "phase": "read from phase one_at_a_time alone",
                "manifest": (
                    "a json_schema verdict that answers joins the model's answering, naming the "
                    "published record; tool_call joins no model's answering whatever its counts, "
                    "because the server does not honour tool_choice, so the call is not forced as "
                    "the client's mechanism names it; a model whose json_schema does not "
                    "answers_lines gets a not_offered_for_lines sentence"
                ),
            },
            "choice_rule": (
                "A candidate is eligible when its json_schema verdict is verified and answers "
                f"lines, and no ask of it in phase eight_warm was ended by the {deadline_ms} ms "
                "deadline. The chosen model is the eligible candidate with the most exact answers "
                "by json_schema in phase one_at_a_time (plain cases naming an offered label and "
                "line cases answered exactly), ties broken by the lower 95th percentile ask time "
                "in phase eight_warm. With none eligible, no model on this computer is offered."
            ),
            "measured": [
                "per call: phase, model, mechanism, case, outcome (the hosted probe's outcomes), "
                "the label's kind, the line's length, completion and prompt tokens, time",
                "per candidate and phase: ask time at the 50th and 95th percentiles and the "
                "longest, the share of asks the deadline ended, the median completion tokens",
                "per candidate: the memory the loaded model holds (/api/ps size_vram), the "
                "server's version, the alias's and its source's digests and quantization",
                "per candidate: whether phase eight_warm chose the label phase one_at_a_time chose "
                "for each case by json_schema (the same ask asked again)",
            ],
            "stop_rule": (
                f"The probe stops after {ERRORS_STOP} failed calls in a row (timed out, failed in "
                "transport or a model error), writing what it asked and why it stopped. A model "
                f"and mechanism asked one at a time stops after {REFUSALS_STOP} refusals of the "
                "request by the server, the rest of its cases recorded as not asked."
            ),
            "max_calls": MAX_CALLS,
            "prompt_version": terms.prompt_version,
            "contract": contract.binding(),
            "manifest_sha256": _manifest_sha256(),
            "tree": _tree(),
            "files_sha256": {path: _sha256((ROOT / path).read_bytes()) for path in READS},
            "record": RECORD,
            "not_covered": [
                f"{len(cases)} synthetic requests of one square: whether a choice or a line is "
                "apt, kind or in character is not judged; only its shape is.",
                "Times are this computer's, with whatever else it was running; another computer "
                "answers at its own speed.",
                "Agreement with a hosted model's answers is not measured here: the requests a "
                "hosted model answered in a person's world are that person's data.",
            ],
        },
    )


# -- the probe ----------------------------------------------------------------------------------


class _Stopped(Exception):
    """The stop rule ended the probe: what it asked is still written, with why it stopped."""


def _client(manifest: Any, budget: Any) -> Any:
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import parse_egress_allowlist
    from exulanica.models.policy import BenchmarkInputs
    from exulanica.models.transport import HttpxTransport

    transport = HttpxTransport(egress=parse_egress_allowlist([SERVER]))
    return ModelClient(
        manifest=manifest, budget=budget, transport=transport, local_only=True
    ).with_policy(BenchmarkInputs(BENCHMARK_REASON))


def _ask_one(
    client: Any,
    manifest: Any,
    model_id: str,
    mechanism_name: str,
    number: int,
    case: Mapping[str, Any],
    deadline: float,
    phase: str,
) -> dict[str, Any]:
    """One case asked once, as the host asks it, and what came of it."""
    from exulanica.api.society_person_decisions import answer_tokens
    from exulanica.models.choice import ChoiceRefused
    from exulanica.models.errors import ModelError, ProviderRefused, TransportError
    from exulanica.models.manifest import AnsweringMechanism
    from exulanica.world.society_decision_contract import LINE_KINDS, person_role

    role = person_role()
    mechanism = AnsweringMechanism(mechanism_name)
    spec = manifest.spec(model_id)
    entry: dict[str, Any] = {
        "phase": phase,
        "model_id": model_id,
        "mechanism": mechanism_name,
        "case": number,
        "takes_line": role.takes_line(case),
    }
    heard: list[Any] = []
    sender = client.with_attempts(heard.append)
    started = time.monotonic()
    try:
        chosen = sender.choose(
            role.chosen,
            model_id,
            role.adapter.messages(role, case, mechanism),
            role.choice(case),
            mechanism=mechanism,
            prompt_version=role.terms(mind.ENGINE).prompt_version,
            timeout=deadline,
            max_tokens=answer_tokens(spec),
        )
    except ChoiceRefused as exc:
        cause = exc.__cause__
        entry.update(
            outcome="answer_not_a_choice",
            detail=str(exc)[:400],
            **({"cause": str(cause)[:400]} if cause is not None else {}),
        )
    except ProviderRefused as exc:
        raise _Stopped(f"{spec.provider} is refused here: {exc.reason}") from None
    except TransportError as exc:
        if exc.reached_provider is True and not exc.retryable and not exc.timed_out:
            entry.update(outcome="provider_refused_request", detail=str(exc)[:300])
        else:
            entry.update(
                outcome="timed_out" if exc.timed_out else "call_failed",
                detail=type(exc).__name__,
            )
    except ModelError as exc:
        entry.update(outcome="model_error", detail=f"{type(exc).__name__}: {str(exc)[:300]}")
    else:
        entry.update(mind._outcome(case, chosen, LINE_KINDS))
        entry["chose"] = chosen.label
        entry["line"] = chosen.line
        entry["served_model_id"] = chosen.call.served_model_id
    entry["latency_ms"] = round((time.monotonic() - started) * 1000)
    entry["attempts"] = [
        {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "usd": str(usage.usd),
        }
        for usage in heard
    ]
    print(
        f"{phase} {model_id} {mechanism_name} case {number}: {entry['outcome']} "
        f"{entry['latency_ms']} ms",
        flush=True,
    )
    return entry


_FAILING: Final = frozenset({"provider_refused_request", "timed_out", "call_failed", "model_error"})


def _in_turn(
    asks: Sequence[tuple[Mapping[str, Any], Callable[[], dict[str, Any]]]],
    calls: list[dict[str, Any]],
) -> None:
    """Each ask in turn. After ``REFUSALS_STOP`` refusals by the server the rest of these asks
    (one model and mechanism) are recorded as not asked; ``ERRORS_STOP`` other failures in a row
    stop the probe."""
    failed_in_a_row = 0
    refused = 0
    for named, ask in asks:
        if refused >= REFUSALS_STOP:
            calls.append({**named, "outcome": "not_asked", "attempts": [], "latency_ms": 0})
            continue
        entry = ask()
        calls.append(entry)
        if entry["outcome"] == "provider_refused_request":
            refused += 1
            continue
        failed_in_a_row = failed_in_a_row + 1 if entry["outcome"] in _FAILING else 0
        if failed_in_a_row >= ERRORS_STOP:
            raise _Stopped(f"{ERRORS_STOP} failed calls in a row")


def _at_once(asks: Sequence[Callable[[], dict[str, Any]]], calls: list[dict[str, Any]]) -> None:
    with ThreadPoolExecutor(max_workers=CONCURRENT) as pool:
        entries = list(pool.map(lambda ask: ask(), asks))
    calls.extend(entries)
    if sum(entry["outcome"] in _FAILING for entry in entries) >= len(entries):
        raise _Stopped("every ask of a concurrent phase failed")


def probe(as_run: bytes) -> None:
    from exulanica.models.budget import BudgetGuard
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
    manifest = _candidate_manifest()
    role = person_role()
    contract = role.contract(role.terms(mind.ENGINE).versions)
    deadline = contract.value("decision_deadline_ms") / 1000
    budget = BudgetGuard(ceiling_usd=BOUND_USD, max_calls=MAX_CALLS)
    client = _client(manifest, budget)
    served = _served()
    memory: dict[str, Any] = {}
    calls: list[dict[str, Any]] = []
    stopped = None

    def ask(model_id: str, mechanism: str, number: int, phase: str) -> Callable[[], dict]:
        case = cases[number - 1]
        return lambda: _ask_one(
            client, manifest, model_id, mechanism, number, case, deadline, phase
        )

    def named(model_id: str, mechanism: str, number: int, phase: str) -> dict[str, Any]:
        takes_line = role.takes_line(cases[number - 1])
        return {
            "phase": phase,
            "model_id": model_id,
            "mechanism": mechanism,
            "case": number,
            "takes_line": takes_line,
        }

    numbers = range(1, len(cases) + 1)
    try:
        for model_id in CANDIDATES:
            _unload_everything()
            for mechanism in MECHANISMS:
                _in_turn(
                    [
                        (
                            named(model_id, mechanism, n, "one_at_a_time"),
                            ask(model_id, mechanism, n, "one_at_a_time"),
                        )
                        for n in numbers
                    ],
                    calls,
                )
            memory[model_id] = _server("/api/ps").get("models")
            _unload_everything()
            _at_once([ask(model_id, "json_schema", n, "eight_cold") for n in numbers], calls)
            _at_once([ask(model_id, "json_schema", n, "eight_warm") for n in numbers], calls)
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
            "served": served,
            "memory": {
                model_id: [
                    {key: model.get(key) for key in ("name", "size", "size_vram", "context_length")}
                    for model in loaded or ()
                ]
                for model_id, loaded in memory.items()
            },
            "calls": calls,
            "stopped": stopped,
            "verdicts": verdicts(calls),
            "timing": timing(calls, deadline),
            "repeated": repeated(calls),
            "chosen": chosen_model(calls, deadline),
            "spent_usd": str(budget.spent_usd),
        },
    )


# -- what the record reads ----------------------------------------------------------------------


def verdicts(calls: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """The hosted probe's verdicts, read from phase one_at_a_time alone."""
    return mind.verdicts([call for call in calls if call["phase"] == "one_at_a_time"])


def timing(calls: Sequence[Mapping[str, Any]], deadline: float) -> dict[str, Any]:
    """Per candidate, mechanism and phase: ask times, the share the deadline ended, tokens."""
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for call in calls:
        if call["outcome"] == "not_asked":
            continue
        grouped.setdefault((call["model_id"], call["mechanism"], call["phase"]), []).append(call)
    found: dict[str, Any] = {}
    for (model_id, mechanism, phase), held in sorted(grouped.items()):
        times = [call["latency_ms"] for call in held]
        tokens = [
            attempt["completion_tokens"]
            for call in held
            for attempt in call["attempts"]
            if attempt["completion_tokens"] is not None
        ]
        found.setdefault(model_id, {}).setdefault(mechanism, {})[phase] = {
            "asks": len(held),
            "p50_ms": _nearest_rank(times, 50),
            "p95_ms": _nearest_rank(times, 95),
            "longest_ms": max(times) if times else None,
            "first_ms": held[0]["latency_ms"] if held else None,
            "ended_by_deadline": sum(call["outcome"] == "timed_out" for call in held),
            "deadline_ms": round(deadline * 1000),
            "completion_tokens_median": _nearest_rank(tokens, 50),
            "completion_tokens_longest": max(tokens) if tokens else None,
            "exact": sum(call["outcome"] in mind.ANSWERS_EXACTLY for call in held),
        }
    return found


def repeated(calls: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Per candidate, how often phase eight_warm chose the label phase one_at_a_time chose for
    the same case by json_schema."""
    first = {
        (call["model_id"], call["case"]): call.get("chose")
        for call in calls
        if call["phase"] == "one_at_a_time" and call["mechanism"] == "json_schema"
    }
    found: dict[str, dict[str, int]] = {}
    for call in calls:
        if call["phase"] != "eight_warm":
            continue
        earlier = first.get((call["model_id"], call["case"]))
        held = found.setdefault(call["model_id"], {"compared": 0, "same_label": 0})
        if earlier is not None and call.get("chose") is not None:
            held["compared"] += 1
            held["same_label"] += earlier == call["chose"]
    return found


def chosen_model(calls: Sequence[Mapping[str, Any]], deadline: float) -> dict[str, Any]:
    """The pre-registered choice rule, applied."""
    judged = verdicts(calls)
    timed = timing(calls, deadline)
    eligible = []
    for model_id in CANDIDATES:
        held = judged.get(model_id, {}).get("json_schema")
        warm = timed.get(model_id, {}).get("json_schema", {}).get("eight_warm")
        if not held or not warm:
            continue
        if held["verified"] and held["answers_lines"] and warm["ended_by_deadline"] == 0:
            exact = held["plain_named_a_label"] + held["line_exact"]
            eligible.append((-exact, warm["p95_ms"], model_id))
    eligible.sort()
    return {
        "eligible": [model_id for _, _, model_id in eligible],
        "chosen": eligible[0][2] if eligible else None,
    }


# -- publishing ---------------------------------------------------------------------------------


def publish() -> None:
    """Copy the pre-registration and the record, unchanged, into docs/evaluation."""
    registered = _read_record(PREREGISTRATION)
    record = _read_record(RECORD)
    if record["preregistration_record_sha256"] != _sha256(canonical_json(registered)):
        raise SystemExit("the record does not name this pre-registration")
    if _sha256((ROOT / SCRIPT).read_bytes()) != record["script_sha256"]:
        raise SystemExit(f"{SCRIPT} is not the script that asked")
    for source, target in (
        (PREREGISTRATION, PUBLISHED_PREREGISTRATION),
        (RECORD, PUBLISHED_RECORD),
    ):
        if (ROOT / target).exists():
            raise SystemExit(f"{target} exists, and docs/evaluation is append-only")
        shutil.copyfile(ROOT / source, ROOT / target)
        print(f"wrote {target}", flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=("contexts", "preregister", "probe", "publish"))
    step = parser.parse_args(argv).step
    os.chdir(ROOT)
    if step == "contexts":
        contexts()
    elif step == "preregister":
        preregister()
    elif step == "probe":
        probe(Path(__file__).read_bytes())
    else:
        publish()


if __name__ == "__main__":
    main()
