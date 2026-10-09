"""A line: one plain line of words, held to one rule wherever words are stored or said.

The rule covers everything a thing says and every word a translation states about what came
across: one line of 1 to 200 code points in Unicode normal form C, with no control, format,
surrogate, private-use, line-separator or paragraph-separator character (Unicode categories Cc,
Cf, Cs, Co, Zl and Zp) and no white space at either end. A line not already in normal form C is
refused rather than rewritten, so what is stored is what was written; a caller holding text from
outside normalises it first and stores the normal form.

A decision's terms may hold a model's lines to more (:data:`LINE_RULES`): under terms that state
``names_no_listener``, a line said to one being does not end with that being's name or description
(:func:`names_listener`), as the option offering it names them.

Pure: no connection, no store.
"""

from __future__ import annotations

import unicodedata
from typing import Final

__all__ = [
    "HEARD_LINES_MAXIMUM",
    "LINE_CHARACTERS_MAXIMUM",
    "LINE_RULES",
    "LineRefused",
    "check_line",
    "listener_forms",
    "names_listener",
]

#: The most code points one line holds.
LINE_CHARACTERS_MAXIMUM: Final = 200
#: The most lines one being may keep, whatever a contract keeps: the bound on the field.
HEARD_LINES_MAXIMUM: Final = 64
#: Characters no line holds: they would break a line, hide text or carry no meaning a reader sees.
_REFUSED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})
#: The rules beside the line rule that a decision's terms may hold a model's lines to, by name.
LINE_RULES: Final = frozenset({"names_no_listener"})
#: The articles a being's kind is described with.
_ARTICLES: Final = ("a ", "an ", "the ")


class LineRefused(ValueError):
    """Text that is not one plain line within the bound."""

    code: Final = "line_out_of_bounds"


def check_line(value: object, *, maximum: int = LINE_CHARACTERS_MAXIMUM) -> str:
    """``value`` as a line, or :class:`LineRefused` saying which rule it breaks."""
    if not isinstance(value, str):
        raise LineRefused("a line is text")
    if unicodedata.normalize("NFC", value) != value:
        raise LineRefused("a line is in Unicode normal form C")
    if not 1 <= len(value) <= maximum:
        raise LineRefused(f"a line holds 1 to {maximum} code points")
    if value != value.strip():
        raise LineRefused("a line has no white space at either end")
    if any(unicodedata.category(character) in _REFUSED_CATEGORIES for character in value):
        raise LineRefused("a line holds no control, format or separator character")
    return value


def listener_forms(listener: str) -> tuple[str, ...]:
    """How a line could name or describe the being it is said to, from the name its option gives
    it (as the page names it), case folded: the name itself; for "Ari Ash 1 (a villager)" also its
    name and its kind with and without an article ("ari ash 1", "a villager", "the villager",
    "villager"); for "the knight" its kind with another article and without one."""
    name = listener.casefold().strip()
    forms = [name]
    kind = None
    if name.endswith(")") and " (" in name:
        own, _, described = name[:-1].rpartition(" (")
        forms.append(own)
        kind = described
    elif name.startswith(_ARTICLES):
        kind = name
    if kind is not None:
        bare = next((kind[len(a) :] for a in _ARTICLES if kind.startswith(a)), kind)
        some = "an " if bare[:1] in ("a", "e", "i", "o", "u") else "a "
        forms.extend((f"{some}{bare}", f"the {bare}", bare))
    return tuple(dict.fromkeys(form for form in forms if form))


def names_listener(line: str, listener: str) -> bool:
    """Whether ``line`` ends with the name or description of the being it is said to
    (:func:`listener_forms`), with case, white space and punctuation at its end set aside: "The
    night deepens, a villager." names its listener; "The villager's cart is full." does not."""
    text = line.casefold().rstrip()
    while text and (text[-1].isspace() or unicodedata.category(text[-1]).startswith("P")):
        text = text[:-1]
    for form in listener_forms(listener):
        if text.endswith(form):
            before = text[: -len(form)]
            if not before or not before[-1].isalnum():
                return True
    return False
