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

:mod:`exulanica.selection.question` sequences them and composes the answer.
:mod:`exulanica.selection.planner` proposes the Selection a question asks for, and
:mod:`exulanica.selection.prompts` holds both prompts.

The names below are read from their modules on first use, so importing one module of this package
(a plan, a kind brief, a reader of the plan vocabulary) does not load the whole answer path.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from exulanica.selection.answer import (
        Abstention,
        Answer,
        AnswerClause,
        AnswerRejected,
        ClauseType,
        abstain,
        abstain_without_a_selection,
        render_deterministic_answer,
        validate_answer,
    )
    from exulanica.selection.executor import (
        SelectedCapture,
        SelectedContent,
        SelectedEntity,
        SelectionResult,
        Support,
        execute,
    )
    from exulanica.selection.packet import (
        EvidenceItem,
        EvidencePacket,
        ValueReference,
        build_packet,
    )
    from exulanica.selection.place_bridge import PlaceBridgeDecision, PlaceBridgeRepository
    from exulanica.selection.plan import (
        CaptureSelector,
        CaptureWindow,
        ContentPageCursor,
        ContentScope,
        ContentSelector,
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

#: Each name this package offers, and the module it is read from.
_HOMES = {
    "Abstention": "exulanica.selection.answer",
    "Answer": "exulanica.selection.answer",
    "AnswerClause": "exulanica.selection.answer",
    "AnswerRejected": "exulanica.selection.answer",
    "AnsweredQuestion": "exulanica.selection.question",
    "CallLog": "exulanica.selection.question",
    "CaptureSelector": "exulanica.selection.plan",
    "CaptureWindow": "exulanica.selection.plan",
    "ClauseType": "exulanica.selection.answer",
    "ContentPageCursor": "exulanica.selection.plan",
    "ContentScope": "exulanica.selection.plan",
    "ContentSelector": "exulanica.selection.plan",
    "EntityChoice": "exulanica.selection.question",
    "EntityMode": "exulanica.selection.plan",
    "EntitySelector": "exulanica.selection.plan",
    "EpistemicScope": "exulanica.selection.plan",
    "EvidenceItem": "exulanica.selection.packet",
    "EvidencePacket": "exulanica.selection.packet",
    "Intent": "exulanica.selection.plan",
    "ModelCall": "exulanica.selection.question",
    "PROMPT_VERSION": "exulanica.selection.question",
    "PlaceBridgeDecision": "exulanica.selection.place_bridge",
    "PlaceBridgeRepository": "exulanica.selection.place_bridge",
    "PlaceSelector": "exulanica.selection.plan",
    "ProcessingState": "exulanica.selection.plan",
    "RejectionCode": "exulanica.selection.validation",
    "SelectedCapture": "exulanica.selection.executor",
    "SelectedContent": "exulanica.selection.executor",
    "SelectedEntity": "exulanica.selection.executor",
    "SelectionPlan": "exulanica.selection.plan",
    "SelectionRejected": "exulanica.selection.validation",
    "SelectionResult": "exulanica.selection.executor",
    "Session": "exulanica.selection.validation",
    "Support": "exulanica.selection.executor",
    "ValidatedPlan": "exulanica.selection.validation",
    "ValueReference": "exulanica.selection.packet",
    "abstain": "exulanica.selection.answer",
    "abstain_without_a_selection": "exulanica.selection.answer",
    "answer_question": "exulanica.selection.question",
    "build_packet": "exulanica.selection.packet",
    "compose_answer": "exulanica.selection.question",
    "entity_catalogue": "exulanica.selection.question",
    "execute": "exulanica.selection.executor",
    "parse": "exulanica.selection.validation",
    "propose_plan": "exulanica.selection.question",
    "render_deterministic_answer": "exulanica.selection.answer",
    "validate": "exulanica.selection.validation",
    "validate_answer": "exulanica.selection.answer",
}

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
    "ContentPageCursor",
    "ContentScope",
    "ContentSelector",
    "EntityChoice",
    "EntityMode",
    "EntitySelector",
    "EpistemicScope",
    "EvidenceItem",
    "EvidencePacket",
    "Intent",
    "ModelCall",
    "PlaceBridgeDecision",
    "PlaceBridgeRepository",
    "PlaceSelector",
    "ProcessingState",
    "RejectionCode",
    "SelectedCapture",
    "SelectedContent",
    "SelectedEntity",
    "SelectionPlan",
    "SelectionRejected",
    "SelectionResult",
    "Session",
    "Support",
    "ValidatedPlan",
    "ValueReference",
    "abstain",
    "abstain_without_a_selection",
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


def __getattr__(name: str) -> Any:
    """An exported name, imported from its module on first use, or a module of this package."""
    module = _HOMES.get(name)
    if module is None:
        try:
            return importlib.import_module(f"{__name__}.{name}")
        except ModuleNotFoundError as missing:
            if missing.name != f"{__name__}.{name}":
                raise
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
