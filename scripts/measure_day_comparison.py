#!/usr/bin/env python3
"""Does swapping the open model that decides for twelve of a town's people change how they fare over a day?

    measure_day_comparison.py develop --out <file> --slot-state <file> --world <id> \\
        --version <uuid> --model <provider>/<id> --model <provider>/<id> --bound-usd <amount> \\
        (--dotenv <file> | --scripted-plan <file>) [--seed-key development_1] [--hours-most 8] \\
        [--stop-file <file>]
    measure_day_comparison.py preregister --name <record name> --slot-state <file> \\
        --world <id> --version <uuid> --model <provider>/<id> --model <provider>/<id> \\
        --development <comparison uuid> --bound-usd <amount>
    measure_day_comparison.py run --name <record name> --slot-state <file> --seeds <file> \\
        --dotenv <file> [--comparison <uuid>] [--stop-file <file>]
    measure_day_comparison.py record --name <record name> --slot-state <file> \\
        --comparison <uuid> [--notes <file>]

**The question.** A town made from the ``small_town`` recipe, its people brought into the living
town's society (``exulanica-society/v5``), one simulated day: 1440 minutes from its 06:00 genesis
to 06:00 the next day, played and sealed hour by hour. The first twelve of its people in the order
the plan route lists them (by name, then identity) are the group; everybody else keeps their
routine in every arm. With the group decided by the first model, run twice so its second run
bounds run-to-run variation, or by the second, how did the group's people fare under the fifth
score of a person in a world (``society-person-score.v5``: the fourth score's half need relief and
half variety over the day, each as a share of what their own routine gives them against waiting on
the same seed), and is the second model's difference from the first larger than the fourth
protocol lets a comparison claim and than the control pair's?

**The development day** (``develop``) plays the same design on one development seed the seed
catalog commits, under a bound of its own, and writes a report beside the lane's notes, not a
record: what each arm's model was asked over the day, what it cost and how long it took, so the
judged day is sized from a living town's own day. With ``--scripted-plan`` it rehearses every step
with the acceptance's scripted transport in place of a provider, refusing to start where a
provider could be reached, and spends nothing.

**The pre-registration** (``preregister``) states the comparison before any held-out seed is run:
the town (its recipe, its tiles' inputs by digest, the society input the comparison freezes by
sequence and digest, its people), the group and how it was chosen, the models and the arms, the
claim, the held-out seeds by digest (the seed catalog a day is defined under), the window, the
protocol's values, the verdict rule, the plan route's figures for the selection (what one decided
person's run can ask and call, what each arm's run can reserve, the longest the asking can take
and the calls each provider's bound holds), the bound and the process call ceiling, the stop
rules, the development day read from its stored runs with every run's integer terms, the scoring
binding and the tree it measures. It refuses a bound under what one seed needs to be admitted or
under the development day's spend for every seed with a quarter more.

**The run** (``run``) is judged once: it refuses when its record exists, when the tree is not the
registered one apart from ``docs/evaluation/``, when this script is not the registered one and when
the registered window to start it has passed. It reads the held-out seeds from ``--seeds``, uses
one only when the SHA-256 of its text is the catalog's commitment, and never prints or records
one. It plays the anchors first, then each seed's model runs, admitting a seed only while what is
left of the bound holds what one like it typically costs and what its runs can hold reserved at
once, and while the process has calls left for the most its runs can make, as a host does. Given
``--comparison``, it goes on with that comparison's open runs, each day's run from the last hour
it sealed. A stop leaves the open runs open and says why.

**The record** (``record``) is written from the comparison's stored runs and the result the
application's route serves: the verdict, every run's integer terms and score, what each run's
model was asked and what it cost, and every hour of every run read back through the run route,
which replays the hour from the state the hour before it sealed and holds it to its recorded
minute digests, events and receipts, and every run's day through the day route. The API those
reads go to answers models with the acceptance's scripted transport, which cannot reach a
provider, so no read is billed.

**Spend.** The key is read from the operator's ``.env`` inside this process only, by
:func:`exulanica.models.credentials.api_key_from_env`, and reaches nothing but the client; the
slot's API never holds it. Every call of every run is within the bound.

**Stops.** A run step stops, leaving its open runs open, when the stop file exists, when its hours
are spent (``develop``), or when the first sealed hour of a model run holds more provider failures
(``PROVIDER_FAILURES``) than answers. A run a host reason ended (a spent bound, a refused provider
or credential) is recorded as failed by its code and never played again.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"
KEY_VARIABLE: Final = "NEBIUS_API_KEY"
#: How much above the plan's most calls the process call ceiling is set: the most is already every
#: ask answered as often as the contract allows, and a tenth more leaves room for whatever else
#: the process's client is asked.
CALL_MARGIN: Final = Decimal("1.1")
#: How much above the development day's spend for every seed a judged bound must be.
SPEND_MARGIN: Final = Decimal("1.25")
#: How long after registration a held-out run may start, in hours.
RUN_WINDOW_HOURS: Final = 12
#: The group: the first this many of the town's people in the plan route's order.
GROUP_SIZE: Final = 12
RECIPE: Final = "small_town"
ROLE: Final = "society_decision"
WINDOW: Final = "day"
HOURS: Final = 24
DAY_TICKS: Final = 1440
#: A receipt's reasons that say the provider, not the model's answer, ended the ask.
PROVIDER_FAILURES: Final = frozenset({"model_call_failed", "model_timed_out", "model_unavailable"})
#: How often, in seconds, a playing run step looks for a first hour of provider failures.
FAILURE_CHECK_SECONDS: Final = 60
#: The outer profile every retained record under docs/evaluation carries
#: (tests/test_retained_evaluation_records.py); what a record is, is its own "kind".
OUTER_PROFILE: Final = "exulanica.digest-bound-record/v1"
PREREGISTRATION_KIND: Final = "exulanica.day-comparison-preregistration/v1"
RECORD_KIND: Final = "exulanica.day-comparison/v1"
DEVELOPMENT_KIND: Final = "exulanica.day-comparison-development/v1"
SCRIPTED_MODEL: Final = ROOT / "scripts" / "acceptance" / "scripted_model.py"


def _paths(name: str) -> dict[str, str]:
    """The records and as-run copies a comparison named ``name`` writes."""
    return {
        "preregistration": f"docs/evaluation/{name}-preregistration.json",
        "record": f"docs/evaluation/{name}.json",
        "script_as_run": f"docs/evaluation/artifacts/{name}/measure_day_comparison-as-run.py.txt",
        "record_script_as_run": f"docs/evaluation/artifacts/{name}/record-as-run.py.txt",
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _sealed(record: dict[str, Any], kind: str) -> dict[str, Any]:
    from exulanica.canonical import canonical_json

    inner = {"kind": kind, **record}
    return {
        "profile": OUTER_PROFILE,
        "record": inner,
        "record_sha256": _sha256(canonical_json(inner)),
    }


def _write_new(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise SystemExit(f"{path} exists: a record is written once")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def models_named(named: Sequence[str]) -> list[tuple[str, str]]:
    """``<provider>/<model id>`` pairs, exactly two and different: the first is run again as the
    control."""
    models = []
    for text in named:
        provider, _, model_id = text.partition("/")
        if not provider or not model_id:
            raise SystemExit(f"--model {text!r} is not <provider>/<model id>")
        models.append((provider, model_id))
    if len(models) != 2 or models[0] == models[1]:
        raise SystemExit("a judged day compares exactly two different models")
    return models


def seeds_from(text: str, committed: Sequence[str]) -> list[str]:
    """The seeds ``text`` holds whose digests ``committed`` names, in its order: one seed a line,
    ``#`` lines skipped. Refuses when any committed digest has no seed in the file."""
    from exulanica.world.society import seed_digest

    found = {
        seed_digest(line.strip()): line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }
    missing = [digest for digest in committed if digest not in found]
    if missing:
        raise SystemExit(f"the seeds file holds no seed for {len(missing)} committed digests")
    return [found[digest] for digest in committed]


def nearest_rank(values: Sequence[int], per_mille: int) -> int | None:
    """The nearest-rank percentile of ``values`` at ``per_mille``, an integer; None for none."""
    if not values:
        return None
    ordered = sorted(values)
    rank = -(-len(ordered) * per_mille // 1000)
    return ordered[max(rank, 1) - 1]


def least_bound(one_seed_suggested: str, development_spend: str, seeds: int) -> dict[str, str]:
    """The least judged bound: what the host needs left to admit one seed, and the development
    day's spend for every seed with a quarter more; the larger binds."""
    admitted = Decimal(one_seed_suggested)
    projected = Decimal(development_spend) * seeds * SPEND_MARGIN
    return {
        "one_seed_admitted_usd": str(admitted),
        "projected_from_development_usd": str(projected),
        "least_usd": str(max(admitted, projected)),
    }


def resumed_bound(
    bound: Decimal, spent_usd: str, minutes: Sequence[Mapping[str, Any]], at_once: int = 2
) -> Decimal:
    """What a comparison going on may still spend of ``bound``: less what its receipts say it
    spent, and less the most one minute of ``at_once`` runs can cost (each decided person asked at
    the dearest arm's ask bound), which a process that stopped inside a minute may have paid and
    never recorded."""
    decided = max(int(minute["decided"]) for minute in minutes)
    dearest = max(Decimal(minute["ask_bound_usd"]) for minute in minutes)
    return bound - Decimal(spent_usd) - at_once * decided * dearest


def provider_failed(asked: int, failed: int) -> bool:
    """Whether an hour's provider failures outnumber the asks they ended in it."""
    return asked > 0 and 2 * failed > asked


def _tree() -> dict[str, Any]:
    """HEAD and the digest of every path that differs from it, tracked or not, but the records."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    listed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    files = {}
    for line in listed:
        relative = line[3:].strip()
        if relative.startswith("docs/evaluation/") or relative.startswith(".exulanica/"):
            continue
        path = ROOT / relative
        files[relative] = _sha256(path.read_bytes()) if path.is_file() else None
    return {"head": head, "files_sha256": dict(sorted(files.items()))}


# -- the slot ---------------------------------------------------------------------------------------


def _state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _environment(state: Mapping[str, Any], bound_usd: str, max_calls: int) -> None:
    """This process's configuration as the slot's API has it, with its own bound and call ceiling.
    The model key is set apart, by :func:`_key`, and never here."""
    runtime = str(state["database"]["runtime_url"])
    os.environ["EXULANICA_DATABASE_URL"] = runtime
    os.environ["EXULANICA_READONLY_DATABASE_URL"] = runtime.replace(
        "exulanica_app@", "exulanica_ro@", 1
    )
    os.environ["EXULANICA_DATA_DIR"] = str(state["data_dir"])
    os.environ["EXULANICA_SOCIETY_CONTROL_WORKSPACES"] = json.dumps([state["workspace_id"]])
    os.environ[BUDGET_VARIABLE] = bound_usd
    os.environ[CALLS_VARIABLE] = str(max_calls)
    # The application's services need a token directory; this process serves no request, so it
    # holds one random token of its own, granted to read the world alone.
    os.environ["EXULANICA_API_TOKENS"] = json.dumps(
        {
            secrets.token_urlsafe(48): {
                "workspace_id": state["workspace_id"],
                "actor": state["actor"],
                "permissions": ["world.read"],
            }
        }
    )


def _key(dotenv: Path) -> None:
    """The model key, read from the operator's ``.env`` into this process alone, never printed."""
    from exulanica.models.credentials import api_key_from_env

    os.environ["EXULANICA_EGRESS_ALLOWLIST"] = json.dumps(["https://api.tokenfactory.nebius.com"])
    os.environ[KEY_VARIABLE] = api_key_from_env(KEY_VARIABLE, dotenv=dotenv)


def _services(scripted_plan: Path | None) -> Any:
    """The application's services in this process: with ``scripted_plan``, its model client
    answers from the acceptance's scripted transport under this process's bound, and nothing that
    could reach a provider may be set."""
    from exulanica.api.services import build_services

    if scripted_plan is None:
        return build_services()
    spec = importlib.util.spec_from_file_location("exulanica_scripted_model", SCRIPTED_MODEL)
    assert spec is not None and spec.loader is not None
    scripted = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scripted)
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from exulanica.models.transport import HttpResponse

    manifest = load_manifest()
    reachable = scripted.provider_settings(
        os.environ, manifest.credential_variables(manifest.roles)
    )
    if reachable:
        raise SystemExit(f"a rehearsal could reach a provider: {', '.join(reachable)}")
    plan, _digest = scripted.load_plan(scripted_plan)
    client = ModelClient(
        api_key={
            provider.provider_id: "scripted-not-a-key" for provider in manifest.providers.values()
        },
        transport=scripted.ScriptedTransport(plan, None, HttpResponse),
        budget=BudgetGuard(
            ceiling_usd=Decimal(os.environ[BUDGET_VARIABLE]),
            max_calls=int(os.environ[CALLS_VARIABLE]),
        ),
    )
    return build_services(model_client=client)


def _owner(state: Mapping[str, Any]) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(state["database"]["owner_url_for_evidence_reads"], row_factory=dict_row)


def _api(state: Mapping[str, Any]) -> Callable[..., tuple[int, Any]]:
    """GET from the slot's API as the run's synthetic owner: the status and the parsed body."""
    token = Path(state["token_file"]).read_text(encoding="utf-8").strip()

    def get(path: str, query: Sequence[tuple[str, str]] = ()) -> tuple[int, Any]:
        suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
        request = urllib.request.Request(
            f"http://127.0.0.1:{state['ports']['api']}{path}{suffix}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                return error.code, json.loads(body)
            except ValueError:
                return error.code, {"text": body.decode("utf-8", "replace")[:500]}

    return get


def _ok(answer: tuple[int, Any], what: str) -> Any:
    status, body = answer
    if status != 200:
        raise SystemExit(f"{what} answered {status}: {json.dumps(body)[:500]}")
    return body


def _reader_is_scripted(state: Mapping[str, Any]) -> dict[str, Any]:
    """The slot API's own statement that it answers models from the scripted transport, which
    refuses to start where a provider could be reached: the reads below can bill nothing."""
    import urllib.request as request

    with request.urlopen(
        f"http://127.0.0.1:{state['ports']['api']}/readyz", timeout=60
    ) as response:
        label = json.loads(response.read()).get("acceptance_model")
    if not label or label.get("mode") != "scripted":
        raise SystemExit("the slot's API is not the scripted one: its reads could reach a provider")
    return dict(label)


# -- what the town and the database hold -------------------------------------------------------------


def _society(state: Mapping[str, Any], version: uuid.UUID, world_id: str) -> dict[str, Any]:
    """The town's society: its id and engine as the database holds them, and its people as the
    plan route lists them, in its order (by name, then identity)."""
    with _owner(state) as connection:
        society = connection.execute(
            "select society_id, engine_version from world_society where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (state["workspace_id"], world_id, version),
        ).fetchone()
    if society is None:
        raise SystemExit("the version holds no society")
    listed = _ok(
        _api(state)(
            f"/world/versions/{version}/society/comparisons/plan",
            [("world_id", world_id), ("window", WINDOW)],
        ),
        "the plan",
    )
    people = [{"id": person["id"], "name": person["name"]} for person in listed["people"]]
    return {
        "society_id": str(society["society_id"]),
        "engine": str(society["engine_version"]),
        "people": people,
    }


def _definition(state: Mapping[str, Any], world_id: str, comparison_id: str) -> dict[str, Any]:
    with _owner(state) as connection:
        row = connection.execute(
            "select input_seq, input_sha256, document from society_comparison "
            "where world_id=%s and comparison_id=%s",
            (world_id, comparison_id),
        ).fetchone()
    if row is None:
        raise SystemExit(f"no comparison {comparison_id} in {world_id}")
    return dict(row)


def _frozen_input(state: Mapping[str, Any], world_id: str, comparison_id: str) -> dict[str, Any]:
    """The society input a comparison froze, by sequence and digest, as its definition holds it."""
    row = _definition(state, world_id, comparison_id)
    return {"input_seq": row["input_seq"], "document_sha256": row["input_sha256"]}


def _asking(state: Mapping[str, Any], world_id: str, comparison_id: str) -> list[dict[str, Any]]:
    """What each run asked, from its receipts: asks, the minutes and people asked, what the asks
    cost, their answer times and every reason a turn ended for, integers and Decimal strings."""
    with _owner(state) as connection:
        runs = connection.execute(
            "select run_id, arm, seed_digest from society_comparison_run "
            "where world_id=%s and comparison_id=%s order by seed_digest, arm",
            (world_id, comparison_id),
        ).fetchall()
        rows = connection.execute(
            "select run_id, subject_id, base_tick, receipt from society_comparison_decision "
            "where world_id=%s and comparison_id=%s",
            (world_id, comparison_id),
        ).fetchall()
    by_run: dict[Any, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], []).append(row)
    found = []
    for run in runs:
        held = by_run.get(run["run_id"], [])
        asked = [row for row in held if row["receipt"].get("provider") is not None]
        costs = [Decimal(str(row["receipt"]["provider"]["cost_usd"])) for row in asked]
        latencies = [int(row["receipt"]["provider"]["latency_ms"]) for row in asked]
        models = Counter(str(row["receipt"]["provider"].get("model_id")) for row in asked)
        subjects = {str(row["subject_id"]) for row in asked}
        found.append(
            {
                "run_id": str(run["run_id"]),
                "arm": run["arm"],
                "seed_digest": run["seed_digest"],
                "receipts": len(held),
                "asks": len(asked),
                "asked_minutes": len({row["base_tick"] for row in asked}),
                "asked_people": len(subjects),
                "models": dict(sorted(models.items())),
                "cost_usd": str(sum(costs, Decimal(0))),
                "cost_unknown": sum(
                    1 for row in asked if not row["receipt"]["provider"].get("cost_known", True)
                ),
                "latency_ms_p50": nearest_rank(latencies, 500),
                "latency_ms_p95": nearest_rank(latencies, 950),
                "latency_ms_most": max(latencies) if latencies else None,
                "reasons": dict(
                    sorted(Counter(str(r["receipt"].get("reason")) for r in held).items())
                ),
            }
        )
    return found


def _first_hour_failures(state: Mapping[str, Any], world_id: str, comparison_id: str) -> list[str]:
    """The model runs whose first sealed hour holds more provider failures than answers."""
    with _owner(state) as connection:
        rows = connection.execute(
            "select h.run_id, count(d.*) filter (where d.receipt->'provider' is not null "
            "and d.receipt->'provider' <> 'null'::jsonb) as asked, "
            "count(d.*) filter (where d.receipt->>'reason' = any(%s)) as failed "
            "from society_comparison_hour h join society_comparison_decision d "
            "on d.workspace_id = h.workspace_id and d.run_id = h.run_id "
            "and d.decision_seq <= h.decision_seq_end "
            "where h.world_id=%s and h.comparison_id=%s and h.hour = 0 group by h.run_id",
            (sorted(PROVIDER_FAILURES), world_id, comparison_id),
        ).fetchall()
    return [str(row["run_id"]) for row in rows if provider_failed(row["asked"], row["failed"])]


def _database_facts(state: Mapping[str, Any], world_id: str, comparison_id: str) -> dict[str, Any]:
    """What the database recorded of a comparison's playing: when it was defined, when its first
    and last outcome were recorded, its runs by status and failure code, and its sealed hours."""
    with _owner(state) as connection:
        defined = connection.execute(
            "select created_at from society_comparison where world_id=%s and comparison_id=%s",
            (world_id, comparison_id),
        ).fetchone()["created_at"]
        span = connection.execute(
            "select min(recorded_at) as first, max(recorded_at) as last "
            "from society_comparison_outcome where world_id=%s and comparison_id=%s",
            (world_id, comparison_id),
        ).fetchone()
        statuses = connection.execute(
            "select r.arm, coalesce(o.status, 'open') as status, o.document->>'code' as code, "
            "count(*) as runs from society_comparison_run r left join society_comparison_outcome o "
            "using (workspace_id, world_id, comparison_id, run_id) "
            "where r.world_id=%s and r.comparison_id=%s group by 1, 2, 3 order by 1, 2, 3",
            (world_id, comparison_id),
        ).fetchall()
        hours = connection.execute(
            "select count(*) as n, min(recorded_at) as first, max(recorded_at) as last "
            "from society_comparison_hour where world_id=%s and comparison_id=%s",
            (world_id, comparison_id),
        ).fetchone()

    def utc(value: Any) -> str | None:
        return None if value is None else value.astimezone(dt.UTC).isoformat()

    return {
        "defined_utc": utc(defined),
        "first_outcome_utc": utc(span["first"]),
        "last_outcome_utc": utc(span["last"]),
        "runs": [dict(row) for row in statuses],
        "hours_sealed": hours["n"],
        "first_hour_sealed_utc": utc(hours["first"]),
        "last_hour_sealed_utc": utc(hours["last"]),
    }


def _served(state: Mapping[str, Any], version: str, world_id: str, comparison_id: str) -> Any:
    """A comparison's result as the application's route serves it."""
    return _ok(
        _api(state)(
            f"/world/versions/{version}/society/comparisons/{comparison_id}",
            [("world_id", world_id)],
        ),
        "the comparison's read",
    )


def _replayed(
    state: Mapping[str, Any], version: str, world_id: str, comparison_id: str
) -> dict[str, Any]:
    """Every hour of every run read back through the run route, each a replay from the state the
    hour before it sealed held to the hour's record, and every run's day through the day route.
    A run with an hour unread or a day not whole is listed with what its read answered."""
    api = _api(state)
    label = _reader_is_scripted(state)
    route = f"/world/versions/{version}/society/comparisons/{comparison_id}/runs"
    with _owner(state) as connection:
        runs = connection.execute(
            "select r.run_id, r.arm, r.seed_digest, coalesce(o.status, 'open') as status, "
            "(select count(*) from society_comparison_hour h where h.workspace_id = r.workspace_id "
            "and h.run_id = r.run_id) as sealed from society_comparison_run r "
            "left join society_comparison_outcome o "
            "using (workspace_id, world_id, comparison_id, run_id) "
            "where r.world_id=%s and r.comparison_id=%s order by r.seed_digest, r.arm",
            (world_id, comparison_id),
        ).fetchall()
    read = []
    for run in runs:
        verified, unverified, slowest = 0, [], 0
        for hour in range(int(run["sealed"])):
            began = time.monotonic_ns()
            status, drawn = api(
                f"{route}/{run['run_id']}", [("world_id", world_id), ("hour", str(hour))]
            )
            slowest = max(slowest, (time.monotonic_ns() - began) // 1_000_000)
            window = (drawn or {}).get("window") or {}
            if (
                status == 200
                and drawn.get("replay_verified") is True
                and window.get("first_tick") == hour * 60
            ):
                verified += 1
            else:
                unverified.append(
                    {"hour": hour, "status": status, "code": (drawn or {}).get("code")}
                )
        status, day = api(f"{route}/{run['run_id']}/day", [("world_id", world_id)])
        minutes = sorted(
            {len(m.get("doing") or "") for m in ((day or {}).get("minutes") or {}).values()}
        )
        read.append(
            {
                "run_id": str(run["run_id"]),
                "arm": run["arm"],
                "seed_digest": run["seed_digest"],
                "status": run["status"],
                "hours_sealed": int(run["sealed"]),
                "hours_verified": verified,
                "hours_unverified": unverified,
                "hour_read_ms_most": slowest,
                "day_status": status,
                "day_hours_sealed": (day or {}).get("hours_sealed"),
                "day_minutes_per_person": minutes,
            }
        )
    whole = [
        run
        for run in read
        if run["status"] == "completed"
        and run["hours_verified"] == HOURS
        and run["day_status"] == 200
        and run["day_minutes_per_person"] == [DAY_TICKS]
    ]
    return {
        "reader": label,
        "runs": read,
        "completed_runs": sum(1 for run in read if run["status"] == "completed"),
        "completed_runs_replayed_whole": len(whole),
        "hours_verified": sum(run["hours_verified"] for run in read),
    }


def _spend(asking: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The comparison's spend by model, from its runs' receipts."""
    totals: dict[str, dict[str, Any]] = {}
    for run in asking:
        for model, asks in run["models"].items():
            held = totals.setdefault(model, {"asks": 0, "cost_usd": Decimal(0)})
            held["asks"] += asks
        if len(run["models"]) == 1:
            (model,) = run["models"]
            totals[model]["cost_usd"] += Decimal(run["cost_usd"])
        elif run["models"]:
            raise SystemExit(f"run {run['run_id']} asked more than one model")
    return {
        "by_model": {
            model: {"asks": value["asks"], "cost_usd": str(value["cost_usd"])}
            for model, value in sorted(totals.items())
        },
        "total_usd": str(sum((Decimal(run["cost_usd"]) for run in asking), Decimal(0))),
    }


def _plan(
    state: Mapping[str, Any],
    version: str,
    world_id: str,
    people: Sequence[str],
    models: Sequence[tuple[str, str]],
    seeds: int,
) -> dict[str, Any]:
    """The plan route's figures for the selection over a day."""
    query = [
        ("world_id", world_id),
        ("role", ROLE),
        ("window", WINDOW),
        ("group", "named"),
        ("control", "true"),
        ("seeds", str(seeds)),
        *(("model", f"{provider}/{model_id}") for provider, model_id in models),
        *(("person", person) for person in people),
    ]
    answer = _ok(
        _api(state)(f"/world/versions/{version}/society/comparisons/plan", query), "the plan"
    )
    if answer.get("plan_refusal") is not None or answer.get("plan") is None:
        raise SystemExit(f"the plan refuses the selection: {answer.get('plan_refusal')}")
    return dict(answer["plan"])


# -- playing ---------------------------------------------------------------------------------------


@dataclasses.dataclass
class Stop:
    """Why a playing step stopped, once it did."""

    reason: str | None = None


def _runner(services: Any, state: Mapping[str, Any], world_id: str, version: uuid.UUID) -> Any:
    """The comparison runner over the slot's workspace, its catalogs a day's."""
    from exulanica.api.society_comparison_start import StartRefused, window_catalogs

    runner = services.comparison_runner(
        uuid.UUID(state["workspace_id"]), world_id, uuid.UUID(state["actor"])
    )
    if runner is None:
        raise SystemExit("this environment configures no society runtime")
    with services.database.session(uuid.UUID(state["workspace_id"])) as connection:
        society = runner._repository(connection).society._row(version)
    if society is None:
        raise SystemExit("the version holds no society")
    try:
        catalogs = window_catalogs(
            services.comparison_catalogs, WINDOW, str(society["engine_version"])
        )
    except StartRefused as exc:
        raise SystemExit(str(exc)) from exc
    return dataclasses.replace(runner, catalogs=catalogs)


def _host(
    services: Any,
    runner: Any,
    state: Mapping[str, Any],
    world_id: str,
    comparison_id: uuid.UUID,
    *,
    navigation_profile: str,
    stop_file: Path | None,
    deadline_ns: int | None,
    stop: Stop,
) -> Any:
    """A host for the local process: it admits a seed as the application's host does, and stops
    on the stop file, the step's hours or a first hour of provider failures."""
    from exulanica.api.society_comparison_runner import RunHost
    from exulanica.api.society_comparison_start import comparison_cost
    from exulanica.world.society_comparison_result import definition_role
    from exulanica.world.society_comparison_verdict import protocol_value

    budget = services.model_client.budget
    workspace = uuid.UUID(state["workspace_id"])
    with services.database.session(workspace) as connection:
        definition = runner._repository(connection)._definition(comparison_id)["document"]
    role = definition_role(definition)

    def admit(runs: Sequence[uuid.UUID]) -> bool:
        with services.database.session(workspace) as connection:
            repository = runner._repository(connection)
            rows = [repository._run(run_id) for run_id in runs]
        seed = comparison_cost(
            definition,
            int(definition["population"]),
            role,
            budget,
            runner.manifest,
            at_once=protocol_value(runner.catalogs, "runs_at_once"),
            navigation_profile=navigation_profile,
            runs_left=[(row["arm"], row["seed_digest"]) for row in rows],
            dearest_elsewhere=True,
        )
        # As the application's host admits a seed: the typical figure's least bound, or what the
        # runs can hold reserved at once where no ground has a figure for a model.
        needed = seed.held_usd if seed.suggested_usd is None else seed.suggested_usd
        money = budget.ceiling_usd - budget.spent_usd >= needed
        admitted = money and budget.max_calls - budget.billed_calls >= seed.calls
        print(
            json.dumps(
                {
                    "admit": admitted,
                    "needed_usd": str(needed),
                    "left_usd": str(budget.ceiling_usd - budget.spent_usd),
                    "calls_left": budget.available_calls,
                    "at": _now(),
                }
            ),
            flush=True,
        )
        return admitted

    checked = [time.monotonic_ns()]

    def stopping() -> bool:
        if stop.reason is not None:
            return True
        if stop_file is not None and stop_file.exists():
            stop.reason = f"stop file {stop_file}"
        elif deadline_ns is not None and time.monotonic_ns() > deadline_ns:
            stop.reason = "the step's hours are spent"
        elif time.monotonic_ns() - checked[0] >= FAILURE_CHECK_SECONDS * 1_000_000_000:
            checked[0] = time.monotonic_ns()
            failing = _first_hour_failures(state, world_id, str(comparison_id))
            if failing:
                stop.reason = f"provider failures outnumber answers in the first hour of {failing}"
        return stop.reason is not None

    return RunHost(minute=lambda: None, stopping=stopping, recorded=lambda _c: None, admit=admit)


def _play(
    runner: Any, comparison_id: uuid.UUID, run_ids: Sequence[uuid.UUID], host: Any, stop: Stop
) -> int:
    """Play the runs; the wall time in milliseconds. A stop leaves the open runs open."""
    from exulanica.api.society_comparison_runner import HostStopping

    started = time.monotonic_ns()
    try:
        runner.run_all(comparison_id, run_ids, host=host)
    except HostStopping:
        print(json.dumps({"stopped": stop.reason, "at": _now()}), flush=True)
    return (time.monotonic_ns() - started) // 1_000_000


def _people_and_ground(
    state: Mapping[str, Any], version: uuid.UUID, world_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    town = _society(state, version, world_id)
    entries = _ok(_api(state)("/world-entries"), "the world entries")
    entry = next((entry for entry in entries if entry["world_id"] == world_id), None)
    if entry is None or entry.get("generated_ground") is None:
        raise SystemExit(f"{world_id} is not a generated town here")
    return town, entry["generated_ground"]


def develop(arguments: argparse.Namespace) -> None:
    from exulanica.api.society_comparison_runner import ComparisonArm
    from exulanica.api.society_comparison_start import comparison_body

    state = _state(arguments.slot_state)
    world_id, version = arguments.world, arguments.version
    models = models_named(arguments.model)
    town, ground = _people_and_ground(state, version, world_id)
    people = [person["id"] for person in town["people"][:GROUP_SIZE]]
    plan = _plan(state, str(version), world_id, people, models, 1)
    ceiling = int((Decimal(plan["calls_most"]) * CALL_MARGIN).to_integral_value(ROUND_CEILING))
    _environment(state, str(Decimal(arguments.bound_usd)), ceiling)
    if arguments.scripted_plan is None:
        _key(arguments.dotenv)
    services = _services(arguments.scripted_plan)
    runner = _runner(services, state, world_id, version)
    entry = runner.catalogs.seeds.get(arguments.seed_key)
    if entry is None or entry["phase"] != "development" or "seed" not in entry:
        raise SystemExit(f"{arguments.seed_key} is no development seed the catalog commits")
    group = {"people": sorted(people), "source": {"kind": "named"}}
    body = comparison_body(
        runner,
        [ComparisonArm(provider, model_id) for provider, model_id in models],
        [str(entry["seed"])],
        control=True,
        group=group,
        others=runner.others_for(version, group["people"]),
    )
    comparison_id = uuid.uuid4()
    runner.define(version, comparison_id=comparison_id, body=body)
    run_ids = runner.reserve_all(comparison_id, [str(entry["seed"])])
    print(
        json.dumps({"comparison": str(comparison_id), "runs": len(run_ids), "at": _now()}),
        flush=True,
    )
    stop = Stop()
    host = _host(
        services,
        runner,
        state,
        world_id,
        comparison_id,
        navigation_profile=str(ground.get("navigation_profile") or "city-walking-surfaces/v1"),
        stop_file=arguments.stop_file,
        deadline_ns=time.monotonic_ns() + int(Decimal(arguments.hours_most) * 3600) * 1_000_000_000,
        stop=stop,
    )
    ran_ms = _play(runner, comparison_id, run_ids, host, stop)
    budget = services.model_client.budget
    asking = _asking(state, world_id, str(comparison_id))
    report = {
        "comparison_id": str(comparison_id),
        "rehearsal": arguments.scripted_plan is not None,
        "seed_key": arguments.seed_key,
        "town": {
            "world_id": world_id,
            "version_id": str(version),
            "society_id": town["society_id"],
            "engine": town["engine"],
            "population": len(town["people"]),
            "frozen_input": _frozen_input(state, world_id, str(comparison_id)),
        },
        "group": town["people"][:GROUP_SIZE],
        "models": [{"provider": p, "model_id": m} for p, m in models],
        "plan": plan,
        "bound_usd": str(budget.ceiling_usd),
        "process_call_ceiling": budget.max_calls,
        "stopped": stop.reason,
        "measured": {
            "run_ms": ran_ms,
            "spent_usd": str(budget.spent_usd),
            "billed_calls": budget.billed_calls,
        },
        "asking": asking,
        "spend": _spend(asking),
        "database": _database_facts(state, world_id, str(comparison_id)),
        "result": _served(state, str(version), world_id, str(comparison_id)),
        "replayed": _replayed(state, str(version), world_id, str(comparison_id)),
        "script_sha256": _sha256(Path(__file__).read_bytes()),
        "tree": _tree(),
        "written_utc": _now(),
    }
    _write_new(arguments.out, _sealed(report, DEVELOPMENT_KIND))
    print(
        json.dumps(
            {
                "written": str(arguments.out),
                "stopped": stop.reason,
                "spent_usd": str(budget.spent_usd),
            }
        )
    )


def preregister(arguments: argparse.Namespace) -> None:
    from exulanica.world.society_catalogs import DAY_COMPARISON_VERSIONS, load_comparison_catalogs
    from exulanica.world.society_comparison_result import scoring_binding
    from exulanica.world.society_comparison_verdict import protocol_values

    state = _state(arguments.slot_state)
    world_id, version = arguments.world, arguments.version
    models = models_named(arguments.model)
    town, ground = _people_and_ground(state, version, world_id)
    if town["engine"] != "exulanica-society/v5":
        raise SystemExit(f"the town's society runs {town['engine']}, not the living town's")
    group = town["people"][:GROUP_SIZE]
    ids = [person["id"] for person in group]
    catalogs = load_comparison_catalogs(versions=DAY_COMPARISON_VERSIONS)
    held_out = [
        {"key": key, "seed_digest": str(entry["seed_digest"])}
        for key, entry in catalogs.seeds.items()
        if entry["phase"] == "held_out"
    ]
    one = _plan(state, str(version), world_id, ids, models, 1)
    every = _plan(state, str(version), world_id, ids, models, len(held_out))
    ceiling = int((Decimal(every["calls_most"]) * CALL_MARGIN).to_integral_value(ROUND_CEILING))
    development = _definition(state, world_id, arguments.development)["document"]
    if development.get("phase") != "development" or sorted(
        development["group"]["people"]
    ) != sorted(ids):
        raise SystemExit("the development comparison is not this design on a development seed")
    asking = _asking(state, world_id, arguments.development)
    spend = _spend(asking)
    least = least_bound(one["suggested_usd"], spend["total_usd"], len(held_out))
    bound = Decimal(arguments.bound_usd)
    if bound < Decimal(least["least_usd"]):
        raise SystemExit(f"the bound {bound} is under the least judged bound {least}")
    facts = _database_facts(state, world_id, arguments.development)
    served = _served(state, str(version), world_id, arguments.development)
    from exulanica.models.manifest import load_manifest

    name = load_manifest().model_name
    record = {
        "question": __doc__.split("\n\n")[2],
        "written_before_any_held_out_call": True,
        "town": {
            "recipe": RECIPE,
            "world_id": world_id,
            "version_id": str(version),
            "ground": ground,
            "society_id": town["society_id"],
            "engine": town["engine"],
            "frozen_input": _frozen_input(state, world_id, arguments.development),
            "population": len(town["people"]),
        },
        "group": {
            "rule": f"the first {GROUP_SIZE} of the town's people in the plan route's order, by "
            "name then identity; everybody else follows their routine",
            "people": group,
        },
        "models": [{"provider": p, "model_id": m} for p, m in models],
        "arms": {
            "model_a": name(models[0][1]),
            "model_b": name(models[1][1]),
            "model_a_again": f"{name(models[0][1])}, the control",
            "routine": "one",
            "wait": "zero",
        },
        "claim": {
            "primary": ["model_a", "model_b"],
            "family": [["model_a", "model_b"], ["routine", "model_a"], ["routine", "model_b"]],
            "control": ["model_a", "model_a_again"],
        },
        "held_out_seeds": held_out,
        "catalogs": dict(catalogs.versions),
        "protocol": protocol_values(catalogs),
        "verdict_rule": (
            "Pooled over seeds, as the server's verdict (exulanica/world/society_comparison_claim.py "
            "and exulanica/world/society_comparison_verdict_v5.py under binding v5). For each "
            "registered pair, the per-seed differences of the fifth score over the seeds both arms "
            "scored, their mean and a percentile bootstrap interval (bootstrap_resamples, "
            "interval_per_mille); Holm's procedure over the family at family_alpha_per_mille. The "
            "control's bound is the larger magnitude of the two ends of the control pair's interval. "
            "The verdict is different, naming the higher arm, only where Holm rejects the primary "
            "difference and the magnitude of its mean exceeds the control's bound; otherwise "
            "no_measured_difference. Per-seed differences are reported beside it and never decide "
            "it. A comparison with any run missing or failed, including a seed the bound did not "
            "admit (comparison_bound_before_seed), reads incomplete and claims nothing; one with "
            "fewer than two seeds every judged arm scored reads not_judged (too_few_seeds_scored); "
            "a seed excluded by name (need_below_floor, variety_not_spared) carries no score."
        ),
        "run_window": {
            "simulated_minutes": protocol_values(catalogs)["window_ticks"],
            "starts_before_utc": (
                dt.datetime.now(dt.UTC).replace(microsecond=0)
                + dt.timedelta(hours=RUN_WINDOW_HOURS)
            ).isoformat(),
        },
        "plan": {"one_seed": one, "every_seed": every},
        "process_calls": {
            "calls_most": every["calls_most"],
            "process_call_ceiling": ceiling,
            "rule": f"the run's process may make at most this many calls ({CALLS_VARIABLE}), "
            "the plan's most calls for every run and a tenth more; a seed is admitted only while "
            "both what is left of the bound and what is left of the call ceiling hold what its "
            "runs can take",
        },
        "bound": {
            "bound_usd": str(bound),
            **least,
            "rule": "at least what the host needs left to admit one seed (the plan's suggested_usd "
            f"for one seed) and the development day's spend times the seeds times {SPEND_MARGIN}",
        },
        "stops": [
            "the bound: an ask past it is never sent; a seed the bound cannot hold is closed "
            "comparison_bound_before_seed and the comparison reads incomplete",
            "a run a host reason ended fails by its code and is never played again",
            "the stop file, or a first sealed hour of a model run with more provider failures "
            f"({', '.join(sorted(PROVIDER_FAILURES))}) than answers: the open runs stay open and "
            "the comparison is incomplete unless a run step with --comparison finishes them "
            "within the run window",
            "the registered window to start the run",
        ],
        "development": {
            "comparison_id": arguments.development,
            "rule": "the same design on one development seed, run before this registration to "
            "size the bound; reported, never judged",
            "verdict": served["verdict"],
            "seeds": served["seeds"],
            "asking": asking,
            "spend": spend,
            "database": facts,
        },
        "script_sha256": _sha256(Path(__file__).read_bytes()),
        "script_as_run": _paths(arguments.name)["script_as_run"],
        "scoring": scoring_binding(catalogs),
        "tree": _tree(),
        "registered_utc": _now(),
    }
    path = ROOT / _paths(arguments.name)["preregistration"]
    _write_new(path, _sealed(record, PREREGISTRATION_KIND))
    print(
        json.dumps(
            {
                "written": str(path.relative_to(ROOT)),
                "file_sha256": _sha256(path.read_bytes()),
                "bound_usd": str(bound),
                **least,
                "process_call_ceiling": ceiling,
            }
        )
    )


def run(arguments: argparse.Namespace) -> None:
    from exulanica.api.society_comparison_runner import ComparisonArm
    from exulanica.api.society_comparison_start import comparison_body

    paths = _paths(arguments.name)
    if (ROOT / paths["record"]).exists():
        raise SystemExit(f"{paths['record']} exists: the comparison is judged once")
    registered = json.loads((ROOT / paths["preregistration"]).read_text(encoding="utf-8"))
    pre = registered["record"]
    if _tree() != pre["tree"]:
        raise SystemExit("the tree is not the pre-registered one")
    if _sha256(Path(__file__).read_bytes()) != pre["script_sha256"]:
        raise SystemExit("this script is not the pre-registered one")
    if arguments.comparison is None and _now() >= pre["run_window"]["starts_before_utc"]:
        raise SystemExit("the registered window to start the run has passed")
    as_run = ROOT / paths["script_as_run"]
    as_run.parent.mkdir(parents=True, exist_ok=True)
    if not as_run.exists():
        as_run.write_bytes(Path(__file__).read_bytes())
    state = _state(arguments.slot_state)
    seeds = seeds_from(
        arguments.seeds.read_text(encoding="utf-8"),
        [entry["seed_digest"] for entry in pre["held_out_seeds"]],
    )
    world_id = pre["town"]["world_id"]
    version = uuid.UUID(pre["town"]["version_id"])
    bound = Decimal(pre["bound"]["bound_usd"])
    ceiling = int(pre["process_calls"]["process_call_ceiling"])
    if arguments.comparison is not None:
        # Going on: the bound is what the comparison's receipts left of it, less what a process
        # that stopped may have paid and never recorded.
        left = resumed_bound(
            bound,
            _spend(_asking(state, world_id, str(arguments.comparison)))["total_usd"],
            pre["plan"]["every_seed"]["minutes"],
        )
        if left <= 0:
            raise SystemExit(f"the bound holds nothing more: {left}")
        bound = left
    _environment(state, str(bound), ceiling)
    _key(arguments.dotenv)
    services = _services(None)
    budget = services.model_client.budget
    if budget.max_calls != ceiling or budget.ceiling_usd != bound:
        raise SystemExit("the process's budget is not the registered bound and call ceiling")
    runner = _runner(services, state, world_id, version)
    if dict(runner.catalogs.versions) != pre["catalogs"]:
        raise SystemExit("the runner's catalogs are not the registered ones")
    if arguments.comparison is None:
        people = [person["id"] for person in pre["group"]["people"]]
        group = {"people": sorted(people), "source": {"kind": "named"}}
        body = comparison_body(
            runner,
            [ComparisonArm(m["provider"], m["model_id"]) for m in pre["models"]],
            seeds,
            control=True,
            phase="held_out",
            preregistration={
                "record": paths["preregistration"],
                "record_sha256": registered["record_sha256"],
            },
            group=group,
            others=runner.others_for(version, group["people"]),
        )
        if body["claim"] != pre["claim"]:
            raise SystemExit("the definition's claim is not the registered one")
        comparison_id = uuid.uuid4()
        runner.define(version, comparison_id=comparison_id, body=body)
        if _frozen_input(state, world_id, str(comparison_id)) != pre["town"]["frozen_input"]:
            raise SystemExit("the comparison froze another input than the registered one")
        run_ids = runner.reserve_all(comparison_id, seeds)
    else:
        comparison_id = arguments.comparison
        definition = _definition(state, world_id, str(comparison_id))["document"]
        if (definition.get("preregistration") or {}).get("record_sha256") != registered[
            "record_sha256"
        ]:
            raise SystemExit("that comparison was not defined under this pre-registration")
        with _owner(state) as connection:
            run_ids = [
                row["run_id"]
                for row in connection.execute(
                    "select run_id from society_comparison_run where world_id=%s "
                    "and comparison_id=%s",
                    (world_id, str(comparison_id)),
                ).fetchall()
            ]
    print(
        json.dumps({"comparison": str(comparison_id), "runs": len(run_ids), "at": _now()}),
        flush=True,
    )
    stop = Stop()
    host = _host(
        services,
        runner,
        state,
        world_id,
        comparison_id,
        navigation_profile=str(
            pre["town"]["ground"].get("navigation_profile") or "city-walking-surfaces/v1"
        ),
        stop_file=arguments.stop_file,
        deadline_ns=None,
        stop=stop,
    )
    ran_ms = _play(runner, comparison_id, run_ids, host, stop)
    print(
        json.dumps(
            {
                "comparison": str(comparison_id),
                "stopped": stop.reason,
                "run_ms": ran_ms,
                "spent_usd": str(budget.spent_usd),
                "billed_calls": budget.billed_calls,
                "at": _now(),
            }
        ),
        flush=True,
    )


def record(arguments: argparse.Namespace) -> None:
    paths = _paths(arguments.name)
    registered = json.loads((ROOT / paths["preregistration"]).read_text(encoding="utf-8"))
    pre = registered["record"]
    state = _state(arguments.slot_state)
    town = pre["town"]
    comparison_id = str(arguments.comparison)
    definition = _definition(state, town["world_id"], comparison_id)["document"]
    if (definition.get("preregistration") or {}).get("record_sha256") != registered[
        "record_sha256"
    ]:
        raise SystemExit("that comparison was not defined under this pre-registration")
    copy = ROOT / paths["record_script_as_run"]
    copy.parent.mkdir(parents=True, exist_ok=True)
    if not copy.exists():
        copy.write_bytes(Path(__file__).read_bytes())
    served = _served(state, town["version_id"], town["world_id"], comparison_id)
    asking = _asking(state, town["world_id"], comparison_id)
    notes = (
        {} if arguments.notes is None else json.loads(arguments.notes.read_text(encoding="utf-8"))
    )
    value = {
        "comparison_id": comparison_id,
        "preregistration": paths["preregistration"],
        "preregistration_record_sha256": registered["record_sha256"],
        "verdict": served["verdict"],
        "result": served,
        "means_over": "each arm's mean_score is over its completed runs only; a failed run "
        "carries no score",
        "asking": asking,
        "spend": _spend(asking),
        "bound_usd": pre["bound"]["bound_usd"],
        "database": _database_facts(state, town["world_id"], comparison_id),
        "replayed": _replayed(state, town["version_id"], town["world_id"], comparison_id),
        "notes": notes,
        "tree": _tree(),
        "run_script_as_run": pre["script_as_run"],
        "run_script_sha256": pre["script_sha256"],
        "record_script_as_run": paths["record_script_as_run"],
        "record_script_sha256": _sha256(Path(__file__).read_bytes()),
        "written_utc": _now(),
    }
    path = ROOT / paths["record"]
    _write_new(path, _sealed(value, RECORD_KIND))
    print(
        json.dumps(
            {
                "written": paths["record"],
                "file_sha256": _sha256(path.read_bytes()),
                "verdict": served["verdict"],
            }
        )
    )


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    steps = parser.add_subparsers(dest="step", required=True)
    develop_step = steps.add_parser("develop")
    develop_step.add_argument("--out", type=Path, required=True)
    develop_step.add_argument("--world", required=True)
    develop_step.add_argument("--version", type=uuid.UUID, required=True)
    develop_step.add_argument("--model", action="append", required=True)
    develop_step.add_argument("--bound-usd", required=True)
    develop_step.add_argument("--seed-key", default="development_1")
    develop_step.add_argument("--hours-most", default="8")
    develop_step.add_argument("--stop-file", type=Path)
    spend = develop_step.add_mutually_exclusive_group(required=True)
    spend.add_argument("--dotenv", type=Path, help="the operator's .env, read for the key alone")
    spend.add_argument("--scripted-plan", type=Path, help="rehearse with the scripted transport")
    preregister_step = steps.add_parser("preregister")
    preregister_step.add_argument("--name", required=True)
    preregister_step.add_argument("--world", required=True)
    preregister_step.add_argument("--version", type=uuid.UUID, required=True)
    preregister_step.add_argument("--model", action="append", required=True)
    preregister_step.add_argument("--development", required=True)
    preregister_step.add_argument("--bound-usd", required=True)
    run_step = steps.add_parser("run")
    run_step.add_argument("--name", required=True)
    run_step.add_argument("--seeds", type=Path, required=True)
    run_step.add_argument("--dotenv", type=Path, required=True)
    run_step.add_argument("--comparison", type=uuid.UUID)
    run_step.add_argument("--stop-file", type=Path)
    record_step = steps.add_parser("record")
    record_step.add_argument("--name", required=True)
    record_step.add_argument("--comparison", type=uuid.UUID, required=True)
    record_step.add_argument("--notes", type=Path)
    for step in (develop_step, preregister_step, run_step, record_step):
        step.add_argument("--slot-state", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parser().parse_args(argv)
    {"develop": develop, "preregister": preregister, "run": run, "record": record}[arguments.step](
        arguments
    )


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
