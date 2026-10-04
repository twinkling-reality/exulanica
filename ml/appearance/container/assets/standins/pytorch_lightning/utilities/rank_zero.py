"""Stand-in for pytorch_lightning's rank-zero logging helpers: the job runs one process."""

import logging
from collections.abc import Callable
from typing import Any

_LOG = logging.getLogger("step1x3d")


def rank_zero_only(function: Callable[..., Any]) -> Callable[..., Any]:
    return function


def rank_zero_debug(*args: Any, **kwargs: Any) -> None:
    _LOG.debug(*args, **kwargs)


def rank_zero_info(*args: Any, **kwargs: Any) -> None:
    _LOG.info(*args, **kwargs)
