"""The amounts code reads from a person's sentence for a world's budget for its minds.

Every expected figure is written here by hand from the sentence beside it, never computed by the
reader under test.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from exulanica.selection import action_budget as budget
from exulanica.selection.action_budget import (
    DECISIONS,
    DEFAULT,
    HOUR,
    NOTHING,
    OTHER,
    USD,
    amounts,
    resolve,
    shape_of,
    stated,
)


def _read(sentence: str) -> list[tuple[str, Decimal, str | None]]:
    return [(found.unit, found.value, found.period) for found in amounts(sentence)]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Let this town spend up to 50 cents an hour on minds.", [(USD, Decimal("0.5"), HOUR)]),
        ("Set the minds budget to $0.50 per hour", [(USD, Decimal("0.50"), HOUR)]),
        ("minds may cost 2 dollars an hour", [(USD, Decimal(2), HOUR)]),
        ("the town can spend USD 1.25 hourly on AI", [(USD, Decimal("1.25"), HOUR)]),
        ("spend at most half a dollar an hour on the minds", [(USD, Decimal("0.5"), HOUR)]),
        ("let the minds spend a dollar an hour", [(USD, Decimal(1), HOUR)]),
        ("up to twenty five cents an hour for minds", [(USD, Decimal("0.25"), HOUR)]),
        ("cap the minds at 75c an hour", [(USD, Decimal("0.75"), HOUR)]),
        ("3 bucks an hour for the AI minds", [(USD, Decimal(3), HOUR)]),
        ("$1,000.50 an hour", [(USD, Decimal("1000.50"), HOUR)]),
    ],
)
def test_dollars_by_the_hour_are_read_exactly(
    sentence: str, expected: list[tuple[str, Decimal, str | None]]
) -> None:
    assert _read(sentence) == expected


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Let the minds make 1000 decisions an hour", [(DECISIONS, Decimal(1000), HOUR)]),
        ("allow 1,200 model decisions per hour", [(DECISIONS, Decimal(1200), HOUR)]),
        ("at most two thousand answers an hour", [(DECISIONS, Decimal(2000), HOUR)]),
        ("the models may be asked 900 times an hour", [(DECISIONS, Decimal(900), HOUR)]),
        ("a hundred AI calls an hour is enough", [(DECISIONS, Decimal(100), HOUR)]),
    ],
)
def test_decisions_by_the_hour_are_read(
    sentence: str, expected: list[tuple[str, Decimal, str | None]]
) -> None:
    assert _read(sentence) == expected


def test_both_figures_of_one_sentence_share_the_hour_it_names_once() -> None:
    assert _read("Let the town spend 50 cents and 2000 decisions an hour on minds") == [
        (USD, Decimal("0.5"), HOUR),
        (DECISIONS, Decimal(2000), HOUR),
    ]


def test_an_hour_named_before_the_amount_is_its_period() -> None:
    assert _read("Each hour the minds may spend 40 cents") == [(USD, Decimal("0.4"), HOUR)]


def test_an_amount_with_no_period_states_none() -> None:
    assert _read("Give the minds a budget of 2 dollars") == [(USD, Decimal(2), None)]


@pytest.mark.parametrize(
    "sentence",
    [
        "Let the minds spend 5 dollars a day",
        "The town may spend 10 dollars a week on minds",
        "minds can cost 3 dollars in all",
        "spend 1 cent a minute on minds",
        "20 dollars in total for the minds",
    ],
)
def test_another_period_is_kept_as_another_and_never_converted(sentence: str) -> None:
    [found] = amounts(sentence)
    assert found.period == OTHER
    assert found.unit == USD


def test_the_words_an_amount_was_read_from_are_the_persons_own() -> None:
    [found] = amounts("Let this town spend up to 50 cents an hour on minds.")
    assert found.words == "50 cents"
    [dollars] = amounts("Set it to $0.50 per hour")
    assert dollars.words == "$0.50"


@pytest.mark.parametrize(
    "sentence",
    [
        "Put 2 benches by the well",
        "Give 3 knights Nemotron 3 Nano 30B",
        "Move on five minutes",
        "Let Qwen3 235B Instruct decide for everyone",
        "Play at speed 4",
        "Make it twice as fast, 2 times",
        "Let the minds spend more",
        "No limit on the minds",
    ],
)
def test_a_number_that_counts_no_money_and_no_decisions_is_no_amount(sentence: str) -> None:
    assert amounts(sentence) == ()


def test_a_figure_a_row_cannot_hold_is_no_amount() -> None:
    # Seven decimals of a dollar: more than a budget's row states.
    assert amounts("spend 0.0000001 dollars an hour") == ()
    # Half a decision is no count.
    assert amounts("allow 2.5 decisions an hour") == ()


def test_two_amounts_of_one_unit_are_both_read_in_order() -> None:
    assert _read("Raise the minds budget from 25 cents to 50 cents an hour") == [
        (USD, Decimal("0.25"), HOUR),
        (USD, Decimal("0.5"), HOUR),
    ]


def test_zero_is_an_amount() -> None:
    assert _read("Spend $0 an hour on minds") == [(USD, Decimal(0), HOUR)]
    assert _read("zero decisions an hour") == [(DECISIONS, Decimal(0), HOUR)]


@pytest.mark.parametrize(
    "sentence",
    [
        # A change, not the figure.
        "Raise the minds budget by 50 cents an hour",
        "Give the minds another dollar an hour",
        "Let the minds spend 20 cents more an hour",
        "Let the minds spend 20 cents an hour more",
        "Allow 200 decisions more an hour",
        # More of a number said beside the amount than code read.
        "Let the minds spend a dollar fifty an hour",
        "Let the minds spend 2 dollars 50 an hour",
        "Spend two fifty dollars an hour on minds",
        "The minds can have $1.5k an hour",
        "Allow 600k decisions an hour",
    ],
)
def test_a_figure_the_words_do_not_state_plainly_is_never_read_as_the_amount(sentence: str) -> None:
    # Unclear, or not read at all: either way no plain amount stands, and the figure is asked for.
    found = amounts(sentence)
    assert all(amount.unclear for amount in found), found


def test_an_unclear_amount_is_marked_so_the_drafter_s_listing_says_it() -> None:
    for sentence in (
        "Raise the minds budget by 50 cents an hour",
        "Let the minds spend a dollar fifty an hour",
        "The minds can have $1.5k an hour",
    ):
        found = amounts(sentence)
        assert found and all(amount.unclear for amount in found), (sentence, found)


@pytest.mark.parametrize(
    "sentence",
    [
        "Raise the minds budget to 50 cents an hour",
        "Let the minds spend 50 cents and 2000 decisions an hour",
        "Set it to $2 3000 decisions an hour",
        "no more than 50 cents an hour for the minds",
        "Give 3 knights a mind and let the minds spend 50 cents an hour",
    ],
)
def test_a_plainly_stated_figure_is_not_unclear(sentence: str) -> None:
    found = amounts(sentence)
    assert found and not any(amount.unclear for amount in found), found


def test_a_range_is_two_amounts_of_one_unit() -> None:
    assert _read("Let the minds spend 50 to 60 cents an hour") == [
        (USD, Decimal("0.5"), HOUR),
        (USD, Decimal("0.6"), HOUR),
    ]
    assert _read("Allow 500 or 800 decisions an hour") == [
        (DECISIONS, Decimal(500), HOUR),
        (DECISIONS, Decimal(800), HOUR),
    ]


def test_an_hour_of_the_world_s_own_time_is_another_span() -> None:
    [found] = amounts("Let the minds spend 50 cents per simulated hour")
    assert found.period == OTHER
    [game] = amounts("50 cents every game hour for the minds")
    assert game.period == OTHER


@pytest.mark.parametrize(
    ("words", "value"),
    [
        ("twenty five", 25),
        ("five hundred", 500),
        ("two thousand five hundred", 2500),
        ("nineteen", 19),
        ("ninety nine", 99),
        ("one hundred twenty", 120),
    ],
)
def test_number_words_are_read_as_one_number(words: str, value: int) -> None:
    assert _read(f"allow {words} decisions an hour") == [(DECISIONS, Decimal(value), HOUR)]


# -- the rule: ask unless the sentence leaves nothing to ask -------------------------------------
#
# Each sentence below is one a reading of this module found planned as a budget the person did
# not state. Held here at the reader and at what the planner makes of it: a question, never a
# figure. ``NOW`` is the world's budget, which is also what a world starts with.

NOW = {"usd_per_hour": "0.250000", "decisions_per_hour": 600}


def _asked(sentence: str, fixed: tuple[str, ...] = ()) -> str | None:
    """The question the planner asks of ``sentence`` where its draft named ``fixed``, or None
    where a budget is planned."""
    return resolve(
        amounts(sentence), fixed, NOW, NOW, stated(sentence), shape_of(sentence)[1]
    ).question


@pytest.mark.parametrize(
    "sentence",
    [
        # A span in the plural or with a count is that span, never an hour.
        "Let the town spend 10 dollars every 24 hours",
        "$50 for 30 days",
        "20 dollars for 2 weeks",
        "5 dollars over the next few days",
        "$1 per 10 minutes",
        "5 dollars for today",
        "$0.01/min",
        "10 dollars for the next 3 hours",
        "3 dollars every two hours",
        "Let the minds spend 4 dollars in 12 hrs",
        "600 decisions every 90 mins",
        "Spend 5 dollars a night on minds",
        "20 dollars for the weekend",
        # A part of an hour.
        "2 dollars every half hour",
        "50 cents per quarter of an hour",
        # A rate over something a budget is not by.
        "50 cents a being",
        "50 cents each",
        "50 cents per mind per hour",
        "a dollar for every knight",
        "$1 per 10 turns",
        # The span is said before the amount, away from it: the sentence's span is the amount's.
        "Every 24 hr the town may spend 10 dollars",
        "For every two hour block the minds may spend 3 dollars",
        "Every half hour the minds may spend 2 dollars",
        "Every min the minds may spend 1 cent",
        "In each game hour let the minds spend 50 cents",
    ],
)
def test_an_amount_for_any_span_but_one_hour_is_asked_about_and_never_planned(sentence):
    found = amounts(sentence)
    assert found and all(amount.period == OTHER for amount in found), found
    for fixed in ((), (NOTHING,), (DEFAULT,)):
        assert _asked(sentence, fixed) is not None


@pytest.mark.parametrize(
    "sentence",
    [
        "Let this town spend up to 50 cents an hour on minds.",
        "Set it to $0.50 per hour",
        "$5 hourly for the minds",
        "Cap the minds at 50c/h",
        "USD 1.50 each hour for the minds",
        "Let the town's minds spend at most 75 cents in any one hour",
        "50 cents for the minds every hour",
        "Let the minds answer 600 times an hour",
        "Allow 300 model decisions per hour and 20 cents",
    ],
)
def test_one_hour_said_any_listed_way_is_the_hour_a_budget_is_by(sentence):
    found = amounts(sentence)
    assert found and all(amount.period == HOUR for amount in found), found
    assert not any(amount.unclear for amount in found)
    # Whom the figure is for stands before the hour in one of them: that order is no shape.
    asked = "budget_required" if sentence == "50 cents for the minds every hour" else None
    assert _asked(sentence) == asked


@pytest.mark.parametrize(
    "sentence",
    [
        "The minds cost me 3 dollars yesterday, turn them off",
        "I was charged $4, stop the AI spending",
        "I paid 2 dollars already, put the budget back to default",
        "It ran 3 dollars an hour last week, turn it off",
        "So far it has cost 2 dollars an hour, stop",
        "We spent 5 dollars an hour on minds, reset it",
        "The bill was 600 decisions an hour",
        # Each with one word of report and no other.
        "The minds cost me 3 dollars, stop them",
        "Yesterday's 3 dollars an hour, turn it off",
    ],
)
def test_a_number_that_reports_what_was_is_never_the_budget(sentence):
    found = amounts(sentence)
    assert found and all(amount.unclear for amount in found), found
    # Whatever the draft names, the plan asks for the figure.
    for fixed in ((), (NOTHING,), (DEFAULT,), (NOTHING, DEFAULT)):
        assert _asked(sentence, fixed) == "budget_required"


@pytest.mark.parametrize(
    "sentence",
    [
        "Turn the minds off, 3 dollars is too much",
        "Reset the budget, 5 dollars an hour is too high",
        "Stop at 50 cents an hour",
    ],
)
def test_a_budget_with_no_figure_named_beside_an_amount_is_asked_about(sentence):
    assert amounts(sentence)
    for fixed in ((NOTHING,), (DEFAULT,)):
        assert _asked(sentence, fixed) == "budget_required"


@pytest.mark.parametrize(
    "sentence",
    [
        # Number words joined by "and": the part code read is not the number said.
        "allow one hundred and twenty decisions an hour",
        "a hundred and fifty dollars an hour",
        "two thousand and five hundred decisions an hour",
        # A sum of parts.
        "a dollar and a half an hour",
        "a dollar and 25 cents an hour",
        "1 dollar 25 cents an hour",
        # A range or a choice said in words, or with its second number bare.
        "fifty to sixty cents an hour",
        "between one and two dollars an hour",
        "2 dollars or 3 an hour",
        "50 cents and 600",
        # A change.
        "add 50 cents",
        "take 10 cents off",
        "minus 5 dollars",
        "plus 200 decisions an hour",
        # Another country's dollars.
        "C$5 an hour",
        "A$5 an hour",
        "5 dollars Canadian an hour",
    ],
)
def test_an_amount_joined_to_more_or_changed_or_foreign_is_asked_for(sentence):
    found = amounts(sentence)
    assert found and all(amount.unclear for amount in found), found
    assert _asked(sentence) == "budget_required"


def test_a_sum_of_parts_is_asked_for_even_where_one_part_is_the_budget_now():
    # The world is at 25 cents: the part equal to it is not set aside, since nothing says "from".
    assert _asked("a dollar and 25 cents an hour") == "budget_required"
    assert _asked("25 cents or 50 cents an hour") == "budget_ambiguous"
    assert _asked("25 to 50 cents an hour") == "budget_ambiguous"


def test_only_an_amount_said_after_from_is_set_aside_and_only_where_it_is_the_budget_now():
    # Each is read as a sentence whose shape is a move from one amount to another.
    moves = budget.FROM_TO
    moved = resolve(amounts("from 25 cents to 50 cents an hour"), (), NOW, NOW, (), moves)
    assert (moved.question, moved.usd_per_hour) == (None, "0.500000")
    digits = resolve(amounts("Go from 25 to 50 cents an hour"), (), NOW, NOW, (), moves)
    assert (digits.question, digits.usd_per_hour) == (None, "0.500000")
    # The world is not at 30 cents, so both ends are asked about.
    wrong = resolve(amounts("from 30 cents to 50 cents an hour"), (), NOW, NOW, (), moves)
    assert (wrong.question, wrong.candidates) == ("budget_ambiguous", ("0.300000", "0.500000"))


def test_two_questions_at_once_are_asked_as_one():
    sentence = "two dollars or 3 dollars, and 500 decisions or 900 decisions an hour"
    asked = resolve(amounts(sentence), (), NOW, NOW, (), budget.AMOUNTS)
    # No count is taken silently while the dollars are asked about.
    assert (asked.question, asked.slot, asked.decisions_per_hour) == ("budget_required", None, None)


def test_a_comma_ends_a_number_unless_three_digits_follow_it():
    assert _read("$2, and 1,000 decisions an hour") == [
        (USD, Decimal(2), HOUR),
        (DECISIONS, Decimal(1000), HOUR),
    ]
    # "1,5" is no number this module reads: the figure is asked for.
    assert _asked("1,5 dollars an hour") == "budget_required"


@pytest.mark.parametrize(
    ("sentence", "says"),
    [
        ("Spend nothing on minds", (NOTHING,)),
        ("Turn the minds' spending off", (NOTHING,)),
        ("Stop the AI spending", (NOTHING,)),
        ("Zero for the minds", (NOTHING,)),
        ("Put the budget back to its default", (DEFAULT,)),
        ("Reset the minds budget", (DEFAULT,)),
        ("Go back to what the world starts with", (DEFAULT,)),
        ("Reset it, stop", (NOTHING, DEFAULT)),
        ("make it cheaper", ()),
        ("Let the minds spend more", ()),
        # No limit is neither, whatever else the sentence says.
        ("No limit on the minds", ()),
        ("Unlimited minds, nothing held back", ()),
        ("Let the minds spend as much as they want, nothing off the table", ()),
        ("Remove the budget, without any cap", ()),
    ],
)
def test_the_budgets_with_no_figure_are_the_sentence_s_own_words(sentence, says):
    assert stated(sentence) == says


@pytest.mark.parametrize(
    ("sentence", "fixed", "figures"),
    [
        ("Spend nothing on minds", (NOTHING,), ("0.000000", 0)),
        ("Turn the minds off", (NOTHING,), ("0.000000", 0)),
        ("Reset the minds budget", (DEFAULT,), ("0.250000", 600)),
        # The draft names one the sentence does not say: asked.
        ("Spend nothing on minds", (DEFAULT,), None),
        ("Reset the minds budget", (NOTHING,), None),
        ("No limit on the minds", (NOTHING,), None),
        ("No limit on the minds", (DEFAULT,), None),
        ("make it cheaper", (NOTHING,), None),
        ("make it cheaper", (DEFAULT,), None),
        ("Reset it, stop", (NOTHING,), None),
        ("Reset it, stop", (NOTHING, DEFAULT), None),
        # The sentence says one and the draft names neither: asked.
        ("Spend nothing on minds", (), None),
    ],
)
def test_a_budget_with_no_figure_needs_the_draft_and_the_sentence_to_name_the_same_one(
    sentence, fixed, figures
):
    held = {"usd_per_hour": "2.000000", "decisions_per_hour": 50}
    shape = shape_of(sentence)[1]
    resolved = resolve(amounts(sentence), fixed, held, NOW, stated(sentence), shape)
    if figures is None:
        assert resolved.question == "budget_required"
        assert (resolved.usd_per_hour, resolved.decisions_per_hour) == (None, None)
    else:
        assert resolved.question is None
        assert (resolved.usd_per_hour, resolved.decisions_per_hour) == figures


# -- the reader plans by shape -------------------------------------------------------------------
#
# A sentence plans a figure only where the whole of it, in order, is one of a short list of shapes
# kept as data (``assets/catalogs/minds-budget-shapes``). What follows is the table three readings
# of this module made: every sentence they found planned as a figure nobody stated, every sentence
# they traced, the sentences that were measured, and plain ones. Each row is the sentence, the names
# another step's options held for it (none for most), and what the reader comes to: a plan with its
# two figures and the shape the sentence is, or a question by its code with the shape (where the
# sentence is one and still asks) or the word no shape gets past. ``_comes_to`` reads a sentence as
# the planner does where the draft names the fixed budget the sentence itself states.


def _comes_to(sentence: str, names: tuple[str, ...] = ()) -> tuple:
    found = amounts(sentence, names)
    said = stated(sentence, names)
    key, plans, stopped = shape_of(sentence, names)
    fixed = said if len(said) == 1 and not found else ()
    resolved = resolve(found, fixed, NOW, NOW, said, plans)
    if resolved.question is not None:
        return ("ask", resolved.question, key if key is not None else f"at {stopped}")
    return ("plan", resolved.usd_per_hour, resolved.decisions_per_hour, key)


ASKS = "ask", "budget_required"
TABLE = [
    # THE TWELVE MEASURED BUDGET SENTENCES
    (
        "Let this world spend up to 40 cents an hour on AI minds.",
        (),
        ("plan", "0.400000", 600, "let"),
    ),
    ("The minds may make at most 1,500 decisions an hour.", (), ("plan", "0.250000", 1500, "may")),
    (
        "Set the minds budget to $2 and 3000 decisions an hour.",
        (),
        ("plan", "2.000000", 3000, "set"),
    ),
    ("Stop spending anything on AI minds.", (), ("plan", "0.000000", 0, "nothing_stop")),
    ("Put the minds budget back to the default.", (), ("plan", "0.250000", 600, "default_back")),
    ("Let the minds spend 5 dollars a day.", (), ("ask", "budget_period", "at a")),
    ("Let the minds spend more.", (), ("ask", "budget_required", "at more")),
    (
        "Give the knight Nemotron 3 Nano 30B and let the minds spend a dollar an hour.",
        ("Nemotron 3 Nano 30B", "knight", "every knight"),
        ("plan", "1.000000", 600, "let"),
    ),
    ("cap the minds at 40 cents an hour", (), ("plan", "0.400000", 600, "set")),
    (
        "ok so I want the townsfolk to get 1500 decisions per hour, leave the money alone",
        (),
        ("ask", "budget_required", "at ok"),
    ),
    (
        "Hello! Could you please set the budget for my town's minds to a dollar fifty an hour "
        "and no more than two thousand decisions an hour? Thank you so much.",
        (),
        ("ask", "budget_required", "at hello"),
    ),
    ("new budget for the minds: $3/hr, 900 decisions", (), ("ask", "budget_required", "at new")),
    # THE RE-REVIEW'S TABLE, in its order
    ("Let the town spend 10 dollars every 24 hours", (), ("ask", "budget_period", "at every")),
    ("$50 for 30 days", (), ("ask", "budget_period", "at for")),
    ("20 dollars for 2 weeks", (), ("ask", "budget_period", "at for")),
    ("5 dollars over the next few days", (), ("ask", "budget_period", "at over")),
    ("$1 per 10 minutes", (), ("ask", "budget_period", "at per")),
    ("5 dollars for today", (), ("ask", "budget_period", "at for")),
    ("$0.01/min", (), ("ask", "budget_period", "at /")),
    ("$5 per day", (), ("ask", "budget_period", "at per")),
    ("5 dollars daily", (), ("ask", "budget_period", "at daily")),
    ("ten bucks a week", (), ("ask", "budget_period", "at a")),
    ("0.5 dollars / 2h", (), ("ask", "budget_period", "at /")),
    ("50 cents per half hour", (), ("ask", "budget_period", "at per")),
    ("a dollar every sixty minutes", (), ("ask", "budget_period", "at every")),
    ("three dollars for the afternoon", (), ("ask", "budget_period", "at for")),
    ("20 dollars total", (), ("ask", "budget_period", "at total")),
    ("1 dollar hourly", (), ("plan", "1.000000", 600, "bare")),
    ("50 cents per hr", (), ("plan", "0.500000", 600, "bare")),
    ("a dollar an h", (), ("ask", "budget_period", "at an")),
    ("1 USD/h", (), ("plan", "1.000000", 600, "bare")),
    ("50c/hr", (), ("plan", "0.500000", 600, "bare")),
    ("2 dollars an hour for the next 3 hours", (), ("ask", "budget_required", "at for")),
    ("an hour's worth is 2 dollars", (), ("ask", "budget_required", "at the hour")),
    ("2 dollars, hourly", (), ("plan", "2.000000", 600, "bare")),
    ("Let the minds spend 5 dollars for 24h", (), ("ask", "budget_required", "at for")),
    ("Give the town a total of 20 dollars for its minds", (), ("ask", "budget_required", "at a")),
    ("This afternoon the minds may spend 3 dollars", (), ("ask", "budget_required", "at this")),
    ("5 dollars until Friday", (), ("ask", "budget_required", "at until")),
    ("5 dollars for this session", (), ("ask", "budget_required", "at for")),
    ("5 dollars quarterly", (), ("ask", "budget_required", "at quarterly")),
    ("50 cents an hour each", (), ("ask", "budget_required", "at each")),
    ("2 dollars an hour per being", (), ("ask", "budget_required", "at per")),
    ("it cost 3 dollars yesterday, turn them off", (), ("ask", "budget_required", "at cost")),
    ("I paid 2 dollars, stop spending", (), ("ask", "budget_required", "at i")),
    ("keep it at 25 cents, not 50", (), ("ask", "budget_required", "at not")),
    ("raise it from 25 cents to 50", (), ("ask", "budget_required", "at from")),
    ("raise it from 25 cents to 50 cents", (), ("plan", "0.500000", 600, "move_from_to")),
    ("lower it by 10 cents", (), ("ask", "budget_required", "at by")),
    ("double it", (), ("ask", "budget_required", "at double")),
    ("half of what it is now", (), ("ask", "budget_required", "at half")),
    ("50 cents but no more than 300 decisions", (), ("ask", "budget_required", "at but")),
    (
        "set 300 decisions and leave the money alone",
        (),
        ("ask", "budget_required", "at the amount"),
    ),
    ("no more than a dollar", (), ("plan", "1.000000", 600, "bare")),
    ("at least a dollar", (), ("ask", "budget_required", "at at")),
    ("about a dollar", (), ("ask", "budget_required", "at about")),
    ("under 2 dollars", (), ("ask", "budget_required", "at under")),
    ("a couple of dollars", (), ("ask", "budget_required", "at a")),
    ("$1.50", (), ("plan", "1.500000", 600, "bare")),
    ("1,50 dollars", (), ("ask", "budget_required", "at 1")),
    ("1.5k decisions", (), ("ask", "budget_required", "at 1.5")),
    ("one thousand five hundred decisions", (), ("plan", "0.250000", 1500, "bare")),
    ("2 dollars per being", (), ("ask", "budget_period", "at per")),
    ("50 cents each", (), ("ask", "budget_period", "at each")),
    ("That cost 3 dollars! Turn it down.", (), ("ask", "budget_required", "at that")),
    (
        "It made only 5 decisions, raise the budget to 2 dollars an hour",
        (),
        ("ask", "budget_required", "at made"),
    ),
    ("Turn the minds off, 3 dollars is too much", (), ("ask", "budget_required", "at the amount")),
    ("make it 25, not 50 cents", (), ("ask", "budget_required", "at 25")),
    ("allow one hundred and twenty decisions an hour", (), ("ask", "budget_required", "at one")),
    ("a hundred and fifty dollars", (), ("ask", "budget_required", "at a")),
    ("a dollar and a half an hour", (), ("ask", "budget_required", "at and")),
    ("a dollar and 25 cents an hour", (), ("ask", "budget_required", "bare")),
    ("fifty to sixty cents", (), ("ask", "budget_required", "at fifty")),
    ("between one and two dollars", (), ("ask", "budget_required", "at between")),
    ("50 to 60 cents", (), ("ask", "budget_ambiguous", "bare")),
    ("No limit on the minds", (), ("ask", "budget_required", "at no")),
    ("unlimited", (), ("ask", "budget_required", "at unlimited")),
    # THE RE-REVIEW'S OTHER SENTENCES (Highs, Mediums and Lows outside its table)
    ("It has cost 3 dollars, cap it", (), ("ask", "budget_required", "at has")),
    ("It came to 4 dollars, please reduce it", (), ("ask", "budget_required", "at came")),
    ("It ran up 3 dollars, set 600 decisions an hour", (), ("ask", "budget_required", "at ran")),
    ("In total they may spend 20 dollars", (), ("ask", "budget_required", "at in")),
    ("5 dollars overnight", (), ("ask", "budget_required", "at overnight")),
    ("5 dollars fortnightly", (), ("ask", "budget_required", "at fortnightly")),
    ("a 24h budget of 5 dollars", (), ("ask", "budget_required", "at a")),
    ("5 dollars for 7d", (), ("ask", "budget_required", "at for")),
    (
        "Reset the budget, 5 dollars an hour is too high",
        (),
        ("ask", "budget_required", "at the amount"),
    ),
    ("I don't want to pay 5 dollars an hour", (), ("ask", "budget_required", "at i")),
    ("take the limit off", (), ("ask", "budget_required", "at take")),
    ("turn the cap off", (), ("ask", "budget_required", "at the")),
    ("50 cents an hour of game time", (), ("ask", "budget_required", "at of")),
    ("5 dollars per hour and a half", (), ("ask", "budget_required", "at and")),
    ("50 cents each per hour", (), ("ask", "budget_period", "at each")),
    # PLAIN SENTENCES
    ("50 cents an hour", (), ("plan", "0.500000", 600, "bare")),
    ("Let this town spend up to 50 cents an hour on minds.", (), ("plan", "0.500000", 600, "let")),
    ("600 decisions an hour", (), ("plan", "0.250000", 600, "bare")),
    ("Spend nothing on minds", (), ("plan", "0.000000", 0, "nothing_spend")),
    ("Set it to $0.50 per hour", (), ("plan", "0.500000", 600, "set")),
    ("Set the minds budget to $2 and 600 decisions an hour", (), ("plan", "2.000000", 600, "set")),
    ("$5 hourly for the minds", (), ("plan", "5.000000", 600, "bare")),
    ("Let the minds make 1,000 decisions an hour", (), ("plan", "0.250000", 1000, "let")),
    ("Cap the minds at 50c/h", (), ("plan", "0.500000", 600, "set")),
    ("Spend a dollar an hour on the minds", (), ("plan", "1.000000", 600, "spend")),
    (
        "Let the town's minds spend at most 75 cents in any one hour",
        (),
        ("plan", "0.750000", 600, "let"),
    ),
    ("USD 1.50 each hour for the minds", (), ("plan", "1.500000", 600, "bare")),
    ("Give the minds 40 cents", (), ("plan", "0.400000", 600, "give")),
    ("Allow 300 model decisions per hour and 20 cents", (), ("plan", "0.200000", 300, "allow")),
    ("Let the minds answer 600 times an hour", (), ("plan", "0.250000", 600, "let")),
    ("Set the minds' budget to $0", (), ("plan", "0.000000", 600, "set")),
    ("half a dollar an hour for the minds", (), ("plan", "0.500000", 600, "bare")),
    ("50 cents for the minds every hour", (), ("ask", "budget_required", "at the hour")),
    ("two thousand five hundred decisions an hour", (), ("plan", "0.250000", 2500, "bare")),
    ("Raise the minds budget to 50 cents an hour", (), ("plan", "0.500000", 600, "move_to")),
    ("Raise the minds budget 50 cents an hour", (), ("ask", "budget_required", "at the amount")),
    ("Lower the budget to 10 cents an hour", (), ("plan", "0.100000", 600, "move_to")),
    ("Turn the minds off", (), ("plan", "0.000000", 0, "nothing_off")),
    ("Turn the minds' spending off", (), ("plan", "0.000000", 0, "nothing_off")),
    ("Reset the minds budget", (), ("plan", "0.250000", 600, "default_reset")),
    ("Put the budget back to its default", (), ("plan", "0.250000", 600, "default_back")),
    ("Go back to what the world starts with", (), ("ask", "budget_required", "at to")),
    ("Each hour the minds may spend 40 cents", (), ("ask", "budget_required", "at the hour")),
    ("Give the minds a budget of 2 dollars", (), ("plan", "2.000000", 600, "give")),
    ("no more than 50 cents an hour for the minds", (), ("plan", "0.500000", 600, "bare")),
    ("Let the minds cost at most 50 cents an hour", (), ("ask", "budget_required", "at cost")),
    (
        "Give 3 knights a mind and let the minds spend 50 cents an hour",
        (),
        ("ask", "budget_required", "at 3"),
    ),
    # COMPOUND SENTENCES (the widening: names of what another step acts on)
    (
        "Give the knight Nemotron 3 Nano 30B and let the minds spend a dollar an hour.",
        (),
        ("ask", "budget_required", "at the"),
    ),
    (
        "Give the knight Nemotron 3 Nano 30B and let the minds spend 3 dollars an hour",
        ("Nemotron 3 Nano 30B", "knight"),
        ("plan", "3.000000", 600, "let"),
    ),
    (
        "Give the knight Nemotron 3 Nano 30 dollars",
        ("Nemotron 3 Nano 30", "knight"),
        ("ask", "budget_required", "at a name"),
    ),
    (
        "Give the knight Nano and let the minds spend a dollar an hour",
        ("Nemotron 3 Nano 30B", "knight"),
        ("ask", "budget_required", "at nano"),
    ),
    (
        "Give 3 knights a mind and let the minds spend 50 cents an hour",
        ("knight",),
        ("ask", "budget_required", "at 3"),
    ),
    (
        "Give every knight Nemotron 3 Nano 30B and let the minds spend a dollar a day",
        ("Nemotron 3 Nano 30B", "knight", "every knight"),
        ("ask", "budget_period", "at a"),
    ),
    # THE THIRD REVIEW'S HIGHS, MEDIUMS AND LOWS
    (
        "$50 \u0432 \u043d\u0435\u0434\u0435\u043b\u044e",
        (),
        ("ask", "budget_required", "at \u0432"),
    ),
    ("\u6bcf\u5929$5", (), ("ask", "budget_required", "at \u6bcf\u5929")),
    ("\ud558\ub8e8\uc5d0 $5", (), ("ask", "budget_required", "at \ud558\ub8e8\uc5d0")),
    (
        "5 USD \u0641\u064a \u0627\u0644\u064a\u0648\u0645",
        (),
        ("ask", "budget_required", "at \u0641\u064a"),
    ),
    ("+50 cents an hour", (), ("ask", "budget_required", "at +")),
    ("Budget +$1", (), ("ask", "budget_required", "at budget")),
    ("-10 cents", (), ("ask", "budget_required", "at -")),
    ("> 2 dollars", (), ("ask", "budget_required", "at >")),
    ("$5+", (), ("ask", "budget_required", "at +")),
    ("1\u00bd dollars", (), ("ask", "budget_required", "at 1")),
    (
        "Give every knight Nemotron 3 Nano 30B and a dollar an hour",
        ("Nemotron 3 Nano 30B", "every knight", "knight"),
        ("ask", "budget_required", "at the amount"),
    ),
    (
        "Give Aldric Nemotron 3 Nano 30B and 2 dollars an hour",
        ("Nemotron 3 Nano 30B", "Aldric"),
        ("ask", "budget_required", "at the amount"),
    ),
    ("Give everyone a dollar an hour", (), ("ask", "budget_required", "at everyone")),
    ("Let everybody spend 50 cents an hour", (), ("ask", "budget_required", "at everybody")),
    ("Give Yesterday a dollar an hour", ("Yesterday",), ("ask", "budget_required", "at a name")),
    (
        "Let the minds spend 5 dollars for just this one hour",
        (),
        ("ask", "budget_required", "at for"),
    ),
    ("Let the minds spend 5 dollars for one hour", (), ("ask", "budget_required", "at for")),
    ("Let the minds spend 5 dollars for an hour", (), ("ask", "budget_required", "at for")),
    ("5 dollars this hour", (), ("ask", "budget_required", "at this")),
    ("2 dollars an hour for a whole hour", (), ("ask", "budget_required", "at for")),
    (
        "The minds make 5 decisions an hour, set the budget to 2 dollars",
        (),
        ("ask", "budget_required", "at make"),
    ),
    ("They spend 3 dollars an hour, cap it", (), ("ask", "budget_required", "at they")),
    ("It's at 3 dollars an hour, cap it", (), ("ask", "budget_required", "at s")),
    ("Lower the budget from 2 dollars", (), ("ask", "budget_required", "at from")),
    (
        "One question: can the minds spend 2 dollars an hour?",
        (),
        ("ask", "budget_required", "at one"),
    ),
    ("I have 2 questions: 50 cents an hour", (), ("ask", "budget_required", "at i")),
    ("Two asks: 50 cents an hour", (), ("ask", "budget_required", "at two")),
    ("One question: 50 cents an hour", (), ("ask", "budget_required", "at one")),
    (
        "Give the knight Nano and spend 5 dollars daily",
        ("Daily", "knight", "Nano"),
        ("ask", "budget_required", "at spend"),
    ),
    ("Go back 50 cents", (), ("ask", "budget_required", "at the amount")),
    ("turn it back 10 cents", (), ("ask", "budget_required", "at it")),
    ("Keep it 10 cents under the maximum", (), ("ask", "budget_required", "at the amount")),
    ("50 cents for 100 decisions", (), ("ask", "budget_required", "at for")),
    ("Nothing should stop the minds", (), ("ask", "budget_required", "at nothing")),
    ("Stop the world", (), ("ask", "budget_required", "at the")),
    ("What would 50 cents an hour get?", (), ("ask", "budget_required", "at what")),
    ("1.000 dollars", (), ("ask", "budget_required", "at 1.000")),
    ("5 US dollars", (), ("ask", "budget_required", "at 5")),
    # THE THIRD REVIEW'S TABLE, in its order
    ("2 dollars per hour per being", (), ("ask", "budget_required", "at per")),
    ("5 dollars per 24 hours", (), ("ask", "budget_period", "at per")),
    ("5 dollars for 24h", (), ("ask", "budget_required", "at for")),
    ("5 dollars an hour for 3 hours", (), ("ask", "budget_required", "at for")),
    ("5 dollars an hour today", (), ("ask", "budget_required", "at today")),
    ("a dollar an hour of game time", (), ("ask", "budget_required", "at of")),
    ("a dollar per half hour", (), ("ask", "budget_period", "at per")),
    ("a dollar an hour and a half", (), ("ask", "budget_required", "at and")),
    ("1 dollar/h", (), ("plan", "1.000000", 600, "bare")),
    ("1 dollar hourly, 600 decisions daily", (), ("ask", "budget_period", "at daily")),
    ("600 decisions a minute", (), ("ask", "budget_period", "at a")),
    ("raise the budget 50 cents an hour", (), ("ask", "budget_required", "at the amount")),
    ("raise the budget to 50 cents an hour", (), ("plan", "0.500000", 600, "move_to")),
    ("raise the budget by 50 cents an hour", (), ("ask", "budget_required", "at by")),
    ("cut it to 10 cents an hour", (), ("ask", "budget_required", "at cut")),
    ("bring it down to a dollar an hour", (), ("ask", "budget_required", "at down")),
    ("make it a dollar an hour", (), ("ask", "budget_required", "at the amount")),
    ("set it back to a dollar an hour", (), ("ask", "budget_required", "at back")),
    ("keep it at a dollar an hour", (), ("plan", "1.000000", 600, "set")),
    ("leave it at a dollar an hour", (), ("plan", "1.000000", 600, "set")),
    (
        "change it from 1 dollar to 2 dollars an hour",
        (),
        ("ask", "budget_ambiguous", "move_from_to"),
    ),
    ("go from 2 dollars to 1 dollar an hour", (), ("ask", "budget_required", "at from")),
    ("from 2 up to 5 dollars", (), ("ask", "budget_required", "at from")),
    (
        "Give Fifty a mind and let the minds spend fifty cents an hour",
        ("Fifty",),
        ("ask", "budget_required", "at the name"),
    ),
    ("Give Off a mind and turn the minds off", ("Off",), ("ask", "budget_required", "at turn")),
    ("no limit", (), ("ask", "budget_required", "at no")),
    ("switch off the limit", (), ("ask", "budget_required", "at the")),
    ("stop the minds", (), ("plan", "0.000000", 0, "nothing_stop_minds")),
    ("nothing more than a dollar an hour", (), ("ask", "budget_required", "at nothing")),
    ("reset to 2 dollars an hour", (), ("ask", "budget_required", "at to")),
    ("the default is fine", (), ("ask", "budget_required", "at the")),
    ("back to how it started", (), ("ask", "budget_required", "at to")),
    ("zero dollars an hour", (), ("plan", "0.000000", 600, "bare")),
    ("0 decisions an hour", (), ("plan", "0.250000", 0, "bare")),
    ("5 dollars for 1 hour", (), ("ask", "budget_required", "at for")),
    ("50 cents a town", (), ("ask", "budget_period", "at a")),
    ("50 cents per world", (), ("ask", "budget_period", "at per")),
    ("\u20ac5 an hour", (), ("ask", "budget_required", "at \u20ac")),
    ("5 euros", (), ("ask", "budget_required", "at 5")),
    ("5 pounds", (), ("ask", "budget_required", "at 5")),
    ("50 percent", (), ("ask", "budget_required", "at 50")),
    ("5k dollars", (), ("ask", "budget_required", "at 5")),
    ("A$5", (), ("ask", "budget_required", "at a")),
    ("S$5", (), ("ask", "budget_required", "at s")),
    ("$5 CAD", (), ("ask", "budget_required", "at cad")),
    # The trace of v4: a pronoun after another step's names, a move word against its own
    # direction, a default said of what is no budget, must and should, a figure given to a
    # budget noun, and a question. Each asks.
    (
        "Give Aldric Nemotron 3 Nano 30B and let it spend 2 dollars an hour",
        ("Nemotron 3 Nano 30B", "Aldric"),
        ("ask", "budget_required", "at it"),
    ),
    (
        "Give Aldric Nemotron 3 Nano 30B and give it 2 dollars an hour",
        ("Nemotron 3 Nano 30B", "Aldric"),
        ("ask", "budget_required", "at it"),
    ),
    (
        "Give Aldric Nemotron 3 Nano 30B and cap it at 40 cents an hour",
        ("Nemotron 3 Nano 30B", "Aldric"),
        ("ask", "budget_required", "at it"),
    ),
    (
        "Give Aldric Nemotron 3 Nano 30B and it may spend 2 dollars an hour",
        ("Nemotron 3 Nano 30B", "Aldric"),
        ("ask", "budget_required", "at it"),
    ),
    (
        "Give every knight Nemotron 3 Nano 30B and set their budget to a dollar an hour",
        ("Nemotron 3 Nano 30B", "every knight", "knight"),
        ("ask", "budget_required", "at their"),
    ),
    (
        "Give every knight Nemotron 3 Nano 30B and set its budget to a dollar an hour",
        ("Nemotron 3 Nano 30B", "every knight", "knight"),
        ("ask", "budget_required", "at its"),
    ),
    ("Drop the budget to 5 dollars an hour", (), ("ask", "budget_required", "move_to")),
    ("raise it to 10 cents", (), ("ask", "budget_required", "move_to")),
    (
        "Raise the budget to 2 dollars and 300 decisions an hour",
        (),
        ("ask", "budget_required", "move_to"),
    ),
    ("Reset the world", (), ("ask", "budget_required", "at the")),
    ("Reset this town", (), ("ask", "budget_required", "at this")),
    ("Reset the minds", (), ("ask", "budget_required", "at the")),
    ("Put the world back to the default", (), ("ask", "budget_required", "at back")),
    ("The minds must spend 2 dollars an hour", (), ("ask", "budget_required", "at must")),
    ("The minds must answer 5 times an hour", (), ("ask", "budget_required", "at must")),
    ("The minds should spend 2 dollars an hour", (), ("ask", "budget_required", "at should")),
    ("Give the budget 50 cents", (), ("ask", "budget_required", "at the")),
    ("Give it 2 dollars an hour", (), ("ask", "budget_required", "at it")),
    ("The minds can spend 2 dollars an hour?", (), ("ask", "budget_required", "at ?")),
    ("50 cents an hour?", (), ("ask", "budget_required", "at ?")),
]


@pytest.mark.parametrize(("sentence", "names", "comes_to"), TABLE)
def test_a_sentence_plans_only_where_the_whole_of_it_is_one_of_the_shapes(
    sentence, names, comes_to
):
    assert _comes_to(sentence, names) == comes_to


def test_the_table_holds_what_the_readings_found_and_what_still_plans():
    planned = [row for row in TABLE if row[2][0] == "plan"]
    asked = [row for row in TABLE if row[2][0] == "ask"]
    assert (len(TABLE), len(planned), len(asked)) == (233, 50, 183)
    # A sentence that is a shape and still asks is one a doubt caught: a sum of parts, a range,
    # a move from an amount the budget is not at, and a move against its own word's direction.
    shaped = {row[0]: row[2] for row in asked if not row[2][2].startswith("at ")}
    assert shaped == {
        "a dollar and 25 cents an hour": ("ask", "budget_required", "bare"),
        "50 to 60 cents": ("ask", "budget_ambiguous", "bare"),
        "Drop the budget to 5 dollars an hour": ("ask", "budget_required", "move_to"),
        "raise it to 10 cents": ("ask", "budget_required", "move_to"),
        "Raise the budget to 2 dollars and 300 decisions an hour": (
            "ask",
            "budget_required",
            "move_to",
        ),
        "change it from 1 dollar to 2 dollars an hour": ("ask", "budget_ambiguous", "move_from_to"),
    }


def test_a_choice_the_sentence_offers_is_a_question_between_its_two_amounts_and_never_a_plan():
    for sentence, key in (
        ("Let the minds spend 30 cents or 50 cents an hour", "let"),
        ("Let the minds spend 50 to 60 cents an hour", "let"),
        ("Allow 800 decisions an hour, or 900 decisions an hour", "allow"),
        ("Set the budget to 1 dollar or 2 dollars", "set"),
    ):
        assert shape_of(sentence) == (key, budget.CHOICE, ""), sentence
        assert _asked(sentence) == "budget_ambiguous", sentence
    # A choice that is not between two amounts of one kind is asked for whole: dollars or a
    # count, the same amount twice.
    for sentence in (
        "50 cents or 600 decisions an hour",
        "Let the minds spend 50 cents or 50 cents an hour",
    ):
        assert shape_of(sentence)[1] == budget.CHOICE, sentence
        assert _asked(sentence) == "budget_required", sentence
    # Whatever is read, a choice plans nothing: with one amount it would have been a plan.
    one = amounts("Let the minds spend 50 cents an hour")
    assert resolve(one, (), NOW, NOW, (), budget.AMOUNTS).question is None
    assert resolve(one, (), NOW, NOW, (), budget.CHOICE).question == "budget_required"
    # "or" and "to" join only two amounts: more, or a third word, is no shape.
    assert shape_of("30 cents or 40 cents or 50 cents")[0] is None
    assert shape_of("30 cents or maybe 50 cents")[0] is None
    assert shape_of("30 cents or")[0] is None


# -- what was taken out so that more is asked ------------------------------------------------------


def test_a_word_that_says_which_way_a_figure_moves_is_held_to_it():
    """ "Lower" to more than the budget is now, or "raise" to less, is asked about: the figure
    is the stated target, and the word says the person thinks the budget is somewhere else."""
    assert shape_of("Raise the budget to 50 cents an hour")[:2] == ("move_to", "amounts:up")
    assert shape_of("Drop the budget to 10 cents an hour")[:2] == ("move_to", "amounts:down")
    assert shape_of("Change the budget to 10 cents an hour")[:2] == ("move_to", "amounts")
    assert shape_of("lower it from 25 cents to 10 cents")[:2] == ("move_from_to", "from_to:down")
    # The world is at 25 cents and 600 decisions.
    assert _comes_to("Raise the budget to 50 cents an hour")[:2] == ("plan", "0.500000")
    assert _comes_to("Raise the budget to 10 cents an hour")[:2] == ASKS
    assert _comes_to("Lower the budget to 10 cents an hour")[:2] == ("plan", "0.100000")
    assert _comes_to("Lower the budget to 50 cents an hour")[:2] == ASKS
    assert _comes_to("lower it from 25 cents to 10 cents")[:2] == ("plan", "0.100000")
    assert _comes_to("lower it from 25 cents to 50 cents")[:2] == ASKS
    # A figure equal to the budget's moves nothing and contradicts nothing.
    assert _comes_to("Lower the budget to 25 cents an hour")[:2] == ("plan", "0.250000")
    # A word that says no way is held to none.
    assert _comes_to("Change the budget to 5 dollars an hour")[:2] == ("plan", "5.000000")
    assert _comes_to("Set the budget to 5 dollars an hour")[:2] == ("plan", "5.000000")
    # Each figure the words name is held to the word: dollars up and decisions down is asked.
    assert _comes_to("Raise the budget to 2 dollars and 900 decisions an hour")[:3] == (
        "plan",
        "2.000000",
        900,
    )
    assert _comes_to("Raise the budget to 2 dollars and 300 decisions an hour")[:2] == ASKS
    # The way is the shape's, read against the budget as it is when the step is read.
    one = amounts("Lower the budget to 2 dollars an hour")
    higher = {"usd_per_hour": "5.000000", "decisions_per_hour": 600}
    assert resolve(one, (), higher, NOW, (), "amounts:down").usd_per_hour == "2.000000"
    assert resolve(one, (), NOW, NOW, (), "amounts:down").question == "budget_required"
    assert resolve(one, (), NOW, NOW, (), "amounts").usd_per_hour == "2.000000"


def test_what_names_no_budget_is_not_reset_and_what_is_no_one_s_is_given_nothing():
    # The default is put back to a budget, a limit or a cap; a world, a town or the minds reset
    # is another request.
    assert shape_of("Reset the budget")[0] == "default_reset"
    assert shape_of("Put the minds budget back to the default")[0] == "default_back"
    for sentence in ("Reset the world", "Reset this town", "Reset the minds", "Reset it"):
        assert shape_of(sentence)[0] is None, sentence
    assert shape_of("Put the world back to the default")[0] is None
    # A figure is given to the minds, the world or the town; given to a budget noun it reads as
    # an amount added.
    assert shape_of("Give the world 50 cents")[0] == "give"
    assert shape_of("Give the budget 50 cents")[0] is None
    assert shape_of("Give it 50 cents")[0] is None
    # "Must" and "should" may mean a floor: neither makes a rule of a ceiling.
    assert shape_of("The minds can spend 2 dollars an hour")[0] == "may"
    assert shape_of("The minds must spend 2 dollars an hour")[0] is None
    assert shape_of("The minds should spend 2 dollars an hour")[0] is None
    # A question is asked back, not planned.
    assert shape_of("50 cents an hour?") == (None, None, "?")
    assert shape_of("The minds can spend 2 dollars an hour?") == (None, None, "?")


def test_the_two_narrower_subject_lists_hold_only_words_of_the_whole_one():
    """The lists the default's shapes and ``give`` take are parts of the one list of whose figure
    it is: neither holds a word that list does not, so neither lets a sentence plan that the
    whole list did not."""
    slots = {e["name"]: set(e["words"]) for e in _catalog()["entries"] if e["kind"] == "slot"}
    whole = slots["subject"]
    assert slots["budget"] < whole and slots["given"] < whole
    assert not slots["budget"] & slots["given"]
    # A budget noun names a budget, a limit or a cap; what a figure is given to names none.
    nouns = {"budget", "limit", "cap"}
    assert all(nouns & set(words.split()) for words in slots["budget"])
    assert not any(nouns & set(words.split()) for words in slots["given"])
    # What is in neither: the pronoun, and the spending.
    assert whole - slots["budget"] - slots["given"] == {
        "it",
        "the spending",
        "the minds spending",
    }
    # And the shapes that take them took the whole list before, and no other shape takes them.
    takes = {
        name: [
            s["name"]
            for s in _catalog()["entries"]
            if s["kind"] == "shape" and f"<{name}>" in s["pattern"]
        ]
        for name in ("budget", "given")
    }
    assert takes == {"budget": ["default_reset", "default_back"], "given": ["give"]}


def test_a_pronoun_after_another_step_s_names_says_nobody_s_figure():
    names = (MODEL, "Aldric", "every knight", "knight")
    for clause in (
        "let it spend 2 dollars an hour",
        "cap it at 40 cents an hour",
        "it may spend 2 dollars an hour",
        "set its budget to a dollar an hour",
        "set their budget to a dollar an hour",
    ):
        # Alone, the clause is the world's budget and a shape.
        assert shape_of(clause)[0] is not None, clause
        # After a name, "it" is what was named.
        after = f"Give Aldric Nemotron 3 Nano 30B and {clause}"
        key, plans, stopped = shape_of(after, names)
        assert (key, plans) == (None, None) and stopped in ("it", "its", "their"), (clause, stopped)
        assert _comes_to(after, names)[:2] == ASKS
    # Said of the minds by their own word, it is the world's.
    assert _comes_to(
        "Give Aldric Nemotron 3 Nano 30B and let the minds spend 2 dollars an hour", names
    ) == ("plan", "2.000000", 600, "let")


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda slots: slots["subject"]["words"].append(""), "holds a word this cannot read"),
        (lambda slots: slots["subject"]["words"].append("   "), "holds a word this cannot read"),
        (lambda slots: slots["modal"].update(direction={"may": "up"}), "only the move slot"),
        (lambda slots: slots["move"]["direction"].update(raise_="up"), "of a word of its own slot"),
        (lambda slots: slots["move"]["direction"].update(lower="sideways"), "is up or down"),
    ],
)
def test_the_loader_refuses_a_slot_it_cannot_hold_to_its_rule(tmp_path, monkeypatch, change, said):
    document = _catalog()
    change({entry["name"]: entry for entry in document["entries"] if entry["kind"] == "slot"})
    written = tmp_path / "minds-budget-shapes.v1.json"
    written.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(budget, "SHAPES", written)
    budget._shapes.cache_clear()
    try:
        with pytest.raises(ValueError, match=said):
            shape_of("50 cents an hour")
    finally:
        monkeypatch.undo()
        budget._shapes.cache_clear()
    assert shape_of("50 cents an hour")[0] == "bare"


# -- every character is read ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "stopped"),
    [
        # Another script: the words that say a week, a day.
        ("$50 \u0432 \u043d\u0435\u0434\u0435\u043b\u044e", "\u0432"),
        ("\u6bcf\u5929$5", "\u6bcf\u5929"),
        ("5 USD \u0641\u064a \u0627\u0644\u064a\u0648\u0645", "\u0641\u064a"),
        # A sign that makes a change or a floor, a fraction, a percent.
        ("+50 cents an hour", "+"),
        ("Budget +$1", "budget"),
        ("-10 cents", "-"),
        ("> 2 dollars", ">"),
        ("$5+", "+"),
        ("1\u00bd dollars", "1"),
        ("50% of a dollar", "50"),
        ("\u20ac5 an hour", "\u20ac"),
    ],
)
def test_what_is_no_number_no_plain_word_and_no_known_sign_is_a_token_no_shape_holds(
    sentence, stopped
):
    key, plans, at = shape_of(sentence)
    assert (key, plans, at) == (None, None, stopped)
    assert _asked(sentence) is not None


def test_plain_punctuation_is_silent_and_a_hyphen_only_between_letters():
    assert shape_of("Set the minds' budget to $2, and 600 decisions an hour!")[0] == "set"
    assert shape_of("Set the minds\u2019 budget to $2")[0] == "set"
    assert shape_of("Please: 50 cents an hour.")[0] == "bare"
    # A number written with a point and three digits may be thousands: it is no number.
    assert shape_of("1.000 dollars") == (None, None, "1.000")
    assert shape_of("0.125 dollars an hour")[0] == "bare"


# -- the hour ------------------------------------------------------------------------------------


def test_the_hour_is_one_rate_word_and_the_hour_and_nothing_that_ends_it():
    for said in ("an hour", "per hour", "every hour", "each hour", "hourly", "in any one hour"):
        assert shape_of(f"50 cents {said}")[0] == "bare", said
    assert shape_of("50c/h")[0] == "bare" and shape_of("$1/hr")[0] == "bare"
    assert shape_of("50 cents an hour of real time")[0] == "bare"
    # An end, a part, a count or the world's own hour is no hour a budget is by.
    for said, stopped in (
        ("for one hour", "for"),
        ("for an hour", "for"),
        ("this hour", "this"),
        ("for just this one hour", "for"),
        ("every 2 hours", "every"),
        ("a game hour", "a"),
        ("an hour each", "each"),
        ("each per hour", "each"),
        ("an hour of game time", "of"),
    ):
        assert shape_of(f"Let the minds spend 5 dollars {said}") == (None, None, stopped), said


# -- the shapes as data --------------------------------------------------------------------------


def _catalog() -> dict:
    return json.loads(budget.SHAPES.read_text(encoding="utf-8"))


def test_every_shape_is_exactly_the_sentences_it_was_written_for():
    entries = _catalog()["entries"]
    shapes = [entry for entry in entries if entry["kind"] == "shape"]
    slots = {entry["name"]: entry["words"] for entry in entries if entry["kind"] == "slot"}
    assert (len(shapes), len(slots)) == (19, 21)
    for shape in shapes:
        assert shape["examples"], shape["name"]
        for example in shape["examples"]:
            key, plans, stopped = shape_of(example)
            # What it plans is the shape's own kind, with the way a move word says, if any.
            assert (key, plans.partition(":")[0]) == (shape["name"], shape["budget"]), (
                example,
                key,
                stopped,
            )
        assert len(shape["reason"].split()) >= 12
    for name, words in slots.items():
        assert len(words) == len(set(words)), name


def test_no_slot_holds_a_word_for_each_of_something_or_for_everyone():
    """A figure for each of something, or for everyone, is not the world's budget: no slot holds
    a word that could be the one such a figure is for, nor a word the reader knows as a span, a
    part, a whole, a report or a change."""
    entries = [entry for entry in _catalog()["entries"] if entry["kind"] == "slot"]
    # The words of another step's own clause are that step's: they stand only before the "and"
    # that ends it, never in the budget's clause (the names tests below hold that).
    [others] = [entry for entry in entries if entry["name"] == "other_step"]
    entries.remove(others)
    words = {word for entry in entries for text in entry["words"] for word in text.split()}
    assert not words & {"everyone", "everybody", "each", "every", "per", "being", "mind", "model"}
    assert not words & {"knight", "villager", "person", "all", "total", "only", "not", "too"}
    doubtful = (
        budget._SPANS
        | budget._SPANS_BESIDE
        | budget._WHOLE
        | budget._PARTS
        | budget._REPORT
        | budget._COST
        | budget._CHANGE_BEFORE
        | budget._OTHER_DOLLARS
        | budget._NO_LIMIT
    )
    # "world" and "town" name whose budget it is; "lower" moves a figure only before "to";
    # "more" stands only in "no more than".
    assert words & (doubtful | budget._CHANGE_AFTER | budget._NOT_REAL_TIME) == {
        "world",
        "town",
        "lower",
        "more",
    }
    # The subjects that can be turned off do not include the world, the town or "it".
    [minds] = [entry["words"] for entry in entries if entry["name"] == "minds"]
    assert not {"it", "the world", "this world", "the town", "this town"} & set(minds)


def test_a_word_of_one_slot_is_allowed_in_that_slot_and_nowhere_else():
    # The same allowed words in another order are no shape.
    assert shape_of("Set the minds budget to $2")[0] == "set"
    assert shape_of("The minds budget set to $2")[0] is None
    assert shape_of("To $2 set the minds budget")[0] is None
    # A verb that reports is no rule without its modal, and a modal makes it one.
    assert shape_of("The minds may spend 3 dollars an hour")[0] == "may"
    assert shape_of("The minds spend 3 dollars an hour")[0] is None
    assert shape_of("They spend 3 dollars an hour, cap it")[0] is None
    # A move needs "to"; "from" alone is no shape, and "from" with "to" is one.
    assert shape_of("Raise the budget 50 cents an hour")[0] is None
    assert shape_of("Lower the budget from 2 dollars")[0] is None
    assert shape_of("Lower the budget from 2 dollars to 1 dollar")[0] == "move_from_to"
    # A preface is no count: "question" counts only with the hour right beside it.
    assert amounts("One question: can the minds spend 2 dollars an hour?")[0].unit == USD
    assert _asked("One question: 50 cents an hour") == "budget_required"
    assert _comes_to("600 answers an hour") == ("plan", "0.250000", 600, "bare")


def test_a_word_inside_an_amount_or_said_of_a_limit_states_no_budget_of_nothing():
    # "zero dollars" is an amount, and is planned as one.
    assert stated("Set the minds budget to zero dollars an hour") == ()
    assert _comes_to("Set the minds budget to zero dollars an hour") == (
        "plan",
        "0.000000",
        600,
        "set",
    )
    # Taking a limit off is not turning the spending off.
    for sentence in (
        "turn the cap off",
        "take the limit off",
        "turn the budget off",
        "stop the cap",
    ):
        assert stated(sentence) == (), sentence
        assert shape_of(sentence)[0] is None, sentence
    assert stated("Turn the minds off") == (NOTHING,)
    assert _comes_to("Set the budget to nothing") == ("plan", "0.000000", 0, "nothing_set")
    # Nor is stopping the world, or a sentence that only holds the word.
    assert shape_of("Stop the world")[0] is None
    assert shape_of("Nothing should stop the minds")[0] is None


# -- names of what another step of the same request acts on ---------------------------------------

MODEL = "Nemotron 3 Nano 30B"


def test_a_name_stands_only_in_its_own_step_s_clause_and_its_numbers_are_no_amount():
    sentence = "Give the knight Nemotron 3 Nano 30B and let the minds spend 3 dollars an hour"
    # With no names it is no shape: the first word no shape gets past is the other step's.
    assert shape_of(sentence)[0] is None and _comes_to(sentence)[:2] == ASKS
    # With the names code holds for the other step's options, the first clause is that step's
    # and the budget's clause is a shape with its own subject. The budget is the three dollars
    # the words give it: not the model's 3, and not its 30.
    names = (MODEL, "knight")
    [three] = amounts(sentence, names)
    assert (three.unit, three.value, three.period, three.words) == (
        USD,
        Decimal(3),
        HOUR,
        "3 dollars",
    )
    assert _comes_to(sentence, names) == ("plan", "3.000000", 600, "let")
    # A number inside a name is never an amount, even with a unit right after the name.
    assert amounts("Give the knight Nemotron 3 Nano 30 dollars", ("Nemotron 3 Nano 30",)) == ()
    # Without the name, that same sentence reads thirty dollars: the name is what keeps it out.
    assert [a.value for a in amounts("Give the knight Nemotron 3 Nano 30 dollars")] == [Decimal(30)]


def test_the_figure_after_a_name_is_never_the_world_s_unless_its_clause_says_whose_it_is():
    names = (MODEL, "every knight", "knight", "Aldric")
    # The figure is each knight's, or one being's: the budget's clause has no subject of its own.
    for sentence in (
        "Give every knight Nemotron 3 Nano 30B and a dollar an hour",
        "Give Aldric Nemotron 3 Nano 30B and 2 dollars an hour",
        "Give every knight Nemotron 3 Nano 30B and spend a dollar an hour",
        "Give every knight Nemotron 3 Nano 30B and allow 600 decisions an hour",
    ):
        assert _comes_to(sentence, names)[:2] == ASKS, sentence
    # With a subject of the closed list in the budget's own clause, it is the world's.
    assert _comes_to(
        "Give every knight Nemotron 3 Nano 30B and let the minds spend a dollar an hour", names
    ) == ("plan", "1.000000", 600, "let")
    assert _comes_to(
        "Give every knight Nemotron 3 Nano 30B and set the budget to a dollar an hour", names
    ) == ("plan", "1.000000", 600, "set")
    # A name in the budget's own clause, or with no "and" after its clause, is no shape; so a
    # being called by a word of doubt cannot hide that word.
    assert shape_of("Give Yesterday a dollar an hour", ("Yesterday",))[0] is None
    daily = ("Daily", "knight", "Nano")
    assert shape_of("Give the knight Nano and spend 5 dollars daily", daily)[0] is None
    aldric = "Give the knight Nano and let Aldric spend a dollar an hour"
    assert shape_of(aldric, (*names, "Nano"))[0] is None
    # A shape that may leave its subject out must not leave it out after names: with nothing
    # that says whose it is, the figure may be each knight's.
    for clause in ("cap at 40 cents an hour", "raise to 2 dollars an hour"):
        left_out = f"Give every knight Nemotron 3 Nano 30B and {clause}"
        assert shape_of(clause)[0] is not None, clause
        assert _comes_to(left_out, names)[:2] == ASKS, clause
    # A budget with no figure is never the second half of a compound, and a clause that turns
    # the minds off says nothing of whose figure it is.
    for clause in ("set the budget to nothing", "reset the budget", "turn the minds off"):
        assert shape_of(f"Give the knight Nano and {clause}", (*names, "Nano"))[0] is None, clause
    # No name at all: everyone is no subject.
    assert _comes_to("Give everyone a dollar an hour")[:2] == ASKS
    assert _comes_to("Let everybody spend 50 cents an hour")[:2] == ASKS


def test_a_name_counts_only_whole_in_order_and_once_a_word():
    sentence = "Give the knight Nano and let the minds spend a dollar an hour"
    # Part of a name is not the name.
    assert shape_of(sentence, (MODEL, "knight")) == (None, None, "nano")
    # A name is what code holds, as written: another word is not it.
    plural = "Give the knights Nano and let the minds spend a dollar"
    assert shape_of(plural, ("knight", "Nano"))[0] is None
    # The longest name takes its words; a shorter one inside it does not split it.
    whole = "Give the knight Nemotron 3 Nano 30B and let the minds spend a dollar an hour"
    assert shape_of(whole, ("Nano", MODEL, "knight"))[0] == "let"
    # The other step's clause holds only its names and its own few words.
    early = "Yesterday give the knight Nano and let the minds spend a dollar"
    assert shape_of(early, ("knight", "Nano")) == (None, None, "yesterday")
    # A name states no budget of nothing: "Off" is a being here, not the word.
    assert stated("Give Off a mind and let the minds spend a dollar an hour", ("Off",)) == ()
