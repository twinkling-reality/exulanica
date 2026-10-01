"""A process stopped by SIGKILL at any point of a paid call, then retried under the same key.

Each case starts a process that makes one call inside ``spending_request_key``, kills it with
SIGKILL at one point, then starts a fresh process that makes the same request under the same key.
What the second process may do depends only on what the first can have done:

*   stopped after its witness was written and before its admission committed: nothing happened,
    and the retry sends;
*   stopped after admission and before dispatch: nothing left, and once the dispatch window has
    passed the retry is admitted again under the same reservation and sends;
*   stopped after dispatch (before or after sending, or with a reply it never settled): the
    request may have been billed, so the retry is refused and sends nothing, and the whole
    reservation stays held;
*   stopped after settling: the retry is refused as already answered.

A restarted process never finds the allowance replenished: what the first held is still held.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from spending_support import bench, one_reservation

__all__ = ["bench"]

pytestmark = pytest.mark.postgres

CHILD = Path(__file__).with_name("spending_race_child.py")

#: Each point: whether the first process's request reached the transport, the reservation's
#: state after the kill (None: no reservation), and the retry's refusal (None: it sends).
CASES = {
    "witnessed": (False, None, None),
    "admitted": (False, "admitted", None),
    "dispatched": (False, "dispatched", "duplicate_request_unknown"),
    "sent": (True, "dispatched", "duplicate_request_unknown"),
    "received": (True, "dispatched", "duplicate_request_unknown"),
    "settled": (True, "settled", "duplicate_request_settled"),
}


def _run(tmp_path: Path, bench, name: str, workspace: uuid.UUID, **config) -> tuple[int, dict]:
    result = tmp_path / f"{name}.result.json"
    document = {
        "database_url": bench.runtime.url,
        "witness_dir": str(bench.witness_dir),
        "data_dir": str(tmp_path / f"{name}-data"),
        "go": str(tmp_path / f"{name}.go"),
        "sends": str(tmp_path / f"{name}.sends.log"),
        "result": str(result),
        "label": name,
        "mode": "plain",
        "workspace": str(workspace),
        "usage": True,
        **config,
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(document))
    (tmp_path / f"{name}.go").write_text("go")
    completed = subprocess.run(
        [sys.executable, str(CHILD), str(path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        timeout=120,
    )
    outcome = json.loads(result.read_text()) if result.exists() else {}
    return completed.returncode, outcome


def _sends(tmp_path: Path) -> int:
    return sum(len(path.read_text().splitlines()) for path in tmp_path.glob("*.sends.log"))


@pytest.mark.parametrize("point", list(CASES))
def test_a_call_killed_at_any_point_is_never_sent_twice_or_refunded(bench, tmp_path, point):
    sent_first, state_after, retry_refusal = CASES[point]
    authority = bench.issue(dispatch_seconds=1)
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    key = f"crash:{point}"

    code, _outcome = _run(tmp_path, bench, "first", workspace, request_key=key, kill_at=point)
    assert code == -signal.SIGKILL
    assert _sends(tmp_path) == int(sent_first)
    rows = bench.reservations(workspace)
    if state_after is None:
        assert rows == []
        assert bench.state(authority)["committed_calls"] == 0
    else:
        (row,) = rows
        assert row["state"] == state_after
        # The restarted world still holds what the killed process held.
        assert bench.state(authority)["committed_calls"] == 1
        assert bench.state(authority)["committed_usd"] == (
            row["settled_usd"] if state_after == "settled" else one_reservation()
        )
    if point == "admitted":
        time.sleep(1.2)  # the dispatch window: an admission never dispatched in it never left

    code, outcome = _run(tmp_path, bench, "retry", workspace, request_key=key)
    assert code == 0, outcome
    assert outcome["errors"] == []
    if retry_refusal is None:
        assert outcome["sent"] == 1 and "last_refusal" not in outcome
        assert _sends(tmp_path) == 1
        (row,) = bench.reservations(workspace)
        assert row["state"] == "settled"
    else:
        assert outcome["sent"] == 0
        assert outcome["last_refusal"]["reason"] == retry_refusal
        assert _sends(tmp_path) == int(sent_first)
        (row,) = bench.reservations(workspace)
        assert row["state"] == state_after
    state = bench.state(authority)
    assert state["committed_calls"] == 1
    if row["state"] == "dispatched":
        assert state["committed_usd"] == one_reservation()
    assert bench.operator.verify_chain(authority)["first_bad_sequence"] is None
