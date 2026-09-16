"""The grammars this repository ships, and the one function that registers them.

This is the only module that names a grammar. The generic contract, the draw, the parameter
cascade and the catalog loader never import anything under this package, and a test holds them
to that. A new grammar is a new module here and one ``register`` line below.

* ``box`` makes a box. It exists to prove the contract is generic: it produces something that is
  not architecture, through exactly the machinery the city uses, with no change to that
  machinery.
* ``city`` is the first and largest grammar. Its stages are record shapes and validators; none of
  them generates anything yet, and each says so in its emission.
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
