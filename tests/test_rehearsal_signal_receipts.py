"""The signal receipt summary charges accepted provider calls and identifies sealed choices."""

from __future__ import annotations

import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "rehearsal"))

from signal_receipts import summarize


def test_receipts_count_exact_provider_cost_and_bind_activation_to_choice():
    workspace = uuid.uuid4()
    choices = [
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "choice_seq": 3,
            "signal_id": "signal-1",
            "effective_second": 120,
            "document_sha256": "a" * 64,
        }
    ]
    requests = [
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "request_id": "request-1",
            "document_sha256": "b" * 64,
        },
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "request_id": "request-2",
            "document_sha256": "b" * 64,
        },
    ]
    decisions = [
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "request_id": "request-1",
            "status": "accepted",
            "cost_usd": "0.00004567",
            "cost_known": "true",
        },
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "request_id": "request-2",
            "status": "unavailable",
            "cost_usd": None,
            "cost_known": None,
        },
    ]
    segments = [
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "episode": 0,
            "segment": 2,
            "choice_seq": 3,
            "active_second": 124,
            "decisions_sha256": "c" * 64,
            "frames_sha256": "d" * 64,
            "continuation_sha256": "e" * 64,
        },
        {
            "world_id": "world:elsewhere",
            "version_id": "version-b",
            "episode": 0,
            "segment": 2,
            "choice_seq": 3,
            "active_second": 125,
            "decisions_sha256": "f" * 64,
            "frames_sha256": "0" * 64,
            "continuation_sha256": "1" * 64,
        },
    ]
    result = summarize(workspace, choices, requests, decisions, segments)
    assert Decimal(result["accounted_usd"]) == Decimal("0.00004567")
    assert Decimal(result["known_cost_usd"]) == Decimal("0.00004567")
    assert result["unknown_cost_calls"] == 0
    assert result["counts"] == {"choices": 1, "requests": 2, "decisions": 2, "segments": 2}
    assert result["accepted_decisions"] == 1
    assert result["pending_requests"] == 0
    assert result["active_choices"] == [
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "subject_id": "signal-1",
            "choice_seq": 3,
            "active_second": 124,
        }
    ]


def test_unsettled_request_is_reported_before_spend_is_called_complete():
    pending = [{"world_id": "world:town", "version_id": "version-a", "request_id": "request-3"}]
    result = summarize(uuid.uuid4(), [], pending, [], [])
    assert result["pending_requests"] == 1
    assert Decimal(result["accounted_usd"]) == 0


def test_timeout_receipt_uses_reserved_bound_without_calling_it_known_cost():
    decisions = [
        {
            "world_id": "world:town",
            "version_id": "version-a",
            "request_id": "timed-out",
            "document_sha256": "f" * 64,
            "status": "unavailable",
            "cost_usd": "0.00120000",
            "cost_known": "false",
        }
    ]
    result = summarize(uuid.uuid4(), [], [], decisions, [])
    assert Decimal(result["accounted_usd"]) == Decimal("0.00120000")
    assert Decimal(result["known_cost_usd"]) == 0
    assert result["unknown_cost_calls"] == 1
