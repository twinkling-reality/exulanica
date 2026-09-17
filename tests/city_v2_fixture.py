"""The hand-written city v2 fixture, imported once by every test that reads its records.

``tests/fixtures/city-v2/build_fixture.py`` is a script, not a package, and run as a script it
rewrites the committed files. Imported here under another module name it builds the records and
writes nothing. Every test that needs a real record of a city kind takes it from this one source,
so a record shape change moves the fixture and its tests together.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES_BY_TYPE

__all__ = ["BUILDER_PATH", "builder", "records_by_kind", "stage_of_kind"]

BUILDER_PATH = Path(__file__).resolve().parent / "fixtures" / "city-v2" / "build_fixture.py"
_MODULE_NAME = "city_v2_fixture_builder"


def builder() -> ModuleType:
    """The builder module, executed once per process. Its ``main`` is never called."""
    loaded = sys.modules.get(_MODULE_NAME)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[_MODULE_NAME]
        raise
    return module


def records_by_kind() -> dict[str, list[Any]]:
    """Every fixture record, owned and halo, grouped by record kind in document order."""
    grouped: dict[str, list[Any]] = {}
    for record in builder().build_document().grammars[0].records():
        grouped.setdefault(CITY_SHAPES_BY_TYPE[type(record)].kind, []).append(record)
    return grouped


def stage_of_kind() -> dict[str, str]:
    """The stage that validates each record kind, as the descriptor declares it."""
    return {
        kind: declaration.stage_id
        for declaration in CITY_GRAMMAR.declared_stages
        for kind, _version in declaration.records
    }
