"""The network: a small convolutional encoder and one set of heads per maker.

Deliberately modest. The dataset is invented pictures of eight makers, and the question the first
run answers is whether a picture carries enough of its recipe to be read back at all, not how far
an architecture can be pushed. The encoder halves the picture four times and pools; the heads
predict the maker, each maker's scalars, and each of its choices. Only the true maker's heads are
scored for a record, so a brick never learns from a kerb's controls.
"""

from __future__ import annotations

from itertools import pairwise

import torch
from torch import nn

from exulanica_training.texture_inverse.targets import TargetLayout

__all__ = ["TextureInverse"]


class TextureInverse(nn.Module):
    def __init__(self, layout: TargetLayout, width: int = 32) -> None:
        super().__init__()
        self.layout = layout
        channels = [3, width, width * 2, width * 4, width * 8]
        blocks: list[nn.Module] = []
        for inner, outer in pairwise(channels):
            blocks += [
                nn.Conv2d(inner, outer, kernel_size=3, stride=2, padding=1),
                nn.BatchNorm2d(outer),
                nn.GELU(),
                nn.Conv2d(outer, outer, kernel_size=3, padding=1),
                nn.BatchNorm2d(outer),
                nn.GELU(),
            ]
        self.encoder = nn.Sequential(*blocks, nn.AdaptiveAvgPool2d(1), nn.Flatten())
        features = channels[-1]
        self.maker = nn.Linear(features, len(layout.makers))
        self.scalars = nn.ModuleList(
            nn.Linear(features, len(maker.scalars)) for maker in layout.makers
        )
        self.choices = nn.ModuleList(
            nn.ModuleList(nn.Linear(features, len(options)) for _, options in maker.choices)
            for maker in layout.makers
        )

    def forward(
        self, pictures: torch.Tensor
    ) -> tuple[torch.Tensor, list[torch.Tensor], list[list[torch.Tensor]]]:
        """Maker logits, then per maker its scalars in [0, 1] and its choice logits."""
        features = self.encoder(pictures)
        scalars = [torch.sigmoid(head(features)) for head in self.scalars]
        choices = [[head(features) for head in heads] for heads in self.choices]
        return self.maker(features), scalars, choices
