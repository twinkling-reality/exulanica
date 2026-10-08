"""The continuation of a kind-drafting measurement cut off from outside: it asks only the drafts its
log never observed, in the pre-registered order, keeps the stop rule's count across the cut and
writes each result before asking the next."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_kind_drafting_models.py"
SUPER, QWEN = "nvidia/nemotron-3-super-120b-a12b", "Qwen/Qwen3-235B-A22B-Instruct-2507"


@pytest.fixture(scope="module")
def measure() -> Any:
    spec = importlib.util.spec_from_file_location("measure_kind_drafting_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _v32(measure: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The continuation continues the v3.2 run, asked of these two candidates."""
    monkeypatch.setattr(measure, "CANDIDATES", (SUPER, QWEN))
    monkeypatch.setattr(measure, "REFUSED_IN_A_ROW", 2)


def _line(number: int, model_id: str, *, valid: bool) -> str:
    outcomes = "['passed']" if valid else "[]"
    unanswered = "None" if valid else "timed_out"
    return (
        f"d{number} {model_id}: valid={valid} first={valid} matched={valid} "
        f"outcomes={outcomes} unanswered={unanswered} 1234 ms"
    )


def _log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, measure: Any, lines: list[str]) -> Path:
    data = ("\n".join(lines) + "\n").encode("utf-8")
    (tmp_path / "run.log.txt").write_bytes(data)
    monkeypatch.setattr(measure, "CUT_OFF_LOG_SHA256", hashlib.sha256(data).hexdigest())
    return tmp_path


def _scripted_asks(
    monkeypatch: pytest.MonkeyPatch, measure: Any, sink: Path, answers: dict[tuple[int, str], bool]
) -> list[tuple[int, str, int]]:
    """Replace the drafter's call with a scripted verdict per draft, recording each draft asked and
    how many results the sink held when it was asked."""
    asked: list[tuple[int, str, int]] = []
    numbers = {entry["description"]: n for n, entry in enumerate(measure.DESCRIPTIONS, 1)}

    def ask(model_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        number = numbers[entry["description"]]
        held = len(sink.read_text("utf-8").splitlines()) if sink.exists() else 0
        asked.append((number, model_id, held))
        valid = answers[(number, model_id)]
        return {
            "valid": valid,
            "valid_first_try": valid,
            "matched": valid,
            "outcomes": ["passed"] if valid else ["check:x", "check:x", "check:x"],
            "unanswered": None,
            "attempts": [],
        }

    monkeypatch.setattr(measure, "_ask", ask)
    return asked


def test_the_log_is_read_as_the_first_drafts_of_the_order(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _log(
        tmp_path,
        monkeypatch,
        measure,
        [_line(1, SUPER, valid=True), _line(1, QWEN, valid=False), _line(2, SUPER, valid=True)],
    )
    observed = measure._observed(out)
    assert [(a["description"], a["model_id"], a["valid"]) for a in observed] == [
        (1, SUPER, True),
        (1, QWEN, False),
        (2, SUPER, True),
    ]
    assert observed[1]["unanswered"] == "timed_out" and observed[1]["draft_ms"] == 1234
    assert measure._unobserved(observed)[0] == (2, QWEN)


def test_a_log_out_of_the_registered_order_is_refused(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _log(tmp_path, monkeypatch, measure, [_line(1, QWEN, valid=True)])
    with pytest.raises(SystemExit, match="pre-registered order"):
        measure._observed(out)


def test_a_log_other_than_the_one_named_is_refused(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _log(tmp_path, monkeypatch, measure, [_line(1, SUPER, valid=True)])
    monkeypatch.setattr(measure, "CUT_OFF_LOG_SHA256", "0" * 64)
    with pytest.raises(SystemExit, match="not the cut-off run's log"):
        measure._observed(out)


def test_only_unobserved_drafts_are_asked_each_written_before_the_next(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [_line(number, model_id, valid=True) for number, model_id in measure._order()[:9]]
    out = _log(tmp_path, monkeypatch, measure, lines)
    sink = out / "asks.jsonl"
    answers = {draft: True for draft in measure._order()}
    asked = _scripted_asks(monkeypatch, measure, sink, answers)
    asks, ended_as = measure._continuation_asks(
        lambda model_id: model_id, measure._observed(out), sink
    )
    assert ended_as == "complete"
    assert asked == [(5, QWEN, 0), (6, SUPER, 1), (6, QWEN, 2)]
    written = [json.loads(line) for line in sink.read_text("utf-8").splitlines()]
    assert [(w["description"], w["model_id"]) for w in written] == [
        (5, QWEN),
        (6, SUPER),
        (6, QWEN),
    ]
    assert len(asks) == 3


def test_the_stop_count_carries_across_the_cut(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _log(tmp_path, monkeypatch, measure, [_line(1, SUPER, valid=False)])
    sink = out / "asks.jsonl"
    answers = {draft: True for draft in measure._order()}
    answers[(1, QWEN)] = False
    asked = _scripted_asks(monkeypatch, measure, sink, answers)
    _, ended_as = measure._continuation_asks(
        lambda model_id: model_id, measure._observed(out), sink
    )
    assert asked == [(1, QWEN, 0)]
    assert ended_as == "stopped: 2 drafts in a row without a valid kind for description 1"


def test_combined_counts_take_the_observed_lines_as_given(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [_line(number, model_id, valid=True) for number, model_id in measure._order()[:11]]
    out = _log(tmp_path, monkeypatch, measure, lines)
    sink = out / "asks.jsonl"
    _scripted_asks(monkeypatch, measure, sink, {draft: False for draft in measure._order()})
    asks, _ = measure._continuation_asks(lambda model_id: model_id, measure._observed(out), sink)
    summaries = {
        s["model_id"]: s for s in measure._combined_summaries(measure._observed(out), asks)
    }
    assert (summaries[SUPER]["valid"], summaries[SUPER]["observed_from_the_log"]) == (6, 6)
    assert (summaries[QWEN]["valid"], summaries[QWEN]["descriptions"]) == (5, 6)
    assert summaries[QWEN]["cost_known"] is False


def test_the_measured_run_writes_each_draft_before_asking_the_next(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = tmp_path / "run-asks.jsonl"
    asked = _scripted_asks(monkeypatch, measure, sink, {draft: True for draft in measure._order()})
    _, ended_as = measure._asks(lambda model_id: model_id, measure.CANDIDATES, sink)
    assert ended_as == "complete"
    assert [held for _, _, held in asked] == list(range(len(measure._order())))
    written = [json.loads(line) for line in sink.read_text("utf-8").splitlines()]
    assert [(w["description"], w["model_id"]) for w in written] == measure._order()


def test_the_measured_run_stops_after_two_descriptions_in_a_row_with_no_valid_kind(
    measure: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(measure, "CANDIDATES", (QWEN,))
    sink = tmp_path / "run-asks.jsonl"
    answers = {(number, QWEN): number == 2 for number in range(1, 7)}
    asked = _scripted_asks(monkeypatch, measure, sink, answers)
    _, ended_as = measure._asks(lambda model_id: model_id, (QWEN,), sink)
    # One failure (description 1) does not stop it; 3 then 4 failing in a row does.
    assert [number for number, _, _ in asked] == [1, 2, 3, 4]
    assert ended_as == "stopped: 2 descriptions in a row with no valid kind, at description 4"
