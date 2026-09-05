"""Real COLMAP rectification with generated test pixels, isolated from torch's OpenMP."""

from __future__ import annotations

import subprocess
import sys


def test_real_colmap_rectification_preserves_pose_and_binds_training_pixels(tmp_path):
    program = r"""
from pathlib import Path
import json, sys
import pycolmap
from PIL import Image
from exulanica.reconstruction.gsplat_runner import prepare_dataset, load_dataset
root = Path(sys.argv[1])
dataset = root / "dataset"
(dataset / "images").mkdir(parents=True)
(dataset / "sparse").mkdir()
output = root / "output"
output.mkdir()
options = pycolmap.SyntheticDatasetOptions(
    num_rigs=1, num_cameras_per_rig=1, num_frames_per_rig=5, num_points3D=40,
    camera_width=96, camera_height=64, camera_params=[80.,48.,32.,0.05],
)
model = pycolmap.synthesize_dataset(options)
model.write(str(dataset / "sparse"))
for index, image in enumerate(model.images.values()):
    path = dataset / "images" / image.name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (96,64), (80+index,140,200)).save(path, format="PNG")
(output / "training/undistorted").mkdir(parents=True)
(output / "training/undistorted/interrupted.txt").write_text("incomplete rectification")
prepared = prepare_dataset(dataset, output)
assert prepared != dataset
views, points = load_dataset(prepared, 5)
assert len(views) == 5 and len(points) == 40
assert sum(v["heldout"] for v in views) == 1
from exulanica.reconstruction.gsplat_runner import _digest_file
chosen = sorted(model.images.values(),key=lambda image: image.name)[-1].name
heldout_hash = _digest_file(dataset / "images" / chosen)
explicit_views, _ = load_dataset(
    prepared, 5, heldout_sources=(heldout_hash,), original_dataset=dataset
)
assert [v["name"] for v in explicit_views if v["heldout"]] == [chosen]
receipt = json.loads((output / "training/dataset.json").read_text())
assert receipt["rectified"] is True
assert len(receipt["images"]) == 5
assert all(len(row["source_sha256"]) == 64 for row in receipt["images"])
assert prepare_dataset(dataset, output) == prepared
# A changed source photo must not silently reuse old rectification or training pixels.
source = dataset / "images" / receipt["images"][0]["name"]
source.write_bytes(b"changed source pixels")
try:
    prepare_dataset(dataset, output)
except ValueError as error:
    assert "source/calibration receipt" in str(error)
else:
    raise AssertionError("changed sources reused stale rectification")
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
