"""The network's shapes, checked with a forward pass and no training step.

Needs torch, which the training environment has; it is skipped, and says why, where torch is not
installed. Nothing here updates a weight: a training run is an operator's decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip(
    "torch", reason="the training environment installs torch; this one did not"
)

from exulanica_training.texture_inverse.model import TextureInverse
from exulanica_training.texture_inverse.targets import load_layout

REPOSITORY = Path(__file__).resolve().parents[2]


def test_every_maker_gets_its_own_heads_and_a_picture_gets_every_prediction():
    catalog = json.loads((REPOSITORY / "assets" / "textures" / "catalog.json").read_bytes())
    makers = [(row["maker_id"], row["version"], row["object_sha256"]) for row in catalog["makers"]]
    layout, _ = load_layout(makers, REPOSITORY / "assets" / "textures" / "objects")
    model = TextureInverse(layout, width=4).eval()
    with torch.no_grad():
        maker_logits, scalars, choices = model(torch.zeros(2, 3, 32, 32))
    assert maker_logits.shape == (2, len(layout.makers))
    for maker, predicted, heads in zip(layout.makers, scalars, choices, strict=True):
        assert predicted.shape == (2, len(maker.scalars))
        assert bool(((predicted >= 0) & (predicted <= 1)).all())
        assert [head.shape[1] for head in heads] == [len(options) for _, options in maker.choices]
