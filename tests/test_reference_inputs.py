"""Exact sources and evaluation splits cannot silently change after preparation."""

import json

import pytest
from exulanica.evaluation.reference_inputs import (
    envelope,
    prepare_inputs,
    read_manifest,
    verify_inputs,
)
from PIL import Image


def prepared(tmp_path):
    sources = tmp_path / "images"
    sources.mkdir()
    for index in range(10):
        Image.new("RGB", (32, 24), (index * 20, 40, 90)).save(sources / f"view-{index:02}.png")
    license_file = tmp_path / "license.txt"
    license_file.write_text("Synthetic test license evidence, never a real permission.")
    output = tmp_path / "review"
    kwargs = dict(
        title="Synthetic input manifest fixture",
        official_source_url="https://example.org/data",
        license_name="TEST ONLY",
        license_file=license_file,
        license_url="https://example.org/license",
        attribution="Synthetic test",
        retrieval_date="2026-09-05",
    )
    manifest = prepare_inputs(sources, output, **kwargs)
    return sources, output, manifest, kwargs


def test_split_is_disjoint_complete_and_prepared_review_is_unanswered(tmp_path):
    sources, output, manifest, _ = prepared(tmp_path)
    value = verify_inputs(manifest, sources)
    split = value["record"]["evaluation_split"]
    assert len(split["heldout_sha256"]) == 2
    assert len(split["training_sha256"]) == 8
    assert not set(split["heldout_sha256"]) & set(split["training_sha256"])
    review = json.loads((output / "review-request.json").read_bytes())
    assert review["reviewed_by_name"] is None and review["attestation"] is None
    assert all(row["no_visible_people_or_sensitive_regions"] is None for row in review["members"])
    assert value["record"]["privacy"]["human_receipt"] is None
    assert "file://" in (output / "review.html").read_text()


def test_changed_source_and_rewritten_split_are_refused(tmp_path):
    sources, _, manifest, _ = prepared(tmp_path)
    image = sources / "view-00.png"
    original = image.read_bytes()
    image.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(ValueError, match="changed"):
        verify_inputs(manifest, sources)
    value = json.loads(manifest.read_bytes())
    value["record"]["evaluation_split"]["heldout_sha256"] = []
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="digest"):
        read_manifest(manifest)
    manifest.write_text(json.dumps(envelope(value["record"])))
    with pytest.raises(ValueError, match="partition"):
        read_manifest(manifest)


def test_preparation_cannot_overwrite_frozen_inventory(tmp_path):
    sources, output, manifest, kwargs = prepared(tmp_path)
    before = manifest.read_bytes()
    Image.new("RGB", (32, 24), (230, 240, 250)).save(sources / "extra.png")
    with pytest.raises(ValueError, match="frozen"):
        prepare_inputs(sources, output, **kwargs)
    assert manifest.read_bytes() == before


def test_duplicate_and_escaping_inventory_are_refused(tmp_path):
    _, _, manifest, _ = prepared(tmp_path)
    record = read_manifest(manifest)["record"]
    record["files"][1]["sha256"] = record["files"][0]["sha256"]
    manifest.write_text(json.dumps(envelope(record)))
    with pytest.raises(ValueError, match="unique"):
        read_manifest(manifest)
    record["files"][0]["path"] = "../outside.png"
    manifest.write_text(json.dumps(envelope(record)))
    with pytest.raises(ValueError, match="escapes"):
        read_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("path", "./view-00.png", "escapes"),
        ("path", "", "escapes"),
        ("sha256", "not-a-digest", "SHA-256"),
        ("bytes", True, "positive integers"),
        ("width", -1, "positive integers"),
        ("height", "24", "positive integers"),
    ],
)
def test_rehashed_malformed_inventory_cannot_become_valid(tmp_path, field, value, message):
    _, _, manifest, _ = prepared(tmp_path)
    record = read_manifest(manifest)["record"]
    record["files"][0][field] = value
    manifest.write_text(json.dumps(envelope(record)))
    with pytest.raises(ValueError, match=message):
        read_manifest(manifest)


def test_rehashed_duplicate_split_entries_are_refused(tmp_path):
    _, _, manifest, _ = prepared(tmp_path)
    record = read_manifest(manifest)["record"]
    record["evaluation_split"]["heldout_sha256"] *= 2
    manifest.write_text(json.dumps(envelope(record)))
    with pytest.raises(ValueError, match="unique arrays"):
        read_manifest(manifest)


def test_symlinked_parent_directory_cannot_substitute_reviewed_sources(tmp_path):
    sources, _, manifest, _ = prepared(tmp_path)
    (sources / "alias").symlink_to(sources, target_is_directory=True)
    record = read_manifest(manifest)["record"]
    record["files"][0]["path"] = "alias/view-00.png"
    manifest.write_text(json.dumps(envelope(record)))
    with pytest.raises(ValueError, match="regular file"):
        verify_inputs(manifest, sources)
