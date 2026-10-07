"""The channel's documents: what a bridge is sent, what it may send, and their bounds.

Every document the door sends a bridge is a **frame** of ``exulanica.door-frame/v1``, delivered in
a poll's answer beside an opaque **cursor**; the bridge sends the cursor back with its next poll and
receives what came after it. A bridge reads only response bodies: some game engines hand their
scripts a response's status and body and never its headers, so nothing here depends on a header.

Frames come from two sources. An **ask** is written for the bridge by the decision host, one row per
request it reserved for a thing this grant decides for. Everything else is a **projection** of a
record that exists anyway: the receipt the host recorded for an answer (``outcome``) and the grant's
own revisions (``grant``, and ``grant_ended`` once it is revoked or past its end). A frame
therefore never disagrees with the history it reports.

An ``asked`` frame carries the request's context byte for byte as a model reads it, with the role's
instruction and the description of the one choice, and the same request rendered as a model is sent
it: the role's own messages, the one function a model is forced to call (``act``), and the world
minute it was asked at. So an agent behind a bridge reads the same words a model does and nothing a
model would not, and no adapter renders a role's words a second time. One poll's answer stops adding
asked frames once it reaches :data:`ASKED_BYTES_MAXIMUM`; the next poll reads on.

Bounds are declared here once and enforced where each document is read: a body's size by the
application's body limit before it is parsed (``exulanica.api.routes.door.BODY_LIMITS``), and its
fields where the door reads them. Nothing a bridge sends has a free-form field: every body is a
closed schema, and an unknown field is refused. Every text a person reads from a bridge or about
one (a line, a mapping's words, the name and maker a program declares) meets the one line rule
every thing's words meet (:func:`exulanica.things.lines.check_line`), through
:func:`words_fault`: one line in Unicode NFC of a bounded number of code points, with no control,
format, surrogate, private use or separator character.

How long a poll is held and how long the host waits for an answer belong to each bridge
(``exulanica.door.bridges``): a game whose scripts wait 20 s for an HTTP answer and an agent that
takes a model call to choose need different figures. The defaults here are the first game's.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.things.lines import LineRefused, check_line

__all__ = [
    "ANSWER_BODY_BYTES",
    "ASKED_BYTES_MAXIMUM",
    "DEADLINE_MS_DEFAULT",
    "DECLARED_CHARACTERS_MAXIMUM",
    "DECLARED_MIND_MAXIMUM",
    "FRAMES_PER_POLL",
    "FRAME_PROFILE",
    "HELLO_BODY_BYTES",
    "HOLD_SECONDS_DEFAULT",
    "HOLD_SECONDS_MAXIMUM",
    "LINE_CHARACTERS_MAXIMUM",
    "MAPPING_PROFILE",
    "OWNER_BODY_BYTES",
    "QUIET_SECONDS",
    "READS_MAXIMUM",
    "REDEEM_BODY_BYTES",
    "WORDS_CHARACTERS_MAXIMUM",
    "Cursor",
    "InvalidCursor",
    "answer_sha256",
    "asked_frame",
    "declared_fault",
    "grant_ended_frame",
    "grant_frame",
    "outcome_frame",
    "words_fault",
]

FRAME_PROFILE: Final = "exulanica.door-frame/v1"
MAPPING_PROFILE: Final = "exulanica.bridge-mapping/v1"

#: The longest a poll is held open with nothing to send, in seconds, unless a bridge declares its
#: own. Under the 20 s the first game engine's HTTP client waits by default, so the hold ends before
#: the client gives up.
HOLD_SECONDS_DEFAULT: Final = 15
#: The longest hold a bridge may declare: under the 30 s an idle proxy commonly allows a connection.
HOLD_SECONDS_MAXIMUM: Final = 25
#: A grant whose bridge has not polled for its hold and this long after it is quiet: its asks are
#: answered at once with ``decider_disconnected`` rather than waited for.
QUIET_SECONDS: Final = 10
#: How long the decision host waits for a bridge's answer to one ask, unless the bridge declares its
#: own; every external request records it as its ``deadline_ms``. The path it covers: the ask wakes
#: a held poll at once in the process that wrote it, or within a second elsewhere; the frame crosses
#: the network; a game's server reads it at its next step (about 0.1 s); its answer crosses back and
#: wakes the waiting asker. Three seconds leaves room for a public network and is under half of the
#: 8 s a world minute takes at normal speed, so a missing bridge costs a minute little. A declared
#: figure, to be replaced by the latencies a recorded run measures. A bridge's own figure is bounded
#: by the role contract's ``decision_deadline_ms``, which the host enforces as well.
DEADLINE_MS_DEFAULT: Final = 3000
#: The most frames one poll's answer carries; a bridge with more waiting polls again at once.
FRAMES_PER_POLL: Final = 32
#: The most bytes of asked frames one poll's answer carries past its first, in canonical JSON: a
#: context is at most 12,000 bytes and its rendering about as much again, so eight or so asks a
#: poll, and never a 32-frame answer of nearly a megabyte.
ASKED_BYTES_MAXIMUM: Final = 262144
#: Body bounds, in bytes of the request as it arrives, refused before the body is parsed. An answer
#: holds two identifiers, a label and a line of at most 200 code points, which JSON escapes may
#: spell in up to twelve bytes each; a hello holds the mapping file.
ANSWER_BODY_BYTES: Final = 4096
HELLO_BODY_BYTES: Final = 65536
REDEEM_BODY_BYTES: Final = 1024
#: An owner's grant routes: a scope of ids, kinds and words.
OWNER_BODY_BYTES: Final = 4096
#: The most code points in a line a bridge sends, the role policy's own bound.
LINE_CHARACTERS_MAXIMUM: Final = 200
#: The most code points in a mapping's words and reason words.
WORDS_CHARACTERS_MAXIMUM: Final = 200
#: The most code points in the name or the maker a program declares at hello, and in the mind it
#: says it thinks with (a model's id may be long).
DECLARED_CHARACTERS_MAXIMUM: Final = 40
DECLARED_MIND_MAXIMUM: Final = 60
#: How many game fields an adapter may declare it reads.
READS_MAXIMUM: Final = 64

#: Declared words are allowed, never listed against: letters, marks and digits of any script, and
#: these few marks. No colon or at sign, so no scheme or address reads as one.
_DECLARED_MARKS: Final = frozenset(" .,'&()_+-")
#: A dotted host name, such as a web address without its scheme, which the allowed marks could
#: still spell: in any script (a letter or digit, a dot, then two letters), or an IPv4 address.
#: Read after compatibility folding and without combining marks, so fullwidth letters spell what
#: they look like and no mark written before the dot hides the letter it follows.
_HOST: Final = re.compile(r"[^\W_]\.[^\W\d_]{2,}|\d{1,3}(?:\.\d{1,3}){3}")

_CURSOR_VERSION: Final = 1
_CURSOR_FIELDS: Final = frozenset({"v", "ask", "outcome", "grant", "ended"})
_CURSOR_TEXT_MAXIMUM: Final = 200
_SEQUENCE_MAXIMUM: Final = 2**62


class InvalidCursor(ValueError):
    """A cursor this door did not write."""

    code: Final = "invalid_cursor"


@dataclass(frozen=True, slots=True)
class Cursor:
    """How far a bridge has read: the last ask, the last outcome, the grant revision it was sent,
    and whether it was told the grant ended.

    ``outcome`` counts asks whose receipts were reported, in ask order, so it never passes ``ask``.
    Encoded as URL-safe base64 of its canonical JSON; a bridge treats it as opaque.
    """

    ask: int = 0
    outcome: int = 0
    grant: int = 0
    ended: bool = False

    def __post_init__(self) -> None:
        for value in (self.ask, self.outcome, self.grant):
            if type(value) is not int or not 0 <= value <= _SEQUENCE_MAXIMUM:
                raise InvalidCursor("a cursor counts whole numbers from zero")
        if type(self.ended) is not bool:
            raise InvalidCursor("a cursor says whether the end was reported")
        if self.outcome > self.ask:
            raise InvalidCursor("a cursor reports no outcome of an ask it has not seen")

    def encode(self) -> str:
        document = {
            "v": _CURSOR_VERSION,
            "ask": self.ask,
            "outcome": self.outcome,
            "grant": self.grant,
            "ended": self.ended,
        }
        return base64.urlsafe_b64encode(canonical_json(document)).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, text: str | None) -> Cursor:
        """The cursor ``text`` encodes; none for a bridge's first poll; or refuse by name."""
        if text is None or text == "":
            return cls()
        if not isinstance(text, str) or len(text) > _CURSOR_TEXT_MAXIMUM:
            raise InvalidCursor("not a cursor")
        try:
            raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
            document = json.loads(raw)
        except (binascii.Error, ValueError) as exc:
            raise InvalidCursor("not a cursor") from exc
        if (
            not isinstance(document, dict)
            or set(document) != _CURSOR_FIELDS
            or document["v"] != _CURSOR_VERSION
        ):
            raise InvalidCursor("not a cursor")
        cursor = cls(
            ask=document["ask"],
            outcome=document["outcome"],
            grant=document["grant"],
            ended=document["ended"],
        )
        if cursor.encode() != text:
            raise InvalidCursor("not a cursor")
        return cursor


def words_fault(text: object, *, maximum: int) -> str | None:
    """Why ``text`` is not words a person may read here, or None: the line rule
    (:func:`exulanica.things.lines.check_line`) with ``maximum`` code points."""
    try:
        check_line(text, maximum=maximum)
    except LineRefused as exc:
        return str(exc)
    return None


def declared_fault(text: object, *, maximum: int, slash: bool = False) -> str | None:
    """Why ``text`` is not words a program may declare about itself, or None: the words rule, then
    only letters, marks and digits of any script and ``. , ' & ( ) _ + -`` (and ``/`` where
    ``slash``, for a model's id), and no dotted host name. Declared words name a program, its maker
    and its mind on a card; they never send a person anywhere."""
    fault = words_fault(text, maximum=maximum)
    if fault is not None:
        return fault
    assert isinstance(text, str)
    marks = _DECLARED_MARKS | ({"/"} if slash else set())
    if not all(
        unicodedata.category(character)[0] in "LMN" or character in marks for character in text
    ):
        return "holds only letters, digits, spaces and . , ' & ( ) _ + -" + (" /" if slash else "")
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKC", text)
        if unicodedata.category(character)[0] != "M"
    )
    if _HOST.search(folded):
        return "holds no host name"
    return None


def answer_sha256(document: Mapping[str, Any]) -> str:
    """The digest of an answer as the bridge sent it, which its receipt records."""
    return hashlib.sha256(canonical_json(dict(document))).hexdigest()


def asked_frame(
    *,
    ask_seq: int,
    request: Mapping[str, Any],
    instruction: str,
    choice_description: str,
    deadline_ms: int,
    messages: list[dict[str, str]],
    act: Mapping[str, Any],
) -> dict[str, Any]:
    """The frame asking a bridge to choose for one thing: the request as a model is asked it, its
    context and the role's words, and the same request rendered as a model is sent it."""
    return {
        "kind": "asked",
        "ask_seq": ask_seq,
        "request_id": request["request_id"],
        "request_sha256": request["document_sha256"],
        "subject_id": request["subject_id"],
        "minute": request["base_tick"],
        "deadline_ms": deadline_ms,
        "instruction": instruction,
        "choice_description": choice_description,
        "context": request["context"],
        "messages": messages,
        "act": dict(act),
    }


def outcome_frame(*, ask_seq: int, request_id: str, status: str, reason: str) -> dict[str, Any]:
    """What the host recorded for one ask: the receipt's status and reason, and nothing else."""
    return {
        "kind": "outcome",
        "ask_seq": ask_seq,
        "request_id": request_id,
        "status": status,
        "reason": reason,
    }


def grant_frame(*, grant_seq: int, scope: Mapping[str, Any]) -> dict[str, Any]:
    """The grant as it now stands, sent first and again whenever its owner changes it."""
    return {"kind": "grant", "grant_seq": grant_seq, "scope": dict(scope)}


def grant_ended_frame(*, grant_id: str, grant_seq: int, reason: str) -> dict[str, Any]:
    """The grant this channel acts under ended: revoked or expired. Its channel may still read
    what it was sent, for a day, and may answer nothing more."""
    return {"kind": "grant_ended", "grant_id": grant_id, "grant_seq": grant_seq, "reason": reason}
