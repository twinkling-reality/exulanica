"""Generated pieces enter through the workspace asset admission like any upload.

The generated asset writer lives outside the product (``ml/appearance``) and the product never
imports it. This test imports both: it runs the generated asset route with its stub model, then
hands every piece to the product's own static profile preparation, which must admit it as
placeable, measure it at the size its receipt states, and find its bottom centre already at the
origin, so the preparation's normalise step moves nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

#: The generated asset writer reads and writes meshes with numpy, which arrives with the
#: `reconstruction` extra; a plain `uv sync`, as CI runs, does not install it.
pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)

from exulanica.world import static_glb
from exulanica.world.asset_preparation import decode_texture

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dry_run_pieces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, dict]]:
    monkeypatch.syspath_prepend(str(ROOT / "ml" / "appearance"))
    from exulanica_appearance.assets.dryrun import dry_run

    dry_run(ROOT, tmp_path)
    pieces = []
    for receipt_path in sorted((tmp_path / "receipts").glob("*.json")):
        receipt = json.loads(receipt_path.read_bytes())
        glb = (tmp_path / "pieces" / f"{receipt['output']['sha256']}.glb").read_bytes()
        pieces.append((glb, receipt))
    return pieces


def test_every_generated_piece_is_admitted_placeable_at_its_receipt_s_size(
    dry_run_pieces: list[tuple[bytes, dict]],
) -> None:
    assert len(dry_run_pieces) == 5
    for glb, receipt in dry_run_pieces:
        prepared = static_glb.prepare_static_glb(
            glb,
            unit="metre",
            expected_dimensions_mm=receipt["measured"]["size_mm"],
            decode_image=decode_texture,
        )
        assert prepared.placeable
        assert prepared.dimensions_mm == receipt["measured"]["size_mm"]
        normalize = next(step for step in prepared.steps if step["step"] == "normalize")
        assert normalize["translation_m"] == ["0.0", "0.0", "0.0"]
        assert normalize["scale"] == "1.0"
