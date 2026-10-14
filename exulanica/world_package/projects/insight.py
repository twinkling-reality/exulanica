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
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.selection.inhabitant_words import inhabitant_words_catalog
from exulanica.world.decision_measures import LATENCY_MINIMUM, measures
from exulanica.world.society_sessions import closed_words
from exulanica.world_package.projects.checkpoint import ProjectError
from exulanica.world_package.projects.schema import ModelBinding, binding_sha256, scan_values
from exulanica.world_package.projects.summary import thing_names

CATALOG: Final = (
    Path(__file__).resolve().parents[3] / "assets/catalogs/roles/choice-account-words.v1.json"
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


def _decisions(count: int) -> str:
    return f"{count} decision" if count == 1 else f"{count} decisions"


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


def _answer(decision: Mapping[str, Any], readable: bool) -> str:
    chosen = decision["chosen_option_id"]
    if chosen is None:
        return "no offered option"
    text = decision.get("readable")
    if readable and text is not None and text.get("choice") is not None:
        return f"“{text['choice']}”"
    index = [o["option_id"] for o in decision["options"]].index(chosen)
    return f"option {index + 1} ({decision['options'][index]['action']})"


def _decision_line(decision: Mapping[str, Any], readable: bool, words: Mapping[str, Any]) -> str:
    receipt = decision.get("receipt")
    told = f"minute {decision['tick']}: of {len(decision['options'])} options, answered "
    told += _answer(decision, readable) + ". "
    if receipt is None:
        return told + f"Recorded outcome {decision['outcome']}; its receipt was not recorded."
    return told + verdict(receipt, words)


def _rows(sessions: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for _, session in sorted(sessions.items()):
        models = {binding_sha256(ModelBinding.model_validate(m)): m for m in session["models"]}
        for decision in session["decisions"]:
            model = models[decision["binding_sha256"]]
            receipt = decision.get("receipt") or {}
            text = decision.get("readable") or {}
            rows.append(
                {
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
            )
    return rows


def _rate(rate: Mapping[str, Any], noun: str) -> str:
    said = f"{noun} {rate['numerator']} of {rate['denominator']}"
    if rate["value"] is None and rate["denominator"]:
        said += f" (not enough data yet: {rate['minimum']} needed)"
    return said


def _being_line(name: str, model: str, rows: Sequence[Mapping[str, Any]]) -> str:
    head = f"- {name}, model {model}: {_decisions(len(rows))}"
    missing = sum(1 for row in rows if not row["has_receipt"])
    if missing:
        return (
            f"{head}; receipts were not recorded for {missing} of them, "
            "so their measures are unavailable."
        )
    counted = measures(rows)
    return f"{head}, {_rate(counted['rates']['applied'], 'applied')}."


def _model_table(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [
        "How each model did (all sessions in this pull request; never a combined score):",
        "",
        "| model | decisions | applied | repeated answer | latency p50 / p95 | cost |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(f"{row['provider']}/{row['model_id']}", []).append(row)
    for model, own in sorted(grouped.items()):
        if not all(row["has_receipt"] for row in own):
            unavailable = "unavailable: receipts were not recorded"
            lines.append(f"| {model} | {len(own)} | {unavailable} | {unavailable} | | |")
            continue
        counted = measures(own)
        repeated = (
            _rate(counted["rates"]["repeated_choice"], "")
            if all(row["has_labels"] for row in own)
            else "unavailable without readable labels"
        )
        latency = counted["latency_ms"]
        timing = (
            f"{latency['p50']} / {latency['p95']} ms"
            if latency["p50"] is not None
            else f"not enough data yet ({latency['n']} of {LATENCY_MINIMUM} timed calls)"
        )
        cost = counted["cost"]
        if not all(row["has_cost"] for row in own):
            money = "unavailable: cost not recorded for every call"
        elif cost["basis"] == "computed":
            money = f"${cost['usd']} computed from reported tokens (not a bill)"
        else:
            money = (
                f"at most ${cost['usd']}, {cost['unknown_calls']} of {cost['calls']} calls "
                "did not report tokens (not a bill)"
            )
        applied = _rate(counted["rates"]["applied"], "applied")
        lines.append(
            f"| {model} | {len(own)} | {applied} | {repeated.strip()} | {timing} | {money} |"
        )
    return lines


def _session_header(session: Mapping[str, Any], count: str) -> list[str]:
    """A living session's minutes, why it stopped in the society's own words, its limits and its
    spending as the spending authority read it. Never a bill."""
    held = session["living_session"]
    opened, closed = held["opened"], held["closed"]
    limits, used = opened["limits"], held["spending"]["used"]
    end = "now" if closed is None else closed["tick"]
    why = "open when captured." if closed is None else closed_words(closed["reason"])
    wall = limits["wall_seconds"]
    wall_words = f"{wall // 60} minutes" if wall % 60 == 0 else f"{wall} seconds"
    spent = f"Spending as found: ${used['usd']} committed for {used['calls']} calls"
    if used["unresolved_count"]:
        spent += (
            f", of which at most ${used['unresolved_usd']} for {used['unresolved_count']} calls "
            "is not known yet"
        )
    within = Decimal(used["usd"]) <= Decimal(limits["usd"])
    spent += f", {'within' if within else 'over'} its ${limits['usd']} limit. Not a bill."
    return [
        f"Living session {held['session_id'][:8]}, minutes {opened['tick']} to {end}: {why} "
        f"{count} ({_coverage(session)}).",
        f"Limits: {limits['minutes']} minutes, {limits['decisions']} decisions, "
        f"${limits['usd']}, {limits['calls']} calls, {wall_words} of wall time.",
        spent,
    ]


def _session_table(sessions: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Each living session's models side by side; timeouts only where every request was read."""
    living = [(name, s) for name, s in sorted(sessions.items()) if s.get("living_session")]
    if not living:
        return []
    lines = [
        "",
        "By living session:",
        "",
        "| session | model | decisions | applied | timeouts | latency p50 / p95 | bound |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, session in living:
        held = session["living_session"]
        bounds = {b["provider"]: b for b in held["spending"]["bounds"]}
        grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for row in _rows({name: session}):
            grouped.setdefault((row["provider"], row["model_id"]), []).append(row)
        for (provider, model_id), own in sorted(grouped.items()):
            label = f"| {held['session_id'][:8]} | {provider}/{model_id} | {len(own)} |"
            if not all(row["has_receipt"] for row in own):
                lines.append(f"{label} unavailable: receipts were not recorded | | | |")
                continue
            counted = measures(own)
            timeouts = (
                str(counted["counts"]["timeouts"])
                if _coverage(session) == "every request of the session"
                else "unavailable"
            )
            latency = counted["latency_ms"]
            timing = (
                f"{latency['p50']} / {latency['p95']} ms"
                if latency["p50"] is not None
                else "not enough data yet"
            )
            bound = bounds.get(provider)
            limit = (
                "no bound read"
                if bound is None
                else f"${bound['committed_usd']} of ${bound['ceiling_usd']}"
            )
            applied = _rate(counted["rates"]["applied"], "applied")
            lines.append(f"{label} {applied} | {timeouts} | {timing} | {limit} |")
    return lines


def _coverage(session: Mapping[str, Any]) -> str:
    held = (session.get("coverage") or {}).get("decisions")
    return {
        "consumed": "only decisions a minute took up",
        "all": "every request of the session",
    }.get(held, "coverage not recorded")


def _sessions_text(
    world: Mapping[str, Any],
    sessions: Mapping[str, Mapping[str, Any]],
    readable: bool,
    words: Mapping[str, Any],
    level: int,
) -> list[str]:
    names = thing_names(world["things"])
    lines = [
        "What the beings did, by session (from the evidence files; the records keep what each "
        "was told and answered, not why):",
    ]
    ordered = sorted(sessions.items(), key=lambda item: item[1]["session_id"])
    detailed = ordered if level < 2 else ordered[-3:]
    for name, session in ordered:
        decisions = sorted(session["decisions"], key=lambda d: (d["tick"], d["record_id"]))
        ticks = [d["tick"] for d in decisions]
        count = _decisions(len(decisions))
        if (name, session) not in detailed:
            lines.append(f"- {session['session_id']}: {count}, see its file evidence/{name}.")
            continue
        lines += [
            "",
            *(
                _session_header(session, count)
                if session.get("living_session")
                else [
                    f"{session['session_id']}, minutes {min(ticks)} to {max(ticks)}, {count} "
                    f"({_coverage(session)})"
                ]
            ),
        ]
        rows = _rows({name: session})
        models = {
            binding_sha256(ModelBinding.model_validate(m)): m["model_id"] for m in session["models"]
        }
        by_being: dict[str, list[Mapping[str, Any]]] = {}
        for decision in decisions:
            by_being.setdefault(decision["thing_id"], []).append(decision)
        for thing_id, own in sorted(by_being.items()):
            label = names.get(thing_id, thing_id)
            model = models[own[0]["binding_sha256"]]
            own_rows = [row for row in rows if row["subject_id"] == thing_id]
            lines.append(_being_line(label, model, own_rows))
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
            if len(own) > len(shown):
                lines.append(f"  - {len(own) - len(shown)} more in evidence/{name}")
    return lines


def insight(
    world: Mapping[str, Any],
    sessions: Mapping[str, Mapping[str, Any]],
    *,
    readable: bool,
    words: Mapping[str, Any] | None = None,
) -> list[str]:
    """The pull request's insight sections, within the budget, value-scanned. Empty without
    evidence."""
    if not sessions:
        return []
    said = words or choice_words()
    table = _model_table(_rows(sessions)) + _session_table(sessions)
    unavailable = []
    if any(_coverage(s) != "every request of the session" for s in sessions.values()):
        unavailable = [
            "",
            "Unavailable here: unanswered and timed-out requests, acceptance and timeout streaks. "
            "These files hold only the decisions a minute took up, or do not say.",
        ]
    notes = (
        [],
        ["", "Shortened to fit: decision lines are left out; each file has them all."],
        ["", "Shortened to fit: decision lines and older sessions' detail are left out."],
    )
    for level in range(3):
        lines = [
            *_sessions_text(world, sessions, readable, said, level),
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
