"""The Companion's answers about the simulated people of the world a question is asked in.

A person watching their world asks who somebody is, what they are doing, why they are there, or
what has happened among the people. Those are questions about the world's simulation, and they are
answered from it: from the society's current state and its recorded events, read through
:class:`~exulanica.world.society_repository.SocietyRepository` exactly as the inspector reads them,
under the same current authorization. Four rules hold on every path:

*   **A simulation is not a memory.** Every citation is a society event or the society's state, of
    truth class ``simulation`` and never evidence of a personal visit, and every answer closes by
    saying the people are simulated.
*   **No inhabitant's name reaches a hosted request, a saved name's lookup or an answer.** An
    inhabitant is ``[inhabitant A]`` and a place they use ``[spot A]``, the maps are returned with
    the answer, and the page draws each name from its own copy of the society, marked simulated.
    Synthetic names are drawn from a small table (``society_legacy.LEGACY_FIRST_NAMES``), so one
    can share a part with somebody the account holder saved; a question whose words could be
    either is refused by name rather than guessed (:data:`SocietyRefusal.SYNTHETIC_NAME_COLLISION`).
*   **Who, doing and why need no model.** They are the inspector's own words for the state
    (:mod:`exulanica.selection.inhabitant_words`), cited to the state and to the event that
    explains it. Only "what happened", over the whole world, asks a model, and only which of the
    event lines answer the question: it is sent lines rebuilt from each event's recorded fields in
    the same words, never a stored summary, a position, a seed or a digest, and it writes nothing.
*   **Talking has no content.** The simulation records that two people talked and never what about,
    so no line says more, and every sentence of an answer is a line's own fixed words.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Final

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from exulanica.epistemics.saved_names import (
    MIN_PART_LETTERS,
    PLACEHOLDER,
    SavedName,
    recognised_spans,
    redact_names,
)
from exulanica.errors import ExulanicaError
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError, StructuredOutputError, TruncatedResponseError
from exulanica.models.manifest import Role
from exulanica.selection.answer import (
    MAX_CLAUSES,
    Abstention,
    Answer,
    AnswerClause,
    AnswerRejected,
    ClauseType,
)
from exulanica.selection.calls import CallLog
from exulanica.selection.inhabitant_words import (
    InhabitantWordsCatalog,
    inhabitant_words,
    inhabitant_words_catalog,
)
from exulanica.selection.packet import MAX_PACKET_ITEMS, TOKEN_LENGTH, ValueReference
from exulanica.selection.plan import SocietyAspect, SocietyScope, SocietySelector
from exulanica.selection.prompts import _SOCIETY_COMPOSER_SYSTEM, PROMPT_VERSION
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_engines import INPUT_ENGINES
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "EVENT_LINES",
    "INHABITANT_PLACEHOLDER",
    "SIMULATED_PLACEHOLDER",
    "SIMULATION",
    "SocietyAnswer",
    "SocietyContext",
    "SocietyEvidenceItem",
    "SocietyEvidencePacket",
    "SocietyRefusal",
    "SocietyScene",
    "UnknownSocietyContext",
    "answer_about_society",
    "build_scene",
    "read_scene",
]

#: The truth class of everything this module cites, as ``build_content_packet`` names simulated
#: content: never a memory, and never evidence of a personal visit.
SIMULATION: Final = "simulation"

#: How many recorded events one answer reads: the packet's own cap, so the composer is sent at most
#: as many lines as any packet holds.
EVENT_LINES: Final = MAX_PACKET_ITEMS

#: An inhabitant and a place they use, as every text this module writes names them. The page reads
#: them with ``SIMULATED_PLACEHOLDER_SOURCE`` in ``web/packages/app/src/companion-simulated.ts``,
#: held to :data:`SIMULATED_PLACEHOLDER` by ``tests/test_companion_simulated_parity.py``.
SIMULATED_PLACEHOLDER: Final = re.compile(r"(\[(?:inhabitant|spot) [A-Z]+\])")
INHABITANT_PLACEHOLDER: Final = re.compile(r"\[inhabitant [A-Z]+\]")
#: Either label typed into a question, in any case: it names nobody in this request.
_TYPED_LABEL: Final = re.compile(r"\[\s*(?:inhabitant|spot)\s+[a-z]+\s*\]", re.IGNORECASE)

#: No ``0O1lI``, as in the photograph packet's tokens (``exulanica.selection.packet``).
_TOKEN_ALPHABET: Final = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
#: A token as written anywhere in a text, not part of a longer run of token letters.
_TOKEN_TEXT: Final = re.compile(
    rf"(?<![{_TOKEN_ALPHABET}])[{_TOKEN_ALPHABET}]{{{TOKEN_LENGTH}}}(?![{_TOKEN_ALPHABET}])"
)

#: The outcomes and event kinds that record two people talking. Their lines say that they talked
#: and with whom, and nothing more.
_TALK_OUTCOMES: Final = frozenset({"talk_started", "talk_ended", "talk_completed"})
_TALK_KIND: Final = "social_contact"

#: The longest a person waits for an answer about what happened, counted from the question's
#: start. The fixed words are ready before the composer is asked, so composing is worth only the
#: time it saves the person: a repair is not begun when less of this is left than one attempt may
#: take (the reasoning role's own timeout in the model manifest, 60 seconds). It is the first
#: attempt's whole bound plus 15 seconds for the planner and the first reply, because the first
#: attempt is never skipped: any budget below that bound would not bound the wait, and would only
#: stop every repair. Measured on the live composer: a refused first reply came back 17 and 22
#: seconds in, and its repair then timed out, so those answers took 78 and 83 seconds; under this
#: budget both are the fixed words at about 17 and 22 seconds, and a refused reply that comes back
#: within 15 seconds is still repaired.
ANSWER_WAIT_BUDGET_SECONDS: Final = 75.0

#: Said before the fixed words when no choice of lines came in time, by what happened to it.
_UNANSWERED: Final[Mapping[str, str]] = {
    "timed_out": "The model that chooses the lines for this answer did not answer in time.",
    "failed": "The model that chooses the lines for this answer did not answer.",
    "no_time": (
        "The lines the model chose could not be used, and there was no time left to ask it again."
    ),
}
#: What the fixed words after that note show, by how many lines they hold.
_UNANSWERED_SHOWN: Final[Mapping[int, str]] = {
    0: "Nothing has been recorded to show instead.",
    1: "Here is the latest recorded line instead.",
}
_UNANSWERED_SHOWN_MANY: Final = "Here are the latest recorded lines instead."

#: How many lines a composed answer shows: every clause an answer may hold, less the minutes the
#: lines cover, a framing and the closing.
MAX_CHOSEN_LINES: Final = MAX_CLAUSES - 3


class Framing(StrEnum):
    """A sentence the composer may put before the lines it chooses, in the words catalog's own
    words (``phrase.framing_<value>``). It is chosen, never written."""

    RECORDED = "recorded"
    TALK = "talk"


class SocietyLineChoice(BaseModel):
    """What the society composer returns: which lines answer the question, and how to frame them.

    No prose. Every sentence of the answer is a chosen line's own fixed words, so the model cannot
    recombine the lines' words into something no line says, what anybody said above all.
    """

    model_config = ConfigDict(extra="forbid")

    lines: Annotated[list[str], Field(min_length=1, max_length=MAX_CHOSEN_LINES)] = Field(
        description="The tokens of the lines that answer the question, each as the list gives it."
    )
    framing: Framing | None = Field(
        default=None,
        description=(
            "recorded: the lines are what was recorded; talk: the lines say who talked with whom. "
            "Null for none."
        ),
    )


_NOT_A_MEMORY: Final = (
    "These are simulated people, invented for this world: what they do is recorded by its "
    "simulation, and none of it is a memory or a real visit."
)


@dataclass(frozen=True, slots=True)
class SocietyContext:
    """The society the page shows, by its world version, and the inhabitant selected in it."""

    version_id: uuid.UUID
    inhabitant_id: uuid.UUID | None = None


class UnknownSocietyContext(ExulanicaError):
    """No such society in this world, or no such inhabitant in it.

    One refusal for "not there" and "not yours", so the question route is not an existence oracle
    for societies or their people.
    """

    def __init__(self) -> None:
        super().__init__("no such inhabitant in this world")


class SocietyRefusal(StrEnum):
    """Why a question about the people of a world is not answered, each said to the person."""

    #: The question is about simulated people and the page named no society.
    NO_SOCIETY_HERE = "no_society_here"
    #: The society is there and nobody is in it now.
    NOBODY_HERE = "nobody_here"
    #: The society runs under a profile the words catalog has no words for.
    PROFILE_HAS_NO_WORDS = "society_profile_has_no_words"
    #: The society cannot be read under current authorization.
    UNAVAILABLE = "society_unavailable"
    #: The question is about one person and does not say which.
    SELECT_A_PERSON = "select_a_person"
    #: A word of the question is a saved name and the selected inhabitant's name alike.
    SYNTHETIC_NAME_COLLISION = "synthetic_name_collision"
    #: The question carries an inhabitant or place label typed from an earlier answer.
    TYPED_INHABITANT_LABEL = "typed_inhabitant_label"
    #: The question asks what somebody said. Talking has no content.
    TALK_HAS_NO_CONTENT = "talk_has_no_content"
    #: The question asks what the simulation does not record.
    NOT_SIMULATED = "not_simulated"


#: What each refusal says, and the code it is scored under. Every clause is ``meta``: an
#: abstention states no fact.
_REFUSALS: Final[Mapping[SocietyRefusal, tuple[Abstention, str]]] = {
    SocietyRefusal.NO_SOCIETY_HERE: (
        Abstention.NOT_CAPTURED,
        "There are no simulated people in view to ask about. Open a world with people in it, "
        "and ask again.",
    ),
    SocietyRefusal.NOBODY_HERE: (
        Abstention.NOT_CAPTURED,
        "Nobody is in this world right now, so there is nobody to ask about.",
    ),
    SocietyRefusal.PROFILE_HAS_NO_WORDS: (
        Abstention.NOT_CAPTURED,
        "The people here are simulated in a way I have no words for, so I cannot say what they "
        "are doing. The inspector shows what is recorded about each of them.",
    ),
    SocietyRefusal.UNAVAILABLE: (
        Abstention.NOT_CAPTURED,
        "The people in this world cannot be read right now, so I have not answered about them.",
    ),
    SocietyRefusal.SELECT_A_PERSON: (
        Abstention.AMBIGUOUS,
        "I cannot tell which simulated person you mean. Select the person you mean in the world, "
        "and ask again.",
    ),
    SocietyRefusal.SYNTHETIC_NAME_COLLISION: (
        Abstention.AMBIGUOUS,
        "A name in your question belongs both to someone you saved and to the person selected in "
        "this world, so I cannot tell who you mean. To ask about the person you saved, use their "
        "full name or clear the selection; to ask about the selected person, ask without the "
        "name, for example: why are they there?",
    ),
    SocietyRefusal.TYPED_INHABITANT_LABEL: (
        Abstention.AMBIGUOUS,
        "A label in square brackets, copied from an earlier answer, names someone only in that "
        "answer, so it names nobody here. Use the person's name, or select them in the world, and "
        "ask again.",
    ),
    SocietyRefusal.TALK_HAS_NO_CONTENT: (
        Abstention.NOT_IN_MODALITY,
        "The simulation records that people talked and with whom, and never what they said, so "
        "there is nothing to tell about what was said.",
    ),
    SocietyRefusal.NOT_SIMULATED: (
        Abstention.NOT_CAPTURED,
        "The simulation records where these people go, what they do there and why, and nothing "
        "else about them: they have no life outside this world to ask about.",
    ),
}


@dataclass(frozen=True, slots=True)
class SocietyEvidenceItem:
    """One citable thing: an inhabitant's current state, or one recorded event."""

    token: str
    #: ``synthetic_inhabitant`` for the state, ``simulation_event`` for an event, as the content
    #: packet names them.
    result_kind: str
    inhabitant_id: uuid.UUID
    event_id: uuid.UUID | None
    #: The simulated minute the state or event is from.
    tick: int
    #: The line as the composer is sent it: placeholders and catalog words only.
    line: str

    @property
    def truth_class(self) -> str:
        return SIMULATION

    @property
    def personal_visit_evidence(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class SocietyEvidencePacket:
    """At most :data:`EVENT_LINES` event lines, or the state lines of the people asked about.

    Tokens are random per request and resolve only here, as the photograph packet's do, so a
    citation the composer invents resolves to nothing.
    """

    society_id: uuid.UUID
    version_id: uuid.UUID
    items: tuple[SocietyEvidenceItem, ...]
    values: tuple[ValueReference, ...]
    #: Each inhabitant placeholder the answer may carry, and the inhabitant it stands for.
    inhabitants: tuple[tuple[str, uuid.UUID], ...]
    #: Each place placeholder, and the society target it stands for.
    spots: tuple[tuple[str, str], ...]
    citable: bool = True

    @property
    def is_empty(self) -> bool:
        return not self.items

    def resolve(self, token: str) -> SocietyEvidenceItem | None:
        """The item a citation names, brackets stripped as the photograph packet strips them."""
        wanted = token.strip().strip("[]")
        return next((item for item in self.items if item.token == wanted), None)

    def canonical(self, token: str) -> str | None:
        item = self.resolve(token)
        return None if item is None else item.token

    def value(self, key: str) -> ValueReference | None:
        return next((value for value in self.values if value.key == key), None)


@dataclass(frozen=True, slots=True)
class SocietyAnswer:
    """What :func:`answer_about_society` returns for ``answer_question`` to record."""

    answer: Answer
    packet: SocietyEvidencePacket | None = None
    abstention: Abstention | None = None
    #: True only when a composer was asked and its output discarded, as ``AnswerView`` means it.
    #: An answer in the inspector's words was never a model's to discard.
    deterministic: bool = False
    repaired: bool = False
    rejections: tuple[str, ...] = ()


def refused(code: SocietyRefusal) -> SocietyAnswer:
    """The named refusal: its sentence, its abstention code, and the code kept with the answer."""
    reason, text = _REFUSALS[code]
    return SocietyAnswer(
        answer=Answer(clauses=[AnswerClause(text=text, type=ClauseType.META)]),
        abstention=reason,
        rejections=(f"society_refused: {code}",),
    )


class _Labels:
    """The request's placeholders for inhabitants and places, in the order they are first used."""

    def __init__(self) -> None:
        self.people: dict[str, str] = {}
        self.spots: dict[str, str] = {}

    def person(self, inhabitant_id: str) -> str:
        if inhabitant_id not in self.people:
            self.people[inhabitant_id] = f"[inhabitant {_letters(len(self.people))}]"
        return self.people[inhabitant_id]

    def spot(self, target_id: str) -> str:
        if target_id not in self.spots:
            self.spots[target_id] = f"[spot {_letters(len(self.spots))}]"
        return self.spots[target_id]


def _letters(index: int) -> str:
    """``A`` for 0, ``Z`` for 25, ``AA`` for 26, as saved names' placeholders count."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


@dataclass(slots=True)
class SocietyScene:
    """One society read for one question: its state, its latest events, and what the question
    named in it. Built by :func:`read_scene`; the words sent onwards use its placeholders."""

    society_id: uuid.UUID
    version_id: uuid.UUID
    profile: str
    tick: int
    people: Mapping[str, Mapping[str, Any]]
    #: The targets people can use now, as the consumed input states them.
    usable_targets: frozenset[str]
    #: Newest first, at most :data:`EVENT_LINES`.
    events: tuple[Mapping[str, Any], ...]
    #: The event each person's state names as its explanation, by id, however long ago it was.
    explaining: Mapping[str, Mapping[str, Any]]
    selected: str | None
    labels: _Labels = field(default_factory=_Labels)
    #: Inhabitants the question names by a name only they carry, by id.
    named: tuple[str, ...] = ()
    #: The question names a part several inhabitants share.
    named_ambiguously: bool = False
    #: A word of the question is a saved name and the selected inhabitant's name alike.
    collision: bool = False
    #: A word of the question is a saved name and, with nobody selected who has it, also an
    #: inhabitant's; it is read as the saved one's. The saved entity's class (``person``, ``place``
    #: and so on), or ``mixed`` for several of different classes; None for no such word.
    shared_name: str | None = None
    #: The question carries an ``[inhabitant A]`` or ``[spot A]`` label typed from elsewhere.
    typed_label: bool = False
    #: The question with every inhabitant's name written as a placeholder or taken out.
    question: str = ""


class _AuthorizedOnce:
    """One question's authorizer: each input authorized once, its verdict shared by every read.

    An authorization reads and hashes every reviewed asset the input names, so the scene, its
    latest events and the events that explain people's states ask it once per input between
    them, not once per read. A withdrawal is remembered as the refusal it was.
    """

    def __init__(self, authorize: Any) -> None:
        self._authorize = authorize
        self._verdicts: dict[tuple[int, str], UnavailableSocietyInput | None] = {}

    def __call__(self, document: Mapping[str, Any]) -> None:
        if self._authorize is None:
            raise UnavailableSocietyInput("current society input authorization is not configured")
        key = (int(document["input_seq"]), str(document["document_sha256"]))
        if key not in self._verdicts:
            try:
                self._authorize(document)
                self._verdicts[key] = None
            except UnavailableSocietyInput as refused:
                self._verdicts[key] = refused
        refusal = self._verdicts[key]
        if refusal is not None:
            raise refusal


def read_scene(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    context: SocietyContext,
    *,
    authorize: Any,
    question: str,
    saved: Sequence[SavedName],
) -> SocietyScene | SocietyRefusal:
    """Read the society the page shows, and what the question's words name in it.

    Raises :class:`UnknownSocietyContext` for a version with no society in this world, in another
    workspace, or an inhabitant not in it, all alike. The state is read as the inspector reads it,
    under current authorization of the input it consumed; a society whose current input cannot be
    authorized is the named refusal :data:`SocietyRefusal.UNAVAILABLE`. The latest events and the
    events that explain people's states are read here, each input behind them authorized once,
    and an event recorded under an input a withdrawal no longer authorizes is left out alone.
    """
    once = _AuthorizedOnce(authorize)
    repository = SocietyRepository(
        connection, workspace_id, world_id=world_id, input_authorizer=once
    )
    try:
        snapshot = repository.snapshot(context.version_id, places=True)
    except UnknownSociety:
        raise UnknownSocietyContext() from None
    except (UnavailableSocietyInput, ValueError):
        return SocietyRefusal.UNAVAILABLE
    try:
        events = _authorized_events(
            connection, workspace_id, world_id, snapshot, repository, once, latest=EVENT_LINES
        )
        shown = {str(event["event_id"]) for event in events}
        wanted = sorted(
            {
                str(event_id)
                for person in snapshot["state"].get("inhabitants", [])
                for event_id in (person.get("explanation") or {}).get("event_ids", [])
            }
            - shown
        )
        older = _authorized_events(
            connection, workspace_id, world_id, snapshot, repository, once, event_ids=wanted
        )
    except (UnavailableSocietyInput, ValueError):
        # Authorization not configured, or a stored input that does not verify: the society
        # cannot be read. A withdrawn input only leaves out its own events.
        return SocietyRefusal.UNAVAILABLE
    places = snapshot.get("places") or {}
    return build_scene(
        snapshot,
        targets=places.get("targets", []),
        events=events,
        explaining=[*events, *older],
        selected=context.inhabitant_id,
        question=question,
        saved=saved,
    )


def _authorized_events(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot: Mapping[str, Any],
    repository: SocietyRepository,
    authorize: _AuthorizedOnce,
    *,
    latest: int | None = None,
    event_ids: Sequence[str] = (),
) -> list[Mapping[str, Any]]:
    """This world's society's ``latest`` events, newest first, or the named ones however long ago,
    each only while the input it was recorded under is still authorized.

    The inputs are read, held to their rows and to this society's version, by the repository's own
    reader (``SocietyRepository._inputs``, whose ``_validate_scope`` binds them), and the latest
    events are ordered as ``SocietyRepository.events`` orders them. An event whose input a
    withdrawal no longer authorizes is left out, and only it; a stored input that does not verify
    raises, as the repository does.
    """
    if latest is None and not event_ids:
        return []
    chosen = (
        "order by e.tick desc,(e.document->>'order')::integer nulls last,e.event_id limit %s"
        if latest is not None
        else "and e.event_id=any(%s::uuid[])"
    )
    rows = connection.execute(
        "select e.event_id,e.tick,e.event_kind,e.subject_id,e.document "
        "from world_society_event e join world_society s "
        "on s.workspace_id=e.workspace_id and s.society_id=e.society_id "
        "where e.workspace_id=%s and s.world_id=%s and e.society_id=%s " + chosen,
        (
            workspace_id,
            world_id,
            snapshot["society_id"],
            latest if latest is not None else list(event_ids),
        ),
    ).fetchall()
    if snapshot["profile"] not in INPUT_ENGINES:
        return [dict(row) for row in rows]
    society = repository._row(uuid.UUID(str(snapshot["version_id"])))
    if society is None:
        raise ValueError("the society is no longer there")
    documents = repository._inputs(society, {row["document"]["input_seq"] for row in rows})
    authorized = set()
    for sequence, document in documents.items():
        try:
            authorize(document)
        except UnavailableSocietyInput:
            continue
        authorized.add(sequence)
    return [dict(row) for row in rows if row["document"]["input_seq"] in authorized]


def build_scene(
    snapshot: Mapping[str, Any],
    *,
    targets: Iterable[Mapping[str, Any]],
    events: Iterable[Mapping[str, Any]],
    explaining: Iterable[Mapping[str, Any]] = (),
    selected: uuid.UUID | None,
    question: str,
    saved: Sequence[SavedName],
) -> SocietyScene:
    """A society snapshot, its targets and its latest events, read for one question.

    ``snapshot`` is :meth:`SocietyRepository.snapshot`'s shape and ``events`` its ``events``';
    ``explaining`` holds the events people's states name as their explanation, however old.
    Raises :class:`UnknownSocietyContext` when the selected inhabitant is not in it.
    """
    state = snapshot["state"]
    people = {str(person["id"]): person for person in state.get("inhabitants", [])}
    chosen = None if selected is None else str(selected)
    if chosen is not None and chosen not in people:
        raise UnknownSocietyContext()
    scene = SocietyScene(
        society_id=uuid.UUID(str(snapshot["society_id"])),
        version_id=uuid.UUID(str(snapshot["version_id"])),
        profile=str(snapshot["profile"]),
        tick=int(snapshot["current_tick"]),
        people=people,
        usable_targets=frozenset(
            str(target["target_id"]) for target in targets if target.get("enabled", True)
        ),
        events=tuple(events)[:EVENT_LINES],
        explaining={str(event["event_id"]): event for event in explaining},
        selected=chosen,
    )
    if chosen is not None:
        scene.labels.person(chosen)
    _read_names(scene, question, saved)
    return scene


def _name_forms(name: str) -> list[str]:
    """A synthetic name whole, without its number ("Ari Ash" of "Ari Ash 1"), and each part of it
    long enough to be a name on its own."""
    whole = " ".join(name.split())
    if not whole:
        return []
    words = whole.split(" ")
    named = list(words)
    while len(named) > 1 and named[-1].isdigit():
        named.pop()
    forms = [whole, " ".join(named)]
    forms += [part for part in words if len(re.sub(r"[^\w]", "", part)) >= MIN_PART_LETTERS]
    return list(dict.fromkeys(forms))


def _form_pattern(form: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<!\w)" + r"\s+".join(re.escape(word) for word in form.split(" ")) + r"(?!\w)",
        re.IGNORECASE,
    )


def _read_names(scene: SocietyScene, question: str, saved: Sequence[SavedName]) -> None:
    """Which inhabitants the question names, whether a name could be a saved person's, and the
    question with every inhabitant's name written as its placeholder.

    One reading, longest first, the way :func:`~exulanica.epistemics.saved_names.redact_names`
    reads saved names, over saved names and inhabitants' names together. The longer words win:
    "Emi Tanaka", a saved person, is that person however an inhabitant called Emi is named, and
    "Ari Ash", an inhabitant, is that inhabitant however a saved "Ash Ketchum" is named. The same
    words read as a saved name and as the selected inhabitant's name are a collision: the
    selection makes the ambiguity deliberate, and ``answer_question`` refuses the question by name
    before it is planned. With nobody selected who has them, they are the saved person's, and the
    answer says someone in the world shares the name.

    Of an inhabitant's forms, one that names one inhabitant, or the selected one among several,
    is written as that inhabitant's placeholder. One several share, none of them selected, names no
    one person and stays the person's own word, so "the ash cloud" is untouched; a question about
    one person named that way is refused as :data:`SocietyRefusal.SELECT_A_PERSON`. So no form
    that names one inhabitant reaches a hosted request.
    """
    # A label an earlier answer used names somebody only in that answer, and these letters are
    # this request's: typed back, it names nobody here, and the question is refused by name.
    scene.typed_label = _TYPED_LABEL.search(question) is not None
    owners: dict[str, set[str]] = {}
    for inhabitant_id, person in scene.people.items():
        for form in _name_forms(str(person.get("display_name") or "")):
            owners.setdefault(form.casefold(), set()).add(inhabitant_id)
    everyone = set(scene.people)
    #: (start, end, kind, owners): kind 0 is a typed placeholder, 1 a saved name, 2 an
    #: inhabitant's name; at equal length a saved name is read before an inhabitant's.
    candidates: list[tuple[int, int, int, frozenset[str]]] = [
        (match.start(), match.end(), 0, frozenset()) for match in PLACEHOLDER.finditer(question)
    ]
    recognised = recognised_spans(question, saved)
    #: What kind of thing each saved name read is, by its span, for the note a tie adds.
    saved_class = {(start, end): name.entity_class for start, end, name in recognised}
    candidates += [(start, end, 1, frozenset()) for start, end, _ in recognised]
    for form, who in owners.items():
        if len(who) > 1 and who == everyone:
            continue
        candidates += [
            (match.start(), match.end(), 2, frozenset(who))
            for match in _form_pattern(form).finditer(question)
        ]
    accepted: list[tuple[int, int, int, frozenset[str]]] = []
    for candidate in sorted(candidates, key=lambda c: (c[0] - c[1], c[2], c[0])):
        start, end, kind, _ = candidate
        overlapping = [held for held in accepted if held[0] < end and start < held[1]]
        if not overlapping:
            accepted.append(candidate)
            continue
        tie = [
            held
            for held in overlapping
            if {held[2], kind} == {1, 2} and held[1] - held[0] == end - start
        ]
        if tie:
            # The same words are a saved name and an inhabitant's. With the one selected who has
            # it, the ambiguity is deliberate and refused by name; otherwise the words are the
            # saved person's, the library's by default, and the answer says someone in the world
            # shares the name.
            owners_here = next(c[3] for c in (candidate, *tie) if c[2] == 2)
            if scene.selected is not None and scene.selected in owners_here:
                scene.collision = True
            else:
                start_end = next((c[0], c[1]) for c in (candidate, *tie) if c[2] == 1)
                kind = saved_class[start_end]
                scene.shared_name = kind if scene.shared_name in (None, kind) else "mixed"
    named: dict[str, None] = {}
    written: list[str] = []
    at = 0
    for start, end, kind, who in sorted(accepted):
        written.append(question[at:start])
        if kind != 2:
            written.append(question[start:end])
        elif len(who) == 1:
            (inhabitant_id,) = who
            named[inhabitant_id] = None
            written.append(scene.labels.person(inhabitant_id))
        elif scene.selected is not None and scene.selected in who:
            named[scene.selected] = None
            written.append(scene.labels.person(scene.selected))
        else:
            # Several people's, none of them selected: no one person's name, so it stays the
            # person's own word, and a question about one person is refused select_a_person.
            scene.named_ambiguously = True
            written.append(question[start:end])
        at = end
    written.append(question[at:])
    scene.named = tuple(named)
    scene.question = "".join(written)


def _token(taken: set[str]) -> str:
    while True:
        candidate = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
        if candidate not in taken:
            taken.add(candidate)
            return candidate


class _Builder:
    """Items, values and placeholders for one answer, in the order they are cited."""

    def __init__(self, scene: SocietyScene, catalog: InhabitantWordsCatalog) -> None:
        self.scene = scene
        self.catalog = catalog
        self.items: list[SocietyEvidenceItem] = []
        self.values: dict[str, ValueReference] = {}
        self.taken: set[str] = set()

    def words(self, inhabitant_id: str) -> Any:
        scene = self.scene
        return inhabitant_words(
            scene.people[inhabitant_id],
            lambda target: scene.labels.spot(target) if target in scene.usable_targets else None,
            lambda other: scene.labels.person(other) if other in scene.people else None,
            self.catalog,
        )

    def state(self, inhabitant_id: str, line: str) -> SocietyEvidenceItem:
        item = SocietyEvidenceItem(
            token=_token(self.taken),
            result_kind="synthetic_inhabitant",
            inhabitant_id=uuid.UUID(inhabitant_id),
            event_id=None,
            tick=self.scene.tick,
            line=line,
        )
        self.items.append(item)
        return item

    def event(self, event: Mapping[str, Any]) -> SocietyEvidenceItem:
        document = event["document"]
        subject = str(event["subject_id"])
        tick = int(event["tick"])
        outcome = str(document.get("outcome") or "")
        outcome_words = self.catalog.tables["outcome"].get(outcome) or self.catalog.words(
            "line", "outcome_unknown"
        ).format(code=outcome)
        subject_label = (
            self.scene.labels.person(subject)
            if subject in self.scene.people
            else self.catalog.words("phrase", "partner_unknown")
        )
        minute = self.minute(tick)
        line = self.catalog.words("line", "event").format(
            minute=minute.text,
            subject=subject_label,
            outcome=outcome_words,
            reason=self.catalog.reason(str(document.get("reason") or "")),
        )
        goal = document.get("goal") if isinstance(document.get("goal"), Mapping) else None
        partner = goal.get("partner_id") if goal is not None else None
        talk = event.get("event_kind") == _TALK_KIND or outcome in _TALK_OUTCOMES
        if partner and goal is not None and (talk or goal.get("kind") == "talk"):
            talk = True
            partner_label = (
                self.scene.labels.person(str(partner))
                if str(partner) in self.scene.people
                else self.catalog.words("phrase", "partner_unknown")
            )
            line = self.catalog.words("line", "with_partner").format(
                line=line, partner=partner_label
            )
        item = SocietyEvidenceItem(
            token=_token(self.taken),
            result_kind="simulation_event",
            inhabitant_id=uuid.UUID(subject),
            event_id=uuid.UUID(str(event["event_id"])),
            tick=tick,
            line=line,
        )
        self.items.append(item)
        return item

    def minute(self, tick: int) -> ValueReference:
        key = f"minute_{tick}"
        if key not in self.values:
            self.values[key] = ValueReference(
                key=key, text=str(tick), label="a simulated minute an event was recorded in"
            )
        return self.values[key]

    def count(self, key: str, count: int, label: str) -> ValueReference:
        self.values[key] = ValueReference(key=key, text=str(count), label=label)
        return self.values[key]

    def packet(self) -> SocietyEvidencePacket:
        return SocietyEvidencePacket(
            society_id=self.scene.society_id,
            version_id=self.scene.version_id,
            items=tuple(self.items),
            values=tuple(self.values.values()),
            inhabitants=tuple(
                (label, uuid.UUID(inhabitant_id))
                for inhabitant_id, label in self.scene.labels.people.items()
            ),
            spots=tuple((label, target) for target, label in self.scene.labels.spots.items()),
        )


def _cited(text: str, item: SocietyEvidenceItem, *more: SocietyEvidenceItem) -> AnswerClause:
    return AnswerClause(
        text=text,
        type=ClauseType.SIMULATION,
        citations=[item.token, *(other.token for other in more)],
    )


def _closing() -> AnswerClause:
    return AnswerClause(text=_NOT_A_MEMORY, type=ClauseType.META)


def _person_answer(
    builder: _Builder, subject: str, aspect: SocietyAspect
) -> list[AnswerClause] | None:
    """Who one person is, what they are doing, or why, in the inspector's words, cited."""
    scene = builder.scene
    label = scene.labels.person(subject)
    said = builder.words(subject)
    if aspect is SocietyAspect.WHO:
        item = builder.state(subject, f"{label}: {said.what}")
        return [_cited(f"{label}. {said.what}", item)]
    if aspect is SocietyAspect.DOING:
        item = builder.state(subject, f"{label}: {said.doing}")
        return [_cited(f"{label}: {said.doing}", item)]
    if aspect is SocietyAspect.WHY:
        state = builder.state(subject, f"{label}: {said.doing} {said.why}")
        explained = list(
            dict.fromkeys(
                str(event_id)
                for event_id in (scene.people[subject].get("explanation") or {}).get(
                    "event_ids", []
                )
            )
        )
        # Each by its id, read however long ago it was recorded, never looked for among the
        # latest minutes only.
        because = [
            builder.event(scene.explaining[event_id])
            for event_id in explained
            if event_id in scene.explaining
        ]
        clauses = [_cited(f"{label}: {said.doing}", state)]
        if said.why:
            clauses.append(_cited(said.why, state, *because))
        return clauses
    if aspect is SocietyAspect.RECENT:
        theirs = [event for event in scene.events if str(event["subject_id"]) == subject]
        if not theirs:
            item = builder.state(subject, f"{label}: {said.doing}")
            return [
                AnswerClause(
                    text=f"Nothing about {label} is in the latest recorded simulated minutes.",
                    type=ClauseType.META,
                ),
                _cited(f"{label}: {said.doing}", item),
            ]
        return [
            _cited(builder.event(event).line, builder.items[-1])
            for event in reversed(theirs[: MAX_CLAUSES - 1])
        ]
    return None


def _world_answer(builder: _Builder, aspect: SocietyAspect) -> list[AnswerClause] | None:
    """Everybody at once: who is here and what each is doing (and why), cited to the state."""
    scene = builder.scene
    if aspect not in (SocietyAspect.WHO, SocietyAspect.DOING, SocietyAspect.WHY):
        return None
    listed = list(scene.people)[: MAX_CLAUSES - 2]
    everybody = builder.count(
        "people_count", len(scene.people), "how many simulated people are in this world"
    )
    shown = builder.count("people_shown", len(listed), "how many of them this answer names")
    clauses = [
        AnswerClause(
            text=(
                f"{everybody.text} simulated people are in this world; here are {shown.text}."
                if len(listed) < len(scene.people)
                else f"{everybody.text} simulated people are in this world."
            ),
            type=ClauseType.META,
            value_refs=[everybody.key, shown.key],
        )
    ]
    for inhabitant_id in listed:
        label = scene.labels.person(inhabitant_id)
        said = builder.words(inhabitant_id)
        text = f"{label}: {said.doing}" + (
            f" {said.why}" if aspect is SocietyAspect.WHY and said.why else ""
        )
        clauses.append(_cited(text, builder.state(inhabitant_id, text)))
    return clauses


def _span(
    builder: _Builder, items: Sequence[SocietyEvidenceItem], *, latest: bool = True
) -> AnswerClause:
    """Which simulated minutes ``items`` cover, said as the simulation counts them: its latest, or
    for lines chosen from among them, only the minutes they are from."""
    ticks = [item.tick for item in items]
    first, last = builder.minute(min(ticks)), builder.minute(max(ticks))
    if latest:
        said = (
            f"These are its latest recorded minutes, {first.text} to {last.text}."
            if first.key != last.key
            else f"This is its latest recorded minute, {first.text}."
        )
    else:
        said = (
            f"These lines are from its minutes {first.text} to {last.text}."
            if first.key != last.key
            else f"These lines are from its minute {first.text}."
        )
    return AnswerClause(
        text=f"The simulation counts minutes, not times of day. {said}",
        type=ClauseType.META,
        value_refs=sorted({first.key, last.key}),
    )


def _happened(builder: _Builder) -> tuple[AnswerClause, list[AnswerClause]]:
    """The latest recorded events, oldest first, as fixed-words lines: the answer at zero model
    compliance. Every line is in the packet the composer is sent; the answer shows the last of
    them, and its first clause states the minutes those it shows cover."""
    for event in reversed(builder.scene.events):
        builder.event(event)
    shown = builder.items[-(MAX_CLAUSES - 2) :]
    return _span(builder, shown), [_cited(item.line, item) for item in shown]


def answer_about_society(
    scene: SocietyScene | None,
    selector: SocietySelector,
    *,
    client: ModelClient | None,
    saved: Sequence[SavedName],
    log: CallLog,
    max_tokens: int,
    attempts: int,
    started: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SocietyAnswer:
    """Answer one question about the people of a world, or refuse it by name.

    The question is the scene's, every inhabitant's name already its placeholder. A composed answer
    is asked for only for what happened over the whole world, and only when ``client`` is given;
    every other answer is the inspector's words. ``saved`` is every name the account holder saved,
    each replaced in what the composer is sent.
    """
    if scene is None:
        return refused(SocietyRefusal.NO_SOCIETY_HERE)
    if scene.collision:
        return refused(SocietyRefusal.SYNTHETIC_NAME_COLLISION)
    catalog = inhabitant_words_catalog()
    if scene.profile not in catalog.profiles:
        return refused(SocietyRefusal.PROFILE_HAS_NO_WORDS)
    if selector.aspect is SocietyAspect.TALK_CONTENT:
        return refused(SocietyRefusal.TALK_HAS_NO_CONTENT)
    if selector.aspect is SocietyAspect.UNRECORDED:
        return refused(SocietyRefusal.NOT_SIMULATED)
    if not scene.people:
        return refused(SocietyRefusal.NOBODY_HERE)
    builder = _Builder(scene, catalog)
    if selector.scope is SocietyScope.SELECTED:
        subject = _subject(scene)
        if subject is None:
            return refused(SocietyRefusal.SELECT_A_PERSON)
        clauses = _person_answer(builder, subject, selector.aspect)
    elif selector.scope is SocietyScope.WORLD and selector.aspect is SocietyAspect.RECENT:
        if not scene.events:
            return SocietyAnswer(
                answer=Answer(
                    clauses=[
                        AnswerClause(
                            text="Nothing has been recorded in this world's simulation yet.",
                            type=ClauseType.META,
                        ),
                        _closing(),
                    ]
                ),
                abstention=Abstention.NOT_CAPTURED,
            )
        shown_span, lines = _happened(builder)
        packet = builder.packet()
        deterministic = Answer(clauses=[shown_span, *lines, _closing()])
        if client is None:
            return SocietyAnswer(answer=deterministic, packet=packet)
        composed = compose_society_answer(
            client,
            scene.question,
            packet,
            log=log,
            saved=saved,
            max_tokens=max_tokens,
            attempts=attempts,
            started=started,
            clock=clock,
        )
        if composed.late is not None:
            # No choice came in time: the fixed words, said as such and by why, with room made for
            # saying so. They are "deterministic" only when a choice the model made was discarded.
            shown = lines[-(MAX_CLAUSES - 3) :] if lines else []
            said = _UNANSWERED_SHOWN.get(len(shown), _UNANSWERED_SHOWN_MANY)
            note = AnswerClause(text=f"{_UNANSWERED[composed.late]} {said}", type=ClauseType.META)
            items = builder.items[-len(shown) :] if shown else []
            return SocietyAnswer(
                answer=Answer(
                    clauses=[
                        *([_span(builder, items)] if items else []),
                        note,
                        *shown,
                        _closing(),
                    ]
                ),
                packet=packet,
                deterministic=composed.discarded,
                rejections=composed.rejections,
            )
        if not composed.items:
            return SocietyAnswer(
                answer=deterministic,
                packet=packet,
                deterministic=True,
                rejections=composed.rejections,
            )
        framing = (
            []
            if composed.framing is None
            else [
                AnswerClause(
                    text=catalog.words("phrase", f"framing_{composed.framing}"),
                    type=ClauseType.META,
                )
            ]
        )
        return SocietyAnswer(
            answer=Answer(
                clauses=[
                    _span(builder, composed.items, latest=False),
                    *framing,
                    *(_cited(item.line, item) for item in composed.items),
                    _closing(),
                ]
            ),
            packet=packet,
            repaired=bool(composed.rejections),
            rejections=composed.rejections,
        )
    elif selector.scope is SocietyScope.WORLD:
        clauses = _world_answer(builder, selector.aspect)
    else:
        raise ValueError(f"unhandled_society_scope: {selector.scope}")
    if clauses is None:
        raise ValueError(f"unhandled_society_aspect: {selector.scope} {selector.aspect}")
    return SocietyAnswer(answer=Answer(clauses=[*clauses, _closing()]), packet=builder.packet())


def _subject(scene: SocietyScene) -> str | None:
    """The one person a question about "them" is about: the selected one, or the one it names.

    A name that is not the selected person's, several people named, or a name several share, is
    no answer to "which person", and the caller refuses rather than choosing.
    """
    if scene.named_ambiguously:
        return None
    if scene.selected is not None:
        return scene.selected if set(scene.named) <= {scene.selected} else None
    return scene.named[0] if len(scene.named) == 1 else None


@dataclass(frozen=True, slots=True)
class _Chosen:
    """What :func:`compose_society_answer` returns: the lines chosen, or why there are none."""

    #: The chosen lines, in the packet's order; empty when the fixed words are given instead.
    items: tuple[SocietyEvidenceItem, ...] = ()
    framing: Framing | None = None
    rejections: tuple[str, ...] = ()
    #: Why no choice came in time (a key of ``_UNANSWERED``), so the fixed words say so.
    late: str | None = None
    #: A choice the model made was refused on the way.
    discarded: bool = False


def compose_society_answer(
    client: ModelClient,
    question: str,
    packet: SocietyEvidencePacket,
    *,
    log: CallLog,
    saved: Sequence[SavedName],
    max_tokens: int,
    attempts: int,
    started: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> _Chosen:
    """Ask the composer which event lines answer the question; check them; ask once more.

    **The composer chooses and never writes.** It returns the tokens of the lines that answer the
    question, at most :data:`MAX_CHOSEN_LINES`, and optionally one :class:`Framing`; the answer is
    each chosen line in its own fixed words, cited to it, in the packet's order. So no sentence can
    say what no line says: three reviews of a composer that wrote prose each found another way to
    recombine the lines' words into a new claim, speech moved onto somebody among them. The one
    thing checked is that every token is in the packet; a choice naming one that is not is refused,
    and asked for once more.

    **A timeout or any failed call ends composition at once, with no second attempt.** The answer
    is already in hand in fixed words, and composing is optional beside it, so the person waits on
    one attempt's bound at most rather than on two. A refused choice is asked for again only while
    at least one attempt's bound is left of :data:`ANSWER_WAIT_BUDGET_SECONDS`, counted from
    ``started``, the question's start (this call's, when not given); otherwise it too ends
    composition, with the fixed words. That bound is the reasoning role's own timeout from the model
    manifest, 60 seconds derived from the longest composer latency measured, for one attempt as the
    API's client makes it; this path does not shorten it, because a per-request timeout is not
    something the client offers (``exulanica/models``). Every attempt is recorded in the call log.
    The composer is sent the lines and the question, through the one policy boundary every hosted
    request passes. Nothing here is photograph-derived, so no photograph right is asked.

    **Every saved name is replaced here, a place's included, whatever right the account holder
    granted.** A place-name right is granted for a use whose purpose the account holder read
    (``exulanica/consent/place-name-uses.v1.json``), and the reasoning role's is writing an answer
    about their photographs, not about the world's simulated people. So this path is no use of that
    right, and no place's name is left for the boundary to release.
    """
    asked = redact_names(question, saved).text
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SOCIETY_COMPOSER_SYSTEM},
        {"role": "user", "content": f"{render_society_packet(packet)}\n\nQuestion: {asked}"},
    ]
    began = clock() if started is None else started
    bound = float(client.manifest[Role.REASONING_CHEAP].timeout_seconds)
    rejections: tuple[str, ...] = ()
    for attempt in range(1, attempts + 1):
        try:
            composed = client.structured(
                Role.REASONING_CHEAP,
                messages,
                SocietyLineChoice,
                prompt_version=PROMPT_VERSION,
                max_tokens=max_tokens,
            )
            log.record(composed.call)
            items = _chosen_lines(composed.value, packet)
            return _Chosen(items=items, framing=composed.value.framing, rejections=rejections)
        except AnswerRejected as rejected:
            rejections = rejected.reasons
            log.rejected(rejections)
            if attempt == attempts:
                break
            left = ANSWER_WAIT_BUDGET_SECONDS - (clock() - began)
            if left < bound:
                # Asking again could outlast the bound, and the fixed words are ready now.
                return _Chosen(
                    rejections=(*rejections, "composer_repair_skipped: the wait bound"),
                    late="no_time",
                    discarded=True,
                )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That choice was refused for these reasons:\n"
                        + "\n".join(f"- {reason}" for reason in rejected.reasons)
                        + "\n\nChoose again, only from the tokens in the list."
                    ),
                }
            )
        except (StructuredOutputError, TruncatedResponseError) as exc:
            rejections = (str(exc),)
            break
        except ModelError as exc:
            # Timed out, failed or refused by the budget: nothing was chosen to discard.
            return _Chosen(
                rejections=(*rejections, f"composer_unanswered: {type(exc).__name__}"),
                late="timed_out" if getattr(exc, "timed_out", False) else "failed",
                discarded=bool(rejections),
            )
    return _Chosen(rejections=rejections, discarded=True)


def _chosen_lines(
    choice: SocietyLineChoice, packet: SocietyEvidencePacket
) -> tuple[SocietyEvidenceItem, ...]:
    """The lines a choice names, once each, in the packet's order; a token not in it is refused.

    Each entry is read as the tokens written in it, so two tokens written into one entry are both
    read, as the live composer was measured writing them (``7S3NG9EFUH", "VFS2MRJ9DY``). Every token
    must be in the packet, an entry with no token in it is refused, and so is a choice of more than
    :data:`MAX_CHOSEN_LINES` lines in all, which the schema's cap on entries does not bound. A
    reason names only token-shaped text, never an entry's own words, because the reasons are
    returned with the answer.
    """
    written = [_TOKEN_TEXT.findall(entry) for entry in choice.lines]
    reasons: list[str] = []
    empty = sum(1 for tokens in written if not tokens)
    if empty:
        reasons.append(f"{empty} of the entries hold no token from the list")
    unknown = [token for tokens in written for token in tokens if packet.resolve(token) is None]
    reasons += [f"{token} is not a token in the list" for token in dict.fromkeys(unknown)]
    chosen = {token for tokens in written for token in tokens}
    if len(chosen) > MAX_CHOSEN_LINES:
        reasons.append(f"the choice names {len(chosen)} lines; choose at most {MAX_CHOSEN_LINES}")
    if reasons:
        raise AnswerRejected(tuple(reasons))
    return tuple(item for item in packet.items if item.token in chosen)


def render_society_packet(packet: SocietyEvidencePacket) -> str:
    """The event lines as the composer is sent them: a token, then the line."""
    lines = [
        "SIMULATION EVENTS",
        "One recorded event per line. The bracketed token names the line.",
        *(f"[{item.token}] {item.line}" for item in packet.items),
    ]
    return "\n".join(lines)


def named_inhabitants(packet: SocietyEvidencePacket | None) -> Iterable[tuple[str, uuid.UUID]]:
    """The inhabitant placeholders an answer may carry, for the route's map."""
    return () if packet is None else packet.inhabitants


def planner_line(scene: SocietyScene | None) -> str | None:
    """What the planner is told of the world's people: that they are in view, and who is selected.

    By placeholder only, so no inhabitant's name reaches the planner's request.
    """
    if scene is None:
        return None
    line = "simulated people are in view."
    if scene.selected is not None:
        line += f" The person selected in the world is {scene.labels.person(scene.selected)}."
    return line


def still_readable(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    context: SocietyContext,
    authorize: Any,
) -> bool:
    """Whether the society is still there after the composer's wait, read from its row alone.

    Not a second authorization: each reads and hashes every reviewed asset its input names, and
    the question paid for its own already. A withdrawal made while the composer writes applies from
    the next question.
    """
    repository = SocietyRepository(connection, workspace_id, world_id=world_id)
    return repository._row(context.version_id) is not None
