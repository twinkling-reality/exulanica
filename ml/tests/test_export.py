"""The export reader refuses anything its committed manifest does not describe, without torch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from exulanica_training.texture_inverse.__main__ import APPROVAL_ENV, REFUSED, main
from exulanica_training.texture_inverse.export import (
    ExportRefused,
    canonical_bytes,
    iter_split,
    verify_export,
)
from exulanica_training.texture_inverse.targets import encode, load_layout

REPOSITORY = Path(__file__).resolve().parents[2]
OBJECTS = REPOSITORY / "assets" / "textures" / "objects"
LIBRARY = REPOSITORY / "web" / "packages" / "loom-texture" / "library"
SIZE = 4


def _catalog_maker(maker_id: str) -> tuple[str, int, str]:
    catalog = json.loads((REPOSITORY / "assets" / "textures" / "catalog.json").read_bytes())
    (row,) = [row for row in catalog["makers"] if row["maker_id"] == maker_id]
    return row["maker_id"], row["version"], row["object_sha256"]


def _export(directory: Path, *, count: int = 3) -> Path:
    """A tiny export in exactly the exporter's format: one brick shard of four-pixel pictures."""
    recipe = json.loads((LIBRARY / "cc0.brick-running-bond.json").read_text())["recipe"]
    (directory / "images").mkdir(parents=True)
    pictures = bytes(range(256))[: SIZE * SIZE * 3] * count
    (directory / "images" / "cc0.brick-running-bond.rgb").write_bytes(pictures)
    lines = []
    for index in range(count):
        varied = json.loads(json.dumps(recipe))
        varied["seed"] = index
        lines.append(
            canonical_bytes(
                {
                    "index": index,
                    "set_id": "cc0.brick-running-bond",
                    "offset": index,
                    "recipe": varied,
                    "recipe_sha256": hashlib.sha256(canonical_bytes(varied)).hexdigest(),
                }
            )
        )
    records = b"".join(line + b"\n" for line in lines)
    (directory / "records.jsonl").write_bytes(records)
    maker_id, version, digest = _catalog_maker("loom.brick")
    manifest = {
        "profile": "exulanica.texture-dataset/v1",
        "truth": "invented",
        "licence_id": "CC0-1.0",
        "makers": [{"maker_id": maker_id, "version": version, "object_sha256": digest}],
        "image": {"width": SIZE, "height": SIZE, "channels": 3, "layout": "sRGB"},
        "shards": [
            {
                "set_id": "cc0.brick-running-bond",
                "path": "images/cc0.brick-running-bond.rgb",
                "records": count,
                "byte_size": len(pictures),
                "sha256": hashlib.sha256(pictures).hexdigest(),
            }
        ],
        "records": {
            "path": "records.jsonl",
            "count": count,
            "byte_size": len(records),
            "sha256": hashlib.sha256(records).hexdigest(),
        },
    }
    raw = canonical_bytes(manifest)
    (directory / "dataset.json").write_bytes(raw)
    committed = directory.parent / f"{directory.name}-committed.json"
    committed.write_bytes(raw)
    return committed


def test_a_matching_export_is_read_split_and_encoded(tmp_path):
    committed = _export(tmp_path / "export")
    export = verify_export(tmp_path / "export", committed)
    assert len(export.records) == 3
    assert export.picture(export.records[1]) == bytes(range(256))[: SIZE * SIZE * 3]
    parts = [part for part, _ in iter_split(export, held_out_every=2)]
    assert parts == ["held_out", "train", "held_out"]
    layout, manifests = load_layout(export.maker_objects(), OBJECTS)
    maker, scalars, choices = encode(export.records[0].recipe, layout, manifests)
    assert maker == 0 and choices == [0]
    assert all(0.0 <= value <= 1.0 for value in scalars)
    assert len(scalars) == len(layout.makers[0].scalars)


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda d: (d / "images" / "cc0.brick-running-bond.rgb").write_bytes(b"x" * 144), "hash"),
        (lambda d: (d / "records.jsonl").write_bytes(b""), "bytes"),
        (lambda d: (d / "dataset.json").write_bytes(b"{}"), "committed manifest"),
    ],
)
def test_an_export_that_differs_from_its_manifest_is_refused(tmp_path, damage, message):
    committed = _export(tmp_path / "export")
    damage(tmp_path / "export")
    with pytest.raises(ExportRefused, match=message):
        verify_export(tmp_path / "export", committed)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"truth": "observed"}, "invented"),
        ({"licence_id": "LicenseRef-Exulanica-Workspace-Private"}, "CC0-1.0"),
    ],
)
def test_only_invented_published_pictures_are_trained_on(tmp_path, change, message):
    committed = _export(tmp_path / "export")
    manifest = {**json.loads(committed.read_bytes()), **change}
    for path in (committed, tmp_path / "export" / "dataset.json"):
        path.write_bytes(canonical_bytes(manifest))
    with pytest.raises(ExportRefused, match=message):
        verify_export(tmp_path / "export", committed)


def test_verify_needs_no_approval_and_train_refuses_without_one(tmp_path, monkeypatch, capsys):
    committed = _export(tmp_path / "export")
    common = [
        "--dataset",
        str(tmp_path / "export"),
        "--manifest",
        str(committed),
        "--objects",
        str(OBJECTS),
    ]
    assert main(["verify", *common]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == 3
    monkeypatch.delenv(APPROVAL_ENV, raising=False)
    assert main(["train", *common, "--out", str(tmp_path / "run")]) == REFUSED
    assert "refusing to train" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()
