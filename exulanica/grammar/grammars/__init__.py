"""The grammars this repository ships, and the one function that registers them.

This is the only module that names a grammar. The generic contract, the draw, the parameter
cascade and the catalog loader never import anything under this package, and a test holds them
to that. A new grammar is a new module here and one ``register`` line below.

* ``box`` makes a box. It shares no vocabulary with the city and uses the same descriptor,
  cascade, draw, validation and receipt.
* ``city`` is the registered city grammar. Ten of its stages emit records through
  ``exulanica.grammar.grammars.city.generation``; the registered tile stage is a record-shape
  contract.
"""

from __future__ import annotations

from exulanica.grammar.grammars.box import BOX_GRAMMAR
from exulanica.grammar.grammars.city import CITY_GRAMMAR
from exulanica.grammar.registry import GrammarRegistry

__all__ = ["builtin_registry"]


def builtin_registry() -> GrammarRegistry:
    registry = GrammarRegistry()
    registry.register(BOX_GRAMMAR)
    registry.register(CITY_GRAMMAR)
    return registry
