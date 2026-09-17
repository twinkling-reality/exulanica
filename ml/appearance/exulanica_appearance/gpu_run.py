"""``exulanica.appearance-gpu-run/v1``: one rented machine, from deploy to deletion, and its cost.

A run record names the provider, the instance type and GPU, the listed rate and where it was read,
when the machine started and when it was deleted, the billed seconds and the cost at the listed
rate, the estimate the run was approved against and its stop at 150 per cent of that estimate, the
purpose, and the generation records it produced. The reader holds the arithmetic: billed seconds are
the interval, cost is rate times seconds rounded up to a micro-dollar, and a run that passed its stop
must say why.

The listed rate times the billed seconds is an estimate of the bill. The provider's billing page,
read by the operator, is the only authoritative total, and the record says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    is_text,
    parse_canonical,
)

__all__ = [
    "AUTHORITATIVE",
    "GPU_RUN_PROFILE",
    "build_gpu_run",
    "ceiling_seconds",
    "cost_microdollars",
    "document_section",
    "ledger_line",
    "read_gpu_run",
]

GPU_RUN_PROFILE: Final = "exulanica.appearance-gpu-run/v1"
AUTHORITATIVE: Final = "the provider's billing page, read by the operator"
_INSTANT: Final = "%Y-%m-%dT%H:%M:%SZ"
_KEYS: Final = (
    "authoritative_total",
    "billed_seconds",
    "hard_deadline_at",
    "instance_name",
    "cost_microdollars",
    "deleted_at",
    "estimate_seconds",
    "generations",
    "gpu",
    "gpu_count",
    "instance_type",
    "over_estimate_reason",
    "profile",
    "provider",
    "purpose",
    "rate_cents_per_hour",
    "rate_source",
    "started_at",
    "stop_at_seconds",
)


def cost_microdollars(rate_cents_per_hour: int, seconds: int) -> int:
    """Rate times seconds, in millionths of a dollar, rounded up."""
    numerator = rate_cents_per_hour * 10_000 * seconds
    return -(-numerator // 3600)


def ceiling_seconds(ceiling_cents: int, rate_cents_per_hour: int) -> int:
    """The most seconds a ceiling buys at a rate, rounded down, so a run cannot pass it by a second."""
    if ceiling_cents < 0 or rate_cents_per_hour < 1:
        raise Refused("a ceiling is not negative and a rate is positive")
    return ceiling_cents * 3600 // rate_cents_per_hour


def build_gpu_run(document: dict[str, Any]) -> bytes:
    full = dict(document)
    started = datetime.strptime(full["started_at"], _INSTANT).replace(tzinfo=UTC)
    deleted = datetime.strptime(full["deleted_at"], _INSTANT).replace(tzinfo=UTC)
    full["billed_seconds"] = int((deleted - started).total_seconds())
    full["cost_microdollars"] = cost_microdollars(
        full["rate_cents_per_hour"], full["billed_seconds"]
    )
    full["stop_at_seconds"] = full["estimate_seconds"] * 3 // 2
    full["generations"] = sorted(full["generations"])
    full["authoritative_total"] = AUTHORITATIVE
    raw = canonical_bytes(full)
    read_gpu_run(raw)
    return raw


def read_gpu_run(raw: bytes) -> dict[str, Any]:
    where = "the GPU run record"
    document = exact_keys(parse_canonical(raw, where), _KEYS, where)
    if document["profile"] != GPU_RUN_PROFILE:
        raise Refused(f"{where}: profile is {GPU_RUN_PROFILE}")
    for key in ("provider", "instance_type", "instance_name", "gpu", "rate_source", "purpose"):
        if not is_text(document[key]):
            raise Refused(f"{where}: {key} is printable ASCII")
    if not is_count(document["gpu_count"], 1) or not is_count(document["rate_cents_per_hour"], 1):
        raise Refused(f"{where}: gpu_count and rate_cents_per_hour are positive integers")
    try:
        started = datetime.strptime(document["started_at"], _INSTANT).replace(tzinfo=UTC)
        deleted = datetime.strptime(document["deleted_at"], _INSTANT).replace(tzinfo=UTC)
    except (TypeError, ValueError) as error:
        raise Refused(
            f"{where}: started_at and deleted_at are UTC instants, YYYY-MM-DDTHH:MM:SSZ"
        ) from error
    try:
        deadline = datetime.strptime(document["hard_deadline_at"], _INSTANT).replace(tzinfo=UTC)
    except (TypeError, ValueError) as error:
        raise Refused(
            f"{where}: hard_deadline_at is a UTC instant, YYYY-MM-DDTHH:MM:SSZ"
        ) from error
    if deadline <= started:
        raise Refused(
            f"{where}: hard_deadline_at is after started_at; it is the time the machine is deleted whatever happens"
        )
    seconds = int((deleted - started).total_seconds())
    if seconds <= 0 or document["billed_seconds"] != seconds:
        raise Refused(
            f"{where}: billed_seconds is the positive interval from started_at to deleted_at"
        )
    if document["cost_microdollars"] != cost_microdollars(document["rate_cents_per_hour"], seconds):
        raise Refused(
            f"{where}: cost_microdollars is the listed rate times the billed seconds, rounded up"
        )
    if (
        not is_count(document["estimate_seconds"], 1)
        or document["stop_at_seconds"] != document["estimate_seconds"] * 3 // 2
    ):
        raise Refused(f"{where}: stop_at_seconds is 150 per cent of a positive estimate")
    over = seconds > document["stop_at_seconds"]
    reason = document["over_estimate_reason"]
    if not isinstance(reason, str) or (over and not is_text(reason)) or (not over and reason != ""):
        raise Refused(
            f"{where}: over_estimate_reason says why a run passed its stop, and is empty otherwise"
        )
    generations = document["generations"]
    if (
        not isinstance(generations, list)
        or not all(is_sha256(g) for g in generations)
        or generations != sorted(set(generations))
    ):
        raise Refused(f"{where}: generations are sorted sha256 digests, each once")
    if document["authoritative_total"] != AUTHORITATIVE:
        raise Refused(f"{where}: authoritative_total names {AUTHORITATIVE}")
    return document


def ledger_line(raw: bytes) -> str:
    """One line for the committed ledger: what was rented, when it began and ended, and what it cost."""
    run = read_gpu_run(raw)
    # Cents by integer arithmetic, rounded half up: a float here prints 6.575 as 6.57.
    cents = (run["cost_microdollars"] + 5_000) // 10_000
    dollars = f"{cents // 100}.{cents % 100:02d}"
    return (
        f"{run['started_at']}  {run['deleted_at']}  deadline {run['hard_deadline_at']}  "
        f"{run['instance_name']} ({run['instance_type']}, {run['gpu_count']}x {run['gpu']}, {run['provider']})  "
        f"{run['billed_seconds']} s  ${dollars} at {run['rate_cents_per_hour']} cents/h  "
        f"{len(run['generations'])} generations  {run['purpose']}"
    )


def document_section(
    raw: bytes,
    *,
    balance_before_cents: int,
    balance_after_cents: int,
    consent: str,
    produced: Sequence[str],
    taught: Sequence[str],
) -> str:
    """The dated section this run adds to ``docs/reference-gpu-compute.md``, for a person to read.

    The operator asked that every instance this lane creates is written into the repository, not only
    into the ignored evidence directory: what was rented, at what rate read that day, when it began
    and ended, what it cost, what it produced by digest, what it taught including the false starts,
    that the operator accepted the provider's data-sharing consent, and the balance before and after.
    The machine-readable record stays beside it; this is the part a person reads later.
    """
    run = read_gpu_run(raw)
    if balance_before_cents < 0 or balance_after_cents < 0:
        raise Refused("a balance is not negative")
    if not produced or not taught:
        raise Refused(
            "a section says what the run produced and what it taught, even if it taught that it failed"
        )
    hours = run["billed_seconds"] / 3600
    cents = (run["cost_microdollars"] + 5_000) // 10_000
    lines = [
        f"## {run['started_at'][:10]} {run['purpose']}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Provider | {run['provider']} |",
        f"| Instance type | `{run['instance_type']}` |",
        f"| Instance name | `{run['instance_name']}` |",
        f"| GPU | {run['gpu_count']} x {run['gpu']} |",
        f"| Rate read that day | ${run['rate_cents_per_hour'] // 100}.{run['rate_cents_per_hour'] % 100:02d} per hour ({run['rate_source']}) |",
        f"| Created | {run['started_at']} |",
        f"| Hard deadline | {run['hard_deadline_at']} |",
        f"| Deleted | {run['deleted_at']} |",
        f"| Billed | {run['billed_seconds']} s ({hours:.2f} h) |",
        f"| Cost at the listed rate | ${cents // 100}.{cents % 100:02d} |",
        f"| Prepaid balance before | ${balance_before_cents // 100}.{balance_before_cents % 100:02d} |",
        f"| Prepaid balance after | ${balance_after_cents // 100}.{balance_after_cents % 100:02d} |",
        f"| Data-sharing consent | {consent} |",
        f"| Authoritative total | {run['authoritative_total']} |",
        "",
        "What it produced:",
        "",
    ]
    lines += [f"- {item}" for item in produced]
    lines += ["", "What it taught:", ""]
    lines += [f"- {item}" for item in taught]
    lines += [
        "",
        (
            "The machine-readable record of this run is `exulanica.appearance-gpu-run/v1` with "
            f"{len(run['generations'])} generation records; the cost above is the listed rate times "
            "the billed seconds, and the provider's billing page, read by the operator, is the only "
            "authoritative total."
        ),
        "",
    ]
    return "\n".join(lines)
