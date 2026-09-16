# Training code

Status: WRITTEN, NOT RUN. Nothing here has trained a model, and nothing may until an operator says
so for a specific run.

This directory holds Exulanica's learned material models. The first one is the texture inverse
model: from a picture of a surface, it proposes a recipe that a published maker can bake. It is not
part of the product:

- **Its own environment.** `ml/pyproject.toml` names torch and numpy. The product's environment
  never installs them for this code, and this project is not locked yet, because resolving and
  installing torch is a download.
- **Its own container.** `ml/container/Dockerfile` takes torch from a PyTorch base pinned by
  digest, and `ml/container/run.sh` runs it with:
  - no network;
  - a read-only root;
  - the export, the committed manifest and the published maker objects mounted read-only;
  - one writable directory.
- **An import wall.** Nothing under `exulanica/` may import `exulanica_training`. The import
  contract in the root `pyproject.toml` holds that over the import graph, and
  `tests/test_training_boundary.py` holds it over the source. The training code imports nothing
  from the product either. It reads files.

## What it trains on

Only the synthetic export that `web/packages/loom-texture` writes from a committed plan
(`docs/texture-package.md`, section 13). `exulanica_training.texture_inverse.export` refuses the
export unless:

- its `dataset.json` is the committed manifest, byte for byte;
- the manifest says `"truth": "invented"` and `"licence_id": "CC0-1.0"`;
- every shard and the records file hash to what the manifest names;
- every record is canonical and in its place.

A workspace's private bakes and a person's photographs are never inputs to this path.

## What a run produces

A run writes the weights, named by their sha256, and a receipt,
`exulanica.texture-inverse-training-run/v1`. The receipt names:

- the export, by the manifest's digest;
- the code, by the digest of this package's source;
- the torch version and the device;
- every setting;
- the operator's approval reference;
- the held-out measurements, as integers in parts per million.

The weights digest is what a photo-derived recipe will name as its model
(`exulanica.materials.photo_derived`). A proposal is only ever a recipe that the published maker's
check accepts, and one read from a person's photographs also waits for the personal model right
(migration 0073).

## Running it

Checking an export needs no torch and no approval:

```sh
PYTHONPATH=ml python -m exulanica_training.texture_inverse verify \
  --dataset .exulanica/datasets/texture/texture-inverse-v1 \
  --manifest web/packages/loom-texture/dataset/manifests/texture-inverse-v1.json \
  --objects assets/textures/objects
```

Training refuses to start unless `EXULANICA_TRAINING_APPROVAL` names the operator's approval of
that run. The intended route is the container:

```sh
ml/container/run.sh IMAGE@sha256:... EXPORT_DIR OUT_DIR "approval reference" --epochs 20
```

The first run is not scheduled. It needs three things:

- an operator's yes to building the image, which downloads it;
- an operator's yes to the GPU time;
- a place to keep the weights and the receipt.

## Tests

The tests run in either environment. The export and target tests need no torch. The model test
makes a forward pass only, and it is skipped where torch is not installed.

```sh
cd ml && python -m pytest
```
