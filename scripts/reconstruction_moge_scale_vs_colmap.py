# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow"]
# ///
"""MoGe-2 metric depth as a scale source for a COLMAP sparse model.

Measures whether MoGe-2's per-image metric depth can supply the metres-per-unit scale that
exulanica/reconstruction/pose.py's manifest currently requires a human to type in. For every
registered image of the COLMAP B8 model (known intrinsics, eight views), for every 2D
observation with a 3D point: depth_colmap = (R x + t).z in COLMAP units and depth_moge = -z of
the MoGe point at the same pixel (OPM frame, metres); their ratio is metres per COLMAP unit.
The estimate is the per-image median, then the median over images, with the median absolute
deviation of the image medians as the spread; it is compared to the ground-truth scale from
the Umeyama alignment of the known camera centres (analysis.json, B8). Also reports coverage
descriptors over the same model (per-point maximum triangulation angle from the tracks, and
azimuth coverage of the cameras around the sparse centroid), because the rung 1 / rung 2
separation is defined over them and an arc capture is the canonical one-sided case. This is
the table in docs/reconstruction-findings.md section 4. Measured on 2026-09-03 with
Ruicheng/moge-2-vitl at 512 px, once with MoGe's own field-of-view estimate and once with the
B8 model's recovered horizontal field of view handed to MoGe as fov_x:

    .venv/bin/python scripts/reconstruction_moge_scale_vs_colmap.py <spike_dir>
    .venv/bin/python scripts/reconstruction_moge_scale_vs_colmap.py <spike_dir> --known-fov

Caveat that governs every number: the inputs are renders of a monocular point map, not
photographs. MoGe is being asked to estimate depth on a picture of its own earlier output. This
measures the estimator mechanism and MoGe's response to a synthetic render; it is not a
measurement of MoGe-2 scale accuracy on photographs.

Inputs: the spike directory, required, holding images/, analysis.json from
reconstruction_pycolmap_analyze.py and runs/B8/sparse/0_text from
reconstruction_pycolmap_run.py. Needs the repository's .venv with the reconstruction extra
(torch, moge) for exulanica.reconstruction.moge, plus numpy and pillow; pycolmap is not needed,
the model is read from its text export. Writes <spike_dir>/moge_scale_vs_colmap.json, or
moge_scale_vs_colmap_knownfov.json with --known-fov, unless --out is given.

Usage:  .venv/bin/python scripts/reconstruction_moge_scale_vs_colmap.py <spike_dir>
            [--known-fov] [--max-edge 512] [--out result.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
# The B8 model's recovered horizontal field of view: mean focal of its single PINHOLE camera
# (cameras.txt: fx 822.868, fy 824.802) on the 1024 px width. Within 0.02 degrees of the true
# 50 degrees vertical at 4:3. Handed to MoGe with --known-fov.
FOV_X_DEG = 2 * math.degrees(math.atan(512.0 / 823.8351906414365))


def parse_args():
    parser = argparse.ArgumentParser(description="Estimate a COLMAP model's metric scale from MoGe-2 depth.")
    parser.add_argument("spike_dir", type=Path, help="directory with images/, analysis.json and runs/B8/sparse/0_text")
    parser.add_argument("--known-fov", action="store_true", help="hand the B8 model's field of view to MoGe as fov_x")
    parser.add_argument("--max-edge", type=int, default=512, help="longest edge MoGe infers at, pixels")
    parser.add_argument("--out", type=Path, default=None, help="result JSON path; default is in the spike directory")
    return parser.parse_args()


def quat_to_R(qw, qx, qy, qz):
    return np.array(
        [
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
        ]
    )


def read_images(path):
    lines = [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
    images = {}
    for i in range(0, len(lines), 2):
        parts = lines[i].split()
        q = [float(v) for v in parts[1:5]]
        t = np.array([float(v) for v in parts[5:8]])
        name = " ".join(parts[9:])
        pts = lines[i + 1].split()
        obs = []
        for j in range(0, len(pts), 3):
            pid = int(pts[j + 2])
            if pid != -1:
                obs.append((float(pts[j]), float(pts[j + 1]), pid))
        images[name] = {"R": quat_to_R(*q), "t": t, "obs": obs}
    return images


def read_points(path):
    pts = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split()
        pid = int(p[0])
        xyz = np.array([float(p[1]), float(p[2]), float(p[3])])
        err = float(p[7])
        track = [(int(p[k]), int(p[k + 1])) for k in range(8, len(p), 2)]
        pts[pid] = {"xyz": xyz, "err": err, "track": track}
    return pts


def main():
    args = parse_args()
    spike = args.spike_dir
    model_dir = spike / "runs" / "B8" / "sparse" / "0_text"
    out_path = args.out or spike / ("moge_scale_vs_colmap_knownfov.json" if args.known_fov else "moge_scale_vs_colmap.json")

    sys.path.insert(0, str(REPO))
    from exulanica.ingest.stages.segmentation import DEPTH_ROLE, local_model_role
    from exulanica.reconstruction.moge import MoGeDepthModel

    pin = local_model_role(DEPTH_ROLE).primary
    t0 = time.monotonic()
    model = MoGeDepthModel(model_id=pin.repo_id, revision=pin.revision, max_edge_px=args.max_edge)
    load_s = time.monotonic() - t0

    images = read_images(model_dir / "images.txt")
    points = read_points(model_dir / "points3D.txt")
    analysis = json.loads((spike / "analysis.json").read_text())
    gt_scale = analysis["B8"]["umeyama_scale_metres_per_colmap_unit"]

    per_image = {}
    all_ratios = []
    infer_s = []
    for name in sorted(images):
        img = Image.open(spike / "images" / name)
        W, H = img.size
        t1 = time.monotonic()
        pred = predict_with_fov(model, img, FOV_X_DEG) if args.known_fov else model.predict(img)
        infer_s.append(time.monotonic() - t1)
        w, h = pred.width, pred.height
        z = np.asarray(pred.points, dtype=np.float64).reshape(h, w, 3)[:, :, 2]
        depth_moge = -z  # OPM frame: -Z forward
        valid = np.frombuffer(pred.valid, dtype=np.uint8).reshape(h, w) != 0
        R, t = images[name]["R"], images[name]["t"]
        ratios = []
        for (x, y, pid) in images[name]["obs"]:
            X = points[pid]["xyz"]
            dc = (R @ X + t)[2]
            if dc <= 0:
                continue
            px = min(w - 1, max(0, round(x * w / W)))
            py = min(h - 1, max(0, round(y * h / H)))
            if not valid[py, px]:
                continue
            dm = depth_moge[py, px]
            if dm <= 0 or not np.isfinite(dm):
                continue
            ratios.append(dm / dc)
        r = np.array(ratios)
        q = np.quantile(r, [0.25, 0.5, 0.75]) if len(r) else [float("nan")] * 3
        per_image[name] = {
            "observations_used": len(r),
            "ratio_p25": float(q[0]),
            "ratio_p50": float(q[1]),
            "ratio_p75": float(q[2]),
            "moge_fov_y_deg": pred.fov_y_degrees,
            "moge_valid_fraction": pred.valid_fraction,
        }
        all_ratios.extend(ratios)

    medians = np.array([v["ratio_p50"] for v in per_image.values()])
    scale_hat = float(np.median(medians))
    pooled = float(np.median(all_ratios))
    spread = float(np.median(np.abs(medians - scale_hat)))

    # Coverage descriptors over the same model.
    centres = {n: -(images[n]["R"].T @ images[n]["t"]) for n in images}
    tracklen = [len(p["track"]) for p in points.values()]
    # image id -> name
    id_to_name = {}
    for line in (model_dir / "images.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            parts = line.split()
            if len(parts) >= 10 and parts[0].isdigit():
                id_to_name[int(parts[0])] = " ".join(parts[9:])
    tri = []
    for p in points.values():
        cams = [centres[id_to_name[i]] for (i, _) in p["track"] if i in id_to_name]
        best = 0.0
        for a in range(len(cams)):
            for b in range(a + 1, len(cams)):
                u = cams[a] - p["xyz"]
                v = cams[b] - p["xyz"]
                c = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-12)
                best = max(best, math.degrees(math.acos(max(-1.0, min(1.0, c)))))
        tri.append(best)
    tri = np.array(tri)
    xyz = np.stack([p["xyz"] for p in points.values()])
    centroid = np.median(xyz, axis=0)
    # azimuth of each camera around the sparse centroid, in the model's horizontal plane
    # (COLMAP y is down, so the horizontal plane is x-z)
    az = []
    for c in centres.values():
        d = c - centroid
        az.append(math.degrees(math.atan2(d[0], d[2])) % 360)
    az = sorted(az)
    # fraction of 360 within 30 deg of some camera
    covered = np.zeros(360, dtype=bool)
    for a in az:
        for k in range(-30, 31):
            covered[int((a + k) % 360)] = True
    azimuth_coverage = float(covered.mean())
    ext = float(
        max(
            np.linalg.norm(centres[a] - centres[b])
            for a in centres
            for b in centres
        )
    )
    middle = list(centres.values())[4]
    med_depth_units = float(np.median([np.linalg.norm(p["xyz"] - middle) for p in points.values()]))

    result = {
        "caveat": "inputs are renders of a monocular point map, not photographs; mechanism test only",
        "model_id": model.model_id,
        "metric_checkpoint": model.metric,
        "max_edge_px": args.max_edge,
        "model_load_s": load_s,
        "inference_s_per_image": infer_s,
        "colmap_model": str(model_dir),
        "ground_truth_metres_per_unit_umeyama": gt_scale,
        "estimate_metres_per_unit_median_of_image_medians": scale_hat,
        "estimate_metres_per_unit_pooled_median": pooled,
        "relative_error_vs_ground_truth": scale_hat / gt_scale - 1,
        "median_abs_deviation_of_image_medians": spread,
        "per_image": per_image,
        "coverage": {
            "points3D": len(points),
            "track_length_p50": float(np.median(tracklen)),
            "max_triangulation_angle_deg_p10": float(np.quantile(tri, 0.10)),
            "max_triangulation_angle_deg_p50": float(np.quantile(tri, 0.50)),
            "max_triangulation_angle_deg_p90": float(np.quantile(tri, 0.90)),
            "fraction_points_max_tri_angle_ge_10deg": float((tri >= 10).mean()),
            "fraction_points_track_ge_3": float((np.array(tracklen) >= 3).mean()),
            "camera_azimuths_deg_about_sparse_centroid": az,
            "azimuth_coverage_within_30deg_fraction": azimuth_coverage,
            "camera_extent_units": ext,
            "median_point_distance_from_middle_camera_units": med_depth_units,
            "baseline_over_depth": ext / med_depth_units,
        },
    }
    out_path.write_text(json.dumps(result, indent=1))
    print(json.dumps({k: v for k, v in result.items() if k != "per_image"}, indent=1))
    for n, v in per_image.items():
        print(n, v)


def predict_with_fov(model, image, fov_x_deg):
    """MoGeDepthModel.predict, with the COLMAP-recovered horizontal FoV handed to MoGe.

    Same downscale, same frame conversion, same mask; the one difference is `fov_x`, which the
    production wrapper does not pass because a single photograph has no independent focal.
    """
    from exulanica.reconstruction.depth import DepthPrediction
    from exulanica.reconstruction.moge import _fit, _fov_y_degrees, _RESOLUTION_LEVEL, to_opm_frame
    torch = model._torch
    rgb = image.convert("RGB")
    width, height = _fit(rgb.size, model._max_edge_px)
    if (width, height) != rgb.size:
        rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)
    tensor = (
        torch.frombuffer(bytearray(rgb.tobytes()), dtype=torch.uint8)
        .reshape(height, width, 3).permute(2, 0, 1).float().div(255).to(model._device)
    )
    with torch.no_grad():
        out = model._model.infer(tensor, resolution_level=_RESOLUTION_LEVEL, use_fp16=False, fov_x=fov_x_deg)
    points = out["points"].detach().to("cpu").flatten().tolist()
    mask = bytes(out["mask"].detach().to("cpu").flatten().to(torch.uint8).tolist())
    return DepthPrediction(width=width, height=height, points=to_opm_frame(points), valid=mask,
                           fov_y_degrees=_fov_y_degrees(out["intrinsics"]), metric=model._metric,
                           model_id=model._model_id)


if __name__ == "__main__":
    main()
