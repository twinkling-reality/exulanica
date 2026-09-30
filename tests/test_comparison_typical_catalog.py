"""Shipped comparison cost figures preserve their measured sources and conservative fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.api.society_comparison_start import (
    _TYPICAL_READERS,
    TYPICAL_CATALOG,
    TYPICAL_FALLBACK,
    figures_for,
    typical_figures,
)

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_figures_match_source_records_and_images_include_catalog():
    catalog = json.loads(TYPICAL_CATALOG.read_text())
    for entry in catalog["entries"]:
        source = ROOT / entry["source"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["source_sha256"]
        cost, latency = _TYPICAL_READERS[entry["extraction"]](
            json.loads(source.read_text())["record"]
        )
        measured = typical_figures(entry["navigation"])
        assert measured is not None
        assert measured.per_person_hour == cost
        assert measured.latency_p95_ms == latency
    for image in ("Dockerfile", "deploy/judge/web.Dockerfile"):
        assert "COPY assets" in (ROOT / image).read_text()


def test_unmeasured_living_ground_uses_named_greatest_measured_fallback():
    figures, matched = figures_for("city-walking-surfaces/v2", ["nvidia/Nemotron-3_5-Lightning"])
    assert figures is not None and not matched
    assert figures.record == TYPICAL_FALLBACK
    model = "nvidia/Nemotron-3_5-Lightning"
    assert figures.per_person_hour[model] == max(
        typical_figures(n).per_person_hour[model]
        for n in ("authored-ground-lattice/v1", "city-walking-surfaces/v1")
    )
