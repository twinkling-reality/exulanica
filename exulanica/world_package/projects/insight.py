"""What the beings did and how each model did, told from a project's evidence files alone.

The pull request text is regenerated from the committed files on every review, so it cannot drift
from them. Numbers come from `exulanica/world/decision_measures.py`, the one authority for the
served measures; a verdict's words come from the shared choice-account catalog the browser reads
too. What the files cannot support is named as unavailable, never shown as zero. Labels, lines and
situations appear only where the repository is private; a public one gets codes only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.selection.inhabitant_words import inhabitant_words_catalog
from exulanica.world.decision_measures import measures
from exulanica.world.society_sessions import closed_words
from exulanica.world_package.projects.checkpoint import ProjectError
from exulanica.world_package.projects.schema import ModelBinding, binding_sha256, scan_values
from exulanica.world_package.projects.summary import run_numbers
from exulanica.world_package.projects.words import (
    capital,
    listed,
    model_name,
    money,
    names,
    plural,
    possessive,
    quoted,
    seconds,
    without_words,
)

CATALOG: Final = (
    Path(__file__).resolve().parents[3] / "assets/catalogs/roles/choice-account-words.v2.json"
)
VERDICT_ORDER: Final = (
    "awaiting_answer",
    "refused",
    "no_answer",
    "stale",
    "not_applied",
    "pending",
    "applied",
)
#: The pull request text's budget, below the 65,536 characters GitHub is reported to accept for a
#: description; GitHub's pull request API page states no limit (read on 14 October 2026).
BUDGET: Final = 60_000
#: Decision lines kept per being per session before the rest are pointed at.
LINES_PER_BEING: Final = 6


def choice_words(path: Path = CATALOG) -> dict[str, Any]:
    """The shared catalog, refused unless it has every verdict in the account's order."""
    return _read_words(str(path))


_TABLES: Final = {
    "verdict": "verdicts",
    "continuation": "continuations",
    "reason_phrase": "reasons",
}


@cache
def _read_words(path: str) -> dict[str, Any]:
    """The catalog's entries as tables by kind, refusing a shape its readers would misread."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("catalog_id") != "choice-account-words":
        raise ProjectError("not the choice account words catalog")
    tables: dict[str, dict[str, str]] = {table: {} for table in _TABLES.values()}
    for entry in document["entries"]:
        kind, code, words = entry.get("kind"), entry.get("code"), entry.get("words")
        if kind not in _TABLES or entry.get("key") != f"{kind}.{code}":
            raise ProjectError("the choice account words catalog has an entry of unknown shape")
        if not isinstance(words, str) or not words or code in tables[_TABLES[kind]]:
            raise ProjectError("the choice account words catalog repeats or empties an entry")
        tables[_TABLES[kind]][code] = words
    if tuple(document["verdict_order"]) != VERDICT_ORDER or set(tables["verdicts"]) != set(
        VERDICT_ORDER
    ):
        raise ProjectError("the choice account words catalog lacks a verdict or its order")
    return {"verdict_order": list(VERDICT_ORDER), **tables}


def _sentence(text: str) -> str:
    trimmed = text.strip()
    capital = trimmed[:1].upper() + trimmed[1:]
    return capital if capital.endswith((".", "!", "?")) else f"{capital}."


def _why(code: str | None, words: Mapping[str, Any]) -> str:
    if code is None:
        return words["reasons"]["reason_none"]
    known = inhabitant_words_catalog().tables["decision_reason"].get(code)
    return known or words["reasons"]["reason_unknown"].format(code=code)


def verdict(receipt: Mapping[str, Any] | None, words: Mapping[str, Any]) -> str:
    """The account's one verdict for a receipt, the first of its order that holds."""
    said = words["verdicts"]
    if receipt is None:
        return _sentence(said["awaiting_answer"])
    minute = receipt["consumed_tick"]
    if receipt["status"] == "rejected":
        return _sentence(said["refused"].format(why=_why(receipt["reason"], words)))
    if receipt["status"] != "accepted":
        after = words["continuations"]
        tail = (
            after["no_answer_untaken"]
            if minute is None
            else after["no_answer_routine"].format(minute=minute)
        )
        return f"{_sentence(said['no_answer'].format(why=_why(receipt['reason'], words)))} {tail}"
    if receipt["disposition"] == "stale":
        return _sentence(said["stale"].format(minute=minute))
    if receipt["disposition"] in ("rejected", "superseded"):
        why = _why(receipt["disposition_reason"], words)
        return _sentence(said["not_applied"].format(minute=minute, why=why))
    if receipt["disposition"] is None:
        return _sentence(said["pending"])
    return _sentence(said["applied"].format(minute=minute))


def _decision_line(decision: Mapping[str, Any], readable: bool, words: Mapping[str, Any]) -> str:
    """ "Minute 6: chose “wait here a minute”, from 4 choices. Applied in minute 7." A public
    repository gets no chosen words: "chose one of 4 choices"."""
    count = len(decision["options"])
    text = decision.get("readable") or {}
    offered = "the one choice" if count == 1 else f"the {count} choices"
    if decision["chosen_option_id"] is None:
        told = f"chose none of {offered}"
    elif readable and text.get("choice") is not None:
        told = f"chose {quoted(text['choice'])}, from {plural(count, 'choice')}"
    else:
        told = f"chose one of {count} choices" if count > 1 else "chose the one choice"
    receipt = decision.get("receipt")
    after = (
        "What the world did with it was not recorded."
        if receipt is None
        else verdict(receipt, words)
    )
    return f"Minute {decision['tick']}: {told}. {after}"


def _row(model: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    """One decision as the served measures read it."""
    receipt = decision.get("receipt") or {}
    text = decision.get("readable") or {}
    return {
        "subject_id": decision["thing_id"],
        "provider": model["provider"],
        "model_id": model["model_id"],
        "has_receipt": bool(receipt),
        "has_labels": bool(text),
        "status": receipt.get("status"),
        "disposition": receipt.get("disposition"),
        "reason": receipt.get("reason"),
        "chose": text.get("choice"),
        "line": text.get("line"),
        "asked_model": True,
        "latency_ms": decision["elapsed_ms"],
        "cost_usd": receipt.get("cost_usd") or "0",
        "cost_known": receipt.get("cost_known", False),
        "has_cost": receipt.get("cost_usd") is not None,
    }


def _bindings(session: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {binding_sha256(ModelBinding.model_validate(m)): m for m in session["models"]}


def _rows(sessions: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for _, session in sorted(sessions.items()):
        models = _bindings(session)
        rows += [_row(models[d["binding_sha256"]], d) for d in session["decisions"]]
    return rows


def _rate(rate: Mapping[str, Any]) -> str:
    """ "5 of 5"; "1 of 1, not enough yet" below the measure's minimum."""
    if not rate["denominator"]:
        return "not enough yet"
    said = f"{rate['numerator']} of {rate['denominator']}"
    return said if rate["value"] is not None else f"{said}, not enough yet"


def _being_line(name: str, model_id: str, rows: Sequence[Mapping[str, Any]]) -> str:
    head = f"- {capital(name)}, with {model_name(model_id)}: {plural(len(rows), 'decision')}"
    missing = sum(1 for row in rows if not row["has_receipt"])
    if missing:
        which = "it" if len(rows) == 1 else "them" if missing == len(rows) else "some of them"
        return f"{head}; what the world did with {which} was not recorded"
    return f"{head}, {measures(rows)['counts']['applied']} done"


#: The model table's one line under it, saying what its least plain column means.
REPEATED_CHOICES: Final = (
    "Repeated choices: how often a character chose the same as its last decision."
)


def _model_table(
    rows: Sequence[Mapping[str, Any]], called: Mapping[str, str], readable: bool
) -> list[str]:
    """How each model did over every run of the pull request, never one combined score."""
    lines = [
        "## How each model did",
        "",
        "| Model | Characters | Decisions | Done | Repeated choices | Time to answer | Spent |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["model_id"], row["provider"]), []).append(row)
    for (model_id, _), own in sorted(grouped.items()):
        who = listed(sorted({capital(called.get(row["subject_id"], "a character")) for row in own}))
        head = f"| {model_name(model_id)} | {who} | {len(own)} |"
        if not all(row["has_receipt"] for row in own):
            lines.append(f"{head} not recorded | not recorded | not recorded | not recorded |")
            continue
        counted = measures(own)
        if not readable:
            repeated = "not shown on a public repository"
        elif all(row["has_labels"] for row in own):
            repeated = _rate(counted["rates"]["repeated_choice"])
        else:
            repeated = "not recorded"
        latency = counted["latency_ms"]
        timing = (
            f"usually {seconds(latency['p50'])}, 19 in 20 within {seconds(latency['p95'])}"
            if latency["p50"] is not None
            else "not enough yet"
        )
        cost = counted["cost"]
        if not all(row["has_cost"] for row in own):
            spent = "not recorded"
        elif cost["basis"] == "computed":
            spent = money(cost["usd"])
        else:
            spent = f"at most {money(cost['usd'])}"
        applied = _rate(counted["rates"]["applied"])
        lines.append(f"{head} {applied} | {repeated} | {timing} | {spent} |")
    return [
        *lines,
        "",
        REPEATED_CHOICES,
        "Spent is worked out from what each model reported, at its listed price. It is not a bill.",
    ]


def _run_facts(session: Mapping[str, Any], whose: str, count: int) -> str:
    """ "Ran 5 minutes with Puddle's model · minutes 6 to 11 · 5 decisions · spent $0.0004 of at
    most $0.05. The run played all its minutes." Why it ended is the society's own sentence."""
    held = session["living_session"]
    opened, closed = held["opened"], held["closed"]
    limits, used = opened["limits"], held["spending"]["used"]
    spent = f"spent {money(used['usd'])} of at most {money(limits['usd'])}"
    if used["unresolved_count"]:
        spent += f", and up to {money(used['unresolved_usd'])} more is not known yet"
    if closed is None:
        ran = f"Running when recorded: {plural(used['minutes'], 'minute')} so far"
        minutes = f"from minute {opened['tick']}"
        ending = ""
    else:
        ran = f"Ran {plural(used['minutes'], 'minute')}"
        minutes = f"minutes {opened['tick']} to {closed['tick']}"
        ending = f" {_sentence(closed_words(closed['reason']))}"
    return f"{ran} with {whose} · {minutes} · {plural(count, 'decision')} · {spent}.{ending}"


def _heading(name: str, session: Mapping[str, Any], number: int | None) -> str:
    held = session.get("living_session")
    if held is not None and number is not None:
        at = datetime.strptime(held["opened"]["at"], "%Y-%m-%dT%H:%M:%SZ")
        return f"### Run {number} · {at.day} {at:%B}, {at:%H:%M} UTC"
    ticks = [d["tick"] for d in session["decisions"]]
    return f"### Decisions, minutes {min(ticks)} to {max(ticks)}"


def _sessions_text(
    sessions: Mapping[str, Mapping[str, Any]],
    called: Mapping[str, str],
    readable: bool,
    words: Mapping[str, Any],
    level: int,
) -> list[str]:
    numbers = run_numbers(sessions)
    lines = [
        "## What the characters did",
        "",
        "Kept beside the world, not part of it: what each character was offered, what it chose "
        "and what the world did with the choice.",
    ]
    ordered = sorted(sessions.items(), key=lambda item: (numbers.get(item[0], 0), item[0]))
    detailed = ordered if level < 2 else ordered[-3:]
    for name, session in ordered:
        decisions = sorted(session["decisions"], key=lambda d: (d["tick"], d["record_id"]))
        number = numbers.get(name)
        if (name, session) not in detailed:
            what = f"Run {number}" if number is not None else "A record of decisions"
            lines += ["", f"{what}: {plural(len(decisions), 'decision')}, in its file."]
            continue
        models = _bindings(session)
        by_being: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for decision in decisions:
            model_id = models[decision["binding_sha256"]]["model_id"]
            by_being.setdefault((decision["thing_id"], model_id), []).append(decision)
        beings = sorted({thing_id for thing_id, _ in by_being})
        whose = (
            f"{possessive(called.get(beings[0], 'a character'))} model"
            if len(beings) == 1
            else f"{len(beings)} characters' models"
        )
        lines += ["", _heading(name, session, number), ""]
        if session.get("living_session"):
            lines += [_run_facts(session, whose, len(decisions)), ""]
        for (thing_id, model_id), own in sorted(by_being.items()):
            label = called.get(thing_id, "a character")
            own_rows = [_row(models[d["binding_sha256"]], d) for d in own]
            lines.append(_being_line(label, model_id, own_rows))
            if level >= 1:
                continue
            marked = [
                d
                for d in own
                if (d.get("receipt") or {}).get("disposition")
                in ("rejected", "superseded", "stale")
            ]
            keep = {id(own[0]), id(own[-1]), *(id(d) for d in marked[-(LINES_PER_BEING - 2) :])}
            shown = [d for d in own if id(d) in keep]
            lines += [f"  - {_decision_line(d, readable, words)}" for d in shown]
            rest = len(own) - len(shown)
            if rest:
                lines.append(
                    f"  - {plural(rest, 'more decision')} {'is' if rest == 1 else 'are'} in "
                    "this run's file."
                    if number is not None
                    else f"  - {plural(rest, 'more decision')} {'is' if rest == 1 else 'are'} "
                    "in its file."
                )
    return lines


def insight(
    world: Mapping[str, Any],
    sessions: Mapping[str, Mapping[str, Any]],
    *,
    readable: bool,
    words: Mapping[str, Any] | None = None,
) -> list[str]:
    """The pull request's sections on what the characters did and how each model did, within
    the budget, value-scanned. Empty without evidence. Without `readable` no written word
    appears, whatever the files hold."""
    if not sessions:
        return []
    said = words or choice_words()
    called = names([world if readable else without_words(world)])
    table = _model_table(_rows(sessions), called, readable)
    unavailable = []
    if any(_coverage(s) != "every request of the session" for s in sessions.values()):
        unavailable = [
            "",
            "Some of these records hold only the decisions the world acted on, so ones that got "
            "no usable answer are not counted there.",
        ]
    notes = (
        [],
        ["", "Shortened to fit: each run's file has every decision."],
        ["", "Shortened to fit: older runs are counted only; each run's file has every decision."],
    )
    for level in range(3):
        lines = [
            *_sessions_text(sessions, called, readable, said, level),
            *notes[level],
            "",
            *table,
            *unavailable,
        ]
        if len("\n".join(lines)) <= BUDGET:
            break
    else:
        raise ProjectError("the evidence is too large to summarise within the description budget")
    try:
        scan_values(lines)
    except ValueError as exc:
        raise ProjectError("the generated description failed the value scan") from exc
    return lines


def _coverage(session: Mapping[str, Any]) -> str:
    held = (session.get("coverage") or {}).get("decisions")
    return {
        "consumed": "only decisions a minute took up",
        "all": "every request of the session",
    }.get(held, "coverage not recorded")
