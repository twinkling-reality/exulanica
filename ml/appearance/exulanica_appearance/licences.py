"""Which weights licences this lane may run, as the repository has already decided.

``docs/license-matrix.md`` section 6 decides that self-hosted weights are used only under
CC-BY-4.0, OpenMDW-1.1, Apache-2.0, MIT or a public-domain dedication, and that nothing under the
NVIDIA Open Model License enters a pipeline, not even self-hosted. This module holds that decision
over what a Hugging Face model card declares at a pinned revision: its raw ``license`` field, and
for ``other`` its ``license_name`` and ``license_link``. A family name, a catalog label or a
repository's code licence is never read as the weights' licence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from exulanica_appearance.canonical import Refused

__all__ = ["ALLOWED", "RULE", "licence_id"]

RULE: Final = "docs/license-matrix.md section 6"

#: SPDX-style id by the card's own ``license`` value.
_PLAIN: Final = {
    "apache-2.0": "Apache-2.0",
    "mit": "MIT",
    "cc-by-4.0": "CC-BY-4.0",
    "cc0-1.0": "CC0-1.0",
}
#: ``license: other`` is allowed only as exactly this name and link.
_OTHER: Final = {("openmdw1.1-license", "https://openmdw.ai/license/1-1/"): "OpenMDW-1.1"}

ALLOWED: Final = frozenset(_PLAIN.values()) | frozenset(_OTHER.values())


def licence_id(card: Mapping[str, object]) -> str:
    """The allowed licence a card declares, or a refusal naming what it declares instead."""
    declared = card.get("license")
    if isinstance(declared, str) and declared in _PLAIN:
        return _PLAIN[declared]
    if declared == "other":
        key = (card.get("license_name"), card.get("license_link"))
        if key in _OTHER:
            return _OTHER[key]  # type: ignore[index]
        raise Refused(
            f"the card declares license other named {card.get('license_name')!r} at "
            f"{card.get('license_link')!r}, which {RULE} does not allow for self-hosted weights"
        )
    raise Refused(
        f"the card declares license {declared!r}, which {RULE} does not allow for self-hosted weights"
    )
