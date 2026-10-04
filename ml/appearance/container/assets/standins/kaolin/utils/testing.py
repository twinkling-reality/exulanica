"""Stand-in for kaolin.utils.testing.check_tensor, the one function FlexiCubes imports."""

from typing import Any


def check_tensor(
    tensor: Any, shape: Any = None, dtype: Any = None, device: Any = None, throw: bool = True
) -> bool:
    """True when ``tensor`` has the shape (None matches any size), dtype and device asked for."""
    problems = []
    if shape is not None and (
        len(shape) != tensor.ndim
        or any(s is not None and s != t for s, t in zip(shape, tensor.shape, strict=True))
    ):
        problems.append(f"shape {tuple(tensor.shape)} is not {tuple(shape)}")
    if dtype is not None and tensor.dtype != dtype:
        problems.append(f"dtype {tensor.dtype} is not {dtype}")
    if device is not None and tensor.device != device:
        problems.append(f"device {tensor.device} is not {device}")
    if problems and throw:
        raise ValueError("; ".join(problems))
    return not problems
