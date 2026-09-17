"""One training run, and the receipt that says exactly what it was.

The run reads a verified export, builds the target layout from the makers' manifests, and trains
:class:`~exulanica_training.texture_inverse.model.TextureInverse` with a fixed seed and
deterministic kernels where torch offers them. Records are split by number, one in
``held_out_every`` held out, so the split is the same on every machine.

The receipt (``exulanica.texture-inverse-training-run/v1``) names the export by its manifest's
digest, the code by the digest of this package's source, the torch version and device, every
setting, the operator's approval reference, the held-out measurements as integers in parts per
million, and the weights by the sha256 of the file written beside it. That digest pins the model:
a photo-derived recipe will name it as the revision ``sha256:<digest>`` once the personal model
right accepts that form. So the receipt is written last, and only after the weights are on disk.
"""

from __future__ import annotations

import hashlib
import io
import random
from argparse import Namespace
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from exulanica_training.texture_inverse.export import (
    Record,
    VerifiedExport,
    canonical_bytes,
    iter_split,
    verify_export,
)
from exulanica_training.texture_inverse.model import TextureInverse
from exulanica_training.texture_inverse.targets import TargetLayout, encode, load_layout

__all__ = ["RUN_PROFILE", "source_sha256", "train"]

RUN_PROFILE = "exulanica.texture-inverse-training-run/v1"
_PACKAGE = Path(__file__).resolve().parent


def source_sha256() -> str:
    """The digest of this package's Python source, file by file, in path order."""
    files = [
        {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(_PACKAGE.glob("*.py"))
    ]
    return hashlib.sha256(canonical_bytes({"files": files})).hexdigest()


class _Pairs(torch.utils.data.Dataset):
    def __init__(
        self,
        export: VerifiedExport,
        records: list[Record],
        layout: TargetLayout,
        manifests: dict[Any, Any],
    ) -> None:
        self.export = export
        self.records = records
        self.targets = [encode(record.recipe, layout, manifests) for record in records]

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, position: int) -> tuple[torch.Tensor, int, torch.Tensor, list[int]]:
        size = self.export.image_size
        raw = np.frombuffer(self.export.picture(self.records[position]), dtype=np.uint8)
        picture = torch.from_numpy(raw.reshape(size, size, 3).copy()).permute(2, 0, 1)
        maker, scalars, choices = self.targets[position]
        return picture.float() / 255.0, maker, torch.tensor(scalars), choices


def _collate(batch: list[tuple[torch.Tensor, int, torch.Tensor, list[int]]]) -> list[Any]:
    return [
        torch.stack([item[0] for item in batch]),
        torch.tensor([item[1] for item in batch]),
        [item[2] for item in batch],
        [item[3] for item in batch],
    ]


def _loss(
    outputs: tuple[torch.Tensor, list[torch.Tensor], list[list[torch.Tensor]]],
    makers: torch.Tensor,
    scalars: list[torch.Tensor],
    choices: list[list[int]],
) -> tuple[torch.Tensor, torch.Tensor]:
    maker_logits, predicted_scalars, predicted_choices = outputs
    total = nn.functional.cross_entropy(maker_logits, makers)
    absolute = torch.zeros((), device=maker_logits.device)
    for row, maker in enumerate(makers.tolist()):
        target = scalars[row].to(maker_logits.device)
        predicted = predicted_scalars[maker][row]
        total = total + nn.functional.mse_loss(predicted, target) / len(makers)
        absolute = absolute + (predicted - target).abs().mean()
        for head, index in zip(predicted_choices[maker], choices[row], strict=True):
            total = total + nn.functional.cross_entropy(
                head[row : row + 1], torch.tensor([index], device=maker_logits.device)
            ) / len(makers)
    return total, absolute


def _seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def train(args: Namespace, *, approval: str) -> dict[str, Any]:
    export = verify_export(args.dataset, args.manifest)
    layout, manifests = load_layout(export.maker_objects(), args.objects)
    _seed(args.seed)
    split: dict[str, list[Record]] = {"train": [], "held_out": []}
    for part, record in iter_split(export, held_out_every=args.held_out_every):
        split[part].append(record)
    device = torch.device(args.device)
    model = TextureInverse(layout, width=args.width).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.learning_rate_ppm / 1_000_000)
    generator = torch.Generator().manual_seed(args.seed)
    loaders = {
        part: torch.utils.data.DataLoader(
            _Pairs(export, records, layout, manifests),
            batch_size=args.batch_size,
            shuffle=part == "train",
            generator=generator if part == "train" else None,
            collate_fn=_collate,
        )
        for part, records in split.items()
    }
    history: list[dict[str, int]] = []
    for epoch in range(args.epochs):
        model.train()
        for pictures, makers, scalars, choices in loaders["train"]:
            optimiser.zero_grad()
            loss, _ = _loss(model(pictures.to(device)), makers.to(device), scalars, choices)
            loss.backward()
            optimiser.step()
        model.eval()
        correct = seen = 0
        absolute = 0.0
        with torch.no_grad():
            for pictures, makers, scalars, choices in loaders["held_out"]:
                outputs = model(pictures.to(device))
                _, error = _loss(outputs, makers.to(device), scalars, choices)
                correct += int((outputs[0].argmax(dim=1).cpu() == makers).sum())
                seen += len(makers)
                absolute += float(error)
        history.append(
            {
                "epoch": epoch + 1,
                "held_out_maker_accuracy_ppm": round(1_000_000 * correct / max(seen, 1)),
                "held_out_scalar_error_ppm": round(1_000_000 * absolute / max(seen, 1)),
            }
        )
    args.out.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    weights = buffer.getvalue()
    weights_sha256 = hashlib.sha256(weights).hexdigest()
    (args.out / f"{weights_sha256}.pt").write_bytes(weights)
    receipt = {
        "profile": RUN_PROFILE,
        "model": {"id": "exulanica.texture-inverse/v1", "weights_sha256": weights_sha256},
        "dataset_manifest_sha256": export.manifest_sha256,
        "code_sha256": source_sha256(),
        "runtime": {"torch": torch.__version__, "device": str(device)},
        "settings": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate_ppm": args.learning_rate_ppm,
            "width": args.width,
            "seed": args.seed,
            "held_out_every": args.held_out_every,
        },
        "records": {"train": len(split["train"]), "held_out": len(split["held_out"])},
        "approval": approval,
        "history": history,
    }
    (args.out / "receipt.json").write_bytes(canonical_bytes(receipt))
    return receipt
