"""Route C on the rented machine: the concept picture follows the plan's sketch; the rest is route A.

The concept is Z-Image with the Fun union control 2.1, through VideoX-Fun at Track A's pinned
commit, with Track A's candidate a2 settings (25 steps, guidance 4.0, control scale 0.9, a single
space as the negative words, 1,024 pixels square). It draws one picture: no roll between steps and
no wrap at the edges, since a creature is a figure in a frame, not a tile. The cut-out (BiRefNet)
and the simplifier are route A's own backend. The mesh is TRELLIS-image-large's second stage alone
(its attention through PyTorch's), on the sketch's own surface voxels: the 3D model details and
paints the plan's body from the cut-out rather than inferring a body from one picture. Every model
loads on its first use. Imported only on the rented machine.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Final

import numpy as np
from exulanica_pieces.geometry.mesh import Simplifier

__all__ = ["CONCEPT_SAMPLER", "RouteCBackend", "place_videox"]

#: Track A's candidate a2, drawing one figure rather than a tile.
CONCEPT_SAMPLER: Final = {
    "control_context_scale_milli": 900,
    "guidance_milli": 4000,
    "height": 1024,
    "name": "flow-match-euler",
    "negative_prompt": " ",
    "steps": 25,
    "width": 1024,
    "wrap_margin_px": 0,
}
_BASE: Final = "Tongyi-MAI__Z-Image"
_CONTROL: Final = "alibaba-pai__Z-Image-Fun-Controlnet-Union-2.1"


def place_videox(code: Path, upstream: Path) -> str:
    """Put the fetched VideoX-Fun tree where its backend reads it, with the commit it was held to;
    returns that commit."""
    from exulanica_appearance.runner.backends.videox import VIDEOX_FUN_ROOT

    sources = json.loads((code / "ml/appearance/container/assets/upstream.json").read_bytes())
    [source] = [item for item in sources["sources"] if item["name"] == "videox-fun"]
    tree = upstream / "videox-fun"
    (tree / "COMMIT").write_text(f"{source['commit']}\n", encoding="ascii")
    if not VIDEOX_FUN_ROOT.exists():
        VIDEOX_FUN_ROOT.symlink_to(tree, target_is_directory=True)
    return str(source["commit"])


class RouteCBackend:
    route = "C"

    def __init__(self, weights: Path) -> None:
        from exulanica_appearance.assets.backends.trellis import TrellisBackend

        self._weights = weights
        self._route_a = TrellisBackend(weights)
        self._figure: Any = None

    def _concept_model(self) -> Any:
        if self._figure is None:
            from exulanica_appearance.runner.backends.videox import ZImageFunControl

            class Figure(ZImageFunControl):
                name = "videox-zimage-fun-control-figure"

                def _shift(self) -> tuple[int, int]:
                    # One picture, not a tile: the latents are never rolled.
                    self.step += 1
                    return 0, 0

            self._figure = Figure(
                {"id": "a2", "sampler": dict(CONCEPT_SAMPLER)},
                {"base": self._weights / _BASE, "control": self._weights / _CONTROL},
            )
        return self._figure

    def simplifier(self) -> Simplifier:
        return self._route_a.simplifier()

    def concept(self, prompt: str, control: np.ndarray, seed: int) -> bytes:
        from PIL import Image

        picture = self._concept_model().generate(
            prompt=prompt, conditioning=control, seed=seed, sampler=CONCEPT_SAMPLER
        )
        buffer = io.BytesIO()
        Image.fromarray(picture).save(buffer, format="PNG")
        return buffer.getvalue()

    def cutout(self, picture: bytes) -> bytes:
        return self._route_a.cutout(picture)

    def mesh(self, cutout: bytes, seed: int, sketch: np.ndarray) -> Any:
        from exulanica_appearance.creatures.geometry import trellis_structure

        voxels = trellis_structure(sketch)
        coords = np.concatenate([np.zeros((len(voxels), 1), dtype=np.int32), voxels], axis=1)
        return self._route_a.mesh_on(cutout, seed, coords)

    def runtime(self) -> dict[str, Any]:
        from exulanica_appearance.runner.backends.videox import VIDEOX_FUN_ROOT

        commit = (VIDEOX_FUN_ROOT / "COMMIT").read_text(encoding="ascii").strip()
        return dict(
            self._route_a.runtime(),
            concept={
                "backend": "videox-zimage-fun-control-figure",
                "base": _BASE,
                "control": _CONTROL,
                "sampler": dict(CONCEPT_SAMPLER),
                "videox_fun": commit,
            },
        )
