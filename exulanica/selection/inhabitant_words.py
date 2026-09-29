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

from exulanica.grammar.catalogs import CatalogSchema, load_catalog, text_field
from exulanica.world.society_catalogs import ACTIVITY_SETTINGS

__all__ = [
    "ACTIVITY_WORDS",
    "ACTIVITY_WORDS_PATH",
    "CATALOG_PATH",
    "ActivityWords",
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

ACTIVITY_WORDS_PATH: Final = CATALOG_PATH.with_name("society-activity-words.v1.json")


@dataclass(frozen=True, slots=True)
class ActivityWords:
    """What the inspector and the Companion say of one kind of activity: the ``doing`` entries of
    the words catalog for walking to it, being at it and having finished it."""

    key: str
    setting: str
    heading_doing: str
    under_way_doing: str
    finished_doing: str
    #: The reason the planner records while an activity in the open is under way, which only
    #: restates the activity; None for an activity at an object, whose goal always says why.
    under_way_reason: str | None


def _activity_words(path: Path = ACTIVITY_WORDS_PATH) -> dict[str, ActivityWords]:
    """Every kind of activity the society records, with its words, or a refusal naming a kind
    that has none or words for a kind nothing records.

    Words are not replayed, so this catalog is corrected in place; the codes stored societies
    record stay in ``society-affordance``, whose published versions never change.
    """
    stages = ("heading_doing", "under_way_doing", "finished_doing")
    page = ("verb", "verb_at_place", "direct_label", "direct_default", "marker_label")
    schema = CatalogSchema(
        "society-activity-words",
        1,
        tuple((name, text_field) for name in (*stages, "under_way_reason", *page, "reason")),
    )
    catalog = load_catalog(path, schema)
    found = {}
    for entry in catalog.entries:
        values = dict(entry.values)
        setting = ACTIVITY_SETTINGS.get(entry.key)
        if setting is None:
            raise WordsCatalogRefused(f"words for {entry.key!r}, which no activity catalog states")
        if any((setting == "object") == (values[name] == "none") for name in page):
            raise WordsCatalogRefused(
                f"{entry.key}: exactly an activity at an object has page words"
            )
        under_way_reason = str(values["under_way_reason"])
        if (setting == "object") != (under_way_reason == "none"):
            raise WordsCatalogRefused(
                f"{entry.key}: exactly an activity in the open states an under-way reason"
            )
        found[entry.key] = ActivityWords(
            entry.key,
            setting,
            *(str(values[s]) for s in stages),
            None if under_way_reason == "none" else under_way_reason,
        )
    missing = sorted(set(ACTIVITY_SETTINGS) - set(found))
    if missing:
        raise WordsCatalogRefused(f"no words for the activities {missing}")
    return found


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


#: What is said of each kind of activity, by its key (``_activity_words``).
ACTIVITY_WORDS: Final = _activity_words()


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
        heading = ACTIVITY_WORDS.get(goal_kind) if isinstance(goal_kind, str) else None
        if heading is not None and heading.setting != "object":
            chosen = heading.heading_doing
        elif goal_kind == "make_room" or action.get("target_id") is None:
            chosen = "walking_to_free_spot"
        elif heading is not None:
            chosen = heading.heading_doing
        else:
            # A goal no kind of activity states: nothing is said of it rather than a guess.
            chosen = "nothing_recorded"
    elif isinstance(kind, str) and kind in ACTIVITY_WORDS:
        activity = ACTIVITY_WORDS[kind]
        chosen = (
            activity.finished_doing
            if completed
            # Only a pair activity waits for the other person, by the planner's own code.
            else "waiting_to_talk"
            if action.get("reason") == "waiting_for_partner"
            else activity.under_way_doing
        )
    elif completed:
        chosen = "standing_aside"
    else:
        chosen = "deciding"
    doing = doing_words[chosen].format(
        place=where(action.get("target_id")), partner=met, still=still
    )
    # The goal says why a person set out. Once they are blocked, the action says why; so it does
    # for standing and talking when it records news since they set out (the other person is still
    # on the way, has gone, or the time is up), but not the reason that only restates the activity
    # under way, which would hide why they set out (a model's choice, say).
    under = ACTIVITY_WORDS.get(kind) if isinstance(kind, str) else None
    acting = status == "blocked" or (
        under is not None
        and under.setting != "object"
        and action.get("reason") != under.under_way_reason
    )
    code = goal["reason"] if not acting and goal is not None else action.get("reason", "")
    return InhabitantWords(who, what, doing, phrase["because"].format(reason=words.reason(code)))
