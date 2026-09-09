"""One Selection primitive, and the path from a question to an answer that cites its evidence.

ADR-0005: "There is one Selection primitive. Every surface is an entry point that produces one,
and nothing else in the system knows where a Selection came from." The Companion, the World
Index, the Atlas Map and direct interaction all build a :class:`~exulanica.selection.plan.
SelectionPlan`, and it goes through the same validation and the same executor whichever built it.

Five modules, and the order is the pipeline:

*   :mod:`exulanica.selection.plan` is what may be asked. A closed vocabulary with one free-text
    field, and no way to express a table, a column, an operator or a workspace.
*   :mod:`exulanica.selection.validation` is what may be run. It only ever rejects, and the type
    it returns is the only thing the executor accepts.
*   :mod:`exulanica.selection.executor` is what runs. No model, parameterized SQL, a read-only
    transaction with a statement timeout.
*   :mod:`exulanica.selection.packet` is what a model may see: at most 24 items with per-request
    citation tokens, and the exact numbers an answer is allowed to contain.
*   :mod:`exulanica.selection.answer` is what a model may say, and the validator that refuses the
    rest. A correct, cited answer exists even when the model complies with nothing.

:mod:`exulanica.selection.question` sequences them and owns the two model calls.
"""

from exulanica.selection.answer import (
    Abstention,
    Answer,
    AnswerClause,
    AnswerRejected,
    ClauseType,
    abstain,
    render_deterministic_answer,
    validate_answer,
)
from exulanica.selection.executor import (
    SelectedCapture,
    SelectedEntity,
    SelectionResult,
    Support,
    execute,
)
from exulanica.selection.packet import EvidenceItem, EvidencePacket, ValueReference, build_packet
from exulanica.selection.plan import (
    CaptureSelector,
    CaptureWindow,
    EntityMode,
    EntitySelector,
    EpistemicScope,
    Intent,
    PlaceSelector,
    ProcessingState,
    SelectionPlan,
)
from exulanica.selection.question import (
    PROMPT_VERSION,
    AnsweredQuestion,
    CallLog,
    EntityChoice,
    ModelCall,
    answer_question,
    compose_answer,
    entity_catalogue,
    propose_plan,
)
from exulanica.selection.validation import (
    RejectionCode,
    SelectionRejected,
    Session,
    ValidatedPlan,
    parse,
    validate,
)

__all__ = [
    "PROMPT_VERSION",
    "Abstention",
    "Answer",
    "AnswerClause",
    "AnswerRejected",
    "AnsweredQuestion",
    "CallLog",
    "CaptureSelector",
    "CaptureWindow",
    "ClauseType",
    "EntityChoice",
    "EntityMode",
    "EntitySelector",
    "EpistemicScope",
    "EvidenceItem",
    "EvidencePacket",
    "Intent",
    "ModelCall",
    "PlaceSelector",
    "ProcessingState",
    "RejectionCode",
    "SelectedCapture",
    "SelectedEntity",
    "SelectionPlan",
    "SelectionRejected",
    "SelectionResult",
    "Session",
    "Support",
    "ValidatedPlan",
    "ValueReference",
    "abstain",
    "answer_question",
    "build_packet",
    "compose_answer",
    "entity_catalogue",
    "execute",
    "parse",
    "propose_plan",
    "render_deterministic_answer",
    "validate",
    "validate_answer",
]
