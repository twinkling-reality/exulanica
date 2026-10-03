"""Land a lock-holder record (``scripts/measure_asset_lock_holders.py``) as retained evidence.

    .venv/bin/python scripts/land_asset_lock_holders.py MEASURED.json RETAINED.json

which wrote docs/evaluation/2026-10-02-asset-lock-holders.json from W2's measured record.

The instrument's record holds what a retained record may not, and what canonical JSON refuses: the
command lines of the busiest other programs on the measuring machine, the run's temporary
directory, the logs it kept beside itself, the database role its own connection used, and floats.
The retained record keeps, by name, the fields that say what was measured, on which tree and how;
writes every float as its decimal string; counts every database role that is not one of the
product's under ``other roles``; binds the measured file by its SHA-256; and is wrapped as
``exulanica.digest-bound-record/v1`` (``tests/test_retained_evaluation_records.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json

MEASURED_PROFILE: Final = "exulanica.asset-lock-holders/v1"
RETAINED_PROFILE: Final = "exulanica.digest-bound-record/v1"
#: The measured record's fields a retained record keeps; anything else is left out.
KEPT: Final = (
    "started_at",
    "finished_at",
    "tree",
    "instrument_sha256",
    "harness_sha256",
    "workload_sha256",
    "machine",
    "notes",
    "idle_before_percent",
    "idle_after_percent",
    "load_before",
    "load_after",
    "phases_requested",
    "phase_specs",
    "phases",
    "refusals_logged",
    "sampler_interval_ms_target",
    "ports_used",
)
LEFT_OUT: Final = {
    "busiest_before": "the command lines of the busiest other programs on the measuring machine",
    "run_dir": "the run's temporary directory, removed after it",
    "process_logs and server_log": "the logs kept beside the measured file, which binds each "
    "by its SHA-256",
    "workload_ports_in_file": "the workload file's own ports; the run's are ports_used",
    "database roles": "every role in backends_peak_by_role that is not one of the product's is "
    "counted under 'other roles'",
}
_PRODUCT_ROLE_PREFIX: Final = "exulanica_"


def _as_text(value: Any) -> Any:
    """The value with every float written as its decimal string, which canonical JSON accepts."""
    if isinstance(value, float):
        return format(Decimal(repr(value)), "f")
    if isinstance(value, dict):
        return {key: _as_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_text(item) for item in value]
    return value


def _roles(by_role: dict[str, int]) -> dict[str, int]:
    kept = {role: count for role, count in by_role.items() if role.startswith(_PRODUCT_ROLE_PREFIX)}
    other = sum(
        count for role, count in by_role.items() if not role.startswith(_PRODUCT_ROLE_PREFIX)
    )
    if other:
        kept["other roles"] = other
    return kept


def landed(measured: bytes) -> dict[str, Any]:
    """The retained document for one measured record's bytes."""
    record = json.loads(measured)
    if record.get("profile") != MEASURED_PROFILE:
        raise SystemExit(f"not a {MEASURED_PROFILE} record")
    kept: dict[str, Any] = {
        "kind": MEASURED_PROFILE,
        "measured_file_sha256": hashlib.sha256(measured).hexdigest(),
        "left_out": LEFT_OUT,
        "numbers": "every float of the measured file is written as its decimal string",
    }
    kept.update({name: record[name] for name in KEPT})
    for phase in kept["phases"].values():
        server = phase["result"]["server"]
        if "backends_peak_by_role" in server:
            server["backends_peak_by_role"] = _roles(server["backends_peak_by_role"])
    kept = _as_text(kept)
    return {
        "profile": RETAINED_PROFILE,
        "record": kept,
        "record_sha256": hashlib.sha256(canonical_json(kept)).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("measured", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; a retained record is never rewritten")
    document = landed(args.measured.read_bytes())
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out} (record_sha256 {document['record_sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
