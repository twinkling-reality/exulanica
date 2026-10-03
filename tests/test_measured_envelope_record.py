"""docs/deployment.md 5.4.7 quotes its inhabited-world figures from their retained record.

The two items for towns beside the supported load, played by the API process and by the playback
process, read every figure from ``docs/evaluation/2026-10-02-asset-lock-holders.json`` (phases
``sharing`` and ``sharing_process``). Each figure is computed here from the record, in the words
the section uses, and must appear in its item, so a figure retyped or left behind by a later record
fails. The record's sampler classed no lock holder as a traffic read, and the section says so.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "evaluation" / "2026-10-02-asset-lock-holders.json"
DEPLOYMENT = ROOT / "docs" / "deployment.md"
ITEMS = {
    "sharing": "- **Inhabited worlds beside the supported load:**",
    "sharing_process": "- **The same towns played by the playback process:**",
}


def _whole(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _tenths(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _time(ms: str) -> str:
    """Milliseconds under a second as whole milliseconds, then tenths of a second, then seconds."""
    value = Decimal(ms)
    if value < 1000:
        return f"{_whole(value)} ms"
    if value < 10000:
        return f"{_tenths(value / 1000)} s"
    return f"{_whole(value / 1000)} s"


def _mib(kib: int) -> str:
    return f"{_whole(Decimal(kib) / 1024)} MiB"


def figures(phase_name: str) -> list[str]:
    """The phrases the section's item for ``phase_name`` quotes, from the record."""
    record = json.loads(RECORD.read_text(encoding="utf-8"))["record"]
    phase = record["phases"][phase_name]
    result, barrier = phase["result"], phase["barrier"]
    towns, traffic = result["towns"], result["traffic_reads"]
    reads, uploads = result["clients"]["reads"], result["clients"]["uploads"]
    server = result["server"]
    tick_seconds = Decimal(towns["base_tick_interval_ms"]) / towns["speed"] / 1000
    owed = Decimal(towns["wall_seconds"]) / tick_seconds
    ticks = towns["ticks_advanced"]
    shares = sorted({_whole(Decimal(tick) * 100 / owed) for tick in ticks})
    refused_reads = sum(n for status, n in reads["by_status"].items() if status != "200")
    rounds = next(cls for cls in phase["refusals"]["by_holder_class"] if cls.startswith("society"))
    photographs = uploads["photos_accepted"] + uploads["parts_busy"]
    held = barrier["samples_with_exclusive_held"]
    phrases = [
        " to ".join(str(share) for share in shares) + " percent of the ticks their speed sets",
        " to ".join(str(tick) for tick in sorted(set(ticks))) + " ticks",
        f"{_time(traffic['ms']['p50'])} p50",
        f"{_time(traffic['ms']['p95'])} p95",
        f"at most {_time(traffic['ms']['max'])}",
        f"{_time(reads['admitted_ms']['p95'])} p95",
        f"{refused_reads:,} of {refused_reads + reads['by_status']['200']:,}",
        f"{uploads['by_status']['202']} of {uploads['sent']} uploads",
        f"{uploads['parts_busy']} of {photographs} photographs",
        f"{_tenths(Decimal(held) * 100 / phase['sampler']['samples'])} percent of its samples",
        f"{phase['refusals']['by_holder_class'][rounds]} of the {phase['refusals']['count']} "
        "guarded writes",
        _mib(server["api_rss_kib_peak"]),
    ]
    if "playback_rss_kib_peak" in server:
        phrases.append(_mib(server["playback_rss_kib_peak"]))
    return phrases


def _item(text: str, label: str) -> str:
    start = text.index(label)
    following = text.find("\n- **", start + len(label))
    return text[start : following if following != -1 else len(text)]


def _section() -> str:
    text = DEPLOYMENT.read_text(encoding="utf-8")
    start = text.index("#### 5.4.7 The measured envelope")
    return text[start : text.index("#### 5.4.8", start)]


def test_each_inhabited_world_figure_is_the_records():
    section = _section()
    assert "evaluation/2026-10-02-asset-lock-holders.json" in re.sub(r"\s+", " ", section)
    for phase_name, label in ITEMS.items():
        item = re.sub(r"\s+", " ", _item(section, label))
        missing = [phrase for phrase in figures(phase_name) if phrase not in item]
        assert not missing, (phase_name, missing)


def test_no_traffic_read_held_the_lock_and_the_section_says_so():
    record = json.loads(RECORD.read_text(encoding="utf-8"))["record"]
    for phase_name in ITEMS:
        holders = record["phases"][phase_name]["holders"]
        assert holders and not [cls for cls in holders if "traffic" in cls], holders
    section = re.sub(r"\s+", " ", _section())
    assert "No traffic read held it." in section
    assert "traffic_host.py" not in section
