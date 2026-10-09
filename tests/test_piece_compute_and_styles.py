"""The piece compute and piece style catalogs: what generating costs and what a request says of its
pack.

The compute catalog's figures are checked against the measured runs on main
(``ml/appearance/evidence/generated-assets-session-1`` and ``-2``: the results files' item
milliseconds, the done markers' claim instants and the gpu-run records' first starting instants),
not restated, so a figure that drifts from the evidence fails here. The style words are checked
against the committed packs and, for the measured pack, against the words the session requests
carried.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica_pieces.canonical import Refused
from exulanica_pieces.compute import COMPUTE_PATH, load_compute, read_compute
from exulanica_pieces.styles import STYLES_PATH, load_styles, read_styles

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "ml/appearance/evidence"
#: Each warm session's folder and its run record.
SESSIONS = {
    "generated-assets-session-1": "gpu-run-aijob-e05cx0ergby4xfwt0r.json",
    "generated-assets-session-2": "gpu-run-aijob-e05ff25ssmw6nk0ey7.json",
}
#: The provider the spending ledger knows GPU generation by (design-7, ruling D).
PROVIDER = "nebius_ai_cloud_gpu"


def _instant(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)


def _item_milliseconds() -> list[int]:
    found = []
    for folder in SESSIONS:
        for path in sorted((EVIDENCE / folder).glob("results-*.json")):
            found += [item["milliseconds"] for item in json.loads(path.read_text())["items"]]
    return found


def test_the_compute_figures_are_the_measured_runs() -> None:
    entry = load_compute(ROOT).for_provider(PROVIDER)
    measured = _item_milliseconds()
    assert len(measured) == 80
    # Typical: the median item, in whole seconds; bound: no item took longer.
    assert entry.item_seconds_typical == round(statistics.median(measured) / 1000)
    assert max(measured) <= entry.item_seconds_bound * 1000
    # Cold: from the first starting state (the record) to the first batch claimed (the markers),
    # with the provisioning before it inside what the catalog states.
    for folder, record in SESSIONS.items():
        started = _instant(json.loads((EVIDENCE / record).read_text())["started_at"])
        claims = [
            _instant(json.loads(path.read_text())["claimed_at"])
            for path in (EVIDENCE / folder / "done").glob("*.json")
        ]
        waited = (min(claims) - started).total_seconds()
        assert 0 < waited < entry.cold_start_seconds
        assert (
            record.removeprefix("gpu-run-").removesuffix(".json")
            in json.loads((EVIDENCE / record).read_text())["instance_name"]
        )
    # The rate and the platform are the ones every run record names.
    for record in SESSIONS.values():
        run = json.loads((EVIDENCE / record).read_text())
        assert run["rate_cents_per_hour"] == entry.rate_cents_per_hour
        assert run["instance_type"].startswith(f"{entry.platform}, preset {entry.preset}")
    assert entry.service_minimum_seconds == 3600
    # The basis an estimate states is these runs: each named by its folder, the items they timed.
    assert entry.basis is not None
    assert entry.basis.evidence == tuple(f"ml/appearance/evidence/{folder}" for folder in SESSIONS)
    assert (entry.basis.runs, entry.basis.items) == (len(SESSIONS), len(measured))


def test_the_estimates_are_the_rate_times_the_seconds() -> None:
    entry = load_compute(ROOT).for_provider(PROVIDER)
    # USD 1.80 an hour is half a cent a ten seconds: 4 items at 30 s and at 8 s.
    assert entry.worst_case_usd(4) == Decimal("0.06")
    assert entry.typical_usd(4) == Decimal("0.016")
    assert entry.usd_for_seconds(3600) == Decimal("1.80")
    # Rounded up to the ledger's eighth decimal place, never down.
    assert entry.usd_for_seconds(1) == Decimal("0.0005")
    with pytest.raises(Refused, match="whole"):
        entry.usd_for_seconds(-1)


def _compute(**changes: Any) -> dict[str, Any]:
    document = json.loads((ROOT / COMPUTE_PATH).read_text())
    document["entries"][0].update(changes)
    return document


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (_compute(item_seconds_typical=31), "no longer than its bound"),
        (_compute(item_seconds_bound=0), "whole number from 1"),
        (_compute(rate_cents_per_hour=1.8), "fraction"),
        (_compute(provider="Nebius AI Cloud"), "spending provider"),
        (_compute(platform="GPU RTX"), "lower case"),
        (_compute(rate_source="read"), "where the rate was read"),
        (_compute(reason="It is fast."), "what was measured"),
        (_compute(colour="red"), "has exactly"),
        (
            _compute(basis={"kind": "guessed", "runs": 1, "items": 1, "evidence": ["x"]}),
            "measured_runs",
        ),
        (
            _compute(
                basis={
                    "kind": "measured_runs",
                    "runs": 2,
                    "items": 80,
                    "evidence": ["ml/appearance/evidence/generated-assets-session-1"],
                }
            ),
            "each run's evidence folder once",
        ),
        ({**_compute(), "catalog_id": "piece-cost"}, "catalog 'piece-compute'"),
        ({**_compute(), "entries": []}, "at least one GPU"),
    ],
)
def test_the_compute_reader_refuses(document: dict[str, Any], match: str) -> None:
    with pytest.raises(Refused, match=match):
        read_compute(json.dumps(document).encode())


def test_a_provider_must_be_named_once() -> None:
    document = _compute()
    document["entries"].append({**document["entries"][0], "key": "a-second-card"})
    with pytest.raises(Refused, match="2 times"):
        read_compute(json.dumps(document).encode()).for_provider(PROVIDER)


def test_every_committed_pack_has_style_words_and_the_measured_ones_are_what_ran() -> None:
    styles = load_styles(ROOT)
    packs = sorted(path.name for path in (ROOT / "assets/style-packs/packs").iterdir())
    assert sorted(styles.words) == packs
    carried = set()
    for folder in SESSIONS:
        for path in (EVIDENCE / folder / "requests").glob("*.json"):
            pack = json.loads(path.read_text())["pack"]
            carried.add((pack["id"], pack["style"]))
    assert carried == {("exulanica.cozy-town", styles.words["exulanica.cozy-town"])}


def _styles(**changes: Any) -> dict[str, Any]:
    document = json.loads((ROOT / STYLES_PATH).read_text())
    document["entries"][0].update(changes)
    return document


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (_styles(style="cozy town in 3 colours"), "no numeral"),
        (_styles(style="Cozy town"), "lower case"),
        (_styles(style="a" * 121), "1 to 120"),
        (_styles(pack_id="Cozy Town"), "style pack's id"),
        (_styles(reason="Nice words."), "why these words"),
        (_styles(licence={**_styles()["entries"][0]["licence"], "verdict": "REVIEW"}), "ships"),
        (_styles(tone="warm"), "has exactly"),
    ],
)
def test_the_style_reader_refuses(document: dict[str, Any], match: str) -> None:
    with pytest.raises(Refused, match=match):
        read_styles(json.dumps(document).encode())


def test_a_pack_must_be_named_once() -> None:
    document = _styles()
    document["entries"].append(dict(document["entries"][0]))
    with pytest.raises(Refused, match="second time"):
        read_styles(json.dumps(document).encode())
