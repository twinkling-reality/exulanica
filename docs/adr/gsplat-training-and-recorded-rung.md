# Gaussian optimization and recorded scene rung are separate decisions

Date: 2026-09-05. Status: accepted for implementation; CUDA execution remains unverified.

The previous standalone controller required a physical metric scale before optimizing any
Gaussians. Gaussian image optimization needs consistent camera/point coordinates but does not
mathematically require metres. Keeping that restriction would prevent honest development of a
nonmetric scene without improving the truth of a later metric or navigation claim.

An accepted pose receipt can therefore authorize optimization in its declared nonmetric coordinate
frame. The controller now verifies the full carried pose manifest, exact original filenames and
source hashes, selected connected model, and entire sparse artifact inventory before execution.
It refuses invalid present scales and unearned joint metric claims. No coordinate normalization
silently replaces that authoritative frame.

`SplatQuality.accepted` is explicitly scoped to held-out image quality and the delivery byte budget.
It authorizes a usable reconstruction substrate; it does not write a rung assertion. The existing
scene gate still composes independently accepted pose, placement, physical scale, coverage, and
splat receipts. A nonmetric accepted Gaussian scene remains rung 3 until those additional gates
pass. Camera movement may be expressed in scene units; it must not imply metres or validated free
navigation.

The held-out split is an explicit original-source digest subset frozen before reconstruction.
Renaming a source or failing to register another view cannot change training membership. Pose
estimation and sparse initialization may condition on all registered image geometry; held-out RGB
is excluded from optimization and initial Gaussian colors. Reports disclose that conditioning.

Regression coverage verifies nonmetric optimization does not imply rung promotion, corrupt or
alternate sparse models are refused, changed source-to-camera names fail, and explicit held-out
identity survives rectification. Existing scene-gate tests continue to enforce independent scale
and coverage requirements. CUDA continuation and visual-quality claims require an actual GPU run.
