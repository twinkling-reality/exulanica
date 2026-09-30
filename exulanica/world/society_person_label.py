"""Public, synthetic labels for people in either society state family."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def person_label(person: Mapping[str, Any]) -> str:
    """Use a recorded name, or the living resident's stable ordinal."""
    name = person.get("display_name")
    if isinstance(name, str) and name:
        return name
    ordinal = person.get("ordinal")
    if type(ordinal) is int and ordinal >= 0:
        return f"Resident {ordinal + 1}"
    raise ValueError("society person has neither a name nor a living ordinal")
