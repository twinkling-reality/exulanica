"""Synthetic world training data and counterfactual trajectory exporter.

Every recorded world decision in Exulanica binds an exact observation (``context`` and
``messages``), the offered affordance options, the model or player proposal, the deterministic
engine verdict, and any counterfactual branches (from ``asked_again`` / ``branches`` or
validator-rejected attempts).

This module projects those records into deterministic, zero-float ``exulanica.world-trajectory/v1``
datasets:

* **SFT (Supervised Fine-Tuning) records**: accepted and applied turns
  ``(world_id, version_id, tick, subject_id, model_id, messages, offered_options, chosen_action,
  latency_ms, cost_usd)``, ready for OpenAI / NVIDIA NeMo Gym tool-calling JSONL or OpenEnv
  episodes.
* **DPO / Preference & Validator pairs**: whenever a decision carries counterfactual branches or
  rejected proposals where the engine refused an invalid choice and fell back or re-asked, pairs
  ``(context_messages, offered_options, chosen_valid_action, rejected_or_alternative_action,
  verdict_reason)`` grounded in the deterministic world validator.
* **Counterfactual Agreement & Distillation Metrics**: pure integer summary statistics
  ``(total_decisions, applied_count, refused_count, counterfactual_pairs,
  agreement_rate_permille, mean_latency_ms)`` for evaluating a distilled student model against a
  frontier teacher model without floating-point drift.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from exulanica.canonical import canonical_json, round_half_down, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.things.lines import LineRefused, check_line, names_listener, repeats_line
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import ANSWER_BY, ANSWER_WITH_LINE_BY, AnsweringMechanism
from exulanica.world.society_decision_contract import situation as build_situation
from exulanica.world.trajectory_store import (
    build_trajectory_bundle,
    project_decisions_to_trajectory_inputs,
    read_trajectory_decisions,
)

__all__ = [
    "TRAJECTORY_PROFILE",
    "DpoPairRecord",
    "SftTrajectoryRecord",
    "TrajectoryBundle",
    "TrajectoryError",
    "TrajectoryMetrics",
    "assert_no_floats",
    "build_trajectory_bundle",
    "compute_trajectory_metrics",
    "export_trajectories",
    "extract_dpo_pairs",
    "extract_sft_records",
    "format_dpo_jsonl",
    "format_openai_tool_jsonl",
    "format_openenv_jsonl",
    "format_trajectory_jsonl",
    "project_decisions_to_trajectory_inputs",
    "read_trajectory_decisions",
    "to_dpo_preference_example",
    "to_openai_tool_example",
    "to_openenv_episode",
    "validate_proposal_verdict",
]

TRAJECTORY_PROFILE: Final = "exulanica.world-trajectory/v1"
_USD_PATTERN: Final = re.compile(r"^[0-9]{1,6}(\.[0-9]{1,12})?$")
_LINE_OPTION_KINDS: Final = frozenset({"say_to", "say_all", "spoke", "spoke_to_all", "talk"})


class TrajectoryError(CanonicalisationError, ValueError):
    """A trajectory input or record violates the zero-float or schema contract."""


class _RecordDict(dict[str, Any]):
    """Dictionary with attribute read access and deterministic canonical JSON serialization."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def to_dict(self) -> dict[str, Any]:
        return json.loads(canonical_json(self).decode("utf-8"))


class SftTrajectoryRecord(_RecordDict):
    """One verified SFT trajectory turn in ``exulanica.world-trajectory/v1``."""

    def to_openai_tool_example(self) -> dict[str, Any]:
        return to_openai_tool_example(self)

    def to_openenv_step(self) -> dict[str, Any]:
        return dict(self["openenv_step"])


class DpoPairRecord(_RecordDict):
    """One DPO / validator preference pair in ``exulanica.world-trajectory/v1``."""

    def to_dpo_example(self) -> dict[str, Any]:
        return to_dpo_preference_example(self)


class TrajectoryMetrics(_RecordDict):
    """Pure integer summary metrics for counterfactual agreement and distillation."""


class TrajectoryBundle(_RecordDict):
    """Complete ``exulanica.world-trajectory/v1`` export bundle."""

    def to_jsonl(self) -> str:
        return format_trajectory_jsonl(self)


def assert_no_floats(value: Any, path: str = "$") -> None:
    """Reject any floating-point value anywhere in a trajectory input or output."""
    if isinstance(value, bool) or value is None or isinstance(value, str | int):
        return
    if isinstance(value, float):
        raise TrajectoryError(
            f"float at {path}: exulanica.world-trajectory/v1 forbids floats; "
            "quantise to integer milliseconds, permille, or canonical USD string first"
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TrajectoryError(f"non-string key at {path}: {key!r}")
            assert_no_floats(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            assert_no_floats(item, f"{path}[{index}]")
        return
    raise TrajectoryError(f"unsupported type {type(value).__name__} at {path}")


def _canonical_sha256(value: Any) -> str:
    assert_no_floats(value)
    return sha256_of_canonical(value).hex()


def _require_non_empty_str(value: Any, field_name: str, fallback: str | None = None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if fallback is not None:
        return fallback
    raise TrajectoryError(f"{field_name} must be a non-empty string")


def _require_non_negative_int(value: Any, field_name: str, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool | float) or not isinstance(value, int):
        raise TrajectoryError(f"{field_name} must be a non-negative integer, got {value!r}")
    if value < 0:
        raise TrajectoryError(f"{field_name} must be >= 0, got {value}")
    return value


def _normalize_cost_usd(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, float):
        raise TrajectoryError("cost_usd must be a canonical decimal string, never a float")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise TrajectoryError("cost_usd cannot be negative")
        return str(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or not _USD_PATTERN.fullmatch(cleaned):
            raise TrajectoryError(f"cost_usd {value!r} is not a valid decimal USD string")
        return cleaned
    raise TrajectoryError(f"cost_usd must be a string, got {type(value).__name__}")


def _option_takes_line(option: Mapping[str, Any]) -> bool:
    if isinstance(option.get("takes_line"), bool):
        return bool(option["takes_line"])
    kind = str(option.get("kind") or option.get("action") or "")
    label = str(option.get("label") or "").lower()
    return kind in _LINE_OPTION_KINDS or label.startswith("say ")


def _normalize_options(raw_options: Sequence[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_options):
        if isinstance(raw, str):
            label = raw.strip()
            if not label:
                continue
            normalized.append(
                {
                    "option_id": f"option:{index + 1}",
                    "label": label,
                    "kind": "say_to" if label.lower().startswith("say ") else "action",
                    "takes_line": label.lower().startswith("say "),
                    "target_id": None,
                }
            )
        elif isinstance(raw, Mapping):
            assert_no_floats(raw, f"$.offered_options[{index}]")
            label = _require_non_empty_str(
                raw.get("label") or raw.get("words") or raw.get("action"),
                f"offered_options[{index}].label",
            )
            kind = str(raw.get("kind") or raw.get("action") or "action")
            target_id = raw.get("target_id")
            if target_id is None and isinstance(raw.get("target"), Mapping):
                target_id = raw["target"].get("target_id")
            normalized.append(
                {
                    "option_id": str(raw.get("option_id") or f"option:{index + 1}"),
                    "label": label,
                    "kind": kind,
                    "takes_line": _option_takes_line(raw),
                    "target_id": str(target_id) if target_id is not None else None,
                }
            )
        else:
            raise TrajectoryError(f"unsupported option at index {index}: {raw!r}")
    return normalized


def _build_messages(
    record: Mapping[str, Any],
    request: Mapping[str, Any],
    context: Mapping[str, Any],
    options: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    raw_messages = (
        record.get("messages")
        or record.get("context_messages")
        or request.get("messages")
        or (record.get("observation") or {}).get("messages")
    )
    if isinstance(raw_messages, Sequence) and not isinstance(raw_messages, str | bytes):
        built: list[dict[str, str]] = []
        for idx, msg in enumerate(raw_messages):
            if not isinstance(msg, Mapping):
                raise TrajectoryError(f"messages[{idx}] must be a mapping")
            assert_no_floats(msg, f"$.messages[{idx}]")
            built.append(
                {
                    "role": _require_non_empty_str(msg.get("role"), f"messages[{idx}].role"),
                    "content": str(msg.get("content") or ""),
                }
            )
        if built:
            return built

    # Reconstruct deterministically from context when messages were not pre-rendered.
    instruction = "You are deciding what one inhabitant of this world does next."
    lines: list[str] = []
    if context:
        # The request names its own role by profile; one that names none has no role to render with.
        profile = request.get("profile")
        role = decision_roles().for_request(profile) if isinstance(profile, str) else None
        if role is not None:
            try:
                mechanism_raw = (request.get("provider_config") or {}).get("mechanism")
                mechanism = (
                    AnsweringMechanism(str(mechanism_raw))
                    if mechanism_raw in {m.value for m in AnsweringMechanism}
                    else AnsweringMechanism.TOOL_CALL
                )
                return role.adapter.messages(role, context, mechanism)
            except Exception:
                instruction = role.terms_of(context).instruction
        try:
            lines.extend(build_situation(dict(context)))
        except Exception:
            if isinstance(context.get("here"), str):
                lines.append(f"Location: {context['here']}")
            if isinstance(context.get("tick"), int):
                lines.append(f"Minute: {context['tick']}")
    takes_line = any(opt.get("takes_line") for opt in options)
    answer_hint = (ANSWER_WITH_LINE_BY if takes_line else ANSWER_BY)[AnsweringMechanism.TOOL_CALL]
    user_lines = [
        *lines,
        "What you can do now:",
        *(f"- {opt['label']}" for opt in options),
        answer_hint,
    ]
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def validate_proposal_verdict(
    offered_options: Sequence[Mapping[str, Any]],
    proposed_label: str | None,
    proposed_line: str | None = None,
    *,
    context: Mapping[str, Any] | None = None,
    listener_name: str | None = None,
    recent_lines: Sequence[str] | None = None,
    line_characters_maximum: int = 200,
) -> str:
    """Deterministically validate a proposed ``(label, line)`` against the world's rules.

    Returns ``"validated_choice"`` when the proposal satisfies every offered option and line rule,
    or the deterministic refusal code (``"answer_not_offered"``, ``"line_where_none"``,
    ``"no_line_where_one"``, ``"line_breaks_rule"``, ``"line_names_listener"``,
    ``"line_said_before"``).
    """
    if not proposed_label or not isinstance(proposed_label, str):
        return "answer_not_offered"
    matched = next(
        (opt for opt in offered_options if opt.get("label") == proposed_label),
        None,
    )
    if matched is None:
        return "answer_not_offered"
    takes_line = _option_takes_line(matched)
    has_line = bool(proposed_line and proposed_line.strip())
    if takes_line != has_line:
        return "line_where_none" if has_line else "no_line_where_one"
    if not takes_line or proposed_line is None:
        return "validated_choice"

    max_chars = int((context or {}).get("line_characters_maximum") or line_characters_maximum)
    try:
        checked = check_line(proposed_line, maximum=max_chars)
    except LineRefused:
        return "line_breaks_rule"
    if checked != proposed_line:
        return "line_breaks_rule"

    inferred_listener = listener_name
    if inferred_listener is None:
        lower = proposed_label.lower()
        if lower.startswith("say something to "):
            rest = proposed_label[len("say something to ") :].split(",")[0].strip()
            if rest:
                inferred_listener = rest
    if inferred_listener and names_listener(checked, inferred_listener):
        return "line_names_listener"

    told: list[str] = list(recent_lines or ())
    if context:
        for key in ("said", "heard"):
            for entry in context.get(key) or ():
                if isinstance(entry, Mapping) and isinstance(entry.get("line"), str):
                    told.append(entry["line"])
    if told and repeats_line(checked, told):
        return "line_said_before"
    return "validated_choice"


def _normalize_action(
    raw_action: Any,
    offered_options: Sequence[Mapping[str, Any]],
    *,
    default_line: str | None = None,
    default_model_id: str | None = None,
) -> dict[str, Any] | None:
    if raw_action is None:
        return None
    if isinstance(raw_action, str):
        label = raw_action.strip()
        if not label:
            return None
        matched = next((o for o in offered_options if o["label"] == label), None)
        return {
            "label": label,
            "kind": matched["kind"] if matched else "action",
            "line": default_line,
            "target_id": matched["target_id"] if matched else None,
            **({"model_id": default_model_id} if default_model_id is not None else {}),
        }
    if isinstance(raw_action, Mapping):
        assert_no_floats(raw_action, "$.action")
        option = raw_action.get("option") if isinstance(raw_action.get("option"), Mapping) else {}
        label = (
            raw_action.get("label")
            or raw_action.get("chosen_label")
            or raw_action.get("choice")
            or raw_action.get("chose")
            or option.get("label")
        )
        if not isinstance(label, str) or not label.strip():
            kind = str(raw_action.get("kind") or option.get("kind") or "carried_on")
            said = raw_action.get("said")
            line = (
                raw_action.get("line")
                or (said.get("line") if isinstance(said, Mapping) else None)
                or default_line
            )
            matched = next((o for o in offered_options if o["kind"] == kind), None)
            label = matched["label"] if matched else kind
        else:
            label = label.strip()
            matched = next((o for o in offered_options if o["label"] == label), None)
            said = raw_action.get("said")
            line = (
                raw_action.get("line")
                if "line" in raw_action
                else (said.get("line") if isinstance(said, Mapping) else default_line)
            )
        kind = str(
            raw_action.get("kind")
            or option.get("kind")
            or (matched["kind"] if matched else "action")
        )
        target_id = (
            raw_action.get("target_id")
            or option.get("target_id")
            or (
                raw_action["target"].get("target_id")
                if isinstance(raw_action.get("target"), Mapping)
                else None
            )
            or (matched["target_id"] if matched else None)
        )
        model_info = raw_action.get("model")
        model_id = (
            raw_action.get("model_id")
            or (model_info.get("model_id") if isinstance(model_info, Mapping) else None)
            or (model_info.get("name") if isinstance(model_info, Mapping) else None)
            or default_model_id
        )
        return {
            "label": str(label),
            "kind": kind,
            "line": str(line) if line is not None else None,
            "target_id": str(target_id) if target_id is not None else None,
            **({"model_id": str(model_id)} if model_id is not None else {}),
        }
    raise TrajectoryError(f"unsupported action representation: {raw_action!r}")


def _unpack_decision_turn(
    item: Mapping[str, Any],
    *,
    default_world_id: str,
    default_version_id: str,
    index: int,
) -> dict[str, Any]:
    """Normalize either a raw ``{request, decision/receipt, event, branches}`` envelope or a
    direct decision dictionary into a canonical internal turn structure."""
    assert_no_floats(item, f"$.decisions[{index}]")
    request = item.get("request") if isinstance(item.get("request"), Mapping) else {}
    receipt = (
        item.get("decision")
        if isinstance(item.get("decision"), Mapping)
        else (item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {})
    )
    event = item.get("event") if isinstance(item.get("event"), Mapping) else {}
    event_doc = event.get("document") if isinstance(event.get("document"), Mapping) else {}
    context = (
        item.get("context")
        if isinstance(item.get("context"), Mapping)
        else (request.get("context") if isinstance(request.get("context"), Mapping) else {})
    )
    provider_cfg = (
        request.get("provider_config")
        if isinstance(request.get("provider_config"), Mapping)
        else {}
    )
    provider_rec = (
        receipt.get("provider")
        if isinstance(receipt.get("provider"), Mapping)
        else (item.get("provider") if isinstance(item.get("provider"), Mapping) else {})
    )

    world_id = _require_non_empty_str(
        item.get("world_id") or request.get("world_id"),
        "world_id",
        fallback=default_world_id,
    )
    version_id = _require_non_empty_str(
        item.get("version_id") or request.get("version_id"),
        "version_id",
        fallback=default_version_id,
    )
    request_id = _require_non_empty_str(
        item.get("request_id")
        or request.get("request_id")
        or receipt.get("request_id")
        or event_doc.get("request_id"),
        "request_id",
        fallback=f"request:{index + 1}",
    )
    tick_raw = (
        item.get("tick")
        if item.get("tick") is not None
        else (
            request.get("base_tick")
            if request.get("base_tick") is not None
            else (
                context.get("tick") if context.get("tick") is not None else event.get("tick", index)
            )
        )
    )
    tick = _require_non_negative_int(tick_raw, "tick")
    subject_id = _require_non_empty_str(
        item.get("subject_id")
        or request.get("subject_id")
        or receipt.get("subject_id")
        or context.get("subject_id")
        or event.get("subject_id"),
        "subject_id",
        fallback=f"subject:{index + 1}",
    )
    model_id = _require_non_empty_str(
        item.get("model_id")
        or provider_rec.get("served_model_id")
        or provider_rec.get("model_id")
        or provider_cfg.get("model_id")
        or (
            item["model"].get("model_id") or item["model"].get("name")
            if isinstance(item.get("model"), Mapping)
            else (item.get("model") if isinstance(item.get("model"), str) else None)
        ),
        "model_id",
        fallback="unknown-model",
    )
    decider_kind = str(
        item.get("decider_kind") or event_doc.get("origin") or provider_cfg.get("kind") or "model"
    )
    prompt_version = (
        item.get("prompt_version")
        or provider_rec.get("prompt_version")
        or provider_cfg.get("prompt_version")
    )

    raw_options = (
        item.get("offered_options")
        or item.get("options")
        or context.get("options")
        or (item.get("observation") or {}).get("offered_options")
        or ()
    )
    offered_options = _normalize_options(raw_options)
    if not offered_options:
        raise TrajectoryError(f"decision {request_id} must include at least one offered option")

    messages = _build_messages(item, request, context, offered_options)

    proposal = (
        item.get("chosen_action")
        or item.get("proposal")
        or receipt.get("proposal")
        or (
            {"label": item["chosen_label"], "line": item.get("line")}
            if "chosen_label" in item
            else None
        )
    )
    chosen_action = _normalize_action(proposal, offered_options, default_model_id=model_id)

    status = str(
        item.get("status")
        or receipt.get("status")
        or ("accepted" if chosen_action is not None else "rejected")
    )
    disposition = str(
        item.get("disposition")
        or event_doc.get("disposition")
        or (
            "applied"
            if item.get("event_kind") == "decision_applied" or status == "accepted"
            else "rejected"
        )
    )
    reason = str(
        item.get("reason")
        or event_doc.get("reason")
        or receipt.get("reason")
        or ("validated_choice" if disposition == "applied" else "answer_not_offered")
    )

    latency_raw = (
        item.get("latency_ms")
        if "latency_ms" in item
        else (
            provider_rec.get("latency_ms")
            if "latency_ms" in provider_rec
            else item.get("elapsed_ms")
        )
    )
    latency_ms = _require_non_negative_int(latency_raw, "latency_ms", default=0)
    has_latency = latency_raw is not None

    cost_raw = item.get("cost_usd") if "cost_usd" in item else provider_rec.get("cost_usd", "0")
    cost_usd = _normalize_cost_usd(cost_raw)

    branches = list(
        item.get("branches")
        or item.get("asked_again")
        or item.get("counterfactual_alternatives")
        or ()
    )
    rejected_proposals = list(item.get("rejected_proposals") or item.get("rejected_attempts") or ())
    # Also check provider calls if any earlier attempt was rejected before a retry succeeded
    for call in provider_rec.get("calls") or ():
        if isinstance(call, Mapping) and call.get("outcome") in (
            "label_not_offered",
            "line",
            "answer_not_offered",
        ):
            rejected_proposals.append(call)

    return {
        "world_id": world_id,
        "version_id": version_id,
        "request_id": request_id,
        "tick": tick,
        "subject_id": subject_id,
        "decider_kind": decider_kind,
        "model_id": model_id,
        "prompt_version": str(prompt_version) if prompt_version is not None else None,
        "context": context,
        "messages": messages,
        "offered_options": offered_options,
        "chosen_action": chosen_action,
        "status": status,
        "disposition": disposition,
        "reason": reason,
        "latency_ms": latency_ms,
        "has_latency": has_latency,
        "cost_usd": cost_usd,
        "branches": branches,
        "rejected_proposals": rejected_proposals,
    }


def extract_sft_records(
    decisions: Iterable[Mapping[str, Any]],
    *,
    world_id: str = "world:default",
    version_id: str = "version:default",
) -> list[SftTrajectoryRecord]:
    """Extract deterministic SFT records for accepted and applied world decisions."""
    records: list[SftTrajectoryRecord] = []
    for index, raw in enumerate(decisions):
        turn = _unpack_decision_turn(
            raw,
            default_world_id=world_id,
            default_version_id=version_id,
            index=index,
        )
        if turn["status"] != "accepted" or turn["disposition"] != "applied":
            continue
        chosen = turn["chosen_action"]
        if chosen is None:
            continue
        verdict = validate_proposal_verdict(
            turn["offered_options"],
            chosen["label"],
            chosen.get("line"),
            context=turn["context"],
        )
        if verdict != "validated_choice":
            continue

        tool_args: dict[str, Any] = {"action": chosen["label"]}
        if (
            any(opt.get("takes_line") for opt in turn["offered_options"])
            or chosen.get("line") is not None
        ):
            tool_args["line"] = chosen.get("line")

        messages_sha256 = _canonical_sha256(turn["messages"])
        action_payload = {
            "label": chosen["label"],
            "kind": chosen["kind"],
            "line": chosen.get("line"),
            "target_id": chosen.get("target_id"),
        }
        openenv_step = {
            "episode_id": f"{turn['world_id']}:{turn['version_id']}",
            "step_index": len(records),
            "tick": turn["tick"],
            "subject_id": turn["subject_id"],
            "observation": {
                "messages": turn["messages"],
                "messages_sha256": messages_sha256,
                "offered_options": turn["offered_options"],
            },
            "action": action_payload,
            "reward": 1,
            "done": False,
        }
        body = {
            "profile": TRAJECTORY_PROFILE,
            "record_kind": "sft",
            "world_id": turn["world_id"],
            "version_id": turn["version_id"],
            "request_id": turn["request_id"],
            "tick": turn["tick"],
            "subject_id": turn["subject_id"],
            "decider_kind": turn["decider_kind"],
            "model_id": turn["model_id"],
            "prompt_version": turn["prompt_version"],
            "messages": turn["messages"],
            "messages_sha256": messages_sha256,
            "offered_options": turn["offered_options"],
            "chosen_action": action_payload,
            "tool_call": {
                "name": "act",
                "arguments": tool_args,
            },
            "openenv_step": openenv_step,
            "latency_ms": turn["latency_ms"],
            "cost_usd": turn["cost_usd"],
        }
        record_sha256 = _canonical_sha256(body)
        records.append(SftTrajectoryRecord({**body, "record_sha256": record_sha256}))

    records.sort(key=lambda r: (r["tick"], r["subject_id"], r["request_id"]))
    for step_idx, rec in enumerate(records):
        rec["openenv_step"]["step_index"] = step_idx
        if step_idx == len(records) - 1:
            rec["openenv_step"]["done"] = True
        without_digest = {k: v for k, v in rec.items() if k != "record_sha256"}
        rec["record_sha256"] = _canonical_sha256(without_digest)
    return records


def extract_dpo_pairs(
    decisions: Iterable[Mapping[str, Any]],
    *,
    world_id: str = "world:default",
    version_id: str = "version:default",
) -> list[DpoPairRecord]:
    """Extract deterministic DPO preference & validator pairs from counterfactual branches and
    validator-refused proposals."""
    pairs: list[DpoPairRecord] = []
    for index, raw in enumerate(decisions):
        turn = _unpack_decision_turn(
            raw,
            default_world_id=world_id,
            default_version_id=version_id,
            index=index,
        )
        chosen = turn["chosen_action"]
        messages_sha256 = _canonical_sha256(turn["messages"])

        valid_anchor: dict[str, Any] | None = None
        if (
            chosen is not None
            and turn["status"] == "accepted"
            and turn["disposition"] == "applied"
            and validate_proposal_verdict(
                turn["offered_options"],
                chosen["label"],
                chosen.get("line"),
                context=turn["context"],
            )
            == "validated_choice"
        ):
            valid_anchor = {
                "label": chosen["label"],
                "kind": chosen["kind"],
                "line": chosen.get("line"),
                "target_id": chosen.get("target_id"),
                "model_id": turn["model_id"],
            }
        else:
            for branch in turn["branches"]:
                if not isinstance(branch, Mapping):
                    continue
                candidate = _normalize_action(branch, turn["offered_options"])
                if candidate is not None:
                    check = validate_proposal_verdict(
                        turn["offered_options"],
                        candidate["label"],
                        candidate.get("line"),
                        context=turn["context"],
                    )
                    if check == "validated_choice":
                        valid_anchor = {
                            "label": candidate["label"],
                            "kind": candidate["kind"],
                            "line": candidate.get("line"),
                            "target_id": candidate.get("target_id"),
                            "model_id": candidate.get("model_id") or "validator_fallback",
                        }
                        break
            if valid_anchor is None:
                fallback_opt = next(
                    (
                        o
                        for o in turn["offered_options"]
                        if o["kind"] in ("wait", "carry_on", "idle", "stood", "waited")
                        or not o["takes_line"]
                    ),
                    turn["offered_options"][-1],
                )
                valid_anchor = {
                    "label": fallback_opt["label"],
                    "kind": fallback_opt["kind"],
                    "line": None,
                    "target_id": fallback_opt["target_id"],
                    "model_id": "routine_fallback",
                }

        if turn["status"] != "accepted" or turn["disposition"] != "applied":
            rejected_action = (
                {
                    "label": chosen["label"],
                    "kind": chosen["kind"],
                    "line": chosen.get("line"),
                    "target_id": chosen.get("target_id"),
                    "model_id": turn["model_id"],
                    "same_choice": False,
                }
                if chosen is not None
                else {
                    "label": None,
                    "kind": None,
                    "line": None,
                    "target_id": None,
                    "model_id": turn["model_id"],
                    "same_choice": False,
                }
            )
            computed_reason = (
                validate_proposal_verdict(
                    turn["offered_options"],
                    chosen["label"] if chosen else None,
                    chosen.get("line") if chosen else None,
                    context=turn["context"],
                )
                if chosen is not None and turn["reason"] in ("validated_choice", "")
                else turn["reason"]
            )
            body = {
                "profile": TRAJECTORY_PROFILE,
                "record_kind": "dpo",
                "pair_kind": "validator_rejection",
                "world_id": turn["world_id"],
                "version_id": turn["version_id"],
                "request_id": turn["request_id"],
                "tick": turn["tick"],
                "subject_id": turn["subject_id"],
                "context_messages": turn["messages"],
                "messages_sha256": messages_sha256,
                "offered_options": turn["offered_options"],
                "chosen_valid_action": valid_anchor,
                "rejected_or_alternative_action": rejected_action,
                "verdict_reason": computed_reason,
            }
            pairs.append(DpoPairRecord({**body, "record_sha256": _canonical_sha256(body)}))

        for attempt_idx, attempt in enumerate(turn["rejected_proposals"]):
            if not isinstance(attempt, Mapping):
                continue
            assert_no_floats(attempt, f"$.decisions[{index}].rejected_proposals[{attempt_idx}]")
            raw_label = attempt.get("label") or attempt.get("chosen_label") or attempt.get("action")
            raw_line = attempt.get("line")
            verdict_reason = str(
                attempt.get("reason")
                or attempt.get("verdict_reason")
                or attempt.get("outcome")
                or validate_proposal_verdict(
                    turn["offered_options"],
                    str(raw_label) if raw_label is not None else None,
                    str(raw_line) if raw_line is not None else None,
                    context=turn["context"],
                )
            )
            rejected_action = {
                "label": str(raw_label) if raw_label is not None else None,
                "kind": str(attempt.get("kind") or "rejected_attempt"),
                "line": str(raw_line) if raw_line is not None else None,
                "target_id": (
                    str(attempt["target_id"]) if attempt.get("target_id") is not None else None
                ),
                "model_id": str(attempt.get("model_id") or turn["model_id"]),
                "same_choice": False,
            }
            body = {
                "profile": TRAJECTORY_PROFILE,
                "record_kind": "dpo",
                "pair_kind": "validator_rejection",
                "world_id": turn["world_id"],
                "version_id": turn["version_id"],
                "request_id": turn["request_id"],
                "tick": turn["tick"],
                "subject_id": turn["subject_id"],
                "context_messages": turn["messages"],
                "messages_sha256": messages_sha256,
                "offered_options": turn["offered_options"],
                "chosen_valid_action": valid_anchor,
                "rejected_or_alternative_action": rejected_action,
                "verdict_reason": verdict_reason,
            }
            pairs.append(DpoPairRecord({**body, "record_sha256": _canonical_sha256(body)}))

        for branch_idx, branch in enumerate(turn["branches"]):
            if not isinstance(branch, Mapping):
                continue
            assert_no_floats(branch, f"$.decisions[{index}].branches[{branch_idx}]")
            alt = _normalize_action(branch, turn["offered_options"])
            if alt is None:
                continue
            same_choice = (
                bool(branch["same_choice"])
                if isinstance(branch.get("same_choice"), bool)
                else (
                    alt["label"] == valid_anchor["label"]
                    and alt.get("line") == valid_anchor.get("line")
                )
            )
            if same_choice:
                continue
            branch_check = validate_proposal_verdict(
                turn["offered_options"],
                alt["label"],
                alt.get("line"),
                context=turn["context"],
            )
            verdict_reason = str(
                branch.get("verdict_reason")
                or branch.get("reason")
                or (
                    branch_check
                    if branch_check != "validated_choice"
                    else "counterfactual_diverged"
                )
            )
            alt_action = {
                "label": alt["label"],
                "kind": alt["kind"],
                "line": alt.get("line"),
                "target_id": alt.get("target_id"),
                "model_id": alt.get("model_id") or "alternative_model",
                "same_choice": False,
            }
            body = {
                "profile": TRAJECTORY_PROFILE,
                "record_kind": "dpo",
                "pair_kind": (
                    "validator_rejection"
                    if branch_check != "validated_choice"
                    else "counterfactual_branch"
                ),
                "world_id": turn["world_id"],
                "version_id": turn["version_id"],
                "request_id": turn["request_id"],
                "tick": turn["tick"],
                "subject_id": turn["subject_id"],
                "context_messages": turn["messages"],
                "messages_sha256": messages_sha256,
                "offered_options": turn["offered_options"],
                "chosen_valid_action": valid_anchor,
                "rejected_or_alternative_action": alt_action,
                "verdict_reason": verdict_reason,
            }
            pairs.append(DpoPairRecord({**body, "record_sha256": _canonical_sha256(body)}))

    pairs.sort(
        key=lambda p: (
            p["tick"],
            p["subject_id"],
            p["request_id"],
            p["pair_kind"],
            str(p["rejected_or_alternative_action"].get("model_id") or ""),
            str(p["rejected_or_alternative_action"].get("label") or ""),
        )
    )
    return pairs


def compute_trajectory_metrics(
    decisions: Iterable[Mapping[str, Any]],
    *,
    world_id: str = "world:default",
    version_id: str = "version:default",
) -> TrajectoryMetrics:
    """Compute pure integer summary statistics for evaluating a student model against a teacher."""
    decision_list = list(decisions)
    turns = [
        _unpack_decision_turn(
            raw,
            default_world_id=world_id,
            default_version_id=version_id,
            index=index,
        )
        for index, raw in enumerate(decision_list)
    ]
    sft_records = extract_sft_records(decision_list, world_id=world_id, version_id=version_id)
    dpo_pairs = extract_dpo_pairs(decision_list, world_id=world_id, version_id=version_id)

    total_decisions = len(turns)
    applied_count = len(sft_records)
    refused_count = total_decisions - applied_count

    agreed_branches = 0
    total_branches = 0
    for turn in turns:
        chosen = turn["chosen_action"]
        for branch in turn["branches"]:
            if not isinstance(branch, Mapping):
                continue
            total_branches += 1
            if isinstance(branch.get("same_choice"), bool):
                if branch["same_choice"]:
                    agreed_branches += 1
            elif chosen is not None:
                alt = _normalize_action(branch, turn["offered_options"])
                if alt is not None and alt["label"] == chosen["label"]:
                    agreed_branches += 1

    agreement_rate_permille = (
        round_half_down(agreed_branches * 1000, total_branches) if total_branches > 0 else 0
    )

    latencies = [
        turn["latency_ms"] for turn in turns if turn["has_latency"] or turn["latency_ms"] > 0
    ]
    mean_latency_ms = round_half_down(sum(latencies), len(latencies)) if latencies else 0

    metrics = TrajectoryMetrics(
        {
            "total_decisions": total_decisions,
            "applied_count": applied_count,
            "refused_count": refused_count,
            "counterfactual_pairs": len(dpo_pairs),
            "evaluated_branches": total_branches,
            "agreed_branches": agreed_branches,
            "agreement_rate_permille": agreement_rate_permille,
            "mean_latency_ms": mean_latency_ms,
        }
    )
    assert_no_floats(metrics)
    return metrics


def export_trajectories(
    decisions: Iterable[Mapping[str, Any]],
    *,
    world_id: str = "world:default",
    version_id: str = "version:default",
) -> TrajectoryBundle:
    """Build a complete, content-addressed ``exulanica.world-trajectory/v1`` bundle."""
    decision_list = list(decisions)
    sft_records = extract_sft_records(decision_list, world_id=world_id, version_id=version_id)
    dpo_pairs = extract_dpo_pairs(decision_list, world_id=world_id, version_id=version_id)
    metrics = compute_trajectory_metrics(decision_list, world_id=world_id, version_id=version_id)
    body = {
        "profile": TRAJECTORY_PROFILE,
        "world_id": _require_non_empty_str(world_id, "world_id"),
        "version_id": _require_non_empty_str(version_id, "version_id"),
        "sft_records": sft_records,
        "dpo_pairs": dpo_pairs,
        "metrics": metrics,
    }
    bundle_sha256 = _canonical_sha256(body)
    return TrajectoryBundle({**body, "bundle_sha256": bundle_sha256})


def to_openai_tool_example(record: Mapping[str, Any]) -> dict[str, Any]:
    """Format an SFT trajectory record as an OpenAI / NVIDIA NeMo Gym tool-calling example."""
    assert_no_floats(record)
    offered = record["offered_options"]
    takes_line = any(opt.get("takes_line") for opt in offered)
    properties: dict[str, Any] = {
        "action": {
            "type": "string",
            "enum": [opt["label"] for opt in offered],
        }
    }
    required = ["action"]
    if takes_line:
        properties["line"] = {"anyOf": [{"type": "string", "maxLength": 200}, {"type": "null"}]}
        required.append("line")

    tool_args = dict(record["tool_call"]["arguments"])
    tool_call_id = f"call_{record['request_id'].replace(':', '_')}"
    example = {
        "profile": TRAJECTORY_PROFILE,
        "format": "openai_tool_call",
        "world_id": record["world_id"],
        "version_id": record["version_id"],
        "tick": record["tick"],
        "subject_id": record["subject_id"],
        "model_id": record["model_id"],
        "messages": [
            *record["messages"],
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": "act",
                            "arguments": canonical_json(tool_args).decode("utf-8"),
                        },
                    }
                ],
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "act",
                    "description": "Choose the character's next valid action in the world.",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "metadata": {
            "request_id": record["request_id"],
            "latency_ms": record["latency_ms"],
            "cost_usd": record["cost_usd"],
            "record_sha256": record["record_sha256"],
        },
    }
    assert_no_floats(example)
    return example


def to_openenv_episode(
    sft_records: Sequence[Mapping[str, Any]],
    *,
    world_id: str = "world:default",
    version_id: str = "version:default",
) -> dict[str, Any]:
    """Package ordered SFT trajectory records into an OpenEnv episode document."""
    steps = []
    for idx, rec in enumerate(sft_records):
        assert_no_floats(rec)
        step = dict(rec["openenv_step"])
        step["step_index"] = idx
        step["done"] = idx == len(sft_records) - 1
        steps.append(step)
    episode = {
        "profile": TRAJECTORY_PROFILE,
        "format": "openenv_episode",
        "episode_id": f"{world_id}:{version_id}",
        "world_id": world_id,
        "version_id": version_id,
        "total_steps": len(steps),
        "total_reward": len(steps),
        "steps": steps,
    }
    episode["episode_sha256"] = _canonical_sha256(episode)
    return episode


def to_dpo_preference_example(pair: Mapping[str, Any]) -> dict[str, Any]:
    """Format a DPO / validator pair for TRL / NeMo Aligner preference optimization."""
    assert_no_floats(pair)
    chosen_call = {
        "name": "act",
        "arguments": {
            "action": pair["chosen_valid_action"]["label"],
            **(
                {"line": pair["chosen_valid_action"]["line"]}
                if pair["chosen_valid_action"].get("line") is not None
                else {}
            ),
        },
    }
    rejected_call = {
        "name": "act",
        "arguments": {
            "action": pair["rejected_or_alternative_action"]["label"],
            **(
                {"line": pair["rejected_or_alternative_action"]["line"]}
                if pair["rejected_or_alternative_action"].get("line") is not None
                else {}
            ),
        },
    }
    example = {
        "profile": TRAJECTORY_PROFILE,
        "format": "dpo_preference",
        "pair_kind": pair["pair_kind"],
        "world_id": pair["world_id"],
        "version_id": pair["version_id"],
        "request_id": pair["request_id"],
        "tick": pair["tick"],
        "subject_id": pair["subject_id"],
        "prompt": pair["context_messages"],
        "offered_options": pair["offered_options"],
        "chosen": chosen_call,
        "rejected": rejected_call,
        "verdict_reason": pair["verdict_reason"],
        "record_sha256": pair["record_sha256"],
    }
    assert_no_floats(example)
    return example


def format_openai_tool_jsonl(sft_records: Sequence[Mapping[str, Any]]) -> str:
    """Serialize SFT records as canonical zero-float OpenAI/NeMo tool-calling JSONL."""
    return "\n".join(
        canonical_json(to_openai_tool_example(rec)).decode("utf-8") for rec in sft_records
    )


def format_openenv_jsonl(
    sft_records: Sequence[Mapping[str, Any]],
    *,
    world_id: str = "world:default",
    version_id: str = "version:default",
) -> str:
    """Serialize SFT records as canonical OpenEnv step JSONL."""
    episode = to_openenv_episode(sft_records, world_id=world_id, version_id=version_id)
    return "\n".join(canonical_json(step).decode("utf-8") for step in episode["steps"])


def format_dpo_jsonl(dpo_pairs: Sequence[Mapping[str, Any]]) -> str:
    """Serialize DPO / validator preference pairs as canonical zero-float JSONL."""
    return "\n".join(
        canonical_json(to_dpo_preference_example(pair)).decode("utf-8") for pair in dpo_pairs
    )


def format_trajectory_jsonl(
    bundle_or_records: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> str:
    """Serialize a trajectory bundle or list of trajectory records as canonical JSONL."""
    if isinstance(bundle_or_records, Mapping):
        rows: list[Mapping[str, Any]] = [
            *(bundle_or_records.get("sft_records") or ()),
            *(bundle_or_records.get("dpo_pairs") or ()),
        ]
    else:
        rows = list(bundle_or_records)
    return "\n".join(canonical_json(row).decode("utf-8") for row in rows)
