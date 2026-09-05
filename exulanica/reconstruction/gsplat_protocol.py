"""Versioned gsplat runner settings, included in every build identity."""

from typing import Any

GSPLAT_REVISION = "937e29912570c372bed6747a5c9bf85fed877bae"
RUNNER_PROFILE = "exulanica.gsplat-scene-runner/v1"
CHECKPOINT_PROFILE = "exulanica.gsplat-training-checkpoint/v1"
# Changing any value changes the manifest and invalidates old optimizer state.
TRAINING_PROTOCOL: dict[str, Any] = {
    "profile": "exulanica.gsplat-training-protocol/v1",
    "seed": 42,
    "compressor": {
        "package": "@playcanvas/splat-transform",
        "version": "3.3.3",
        "format": "sog-v2",
    },
    "sh_degree": 3,
    "sh_degree_interval": 1000,
    "ssim_weight": 0.2,
    "opacity_regularization": 0.01,
    "scale_regularization": 0.01,
    "means_lr": 0.00016,
    "means_lr_final_factor": 0.01,
    "scales_lr": 0.005,
    "quats_lr": 0.001,
    "opacities_lr": 0.05,
    "sh0_lr": 0.0025,
    "shN_lr": 0.000125,
    "mcmc_noise_lr": 500000.0,
    "mcmc_refine_start": 500,
    "mcmc_refine_stop": 25000,
    "mcmc_refine_every": 100,
    "mcmc_min_opacity": 0.005,
    "image_resolution": "COLMAP-undistorted-no-max-image-size-downsampling",
    "undistortion": {
        "backend": "pycolmap-4.2.0",
        "blank_pixels": 0.0,
        "min_scale": 0.2,
        "max_scale": 2.0,
        "max_image_size": -1,
        "jpeg_quality": 100,
        "interpolation": "bilinear",
    },
    "split": "explicit-original-source-digests-frozen-before-reconstruction",
    "initial_color": "neutral-gray-no-heldout-RGB",
    "geometry_conditioning": "COLMAP-poses-and-sparse-geometry-use-all-registered-images",
    "coordinate_frame": "unchanged-COLMAP-world-camera-x-right-y-down-z-forward",
    "coverage": "mean-heldout-pixel-fraction-alpha-at-least-0.95",
    "floaters": "opacity-weighted-fraction-beyond-5x-median-sparse-neighbor-spacing",
    "floater_metric_limit": (
        "sparse-support-proxy-not-a-human-floater-or-geometry-completeness-score"
    ),
    "lpips": "torchmetrics-alexnet-normalize-true-no-color-correction",
}
