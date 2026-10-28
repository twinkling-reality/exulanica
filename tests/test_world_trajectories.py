"""Tests for ``exulanica.world.trajectories`` (``exulanica.world-trajectory/v1``).

Verifies:
1. SFT trajectory extraction from accepted and applied world decisions (OpenAI/NeMo tool-calling
   JSONL and OpenEnv episode formats).
2. DPO counterfactual & deterministic validator pair construction from ``asked_again`` /
   ``branches`` and validator-refused proposals (``answer_not_offered``, ``line_names_listener``,
   ``line_said_before``, ``line_breaks_rule``).
3. Counterfactual agreement and distillation summary metrics (``total_decisions``,
   ``applied_count``, ``refused_count``, ``counterfactual_pairs``, ``agreement_rate_permille``,
   ``mean_latency_ms``).
4. Determinism across input orderings and strict zero-float invariants via ``canonical_json``.
"""

from __future__ import annotations

import json

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.world.trajectories import (
    TRAJECTORY_PROFILE,
    TrajectoryError,
    assert_no_floats,
    compute_trajectory_metrics,
    export_trajectories,
    extract_dpo_pairs,
    extract_sft_records,
    format_dpo_jsonl,
    format_openai_tool_jsonl,
    format_openenv_jsonl,
    format_trajectory_jsonl,
    to_openenv_episode,
    validate_proposal_verdict,
)


def _sample_decisions() -> list[dict]:
    return [
        {
            "world_id": "world:terraces-bay",
            "version_id": "3c4d5e6f-0000-4000-8000-000000000002",
            "request_id": "req-412-teo",
            "tick": 412,
            "subject_id": "teo",
            "model_id": "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "prompt_version": "society-person-choice/v12",
            "messages": [
                {
                    "role": "system",
                    "content": "You are deciding what one inhabitant of this world does next.",
                },
                {
                    "role": "user",
                    "content": (
                        "Location: by the bench\nWhat you can do now:\n"
                        "- say something to Ines, 3 m away\n"
                        "- walk to the market, 18 m away\n"
                        "- wait here a minute"
                    ),
                },
            ],
            "offered_options": [
                {
                    "option_id": "option:1",
                    "label": "say something to Ines, 3 m away",
                    "kind": "say_to",
                    "takes_line": True,
                    "target_id": "ines",
                },
                {
                    "option_id": "option:2",
                    "label": "walk to the market, 18 m away",
                    "kind": "go",
                    "takes_line": False,
                    "target_id": "market:1",
                },
                {
                    "option_id": "option:3",
                    "label": "wait here a minute",
                    "kind": "wait",
                    "takes_line": False,
                    "target_id": None,
                },
            ],
            "chosen_action": {
                "label": "say something to Ines, 3 m away",
                "kind": "say_to",
                "line": "Morning! The boats are out early.",
                "target_id": "ines",
            },
            "status": "accepted",
            "disposition": "applied",
            "reason": "validated_choice",
            "latency_ms": 640,
            "cost_usd": "0.0003",
            "branches": [
                {
                    "ask_id": "ask-1",
                    "model_id": "nvidia/Nemotron-3-Nano-30B",
                    "same_choice": False,
                    "label": "walk to the market, 18 m away",
                    "kind": "go",
                    "target_id": "market:1",
                    "line": None,
                },
                {
                    "ask_id": "ask-2",
                    "model_id": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
                    "same_choice": True,
                    "label": "say something to Ines, 3 m away",
                    "kind": "say_to",
                    "target_id": "ines",
                    "line": "Morning! The boats are out early.",
                },
            ],
            "rejected_proposals": [
                {
                    "label": "fly to the roof",
                    "line": None,
                    "model_id": "nvidia/Nemotron-3-Nano-30B",
                }
            ],
        },
        {
            "world_id": "world:terraces-bay",
            "version_id": "3c4d5e6f-0000-4000-8000-000000000002",
            "request_id": "req-415-ines",
            "tick": 415,
            "subject_id": "ines",
            "model_id": "nvidia/Nemotron-3-Super-120B",
            "prompt_version": "society-person-choice/v12",
            "offered_options": [
                {
                    "option_id": "option:1",
                    "label": "walk to the market, 12 m away",
                    "kind": "go",
                    "takes_line": False,
                    "target_id": "market:1",
                },
                {
                    "option_id": "option:2",
                    "label": "wait here a minute",
                    "kind": "wait",
                    "takes_line": False,
                    "target_id": None,
                },
            ],
            "chosen_action": {
                "label": "walk to the market, 12 m away",
                "kind": "go",
                "line": None,
                "target_id": "market:1",
            },
            "status": "accepted",
            "disposition": "applied",
            "reason": "validated_choice",
            "latency_ms": 480,
            "cost_usd": "0.0002",
            "branches": [
                {
                    "ask_id": "ask-3",
                    "model_id": "nvidia/Nemotron-3-Nano-30B",
                    "same_choice": True,
                    "label": "walk to the market, 12 m away",
                    "kind": "go",
                    "target_id": "market:1",
                }
            ],
        },
        {
            "world_id": "world:terraces-bay",
            "version_id": "3c4d5e6f-0000-4000-8000-000000000002",
            "request_id": "req-420-marco",
            "tick": 420,
            "subject_id": "marco",
            "model_id": "nvidia/Nemotron-3-Nano-30B",
            "offered_options": [
                {
                    "option_id": "option:1",
                    "label": "say something to Teo, 4 m away",
                    "kind": "say_to",
                    "takes_line": True,
                    "target_id": "teo",
                },
                {
                    "option_id": "option:2",
                    "label": "wait here a minute",
                    "kind": "wait",
                    "takes_line": False,
                    "target_id": None,
                },
            ],
            "chosen_action": {
                "label": "say something to Teo, 4 m away",
                "kind": "say_to",
                "line": "Good morning, Teo",
                "target_id": "teo",
            },
            "status": "rejected",
            "disposition": "rejected",
            "reason": "line_names_listener",
            "latency_ms": 380,
            "cost_usd": "0.0001",
            "branches": [],
        },
    ]


def test_sft_extraction_and_tool_openenv_formats() -> None:
    decisions = _sample_decisions()
    sft = extract_sft_records(
        decisions,
        world_id="world:terraces-bay",
        version_id="3c4d5e6f-0000-4000-8000-000000000002",
    )
    # Only the 2 accepted + applied turns become SFT records; tick 420 is excluded.
    assert len(sft) == 2
    first, second = sft[0], sft[1]
    assert second.tick == 415

    assert first.profile == TRAJECTORY_PROFILE
    assert first.world_id == "world:terraces-bay"
    assert first.version_id == "3c4d5e6f-0000-4000-8000-000000000002"
    assert first.tick == 412
    assert first.subject_id == "teo"
    assert first.model_id == "Qwen/Qwen3-235B-A22B-Instruct-2507"
    assert first.chosen_action["label"] == "say something to Ines, 3 m away"
    assert first.chosen_action["line"] == "Morning! The boats are out early."
    assert first.latency_ms == 640
    assert first.cost_usd == "0.0003"
    assert len(first.record_sha256) == 64

    # OpenAI / NeMo Gym tool-calling JSONL format
    tool_jsonl = format_openai_tool_jsonl(sft)
    lines = tool_jsonl.splitlines()
    assert len(lines) == 2
    parsed_tool = json.loads(lines[0])
    assert parsed_tool["format"] == "openai_tool_call"
    assert parsed_tool["messages"][-1]["role"] == "assistant"
    call = parsed_tool["messages"][-1]["tool_calls"][0]["function"]
    assert call["name"] == "act"
    assert json.loads(call["arguments"]) == {
        "action": "say something to Ines, 3 m away",
        "line": "Morning! The boats are out early.",
    }

    # OpenEnv episode format
    episode = to_openenv_episode(
        sft,
        world_id="world:terraces-bay",
        version_id="3c4d5e6f-0000-4000-8000-000000000002",
    )
    assert episode["format"] == "openenv_episode"
    assert episode["total_steps"] == 2
    assert episode["total_reward"] == 2
    assert episode["steps"][0]["done"] is False
    assert episode["steps"][1]["done"] is True
    openenv_lines = format_openenv_jsonl(
        sft,
        world_id="world:terraces-bay",
        version_id="3c4d5e6f-0000-4000-8000-000000000002",
    ).splitlines()
    assert len(openenv_lines) == 2


def test_dpo_counterfactual_and_validator_pairs() -> None:
    decisions = _sample_decisions()
    pairs = extract_dpo_pairs(
        decisions,
        world_id="world:terraces-bay",
        version_id="3c4d5e6f-0000-4000-8000-000000000002",
    )
    # Expected DPO pairs:
    # 1. Tick 412 counterfactual branch (Nemotron 3 Nano 30B chose "walk to the market, 18 m away")
    # 2. Tick 412 validator rejection ("fly to the roof" -> answer_not_offered)
    # 3. Tick 420 validator rejection ("Good morning, Teo" -> line_names_listener)
    assert len(pairs) == 3

    by_reason = {pair["verdict_reason"]: pair for pair in pairs}
    assert set(by_reason) == {
        "counterfactual_diverged",
        "answer_not_offered",
        "line_names_listener",
    }

    diverged = by_reason["counterfactual_diverged"]
    assert diverged.pair_kind == "counterfactual_branch"
    assert diverged.chosen_valid_action["label"] == "say something to Ines, 3 m away"
    assert diverged.rejected_or_alternative_action["label"] == "walk to the market, 18 m away"
    assert diverged.rejected_or_alternative_action["model_id"] == "nvidia/Nemotron-3-Nano-30B"

    not_offered = by_reason["answer_not_offered"]
    assert not_offered.pair_kind == "validator_rejection"
    assert not_offered.rejected_or_alternative_action["label"] == "fly to the roof"

    named_listener = by_reason["line_names_listener"]
    assert named_listener.tick == 420
    assert named_listener.chosen_valid_action["label"] == "wait here a minute"
    assert named_listener.rejected_or_alternative_action["line"] == "Good morning, Teo"

    dpo_jsonl = format_dpo_jsonl(pairs)
    assert len(dpo_jsonl.splitlines()) == 3
    for row in dpo_jsonl.splitlines():
        item = json.loads(row)
        assert item["profile"] == TRAJECTORY_PROFILE
        assert item["format"] == "dpo_preference"
        assert "chosen" in item and "rejected" in item


def test_validator_verdict_rules() -> None:
    options = [
        {"label": "say something to Ines, 3 m away", "kind": "say_to", "takes_line": True},
        {"label": "wait here a minute", "kind": "wait", "takes_line": False},
    ]
    assert (
        validate_proposal_verdict(
            options,
            "say something to Ines, 3 m away",
            "The tide is coming in fast.",
        )
        == "validated_choice"
    )
    assert (
        validate_proposal_verdict(options, "jump over the moon", None)
        == "answer_not_offered"
    )
    assert (
        validate_proposal_verdict(options, "wait here a minute", "Talking while waiting")
        == "line_where_none"
    )
    assert (
        validate_proposal_verdict(options, "say something to Ines, 3 m away", None)
        == "no_line_where_one"
    )
    assert (
        validate_proposal_verdict(
            options,
            "say something to Ines, 3 m away",
            "Hello there, Ines",
        )
        == "line_names_listener"
    )
    assert (
        validate_proposal_verdict(
            options,
            "say something to Ines, 3 m away",
            "The tide is coming in fast.",
            recent_lines=["The tide is coming in fast."],
        )
        == "line_said_before"
    )


def test_metrics_determinism_and_zero_float_invariants() -> None:
    decisions = _sample_decisions()
    metrics = compute_trajectory_metrics(
        decisions,
        world_id="world:terraces-bay",
        version_id="3c4d5e6f-0000-4000-8000-000000000002",
    )
    assert metrics["total_decisions"] == 3
    assert metrics["applied_count"] == 2
    assert metrics["refused_count"] == 1
    assert metrics["counterfactual_pairs"] == 3
    # 2 out of 3 counterfactual branches agreed (666 permille via round_half_down(2000, 3))
    assert metrics["evaluated_branches"] == 3
    assert metrics["agreed_branches"] == 2
    assert metrics["agreement_rate_permille"] == 667
    # Mean latency of (640 + 480 + 380) / 3 = 1500 / 3 = 500 ms (exact integer)
    assert metrics["mean_latency_ms"] == 500

    # Bundle determinism regardless of input decision order
    bundle_forward = export_trajectories(
        decisions,
        world_id="world:terraces-bay",
        version_id="3c4d5e6f-0000-4000-8000-000000000002",
    )
    bundle_reversed = export_trajectories(
        list(reversed(decisions)),
        world_id="world:terraces-bay",
        version_id="3c4d5e6f-0000-4000-8000-000000000002",
    )
    assert bundle_forward["bundle_sha256"] == bundle_reversed["bundle_sha256"]
    assert canonical_json(bundle_forward) == canonical_json(bundle_reversed)
    assert format_trajectory_jsonl(bundle_forward) == format_trajectory_jsonl(bundle_reversed)

    # Zero-float invariant: any float anywhere in input or cost/latency is rejected
    with pytest.raises((TrajectoryError, CanonicalisationError, ValueError)):
        assert_no_floats({"latency_ms": 640.5})

    with pytest.raises((TrajectoryError, CanonicalisationError, ValueError)):
        bad = [{**decisions[0], "cost_usd": 0.0003}]
        export_trajectories(bad)

    with pytest.raises((TrajectoryError, CanonicalisationError, ValueError)):
        bad_nested = [
            {
                **decisions[0],
                "offered_options": [{"label": "wait", "kind": "wait", "distance": 3.5}],
            }
        ]
        export_trajectories(bad_nested)


def test_project_checkpoint_and_github_trajectory_export(tmp_path) -> None:
    from exulanica.world_package.projects.repository import (
        TRAJECTORIES_FILE,
        Author,
        Project,
        create,
        project_trajectory_files,
    )

    from test_world_project import sample

    project, dependencies = sample()
    files = project_trajectory_files(project)
    assert sorted(files) == sorted(
        [
            TRAJECTORIES_FILE,
            "training/dpo.jsonl",
            "training/sft.jsonl",
            "training/trajectories.json",
        ]
    )
    bundle = json.loads(files["training/trajectories.json"].decode("utf-8"))
    assert bundle["profile"] == TRAJECTORY_PROFILE
    assert bundle["metrics"]["total_decisions"] == 1
    assert bundle["metrics"]["applied_count"] == 1
    assert len(bundle["sft_records"]) == 1

    folder = tmp_path / "project-with-trajectories"
    create(
        folder,
        project,
        author=Author("Synthetic Student", "student@example.invalid"),
        dependencies=dependencies,
    )
    local = Project(folder)
    published_with_trajectories = local.published_files("HEAD", include_trajectories=True)
    assert TRAJECTORIES_FILE in published_with_trajectories
    assert "training/trajectories.json" in published_with_trajectories
    written = local.write_trajectories("HEAD")
    assert TRAJECTORIES_FILE in written
    assert (folder / TRAJECTORIES_FILE).is_file()
    assert (folder / "training" / "sft.jsonl").is_file()

