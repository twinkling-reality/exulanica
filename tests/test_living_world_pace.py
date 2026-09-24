"""The host's default playback pace is the one its measurement supports.

``docs/evaluation/2026-09-24-living-world-pace.json`` records how far a person in a saved world
walks in a simulated minute. A renderer walks each recorded path over the effective interval, so
the default base wait decides how fast walking looks at 1x. These tests hold the declared default
to the record that measured it and to the ordinary walking speeds the society policy states, and
hold the record to the exact script bytes it names.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.world.society import SOCIETY_TICK_SECONDS
from exulanica.world.society_catalogs import load_routine_model
from exulanica.world.society_controls import DEFAULT_BASE_TICK_INTERVAL_MS

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "evaluation" / "2026-09-24-living-world-pace.json"
MS_PER_SECOND = 1000


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))["record"]


def test_the_record_holds_the_script_that_measured_it_and_its_series():
    record = _record()
    for artifact in record["artifacts"]["files"]:
        data = (ROOT / artifact["path"]).read_bytes()
        assert len(data) == artifact["byte_size"], artifact["path"]
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"], artifact["path"]
    script = record["artifacts"]["files"][0]
    assert script["path"].endswith("measure_living_world_pace.py.txt")
    assert script["sha256"] == record["measured_with_sha256"]


def test_the_default_pace_was_measured_and_shows_ordinary_walking_at_1x():
    record = _record()
    assert record["inputs"]["declared_default_base_ms"] == DEFAULT_BASE_TICK_INTERVAL_MS
    assert DEFAULT_BASE_TICK_INTERVAL_MS in record["inputs"]["worker_bases_ms"]
    median_walked_mm = record["summary"]["inferred_walking_pace_on_screen"]["median_walked_mm"]
    on_screen_mm_per_second = median_walked_mm * MS_PER_SECOND // DEFAULT_BASE_TICK_INTERVAL_MS
    policy = load_routine_model().policy
    slowest = policy["walk_speed_minimum_mm_per_tick"] // SOCIETY_TICK_SECONDS
    fastest = policy["walk_speed_maximum_mm_per_tick"] // SOCIETY_TICK_SECONDS
    assert slowest <= on_screen_mm_per_second <= fastest, (
        f"at the default base a median walk shows {on_screen_mm_per_second} mm/s, outside the "
        f"policy's ordinary walking {slowest}..{fastest} mm/s"
    )
