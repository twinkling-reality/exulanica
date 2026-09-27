"""The schemas every decision role's contract catalogs are read by, and nothing else.

A role's contract is two catalogs its registry entry names (:mod:`exulanica.world.decision_roles`):
its actions, each a kind the role's adapter applies with the words a model reads, and its policy,
each one bound on asking. One schema reads every role's actions and one every role's policy, so a
new role's catalogs need no schema of their own. They stand apart from the registry so that the
society catalogs can name the person's two with them while importing nothing a score may not
(the import contract "A person's score cannot read a model").
"""

from __future__ import annotations

from typing import Final

from exulanica.grammar.catalogs import CatalogSchema, FieldValue, integer_field, text_field
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.records import KEY_PATTERN

__all__ = ["POLICY_VALUE_MAXIMUM", "role_action_schema", "role_policy_schema"]

#: The largest bound a policy entry may state, the society policy catalogs' own ceiling.
POLICY_VALUE_MAXIMUM: Final = 10**9


def _kind(where: str, value: object) -> FieldValue:
    if type(value) is not str or KEY_PATTERN.fullmatch(value) is None:
        raise CatalogError(f"{where} is a lowercase key, got {value!r}")
    return value


def role_action_schema(catalog_id: str, version: int) -> CatalogSchema:
    """A role's action catalog: each entry an action kind, its words and why it is offered. The
    kinds are the role's adapter's to accept, so one schema reads every role's."""
    return CatalogSchema(
        catalog_id,
        version,
        (("kind", _kind), ("words", text_field), ("reason", text_field)),
    )


def role_policy_schema(catalog_id: str, version: int) -> CatalogSchema:
    """A role's policy catalog: each entry one bound on asking, a whole number, and its reason."""
    return CatalogSchema(
        catalog_id,
        version,
        (("value", integer_field(0, POLICY_VALUE_MAXIMUM)), ("reason", text_field)),
    )
