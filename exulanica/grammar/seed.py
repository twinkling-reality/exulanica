"""The seed: 64 lowercase hexadecimal characters, validated, and never produced here.

A seed is an input. This package has no clock, no ``random`` and no ``secrets``, so it cannot
make one up, and it has no default, so a caller that forgot to pass one is refused rather than
handed a world nobody chose. Whoever mints a seed records it; this module only checks the shape.

The shape is strict on purpose. Uppercase is refused rather than folded, because two spellings
of one seed would be two different digest inputs to ``_number``. An ``int`` is refused rather
than formatted, because there is more than one way to format it.
"""

from __future__ import annotations

import re
from typing import Final

from exulanica.grammar.errors import InvalidSeedError

__all__ = ["SEED_HEX_LENGTH", "require_seed"]

SEED_HEX_LENGTH: Final = 64

# An explicit ASCII class: `\d` would also accept digits from other scripts.
_SEED: Final = re.compile(r"[0-9a-f]{64}")


def require_seed(value: object) -> str:
    """Return ``value`` unchanged if it is a well formed seed, or raise ``InvalidSeedError``."""
    if type(value) is not str:
        raise InvalidSeedError(
            f"a seed is a {SEED_HEX_LENGTH} character lowercase hexadecimal string, "
            f"not {type(value).__name__}"
        )
    if _SEED.fullmatch(value) is None:
        raise InvalidSeedError(
            f"a seed is exactly {SEED_HEX_LENGTH} lowercase hexadecimal characters; "
            f"got {len(value)} characters that do not all match"
        )
    return value
