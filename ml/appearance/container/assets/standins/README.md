# Stand-ins for the generated asset job

Modules the pinned upstream code imports at module level but the job never uses, put first on the
job's `PYTHONPATH` so the real packages are neither installed nor imported. Each one either does the
one thing the job's path needs or refuses loudly if anything calls it.

| Module | Upstream licence | Why it is stood in | What the stand-in does |
| --- | --- | --- | --- |
| `plyfile` | GPL-3.0-or-later | TRELLIS's Gaussian class imports it to save PLY files | Refuses on any use |
| `easydict` | LGPL-3.0 | TRELLIS imports `EasyDict`, a dict with attribute access | A dict with attribute access |
| `pymeshlab` | GPL-3.0 | Step1X-3D's pipeline utilities import it for face reduction and name `MeshSet` in an annotation | Each name is a class that may be named; making or calling one refuses; the post-process simplifies |
| `rembg` | MIT | Both pipelines import it; the cut-out comes from BiRefNet | Refuses on any use |
| `kaolin.utils.testing` | Apache-2.0 | FlexiCubes imports `check_tensor` for one shape assertion | The same assertion |
| `pytorch_lightning.utilities.rank_zero` | Apache-2.0 | Step1X-3D's package imports its logging helpers | Logging helpers |
