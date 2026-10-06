"""The reference bundle: the notes one drafter receives, and where each came from.

Profile ``exulanica.reference-bundle/v1``, a canonical JSON document named by the sha256 of its
bytes. It is drafting input, never world content and never a claim about the real world:

* ``notes``: at most :data:`MAX_NOTES`, each one line about one aspect, with its basis:
  ``web_description`` (drafted by a model from a web source's words, which are not kept) or
  ``own_picture`` (read by a vision model from a picture the person gave, under their consent),
  the latter naming its picture;
* ``lookups``: our own record of each search made for it, by id; no query result, address, title
  or picture of a source is here or anywhere else;
* ``pictures``: each picture the person gave, with the model rights it was read under and the
  model that read it;
* ``model_calls``: each planning, reading and vision call: the provider (the account it is charged
  to), role, model, tokens and USD, as the call reported them;
* ``outcome``: ``complete``, or ``partial`` with the steps that did not finish (a source down or
  out of budget, a deadline passed), so a drafter and the person see what is missing.

Every note's picture is one the bundle lists; a picture note without one, or a web note with one,
is refused. Integers and strings only: canonical JSON refuses a float.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.references.catalogs import ReferenceCatalogs, load_reference_catalogs
from exulanica.references.notes import MAX_NOTE_CHARACTERS

__all__ = [
    "BASES",
    "MAX_NOTES",
    "MAX_PICTURES",
    "MISSED_STEPS",
    "PROFILE",
    "PURPOSES",
    "BundleCall",
    "BundleError",
    "BundleNote",
    "BundlePicture",
    "ReferenceBundle",
    "read_bundle",
]

PROFILE: Final = "exulanica.reference-bundle/v1"
#: Which drafter a bundle serves. ``things`` is named for the thing-kind drafter to come.
PURPOSES: Final = ("world_draft", "kind", "look", "pieces", "things")
BASES: Final = ("web_description", "own_picture")
#: Steps a partial bundle may name as not finished.
MISSED_STEPS: Final = ("plan", "search", "read", "pictures")
OUTCOMES: Final = ("complete", "partial")
MAX_NOTES: Final = 24
MAX_PICTURES: Final = 4
MAX_LOOKUPS: Final = 3
MAX_MODEL_CALLS: Final = 16
MAX_RIGHTS: Final = 8
_KEYS: Final = frozenset(
    {
        "profile",
        "purpose",
        "workspace_id",
        "world_id",
        "notes",
        "lookups",
        "pictures",
        "model_calls",
        "outcome",
        "missed",
    }
)
_NOTE_KEYS: Final = frozenset({"aspect", "text", "basis", "picture_id"})
_PICTURE_KEYS: Final = frozenset({"picture_id", "model_right_ids", "model"})
_MODEL_KEYS: Final = frozenset({"provider", "role", "model_id"})
_CALL_KEYS: Final = frozenset(
    {"provider", "role", "model_id", "prompt_tokens", "completion_tokens", "usd"}
)
_USD: Final = re.compile(r"(0|[1-9][0-9]{0,5})\.[0-9]{8}")
_NAME: Final = re.compile(r"[a-z][a-z0-9_]{0,62}")
_MODEL_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


class BundleError(ValueError):
    """A document that is not a reference bundle, named by where it fails."""


@dataclass(frozen=True, slots=True)
class BundleNote:
    aspect: str
    text: str
    basis: str
    picture_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class BundleCall:
    """One model call a bundle took, charged to ``provider``'s account."""

    provider: str
    role: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    #: USD with eight decimal places, as the ledger writes it.
    usd: str


@dataclass(frozen=True, slots=True)
class BundlePicture:
    picture_id: uuid.UUID
    model_right_ids: tuple[uuid.UUID, ...]
    #: ``(provider, role, model_id)`` of the model that read it.
    model: tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class ReferenceBundle:
    purpose: str
    workspace_id: uuid.UUID
    world_id: uuid.UUID | None
    notes: tuple[BundleNote, ...]
    lookups: tuple[uuid.UUID, ...]
    pictures: tuple[BundlePicture, ...]
    model_calls: tuple[BundleCall, ...]
    outcome: str
    missed: tuple[str, ...]

    def __post_init__(self) -> None:
        # Every bundle, however it was built, is one read_bundle would accept.
        _parts(self.document(), load_reference_catalogs())

    def document(self) -> dict[str, Any]:
        return {
            "profile": PROFILE,
            "purpose": self.purpose,
            "workspace_id": str(self.workspace_id),
            "world_id": None if self.world_id is None else str(self.world_id),
            "notes": [
                {
                    "aspect": note.aspect,
                    "text": note.text,
                    "basis": note.basis,
                    "picture_id": None if note.picture_id is None else str(note.picture_id),
                }
                for note in self.notes
            ],
            "lookups": [str(item) for item in self.lookups],
            "pictures": [
                {
                    "picture_id": str(picture.picture_id),
                    "model_right_ids": [str(item) for item in picture.model_right_ids],
                    "model": dict(
                        zip(("provider", "role", "model_id"), picture.model, strict=True)
                    ),
                }
                for picture in self.pictures
            ],
            "model_calls": [
                {
                    "provider": call.provider,
                    "role": call.role,
                    "model_id": call.model_id,
                    "prompt_tokens": call.prompt_tokens,
                    "completion_tokens": call.completion_tokens,
                    "usd": call.usd,
                }
                for call in self.model_calls
            ],
            "outcome": self.outcome,
            "missed": list(self.missed),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.document())

    @property
    def digest(self) -> str:
        """The bundle's name: the sha256 of its canonical bytes, in lowercase hex."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @property
    def picture_ids(self) -> frozenset[uuid.UUID]:
        """Every picture a note was read from: what a drafter's request must declare."""
        return frozenset(note.picture_id for note in self.notes if note.picture_id is not None)


def _object(where: str, value: object, keys: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BundleError(f"{where} is an object with exactly {sorted(keys)}")
    return value


def _list(where: str, value: object, maximum: int) -> Sequence[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise BundleError(f"{where} is a list of at most {maximum}")
    return value


def _choice(where: str, value: object, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise BundleError(f"{where} is one of {list(choices)}")
    return str(value)


def _uuid(where: str, value: object) -> uuid.UUID:
    if not isinstance(value, str):
        raise BundleError(f"{where} is an id")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise BundleError(f"{where} is an id") from error
    if str(parsed) != value:
        raise BundleError(f"{where} is an id in its lowercase hyphenated spelling")
    return parsed


def _ids(where: str, value: object, maximum: int) -> tuple[uuid.UUID, ...]:
    ids = tuple(
        _uuid(f"{where}[{index}]", item) for index, item in enumerate(_list(where, value, maximum))
    )
    if len(set(ids)) != len(ids):
        raise BundleError(f"{where} names an id twice")
    return ids


def _model(where: str, provider: object, role: object, model_id: object) -> tuple[str, str, str]:
    if not (
        isinstance(provider, str)
        and _NAME.fullmatch(provider)
        and isinstance(role, str)
        and _NAME.fullmatch(role)
        and isinstance(model_id, str)
        and _MODEL_ID.fullmatch(model_id)
    ):
        raise BundleError(f"{where} names a provider, a role and a model")
    return provider, role, model_id


def _call(where: str, value: object) -> BundleCall:
    call = _object(where, value, _CALL_KEYS)
    provider, role, model_id = _model(where, call["provider"], call["role"], call["model_id"])
    counts = (call["prompt_tokens"], call["completion_tokens"])
    if any(type(count) is not int or count < 0 for count in counts):
        raise BundleError(f"{where} states its tokens as whole numbers")
    usd = call["usd"]
    if not isinstance(usd, str) or _USD.fullmatch(usd) is None:
        raise BundleError(f"{where}.usd is USD with eight decimal places, as a string")
    return BundleCall(provider, role, model_id, *counts, usd)  # type: ignore[arg-type]


def read_bundle(document: object, *, catalogs: ReferenceCatalogs | None = None) -> ReferenceBundle:
    """``document`` as a reference bundle, or :class:`BundleError` naming where it fails."""
    return ReferenceBundle(
        **_parts(document, catalogs if catalogs is not None else load_reference_catalogs())
    )


def _parts(document: object, catalogs: ReferenceCatalogs) -> dict[str, Any]:
    raw = _object("the bundle", document, _KEYS)
    if raw["profile"] != PROFILE:
        raise BundleError(f"the bundle's profile is {PROFILE}")
    try:
        canonical_json(dict(raw))
    except Exception as error:  # a float, or any other value canonical JSON refuses
        raise BundleError(f"the bundle is not canonical JSON: {error}") from error
    pictures: list[BundlePicture] = []
    for index, item in enumerate(_list("pictures", raw["pictures"], MAX_PICTURES)):
        where = f"pictures[{index}]"
        picture = _object(where, item, _PICTURE_KEYS)
        model = _object(f"{where}.model", picture["model"], _MODEL_KEYS)
        provider, role, model_id = _model(
            f"{where}.model", model["provider"], model["role"], model["model_id"]
        )
        rights = _ids(f"{where}.model_right_ids", picture["model_right_ids"], MAX_RIGHTS)
        if not rights:
            raise BundleError(f"{where} was read under at least one model right")
        pictures.append(
            BundlePicture(
                picture_id=_uuid(f"{where}.picture_id", picture["picture_id"]),
                model_right_ids=rights,
                model=(provider, role, model_id),
            )
        )
    listed = [picture.picture_id for picture in pictures]
    if len(set(listed)) != len(listed):
        raise BundleError("pictures lists a picture twice")
    notes: list[BundleNote] = []
    for index, item in enumerate(_list("notes", raw["notes"], MAX_NOTES)):
        where = f"notes[{index}]"
        note = _object(where, item, _NOTE_KEYS)
        aspect = _choice(f"{where}.aspect", note["aspect"], tuple(catalogs.aspects))
        text = note["text"]
        if (
            not isinstance(text, str)
            or not text.strip()
            or text != text.strip()
            or len(text) > MAX_NOTE_CHARACTERS
        ):
            raise BundleError(
                f"{where}.text is one line of at most {MAX_NOTE_CHARACTERS} characters"
            )
        basis = _choice(f"{where}.basis", note["basis"], BASES)
        picture_id = (
            None if note["picture_id"] is None else _uuid(f"{where}.picture_id", note["picture_id"])
        )
        if (basis == "own_picture") != (picture_id is not None):
            raise BundleError(f"{where}: exactly a note read from a picture names its picture")
        if picture_id is not None and picture_id not in listed:
            raise BundleError(f"{where} names a picture the bundle does not list")
        notes.append(BundleNote(aspect=aspect, text=text, basis=basis, picture_id=picture_id))
    outcome = _choice("outcome", raw["outcome"], OUTCOMES)
    missed = tuple(
        _choice(f"missed[{index}]", step, MISSED_STEPS)
        for index, step in enumerate(_list("missed", raw["missed"], len(MISSED_STEPS)))
    )
    if len(set(missed)) != len(missed) or (outcome == "partial") != bool(missed):
        raise BundleError("exactly a partial bundle names the steps it missed, each once")
    world = raw["world_id"]
    return dict(
        purpose=_choice("purpose", raw["purpose"], PURPOSES),
        workspace_id=_uuid("workspace_id", raw["workspace_id"]),
        world_id=None if world is None else _uuid("world_id", world),
        notes=tuple(notes),
        lookups=_ids("lookups", raw["lookups"], MAX_LOOKUPS),
        pictures=tuple(pictures),
        model_calls=tuple(
            _call(f"model_calls[{index}]", item)
            for index, item in enumerate(_list("model_calls", raw["model_calls"], MAX_MODEL_CALLS))
        ),
        outcome=outcome,
        missed=missed,
    )
