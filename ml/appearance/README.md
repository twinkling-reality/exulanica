# Generated appearance

Status: capture, records and measurement WRITTEN AND TESTED on the operator's Mac; no model has run.
The full account is [docs/generated-appearance.md](../../docs/generated-appearance.md).

Structure is the truth and a model supplies appearance only. This package:

- captures a world's exact structure at a camera (depth, normals, per-pixel surface identity,
  surface coordinates, exact edges), today from the tile runtime bench's test street;
- pins model weights file by file at a Hugging Face revision, with each component's licence held
  to `docs/license-matrix.md` section 6 (`weights/`);
- reads and writes the records that make a model output a data object: weights, structure,
  generation and GPU run, each canonical JSON named by its sha256;
- measures pictures and texture sets against the structure with no model: edge agreement,
  per-surface spread, reprojection flicker along a camera path, seams, repetition, module periods,
  texel pitch and decoded cost.

It is not part of the product. Nothing under `exulanica/` imports `exulanica_appearance` (an import
contract in the root `pyproject.toml`, and `tests/test_training_boundary.py`), and this package
imports nothing from the product. Its base environment has numpy and Pillow only; model libraries
are in the `gpu` extra, which only the GPU container installs.

```sh
cd ml/appearance
uv sync --locked                 # base environment, no torch
.venv/bin/python -m pytest       # every test runs without a GPU or a download

# exact structure of the bench street at its six poses and a 121-frame walk
(cd ../../web && ./node_modules/.bin/tsx ../ml/appearance/capture/export-bench.ts) > bench-geometry.json
.venv/bin/python -m exulanica_appearance capture bench --geometry bench-geometry.json --out OUT

# the procedural look at those cameras (the bench's Vite server must be running), then measure it
node scripts/capture-bench-frames.mjs http://127.0.0.1:5311/ OUT FRAMES
.venv/bin/python -m exulanica_appearance measure frames --structure OUT --frames FRAMES --out frames.json
.venv/bin/python -m exulanica_appearance measure textures --repository ../.. --out textures.json
.venv/bin/python -m exulanica_appearance sheet before --structure OUT --frames FRAMES --out SHEETS

# the whole Track A pipeline with a stub model: staging, verification, tiling, records, measurements
.venv/bin/python -m exulanica_appearance runner dry-run --repository ../.. --out DRY

# a real session: stage on this machine, fetch and run on the rented one, check what came back
.venv/bin/python -m exulanica_appearance runner stage --spec jobs/track-a-smoke.json --repository ../.. --weights weights/ --out STAGED
python3 scripts/fetch-weights.py STAGED WEIGHTS          # on the rented machine's host
container/run.sh IMAGE@sha256:... STAGED WEIGHTS OUT 5670   # no network, read-only, hard time limit
.venv/bin/python -m exulanica_appearance runner check --out OUT

# weights manifests from Hugging Face metadata only (no weights file is fetched)
scripts/fetch-hf-metadata.sh <repo> <40-hex revision> METADATA/<repo>@<revision>
.venv/bin/python -m exulanica_appearance weights build --spec weights/candidates.json --metadata METADATA --out weights/
```

Large outputs (layers, frames, sheets, metadata) live under `.exulanica/appearance/`, which git
ignores. Git holds code, the weights manifests and small `.log.txt` evidence.
