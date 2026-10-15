"""What a question about a world's simulated people names, and what its answer is made of.

The society and inhabitant the page shows (:class:`SocietyContext`), why a question is not
answered (:class:`SocietyRefusal`, whose sentences :mod:`exulanica.selection.society_question`
holds), each citable line (:class:`SocietyEvidenceItem`, of truth class ``simulation`` and never
evidence of a personal visit), the packet the lines are cited from, and the answer
:func:`~exulanica.selection.society_question.answer_about_society` returns. Shapes only: nothing
here reads the database or asks a model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from exulanica.errors import ExulanicaError
from exulanica.selection.answer import Abstention, Answer
from exulanica.selection.packet import ValueReference

#: The truth class of everything a society answer cites, as ``build_content_packet`` names simulated
#: content: never a memory, and never evidence of a personal visit.
SIMULATION: Final = "simulation"


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
    #: The line as the composer is sent it: placeholders and catalog words, and the name of the
    #: model a person's owner chose when the line says that model picked their goal
    #: (``Manifest.model_name``: a manifest description, never anything a person wrote).
    line: str
    #: For an event: the society input its minute consumed, as the event's document records it.
    #: Null for a state line. Never sent to a model: the lines are.
    input_seq: int | None = None
    #: For an event whose target is a placed authored object: that object's id. Null otherwise.
    object_id: str | None = None
    #: The version edit that last set that object at or before the authored state the input
    #: followed (the input's ``authored_state.edit_seq``), by sequence and id. Null when the
    #: event names no placed object, the input records no authored state, or no edit is found.
    edit_seq: int | None = None
    edit_id: uuid.UUID | None = None

    @property
    def truth_class(self) -> str:
        return SIMULATION

    @property
    def personal_visit_evidence(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class SocietyEvidencePacket:
    """At most :data:`~exulanica.selection.society_scene.EVENT_LINES` event lines, or the state
    lines of the people asked about.

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
    """What :func:`~exulanica.selection.society_question.answer_about_society` returns for
    ``answer_question`` to record."""

    answer: Answer
    packet: SocietyEvidencePacket | None = None
    abstention: Abstention | None = None
    #: True only when a composer was asked and its output discarded, as ``AnswerView`` means it.
    #: An answer in the inspector's words was never a model's to discard.
    deterministic: bool = False
    rejections: tuple[str, ...] = ()
