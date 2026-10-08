"""TRELLIS's second stage on a given structure, held to a stand-in pipeline and a stand-in torch.

The steps and their order are run()'s at the pinned commit without its first stage; the structure is
checked before anything is sampled, each check refused alone against a positive control; and a
pipeline whose methods are not the pinned ones is refused by name before any weights load.
"""

from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import pytest
from exulanica_pieces.canonical import Refused

from exulanica_appearance.assets.backends.trellis import (
    PIPELINE_SIGNATURES,
    STRUCTURE_RESOLUTION,
    check_coords,
    check_pipeline,
    second_stage,
)


def _coords(rows: list[tuple[int, int, int, int]]) -> np.ndarray:
    return np.asarray(rows, dtype=np.int32)


GOOD = _coords([(0, 0, 0, 0), (0, 1, 2, 3), (0, 63, 63, 63)])


class _Tensor:
    def __init__(self, array: np.ndarray, device: str = "cpu") -> None:
        self.array, self.device = array, device

    def to(self, device: str) -> _Tensor:
        return _Tensor(self.array, device)


class _Torch:
    """The calls the second stage makes of torch, recorded in order."""

    def __init__(self, calls: list) -> None:
        self.calls = calls

    @contextmanager
    def no_grad(self):
        self.calls.append(("no_grad", "enter"))
        yield
        self.calls.append(("no_grad", "exit"))

    def manual_seed(self, seed: int) -> None:
        self.calls.append(("manual_seed", seed))

    def from_numpy(self, array: np.ndarray) -> _Tensor:
        self.calls.append(("from_numpy", array.dtype.name, array.shape))
        return _Tensor(array)


class _Pipeline:
    """A pipeline with TRELLIS's method names and parameters, recording each call."""

    device = "cuda"

    def __init__(self, calls: list) -> None:
        self.calls = calls

    def preprocess_image(self, input):
        self.calls.append(("preprocess_image", input))
        return f"prepared {input}"

    def get_cond(self, image):
        self.calls.append(("get_cond", tuple(image)))
        return {"cond": "c", "neg_cond": "n"}

    def sample_slat(self, cond, coords, sampler_params={}):  # noqa: B006 - TRELLIS's own default
        self.calls.append(("sample_slat", cond, coords.device, coords.array.shape, sampler_params))
        return "slat"

    def decode_slat(self, slat, formats=["mesh", "gaussian", "radiance_field"]):  # noqa: B006
        self.calls.append(("decode_slat", slat, tuple(formats)))
        return {"mesh": ["m"], "gaussian": ["g"]}


def test_the_second_stage_runs_run_s_steps_in_its_order_without_the_first_stage():
    calls: list = []
    outputs = second_stage(_Pipeline(calls), _Torch(calls), "cut-out", 1234, GOOD)
    assert outputs == {"mesh": ["m"], "gaussian": ["g"]}
    assert calls == [
        ("no_grad", "enter"),
        ("preprocess_image", "cut-out"),
        ("get_cond", ("prepared cut-out",)),
        # Seeded after the picture is encoded and before the latent is sampled, as run() does.
        ("manual_seed", 1234),
        ("from_numpy", "int32", (3, 4)),
        # On the pipeline's device, with the pipeline's own sampler settings.
        ("sample_slat", {"cond": "c", "neg_cond": "n"}, "cuda", (3, 4), {}),
        ("decode_slat", "slat", ("mesh", "gaussian")),
        ("no_grad", "exit"),
    ]


@pytest.mark.parametrize(
    ("coords", "words"),
    [
        (GOOD.astype(np.int64), "int32"),
        (GOOD.tolist(), "int32"),
        (GOOD[:, 1:].copy(), "rows of batch index"),
        (np.zeros((0, 4), dtype=np.int32), "at least one voxel"),
        (_coords([(0, 1, 1, 1), (1, 1, 1, 2)]), "one object"),
        (_coords([(0, 1, 1, 1), (0, -1, 1, 1)]), "from 0 to 63"),
        (_coords([(0, 1, 1, 1), (0, 1, STRUCTURE_RESOLUTION, 1)]), "from 0 to 63"),
        (_coords([(0, 1, 1, 1), (0, 1, 1, 1)]), "each voxel once"),
    ],
)
def test_a_structure_the_second_stage_cannot_take_is_refused_before_anything_runs(coords, words):
    check_coords(GOOD)
    calls: list = []
    with pytest.raises(Refused, match=words):
        second_stage(_Pipeline(calls), _Torch(calls), "cut-out", 1, coords)
    assert calls == []


def test_the_pinned_pipeline_s_methods_pass_and_a_changed_one_is_refused_by_name():
    check_pipeline(_Pipeline)
    assert set(PIPELINE_SIGNATURES) == {
        "preprocess_image",
        "get_cond",
        "sample_slat",
        "decode_slat",
    }

    class Renamed(_Pipeline):
        def sample_slat(self, cond, structure, sampler_params={}):  # noqa: B006
            return "slat"

    class Missing:
        pass

    with pytest.raises(Refused, match=r"sample_slat takes \(self, cond, structure"):
        check_pipeline(Renamed)
    with pytest.raises(Refused, match="no method preprocess_image"):
        check_pipeline(Missing)
