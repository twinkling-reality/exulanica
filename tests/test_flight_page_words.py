"""The words a page says about a saved world's flight cover every code the server can send it.

The page stops at a refusal the server keeps giving and says why in words, from ``REFUSAL_WORDS``
in ``web/packages/app/src/composition/saved-world-flight.ts``; it says why flyers an object hosts
have no home from ``UNPLACED_WORDS`` beside it. A code with no words reaches a person as a bare
code, so each table names exactly the codes the server can give: every ``FlightRefused`` code
raised in the package, and the flight module's registry refusal when its row states one, for the
first; every reason the composer puts under ``unplaced``, for the second. A code the server stops
giving leaves words nobody reads, so an extra entry fails too.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from exulanica.movement.registry import FLIGHT, MODULES_PATH
from exulanica.world.flight_worker import FlightWorkerUnavailable

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "exulanica"
PAGE = ROOT / "web" / "packages" / "app" / "src" / "composition" / "saved-world-flight.ts"
#: Answered 503 and tried again by the page, which never shows refusal words for it.
RETRIED = frozenset({FlightWorkerUnavailable("retried").code})
#: The keys a flyer the composer could not home is stated by.
UNPLACED_KEYS = frozenset({"object_id", "kind", "count", "reason"})


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _code(call: ast.Call, where: str) -> str:
    first = call.args[0] if call.args else None
    assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
        f"{where} gives a flight refusal whose code this test cannot read"
    )
    return first.value


def _trees() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(PACKAGE.rglob("*.py"))
    ]


def _refusal_codes() -> set[str]:
    trees = _trees()
    # FlightRefused and every class made from it, however deep.
    refusals = {"FlightRefused"}
    while True:
        more = {
            node.name
            for _, tree in trees
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and {_name(base) for base in node.bases} & refusals
        }
        if more <= refusals:
            break
        refusals |= more
    codes: set[str] = set()
    for path, tree in trees:
        for node in ast.walk(tree):
            # A class made from FlightRefused states its code once, in its own constructor.
            if isinstance(node, ast.Call) and _name(node.func) == "FlightRefused":
                codes.add(_code(node, f"{path.relative_to(ROOT)}:{node.lineno}"))
            if isinstance(node, ast.ClassDef) and node.name in refusals - {"FlightRefused"}:
                for call in ast.walk(node):
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "__init__"
                        and isinstance(call.func.value, ast.Call)
                        and _name(call.func.value.func) == "super"
                    ):
                        codes.add(_code(call, f"{path.relative_to(ROOT)}:{call.lineno}"))
    rows = json.loads(MODULES_PATH.read_text(encoding="utf-8"))
    rows = rows["modules"] if isinstance(rows, dict) else rows
    (flight,) = [row for row in rows if row["module"] == FLIGHT]
    if flight.get("refusal"):
        codes.add(flight["refusal"])
    return codes


def _unplaced_reasons() -> set[str]:
    reasons: set[str] = set()
    for path, tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
            if set(keys) != UNPLACED_KEYS:
                continue
            reason = node.values[keys.index("reason")]
            assert isinstance(reason, ast.Constant) and isinstance(reason.value, str), (
                f"{path.relative_to(ROOT)}:{node.lineno} leaves flyers without a home for a "
                "reason this test cannot read"
            )
            reasons.add(reason.value)
    return reasons


def _table(name: str) -> set[str]:
    source = PAGE.read_text(encoding="utf-8")
    found = re.search(rf"^const {name}: [^=]+= \{{\n(?P<body>.*?)\n\}};", source, re.M | re.S)
    assert found, f"{name} is not in {PAGE.name}"
    lines = [line for line in found["body"].splitlines() if not line.strip().startswith("//")]
    keys = [re.match(r"  ([a-z][a-z0-9_]*): ", line) for line in lines]
    assert all(keys), f"{name} has an entry this test cannot read: one code a line"
    return {key[1] for key in keys if key}


def test_every_refusal_the_server_can_give_a_page_has_words_and_no_other():
    codes = _refusal_codes()
    assert codes >= RETRIED and "home_perch_unusable" in codes
    words = _table("REFUSAL_WORDS")
    assert sorted(codes - RETRIED - words) == [], "refusals a page would show as a bare code"
    assert sorted(words - codes) == [], "words for a refusal the server never gives"


def test_every_reason_flyers_have_no_home_has_words_and_no_other():
    reasons = _unplaced_reasons()
    assert "home_perch_unusable" in reasons
    words = _table("UNPLACED_WORDS")
    assert sorted(reasons - words) == [], "reasons a page would show as a bare code"
    assert sorted(words - reasons) == [], "words for a reason the server never gives"
