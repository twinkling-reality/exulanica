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

An ``asked`` frame carries the request's context as a model reads it, less the lines the door leaves
out as it sends it (those heard or said in or before the minute of the grant's first ask, and any
carrying a name the account holder saved), with the role's instruction and the description of the
one choice, and that context rendered as a model is sent it: the role's own messages, the one
function a model is forced to call (``act``), and the world minute it was asked at. So an agent
behind a bridge reads the words a model would be sent for that context and nothing a model would
not, and no adapter renders a role's words a second time. One poll's answer stops adding asked
frames once it reaches :data:`ASKED_BYTES_MAXIMUM`; the next poll reads on.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.things.lines import LineRefused, check_line

__all__ = [
    "ANSWER_BODY_BYTES",
    "ARRIVAL_BODY_BYTES",
    "ASKED_BYTES_MAXIMUM",
    "DEADLINE_MS_DEFAULT",
    "DECLARED_CHARACTERS_MAXIMUM",
    "DECLARED_MIND_MAXIMUM",
    "DELIVERY_BODY_BYTES",
    "FRAMES_PER_POLL",
    "FRAME_PROFILE",
    "HELLO_BODY_BYTES",
    "HOLD_SECONDS_DEFAULT",
    "HOLD_SECONDS_MAXIMUM",
    "LINE_CHARACTERS_MAXIMUM",
    "MAPPING_PROFILE",
    "MAPPING_PROFILES",
    "MAPPING_PROFILE_V2",
    "OWNER_BODY_BYTES",
    "QUIET_SECONDS",
    "READS_MAXIMUM",
    "REDEEM_BODY_BYTES",
    "WORDS_CHARACTERS_MAXIMUM",
    "Cursor",
    "InvalidCursor",
    "answer_sha256",
    "arrival_refused_frame",
    "arrived_frame",
    "asked_frame",
    "declared_fault",
    "departed_frame",
    "grant_ended_frame",
    "grant_frame",
    "outcome_frame",
    "said_frame",
    "words_fault",
]

FRAME_PROFILE: Final = "exulanica.door-frame/v1"
MAPPING_PROFILE: Final = "exulanica.bridge-mapping/v1"
#: The second profile, read beside the first: a visitor's look names the thing library's look by its
#: key, version and digest, where the first names it by digest alone.
MAPPING_PROFILE_V2: Final = "exulanica.bridge-mapping/v2"
MAPPING_PROFILES: Final = (MAPPING_PROFILE, MAPPING_PROFILE_V2)

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
#: An arrival names a visitor's type, its look and at most sixteen carried game items; a delivery
#: report names each thing a departed visitor carried home. Each fits in a few kilobytes.
ARRIVAL_BODY_BYTES: Final = 8192
DELIVERY_BODY_BYTES: Final = 8192
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

#: Every cursor this door has written, by version, and what each counts. An older one is read as
#: told nothing its version did not count (the first no crossing, the first and second no line
#: said), which is all the door that wrote it could tell, so a bridge holding one across an upgrade
#: reads on from where it was. The door writes the newest.
_CURSOR_VERSIONS: Final[Mapping[int, tuple[str, ...]]] = {
    1: ("ask", "outcome", "grant", "ended"),
    2: ("ask", "outcome", "grant", "crossed", "departed", "ended"),
    3: ("ask", "outcome", "grant", "crossed", "departed", "said", "ended"),
}
_CURSOR_VERSION: Final = 3
_CURSOR_TEXT_MAXIMUM: Final = 200
_SEQUENCE_MAXIMUM: Final = 2**62


class InvalidCursor(ValueError):
    """A cursor this door did not write."""

    code: Final = "invalid_cursor"


@dataclass(frozen=True, slots=True)
class Cursor:
    """How far a bridge has read: the last ask, the last outcome, the grant revision it was sent,
    the last of its arrivals' outcomes it was told (by the crossing's sequence in its society, so a
    poll reads on from there rather than counting past what it was told), how many of its visitors'
    departures it was told, the place of the last line its visitors said or heard it was told (its
    minute and its order within the minute, as one number), and whether it was told the grant
    ended.

    ``outcome`` counts asks whose receipts were reported, in ask order, so it never passes ``ask``.
    Encoded as URL-safe base64 of its canonical JSON; a bridge treats it as opaque.
    """

    ask: int = 0
    outcome: int = 0
    grant: int = 0
    crossed: int = 0
    departed: int = 0
    said: int = 0
    ended: bool = False

    def __post_init__(self) -> None:
        for value in (self.ask, self.outcome, self.grant, self.crossed, self.departed, self.said):
            if type(value) is not int or not 0 <= value <= _SEQUENCE_MAXIMUM:
                raise InvalidCursor("a cursor counts whole numbers from zero")
        if type(self.ended) is not bool:
            raise InvalidCursor("a cursor says whether the end was reported")
        if self.outcome > self.ask:
            raise InvalidCursor("a cursor reports no outcome of an ask it has not seen")

    def encode(self) -> str:
        fields = _CURSOR_VERSIONS[_CURSOR_VERSION]
        return _cursor_text({"v": _CURSOR_VERSION, **{key: getattr(self, key) for key in fields}})

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
        if not isinstance(document, dict) or type(document.get("v")) is not int:
            raise InvalidCursor("not a cursor")
        fields = _CURSOR_VERSIONS.get(document["v"])
        if fields is None or set(document) != {"v", *fields}:
            raise InvalidCursor("not a cursor")
        cursor = cls(**{key: document[key] for key in fields})
        # Only this door's own writing of a cursor of that version is one.
        if _cursor_text({"v": document["v"], **{key: document[key] for key in fields}}) != text:
            raise InvalidCursor("not a cursor")
        return cursor


def _cursor_text(document: Mapping[str, Any]) -> str:
    """A cursor's text: URL-safe base64 of its canonical JSON, without padding."""
    return base64.urlsafe_b64encode(canonical_json(dict(document))).decode("ascii").rstrip("=")


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
    idle_label: str | None = None,
    line_labels: Sequence[str] = (),
    line_characters_maximum: int | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The frame asking a bridge to choose for one thing: the request as a model is asked it, its
    context (``context`` where the door sends less of it than the request holds, its digest still
    the request's) and the words of the terms it was asked under, the same request rendered as a
    model is sent it, the label of the offered option that changes nothing (the role's own, None
    where it offers none), and which labels' answers carry a line and how long one may be (none,
    and None, where no option says anything)."""
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
        "context": request["context"] if context is None else dict(context),
        "messages": messages,
        "act": dict(act),
        "idle_label": idle_label,
        "line_labels": list(line_labels),
        "line_characters_maximum": line_characters_maximum,
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


def arrived_frame(
    *, arrival_id: str, thing_id: str, carried: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """A visitor the bridge sent arrived: its id here, and the id each carried thing has here
    beside the game item it was, so the game keeps each original under its id."""
    return {
        "kind": "arrived",
        "arrival_id": arrival_id,
        "thing_id": thing_id,
        "carried": [dict(held) for held in carried],
    }


def arrival_refused_frame(*, arrival_id: str, reason: str) -> dict[str, Any]:
    """The society refused an arrival, and why, in one of the society's own words."""
    return {"kind": "arrival_refused", "arrival_id": arrival_id, "reason": reason}


def departed_frame(
    *, departure_id: str, thing_id: str, why: str, carried: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """A visitor left the world, why, and what it carried home: each thing's id, its kind and the
    game item it becomes (null where the mapping lets no item of that kind travel out)."""
    return {
        "kind": "departed",
        "departure_id": departure_id,
        "thing_id": thing_id,
        "why": why,
        "carried": [dict(held) for held in carried],
    }


def said_frame(
    *,
    tick: int,
    speaker: Mapping[str, Any],
    to: str | None,
    to_label: str | None,
    line: str | None,
) -> dict[str, Any]:
    """A line said in the world that one of the grant's visitors said or heard: the minute, who
    said it (its id, its kind and number in words, and who decided it), whom it was said to (an id
    and words, both None for everyone near) and the line. A field whose words carry a name the
    account holder saved is sent as None."""
    return {
        "kind": "said",
        "tick": tick,
        "speaker": {
            "id": speaker["id"],
            "label": speaker["label"],
            "mind": dict(speaker["mind"]),
        },
        "to": to,
        "to_label": to_label,
        "line": line,
    }


def grant_frame(*, grant_seq: int, scope: Mapping[str, Any]) -> dict[str, Any]:
    """The grant as it now stands, sent first and again whenever its owner changes it."""
    return {"kind": "grant", "grant_seq": grant_seq, "scope": dict(scope)}


def grant_ended_frame(*, grant_id: str, grant_seq: int, reason: str) -> dict[str, Any]:
    """The grant this channel acts under ended: revoked or expired. Its channel may still read
    what it was sent, for a day, and may answer nothing more."""
    return {"kind": "grant_ended", "grant_id": grant_id, "grant_seq": grant_seq, "reason": reason}
