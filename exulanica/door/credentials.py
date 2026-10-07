"""The two secrets the door issues: a channel credential and an invite code.

**A channel credential** lets one bridge act under one grant. It is 32 random bytes, shown once to
whoever receives it and stored only as its SHA-256, so a copy of the database cannot be replayed as
a credential. High-entropy secrets need no slow hash: nobody can search 256 bits from a digest.

**An invite code** routes one player of a listed bridge to one grant. It is sixteen characters of
Crockford's base32 alphabet, 80 random bits, written as four groups of four so a person can copy it
from a page into a game's chat, or type it there. It is single use and expires in fifteen minutes,
and only a bridge presenting the deployment's own credential may redeem one, which counts and
limits its failed attempts. Typing is forgiving the way Crockford's alphabet intends: case, spaces
and hyphens are ignored, ``O`` reads as ``0`` and ``I`` and ``L`` as ``1``; anything else is not a
code.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Final

__all__ = [
    "CHANNEL_CREDENTIAL_BYTES",
    "CHANNEL_CREDENTIAL_FORM",
    "INVITE_ALPHABET",
    "INVITE_LENGTH",
    "credential_sha256",
    "format_invite_code",
    "new_channel_credential",
    "new_invite_code",
    "normalise_invite_code",
]

#: Random bytes in a channel credential. Its text is ``secrets.token_urlsafe`` of them: 43 URL-safe
#: characters, which also clears the 32-character floor the API's bearer tokens keep.
CHANNEL_CREDENTIAL_BYTES: Final = 32
#: What a channel credential looks like as the door writes it, so anything else is refused before a
#: digest is looked up: 43 characters of the URL-safe alphabet.
CHANNEL_CREDENTIAL_FORM: Final = re.compile(r"[A-Za-z0-9_-]{43}")
#: Crockford's base32 digits: no I, L, O or U, so no two read alike.
INVITE_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
#: Digits in an invite code: 80 bits, five to a digit.
INVITE_LENGTH: Final = 16
#: Digits in each group a code is written in.
_GROUP: Final = 4
#: What a typed code may contain besides digits, read as Crockford's decoding reads them.
_READ_AS: Final = {"O": "0", "I": "1", "L": "1"}
_IGNORED: Final = frozenset(" -")
#: The longest text read as a code, so a pasted paragraph is refused before it is scanned.
_TYPED_MAXIMUM: Final = 40


def credential_sha256(secret: str) -> str:
    """The digest a secret is stored and looked up by."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_channel_credential() -> str:
    """A fresh channel credential."""
    return secrets.token_urlsafe(CHANNEL_CREDENTIAL_BYTES)


def new_invite_code() -> str:
    """A fresh invite code, as its canonical digits."""
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


def format_invite_code(code: str) -> str:
    """A canonical code as a person reads it: four groups of four."""
    if len(code) != INVITE_LENGTH or any(digit not in INVITE_ALPHABET for digit in code):
        raise ValueError("not a canonical invite code")
    return "-".join(code[start : start + _GROUP] for start in range(0, INVITE_LENGTH, _GROUP))


def normalise_invite_code(typed: str) -> str | None:
    """The canonical digits of a typed code, or None when the text cannot be one."""
    if not isinstance(typed, str) or len(typed) > _TYPED_MAXIMUM:
        return None
    digits = []
    for character in typed.upper():
        if character in _IGNORED:
            continue
        character = _READ_AS.get(character, character)
        if character not in INVITE_ALPHABET:
            return None
        digits.append(character)
    return "".join(digits) if len(digits) == INVITE_LENGTH else None
