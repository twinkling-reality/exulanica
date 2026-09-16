"""``python -m exulanica_training.texture_inverse verify|train``.

``verify`` checks an export against its committed manifest and builds the target layout, with no
torch and no approval: it is how an operator sees what a run would use before deciding anything.

``train`` refuses to start unless ``EXULANICA_TRAINING_APPROVAL`` names the operator's approval
of this run (a ticket, a message, a signed note), and records that reference in the receipt. It
imports torch only after that check, so a machine without torch can still show the refusal.
Nothing here downloads anything; the container recipe brings torch, and building it is itself a
step an operator approves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from exulanica_training.texture_inverse.export import verify_export
from exulanica_training.texture_inverse.targets import load_layout

APPROVAL_ENV = "EXULANICA_TRAINING_APPROVAL"
REFUSED = 3


def _verify(args: argparse.Namespace) -> int:
    export = verify_export(args.dataset, args.manifest)
    layout, _ = load_layout(export.maker_objects(), args.objects)
    print(
        json.dumps(
            {
                "manifest_sha256": export.manifest_sha256,
                "records": len(export.records),
                "image_size": export.image_size,
                "makers": [
                    {
                        "maker_id": maker.maker_id,
                        "version": maker.version,
                        "scalars": len(maker.scalars),
                        "choices": len(maker.choices),
                    }
                    for maker in layout.makers
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exulanica_training.texture_inverse")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "train"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--objects", type=Path, required=True)
        if name == "train":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--epochs", type=int, default=20)
            command.add_argument("--batch-size", type=int, default=64)
            command.add_argument("--learning-rate-ppm", type=int, default=1000)
            command.add_argument("--width", type=int, default=32)
            command.add_argument("--seed", type=int, default=20260916)
            command.add_argument("--held-out-every", type=int, default=10)
            command.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    if args.command == "verify":
        return _verify(args)
    approval = os.environ.get(APPROVAL_ENV, "").strip()
    if not approval:
        print(
            f"refusing to train: {APPROVAL_ENV} does not name an operator's approval of this run. "
            "Nothing trains, and no GPU time is spent, without one.",
            file=sys.stderr,
        )
        return REFUSED
    from exulanica_training.texture_inverse.train import train

    receipt = train(args, approval=approval)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
