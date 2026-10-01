"""Separate processes racing one small durable limit never admit past it together.

Four operating-system processes spend under one authority at once: two plain clients, one built
as the API builds its client (``build_services``, ``Services.hosted_model``), one built as the
derivative worker builds its own (``worker_model_client``, the caption pass's workspace policy).
Every answer arrives without a usage report, so every admitted attempt keeps its whole reservation
and the limit is reached by liability alone. The ledger's own events are replayed afterwards: at no
point did the authority's committed liability pass its ceiling, every request the transports saw
was a dispatched reservation, and no refused attempt reached a transport.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.usage import usd_string

from spending_support import bench, one_reservation

__all__ = ["bench"]

pytestmark = pytest.mark.postgres

CHILD = Path(__file__).with_name("spending_race_child.py")


def _embedding_reservation() -> Decimal:
    spec = load_manifest()[Role.EMBEDDING].primary
    return BudgetGuard(ceiling_usd=Decimal(1), max_calls=1).estimate_usd(
        spec, prompt_chars=len("a caption"), max_tokens=0
    )


def _launch(
    tmp_path: Path, bench, name: str, *, witnessed: bool = True, **config
) -> tuple[subprocess.Popen, Path]:
    result = tmp_path / f"{name}.result.json"
    document = {
        "database_url": bench.runtime.url,
        "witness_dir": str(bench.witness_dir) if witnessed else None,
        "data_dir": str(tmp_path / f"{name}-data"),
        "go": str(tmp_path / "go"),
        "sends": str(tmp_path / f"{name}.sends.log"),
        "result": str(result),
        "label": name,
        **config,
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(document))
    process = subprocess.Popen(
        [sys.executable, str(CHILD), str(path)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return process, result


@pytest.mark.parametrize("witnessed", [True, False], ids=["witnessed", "database-lock-only"])
def test_processes_racing_one_small_limit_never_admit_past_it(bench, tmp_path, witnessed):
    """With a witness, every step also waits on the witness's file lock. Without one, the
    authority's row lock is all that orders them, and the result must not change."""
    chat, embed = one_reservation(), _embedding_reservation()
    ceiling = chat * 40
    authority = bench.issue(ceiling=ceiling, calls=100_000, witnessed=witnessed)
    first, second = uuid.uuid4(), uuid.uuid4()
    bench.grant(authority, first, ceiling=ceiling, calls=100_000)
    bench.grant(authority, second, ceiling=ceiling, calls=100_000)
    names = {
        "race-plain-a": ("plain", first),
        "race-plain-b": ("plain", second),
        "race-api": ("api", first),
        "race-worker": ("worker", second),
    }
    launched = [
        _launch(tmp_path, bench, name, witnessed=witnessed, mode=mode, workspace=str(workspace))
        for name, (mode, workspace) in names.items()
    ]
    deadline = time.monotonic() + 120
    while not all(result.with_suffix(".ready").exists() for _process, result in launched):
        assert time.monotonic() < deadline, "a racing process never became ready"
        assert all(process.poll() is None for process, _result in launched), "a process died"
        time.sleep(0.05)
    (tmp_path / "go").write_text("go")
    results = []
    for process, result in launched:
        _stdout, stderr = process.communicate(timeout=180)
        assert process.returncode == 0, stderr.decode()[-2000:]
        results.append(json.loads(result.read_text()))
    for result in results:
        assert result["errors"] == [], result
        assert result["sent"] >= 1, result
        assert set(result["refused"]) <= {"spending_limit_reached"}, result

    sends = sum(len(path.read_text().splitlines()) for path in tmp_path.glob("*.sends.log"))
    reservations = bench.query("select * from spending_reservation")
    dispatched = [row for row in reservations if row["dispatched_at"] is not None]
    # Every request a transport saw was a dispatched reservation, and every call a process
    # counted as sent was one of them: a refused attempt reached no transport.
    assert sends == len(dispatched) == sum(result["sent"] for result in results)
    assert all(row["state"] == "unknown" for row in dispatched)
    # The ledger replayed event by event: the authority never held more than its ceiling.
    path = bench.committed_over_time(authority)
    assert max(path) <= ceiling
    state = bench.state(authority)
    assert state["committed_usd"] == sum(row["settled_usd"] for row in dispatched)
    # And it was spent to within one attempt of the ceiling: the refusals were real.
    assert ceiling - state["committed_usd"] < max(chat, embed)
    # Four processes, each naming every attempt it admitted apart.
    assert len({row["holder"].rsplit(":", 1)[0] for row in reservations}) == 4
    assert len({row["holder"] for row in reservations}) == len(reservations)
    assert bench.operator.verify_chain(authority)["first_bad_sequence"] is None
    evidence = os.environ.get("EXULANICA_B1_EVIDENCE_DIR")
    if evidence:
        record = {
            "witnessed": witnessed,
            "ceiling_usd": usd_string(ceiling),
            "chat_reservation_usd": usd_string(chat),
            "embedding_reservation_usd": usd_string(embed),
            "processes": {name: result for name, result in zip(names, results, strict=True)},
            "transport_sends": sends,
            "dispatched_reservations": len(dispatched),
            "committed_usd": usd_string(state["committed_usd"]),
            "committed_calls": state["committed_calls"],
            "highest_committed_usd_replayed": usd_string(max(path)),
            "events": len(path),
        }
        target = Path(evidence) / f"race-{'witnessed' if witnessed else 'database-lock-only'}.json"
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
