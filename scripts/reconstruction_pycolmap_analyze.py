# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pycolmap"]
# ///
"""Summarise every pycolmap run in a spike directory against its ground truth.

For each <spike_dir>/runs/<tag> written by reconstruction_pycolmap_run.py: registered images,
points, mean reprojection error and stage times; alignment-free pairwise relative rotation and
baseline-direction errors; a rotation-informed similarity (rotation from the chordal mean of
the per-image rotations, then scale and translation from the centres) with its centre
residuals; and the Umeyama numbers carried over from the run. Then loads
exulanica/reconstruction/pose.py unmodified from this repository and checks its private parsers
and quality function against pycolmap's own text export of the A8 and B8 models. Writes
<spike_dir>/analysis.json and prints one row per run followed by the two parser checks. This is
the summary behind the table in docs/reconstruction-findings.md section 3 and the two facts
about pose.py stated below it. Measured on 2026-09-02 with pycolmap 4.2.0:

    python scripts/reconstruction_pycolmap_analyze.py <spike_dir>

Caveat that governs every number: the runs are on renders of a monocular point map, not
photographs, so the accuracy figures are upper bounds; the runtimes, the API and the file
format are real measurements.

Inputs: the spike directory, required (ground_truth.json, images/, runs/). pose.py is read
from the repository root this script lives in. Needs numpy and pycolmap in the interpreter.

Usage:  python scripts/reconstruction_pycolmap_analyze.py <spike_dir>
"""
import hashlib
import importlib.util
import json
import sys
import traceback
from pathlib import Path

import numpy as np
import pycolmap

REPO = Path(__file__).resolve().parents[1]
POSE_PY = REPO / 'exulanica' / 'reconstruction' / 'pose.py'


def angle_deg(Ra, Rb):
    return float(np.degrees(np.arccos(np.clip((np.trace(Ra.T @ Rb) - 1) / 2, -1, 1))))


def chordal_mean_rotation(Rs):
    M = sum(Rs)
    U, _, Vt = np.linalg.svd(M)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    return R


def load_pose_module():
    spec = importlib.util.spec_from_file_location('exulanica_pose', POSE_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def analyze_run(run_dir, gt_by_name):
    with open(run_dir / 'result.json') as fh:
        res = json.load(fh)
    out = {'tag': res['tag'], 'n_images': res['n_images'], 'config': res['config'],
           'init_min_tri_angle': res.get('init_min_tri_angle'),
           'stages_s': {k: v['seconds'] for k, v in res['stages'].items()},
           'model_count': res.get('model_count', 0),
           'db': res.get('database', {})}
    if not res.get('models'):
        out['registered'] = 0
        return out, res
    best = res['best_model']
    rec = pycolmap.Reconstruction(str(run_dir / 'sparse' / str(best)))
    names, est_C, est_Rwc, gt_C, gt_Rwc = [], [], [], [], []
    for img in rec.images.values():
        if not img.has_pose:
            continue
        pose = img.cam_from_world
        if callable(pose):
            pose = pose()
        names.append(img.name)
        est_Rwc.append(np.asarray(pose.rotation.matrix()).T)
        est_C.append(np.asarray(img.projection_center()))
        gt_Rwc.append(np.array(gt_by_name[img.name]['R_wc']))
        gt_C.append(np.array(gt_by_name[img.name]['C']))
    est_C, gt_C = np.array(est_C), np.array(gt_C)
    n = len(names)
    out['registered'] = n
    out['points3D'] = rec.num_points3D()
    out['mean_reproj_px'] = rec.compute_mean_reprojection_error()
    out['mean_track_length'] = rec.compute_mean_track_length()
    out['num_cameras_in_model'] = rec.num_cameras()
    out['focal_px'] = [float(c.mean_focal_length()) for c in rec.cameras.values()]

    # alignment-free: pairwise relative rotation error and pairwise baseline-direction error
    rel_rot, rel_dir = [], []
    for i in range(n):
        for j in range(i + 1, n):
            Rr_e = est_Rwc[i].T @ est_Rwc[j]
            Rr_g = gt_Rwc[i].T @ gt_Rwc[j]
            rel_rot.append(angle_deg(Rr_e, Rr_g))
            be = est_Rwc[i].T @ (est_C[j] - est_C[i])
            bg = gt_Rwc[i].T @ (gt_C[j] - gt_C[i])
            be, bg = be / np.linalg.norm(be), bg / np.linalg.norm(bg)
            rel_dir.append(float(np.degrees(np.arccos(np.clip(be @ bg, -1, 1)))))
    out['pairwise_relative_rotation_error_deg_mean'] = float(np.mean(rel_rot))
    out['pairwise_relative_rotation_error_deg_max'] = float(np.max(rel_rot))
    out['pairwise_baseline_direction_error_deg_mean'] = float(np.mean(rel_dir))
    out['pairwise_baseline_direction_error_deg_max'] = float(np.max(rel_dir))

    # rotation-informed similarity: R_align from rotations, then s and t from centres
    R_align = chordal_mean_rotation([g @ e.T for g, e in zip(gt_Rwc, est_Rwc, strict=True)])
    rot_err_aligned = [angle_deg(R_align @ e, g) for g, e in zip(gt_Rwc, est_Rwc, strict=True)]
    out['rot_error_after_rotation_alignment_deg_mean'] = float(np.mean(rot_err_aligned))
    out['rot_error_after_rotation_alignment_deg_max'] = float(np.max(rot_err_aligned))
    if n >= 2:
        rot_est = (R_align @ est_C.T).T
        mu_e, mu_g = rot_est.mean(0), gt_C.mean(0)
        xe, xg = rot_est - mu_e, gt_C - mu_g
        s = float((xe * xg).sum() / (xe ** 2).sum())
        t = mu_g - s * mu_e
        resid = np.linalg.norm(s * rot_est + t - gt_C, axis=1)
        out['scale_from_rotation_aligned_fit'] = s
        out['rms_centre_residual_rotation_aligned_m'] = float(np.sqrt((resid ** 2).mean()))
        out['max_centre_residual_rotation_aligned_m'] = float(resid.max())
    # carry over the Umeyama numbers from the run
    a = res.get('alignment', {})
    for k in ('scale_metres_per_colmap_unit', 'rms_centre_residual_m', 'max_centre_residual_m',
              'mean_rotation_error_deg', 'max_rotation_error_deg', 'relative_rotation_error_deg',
              'baseline_direction_error_deg', 'gt_baseline_extent_m'):
        if k in a:
            out['umeyama_' + k] = a[k]
    out['registered_names'] = names
    return out, res


def parser_check(spike, run_dir, res):
    """Call exulanica/reconstruction/pose.py's private parsers on pycolmap's text export."""
    pose = load_pose_module()
    # The run wrote its text export to sparse/<best>_text; derive it from the run directory
    # rather than trusting the absolute path recorded in result.json, so a moved spike works.
    text_dir = run_dir / 'sparse' / f"{res['best_model']}_text"
    check = {'text_dir': str(text_dir)}
    images = pose._images(text_dir / 'images.txt')
    check['parser_images_count'] = len(images)
    mean_err = pose._mean_error(text_dir / 'points3D.txt')
    check['parser_mean_error_px'] = mean_err
    rec = pycolmap.Reconstruction(str(run_dir / 'sparse' / str(res['best_model'])))
    check['pycolmap_mean_error_px'] = rec.compute_mean_reprojection_error()
    diffs = []
    for img in rec.images.values():
        c_parser = np.array(images[img.name])
        c_py = np.asarray(img.projection_center())
        diffs.append(float(np.linalg.norm(c_parser - c_py)))
    check['max_centre_diff_parser_vs_pycolmap_units'] = max(diffs)
    check['translation_extent_units'] = pose._translation_extent(images)

    # full _quality() call on a sparse-like directory laid out as the parser expects
    # (sparse/<model>/images.txt + points3D.txt); pycolmap wrote them into sparse/<best>_text
    frames = []
    for name in res['image_names']:
        digest = hashlib.sha256((spike / 'images' / name).read_bytes()).hexdigest()
        frames.append(pose.SourceFrame(capture_ref=name, filename=name, sha256=digest, capture_set='synthetic'))
    manifest = pose.PoseBuildManifest(
        scene_ref='glasshouse-courtyard-synthetic',
        code_revision='0' * 40,
        colmap_version=f'pycolmap {pycolmap.__version__}',
        execution_image='local@sha256:' + '0' * 64,
        frames=tuple(frames),
        min_registered_fraction=1.0,
        max_mean_reprojection_error_px=1.0,
        min_camera_translation_units=0.5,
    )
    quality = pose._quality(manifest, run_dir / 'sparse')
    check['quality'] = quality.as_payload()
    check['quality']['artifact_inventory'] = f"{len(check['quality']['artifact_inventory'])} files"
    return check


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: reconstruction_pycolmap_analyze.py <spike_dir>')
    spike = Path(sys.argv[1])
    with open(spike / 'ground_truth.json') as fh:
        gt = json.load(fh)
    gt_by_name = {v['name']: v for v in gt['views']}

    runs = sorted(p for p in (spike / 'runs').iterdir() if (p / 'result.json').exists())
    rows, details = [], {}
    for run_dir in runs:
        out, _ = analyze_run(run_dir, gt_by_name)
        details[out['tag']] = out
        rows.append(out)
    with open(spike / 'analysis.json', 'w') as fh:
        json.dump(details, fh, indent=1)

    cols = ['tag', 'n_images', 'registered', 'model_count', 'points3D', 'mean_reproj_px',
            'stages_s', 'umeyama_scale_metres_per_colmap_unit', 'umeyama_rms_centre_residual_m',
            'umeyama_mean_rotation_error_deg', 'pairwise_relative_rotation_error_deg_mean',
            'pairwise_baseline_direction_error_deg_mean', 'rot_error_after_rotation_alignment_deg_mean',
            'rms_centre_residual_rotation_aligned_m', 'focal_px']
    for r in rows:
        line = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, float):
                v = f'{v:.4g}'
            elif isinstance(v, dict):
                v = ' '.join(f'{k.split("_")[0][:5]}={x:.2f}' for k, x in v.items())
            elif isinstance(v, list):
                v = f'{min(v):.1f}..{max(v):.1f}' if v and isinstance(v[0], float) else str(v)
            line.append(str(v))
        print(' | '.join(line))

    print('\n=== parser check on A8 and B8 text exports')
    for tag in ('A8', 'B8'):
        with open(spike / 'runs' / tag / 'result.json') as fh:
            res = json.load(fh)
        try:
            check = parser_check(spike, spike / 'runs' / tag, res)
            print(tag, json.dumps(check, indent=1))
        except Exception as exc:
            print(tag, 'PARSER CHECK FAILED', repr(exc))
            traceback.print_exc()


if __name__ == '__main__':
    main()
