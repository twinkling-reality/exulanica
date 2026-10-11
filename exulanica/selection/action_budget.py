"""A world's budget for its minds, as a step of a Companion plan.

A person may set what a world spends on the model minds of its beings in one sentence ("let this
town spend up to 50 cents an hour on minds"). The step is the request the budget route takes
(``POST /world/versions/{version_id}/models/{role_key}/budget``), so a budget reached through the
Companion is the budget sent directly. The Companion's drafter fills listed options only and
never writes a number, so the figures of such a step are read here, from the person's own words,
and listed for the drafter as options: US dollars with a money word, model decisions with a count
word, each with the period the words give it.

What code reads is a stated limit, not a guess at language: digits, or plain English number words
up to the thousands, beside ``$``, ``USD``, dollars, bucks, cents or ``c`` for money, and beside
decisions, answers, asks, calls, questions or "times an hour" for a count. A sentence whose
amount is said another way is asked for its figure; it is never refused and never guessed.

**The rule: a sentence plans a figure only where the whole of it, in order, is one of a short
list of shapes.** The shapes are data (:data:`SHAPES`): each a pattern of slots in order, with the
sentences it was written for, and each slot a closed list of words that is allowed in that slot
and nowhere else. A shape is made of amounts in a form listed above, the hour a budget is by,
slot words, and, in the one compound, names code holds for what another step of the same request
acts on (:func:`shape_of`). Every character of the sentence is read: what is no number, no plain
word and no known sign is a token no shape holds. Anything that is not a shape is asked about.
What is doubtful (a span, a change, a report of the past, a sum of parts) needs no list to be
caught; the lists below only choose which question is asked. A question costs nothing and a
wrong budget spends money.

What this module holds by construction:

*   **A figure is the person's or it is not offered.** Digits, or plain number words, beside a
    unit this module knows. Anything else is not an amount, and the plan asks for the figure
    rather than guessing one.
*   **A figure the words do not state plainly is asked about.** Read as unclear, each asked
    for its figure: an amount said as a change ("by 50 cents", "a dollar more", "add 50
    cents", "10 cents off"); an amount with more of a number beside it ("a dollar fifty",
    "1.5k", "two fifty"); an amount joined to more by "and", "to" or "or" ("one hundred and
    twenty decisions", "a dollar and a half", "a dollar and 25 cents", "fifty to sixty cents",
    "2 dollars or 3"); an amount in a sentence that reports what was charged, paid, spent or
    billed, or that speaks of yesterday, last week or what already was; and dollars said to be
    another country's. A range in digits ("50 to 60 cents") is two amounts, and so are two
    amounts with "or" between them: a choice the sentence offers, which is never planned and is
    asked about with both where they are of one kind. An amount said after "from" is what the
    budget is changed from, and is set aside only where it is the world's budget now.
*   **Nothing is converted between periods.** A budget is by the hour of real time: "an hour",
    "per hour", "every hour", "each hour", "hourly", "/h", "/hr". An amount the words give any
    other span is read with that span, so the plan can ask what the world may spend in an hour;
    it is never divided or multiplied into one. Another span is any of: a counted span ("every
    24 hours", "for 30 days", "per 10 minutes"), a part of an hour ("half an hour"), a span
    word in the singular or the plural or its short form (seconds, minutes, hours, days, weeks,
    months, years, today, tonight), an hour of the world's own time ("a game hour"), the whole
    of it ("in all", "in total"), and "a", "per", "every" or "each" before any word that is not
    an hour's ("50 cents a being", "per turn"). A span word anywhere in the sentence is the
    span of every amount that names no hour of its own.
*   **The two budgets with no figure are held to the person's own words.** "Nothing" is planned
    only where the sentence says nothing, none, zero, off or stop, and the default only where it
    says default, reset, original or "starts with"; a sentence that speaks of no limit is asked
    for its figure, and so is one where an amount was read beside either.
*   **Dollars are exact.** Amounts are decimals, never binary fractions, and a figure a budget's
    row cannot hold as written (more than six decimals) is not an amount.
*   **A figure the words do not name is kept.** "50 cents an hour" sets the dollars and leaves
    the decisions as the world has them; the step says which figures the words named.
*   **What it comes to is said before the yes.** The step carries the route's own figures for
    this world (:class:`Budgets`, which the actions route hands the planner): both ceilings, which
    runs out first, what the hour already holds and what this server allows above any budget.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, Protocol

__all__ = [
    "BUDGET",
    "DECISIONS",
    "DEFAULT",
    "FIGURES",
    "HOUR",
    "NOTHING",
    "OTHER",
    "USD",
    "Amount",
    "Budgets",
    "PreparedBudget",
    "Resolved",
    "amounts",
    "budget_key",
    "figure_title",
    "prepare",
    "resolve",
    "shape_of",
    "stated",
    "usd_text",
]

#: The route a world's budget for its minds is sent to, for the role that decides for people.
BUDGET: Final = "POST /world/versions/{version_id}/models/{role_key}/budget"
#: The two budgets a person may name without a figure: no model asked at all, and what a world
#: has before anyone sets one.
NOTHING: Final = "nothing"
DEFAULT: Final = "default"
#: A budget's two figures, as a typed step and the route's body name them.
FIGURES: Final = ("usd_per_hour", "decisions_per_hour")

USD: Final = "usd"
DECISIONS: Final = "decisions"
#: An amount's period as the words give it: an hour, another span, or None where they name none
#: (a budget is by the hour, so the sheet then says the hour).
HOUR: Final = "hour"
OTHER: Final = "other"

_MICRO: Final = Decimal("0.000001")
#: A number keeps a comma only where three digits follow it ("1,000"): "$2, and" reads 2.
#: Every character of a sentence is read. A number, a word in plain letters and the three signs
#: this module knows are tokens it can account for; a hyphen that joins no two letters, and any
#: other run of characters (another script, a plus or a percent sign, a fraction, a symbol), is
#: a token nothing accounts for. Only plain punctuation is silent: . , ; : ! ' " ( ) with the
#: curly forms of the two quotes, and a hyphen between letters. A question mark is read: a
#: question is asked back, not planned.
_TOKEN: Final = re.compile(
    r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|\.[0-9]+|[a-z]+|[$¢/]"
    r"|(?<![a-z])-|-(?![a-z])"
    r"|[^\s\w.,;:!'\"()\u2018\u2019\u201c\u201d$¢/\-]+|[^\Wa-z0-9_]+|_+"
)
_DIGITS: Final = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+")
#: A whole number with exactly three decimals ("1.000", "2.500") may be thousands written the
#: continental way: it is read as no number, and so is asked about.
_THOUSANDS_OR_DECIMALS: Final = re.compile(r"[1-9][0-9]{0,2}\.[0-9]{3}")

_ONES: Final = {
    word: value
    for value, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_TENS: Final = {
    word: 10 * value
    for value, word in enumerate(
        ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"], start=2
    )
}
_DOLLARS: Final = frozenset({"dollar", "dollars", "usd", "buck", "bucks"})
_CENTS: Final = frozenset({"cent", "cents", "¢"})
_COUNTED: Final = frozenset(
    {"decision", "decisions", "answer", "answers", "ask", "asks", "call", "calls", "question"}
    | {"questions"}
)
#: Words that may stand between a number and what it counts ("600 model decisions").
_COUNT_FILLERS: Final = frozenset({"model", "ai"})
#: The hour a budget is by, in the singular: one hour of real time and no other span.
_HOURS: Final = frozenset({"hour", "hourly", "hr"})
#: Every other span of time, in the singular, the plural and the short form. Hours in the plural
#: are a span of their own ("every 24 hours", "for 3 hours"), never the hour a budget is by.
_SPANS: Final = frozenset(
    {"second", "seconds", "sec", "secs", "minute", "minutes", "min", "mins"}
    | {"hours", "hrs", "day", "days", "daily", "week", "weeks", "weekly", "fortnight"}
    | {"month", "months", "monthly", "year", "years", "yearly", "annually", "annual"}
    | {"today", "tonight", "tomorrow", "weekend"}
)
#: Spans that are one only said with an amount ("5 dollars a night"); elsewhere in a sentence
#: the same words are an hour of the day.
_SPANS_BESIDE: Final = frozenset({"night", "nights", "nightly", "morning", "afternoon", "evening"})
#: Said after an amount, the whole of it and no rate: "5 dollars in all", "5 dollars total".
_WHOLE: Final = frozenset({"total", "altogether", "overall"})
#: A part of an hour is another span: "every half hour", "per quarter of an hour".
_PARTS: Final = frozenset({"half", "quarter"})
#: Before a span, the words that make an amount a rate over it; before any word that is not an
#: hour's they make it a rate over something a budget is not by ("per being", "each turn").
_RATE: Final = frozenset({"per", "every", "each", "/"})
#: Words that may stand between such a word and its span ("in any one hour", "per real hour").
_SPAN_FILLERS: Final = frozenset(
    {"the", "this", "any", "one", "single", "real", "whole", "full", "clock", "given"}
)
#: How many words after an amount may hold its period ("50 cents in any one hour").
_REACH: Final = 4
#: Said before "hour", the world's own time and not the real hour a budget is counted by.
_NOT_REAL_TIME: Final = frozenset(
    {"simulated", "simulation", "sim", "game", "world", "town", "ingame", "virtual", "story"}
)
#: Said right before an amount, or right after it, the amount is a change and not the figure.
_CHANGE_BEFORE: Final = frozenset(
    {"by", "another", "extra", "additional", "add", "plus", "minus", "subtract"}
)
_CHANGE_AFTER: Final = frozenset({"more", "less", "extra", "fewer", "higher", "lower", "off"})
#: Between two numbers, the words that make them a range, a choice or a sum of parts.
_BETWEEN: Final = frozenset({"to", "or", "and"})
#: Anywhere in a sentence, the words that make its amounts a report of what was and not a
#: figure asked for: what was charged or paid, and when.
_REPORT: Final = frozenset(
    {"charged", "paid", "billed", "spent", "costed", "wasted", "burned", "burnt", "used"}
    | {"was", "were", "been", "yesterday", "already", "ago", "earlier", "previously", "last"}
    | {"bill", "invoice"}
)
#: "cost me", "costs us": a report of a cost, where "cost" alone may be the figure asked for.
_COST: Final = frozenset({"cost", "costs", "costing"})
_TO_WHOM: Final = frozenset({"me", "us", "you", "him", "her", "them"})
#: Dollars that are not US dollars: a letter stuck before the sign ("C$5"), or said after.
_OTHER_DOLLARS: Final = frozenset(
    {"canadian", "australian", "cad", "aud", "nzd", "sgd", "hkd", "zealand", "singapore"}
    | {"hong", "taiwan", "mexican", "jamaican", "bahamian", "fijian", "namibian", "liberian"}
)
#: The shapes a sentence that sets a budget may have, as data: each a pattern of slots in order
#: with the sentences it was written for, and each slot's closed list of words. A sentence is
#: planned only where the whole of it, in order, is one of them.
SHAPES: Final = (
    Path(__file__).resolve().parents[2]
    / "assets/catalogs/minds-budget-shapes/minds-budget-shapes.v1.json"
)
#: Before the hour, the one word that makes an amount a rate over it, and the words that may
#: stand between that word and the hour ("in any one hour"). "For", "this" and "whole" are not
#: among them: "for one hour" is an end, not a rate.
_HOUR_RATE: Final = frozenset({"a", "an", "per", "every", "each", "/", "in"})
_HOUR_FILLERS: Final = frozenset({"any", "one", "single"})
#: What a shape plans: the amounts its words state, an amount moved from what the budget is
#: now, or one of the two budgets with no figure.
AMOUNTS: Final = "amounts"
FROM_TO: Final = "from_to"
#: What a shape comes to where its amounts are a choice the sentence itself offers ("30 cents or
#: 50 cents", "50 to 60 cents"): never a plan, and the question between them where they are two
#: amounts of one kind.
CHOICE: Final = "choice"
_CHOSEN: Final = "one of the amounts"
_CHOICE_JOINS: Final = frozenset({"or", "to"})
#: The slots whose filling says whose figure it is: the budget's clause after another step's
#: names must fill one.
_SAYS_WHOSE: Final = frozenset({"subject", "given"})
#: After another step's names a pronoun points at what was just named, not at the world: a
#: budget's clause that holds one says nobody's figure.
_POINTS_BACK: Final = frozenset({"it", "its", "their"})
#: The slot whose words may say which way a figure moves, and the mark a shape's kind carries
#: where its sentence says one ("amounts:down"): :func:`resolve` holds the figure to it.
_MOVE: Final = "move"
UP: Final = "up"
DOWN: Final = "down"
#: The slot of the few words another step's clause may hold among its names.
_OTHER_STEP: Final = "other_step"
#: The words a sentence states each budget with no figure by, and those that speak of no limit
#: at all, which is never either of them.
_SAYS_NOTHING: Final = frozenset({"nothing", "none", "zero", "0", "off", "stop"})
#: Said of a limit, the words that take the limit away and do not turn the spending off:
#: "turn the cap off" states no budget of nothing.
_TAKES_AWAY: Final = frozenset({"off", "stop", "none"})
_SAYS_DEFAULT: Final = frozenset({"default", "defaults", "reset", "original"})
_NO_LIMIT: Final = frozenset({"unlimited", "limitless", "uncapped", "infinite", "unbounded"})
_LIMITS: Final = frozenset(
    {"limit", "limits", "cap", "caps", "ceiling", "bound", "bounds", "maximum", "max"}
    | {"restriction", "restrictions"}
)
_LIMITED: Final = _LIMITS | {"budget", "budgets"}


@dataclass(frozen=True, slots=True)
class Amount:
    """One amount a sentence states: US dollars or model decisions, the period its words give it
    (:data:`HOUR`, :data:`OTHER` or None) and the words it was read from. ``unclear`` says the
    sentence does not state it plainly as the budget's own figure: it is a change, a part of a
    sum, a report of the past, another country's dollars, or more of a number is said next to it
    than code read. ``was`` says it follows "from": what the budget is changed from."""

    unit: str
    value: Decimal
    period: str | None
    words: str
    unclear: bool = False
    was: bool = False


@dataclass(frozen=True, slots=True)
class _Word:
    text: str
    start: int
    end: int


def _number(words: list[_Word], at: int) -> tuple[Decimal, int] | None:
    """The number that starts at ``words[at]`` and where it ends: digits, or number words up to
    the thousands said as one number ("twenty five", "five hundred", "two thousand five
    hundred"), or None. Words that are two numbers side by side ("two fifty") end at the first:
    the second is then a number beside it, which makes the amount unclear."""
    text = words[at].text
    if _THOUSANDS_OR_DECIMALS.fullmatch(text):
        return None
    if _DIGITS.fullmatch(text):
        return Decimal(text.replace(",", "")), at + 1
    total = 0
    current = 0
    #: What the word before was: a unit under ten, a teen, a ten, or a scale word.
    last = ""
    index = at
    while index < len(words):
        word = words[index].text
        if word in _ONES and _ONES[word] < 10 and last in ("", "ten", "scale"):
            current += _ONES[word]
            last = "one"
        elif word in _ONES and _ONES[word] >= 10 and last in ("", "scale"):
            current += _ONES[word]
            last = "teen"
        elif word in _TENS and last in ("", "scale"):
            current += _TENS[word]
            last = "ten"
        elif word == "hundred" and last == "one" and current < 10:
            current *= 100
            last = "scale"
        elif word == "thousand" and last in ("one", "teen", "ten", "scale") and total == 0:
            total = current * 1000
            current = 0
            last = "scale"
        else:
            break
        index += 1
    if not last:
        return None
    return Decimal(total + current), index


def _article(words: list[_Word], at: int) -> tuple[Decimal, int] | None:
    """ "a dollar", "a hundred decisions" and "half a cent": the article as one, or a half."""
    text = words[at].text
    if text == "half" and at + 1 < len(words) and words[at + 1].text in ("a", "an"):
        return Decimal("0.5"), at + 2
    if text in ("a", "an") and at + 1 < len(words):
        following = words[at + 1].text
        if following in ("hundred", "thousand"):
            scale = 100 if following == "hundred" else 1000
            return Decimal(scale), at + 2
        if following in _DOLLARS or following in _CENTS:
            return Decimal(1), at + 1
    return None


def _counted(words: list[_Word], at: int) -> tuple[Decimal, int] | None:
    """A number at ``words[at]`` that counts something: "one", "a" and "an" are no count."""
    if words[at].text in ("one", "a", "an"):
        return None
    read = _number(words, at)
    return None if read is None or read[0] == 1 else read


def _is_hour(words: list[_Word], at: int) -> bool:
    word = words[at].text
    return word in _HOURS or (word == "h" and at > 0 and words[at - 1].text == "/")


def _hour_said(words: list[_Word], at: int) -> str:
    """The span the hour word at ``words[at]`` names: the hour a budget is by, or another span
    where it is an hour of the world's own time, a counted number of hours or a part of one."""
    before = [word.text for word in words[max(0, at - 3) : at]]
    if before and before[-1] in _NOT_REAL_TIME:
        return OTHER
    if any(part in _PARTS for part in before):
        return OTHER
    back = at - 1
    while back >= 0 and words[back].text in _SPAN_FILLERS and words[back].text != "one":
        back -= 1
    if back < 0 or words[at].text == "hourly":
        # "$5 hourly": the number before is the amount's own, never a count of hours.
        return HOUR
    counted = words[back].text
    if _DIGITS.fullmatch(counted):
        return HOUR if Decimal(counted.replace(",", "")) == 1 else OTHER
    if counted != "one" and (
        counted in _ONES or counted in _TENS or counted in ("hundred", "thousand")
    ):
        return OTHER
    return HOUR


def _own_period(words: list[_Word], after: int, starts: frozenset[int]) -> str | None:
    """The period said right after an amount, before any other amount: None where none is."""
    for index in range(after, min(len(words), after + _REACH)):
        word = words[index].text
        if index in starts:
            return None
        if _is_hour(words, index):
            return _hour_said(words, index)
        if word in _SPANS or word in _SPANS_BESIDE or word in _WHOLE or word in _PARTS:
            return OTHER
        if word == "all" and words[index - 1].text == "in":
            return OTHER
        counted = _counted(words, index)
        if counted is not None:
            # A counted span ("every 24 hours", "for 30 days"), or a count of anything after a
            # word that makes a rate ("per 10 turns"); any other number ends the amount's own
            # words.
            following = counted[1]
            spans = following < len(words) and (
                _is_hour(words, following)
                or words[following].text in _SPANS
                or words[following].text in _SPANS_BESIDE
            )
            return OTHER if spans or words[index - 1].text in _RATE else None
        if word in _RATE or (word in ("a", "an") and index == after):
            ahead = index + 1
            while ahead < len(words) and words[ahead].text in _SPAN_FILLERS:
                ahead += 1
            if ahead >= len(words):
                # "50 cents each": a figure for each of something, which a budget is not by.
                if word == "each":
                    return OTHER
                continue
            known = (
                _is_hour(words, ahead)
                or words[ahead].text in _SPANS
                or words[ahead].text in _SPANS_BESIDE
                or words[ahead].text in _PARTS
                or _number(words, ahead) is not None
                # "/h" is read at its letter, which follows the sign.
                or (word == "/" and words[ahead].text == "h")
            )
            if not known:
                return OTHER
    return None


def _sentence_period(words: list[_Word]) -> str | None:
    """The span of time a sentence names, for an amount that names none of its own: another span
    where any word of the sentence is one's, an hour where every such word is an hour's, else
    None."""
    found = {_hour_said(words, index) for index in range(len(words)) if _is_hour(words, index)}
    found |= {OTHER for word in words if word.text in _SPANS}
    return OTHER if OTHER in found else HOUR if found else None


def _reports(words: list[_Word]) -> bool:
    """Whether a sentence reports what was: its amounts are then not figures asked for."""
    texts = [word.text for word in words]
    return (
        any(text in _REPORT for text in texts)
        or any(text in _COST and following in _TO_WHOM for text, following in pairwise(texts))
        or any(pair == ("so", "far") for pair in pairwise(texts))
    )


def stated(utterance: str, names: Sequence[str] = ()) -> tuple[str, ...]:
    """The budgets with no figure that ``utterance`` states in its own words: :data:`NOTHING`,
    :data:`DEFAULT`, both or neither. A sentence that speaks of no limit states neither; a word
    inside an amount states nothing ("zero dollars" is an amount), nor does a word inside one of
    ``names`` (see :func:`shape_of`); and "off", "stop" and "none" said of a limit or the budget
    itself take a limit away and state neither."""
    words, _found, spans, _named = _read(utterance, names)
    inside = {index for start, after in spans for index in range(start, after)}
    texts = [word.text for index, word in enumerate(words) if index not in inside]
    pairs = list(pairwise(texts))
    if any(text in _NO_LIMIT for text in texts) or any(
        (first in ("no", "without", "any") and second in _LIMITS)
        or (first, second) == ("as", "much")
        for first, second in pairs
    ):
        return ()
    found = []
    limited = any(text in _LIMITED for text in texts)
    if any(text in _SAYS_NOTHING and not (limited and text in _TAKES_AWAY) for text in texts):
        found.append(NOTHING)
    if any(text in _SAYS_DEFAULT for text in texts) or any(
        first in ("starts", "started", "start") and second == "with" for first, second in pairs
    ):
        found.append(DEFAULT)
    return tuple(found)


def _hour_unit(words: list[_Word], at: int, taken: Set[int]) -> int | None:
    """Where the hour said from ``words[at]`` ends, or None where no hour a budget is by is said
    there: one word that makes a rate ("an", "per", "every", "each", "in", "/") with the words
    that may follow it ("any", "one"), then an hour word that is one real hour, then "of real
    time" where it is said. The bare word ("hourly", "hour") is the hour too."""
    index = at
    if index < len(words) and index not in taken and words[index].text in _HOUR_RATE:
        index += 1
        while index < len(words) and index not in taken and words[index].text in _HOUR_FILLERS:
            index += 1
    if index >= len(words) or index in taken or not _is_hour(words, index):
        return None
    if _hour_said(words, index) != HOUR:
        return None
    index += 1
    if [word.text for word in words[index : index + 3]] == ["of", "real", "time"]:
        index += 3
    return index


@dataclass(frozen=True, slots=True)
class _Shape:
    """One shape: its key, what it plans, its pattern's elements in order, and whether it may be
    the budget's clause after another step's names."""

    key: str
    budget: str
    elements: tuple[tuple[str, str, bool], ...]
    after_names: bool


@cache
def _shapes() -> tuple[
    tuple[_Shape, ...], Mapping[str, tuple[tuple[str, ...], ...]], Mapping[str, str]
]:
    """The shapes, each slot's phrases as their words in order, longest first, and the direction
    a word of the move slot says, where it says one."""
    document = json.loads(SHAPES.read_text(encoding="utf-8"))
    slots: dict[str, tuple[tuple[str, ...], ...]] = {}
    directions: dict[str, str] = {}
    shapes: list[_Shape] = []
    for entry in document["entries"]:
        if entry["kind"] == "slot":
            phrases = {tuple(text.split()) for text in entry["words"]}
            # An empty entry would match nothing and still count as its slot filled.
            if any(not phrase for phrase in phrases) or any(
                _TOKEN.fullmatch(word) is None for phrase in phrases for word in phrase
            ):
                raise ValueError(
                    f"{SHAPES.name}: slot {entry['name']} holds a word this cannot read"
                )
            slots[entry["name"]] = tuple(sorted(phrases, key=len, reverse=True))
            stated = entry.get("direction", {})
            if entry["name"] != _MOVE and stated:
                raise ValueError(f"{SHAPES.name}: only the move slot states a direction")
            if any(way not in (UP, DOWN) or (word,) not in phrases for word, way in stated.items()):
                raise ValueError(
                    f"{SHAPES.name}: a direction is up or down, of a word of its own slot"
                )
            directions.update(stated)
    for entry in document["entries"]:
        if entry["kind"] != "shape":
            continue
        elements = []
        for written in entry["pattern"].split():
            optional = written.endswith("?")
            name = written.removesuffix("?")
            if name in ("AMOUNTS", "FROM_TO"):
                elements.append((name, "", optional))
            elif name.startswith("<") and name.endswith(">"):
                if name[1:-1] not in slots:
                    raise ValueError(f"{SHAPES.name}: {entry['name']} names no such slot: {name}")
                elements.append(("slot", name[1:-1], optional))
            else:
                elements.append(("word", name, optional))
        shapes.append(_Shape(entry["name"], entry["budget"], tuple(elements), entry["after_names"]))
    return tuple(shapes), slots, directions


def _units(
    words: list[_Word], spans: Sequence[tuple[int, int]], named: Sequence[tuple[int, int]]
) -> list[tuple[str, str]]:
    """The sentence as what a shape is made of, in order: each amount, each name, the hour where
    it is said, and every other token as the word it is."""
    amount_at = {start: after for start, after in spans}
    name_at = {start: after for start, after in named}
    taken = {index for start, after in (*spans, *named) for index in range(start, after)}
    units: list[tuple[str, str]] = []
    index = 0
    while index < len(words):
        if index in amount_at:
            units.append(("amount", ""))
            index = amount_at[index]
        elif index in name_at:
            units.append(("name", ""))
            index = name_at[index]
        elif (ends := _hour_unit(words, index, taken)) is not None:
            units.append(("hour", ""))
            index = ends
        else:
            units.append(("word", words[index].text))
            index += 1
    return units


def _fits(
    shape: _Shape,
    units: Sequence[tuple[str, str]],
    slots: Mapping[str, tuple[tuple[str, ...], ...]],
) -> tuple[bool, frozenset[str], int]:
    """Whether ``units``, whole and in order, are ``shape``; the slots it filled; and how far
    into the sentence the furthest try reached."""
    furthest = 0

    def amounts_from(at: int) -> list[tuple[int, bool]]:
        """Every place the amounts said from ``at`` may end, and whether they are a choice: one
        amount, or two with or without "and" between them, or two with "or" or "to" between
        them (a choice), each with the hour after it where it is said."""
        ends: list[tuple[int, bool]] = []

        def one(index: int) -> list[int]:
            if index >= len(units) or units[index][0] != "amount":
                return []
            index += 1
            return (
                [index + 1, index] if index < len(units) and units[index][0] == "hour" else [index]
            )

        for first in one(at):
            ends.append((first, False))
            join = units[first][1] if first < len(units) and units[first][0] == "word" else ""
            if join in _CHOICE_JOINS:
                ends.extend((end, True) for end in one(first + 1))
                continue
            joined = first + 1 if join == "and" else first
            for start in dict.fromkeys((joined, first)):
                ends.extend((end, False) for end in one(start))
        return ends

    def go(element: int, at: int, filled: frozenset[str]) -> frozenset[str] | None:
        nonlocal furthest
        furthest = max(furthest, at)
        if element == len(shape.elements):
            return filled if at == len(units) else None
        kind, name, optional = shape.elements[element]
        ends: list[tuple[int, frozenset[str]]] = []
        if kind == "AMOUNTS":
            ends = [
                (end, filled | {_CHOSEN} if choice else filled) for end, choice in amounts_from(at)
            ]
        elif kind == "FROM_TO":
            # "from" an amount "to" an amount, with the hour after the second where it is said.
            if units[at : at + 2] == [("word", "from"), ("amount", "")] and units[
                at + 2 : at + 4
            ] == [("word", "to"), ("amount", "")]:
                end = at + 4
                ends = [(end, filled)]
                if end < len(units) and units[end][0] == "hour":
                    ends.insert(0, (end + 1, filled))
        elif kind == "word":
            if at < len(units) and units[at] == ("word", name):
                ends = [(at + 1, filled)]
        else:
            for phrase in slots[name]:
                reach = units[at : at + len(phrase)]
                if [unit for unit in reach] == [("word", word) for word in phrase]:
                    ends.append((at + len(phrase), filled | {name}))
        for end, now_filled in ends:
            found = go(element + 1, end, now_filled)
            if found is not None:
                return found
        return go(element + 1, at, filled) if optional else None

    filled = go(0, 0, frozenset())
    return filled is not None, filled or frozenset(), furthest


def shape_of(utterance: str, names: Sequence[str] = ()) -> tuple[str | None, str | None, str]:
    """The shape the whole of ``utterance`` has, in order: its key and what it plans
    (:data:`AMOUNTS`, :data:`FROM_TO`, :data:`NOTHING` or :data:`DEFAULT`; :data:`CHOICE` where
    its amounts are a choice, which plans nothing and chooses the question; an amount kind is
    followed by ``:up`` or ``:down`` where a move word says which way), or ``(None, None)``
    with the word no shape gets past. A sentence is planned only where this names a shape.

    ``names`` are names code holds for what another step of the same request acts on (a being,
    a kind, a model, by the words the form listed). They may stand only in that step's own
    clause, before the "and" that opens the budget's clause, among the few words such a clause
    holds; and the budget's clause must then be a shape that says whose figure it is, by a
    subject of the closed list, and hold no pronoun ("it", "its", "their"), which after a name
    points at what was named. A name counts only whole and in order, as written; each word is
    taken by one reading, and a number inside a name is never an amount."""
    words, _found, spans, named = _read(utterance, names)
    units = _units(words, spans, named)
    shapes, slots, directions = _shapes()
    clause = 0
    after_names = False
    if any(kind == "name" for kind, _text in units):
        # Another step's clause: names and its own few words, up to the first "and"; nothing
        # after that "and" may be a name.
        join = next((at for at, unit in enumerate(units) if unit == ("word", "and")), None)
        other = {phrase[0] for phrase in slots[_OTHER_STEP]}
        opening = units[: join or 0]
        if (
            join is None
            or not any(kind == "name" for kind, _text in opening)
            or any(
                kind != "name" and (kind != "word" or text not in other) for kind, text in opening
            )
        ):
            stopped = next(
                (text or kind for kind, text in opening if kind != "name" and text not in other),
                "and" if join is not None else "a name",
            )
            return None, None, stopped
        clause, after_names = join + 1, True
    rest = units[clause:]
    if after_names:
        # A pronoun after names points at what was just named: no clause that holds one says
        # whose figure it is.
        back = next((text for kind, text in rest if kind == "word" and text in _POINTS_BACK), None)
        if back is not None:
            return None, None, back
    furthest = 0
    for shape in shapes:
        if after_names and not shape.after_names:
            continue
        fits, filled, reached = _fits(shape, rest, slots)
        furthest = max(furthest, reached)
        if fits and (not after_names or _SAYS_WHOSE & filled):
            if _CHOSEN in filled:
                return shape.key, CHOICE, ""
            # A move word that says a way is the first of the clause's words that says one.
            way = (
                next((directions[text] for kind, text in rest if text in directions), None)
                if _MOVE in filled
                else None
            )
            return shape.key, shape.budget if way is None else f"{shape.budget}:{way}", ""
    if furthest < len(rest):
        kind, text = rest[furthest]
        return None, None, text or f"the {kind}"
    return None, None, "the end of the sentence"


def _is_number(words: list[_Word], at: int) -> bool:
    return 0 <= at < len(words) and _number(words, at) is not None


def _ends_a_number(words: list[_Word], end: int) -> bool:
    """Whether a number, in digits or in words, ends right before ``words[end]``."""
    return any(
        (read := _number(words, at) or _article(words, at)) is not None and read[1] == end
        for at in range(max(0, end - 6), end)
    )


def _adjacent(words: list[_Word], end: int, begin: int) -> bool:
    """Whether the words that begin at ``begin`` follow those that end at ``end`` directly, or
    across one "and"."""
    return begin == end or (begin == end + 1 and words[end].text == "and")


def amounts(utterance: str, names: Sequence[str] = ()) -> tuple[Amount, ...]:
    """Every amount ``utterance`` states, in the order it states them; no word inside one of
    ``names`` (see :func:`shape_of`) is read as part of one."""
    return _read(utterance, names)[1]


def _read(
    utterance: str, names: Sequence[str] = ()
) -> tuple[list[_Word], tuple[Amount, ...], list[tuple[int, int]], list[tuple[int, int]]]:
    """``utterance`` as its words, the amounts it states in order, for each amount (the first
    end of a range in digits among them) the words it spans, from its first to past its last,
    and the words each of ``names`` spans where the sentence says it whole. The words of a name
    are read as nothing else: they are blank to every rule below."""
    lowered = utterance.lower()
    words = [_Word(match.group(), match.start(), match.end()) for match in _TOKEN.finditer(lowered)]
    named: list[tuple[int, int]] = []
    held: set[int] = set()
    # The longest name first, so a name inside another does not take its words.
    for name in sorted(dict.fromkeys(names), key=len, reverse=True):
        parts = [match.group() for match in _TOKEN.finditer(name.lower())]
        for at in range(len(words) - len(parts) + 1 if parts else 0):
            reach = range(at, at + len(parts))
            if not held.intersection(reach) and [words[index].text for index in reach] == parts:
                held.update(reach)
                named.append((at, at + len(parts)))
    for index in held:
        words[index] = _Word("", words[index].start, words[index].end)
    shared = _sentence_period(words)
    report = _reports(words)
    #: Each amount read, with the words it spans: where it starts and where it ends.
    #: With where its number's own digits or words end.
    read_at: list[tuple[int, int, str, Decimal, int]] = []
    index = 0
    while index < len(words):
        read = _number(words, index) or _article(words, index)
        if read is None:
            index += 1
            continue
        value, after = read
        digits_end = after
        before = words[index - 1].text if index > 0 else ""
        unit: str | None = None
        start = index
        if before == "$" or (before == "usd" and _DIGITS.fullmatch(words[index].text)):
            unit = USD
            start = index - 1
            if after < len(words) and words[after].text in _DOLLARS:
                after += 1
        else:
            counted = after
            while counted < len(words) and words[counted].text in _COUNT_FILLERS:
                counted += 1
            following = words[after].text if after < len(words) else ""
            glued = after < len(words) and words[after].start == words[after - 1].end
            if following in _DOLLARS:
                unit, after = USD, after + 1
            elif following in _CENTS or (following == "c" and glued):
                unit, value, after = USD, value / 100, after + 1
            elif (
                counted < len(words)
                and words[counted].text in _COUNTED
                # "Decisions" is a count wherever it stands. An answer, an ask, a call or a
                # question is one only with the hour right beside it, as "times" is: "One
                # question: ..." opens a sentence and counts nothing.
                and (
                    words[counted].text in ("decision", "decisions")
                    or _hour_unit(words, counted + 1, frozenset()) is not None
                )
            ):
                unit, after = DECISIONS, counted + 1
            elif following == "times" and _own_period(words, after + 1, frozenset()) is not None:
                unit, after = DECISIONS, after + 1
        if unit is None:
            index = after
            continue
        whole = value == value.to_integral_value()
        if (unit == DECISIONS and not whole) or value != value.quantize(_MICRO):
            index = after
            continue
        read_at.append((start, after, unit, value, digits_end))
        index = after
    starts = frozenset(item[0] for item in read_at)
    ends = {item[1] for item in read_at}
    found: list[Amount] = []
    spans: list[tuple[int, int]] = []
    for position, (start, after, unit, value, digits_end) in enumerate(read_at):
        period = _own_period(words, after, starts) or shared
        said = lowered[words[start].start : words[after - 1].end]
        joined = start > 0 and words[start - 1].text in _BETWEEN
        # A number in digits two words back, joined by "to", "or" or "and" and counting nothing
        # itself, shares this amount's unit: a range or a choice, read as two amounts.
        earlier = start - 2
        ranged = (
            joined
            and earlier >= 0
            and _DIGITS.fullmatch(words[earlier].text) is not None
            and (earlier + 1) not in ends
            and not (earlier > 0 and words[earlier - 1].text == "$")
        )
        if ranged:
            other = Decimal(words[earlier].text.replace(",", ""))
            other = other / 100 if said.endswith(("cent", "cents", "c", "¢")) else other
            if other == other.quantize(_MICRO) and (unit == USD or other == int(other)):
                spans.append((earlier, earlier + 1))
                found.append(
                    Amount(
                        unit,
                        other,
                        period,
                        words[earlier].text,
                        unclear=report,
                        was=earlier > 0 and words[earlier - 1].text == "from",
                    )
                )
        # After the amount and the period said with it: a word that makes it a change.
        tail = after
        while tail < len(words) and tail < after + _REACH and not _is_number(words, tail):
            if words[tail].text in _CHANGE_AFTER:
                break
            if _is_hour(words, tail) or words[tail].text in _SPANS:
                tail += 1
                break
            tail += 1
        changed = (start > 0 and words[start - 1].text in _CHANGE_BEFORE) or (
            tail < len(words) and words[tail].text in _CHANGE_AFTER
        )
        # More of a number said beside it than was read: digits or number words directly
        # before or after that belong to no amount, or letters stuck to its digits ("1.5k").
        stuck = (
            digits_end < len(words)
            and words[digits_end].start == words[digits_end - 1].end
            and words[digits_end].text.isalpha()
            and words[digits_end].text != "c"
            and _DIGITS.fullmatch(words[digits_end - 1].text) is not None
        )
        beside = (_is_number(words, after) and after not in starts) or (
            _is_number(words, start - 1) and start not in ends
        )
        # Joined to more of a number by "and", "to" or "or": a number in words before the join
        # ("one hundred and twenty", "fifty to sixty"), or after it a number that starts no
        # amount of its own, or a half ("a dollar and a half", "2 dollars or 3").
        behind = after + 1
        if behind < len(words) and words[behind].text in ("a", "an"):
            behind += 1
        parted = (
            joined and not ranged and (start - 1) not in ends and _ends_a_number(words, start - 1)
        ) or (
            after < len(words)
            and words[after].text in _BETWEEN
            and after + 1 < len(words)
            and (
                (_is_number(words, after + 1) and (after + 1) not in starts)
                or (behind < len(words) and words[behind].text in _PARTS)
            )
        )
        # A sum of parts: an amount of the same unit right after this one, or across "and"
        # ("a dollar and 25 cents", "1 dollar 25 cents"), on either side.
        summed = (
            position + 1 < len(read_at)
            and read_at[position + 1][2] == unit
            and _adjacent(words, after, read_at[position + 1][0])
        ) or (
            position > 0
            and read_at[position - 1][2] == unit
            and _adjacent(words, read_at[position - 1][1], start)
        )
        # Dollars of another country: a letter stuck before the sign, or its name said after.
        foreign = unit == USD and (
            (
                words[start].text == "$"
                and start > 0
                and words[start - 1].end == words[start].start
                and words[start - 1].text.isalpha()
                and words[start - 1].text != "us"
            )
            or any(word.text in _OTHER_DOLLARS for word in words[after : after + 2])
        )
        found.append(
            Amount(
                unit,
                value,
                period,
                said,
                unclear=report or changed or stuck or beside or parted or summed or foreign,
                was=start > 0 and words[start - 1].text == "from",
            )
        )
        spans.append((start, after))
    return words, tuple(found), spans, named


# -- from the amounts a sentence states to a budget's two figures -----------------------------


def usd_text(value: Decimal) -> str:
    """Dollars as a budget's row states them: six decimals."""
    return str(value.quantize(_MICRO))


def title(amount: Amount) -> str:
    """An amount as the drafter is shown it: the figure, what it counts and its period."""
    if amount.unit == USD:
        cents = amount.value.quantize(Decimal("0.01"))
        figure = f"{cents if cents == amount.value else amount.value.normalize():f} US dollars"
    else:
        figure = f"{int(amount.value)} model decisions"
    if amount.unclear:
        return f"{figure}, which the words do not state plainly as the amount"
    if amount.period == HOUR:
        return f"{figure} an hour"
    if amount.period == OTHER:
        return f"{figure}, over a span that is not an hour"
    return figure


def figure_title(figure: str, value: str) -> str:
    """One of a budget's two figures in the words an amount is listed with."""
    unit = USD if figure == "usd_per_hour" else DECISIONS
    return title(Amount(unit, Decimal(value), HOUR, ""))


@dataclass(frozen=True, slots=True)
class Resolved:
    """A budget's two figures as a sentence's amounts give them, or what to ask first.

    ``named`` are the figures the words named; one they did not name is the world's own now.
    ``question`` is ``budget_required`` where the words name no figure, ``budget_period`` where
    they give an amount a span that is not an hour, and ``budget_ambiguous`` where they name two
    amounts of one kind, with ``slot`` the figure asked about and ``candidates`` its amounts."""

    usd_per_hour: str | None
    decisions_per_hour: int | None
    named: tuple[str, ...] = ()
    question: str | None = None
    slot: str | None = None
    candidates: tuple[str, ...] = ()


def resolve(
    found: Sequence[Amount],
    fixed: Sequence[str],
    now: Mapping[str, Any],
    default: Mapping[str, Any],
    said: Sequence[str] = (),
    shape: str | None = None,
) -> Resolved:
    """The budget a sentence asks for, from the amounts code read in it (``found``), the fixed
    budgets its draft named (``fixed``: :data:`NOTHING`, :data:`DEFAULT`), the fixed budgets the
    sentence's own words state (``said``, from :func:`stated`), what the shape of the whole
    sentence plans (``shape``, from :func:`shape_of`: None where it is no shape; with the way
    a move word says the figure goes, where it says one), the world's budget ``now`` and the
    ``default`` a world starts with.

    A budget is planned only where the whole sentence, in order, is one of the shapes and
    nothing is left to ask. What is doubtful only chooses the question: an unclear amount, an
    amount over another span and two amounts of one kind are each asked about by name. An amount
    is never converted. A fixed budget is planned only where the sentence is a shape of that
    budget, the draft names it, the sentence's own words state it and no other, and no amount
    stands beside it. An amount said after "from" is what the budget is moved from: it is set
    aside where it is the budget now ("from 25 cents to 50 cents"), and alone it is no figure."""
    held_usd = str(now["usd_per_hour"])
    held_decisions = int(now["decisions_per_hour"])
    shape, _, way = (shape or "").partition(":")
    shape = shape or None
    if any(amount.unclear for amount in found):
        # A change, a report, a part of a sum, or a figure with more said beside it than code
        # read: the figure is asked for.
        return Resolved(None, None, question="budget_required")
    if any(amount.period == OTHER for amount in found):
        return Resolved(None, None, question="budget_period")
    if shape is None or (found and said):
        # A sentence that is none of the shapes, or the sentence's own word for nothing or the
        # default beside an amount: the figure is asked for, whatever the draft names.
        return Resolved(None, None, question="budget_required")
    chosen = list(dict.fromkeys(name for name in fixed if name in (NOTHING, DEFAULT)))
    if chosen:
        # A budget with no figure is the sentence's own shape and word for it, alone: with an
        # amount read beside it, or another budget than the draft's, the figure is asked for.
        if found or len(chosen) != 1 or tuple(said) != (chosen[0],) or shape != chosen[0]:
            return Resolved(None, None, question="budget_required")
        if chosen == [NOTHING]:
            return Resolved(usd_text(Decimal(0)), 0, FIGURES)
        return Resolved(str(default["usd_per_hour"]), int(default["decisions_per_hour"]), FIGURES)

    def distinct(unit: str, held: Decimal) -> list[Decimal]:
        of_unit = [amount for amount in found if amount.unit == unit]
        values = list(dict.fromkeys(amount.value for amount in of_unit))
        if len(values) > 1:
            # What the budget is changed from, where that is the budget now, is not a figure
            # asked for.
            left = {amount.value for amount in of_unit if amount.was and amount.value == held}
            values = [value for value in values if value not in left] or values
        return values

    if shape not in (AMOUNTS, FROM_TO, CHOICE):
        # A shape of nothing or of the default that the draft did not name plans no amount.
        return Resolved(None, None, question="budget_required")
    for unit in (USD, DECISIONS):
        of_unit = [amount for amount in found if amount.unit == unit]
        if len(of_unit) == 1 and of_unit[0].was:
            # What the budget is moved from, with nothing said of where to: no figure.
            return Resolved(None, None, question="budget_required")
    dollars = distinct(USD, Decimal(held_usd))
    counts = distinct(DECISIONS, Decimal(held_decisions))
    if not dollars and not counts:
        return Resolved(None, None, question="budget_required")
    if len(dollars) > 1 and len(counts) > 1:
        # Two questions at once are asked as one: both figures.
        return Resolved(None, None, question="budget_required")
    if shape == CHOICE and (len(dollars) > 1) == (len(counts) > 1):
        # A choice the sentence offers is never planned: where it is not between two amounts of
        # one kind (dollars or a count, the same amount twice), the figure is asked for.
        return Resolved(None, None, question="budget_required")
    named = tuple(
        figure for figure, values in zip(FIGURES, (dollars, counts), strict=True) if values
    )
    usd = usd_text(dollars[0]) if dollars else held_usd
    decisions = int(counts[0]) if counts else held_decisions
    if len(dollars) > 1:
        return Resolved(
            None,
            decisions,
            named,
            "budget_ambiguous",
            "usd_per_hour",
            tuple(usd_text(value) for value in dollars),
        )
    if len(counts) > 1:
        return Resolved(
            usd,
            None,
            named,
            "budget_ambiguous",
            "decisions_per_hour",
            tuple(str(int(value)) for value in counts),
        )
    # A word that says which way the figure moves is held to it: down to more than the budget
    # is now, or up to less, is asked about. A figure equal to the budget's moves nothing.
    moved = [
        (Decimal(new), Decimal(held))
        for new, held, values in (
            (usd, held_usd, dollars),
            (decisions, held_decisions, counts),
        )
        if values
    ]
    if (way == UP and any(new < held for new, held in moved)) or (
        way == DOWN and any(new > held for new, held in moved)
    ):
        return Resolved(None, None, question="budget_required")
    return Resolved(usd, decisions, named)


# -- the step: the route's request and what the sheet says before the yes ----------------------


class Budgets(Protocol):
    """A world's budget for its minds, as the actions route hands it to the planner
    (``exulanica.api.mind_offer.WorldMinds``): the budget now beside what a world starts with,
    and what a budget asked for would come to here, recording nothing."""

    role_key: str
    #: The account that asks, where the caller is one: part of a planned budget's key.
    actor: uuid.UUID | None

    def budget(self) -> Mapping[str, Any]: ...

    def budget_sheet(
        self, usd_per_hour: str, decisions_per_hour: int, beings: int | None
    ) -> Mapping[str, Any]: ...


def budget_key(
    world_id: str,
    role_key: str,
    budget_seq: int | None,
    usd_per_hour: str,
    decisions_per_hour: int,
    actor: uuid.UUID | None = None,
) -> uuid.UUID:
    """The key a planned budget is sent with: the same plan sent twice answers the record it
    made, and the same words asked again after any other setting are a new request, since the
    world's newest budget is part of it; so is the account that asks, as the record refuses a key
    another account used."""
    asker = "" if actor is None else f"|{actor}"
    return uuid.uuid5(
        uuid.UUID(int=0),
        f"{world_id}|{role_key}|{budget_seq or 0}|{usd_per_hour}|{decisions_per_hour}"
        f"|minds-budget{asker}",
    )


@dataclass(frozen=True, slots=True)
class PreparedBudget:
    """A budget as a step states it: the request, or the code that blocks it, and every figure
    the sheet says before the yes."""

    body: dict[str, Any] | None
    code: str | None
    facts: dict[str, Any]
    pins: dict[str, Any]


def prepare(
    budgets: Budgets,
    *,
    world_id: str,
    usd_per_hour: str,
    decisions_per_hour: int,
    named: Sequence[str],
    beings: int | None,
) -> PreparedBudget:
    """The budget ``usd_per_hour`` and ``decisions_per_hour`` for this world's minds, as the
    budget route would take it now, held to the budget the world has now: sent after anybody
    sets another, it is refused (``budget_changed``). Blocked with ``no_change`` where the
    world's budget already reads both figures. Setting a budget asks no model and spends
    nothing."""
    sheet = dict(budgets.budget_sheet(usd_per_hour, decisions_per_hour, beings))
    now = sheet["now"]
    facts = {**sheet, "named": [figure for figure in FIGURES if figure in named]}
    pins = {"budget_seq": now.get("budget_seq")}
    if (
        Decimal(str(now["usd_per_hour"])) == Decimal(usd_per_hour)
        and int(now["decisions_per_hour"]) == decisions_per_hour
    ):
        return PreparedBudget(None, "no_change", facts, pins)
    body = {
        "idempotency_key": str(
            budget_key(
                world_id,
                budgets.role_key,
                now.get("budget_seq"),
                usd_per_hour,
                decisions_per_hour,
                budgets.actor,
            )
        ),
        "usd_per_hour": usd_per_hour,
        "decisions_per_hour": decisions_per_hour,
        # The budget this plan was made against: a figure the words did not name is the
        # world's as it stood then, so a budget set since refuses this one instead of being
        # put back by it.
        "after_budget_seq": int(now.get("budget_seq") or 0),
    }
    return PreparedBudget(body, None, facts, pins)
