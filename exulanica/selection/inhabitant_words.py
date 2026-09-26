"""Who a simulated person is and what they are doing, in the words the inspector uses.

The words are one data file,
``assets/catalogs/society-words/society-inhabitant-words.v1.json``, which the browser's inspector
reads too (``web/packages/app/src/society-inhabitant-words.ts``). The choice of sentence for a
state is code on both sides, and both are held to one set of cases,
``tests/fixtures/society-inhabitant-words/cases.json``, which ``tests/test_inhabitant_words.py`` and
``web/packages/app/test/society-inhabitant-words.test.ts`` run. So the inspector and the Companion
say the same thing of the same person, and a change to either side's choice fails a test.

Nothing here names anybody: the caller says how a place and another person are written, which on
the server is a placeholder the page draws (:mod:`exulanica.selection.society_question`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CATALOG_PATH",
    "InhabitantWords",
    "InhabitantWordsCatalog",
    "WordsCatalogRefused",
    "inhabitant_words",
    "inhabitant_words_catalog",
]

CATALOG_PATH: Final = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "catalogs"
    / "society-words"
    / "society-inhabitant-words.v1.json"
)

#: The kinds of entry the catalog holds, each read into its own table below. A kind outside these
#: is refused rather than ignored, so an entry nothing reads cannot ship.
_KINDS: Final = (
    "reason",
    "phrase",
    "doing",
    "outcome",
    "event_reason",
    "line",
    # Why a person's model was or was not followed. The page's People panel reads them; the
    # server holds them to ``DECISION_REASONS`` (tests/test_companion_decision_model.py).
    "decision_reason",
)


class WordsCatalogRefused(ValueError):
    """The words catalog does not have the shape its readers need."""


@dataclass(frozen=True, slots=True)
class InhabitantWordsCatalog:
    """The catalog's entries by kind and code, the profiles it has words for, and its digest."""

    tables: Mapping[str, Mapping[str, str]]
    profiles: frozenset[str]
    sha256: str

    def words(self, kind: str, code: str) -> str:
        """One entry's words. A missing one is a defect of the catalog, raised as one."""
        try:
            return self.tables[kind][code]
        except KeyError:
            raise WordsCatalogRefused(f"the words catalog has no {kind} {code!r}") from None

    def reason(self, code: str) -> str:
        """Why a person does something, or the named sentence for a code with no words."""
        known = self.tables["reason"].get(code) or self.tables["event_reason"].get(code)
        if known is not None:
            return known
        return self.words("phrase", "reason_unknown").format(code=code)


@cache
def inhabitant_words_catalog(path: Path = CATALOG_PATH) -> InhabitantWordsCatalog:
    """The catalog, read once, refusing any shape its readers would misread."""
    raw = path.read_bytes()
    document = json.loads(raw)
    if document.get("catalog_id") != "society-inhabitant-words":
        raise WordsCatalogRefused("not the society inhabitant words catalog")
    tables: dict[str, dict[str, str]] = {kind: {} for kind in _KINDS}
    for entry in document["entries"]:
        kind, code, words = entry.get("kind"), entry.get("code"), entry.get("words")
        if kind not in tables:
            raise WordsCatalogRefused(f"entry {entry.get('key')!r} has an unknown kind {kind!r}")
        if not isinstance(code, str) or not isinstance(words, str) or not words:
            raise WordsCatalogRefused(f"entry {entry.get('key')!r} has no code or no words")
        if entry.get("key") != f"{kind}.{code}":
            raise WordsCatalogRefused(f"entry {entry.get('key')!r} is not keyed by kind and code")
        if code in tables[kind]:
            raise WordsCatalogRefused(f"entry {entry['key']!r} is stated twice")
        tables[kind][code] = words
    return InhabitantWordsCatalog(
        tables=tables,
        profiles=frozenset(document["profiles"]),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class InhabitantWords:
    """A person's own words at the top of the inspector: who, what they are doing now, and why."""

    who: str
    what: str
    doing: str
    why: str


def inhabitant_words(
    person: Mapping[str, Any],
    place: Callable[[str], str | None],
    partner: Callable[[str], str | None],
    catalog: InhabitantWordsCatalog | None = None,
) -> InhabitantWords:
    """Who a simulated person is and what they are doing, from their recorded state.

    ``place`` writes a target the person uses, or returns None for one the world no longer holds;
    ``partner`` writes another person, or None for one not in the society. The choice follows
    ``inhabitantWords`` in the inspector line for line, and the shared cases hold the two equal.
    Talking has no content, so nothing here says what anybody talked about.
    """
    words = catalog or inhabitant_words_catalog()
    phrase = words.tables["phrase"]
    doing_words = words.tables["doing"]
    who = person.get("display_name") or phrase["who_unnamed"]
    what = phrase["what"].format(role=person.get("role") or phrase["role_unknown"])
    action = person.get("action")
    goal = person.get("goal")
    goal = goal if isinstance(goal, Mapping) and "kind" in goal else None
    if action is None:
        return InhabitantWords(who, what, doing_words["nothing_recorded"], "")

    def where(target_id: str | None) -> str:
        if not target_id:
            return phrase["place_none"]
        return place(target_id) or phrase["place_gone"]

    remaining = action.get("remaining_ticks") or 0
    still = (
        ""
        if not remaining
        else phrase["still_one"]
        if remaining == 1
        else phrase["still_many"].format(count=remaining)
    )
    partner_id = goal.get("partner_id") if goal is not None else None
    met = (partner(partner_id) if partner_id else None) or phrase["partner_unknown"]
    kind, status = action.get("kind"), action.get("status")
    completed = status == "completed"
    if status == "blocked":
        chosen = "waiting"
    elif kind == "move":
        goal_kind = goal.get("kind") if goal is not None else None
        if goal_kind == "stand":
            chosen = "walking_to_stand"
        elif goal_kind == "talk":
            chosen = "walking_to_talk"
        elif goal_kind == "make_room" or action.get("target_id") is None:
            chosen = "walking_to_free_spot"
        else:
            chosen = "walking_to_rest" if goal_kind == "rest" else "walking_to_visit"
    elif kind in ("rest", "visit"):
        stem = "resting" if kind == "rest" else "visiting"
        chosen = f"finished_{stem}" if completed else stem
    elif kind == "stand":
        chosen = "finished_standing" if completed else "standing"
    elif kind == "talk":
        chosen = (
            "finished_talking"
            if completed
            else "waiting_to_talk"
            if action.get("reason") == "waiting_for_partner"
            else "talking"
        )
    elif completed:
        chosen = "standing_aside"
    else:
        chosen = "deciding"
    doing = doing_words[chosen].format(
        place=where(action.get("target_id")), partner=met, still=still
    )
    # The goal says why a person set out. Once they are blocked, the action says why; so it does
    # for standing and talking, under way or over, where only the action knows whether the other
    # person is still on the way, is there, or has gone.
    acting = status == "blocked" or kind in ("stand", "talk")
    code = goal["reason"] if not acting and goal is not None else action.get("reason", "")
    return InhabitantWords(who, what, doing, phrase["because"].format(reason=words.reason(code)))
