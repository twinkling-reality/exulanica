"""Which drafted notes may be kept: a model's own words, never a source's, and nothing personal.

A reader model drafts notes from a source's excerpts and picture descriptions, which are not ours to
keep. A note is kept only if it is one short line about one aspect of the reference catalogs, whole
(a note the length bound stopped inside a word, :func:`cut_at_bound`, is not: a note shows whole or
not at all), shares no run of :data:`COPY_RUN_WORDS` consecutive words with any of those texts, and
passes the outgoing screen (:func:`exulanica.references.boundary.screen_text`): no link, email
address, long number, screened word or withheld word. Everything else is dropped and counted by
reason; a dropped note is never quoted, since it may be a source's words.

Saved names are not judged here: a note reaches a hosted model only inside a drafter's request,
which the workspace's request policy judges like every other.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from exulanica.references.boundary import QueryRefused, screen_text, words_of
from exulanica.references.catalogs import ReferenceCatalogs, load_reference_catalogs

__all__ = [
    "COPY_RUN_WORDS",
    "MAX_NOTE_CHARACTERS",
    "NOTE_DROPS",
    "DraftedNote",
    "NoteScreen",
    "cut_at_bound",
    "keep_notes",
]

MAX_NOTE_CHARACTERS: Final = 80
#: A note sharing this many consecutive words with a source text is that text, not a note.
COPY_RUN_WORDS: Final = 6
NOTE_DROPS: Final = (
    "note_shape",
    "cut_word",
    "aspect_unknown",
    "copied_run",
    "duplicate",
    "link_or_contact",
    "long_number",
    "screened_word",
    "withheld_word",
)


@dataclass(frozen=True, slots=True)
class DraftedNote:
    """A note as a model drafted it, before it is judged."""

    aspect: str
    text: str


@dataclass(frozen=True, slots=True)
class NoteScreen:
    kept: tuple[DraftedNote, ...]
    #: How many notes each reason dropped. Counts only: a dropped note is never kept or quoted.
    dropped: Mapping[str, int]


def cut_at_bound(text: str) -> bool:
    """Whether a note reached the length bound ending inside a word: a reader's structured answer
    stops a longer note at the bound, wherever it falls, so such a note was cut there."""
    return len(text) >= MAX_NOTE_CHARACTERS and text[-1:].isalnum()


def _runs(text: str) -> set[tuple[str, ...]]:
    words = words_of(text)
    return {
        words[index : index + COPY_RUN_WORDS] for index in range(len(words) - COPY_RUN_WORDS + 1)
    }


def keep_notes(
    drafted: Sequence[DraftedNote],
    *,
    sources: Iterable[str],
    withheld_words: Iterable[str] = (),
    catalogs: ReferenceCatalogs | None = None,
) -> NoteScreen:
    """The notes of ``drafted`` that may be kept, judged against the texts they were drafted from.

    ``sources`` is every text the drafting model was shown: a web source's excerpts and picture
    descriptions. Notes read from a person's own picture are judged with ``sources`` empty.
    """
    catalogs = catalogs if catalogs is not None else load_reference_catalogs()
    withheld = tuple(withheld_words)
    copied: set[tuple[str, ...]] = set()
    for text in sources:
        copied |= _runs(text)
    kept: list[DraftedNote] = []
    dropped: Counter[str] = Counter()
    seen: set[str] = set()
    for note in drafted:
        text = note.text
        if (
            not isinstance(text, str)
            or not text.strip()
            or text != text.strip()
            or len(text) > MAX_NOTE_CHARACTERS
            or any(not character.isprintable() for character in text)
        ):
            dropped["note_shape"] += 1
            continue
        if cut_at_bound(text):
            dropped["cut_word"] += 1
            continue
        if note.aspect not in catalogs.aspects:
            dropped["aspect_unknown"] += 1
            continue
        if _runs(text) & copied:
            dropped["copied_run"] += 1
            continue
        try:
            screen_text(text, withheld_words=withheld, catalogs=catalogs)
        except QueryRefused as refusal:
            dropped[refusal.code] += 1
            continue
        if text.casefold() in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(text.casefold())
        kept.append(note)
    return NoteScreen(kept=tuple(kept), dropped=MappingProxyType(dict(dropped)))
