"""A refusal's words are said back only as JSON and UTF-8 can carry them.

A client's own value reaches a refusal; JSON parses a lone surrogate and Python's reader a NaN or an
infinity, and neither can be written back. Each case is checked by writing the result the way a
response is written (strict JSON, UTF-8), which is the source of the expected outcome here.
"""

from __future__ import annotations

import json
import math

import pytest
from exulanica.api.sayable import sayable


def _written(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -math.inf,
        "\ud800",
        {"\udfff": [float("nan"), {"key": "a\ud800b"}]},
        ("x", float("-inf")),
    ],
)
def test_a_value_json_or_utf8_cannot_carry_is_said_in_words(value: object) -> None:
    with pytest.raises((ValueError, UnicodeEncodeError)):
        _written(value)
    said = _written(sayable(value))
    assert said


def test_everything_else_is_said_as_it_was() -> None:
    value = {"code": "x", "detail": "words", "value": [1, 2.5, None, True, "é"]}
    assert sayable(value) == value
    assert sayable("\ud800") == "\\ud800"
    assert sayable(float("nan")) == "nan"
