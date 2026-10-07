"""Notes from a person's own picture: the one reading call, and what every note it writes must pass.

What a picture may become is fixed here, before any model sees one. The reading call, on the
``reference_vision`` role, answers a strict form: ``refuse`` (one of :data:`REFUSALS`, or null)
and then at most the prompt's number of notes, each about one of the aspects open to pictures. A
refusal keeps nothing of the picture but its reason. Nothing in a picture is located, cropped or
compared, and the form has no field for a person, a place name or any writing.

Every note kept then passes :func:`screen_picture_notes`: its aspect must be open to pictures, it
may hold no word of the picture screen (``reference-picture-screen.v1.json``), no capitalised
word inside a sentence (lettering or a proper name read from the picture), no quotation mark, and
no word cut at the length bound; then the screen every note passes (links, email addresses, long
numbers, screened words and the account's withheld words). A word list catches only the words it
lists, so the reading model is also told to refuse a picture showing a person.

The call declares its picture as a photograph, so the workspace's request policy refuses it unless
a current right names this role's chain for that picture.
"""

from __future__ import annotations

import functools
import itertools
import re
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
from exulanica.models.manifest import Role
from exulanica.models.messages import image_part, text_part
from exulanica.models.results import ChatResult
from exulanica.references.catalogs import ReferenceCatalogs, load_reference_catalogs
from exulanica.references.drafting import ReferencePrompts, reference_prompts
from exulanica.references.notes import MAX_NOTE_CHARACTERS, DraftedNote, NoteScreen, keep_notes

__all__ = [
    "PICTURE_DROPS",
    "PICTURE_ROLE",
    "REFUSALS",
    "PictureRead",
    "picture_user_text",
    "read_picture",
    "screen_picture_notes",
]

PICTURE_ROLE: Final = Role.REFERENCE_VISION
#: The completion ceiling of one reading: six notes of at most 80 characters with their aspects
#: are under 200 tokens (the timeout basis's longest answer was 157).
PICTURE_MAX_TOKENS: Final = 512
#: Why a reading refuses a whole picture, as the page names it.
REFUSALS: Final = ("shows_people", "shows_text", "not_a_place")
#: Why a note from a picture is dropped before the screen every note passes.
PICTURE_DROPS: Final = ("aspect_closed", "person_word", "lettering", "cut_word")
_WORD: Final = re.compile(r"[a-z]+")
#: Double quotation marks, straight, curly and angled: an apostrophe is a word's, not a quote.
_QUOTES: Final = frozenset(chr(code) for code in (0x22, 0x201C, 0x201D, 0xAB, 0xBB))
_SENTENCE_ENDS: Final = (".", "!", "?", ":", ";")


@dataclass(frozen=True, slots=True)
class PictureRead:
    """What one reading wrote, or the reason it kept nothing, and the call when one was made."""

    notes: tuple[DraftedNote, ...] = ()
    refused: str | None = None
    call: ChatResult | None = None


def picture_user_text(catalogs: ReferenceCatalogs) -> str:
    """The words beside the picture: the aspects open to pictures, one per line."""
    lines = "\n".join(f"- {key}" for key in catalogs.picture_aspects)
    return f"The aspects:\n{lines}\nThe picture:"


@functools.cache
def _schema(aspects: tuple[str, ...], notes: int) -> type[BaseModel]:
    note = create_model(
        "PictureNote",
        __config__=ConfigDict(extra="forbid"),
        aspect=(Literal[aspects], ...),  # type: ignore[valid-type]
        text=(str, Field(min_length=1, max_length=MAX_NOTE_CHARACTERS)),
    )
    return create_model(
        "PictureReading",
        __config__=ConfigDict(extra="forbid"),
        refuse=(Literal[REFUSALS] | None, ...),  # type: ignore[valid-type]
        notes=(list[note], Field(max_length=notes)),  # type: ignore[valid-type]
    )


def _within(client: ModelClient, deadline_s: float | None) -> float | None:
    if deadline_s is None:
        return None
    return min(deadline_s, float(client.manifest[PICTURE_ROLE].timeout_seconds))


def read_picture(
    client: ModelClient,
    image: bytes,
    *,
    capture_id: uuid.UUID,
    prompts: ReferencePrompts | None = None,
    catalogs: ReferenceCatalogs | None = None,
    deadline_s: float | None = None,
) -> PictureRead:
    """One reading of ``image``, the rendition of ``capture_id``, within ``deadline_s`` when given.

    The picture is declared as ``capture_id``, so the request policy asks for that picture's right
    before anything is sent. A refusal or a form the model could not complete keeps no note.
    """
    prompts = prompts if prompts is not None else reference_prompts()
    catalogs = catalogs if catalogs is not None else load_reference_catalogs()
    schema = _schema(catalogs.picture_aspects, prompts.picture_notes_maximum)
    messages = [
        {"role": "system", "content": prompts.picture},
        {
            "role": "user",
            "content": [text_part(picture_user_text(catalogs)), image_part(image)],
        },
    ]
    try:
        drafted = client.structured(
            PICTURE_ROLE,
            messages,
            schema,
            prompt_version=prompts.picture_version,
            max_tokens=PICTURE_MAX_TOKENS,
            image_prompt_tokens=client.manifest[PICTURE_ROLE].image_reservation(1),
            photographs=(capture_id,),
            arrays_last=True,
            deadline_s=_within(client, deadline_s),
        )
    except TruncatedResponseError:
        return PictureRead(refused="read_truncated")
    except StructuredOutputError:
        return PictureRead(refused="read_refused")
    value = drafted.value
    if value.refuse is not None:  # type: ignore[attr-defined]
        return PictureRead(refused=value.refuse, call=drafted.call)  # type: ignore[attr-defined]
    return PictureRead(
        notes=tuple(DraftedNote(item.aspect, item.text) for item in value.notes),  # type: ignore[attr-defined]
        call=drafted.call,
    )


def _lettering(text: str) -> bool:
    """A quotation mark, or a capitalised word that does not begin a sentence."""
    if any(character in _QUOTES for character in text):
        return True
    words = text.split()
    for previous, word in itertools.pairwise(words):
        if word[:1].isupper() and not previous.endswith(_SENTENCE_ENDS):
            return True
    return False


def _cut(text: str) -> bool:
    """A note that reached the length bound ending inside a word was cut there."""
    return len(text) >= MAX_NOTE_CHARACTERS and text[-1:].isalnum()


def screen_picture_notes(
    drafted: Sequence[DraftedNote],
    *,
    withheld_words: Iterable[str] = (),
    catalogs: ReferenceCatalogs | None = None,
) -> NoteScreen:
    """The notes of ``drafted``, read from a person's own picture, that may be kept."""
    catalogs = catalogs if catalogs is not None else load_reference_catalogs()
    dropped: Counter[str] = Counter()
    passed: list[DraftedNote] = []
    for note in drafted:
        text = note.text if isinstance(note.text, str) else ""
        if note.aspect not in catalogs.picture_aspects:
            dropped["aspect_closed"] += 1
        elif any(word in catalogs.picture_screened for word in _WORD.findall(text.lower())):
            dropped["person_word"] += 1
        elif _lettering(text):
            dropped["lettering"] += 1
        elif _cut(text):
            dropped["cut_word"] += 1
        else:
            passed.append(note)
    screened = keep_notes(passed, sources=(), withheld_words=withheld_words, catalogs=catalogs)
    dropped.update(screened.dropped)
    return NoteScreen(kept=screened.kept, dropped=MappingProxyType(dict(dropped)))
