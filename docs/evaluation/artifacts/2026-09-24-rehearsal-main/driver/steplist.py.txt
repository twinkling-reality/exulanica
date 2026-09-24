"""The rehearsal's step list: load it, say whether it is well formed, and read the gates it covers.

The step list is data, ``steps.json`` beside this file. Each step is one named action a person takes
in the application, with the results a person or a program can observe after it: what the page
shows, what the API holds, and what a reload must preserve. A step either runs, in the page session
or the orchestrator stage its ``session`` names, or it is declared ``not_available`` with the reason
the product cannot attempt it, and a run reports it by that name rather than leaving a line out.

The gates a step serves are not written here, and not written in the step list either. They are
read from the document that owns them, ``docs/product-direction.md``, at the sections the step list
names: the first-milestone deliverables (a table) and the delivery gates for the first demonstration
(a numbered list). A gate that document adds, renames or drops therefore makes the step list stop
being well formed until a step serves it, which is the point: the rehearsal cannot quietly cover
less than the demonstration it rehearses.

Standard library only, so the orchestrator can run under any Python 3.11+ without the product's
environment, and the test can import it by file path.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STEPS_FILE = HERE / "steps.json"

STEPS_PROFILE = "exulanica.rehearsal-steps/v1"
#: What a run may say about a step. ``not_reachable`` is a step the run tried to reach and could not
#: (a step it requires did not pass, or its page session ended first); ``not_available`` is a step
#: the step list itself declares the product cannot attempt.
STATUSES = ("passed", "failed", "not_reachable", "not_available")
#: Who performs a session's steps: the orchestrator (``rehearse.py``) or one page session of the
#: browser driver (``session.mjs``), which is one headless Chrome with one page.
RUNNERS = ("orchestrator", "browser")
#: The three kinds of observable result a step can name.
OBSERVABLE_KINDS = ("page", "api", "reload")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class StepListError(ValueError):
    """The step list is not well formed; the message lists every problem found."""


@dataclass(frozen=True)
class Gate:
    """One gate of the demonstration, as the owning document states it."""

    key: str
    source: str
    name: str
    document: str
    heading: str


def _section(text: str, heading: str) -> str | None:
    """The body of the level-two section with exactly this heading, or None when there is none."""
    lines = text.splitlines()
    try:
        start = lines.index(f"## {heading}")
    except ValueError:
        return None
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _table_first_column(section: str) -> list[str]:
    """The first cell of every body row of the section's first table."""
    rows = [line for line in section.splitlines() if line.startswith("|")]
    # The header row and the separator row come first.
    return [row.strip("|").split("|")[0].strip() for row in rows[2:]]


_NUMBERED_BOLD = re.compile(r"^\d+\.\s+\*\*(?P<name>[^*]+?):\*\*")


def _numbered_bold(section: str) -> list[str]:
    """The bold name that opens every item of the section's numbered list."""
    return [
        match.group("name").strip()
        for match in (_NUMBERED_BOLD.match(line) for line in section.splitlines())
        if match is not None
    ]


#: How a gate source is read, by the ``form`` the step list declares for it.
GATE_FORMS: Mapping[str, Callable[[str], list[str]]] = {
    "table": _table_first_column,
    "numbered": _numbered_bold,
}


def read_gates(sources: Sequence[Mapping[str, Any]], root: Path = ROOT) -> tuple[Gate, ...]:
    """Every gate the named sections state, in document order. Refuses a source it cannot read."""
    gates: list[Gate] = []
    for source in sources:
        form = source.get("form")
        reader = GATE_FORMS.get(form) if isinstance(form, str) else None
        if reader is None:
            raise StepListError(f"gate source {source.get('key')!r}: unknown form {form!r}")
        document = root / source["document"]
        section = _section(document.read_text(encoding="utf-8"), source["heading"])
        if section is None:
            raise StepListError(
                f"gate source {source['key']!r}: {source['document']} has no section "
                f"'## {source['heading']}'"
            )
        names = reader(section)
        if not names:
            raise StepListError(
                f"gate source {source['key']!r}: '## {source['heading']}' in "
                f"{source['document']} states no gate in the {form} form"
            )
        gates.extend(
            Gate(
                key=f"{source['key']}:{name}",
                source=source["key"],
                name=name,
                document=source["document"],
                heading=source["heading"],
            )
            for name in names
        )
    return tuple(gates)


def load(path: Path = STEPS_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path = STEPS_FILE) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _observable_problems(step_id: str, expect: object) -> list[str]:
    if not isinstance(expect, dict) or not expect:
        return [f"{step_id}: names no observable result (expect is empty)"]
    problems = [
        f"{step_id}: expect has an unknown kind {kind!r}"
        for kind in expect
        if kind not in OBSERVABLE_KINDS
    ]
    seen: set[str] = set()
    total = 0
    for kind, observables in expect.items():
        if not isinstance(observables, list):
            problems.append(f"{step_id}: expect.{kind} is not a list")
            continue
        for observable in observables:
            total += 1
            identifier = observable.get("id") if isinstance(observable, dict) else None
            says = observable.get("says") if isinstance(observable, dict) else None
            if not isinstance(identifier, str) or not _IDENTIFIER.match(identifier):
                problems.append(f"{step_id}: an observable in expect.{kind} has no valid id")
                continue
            if identifier in seen:
                problems.append(f"{step_id}: observable {identifier!r} is named twice")
            seen.add(identifier)
            if not isinstance(says, str) or not says.strip():
                problems.append(
                    f"{step_id}: observable {identifier!r} does not say what it expects"
                )
    if total == 0:
        problems.append(f"{step_id}: names no observable result")
    return problems


def problems(steps: Mapping[str, Any], gates: Sequence[Gate]) -> list[str]:
    """Every way the step list is not well formed; an empty list means it is."""
    found: list[str] = []
    if steps.get("profile") != STEPS_PROFILE:
        found.append(f"profile is {steps.get('profile')!r}, not {STEPS_PROFILE!r}")
    version = steps.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        found.append("version is not a positive integer")

    sessions: dict[str, Mapping[str, Any]] = {}
    for session in steps.get("sessions", []):
        identifier = session.get("id")
        if not isinstance(identifier, str) or not _IDENTIFIER.match(identifier):
            found.append(f"a session has no valid id: {session!r}")
            continue
        if identifier in sessions:
            found.append(f"session {identifier!r} is declared twice")
        sessions[identifier] = session
        if session.get("runner") not in RUNNERS:
            found.append(f"session {identifier!r}: runner is not one of {RUNNERS}")
        if not str(session.get("purpose", "")).strip():
            found.append(f"session {identifier!r}: says no purpose")
        if session.get("runner") == "browser":
            budget = session.get("budget_seconds")
            if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
                found.append(f"session {identifier!r}: budget_seconds is not a positive integer")
            if not str(session.get("budget_reason", "")).strip():
                found.append(f"session {identifier!r}: its budget has no reason")
    if not sessions:
        found.append("declares no session")

    spend = steps.get("spend", {})
    bound = _decimal(spend.get("bound_usd"))
    ask_before = _decimal(spend.get("ask_before_usd"))
    if bound is None or ask_before is None:
        found.append("spend.bound_usd and spend.ask_before_usd must be decimal strings")

    gate_keys = {gate.key for gate in gates}
    served: dict[str, list[str]] = {gate.key: [] for gate in gates}
    earlier: set[str] = set()
    used_sessions: set[str] = set()
    estimate = Decimal(0)
    for step in steps.get("steps", []):
        identifier = step.get("id")
        if not isinstance(identifier, str) or not _IDENTIFIER.match(identifier):
            found.append(f"a step has no valid id: {str(step)[:120]}")
            continue
        if identifier in earlier:
            found.append(f"step {identifier!r} is declared twice")
        if not str(step.get("action", "")).strip():
            found.append(f"{identifier}: names no action")
        if not str(step.get("owner_area", "")).strip():
            found.append(f"{identifier}: names no owner area to route a failure to")
        found.extend(_observable_problems(identifier, step.get("expect")))
        step_gates = step.get("gates")
        if not isinstance(step_gates, list) or not step_gates:
            found.append(f"{identifier}: serves no gate")
        else:
            for gate in step_gates:
                if gate not in gate_keys:
                    found.append(
                        f"{identifier}: serves {gate!r}, which the owning document does not state"
                    )
                else:
                    served[gate].append(identifier)
        for required in step.get("requires", []):
            if required not in earlier:
                found.append(f"{identifier}: requires {required!r}, which is not an earlier step")
        unavailable = step.get("not_available")
        if unavailable is not None:
            if not isinstance(unavailable, str) or not unavailable.strip():
                found.append(f"{identifier}: not_available must say why")
            if "session" in step:
                found.append(f"{identifier}: a step the product cannot attempt runs in no session")
        else:
            session = step.get("session")
            if session not in sessions:
                found.append(f"{identifier}: runs in session {session!r}, which is not declared")
            else:
                used_sessions.add(session)
        if step.get("hosted_model", False) is not False:
            if step.get("hosted_model") is not True:
                found.append(f"{identifier}: hosted_model must be true or absent")
            amount = _decimal(step.get("spend_estimate_usd"))
            if amount is None:
                found.append(f"{identifier}: a hosted-model step needs spend_estimate_usd")
            else:
                estimate += amount
            if not str(step.get("spend_estimate_source", "")).strip():
                found.append(f"{identifier}: its spend estimate names no source")
        earlier.add(identifier)
    if not earlier:
        found.append("declares no step")
    for session in sorted(set(sessions) - used_sessions):
        found.append(f"session {session!r} runs no step")
    for gate in gates:
        if not served[gate.key]:
            found.append(f"gate {gate.key!r} ({gate.document}, '## {gate.heading}') has no step")
    if ask_before is not None and estimate > ask_before:
        found.append(
            f"the hosted-model steps are estimated at {estimate} USD, over the {ask_before} USD "
            "that needs a decision before a run"
        )
    return found


def check(steps: Mapping[str, Any], gates: Sequence[Gate]) -> None:
    found = problems(steps, gates)
    if found:
        raise StepListError("the step list is not well formed:\n  " + "\n  ".join(found))


def load_checked(
    path: Path = STEPS_FILE, root: Path = ROOT
) -> tuple[dict[str, Any], tuple[Gate, ...]]:
    """The step list and its gates, or StepListError naming every problem."""
    steps = load(path)
    gates = read_gates(steps.get("gate_sources", []), root)
    check(steps, gates)
    return steps, gates


def spend_estimate(steps: Mapping[str, Any]) -> Decimal:
    return sum(
        (
            Decimal(step["spend_estimate_usd"])
            for step in steps["steps"]
            if step.get("hosted_model")
        ),
        Decimal(0),
    )
