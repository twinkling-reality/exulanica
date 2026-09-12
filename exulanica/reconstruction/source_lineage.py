"""Pure, independently verifiable normalized-image lineage, separate from privacy masks."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

DECODED_PROFILE = "exulanica.decoded-source/v1"
DECODED_PARAMS = {
    "decoder": "pi-heif",
    "decoder_version": "1.4.0",
    "format": "PNG",
    "mode": "RGB",
    "bits_per_channel": 8,
    "compress_level": 6,
    "orientation": "libheif-container-transform-once",
    "pixel_grid": "display-top-left-x-right-y-down",
    "color_policy": "decoder-rgb-no-icc-transform",
    "metadata": "removed",
    "convert_hdr_to_8bit": True,
    "hdr_to_16bit": True,
    "alpha_policy": "discard-after-decoder-rgb-conversion",
    "decode_threads": 1,
}


def verify_decoded_record(
    value: dict[str, Any], *, source_sha256: str, output_sha256: str
) -> dict[str, Any]:
    """Verify the receipt's internal binding. Hashing pixels is the byte reader's job."""
    if set(value) != {
        "profile",
        "source_sha256",
        "output_sha256",
        "decoder",
        "parameters",
        "pixel_grid",
    }:
        raise ValueError("decoded source receipt has unexpected fields")
    if value["profile"] != DECODED_PROFILE or canonical_json(value["parameters"]) != canonical_json(
        {
            **DECODED_PARAMS,
            "decoder_inventory": value["decoder"],
        }
    ):
        raise ValueError("unsupported decoded source contract")
    if value["source_sha256"] != source_sha256 or value["output_sha256"] != output_sha256:
        raise ValueError("decoded source digest binding disagrees")
    if source_sha256 == output_sha256 or any(
        not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
        for v in (source_sha256, output_sha256)
    ):
        raise ValueError("decoded source requires distinct exact source and output hashes")
    decoder = value["decoder"]
    if (
        not isinstance(decoder, dict)
        or set(decoder) != {"pi-heif", "libheif", "libde265", "pillow"}
        or decoder["pi-heif"] != "1.4.0"
        or any(not isinstance(v, str) or not v for v in decoder.values())
    ):
        raise ValueError("decoded source decoder inventory is incomplete")
    grid = value["pixel_grid"]
    if (
        not isinstance(grid, dict)
        or set(grid) != {"width", "height", "orientation", "convention"}
        or type(grid["orientation"]) is not int
        or grid["orientation"] != 1
        or grid["convention"] != DECODED_PARAMS["pixel_grid"]
        or any(type(grid[k]) is not int or grid[k] <= 0 for k in ("width", "height"))
        or grid["width"] * grid["height"] > 64_000_000
    ):
        raise ValueError("decoded source pixel grid is invalid")
    canonical_json(value)
    return value


def decoded_receipt(record: dict[str, Any]) -> dict[str, Any]:
    verify_decoded_record(
        record, source_sha256=record["source_sha256"], output_sha256=record["output_sha256"]
    )
    return {"record": record, "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest()}


def verify_decoded_receipt(
    value: dict[str, Any], *, source_sha256: str, output_sha256: str
) -> dict[str, Any]:
    if set(value) != {"record", "record_sha256"}:
        raise ValueError("decoded receipt envelope is malformed")
    record = verify_decoded_record(
        value["record"], source_sha256=source_sha256, output_sha256=output_sha256
    )
    if hashlib.sha256(canonical_json(record)).hexdigest() != value["record_sha256"]:
        raise ValueError("decoded receipt digest disagrees")
    return record


def decoded_training_sources(
    lineage: tuple[dict[str, Any], ...],
    masked_remap: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, tuple[str, str, dict[str, Any]]]:
    """Capture -> (original, selected input, receipt), composing conversion and masking."""
    masks = {capture: (original, masked) for capture, original, masked in masked_remap}
    result = {}
    originals, normalized = set(), set()
    for entry in lineage:
        if not isinstance(entry, dict) or set(entry) != {"capture_ref", "receipt"}:
            raise ValueError("decoded training lineage entry is malformed")
        capture = entry["capture_ref"]
        if (
            not isinstance(capture, str)
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", capture)
            or capture in result
        ):
            raise ValueError("decoded training lineage has no unique capture")
        envelope = entry["receipt"]
        try:
            record = envelope["record"]
            source, output = record["source_sha256"], record["output_sha256"]
            verify_decoded_receipt(envelope, source_sha256=source, output_sha256=output)
        except (KeyError, TypeError) as error:
            raise ValueError("decoded training receipt is malformed") from error
        if source in originals or output in normalized:
            raise ValueError("decoded training lineage duplicates source identities")
        originals.add(source)
        normalized.add(output)
        selected = output
        if capture in masks:
            if masks[capture][0] != source:
                raise ValueError("mask and decoded source originals disagree")
            selected = masks[capture][1]
        result[capture] = (source, selected, record)
    if list(result) != sorted(result):
        raise ValueError("decoded training lineage must be ordered by capture")
    return result


def verify_decoded_training_inputs(
    lineage: tuple[dict[str, Any], ...],
    masked_remap: tuple[tuple[str, str, str], ...],
    sources: Iterable[str],
) -> None:
    for original, selected, record in decoded_training_sources(lineage, masked_remap).values():
        if selected not in sources or original in sources:
            raise ValueError("decoded training input does not bind the selected derivative")
        if selected != record["output_sha256"] and record["output_sha256"] in sources:
            raise ValueError("an unmasked normalized input reached masked training")


def verify_decoded_training_files(
    lineage: tuple[dict[str, Any], ...],
    masked_remap: tuple[tuple[str, str, str], ...],
    paths: Iterable[Path],
) -> None:
    """Offline verification of selected bytes and pixel grids, without opening originals."""
    from exulanica.corpus.decode import open_sensor

    by_digest = {}
    for path in paths:
        data = path.read_bytes()
        by_digest[hashlib.sha256(data).hexdigest()] = data
    verify_decoded_training_inputs(lineage, masked_remap, set(by_digest))
    for _, selected, record in decoded_training_sources(lineage, masked_remap).values():
        with open_sensor(by_digest[selected]) as image:
            grid = record["pixel_grid"]
            if image.size != (grid["width"], grid["height"]) or image.getexif().get(274, 1) != 1:
                raise ValueError("decoded training input pixel grid disagrees")
            if selected == record["output_sha256"] and (
                image.format != "PNG" or image.mode != "RGB"
            ):
                raise ValueError("normalized training input is not an RGB PNG")
