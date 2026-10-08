"""Where pieces are generated and what it measured to cost: the piece compute catalog.

``assets/catalogs/generation/piece-compute.v1.json`` names, per GPU the product may generate on,
its spending provider, its region, platform and preset, the listed rate with its source and the
date it was read, and what generating took there: the typical and the bounding seconds of one item
and the seconds from asking for a session to its first batch. Every figure comes from a measured
run that the entry's reason names; a new GPU, or a new rate, is a new catalog version.

A request's estimate and its spending worst case are read from here, so the page, the ledger and
the worker hold one set of numbers. Plain Python with no numpy: the product reads this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Final

from exulanica_pieces.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    parse_strict,
    sha256_hex,
)

__all__ = [
    "COMPUTE_CATALOG_ID",
    "COMPUTE_PATH",
    "ComputeEntry",
    "PieceCompute",
    "load_compute",
    "read_compute",
]

#: Relative to the repository root.
COMPUTE_PATH: Final = "assets/catalogs/generation/piece-compute.v1.json"
COMPUTE_CATALOG_ID: Final = "piece-compute"
_CATALOG_KEYS: Final = ("catalog_id", "catalog_version", "entries", "schema_version")
_ENTRY_KEYS: Final = (
    "cold_start_seconds",
    "item_seconds_bound",
    "item_seconds_typical",
    "key",
    "licence",
    "platform",
    "preset",
    "provider",
    "rate_cents_per_hour",
    "rate_source",
    "reason",
    "region",
    "service_minimum_seconds",
)
_LICENCE_KEYS: Final = ("content_source", "licence_source", "origin", "spdx", "verdict")
_KEY: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
#: The spending ledger's provider names (0124's check on the provider column).
_PROVIDER: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_NAME: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_REASON_WORDS: Final = 5
#: The ledger holds amounts to eight decimal places (0124).
_USD_QUANTUM: Final = Decimal("0.00000001")


@dataclass(frozen=True, slots=True)
class ComputeEntry:
    """One GPU the product may generate on, and what generating there measured."""

    key: str
    provider: str
    region: str
    platform: str
    preset: str
    rate_cents_per_hour: int
    rate_source: str
    item_seconds_typical: int
    item_seconds_bound: int
    cold_start_seconds: int
    service_minimum_seconds: int

    def usd_for_seconds(self, seconds: int) -> Decimal:
        """The listed rate times ``seconds``, rounded up to the ledger's quantum."""
        if not is_count(seconds):
            raise Refused("a duration is a whole, non-negative number of seconds")
        usd = Decimal(self.rate_cents_per_hour) * seconds / Decimal(360_000)
        return usd.quantize(_USD_QUANTUM, rounding=ROUND_CEILING)

    def usd_for_milliseconds(self, milliseconds: int) -> Decimal:
        """What a request's measured milliseconds cost: the listed rate times them, rounded up to
        the millionth of a dollar, the rounding a GPU run record's charge lines use, so the ledger
        and the run record settle a request to the same amount."""
        if not is_count(milliseconds):
            raise Refused("a duration is a whole, non-negative number of milliseconds")
        microdollars = -(-self.rate_cents_per_hour * 10_000 * milliseconds // 3_600_000)
        return Decimal(microdollars) / Decimal(1_000_000)

    def worst_case_usd(self, items: int) -> Decimal:
        """What ``items`` items can cost at most: each at its bounding seconds."""
        return self.usd_for_seconds(items * self.item_seconds_bound)

    def typical_usd(self, items: int) -> Decimal:
        """What ``items`` items typically cost: each at its typical seconds."""
        return self.usd_for_seconds(items * self.item_seconds_typical)


@dataclass(frozen=True, slots=True)
class PieceCompute:
    """The read catalog: its version, its digest and its entries by key."""

    catalog_version: int
    sha256: str
    entries: Mapping[str, ComputeEntry]

    def for_provider(self, provider: str) -> ComputeEntry:
        """The one entry a spending provider names."""
        found = [entry for entry in self.entries.values() if entry.provider == provider]
        if len(found) != 1:
            raise Refused(f"{COMPUTE_PATH} names {provider} {len(found)} times, not once")
        return found[0]


def read_compute(raw: bytes) -> PieceCompute:
    """The catalog, strictly: the house envelope, exact keys, every figure a positive whole number,
    a typical item no slower than its bound, and every entry saying what was measured."""
    where = COMPUTE_PATH
    document = exact_keys(parse_strict(raw, where), _CATALOG_KEYS, where)
    if document["schema_version"] != 1 or document["catalog_id"] != COMPUTE_CATALOG_ID:
        raise Refused(f"{where} is schema version 1 of catalog {COMPUTE_CATALOG_ID!r}")
    if not is_count(document["catalog_version"], 1):
        raise Refused(f"{where}: catalog_version is a whole number from 1")
    entries = document["entries"]
    if not isinstance(entries, list) or not entries:
        raise Refused(f"{where}: entries is a list of at least one GPU")
    found: dict[str, ComputeEntry] = {}
    for index, value in enumerate(entries):
        at = f"{where}: entries[{index}]"
        entry = exact_keys(value, _ENTRY_KEYS, at)
        if not isinstance(entry["key"], str) or _KEY.fullmatch(entry["key"]) is None:
            raise Refused(f"{at}.key is lower case letters, digits and hyphens")
        if entry["key"] in found:
            raise Refused(f"{at}.key {entry['key']} is named a second time")
        if not isinstance(entry["provider"], str) or _PROVIDER.fullmatch(entry["provider"]) is None:
            raise Refused(f"{at}.provider is a spending provider's name")
        for name in ("region", "platform", "preset"):
            if not isinstance(entry[name], str) or _NAME.fullmatch(entry[name]) is None:
                raise Refused(f"{at}.{name} is lower case letters, digits and hyphens")
        for name in (
            "rate_cents_per_hour",
            "item_seconds_typical",
            "item_seconds_bound",
            "cold_start_seconds",
            "service_minimum_seconds",
        ):
            if not is_count(entry[name], 1):
                raise Refused(f"{at}.{name} is a whole number from 1")
        if entry["item_seconds_typical"] > entry["item_seconds_bound"]:
            raise Refused(f"{at}: a typical item takes no longer than its bound")
        if not isinstance(entry["rate_source"], str) or len(entry["rate_source"].split()) < 3:
            raise Refused(f"{at}.rate_source says where the rate was read and when")
        reason = entry["reason"]
        if not isinstance(reason, str) or len(reason.split()) < _REASON_WORDS:
            raise Refused(f"{at}.reason says, in a sentence, what was measured")
        licence = exact_keys(entry["licence"], _LICENCE_KEYS, f"{at}.licence")
        if licence["origin"] != "original" or licence["verdict"] != "SHIP":
            raise Refused(f"{at}.licence is original content that ships")
        found[entry["key"]] = ComputeEntry(
            key=entry["key"],
            provider=entry["provider"],
            region=entry["region"],
            platform=entry["platform"],
            preset=entry["preset"],
            rate_cents_per_hour=entry["rate_cents_per_hour"],
            rate_source=entry["rate_source"],
            item_seconds_typical=entry["item_seconds_typical"],
            item_seconds_bound=entry["item_seconds_bound"],
            cold_start_seconds=entry["cold_start_seconds"],
            service_minimum_seconds=entry["service_minimum_seconds"],
        )
    return PieceCompute(
        catalog_version=document["catalog_version"],
        sha256=sha256_hex(canonical_bytes(document)),
        entries=MappingProxyType(found),
    )


def load_compute(repository: Path) -> PieceCompute:
    """The committed catalog."""
    return read_compute((repository / COMPUTE_PATH).read_bytes())
