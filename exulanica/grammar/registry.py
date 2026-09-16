"""A registry of grammars, keyed by id and version, with nothing in it by default.

Adding a grammar is registration and nothing else: this module, the contract and the draw do
not change, and they do not import any grammar. The grammars this repository ships are
registered by ``exulanica.grammar.grammars.builtin_registry``, which is the one place that
names them.

A key is registered once. A second grammar under the same id and version is refused rather
than allowed to replace the first, because a replaced grammar would change what every receipt
naming that key means.
"""

from __future__ import annotations

from exulanica.grammar.contract import Grammar, GrammarKey
from exulanica.grammar.errors import InvalidRecordError, UnregisteredGrammarError

__all__ = ["GrammarRegistry"]


class GrammarRegistry:
    __slots__ = ("_grammars",)

    def __init__(self) -> None:
        self._grammars: dict[GrammarKey, Grammar] = {}

    def register(self, grammar: Grammar) -> None:
        if grammar.key in self._grammars:
            raise InvalidRecordError(
                f"{grammar.key.grammar_id} v{grammar.key.grammar_version} is already registered"
            )
        self._grammars[grammar.key] = grammar

    def get(self, grammar_id: str, grammar_version: int) -> Grammar:
        key = GrammarKey(grammar_id, grammar_version)
        try:
            return self._grammars[key]
        except KeyError:
            raise UnregisteredGrammarError(f"no grammar {grammar_id} v{grammar_version}") from None

    def registered_keys(self) -> tuple[GrammarKey, ...]:
        return tuple(sorted(self._grammars, key=lambda key: (key.grammar_id, key.grammar_version)))
