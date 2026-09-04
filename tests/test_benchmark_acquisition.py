"""The licensed benchmark is exact, bounded, and separate from production ingest."""

from __future__ import annotations

import hashlib

import pytest
from exulanica.evaluation import benchmark
from exulanica.evaluation.benchmark import (
    BenchmarkAcquisitionError,
    load_benchmark_manifest,
    verify_benchmark_tree,
)


def test_eth3d_manifest_is_digest_bound_and_explicitly_benchmark():
    record, digest = load_benchmark_manifest()

    assert digest == "4402e042b99153d1cbf247449b16b36f2864338bac28e44dc59f631a25815814"
    assert record["corpus_class"] == "benchmark"
    assert record["dataset"]["scene"] == "pipes"
    assert record["archive"]["url"].startswith("https://www.eth3d.net/data/")
    assert record["license"]["identifier"] == "CC-BY-NC-SA-4.0"
    assert record["image_count"] == 14
    images = [item for item in record["files"] if "width" in item]
    assert len(images) == 14
    assert {(item["width"], item["height"]) for item in images} == {(6220, 4141)}
    assert record["privacy_inspection"]["production_human_review"] == ("required-before-admission")


def test_materialized_benchmark_refuses_changed_or_uninventoried_bytes(tmp_path):
    payload = b"licensed benchmark frame"
    path = tmp_path / "scene" / "images" / "frame.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    manifest = {
        "files": [
            {
                "bytes": len(payload),
                "path": "scene/images/frame.jpg",
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ]
    }
    verify_benchmark_tree(tmp_path, manifest)

    path.write_bytes(b"changed")
    with pytest.raises(BenchmarkAcquisitionError, match="size mismatch"):
        verify_benchmark_tree(tmp_path, manifest)
    path.write_bytes(payload)
    (tmp_path / "unlisted.txt").write_text("not admitted")
    with pytest.raises(BenchmarkAcquisitionError, match="unexpected"):
        verify_benchmark_tree(tmp_path, manifest)


def test_archive_listing_refuses_traversal_and_requires_exact_inventory():
    with pytest.raises(BenchmarkAcquisitionError, match="unsafe"):
        benchmark._safe_archive_members("../outside.jpg\n", {"scene/frame.jpg"})
    with pytest.raises(BenchmarkAcquisitionError, match="inventory differs"):
        benchmark._safe_archive_members("scene/other.jpg\n", {"scene/frame.jpg"})

    benchmark._safe_archive_members(
        "scene/\nscene/frame.jpg\n",
        {"scene/frame.jpg"},
    )
