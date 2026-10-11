"""What an ask of a model mind typically costs, and how often a being is asked: measured figures.

The most one answer can cost is the host's own reservation bound
(``exulanica.api.decision_host.ask_bound_usd``), and it is far above what an ask usually costs. A
person who gives a mind or sets a world's budget for its minds is told both, so the typical
figures are data: ``assets/catalogs/society-minds-cost/society-minds-typical-cost.v1.json``, one
entry a society engine and a model, each naming the immutable evaluation record it is read from
and the counts of that record's arm. This module works the two figures out of the counts exactly:
dollars an ask, and asks a being a simulated minute.

What it holds by construction:

*   **A figure is stated with its class.** A rate from an arm its own registration calls cut is
    an estimate (``rate_class``), and every value read here carries that, so a reader cannot
    serve it as a measurement.
*   **No entry, no figure.** An engine and model nobody measured has no typical cost; nothing is
    carried over from another model or another engine.
*   **One model at a time.** A read answers for the one model it is asked about. Nothing here
    lists models beside each other.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final

__all__ = ["CATALOG", "ESTIMATE", "MEASURED", "TypicalAsk", "typical_ask"]

_ROOT: Final = Path(__file__).resolve().parents[2]
CATALOG: Final = _ROOT / "assets/catalogs/society-minds-cost/society-minds-typical-cost.v1.json"
MEASURED: Final = "measured"
ESTIMATE: Final = "estimate"
_CLASSES: Final = (MEASURED, ESTIMATE)
_MICRO: Final = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class TypicalAsk:
    """One engine's and model's typical figures, as its arm of the record counted them."""

    engine: str
    provider: str
    model_id: str
    asks: int
    beings: int
    simulated_minutes: int
    usd: Decimal
    #: How many beings the measured world held in all.
    beings_in_the_world: int
    rate_class: str
    price_class: str
    source: str
    source_sha256: str
    arm: str

    @property
    def usd_per_ask(self) -> Decimal:
        """What one ask cost on average: every dollar the arm's receipts state over its asks,
        an answer the model did not finish among them."""
        return self.usd / Decimal(self.asks)

    @property
    def asks_per_being_minute(self) -> Decimal:
        """How often one being whose mind is the model was asked, a simulated minute."""
        return Decimal(self.asks) / Decimal(self.beings * self.simulated_minutes)

    @property
    def rate_is_an_estimate(self) -> bool:
        return self.rate_class != MEASURED

    def view(self) -> dict[str, Any]:
        """The figures as a read serves them, each with its class and where it comes from."""
        return {
            "usd_per_ask": str(self.usd_per_ask.quantize(Decimal("0.00000001"))),
            "price_class": self.price_class,
            "asks_per_being_minute": str(self.asks_per_being_minute.quantize(_MICRO)),
            "rate_class": self.rate_class,
            "measured_on": {
                "asks": self.asks,
                "beings_with_the_model": self.beings,
                "beings_in_the_world": self.beings_in_the_world,
                "simulated_minutes": self.simulated_minutes,
            },
            "source": self.source,
            "source_sha256": self.source_sha256,
        }


def _entry(raw: Mapping[str, Any]) -> TypicalAsk:
    found = TypicalAsk(
        engine=str(raw["engine"]),
        provider=str(raw["provider"]),
        model_id=str(raw["model_id"]),
        asks=int(raw["asks"]),
        beings=int(raw["beings"]),
        simulated_minutes=int(raw["simulated_minutes"]),
        usd=Decimal(str(raw["usd"])),
        beings_in_the_world=int(raw["beings_in_the_world"]),
        rate_class=str(raw["rate_class"]),
        price_class=str(raw["price_class"]),
        source=str(raw["source"]),
        source_sha256=str(raw["source_sha256"]),
        arm=str(raw["arm"]),
    )
    if (
        min(found.asks, found.beings, found.simulated_minutes) < 1
        or found.usd <= 0
        or found.rate_class not in _CLASSES
        or found.price_class not in _CLASSES
        or raw.get("key") != f"{found.engine}|{found.provider}|{found.model_id}"
    ):
        raise ValueError(f"invalid typical-cost entry {raw.get('key')!r}")
    return found


@cache
def _entries(path: Path = CATALOG) -> Mapping[tuple[str, str, str], TypicalAsk]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("catalog_id") != "society-minds-typical-cost"
        or document.get("catalog_version") != 1
    ):
        raise ValueError("invalid minds typical-cost catalog")
    found: dict[tuple[str, str, str], TypicalAsk] = {}
    for raw in document["entries"]:
        entry = _entry(raw)
        key = (entry.engine, entry.provider, entry.model_id)
        if key in found:
            raise ValueError(f"typical-cost entry stated twice: {raw['key']!r}")
        found[key] = entry
    return found


def typical_ask(engine: str | None, provider: str, model_id: str) -> TypicalAsk | None:
    """The typical figures of ``model_id`` deciding for beings of ``engine``, or None where that
    engine and model were never measured."""
    if engine is None:
        return None
    return _entries().get((engine, provider, model_id))
