"""The held-out comparison tool trusts only bytes the bundle's own inventory vouches for."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "heldout_comparisons.py"
spec = importlib.util.spec_from_file_location("heldout_comparisons", MODULE)
assert spec is not None and spec.loader is not None
heldout_comparisons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heldout_comparisons)


def _png(color: tuple[int, int, int], size=(40, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpg(color: tuple[int, int, int], size=(40, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _bundle(path: Path, *, corrupt_render: bool = False) -> None:
    render = _png((200, 40, 40))
    reference = _jpg((40, 200, 40))
    files = {
        "heldout/view-00000.png": render,
        "training/undistorted/images/000000.jpg": reference,
    }
    metrics = {
        "profile": "exulanica.gsplat-heldout-metrics/v1",
        "manifest_digest": "m" * 64,
        "dataset_digest": "d" * 64,
        "psnr": 25.0,
        "ssim": 0.9,
        "lpips": 0.3,
        "coverage_fraction": 0.98,
        "floaters_fraction": 0.4,
        "heldout_views": 1,
        "per_view": [
            {
                "render": "heldout/view-00000.png",
                "render_sha256": hashlib.sha256(render).hexdigest(),
                "source_name": "000000.jpg",
                "source_sha256": "s" * 64,
                "psnr": 25.0,
                "ssim": 0.9,
                "lpips": 0.3,
                "coverage_fraction": 0.98,
                "width": 40,
                "height": 30,
            }
        ],
    }
    files["metrics.json"] = json.dumps(metrics).encode()
    inventory = {
        "files": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
            for name, data in sorted(files.items())
        ]
    }
    if corrupt_render:
        files["heldout/view-00000.png"] = _png((0, 0, 0))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("inventory.json", json.dumps(inventory))
        for name, data in files.items():
            archive.writestr(name, data)


def test_each_comparison_binds_the_render_reference_and_scores_it_shows(tmp_path):
    bundle = tmp_path / "bundle.zip"
    _bundle(bundle)
    output = tmp_path / "out"

    summary = heldout_comparisons.compose_bundle(bundle, output, max_width=200)

    comparison = output / "view-00000-photograph-vs-render.jpg"
    assert comparison.is_file()
    with Image.open(comparison) as image:
        assert image.width == 200
        assert image.height > 30
    assert summary["bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    [entry] = summary["comparisons"]
    assert entry["comparison_sha256"] == hashlib.sha256(comparison.read_bytes()).hexdigest()
    assert entry["render_sha256"] == hashlib.sha256(_png((200, 40, 40))).hexdigest()
    assert entry["scores"] == {"psnr": 25.0, "ssim": 0.9, "lpips": 0.3, "coverage_fraction": 0.98}
    assert json.loads((output / "comparisons.json").read_text()) == summary
    assert "no physical scale" in summary["claim"]


def test_a_render_that_differs_from_the_inventory_is_refused_not_drawn(tmp_path):
    bundle = tmp_path / "bundle.zip"
    _bundle(bundle, corrupt_render=True)

    with pytest.raises(heldout_comparisons.BundleIntegrityError, match="inventory digest"):
        heldout_comparisons.compose_bundle(bundle, tmp_path / "out", max_width=200)
    assert not (tmp_path / "out" / "view-00000-photograph-vs-render.jpg").exists()


def test_the_command_line_names_the_bundle_it_read(tmp_path, capsys):
    bundle = tmp_path / "bundle.zip"
    _bundle(bundle)

    assert (
        heldout_comparisons.main(
            ["--bundle", str(bundle), "--output", str(tmp_path / "out"), "--max-width", "200"]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "view-00000-photograph-vs-render.jpg" in out
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() in out
