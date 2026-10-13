"""Current contact considers every authored delta family, including removed rows."""

from types import SimpleNamespace

import pytest
from exulanica.world.authored_delta import DELTA_SECTIONS
from exulanica.world.terrain_source import _has_authored_delta


@pytest.mark.parametrize("section", DELTA_SECTIONS, ids=lambda section: section.key)
def test_every_registered_section_is_unreconciled_even_if_removed(section):
    empty = {item.key: () for item in DELTA_SECTIONS}
    assert not _has_authored_delta(SimpleNamespace(**empty))
    occupied = {**empty, section.key: (SimpleNamespace(removed=True),)}
    assert _has_authored_delta(SimpleNamespace(**occupied))


def test_new_unmapped_authored_section_refuses_before_reading(monkeypatch):
    import uuid

    import exulanica.world.terrain_source as source
    from exulanica.world.errors import InvalidStructuralData

    monkeypatch.setattr(source, "DELTA_SECTIONS", (*DELTA_SECTIONS, SimpleNamespace(key="future")))
    with pytest.raises(InvalidStructuralData, match="coverage is incomplete"):
        source._has_retained_delta(SimpleNamespace(), uuid.uuid4())
