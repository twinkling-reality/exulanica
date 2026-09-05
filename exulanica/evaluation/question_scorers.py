"""Score declared gold plans and deterministic answers without a model or a user decision."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from exulanica.evaluation.counts import Count, NamedCase
from exulanica.evaluation.ground_truth import GroundTruth
from exulanica.evaluation.questions import GoldQuestions, derive_questions
from exulanica.selection import Session, execute, parse, validate
from exulanica.selection.answer import (
    ClauseType,
    abstain,
    render_deterministic_answer,
    validate_answer,
)
from exulanica.selection.packet import build_packet

QUESTION_COMPONENTS = (
    "M8.plan_validity",
    "M8.gold_result_exact_match",
    "M1.answer_citation_grounding",
)


@dataclass(frozen=True)
class QuestionScores:
    results: dict[str, Count | None]
    blocked: dict[str, str]
    observations: tuple[dict[str, Any], ...]


def score_gold_questions(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    truth: GroundTruth,
    questions: GoldQuestions,
) -> QuestionScores:
    """Measure the real compiler, SQL, packet, clause and citation-token path.

    Plan validity is recorded per parse, reference/schema validation and execution stage. Object
    retrieval is a diagnostic of this pipeline and this fixed appearance phrase, never person or
    entity recall. The deterministic renderer is selected explicitly; no model was asked to fail.
    The corpus must be ingested in full and without unrelated captures, or all components block.
    """
    if questions != derive_questions(truth):
        raise ValueError("questions disagree with manifest-derived answers or rules")
    rows = connection.execute(
        "select blob_sha256 from capture where workspace_id = %s and deleted_at is null",
        (workspace,),
    ).fetchall()
    ingested = {bytes(row["blob_sha256"]).hex() for row in rows}
    if ingested != set(truth.by_hash) or len(rows) != len(truth.frames):
        reason = (
            "Gold questions require each manifest photo exactly once and no unrelated "
            "captures; incomplete or mixed workspaces are not scored."
        )
        return QuestionScores(
            dict.fromkeys(QUESTION_COMPONENTS), dict.fromkeys(QUESTION_COMPONENTS, reason), ()
        )

    cases: dict[str, list[NamedCase]] = {key: [] for key in QUESTION_COMPONENTS}
    observations: list[dict[str, Any]] = []
    for question in questions.questions:
        record: dict[str, Any] = {
            "question_id": question.question_id,
            "question": question.question,
            "dimension": question.dimension,
            "plan_source": "manifest-derived declared gold plan",
            "expected_photo_sha256": list(question.expected_photo_sha256),
        }
        observations.append(record)
        if question.plan is None:
            record["blocked_on"] = question.blocked_on
            continue
        phase = "parse"
        record["stage_results"] = {"parse": False, "schema": False, "execute": False}
        try:
            # A failed SQL statement is isolated so the next case is still measured.
            with connection.transaction():
                plan = parse(question.plan)
                record["stage_results"]["parse"] = True
                cases["M8.plan_validity"].append(NamedCase(f"{question.question_id}:parse", True))
                phase = "schema/reference validation"
                validated = validate(connection, plan, Session(workspace, uuid.UUID(int=0)))
                record["stage_results"]["schema"] = True
                cases["M8.plan_validity"].append(NamedCase(f"{question.question_id}:schema", True))
                phase = "execution"
                result = execute(connection, validated)
                record["stage_results"]["execute"] = True
                cases["M8.plan_validity"].append(NamedCase(f"{question.question_id}:execute", True))
                record["plan"] = plan.model_dump(mode="json")
                record["bounded_result"] = result.truncated
                actual = {capture.blob_id.hex for capture in result.captures}
                expected = set(question.expected_photo_sha256)
                record["retrieved_photo_sha256"] = sorted(actual)
                exact = not result.truncated and actual == expected
                cases["M8.gold_result_exact_match"].append(
                    NamedCase(
                        question.question_id,
                        exact,
                        ""
                        if exact
                        else f"bounded_result={result.truncated}; "
                        f"missing={sorted(expected - actual)}; "
                        f"unexpected={sorted(actual - expected)}",
                    )
                )
                packet = build_packet(connection, result, workspace_id=workspace)
                if packet.is_empty:
                    answer, reason = abstain(packet)
                    code = reason.value
                else:
                    answer = render_deterministic_answer(packet)
                    code = None
                record.update(
                    {
                        "answer_source": "deterministic renderer, no model call",
                        "answer": answer.model_dump(mode="json"),
                        "citation_photo_sha256": {
                            item.token: item.address.blob_id.hex for item in packet.items
                        },
                    }
                )
                validate_answer(answer, packet)
                historical = [c for c in answer.clauses if c.type is ClauseType.HISTORICAL]
                cited = [packet.resolve(token) for c in historical for token in c.citations]
                count = packet.value("capture_count")
                shown = packet.value("shown_count")
                # This is a check of the declared deterministic template, not semantic judging
                # of arbitrary prose. Checking only the packet would allow the renderer to
                # state a different count while its unused backing value remained correct.
                count_is_rendered = shown is not None and any(
                    clause.type is ClauseType.META
                    and clause.text
                    == f"{question.expected_capture_count} captures match, "
                    f"and I can show you {shown.text}."
                    and set(clause.value_refs) == {"capture_count", "shown_count"}
                    for clause in answer.clauses
                )
                grounded = (
                    not expected and code == "UNANSWERABLE_NOT_CAPTURED" and not historical
                ) or (
                    bool(expected)
                    and bool(historical)
                    and bool(cited)
                    and all(clause.citations for clause in historical)
                    and count is not None
                    and count.text == str(question.expected_capture_count)
                    and count_is_rendered
                    and all(
                        item is not None and item.address.blob_id.hex in expected for item in cited
                    )
                )
                cases["M1.answer_citation_grounding"].append(
                    NamedCase(
                        question.question_id,
                        grounded,
                        ""
                        if grounded
                        else "Deterministic answer count, abstention or cited "
                        "photo addresses disagree with manifest gold.",
                    )
                )
                record.update(
                    {
                        "abstention": code,
                        "gold_result_exact_match": exact,
                        "answer_grounded": grounded,
                    }
                )
        except Exception as exc:
            evidence = f"{phase}: {type(exc).__name__}: {exc}"
            # Exceptions are failures, never silently removed from the denominator.
            for stage, passed in record["stage_results"].items():
                if not passed:
                    cases["M8.plan_validity"].append(
                        NamedCase(f"{question.question_id}:{stage}", False, evidence)
                    )
            for key in ("M8.gold_result_exact_match", "M1.answer_citation_grounding"):
                if not any(case.name == question.question_id for case in cases[key]):
                    cases[key].append(NamedCase(question.question_id, False, evidence))
            record["error"] = evidence

    results = {
        key: Count(sum(case.passed for case in group), len(group), tuple(group)) if group else None
        for key, group in cases.items()
    }
    blocked = {
        key: "No eligible gold question reached this component."
        for key, value in results.items()
        if value is None
    }
    return QuestionScores(results, blocked, tuple(observations))
