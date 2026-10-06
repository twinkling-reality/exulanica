"""The one way a search subject becomes a query that may leave for a reference source.

A source's terms make every query it receives permanent and theirs: Tavily, the first source,
holds a perpetual licence to every query, may train models on it and may pass it to other search
indexes. So a query carries nothing of a person, and :func:`admit_query` is the only constructor of
the :class:`AdmittedQuery` an adapter will send. It judges one subject in order:

1.  **Shape.** One line of at most :data:`MAX_QUERY_CHARACTERS` characters and
    :data:`MAX_QUERY_WORDS` words, about one aspect of the reference catalogs.
2.  **The workspace's hosted request policy**, the same object every model call passes: a person's
    saved name never goes, and a saved place's name goes only where a right releases it for this
    hand-over (none names a search source). The hand-over names the source as its one identity at
    its one origin. A subject the policy changes at all, or that carries a placeholder, is refused
    rather than sent with a placeholder in it: a query about "[place AB]" finds nothing and says
    that a name was there.
3.  **The screen.** No link, email address, long number or run of digits; none of the words the
    query-screen catalog lists (first-person words, credentials, identifiers, financial, health and
    contact words); none of the caller's withheld words (the account's own display name and email,
    which no saved name covers).

A subject comes only from the person's typed words, after saved names are replaced, or from catalog
words. Text derived from a photograph is never a subject: the caller has no path to pass one, since
nothing here takes a photograph, and a policy that is scoped to photographs refuses the request.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from exulanica.epistemics.saved_names import PLACEHOLDER
from exulanica.errors import ExulanicaError
from exulanica.models.handoff import ModelHandoff, ModelIdentity
from exulanica.models.policy import HostedRequest, HostedRequestPolicy
from exulanica.references.catalogs import (
    ReferenceCatalogs,
    ReferenceSource,
    load_reference_catalogs,
)

__all__ = [
    "MAX_QUERY_CHARACTERS",
    "MAX_QUERY_WORDS",
    "REFUSALS",
    "SEARCH_ROLE",
    "AdmittedQuery",
    "QueryRefused",
    "SearchSubject",
    "admit_query",
    "screen_text",
    "source_handoff",
    "words_of",
]

#: The role a search hand-over is judged under. Not a manifest role: no model answers it.
SEARCH_ROLE: Final = "reference_search"
MAX_QUERY_CHARACTERS: Final = 80
MAX_QUERY_WORDS: Final = 8
#: Every reason a subject is refused, by code.
REFUSALS: Final = (
    "query_shape",
    "aspect_unknown",
    "names_withheld",
    "link_or_contact",
    "long_number",
    "screened_word",
    "withheld_word",
)

_WORD: Final = re.compile(r"[a-z0-9]+")
_LINK_OR_CONTACT: Final = re.compile(r"@|://|\bwww\b|[a-z0-9]\.[a-z]{2,}\b", re.IGNORECASE)
_DIGIT_RUN: Final = re.compile(r"\d{5,}")
#: Digits anywhere in a query, past which they could spell a phone number or an address.
_MAX_DIGITS: Final = 6
#: A withheld word shorter than this is too common to screen ("of", "la"); saved names are
#: matched by the policy, which knows their parts.
_MIN_WITHHELD_LETTERS: Final = 3
_SEAL: Final = object()


class QueryRefused(ExulanicaError):
    """A subject that may not leave. ``code`` is one of :data:`REFUSALS`; nothing is quoted."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in REFUSALS:
            raise ValueError(f"unknown refusal {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True, slots=True)
class SearchSubject:
    """What to search for and which aspect of a world it is about, before the boundary."""

    text: str
    aspect: str


@dataclass(frozen=True, slots=True)
class AdmittedQuery:
    """A query that passed the boundary for one source. Built only by :func:`admit_query`."""

    source: str
    text: str
    aspect: str
    seal: object

    def __post_init__(self) -> None:
        if self.seal is not _SEAL:
            raise TypeError("an admitted query is built by admit_query and nothing else")


def words_of(text: str) -> tuple[str, ...]:
    """The lowercase words of ``text``, letters and digits only, in order."""
    return tuple(_WORD.findall(text.lower()))


def source_handoff(source: ReferenceSource) -> ModelHandoff:
    """The hand-over a query to ``source`` is judged as: the source itself, at its origin."""
    return ModelHandoff(
        identities=(
            ModelIdentity(
                provider=source.key, role=SEARCH_ROLE, model_id=source.key, revision=None
            ),
        ),
        destination=source.egress_origin,
    )


def admit_query(
    subject: SearchSubject,
    *,
    source: ReferenceSource,
    policy: HostedRequestPolicy,
    withheld_words: Iterable[str] = (),
    catalogs: ReferenceCatalogs | None = None,
) -> AdmittedQuery:
    """``subject`` as a query that may leave for ``source``, or :class:`QueryRefused`."""
    catalogs = catalogs if catalogs is not None else load_reference_catalogs()
    text = subject.text
    if (
        not isinstance(text, str)
        or not text.strip()
        or text != text.strip()
        or len(text) > MAX_QUERY_CHARACTERS
        or len(text.split()) > MAX_QUERY_WORDS
        or any(not character.isprintable() for character in text)
    ):
        raise QueryRefused(
            "query_shape",
            f"a query is one line of at most {MAX_QUERY_WORDS} words and "
            f"{MAX_QUERY_CHARACTERS} characters",
        )
    if subject.aspect not in catalogs.aspects:
        raise QueryRefused("aspect_unknown", "a query is about one aspect the catalog names")
    admitted = tuple(
        policy.admit(
            HostedRequest(
                role=SEARCH_ROLE,
                handoff=source_handoff(source),
                texts=(text,),
                instructions=(),
                photographs=frozenset(),
                images=0,
            )
        )
    )
    if admitted != (text,) or PLACEHOLDER.search(text) is not None:
        raise QueryRefused("names_withheld", "the subject named something that may not leave")
    screen_text(text, withheld_words=withheld_words, catalogs=catalogs)
    return AdmittedQuery(source=source.key, text=text, aspect=subject.aspect, seal=_SEAL)


def screen_text(
    text: str,
    *,
    withheld_words: Iterable[str] = (),
    catalogs: ReferenceCatalogs | None = None,
) -> None:
    """Refuse ``text`` if it carries a link, a long number, a screened word or a withheld word.

    The screen every outgoing query passes after the request policy, and every kept note passes.
    """
    catalogs = catalogs if catalogs is not None else load_reference_catalogs()
    if _LINK_OR_CONTACT.search(text) is not None:
        raise QueryRefused(
            "link_or_contact", "nothing that leaves carries a link or an email address"
        )
    if _DIGIT_RUN.search(text) is not None or sum(c.isdigit() for c in text) > _MAX_DIGITS:
        raise QueryRefused("long_number", "nothing that leaves carries a long number")
    words = words_of(text)
    for phrase, category in catalogs.screened.items():
        span = len(phrase)
        if any(words[index : index + span] == phrase for index in range(len(words))):
            raise QueryRefused("screened_word", f"nothing that leaves carries a {category} word")
    withheld = {
        word
        for item in withheld_words
        for word in words_of(item)
        if len(word) >= _MIN_WITHHELD_LETTERS
    }
    if withheld & set(words):
        raise QueryRefused(
            "withheld_word", "nothing that leaves carries a word of the account's own"
        )
