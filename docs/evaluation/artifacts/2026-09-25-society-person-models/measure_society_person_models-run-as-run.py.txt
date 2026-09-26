#!/usr/bin/env python3
"""Which open models can decide for a person in a world, and what do they decide there?

    uv run python scripts/measure_society_person_models.py contexts
    uv run python scripts/measure_society_person_models.py dry-run
    uv run python scripts/measure_society_person_models.py preregister
    uv run python scripts/measure_society_person_models.py probe
    uv run python scripts/measure_society_person_models.py run

**The question.** A world's owner may choose a model to decide for some of its people. Which of
the candidate open models answer the decision contract's one choice by a mechanism the product
asks with, a forced call of the function ``act`` or a JSON schema, and, each run in the small
square of a starter world for an hour of simulated time, what do they decide, how often is what
they decide acted on, and what does it take and cost?

**One pre-registration** (``preregister``) states the probe and the run before either asks
anything, with the tree they are to measure: every path that differs from HEAD, tracked or not,
each by its digest. It is written after the contexts the probe asks and a scripted dry run of the
run's harness (``dry-run``), neither of which asks a model. The probe and the run each take the
tree again before their first call and refuse to ask anything unless it is the pre-registered one
apart from the records and artifacts under ``RECORDS_DIRECTORY``, which this script writes, and,
for the run, the manifest's ``answering`` entries, which the probe's verdicts decide. Each reads
its own bytes once, before anything else, and those are the bytes its record binds. Every record
and artifact is written by this script; none is edited after.

**The probe** asks every candidate each of ``PROBE_CASES`` recorded choices once by each
mechanism, through the product's client (``ModelClient.choose``) as the host asks: the contract's
instruction and the person's situation (``decision_messages``), the choice built from the
contract's options (``choice_request``), the host's token bound for the model
(``answer_tokens``), and the contract's deadline.
The choices are people at a choice point in the small square under its routine alone, read by
``contexts`` from the first ``CONTEXT_MINUTES`` minutes before any model is asked. A mechanism is
verified for a model when at least ``VERIFIED_AT_LEAST`` of its first answers are one of the
offered actions as the product reads them. The probe record names every verdict; the manifest's
``answering`` entries name the probe record, and the run refuses a manifest they disagree with.

**The run** plays one fresh starter world per arm, the routine alone and each model the manifest
offers, with the small square placed where a person arrives and its people brought in with the
browser's own seed, for ``TICKS`` simulated minutes. In a model's arm every person is chosen for
that model through the owner's own route, and the world is set playing through the control route.
Every minute is a claim of the playback worker the application builds for the workspaces it lists
(``Services.build_society_control_worker``): the claim, the host's decision phase before the
minute (``PersonDecisionHost.before_minute``), then the minute. The one thing the harness does that
a host does not is make each claim due at once, rather than wait the host's base interval. Then
the models route's read, every receipt, and a replay of the whole history with the process's
billed calls counted before and after.

**Spend.** The key is read from the environment, ``KEY_VARIABLE`` only, and reaches nothing but the
client. Each asking invocation reads its bound from ``BUDGET_VARIABLE`` and refuses a bound above
the one pre-registered for it. The run's bound is what people's decisions may spend: the process's
ceiling is set so that the share the decision contract lets them use, all but its
``process_reserve_percent``, is the bound, and nothing else in the process asks a model.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_living_square import bring_in, make_square, minute_of  # noqa: E402
from measure_living_world_pace import Api, _database, seeds  # noqa: E402

from exulanica.canonical import canonical_json  # noqa: E402

PROFILE: Final = "exulanica.digest-bound-record/v1"
PREREGISTRATION: Final = "docs/evaluation/2026-09-25-society-person-models-preregistration.json"
PROBE_RECORD: Final = "docs/evaluation/2026-09-25-society-person-models-probe.json"
RECORD: Final = "docs/evaluation/2026-09-25-society-person-models.json"
ARTIFACTS: Final = "docs/evaluation/artifacts/2026-09-25-society-person-models"
CONTEXTS: Final = f"{ARTIFACTS}/contexts.json"
DRY_RUN: Final = f"{ARTIFACTS}/dry-run.json"
PROBE_RUN: Final = f"{ARTIFACTS}/probe-run.json"
RUN: Final = f"{ARTIFACTS}/run.json"
PROBE_AS_RUN: Final = f"{ARTIFACTS}/measure_society_person_models-probe-as-run.py.txt"
RUN_AS_RUN: Final = f"{ARTIFACTS}/measure_society_person_models-run-as-run.py.txt"
MANIFEST_RELATIVE: Final = "exulanica/models/models.manifest.json"
#: Where this script's records and artifacts go: the one part of a tree a run does not measure.
RECORDS_DIRECTORY: Final = "docs/evaluation/"

#: The open models the probe asks: two small reasoning models from NVIDIA, a large model that
#: answers without reasoning, and a reasoning model from DeepSeek, all in the manifest already.
CANDIDATES: Final = (
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/Nemotron-3_5-Lightning",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
)
#: The browser's own seed, the one "Bring in inhabitants" sends first.
SEED: Final = seeds()[0]
CONTEXT_MINUTES: Final = 30
PROBE_CASES: Final = 6
VERIFIED_AT_LEAST: Final = 5
TICKS: Final = 60
MINUTES_PER_HOUR: Final = 60
KEY_VARIABLE: Final = "NEBIUS_API_KEY"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
MAX_CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"
#: Bounds on what each asking invocation may spend, together within what this measurement may.
PROBE_BOUND_USD: Final = Decimal("0.01")
RUN_BOUND_USD: Final = Decimal("0.11")
#: Far above what either invocation makes; the dollar bound is what stops one.
MAX_CALLS: Final = 2000
BENCHMARK_REASON: Final = (
    "decision contexts of the simulated people of a synthetic square: invented people, invented "
    "places, no account holder's data"
)

#: Said by the run record of what came before it.
#: Each earlier measurement of these models, and why it was not kept, in words.
EARLIER_MEASUREMENTS: Final = (
    "The first probe and run were not kept: the tree they bound was taken after their calls and "
    "left untracked files out, so it could not show which code they measured, and the run's "
    "harness played the minutes itself rather than through the playback worker's claim.",
    "The second run was not kept: the probe record it followed was edited by hand after the probe "
    "wrote it, and the code changed after the run, so it did not measure the code that lands.",
    "The third probe and run were not kept: the code changed after them, so they did not measure "
    "the code that lands.",
)


# -- records --------------------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document(record: dict[str, Any]) -> dict[str, Any]:
    return {"profile": PROFILE, "record": record, "record_sha256": _sha256(canonical_json(record))}


def _write_new(relative: str, value: dict[str, Any], *, record: bool = True) -> None:
    target = ROOT / relative
    if target.exists():
        raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = _document(value) if record else value
    target.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {relative}", flush=True)


def _read_record(relative: str) -> dict[str, Any]:
    document = json.loads((ROOT / relative).read_bytes())
    if _sha256(canonical_json(document["record"])) != document["record_sha256"]:
        raise SystemExit(f"{relative} does not match its own digest")
    return document["record"]


def _manifest_sha256() -> str:
    from exulanica.models.manifest import MANIFEST_PATH

    return _sha256(MANIFEST_PATH.read_bytes())


def _manifest_without_answering_sha256() -> str:
    """The manifest's digest with every model's ``answering`` left out, which the probe decides."""
    from exulanica.models.manifest import MANIFEST_PATH

    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for model in document["models"].values():
        model.pop("answering", None)
    return _sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())


def _registered(tree: Mapping[str, Any], *, answering_may_change: bool) -> dict[str, Any]:
    """The pre-registration, refusing a tree other than the one it states.

    Records and artifacts are what this script writes, so they may differ. The manifest may differ
    only in its ``answering`` entries, and only for the run, which follows the probe's verdicts.
    """
    registered = _read_record(PREREGISTRATION)
    measured, bound = _measured(tree), _measured(registered["tree"])
    ignored = {MANIFEST_RELATIVE} if answering_may_change else set()
    differ = sorted(
        path
        for path in {*measured["files_sha256"], *bound["files_sha256"]} - ignored
        if measured["files_sha256"].get(path) != bound["files_sha256"].get(path)
    )
    if measured["head"] != bound["head"] or differ:
        raise SystemExit(f"the tree is not the pre-registered one: {measured['head']} {differ}")
    if _manifest_without_answering_sha256() != registered["manifest_without_answering_sha256"]:
        raise SystemExit("the manifest differs from the pre-registered one beyond its answering")
    return registered


def _bound(limit: Decimal) -> Decimal:
    """This invocation's spend bound, from the environment, no higher than ``limit``."""
    raw = os.environ.get(BUDGET_VARIABLE)
    if not raw:
        raise SystemExit(f"{BUDGET_VARIABLE} must state this invocation's bound")
    bound = Decimal(raw)
    if not Decimal(0) < bound <= limit:
        raise SystemExit(f"{BUDGET_VARIABLE}={bound} is not within (0, {limit}]")
    if not os.environ.get(KEY_VARIABLE):
        raise SystemExit(f"{KEY_VARIABLE} is not in this process's environment")
    return bound


def _tree() -> dict[str, Any]:
    """The tree as it is now: HEAD, and the digest of every path that differs from it, tracked
    or not, so a new file is bound as surely as a changed one. A deleted path's digest is None."""

    def git(*arguments: str) -> bytes:
        return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout

    changed = git("diff", "HEAD", "--name-only", "-z").decode().split("\0")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    files: dict[str, str | None] = {}
    for path in sorted({path for path in (*changed, *untracked) if path}):
        target = ROOT / path
        files[path] = _sha256(target.read_bytes()) if target.is_file() else None
    return {"head": git("rev-parse", "HEAD").decode().strip(), "files_sha256": files}


def _measured(tree: Mapping[str, Any]) -> dict[str, Any]:
    """What a run measures of a tree: all of it but the records and artifacts this script writes."""
    return {
        "head": tree["head"],
        "files_sha256": {
            path: digest
            for path, digest in tree["files_sha256"].items()
            if not path.startswith(RECORDS_DIRECTORY)
        },
    }


def _nearest_rank(values: Sequence[int], share: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-share * len(ordered) // 100) - 1)]


# -- the application ------------------------------------------------------------------------------


def _grant() -> dict[str, Any]:
    return {"id": uuid.uuid4(), "actor": uuid.uuid4(), "token": f"person-models-{uuid.uuid4().hex}"}


@contextlib.contextmanager
def _application(
    grants: Sequence[Mapping[str, Any]],
    *,
    live: bool = False,
    model_client: Any = None,
) -> Iterator[tuple[Any, Any, dict[str, str]]]:
    """The product in process over a private PostgreSQL, as the runtime role, with ``grants``.

    It starts with no workspace listed, so it starts no playback thread of its own; ``_play``
    lists them. With ``live`` the client is the one the deployment builds from the environment.
    """
    import psycopg
    from fastapi.testclient import TestClient

    from exulanica.api.app import create_app
    from exulanica.api.authorisation import API_TOKENS_ENV
    from exulanica.api.permissions import Permission
    from exulanica.api.services import (
        DATA_DIR_ENV,
        DERIVATIVE_WORKER_ENV,
        READONLY_DATABASE_URL_ENV,
        build_services,
    )
    from exulanica.db.migrate import provision_workspace
    from exulanica.db.session import DATABASE_URL_ENV

    data_dir = Path(tempfile.mkdtemp(prefix="society-person-models-"))
    with _database() as urls:
        with psycopg.connect(urls["owner"], autocommit=True) as owner:
            for grant in grants:
                provision_workspace(owner, grant["id"])
        environ = {
            DATABASE_URL_ENV: urls["runtime"],
            READONLY_DATABASE_URL_ENV: urls["readonly"],
            DATA_DIR_ENV: str(data_dir),
            DERIVATIVE_WORKER_ENV: "off",
            API_TOKENS_ENV: json.dumps(
                {
                    grant["token"]: {
                        "workspace_id": str(grant["id"]),
                        "actor": str(grant["actor"]),
                        "permissions": [str(permission) for permission in Permission],
                    }
                    for grant in grants
                }
            ),
        }
        if live:
            # The one variable the manifest's provider names, as the deployment passes it.
            environ[KEY_VARIABLE] = os.environ[KEY_VARIABLE]
        services = build_services(environ, model_client=model_client)
        if live and services.model_client is None:
            raise SystemExit("the application built no model client from the environment")
        with TestClient(create_app(services, verify=False)) as http:
            yield http, services, urls


def _latest_input(owner_url: str, society_id: str) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(owner_url, row_factory=dict_row) as connection:
        row = connection.execute(
            "select document from world_society_input where society_id=%s "
            "order by input_seq desc limit 1",
            (society_id,),
        ).fetchone()
    return row["document"]


def _receipts(owner_url: str, society_id: str) -> list[dict[str, Any]]:
    """Every person decision the society recorded, with its request and what its minute did."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(owner_url, row_factory=dict_row) as connection:
        return connection.execute(
            "select d.decision_seq,d.document,r.document as request,t.disposition,t.tick,"
            "(select e.document->>'reason' from world_society_event e "
            "where e.society_id=d.society_id and e.tick=t.tick "
            "and e.event_kind='decision_applied' "
            "and (e.document->>'decision_seq')::bigint=d.decision_seq) as disposition_reason "
            "from world_society_decision d join world_society_decision_request r "
            "using(workspace_id,society_id,request_id) "
            "left join world_society_transition_decision t "
            "using(workspace_id,society_id,decision_seq) "
            "where d.society_id=%s order by d.decision_seq",
            (society_id,),
        ).fetchall()


def _step(api: Api, world: dict[str, Any], control: dict, state: dict) -> tuple[dict, dict]:
    stepped = api(
        "POST",
        f"/world/versions/{world['version']}/society/control/steps",
        params=world["scope"],
        json={
            "base_revision": control["revision"],
            "base_tick": state["current_tick"],
            "base_state_sha256": state["state_sha256"],
        },
    )
    return stepped["control"], stepped["society"]


# -- contexts -------------------------------------------------------------------------------------


def pick_cases(found: Sequence[Mapping[str, Any]], count: int) -> list[dict[str, Any]]:
    """``count`` contexts spread over how many options they offer, deterministically.

    Ordered by the number of options, then minute and person, and taken at evenly spaced ranks,
    so the fewest and the most options are both asked and duplicates of one situation are not.
    """
    ordered = sorted(
        found, key=lambda context: (len(context["options"]), context["tick"], context["subject_id"])
    )
    if len(ordered) < count:
        raise SystemExit(f"the square offered {len(ordered)} choices, fewer than {count}")
    ranks = sorted({round(index * (len(ordered) - 1) / (count - 1)) for index in range(count)})
    return [dict(ordered[rank]) for rank in ranks]


def contexts() -> None:
    from exulanica.world.society_decision_contract import (
        at_choice_point,
        choice_options,
        decision_context,
        decision_contract,
    )

    contract = decision_contract()
    owner = _grant()
    found: list[dict[str, Any]] = []
    with _application([owner]) as (http, _services, urls):
        api = Api(http, owner["token"])
        world = make_square(api, "Society person models: contexts")
        bring_in(api, world, SEED)
        society = f"/world/versions/{world['version']}/society"
        control = api("GET", society + "/control", params=world["scope"])
        state = api("GET", society, params=world["scope"])
        for _ in range(CONTEXT_MINUTES):
            document = _latest_input(urls["owner"], state["society_id"])
            for person in state["state"]["inhabitants"]:
                if not at_choice_point(person):
                    continue
                options = choice_options(
                    state["state"], document, person["id"], contract, seed=SEED
                )
                if options:
                    found.append(decision_context(state["state"], document, person["id"], options))
            control, state = _step(api, world, control, state)
    cases = pick_cases(found, PROBE_CASES)
    _write_new(
        CONTEXTS,
        {
            "profile": "exulanica.society-person-model-contexts/v1",
            "seed": SEED,
            "minutes": CONTEXT_MINUTES,
            "choices_found": len(found),
            "contract": contract.binding(),
            "cases": cases,
        },
        record=False,
    )


# -- the scripted model ---------------------------------------------------------------------------


class ScriptedChooser:
    """A model that picks one offered action by a seeded draw, for the dry run. No network.

    It answers by whichever mechanism the request asks with: a call of the forced function, or
    content matching the response format's schema.
    """

    def __init__(self, seed: str) -> None:
        self.random = random.Random(seed)
        self.call_count = 0

    def post_json(self, url, *, headers, payload, timeout):
        from exulanica.models.transport import HttpResponse

        self.call_count += 1
        if "tools" in payload:
            schema = payload["tools"][0]["function"]["parameters"]
        else:
            schema = payload["response_format"]["json_schema"]["schema"]
        answer = json.dumps({"action": self.random.choice(schema["properties"]["action"]["enum"])})
        message: dict[str, Any] = {"role": "assistant", "content": answer}
        finish = "stop"
        if "tools" in payload:
            finish = "tool_calls"
            message["content"] = None
            message["tool_calls"] = [
                {"id": "call", "type": "function", "function": {"name": "act", "arguments": answer}}
            ]
        body = {
            "id": f"scripted-{self.call_count}",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 300, "total_tokens": 1100},
        }
        return HttpResponse(200, json.dumps(body))


def _probe_manifest(mechanisms: Sequence[str], record: str) -> Any:
    """The manifest with every candidate verified for ``mechanisms`` by ``record``."""
    from exulanica.models.manifest import MANIFEST_PATH, parse_manifest

    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    for model_id in CANDIDATES:
        document["models"][model_id]["answering"] = {mechanism: record for mechanism in mechanisms}
    return parse_manifest(document)


# -- arms -----------------------------------------------------------------------------------------


def _due_now(database: Any, workspace: uuid.UUID, society_id: str) -> None:
    """Make a playing society due at once, as it is when the host's wait is over. A claim takes
    the workspace's most overdue society, so the arm's must be the one society playing there."""
    with database.session(workspace) as connection:
        playing = connection.execute(
            "select society_id from world_society_control where workspace_id=%s and mode='playing'",
            (workspace,),
        ).fetchall()
        if [str(row["society_id"]) for row in playing] != [society_id]:
            raise SystemExit(
                f"society {society_id} is not the one society playing in its workspace"
            )
        connection.execute(
            "update world_society_control set next_due_at=clock_timestamp()-interval '1 millisecond' "
            "where workspace_id=%s and society_id=%s",
            (workspace, society_id),
        )


def _arm(
    http: Any,
    grant: Mapping[str, Any],
    services: Any,
    worker: Any,
    owner_url: str,
    model: Mapping[str, str] | None,
    billed: Any,
) -> dict[str, Any]:
    """One world, played ``TICKS`` minutes by the playback worker, its people run by ``model`` or
    by their routine."""
    api = Api(http, grant["token"])
    label = "routine" if model is None else model["model_id"]
    world = make_square(api, f"Society person models: {label}")
    bring_in(api, world, SEED)
    society = f"/world/versions/{world['version']}/society"
    state = api("GET", society, params=world["scope"])
    people = sorted(person["id"] for person in state["state"]["inhabitants"])
    if model is not None:
        api(
            "POST",
            society + "/models",
            params=world["scope"],
            json={"idempotency_key": str(uuid.uuid4()), "people": people, "model": dict(model)},
        )
    control = api("GET", society + "/control", params=world["scope"])
    api(
        "PUT",
        society + "/control",
        params=world["scope"],
        json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
    )
    minutes: list[dict[str, Any]] = []
    claims: list[int] = []
    advanced: list[int] = []
    started = time.monotonic()
    while state["current_tick"] < TICKS:
        _due_now(services.database, grant["id"], state["society_id"])
        claimed = time.monotonic()
        result = worker.run_once(grant["id"])
        claims.append(round((time.monotonic() - claimed) * 1000))
        if result is None or "receipt" not in result:
            raise SystemExit(f"{label}: a due claim advanced no minute: {result}")
        advanced.append(result["receipt"]["executed_ticks"])
        state = api("GET", society, params=world["scope"])
        counts = Counter(minute_of(person)[0] for person in state["state"]["inhabitants"])
        minutes.append({"tick": state["current_tick"], **dict(sorted(counts.items()))})
    wall_ms = round((time.monotonic() - started) * 1000)
    read = api("GET", society + "/models", params=world["scope"])
    receipts = _receipts(owner_url, state["society_id"])
    before = billed()
    replay = api("GET", society + "/replay", params=world["scope"])
    return {
        "arm": label,
        "model": None if model is None else dict(model),
        "people": len(people),
        "minutes": minutes,
        "claim_ms": claims,
        "minutes_per_claim": advanced,
        "wall_ms": wall_ms,
        "decisions": [_decision(row) for row in receipts],
        "by_model": read["by_model"],
        "host_refusal": read["host_refusal"],
        "replay_verified": replay.get("replay_verified"),
        "billed_calls_during_replay": billed() - before,
        "state_sha256": state["state_sha256"],
    }


def _decision(row: Mapping[str, Any]) -> dict[str, Any]:
    receipt, request = row["document"], row["request"]
    provider = receipt["provider"] or {}
    proposal = receipt["proposal"]
    option = None if proposal is None else proposal["option"]
    return {
        "decision_seq": row["decision_seq"],
        "subject_id": receipt["subject_id"],
        "base_tick": receipt["base_tick"],
        "consumed_tick": row["tick"],
        "options": len(request["context"]["options"]),
        "mechanism": request["provider_config"]["mechanism"],
        "status": receipt["status"],
        "reason": receipt["reason"],
        "disposition": row["disposition"],
        "disposition_reason": row["disposition_reason"],
        "chose_kind": None if option is None else option["kind"],
        "chose_activity": None if option is None else option["activity"],
        "chose_walk_mm": None if option is None else option["walk_mm"],
        "answers_asked": provider.get("answers_asked"),
        "outcomes": [call["outcome"] for call in provider.get("calls", [])],
        "latency_ms": provider.get("latency_ms"),
        "prompt_tokens": provider.get("prompt_tokens"),
        "completion_tokens": provider.get("completion_tokens"),
        "cost_usd": provider.get("cost_usd"),
        "cost_known": provider.get("cost_known"),
        "served_model_id": provider.get("served_model_id"),
    }


def summarise(arm: Mapping[str, Any]) -> dict[str, Any]:
    """One arm's decisions and minutes as the comparison reads them."""
    decisions = arm["decisions"]
    asked = [d for d in decisions if d["answers_asked"]]
    settled = [d for d in decisions if d["disposition"] is not None]
    applied = [d for d in settled if d["disposition"] == "applied"]
    latencies = [d["latency_ms"] for d in asked if d["latency_ms"] is not None]
    cost = sum((Decimal(d["cost_usd"]) for d in asked), Decimal(0))
    person_minutes: Counter[str] = Counter()
    for minute in arm["minutes"]:
        person_minutes.update({k: v for k, v in minute.items() if k != "tick"})
    chose = [d for d in decisions if d["status"] == "accepted"]
    walks = [d["chose_walk_mm"] for d in chose if d["chose_walk_mm"] is not None]
    return {
        "arm": arm["arm"],
        "people": arm["people"],
        "decisions": len(decisions),
        "asked": len(asked),
        "accepted": len(chose),
        "first_answer_accepted": sum(1 for d in chose if d["answers_asked"] == 1),
        "applied": len(applied),
        "settled": len(settled),
        "not_acted_on_share": (
            None
            if not settled
            else str(
                (Decimal(len(settled) - len(applied)) / len(settled)).quantize(Decimal("0.001"))
            )
        ),
        "by_reason": dict(sorted(Counter(d["reason"] for d in decisions).items())),
        "by_disposition": dict(
            sorted(Counter(d["disposition"] or "pending" for d in decisions).items())
        ),
        # Why each settled decision was not acted on, once each, as the models route counts it:
        # the receipt's reason, or the minute's when an accepted one was not acted on.
        "not_acted_on": dict(
            sorted(
                Counter(
                    d["reason"] if d["status"] != "accepted" else d["disposition_reason"]
                    for d in settled
                    if d["disposition"] != "applied"
                ).items()
            )
        ),
        "chose": dict(
            sorted(
                Counter(
                    "wait" if d["chose_kind"] == "wait" else f"go:{d['chose_activity']}"
                    for d in chose
                ).items()
            )
        ),
        "chose_walk_mm_median": None if not walks else round(statistics.median(walks)),
        "latency_ms": {
            "p50": _nearest_rank(latencies, 50),
            "p95": _nearest_rank(latencies, 95),
            "longest": max(latencies) if latencies else None,
        },
        "prompt_tokens": sum(d["prompt_tokens"] or 0 for d in asked),
        "completion_tokens": sum(d["completion_tokens"] or 0 for d in asked),
        "cost_usd": str(cost),
        "cost_known": all(d["cost_known"] for d in asked),
        "cost_usd_per_simulated_hour": str(
            (cost * MINUTES_PER_HOUR / TICKS).quantize(Decimal("0.000001"))
        ),
        "person_minutes": dict(sorted(person_minutes.items())),
        "claim_ms": {
            "p50": _nearest_rank(arm["claim_ms"], 50),
            "p95": _nearest_rank(arm["claim_ms"], 95),
            "longest": max(arm["claim_ms"]),
        },
        "claims": len(arm["claim_ms"]),
        "claims_advancing_more_than_one_minute": sum(
            1 for minutes in arm["minutes_per_claim"] if minutes != 1
        ),
        "host_refusal_at_the_end": arm["host_refusal"],
        "replay_verified": arm["replay_verified"],
        "billed_calls_during_replay": arm["billed_calls_during_replay"],
    }


def _offered(manifest: Any, contract: Any) -> list[Any]:
    """The models the manifest offers a person's decisions that the contract can ask, in order."""
    from exulanica.models.manifest import Role

    return [
        spec
        for spec in manifest.offered_models(Role.SOCIETY_DECISION)
        if contract.mechanism_for(spec) is not None
    ]


def _play(models: Sequence[Mapping[str, str]], *, live: bool, client: Any = None) -> dict[str, Any]:
    """Every arm, the routine first, each in a workspace of its own in one application.

    Once it has started, every arm's workspace is listed, as a host's environment lists the
    workspaces it plays (``EXULANICA_SOCIETY_CONTROL_WORKSPACES``), and the playback worker and
    its decision phase are the ones the application builds for that listing.
    """
    grants = {arm: _grant() for arm in ["routine", *(m["model_id"] for m in models)]}
    arms = []
    with _application(list(grants.values()), live=live, model_client=client) as (
        http,
        services,
        urls,
    ):
        listed = dataclasses.replace(
            services, society_control_workspaces=tuple(grant["id"] for grant in grants.values())
        )
        http.app.state.services = listed
        worker = listed.build_society_control_worker()
        if worker is None:
            raise SystemExit("the application built no playback worker for the listed workspaces")
        budget = listed.model_client.budget if listed.model_client is not None else None

        def billed() -> int:
            return 0 if budget is None else budget.billed_calls

        for model in [None, *models]:
            key = "routine" if model is None else model["model_id"]
            arm = _arm(http, grants[key], listed, worker, urls["owner"], model, billed)
            print(f"{key}: {len(arm['decisions'])} decisions", flush=True)
            arms.append(arm)
        spent = None if budget is None else str(budget.spent_usd)
        ceiling = None if budget is None else str(budget.ceiling_usd)
    return {"arms": arms, "spent_usd": spent, "process_ceiling_usd": ceiling}


def dry_run() -> None:
    """Every arm with a scripted model, played as the run plays them: the harness checked, and
    each arm's decisions counted, before any bound is written. Asks no model."""
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import decision_contract

    if (ROOT / DRY_RUN).exists():
        raise SystemExit(f"{DRY_RUN} exists")
    tree = _tree()
    manifest = load_manifest()
    transport = ScriptedChooser(SEED)
    client = ModelClient(
        api_key="dry-run-not-a-credential",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10 * MAX_CALLS),
    )
    models = [
        {"provider": spec.provider, "model_id": spec.model_id}
        for spec in _offered(manifest, decision_contract())
    ]
    played = _play(models, live=False, client=client)
    _write_new(
        DRY_RUN,
        {
            "profile": "exulanica.society-person-models-dry-run/v2",
            "tree": tree,
            "models": models,
            "scripted_calls": transport.call_count,
            "summaries": [summarise(arm) for arm in played["arms"]],
        },
        record=False,
    )


# -- the pre-registration -------------------------------------------------------------------------


def _ceiling(bound: Decimal, contract: Any) -> Decimal:
    """The process's ceiling whose share for people's decisions is ``bound``."""
    return (bound * 100 / (100 - contract.value("process_reserve_percent"))).quantize(
        Decimal("0.000001")
    )


def _ceiling_calls(calls: int, contract: Any) -> int:
    """The process's call limit whose share for people's decisions is ``calls``."""
    return calls * 100 // (100 - contract.value("process_reserve_percent"))


def preregister() -> None:
    from exulanica.world.society_decision_contract import PROMPT_VERSION, decision_contract

    if (ROOT / PREREGISTRATION).exists():
        raise SystemExit(f"{PREREGISTRATION} is already written")
    tree = _tree()
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    dry_bytes = (ROOT / DRY_RUN).read_bytes()
    dry = json.loads(dry_bytes)
    if _measured(dry["tree"]) != _measured(tree):
        raise SystemExit("the tree changed since the dry run; run the dry run again")
    cases = json.loads(context_bytes)["cases"]
    contract = decision_contract()
    people = dry["summaries"][0]["people"]
    record = {
        "question": (
            "Which candidate open models answer a person's decision in a world by a mechanism "
            "the product asks with (a forced call of act, or a JSON schema), and, each deciding "
            f"for the {people} people of the small square for {TICKS} simulated minutes as a "
            "host's playback plays a world, what they decide, how often it is acted on, and what "
            "it takes and costs, beside the routine alone."
        ),
        "written_before_this_measurement_asked_any_model": True,
        "earlier_measurements": list(EARLIER_MEASUREMENTS),
        "candidates": list(CANDIDATES),
        "probe": {
            "cases": [
                {
                    "tick": case["tick"],
                    "subject_id": case["subject_id"],
                    "options": len(case["options"]),
                    "context_sha256": _sha256(canonical_json(case)),
                }
                for case in cases
            ],
            "contexts_artifact": CONTEXTS,
            "contexts_sha256": _sha256(context_bytes),
            "mechanisms": ["tool_call", "json_schema"],
            "asked": (
                "each case once per mechanism per candidate through ModelClient.choose, with "
                "decision_messages, choice_request, the host's token bound for the model "
                "(answer_tokens), the contract's deadline and temperature 0; no retry"
            ),
            "verified_when": (
                f"at least {VERIFIED_AT_LEAST} of the {PROBE_CASES} first answers are one of the "
                "offered actions as the product reads them"
            ),
            "bound_usd": str(PROBE_BOUND_USD),
            "record": PROBE_RECORD,
        },
        "run": {
            "arms": (
                "the routine alone, then each model the manifest offers a person's decisions "
                "after the probe, in the manifest's order; the manifest's answering entries "
                "must be the probe's verdicts"
            ),
            "world": (
                "a starter world per arm, the small square placed where a person arrives, its "
                "people brought in with the profile exulanica-society/v2, and the world set "
                "playing at speed 1 through the control route"
            ),
            "seed": SEED,
            "ticks": TICKS,
            "every_person_run_by_the_arms_model": True,
            "played_by": (
                "the playback worker the application builds for the workspaces it lists "
                "(Services.build_society_control_worker), one claim at a time: the claim, the "
                "host's decision phase before the minute (PersonDecisionHost.before_minute), "
                "then the minute"
            ),
            "harness_intervention": (
                "each claim is made due at once, its next_due_at set a millisecond back, where "
                "a host waits its base interval"
            ),
            "measured": [
                "decisions, asked, accepted, accepted on the first answer, applied",
                "the share of settled decisions not acted on, by reason and disposition",
                "what was chosen: waiting, or going, by activity; median walk of a chosen place",
                "latency p50, p95 and longest; prompt and completion tokens; cost, and per hour",
                "person-minutes walking, using, waiting and otherwise",
                "each claim's wall time: the claim, the decision phase and the minute",
                "claims that advanced more than one minute",
                "the host's refusal, if any, when each arm ends",
                "replay verified, and the billed calls made during replay",
            ],
            "bound_usd": str(RUN_BOUND_USD),
            "process_ceiling_usd": str(_ceiling(RUN_BOUND_USD, contract)),
            "process_max_calls": _ceiling_calls(MAX_CALLS, contract),
            "bound_why": (
                "the decision contract lets people's decisions spend all but "
                "process_reserve_percent of the process's ceiling, and nothing else in the "
                "run's process asks a model, so the run spends at most its bound"
            ),
            "record": RECORD,
        },
        "dry_run": {
            "artifact": DRY_RUN,
            "sha256": _sha256(dry_bytes),
            "scripted_calls": dry["scripted_calls"],
            "decisions_per_arm": {
                summary["arm"]: summary["decisions"] for summary in dry["summaries"]
            },
        },
        "prompt_version": PROMPT_VERSION,
        "contract": contract.binding(),
        "spend_read_from": "the usage the provider reported, as the client's ledger counts it",
        "manifest_without_answering_sha256": _manifest_without_answering_sha256(),
        "tree": tree,
        "not_covered": [
            "One square, one seed and one hour of simulated time per model; other worlds, "
            "seeds and longer runs are not measured.",
            "Temperature 0 and one probe answer per case and mechanism; how often an answer "
            "varies between identical asks is not measured.",
            "The people are all run by one model in each arm; worlds mixing models, or mixing "
            "models with the routine, are not measured.",
            "The playback worker's own loop, its polling and its round across workspaces, is "
            "not measured: the harness makes each claim, one workspace at a time.",
            "Latency is the provider's from this machine at the time of the run, not a "
            "deployment's.",
            "Whether a model's choices are better for the people than the routine's is not "
            "judged; the record states what each chose.",
        ],
    }
    _write_new(PREREGISTRATION, record)


# -- the probe ------------------------------------------------------------------------------------


def verdicts(calls: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each candidate's verified mechanisms, by the pre-registered rule, from the probe's calls."""
    found: dict[str, dict[str, Any]] = {}
    for model_id in CANDIDATES:
        by_mechanism = {}
        for mechanism in ("tool_call", "json_schema"):
            asked = [c for c in calls if c["model_id"] == model_id and c["mechanism"] == mechanism]
            valid = sum(1 for c in asked if c["outcome"] == "offered_action")
            by_mechanism[mechanism] = {
                "asked": len(asked),
                "offered_action": valid,
                "verified": len(asked) == PROBE_CASES and valid >= VERIFIED_AT_LEAST,
            }
        found[model_id] = by_mechanism
    return found


def probe(as_run: bytes) -> None:
    from exulanica.api.society_person_decisions import answer_tokens
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.choice import ChoiceRefused
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.errors import (
        BudgetExceededError,
        ModelError,
        TransportError,
        TruncatedResponseError,
    )
    from exulanica.models.manifest import AnsweringMechanism, Role, load_manifest
    from exulanica.models.policy import BenchmarkInputs
    from exulanica.world.society_decision_contract import (
        PROMPT_VERSION,
        choice_request,
        decision_contract,
        decision_messages,
    )

    # The tree, before anything is asked.
    tree = _tree()
    registered = _registered(tree, answering_may_change=False)
    if _sha256(as_run) != tree["files_sha256"].get("scripts/measure_society_person_models.py"):
        raise SystemExit("the bytes running are not the script the tree binds")
    if (ROOT / PROBE_RECORD).exists():
        raise SystemExit(f"{PROBE_RECORD} exists")
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    if _sha256(context_bytes) != registered["probe"]["contexts_sha256"]:
        raise SystemExit("the contexts are not the ones the pre-registration binds")
    cases = json.loads(context_bytes)["cases"]
    bound = _bound(PROBE_BOUND_USD)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    manifest = _probe_manifest(["tool_call", "json_schema"], PROBE_RECORD)
    budget = BudgetGuard(ceiling_usd=bound, max_calls=MAX_CALLS)
    client = ModelClient(manifest=manifest, budget=budget).with_policy(
        BenchmarkInputs(BENCHMARK_REASON)
    )
    deadline = decision_contract().value("decision_deadline_ms") / 1000
    calls: list[dict[str, Any]] = []
    for model_id in CANDIDATES:
        for mechanism in (AnsweringMechanism.TOOL_CALL, AnsweringMechanism.JSON_SCHEMA):
            for number, case in enumerate(cases, 1):
                heard: list[Any] = []
                sender = client.with_attempts(heard.append)
                entry: dict[str, Any] = {
                    "model_id": model_id,
                    "mechanism": mechanism.value,
                    "case": number,
                    "options": len(case["options"]),
                }
                started = time.monotonic()
                try:
                    chosen = sender.choose(
                        Role.SOCIETY_DECISION,
                        model_id,
                        decision_messages(case, mechanism),
                        choice_request(case),
                        mechanism=mechanism,
                        prompt_version=PROMPT_VERSION,
                        timeout=deadline,
                        max_tokens=answer_tokens(manifest.spec(model_id)),
                    )
                except BudgetExceededError:
                    raise SystemExit("the probe reached its bound; nothing is written") from None
                except ChoiceRefused as exc:
                    entry.update(outcome="not_an_offered_action", detail=str(exc)[:300])
                except TruncatedResponseError:
                    entry.update(outcome="truncated")
                except TransportError as exc:
                    entry.update(
                        outcome="timed_out" if exc.timed_out else "call_failed",
                        detail=type(exc).__name__,
                    )
                except ModelError as exc:
                    entry.update(outcome="model_error", detail=type(exc).__name__)
                else:
                    entry.update(
                        outcome="offered_action",
                        label=chosen.label,
                        served_model_id=chosen.call.served_model_id,
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
                print(f"{model_id} {mechanism.value} case {number}: {entry['outcome']}", flush=True)
    found = verdicts(calls)
    run = {
        "profile": "exulanica.society-person-models-probe-run/v2",
        "tree": tree,
        "manifest_sha256": _manifest_sha256(),
        "calls": calls,
        "spent_usd": str(budget.spent_usd),
    }
    _write_new(PROBE_RUN, run, record=False)
    _write_new_bytes(PROBE_AS_RUN, as_run)
    _write_new(
        PROBE_RECORD,
        {
            "preregistration": PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "run_artifact": PROBE_RUN,
            "run_sha256": _sha256((ROOT / PROBE_RUN).read_bytes()),
            "script_as_run": PROBE_AS_RUN,
            "script_sha256": _sha256(as_run),
            "tree": tree,
            "manifest_sha256": run["manifest_sha256"],
            "verified_when": registered["probe"]["verified_when"],
            "verdicts": found,
            "answering": {
                model_id: sorted(m for m, verdict in by.items() if verdict["verified"])
                for model_id, by in found.items()
            },
            "spent_usd": run["spent_usd"],
            "bound_usd": str(bound),
        },
    )


def _write_new_bytes(relative: str, data: bytes) -> None:
    target = ROOT / relative
    if target.exists():
        raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    target.write_bytes(data)
    print(f"wrote {relative}", flush=True)


# -- the run --------------------------------------------------------------------------------------


def run(as_run: bytes) -> None:
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import decision_contract

    # The tree, before anything is asked.
    tree = _tree()
    registered = _registered(tree, answering_may_change=True)
    if _sha256(as_run) != tree["files_sha256"].get("scripts/measure_society_person_models.py"):
        raise SystemExit("the bytes running are not the script the tree binds")
    probed = _read_record(PROBE_RECORD)
    if probed["preregistration_record_sha256"] != _sha256(canonical_json(registered)):
        raise SystemExit(f"{PROBE_RECORD} follows another pre-registration")
    if (ROOT / RECORD).exists():
        raise SystemExit(f"{RECORD} exists")
    bound = _bound(RUN_BOUND_USD)
    manifest = load_manifest()
    contract = decision_contract()
    offered = _offered(manifest, contract)
    for spec in offered:
        if set(spec.answering.values()) != {PROBE_RECORD}:
            raise SystemExit(f"{spec.model_id}'s answering names a record other than the probe's")
        if sorted(str(m) for m in spec.answering) != probed["answering"].get(spec.model_id):
            raise SystemExit(f"{spec.model_id}'s answering is not the probe's verdict")
    models = [{"provider": spec.provider, "model_id": spec.model_id} for spec in offered]
    ceiling = _ceiling(bound, contract)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(manifest.bound_origins()))
    os.environ[BUDGET_VARIABLE] = str(ceiling)
    os.environ[MAX_CALLS_VARIABLE] = str(_ceiling_calls(MAX_CALLS, contract))
    played = _play(models, live=True)
    _write_new(
        RUN,
        {
            "profile": "exulanica.society-person-models-run/v2",
            "tree": tree,
            "manifest_sha256": _manifest_sha256(),
            **played,
        },
        record=False,
    )
    _write_new_bytes(RUN_AS_RUN, as_run)
    _write_new(
        RECORD,
        {
            "preregistration": PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "probe_record": PROBE_RECORD,
            "probe_record_sha256": _sha256(canonical_json(probed)),
            "earlier_measurements": list(EARLIER_MEASUREMENTS),
            "run_artifact": RUN,
            "run_sha256": _sha256((ROOT / RUN).read_bytes()),
            "script_as_run": RUN_AS_RUN,
            "script_sha256": _sha256(as_run),
            "tree": tree,
            "manifest_sha256": _manifest_sha256(),
            "mechanisms": {spec.model_id: str(contract.mechanism_for(spec)) for spec in offered},
            "summaries": [summarise(arm) for arm in played["arms"]],
            "spent_usd": played["spent_usd"],
            "bound_usd": str(bound),
            "process_ceiling_usd": played["process_ceiling_usd"],
            "within_bound": Decimal(played["spent_usd"]) <= bound,
        },
    )


def main(argv: Sequence[str] | None = None) -> None:
    # The bytes that run, read before anything else can change the file.
    as_run = Path(__file__).read_bytes()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=("contexts", "dry-run", "preregister", "probe", "run"))
    step = parser.parse_args(argv).step
    if step == "probe":
        probe(as_run)
    elif step == "run":
        run(as_run)
    else:
        {"contexts": contexts, "dry-run": dry_run, "preregister": preregister}[step]()


if __name__ == "__main__":
    main()
