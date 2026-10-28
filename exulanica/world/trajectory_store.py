"""PostgreSQL reader and project-checkpoint adapter for ``exulanica.world-trajectory/v1``."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.canonical import sha256_of_canonical
from exulanica.world.decision_roles import DecisionRole, decision_roles
from exulanica.world.role_decisions import ANSWER_BY, ANSWER_WITH_LINE_BY, AnsweringMechanism
from exulanica.world.society import UnknownSociety
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_decisions import validate_decision_receipt
from exulanica.world.society_engines import society_engine

__all__ = [
    "build_trajectory_bundle",
    "project_decisions_to_trajectory_inputs",
    "read_trajectory_decisions",
]

_LINE_OPTION_KINDS = frozenset({"say_to", "say_all", "spoke", "spoke_to_all", "talk"})


def _option_takes_line(option: Mapping[str, Any]) -> bool:
    if isinstance(option.get("takes_line"), bool):
        return bool(option["takes_line"])
    kind = str(option.get("kind") or option.get("action") or "")
    label = str(option.get("label") or "").lower()
    return kind in _LINE_OPTION_KINDS or label.startswith("say ")


def read_trajectory_decisions(
    society: Any,
    version_id: uuid.UUID,
    *,
    role: DecisionRole | None = None,
    limit: int = 2000,
    subject_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
    authorized: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Query a world version's recorded decision requests, receipts, dispositions, and
    counterfactual branch asks from PostgreSQL."""
    resolved_role = decision_roles().deciding_for("person") if role is None else role
    society._lock()
    row = society._row(version_id, lock=True)
    if row is None:
        raise UnknownSociety("society is unavailable")
    if (
        authorized is None
        or authorized.get("society_id") != row["society_id"]
        or authorized.get("version_id") != version_id
    ):
        society.snapshot(version_id)
    if not society_engine(row["engine_version"]).model_decisions:
        return []

    decision_repo = SocietyDecisionRepository(society)
    rows = decision_repo.connection.execute(
        "select d.decision_seq, d.document as decision, r.document as request, d.recorded_at, "
        "t.disposition, t.tick as consumed_tick, "
        "(select e.document->>'reason' from world_society_event e "
        "where e.workspace_id=d.workspace_id and e.society_id=d.society_id "
        "and e.tick=t.tick and e.event_kind='decision_applied' "
        "and (e.document->>'decision_seq')::bigint=d.decision_seq) as disposition_reason "
        "from world_society_decision d "
        "join world_society_decision_request r using(workspace_id, society_id, request_id) "
        "left join world_society_transition_decision t "
        "using(workspace_id, society_id, decision_seq) "
        "where d.workspace_id=%s and d.society_id=%s and d.document->>'profile'=%s "
        "and (%s::uuid is null or r.subject_id=%s::uuid) "
        "and (%s::uuid is null or r.request_id=%s::uuid) "
        "order by d.decision_seq desc limit %s",
        (
            row["workspace_id"],
            row["society_id"],
            resolved_role.receipt_profile,
            subject_id,
            subject_id,
            request_id,
            request_id,
            limit,
        ),
    ).fetchall()
    if not rows:
        return []

    ordered_rows = list(reversed(rows))
    request_uuids = [uuid.UUID(str(value["request"]["request_id"])) for value in ordered_rows]
    ask_rows = decision_repo.connection.execute(
        "select ask_id, request_id, provider, model_id, mechanism, prompt_version, "
        "messages_sha256, request_messages_sha256, status, reason, document, asked_at "
        "from world_society_decision_ask "
        "where workspace_id=%s and society_id=%s and request_id = any(%s) "
        "order by asked_at, ask_id",
        (row["workspace_id"], row["society_id"], request_uuids),
    ).fetchall()

    originals: dict[str, tuple[str | None, str | None]] = {}
    for value in ordered_rows:
        req_id_str = str(value["request"]["request_id"])
        proposal = value["decision"].get("proposal")
        if isinstance(proposal, Mapping):
            originals[req_id_str] = (proposal.get("label"), proposal.get("line"))
        else:
            originals[req_id_str] = (None, None)

    branches_by_request: dict[str, list[dict[str, Any]]] = {}
    rejected_by_request: dict[str, list[dict[str, Any]]] = {}
    for ask_row in ask_rows:
        req_id_str = str(ask_row["request_id"])
        ask_doc = ask_row["document"] if isinstance(ask_row["document"], Mapping) else {}
        proposal = ask_doc.get("proposal") if isinstance(ask_doc.get("proposal"), Mapping) else None
        option = proposal.get("option") if isinstance(proposal, Mapping) else None
        ask_label = proposal.get("label") if isinstance(proposal, Mapping) else None
        ask_line = proposal.get("line") if isinstance(proposal, Mapping) else None
        orig_label, orig_line = originals.get(req_id_str, (None, None))
        if ask_row["status"] == "accepted" and isinstance(ask_label, str):
            branches_by_request.setdefault(req_id_str, []).append(
                {
                    "ask_id": str(ask_row["ask_id"]),
                    "provider": str(ask_row["provider"]),
                    "model_id": str(ask_row["model_id"]),
                    "mechanism": str(ask_row["mechanism"]),
                    "same_choice": bool(
                        orig_label is not None and ask_label == orig_label and ask_line == orig_line
                    ),
                    "label": ask_label,
                    "kind": (
                        str(option["kind"])
                        if isinstance(option, Mapping) and option.get("kind") is not None
                        else "action"
                    ),
                    "line": str(ask_line) if ask_line is not None else None,
                    "target_id": (
                        str(option["target_id"])
                        if isinstance(option, Mapping) and option.get("target_id") is not None
                        else None
                    ),
                }
            )
        elif ask_row["status"] == "rejected":
            rejected_by_request.setdefault(req_id_str, []).append(
                {
                    "label": str(ask_label) if ask_label is not None else None,
                    "line": str(ask_line) if ask_line is not None else None,
                    "model_id": str(ask_row["model_id"]),
                    "reason": str(ask_row["reason"]),
                }
            )

    world_id_str = str(getattr(society, "world_id", None) or "world:default")
    version_id_str = str(version_id)
    turns: list[dict[str, Any]] = []
    for value in ordered_rows:
        receipt = value["decision"]
        request = value["request"]
        validate_decision_receipt(receipt, request)
        req_id_str = str(request["request_id"])
        raw_disp = value["disposition"]
        if raw_disp is not None:
            disposition = str(raw_disp)
        else:
            disposition = "applied" if receipt["status"] == "accepted" else str(receipt["status"])
        reason = (
            str(receipt["reason"])
            if disposition == "applied"
            else str(value["disposition_reason"] or receipt["reason"])
        )
        turns.append(
            {
                "world_id": world_id_str,
                "version_id": version_id_str,
                "request": request,
                "decision": receipt,
                "status": str(receipt["status"]),
                "disposition": disposition,
                "reason": reason,
                "branches": branches_by_request.get(req_id_str, []),
                "rejected_proposals": rejected_by_request.get(req_id_str, []),
            }
        )
    return turns


def build_trajectory_bundle(
    society: Any,
    version_id: uuid.UUID,
    *,
    role: DecisionRole | None = None,
    limit: int = 2000,
    subject_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
    authorized: Mapping[str, Any] | None = None,
) -> Any:
    """Query PostgreSQL for a world version's recorded decisions and counterfactual asks and
    return its canonical ``exulanica.world-trajectory/v1`` bundle."""
    from exulanica.world.trajectories import export_trajectories

    world_id_str = str(getattr(society, "world_id", None) or "world:default")
    decisions = read_trajectory_decisions(
        society,
        version_id,
        role=role,
        limit=limit,
        subject_id=subject_id,
        request_id=request_id,
        authorized=authorized,
    )
    return export_trajectories(
        decisions,
        world_id=world_id_str,
        version_id=str(version_id),
    )


def project_decisions_to_trajectory_inputs(
    checkpoint: Mapping[str, Any],
    sessions: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Convert a project checkpoint (``exulanica.world-project/v1``) and its session evidence
    documents (``exulanica.world-project-evidence/v1``) into trajectory decision inputs."""
    source = checkpoint.get("source") if isinstance(checkpoint.get("source"), Mapping) else {}
    world_id = str(source.get("world_id") or "world:default")
    version_id = str(source.get("version_id") or "version:default")

    bindings_by_sha: dict[str, Mapping[str, Any]] = {}
    models_by_thing: dict[str, Mapping[str, Any]] = {}
    for model in checkpoint.get("models") or ():
        if isinstance(model, Mapping):
            models_by_thing[str(model.get("thing_id"))] = model
            bindings_by_sha[sha256_of_canonical(model).hex()] = model

    session_list: list[Mapping[str, Any]] = (
        list(sessions.values()) if isinstance(sessions, Mapping) else list(sessions)
    )
    for session_doc in session_list:
        for model in session_doc.get("models") or ():
            if isinstance(model, Mapping):
                bindings_by_sha[sha256_of_canonical(model).hex()] = model

    all_decisions: list[Mapping[str, Any]] = list(checkpoint.get("decisions") or ())
    for session_doc in session_list:
        all_decisions.extend(session_doc.get("decisions") or ())

    inputs: list[dict[str, Any]] = []
    seen_records: set[str] = set()
    for decision in all_decisions:
        if not isinstance(decision, Mapping):
            continue
        record_id = str(decision.get("record_id") or "")
        if record_id in seen_records:
            continue
        seen_records.add(record_id)

        thing_id = str(decision.get("thing_id") or "subject:1")
        binding = (
            bindings_by_sha.get(str(decision.get("binding_sha256") or ""))
            or models_by_thing.get(thing_id)
            or {}
        )
        readable = (
            decision.get("readable") if isinstance(decision.get("readable"), Mapping) else None
        )
        receipt = decision.get("receipt") if isinstance(decision.get("receipt"), Mapping) else None
        model_id = str(
            (readable or {}).get("served_model_id")
            or (receipt or {}).get("served_model_id")
            or binding.get("model_id")
            or binding.get("revision")
            or "unknown-model"
        )

        raw_options = list(decision.get("options") or ())
        readable_labels = list((readable or {}).get("options") or ())
        offered_options: list[dict[str, Any]] = []
        option_label_by_id: dict[str, str] = {}
        for idx, opt in enumerate(raw_options):
            if not isinstance(opt, Mapping):
                continue
            opt_id = str(opt.get("option_id") or f"option:{idx + 1}")
            action_kind = str(opt.get("action") or "action")
            label = (
                str(readable_labels[idx])
                if idx < len(readable_labels) and isinstance(readable_labels[idx], str)
                else f"{opt_id}:{action_kind}"
            )
            option_label_by_id[opt_id] = label
            offered_options.append(
                {
                    "option_id": opt_id,
                    "label": label,
                    "kind": action_kind,
                    "takes_line": _option_takes_line({"label": label, "kind": action_kind}),
                    "target_id": (
                        str(opt["target_id"]) if opt.get("target_id") is not None else None
                    ),
                }
            )

        chosen_opt_id = decision.get("chosen_option_id")
        chosen_label = (
            str(readable["choice"])
            if readable and isinstance(readable.get("choice"), str)
            else (
                option_label_by_id.get(str(chosen_opt_id))
                if chosen_opt_id is not None
                else None
            )
        )
        chosen_line = (
            str(readable["line"])
            if readable and readable.get("line") is not None
            else None
        )
        matched_opt = next((o for o in offered_options if o["label"] == chosen_label), None)
        chosen_action = (
            {
                "label": chosen_label,
                "kind": matched_opt["kind"] if matched_opt else "action",
                "line": chosen_line,
                "target_id": matched_opt["target_id"] if matched_opt else None,
            }
            if chosen_label is not None
            else None
        )

        outcome = str(decision.get("outcome") or "not-applied")
        status = str(
            (receipt or readable or {}).get("status")
            or ("accepted" if outcome == "applied" or chosen_action is not None else "rejected")
        )
        disposition = str(
            (receipt or readable or {}).get("disposition")
            or ("applied" if outcome == "applied" else "rejected")
        )
        reason = str(
            decision.get("reason_code")
            or (receipt or readable or {}).get("reason")
            or ("validated_choice" if disposition == "applied" else "answer_not_offered")
        )

        situation_text = (
            str(readable["situation"])
            if readable and isinstance(readable.get("situation"), str)
            else f"Subject: {thing_id}\nTick: {decision.get('tick', 0)}"
        )
        takes_line = any(o.get("takes_line") for o in offered_options)
        answer_hint = (ANSWER_WITH_LINE_BY if takes_line else ANSWER_BY)[
            AnsweringMechanism.TOOL_CALL
        ]
        user_content = "\n".join(
            [
                situation_text,
                "What you can do now:",
                *(f"- {o['label']}" for o in offered_options),
                answer_hint,
            ]
        )
        messages = [
            {
                "role": "system",
                "content": "You are deciding what one inhabitant of this world does next.",
            },
            {"role": "user", "content": user_content},
        ]

        inputs.append(
            {
                "world_id": world_id,
                "version_id": version_id,
                "request_id": record_id.removeprefix("request:"),
                "tick": int(decision.get("tick") or 0),
                "subject_id": thing_id,
                "model_id": model_id,
                "messages": messages,
                "offered_options": offered_options,
                "chosen_action": chosen_action,
                "status": status,
                "disposition": disposition,
                "reason": reason,
                "latency_ms": int(decision.get("elapsed_ms") or 0),
                "cost_usd": str((receipt or readable or {}).get("cost_usd") or "0"),
                "branches": list(decision.get("branches") or ()),
            }
        )
    return inputs
