"""Sea stacks: a stack stated by its sizes, lean, shoulders and passage, made into a volume by rule.

A sea stack is one kind of rock a world places in its sea, near or far. Stated as a volume it is a
handful of parts whose sizes depend on each other; stated as a stack it is the few values a person
or a scatter chooses, and the maker turns them into the parts by rules judged in the application.

* :mod:`.catalog`: the bound of every value a stack states (``assets/catalogs/stacks``).
* :mod:`.document`: ``exulanica.sea-stack/v1``, read against the catalog and refused by rule.
* :mod:`.maker`: the stack and a seed made into an unchanged ``exulanica.volume/v1`` document.

Nothing here opens a database, a store or evidence, and nothing reads a sea stack yet: its volume
is a pure function of the stack document and a seed.
"""

from exulanica.grammar.stacks.catalog import (
    CATALOG_VERSION,
    CATALOG_VERSIONS,
    VOLUME_CATALOG_VERSION,
    SeaStackCatalog,
    load_sea_stack_catalog,
    sea_stack_catalog,
)
from exulanica.grammar.stacks.document import (
    FLANK_PERMILLE,
    PROFILE,
    SILL_MM,
    SeaStackArch,
    SeaStackDocument,
    SeaStackRefused,
    read_sea_stack_document,
    trunk_radius,
)
from exulanica.grammar.stacks.maker import axis_point, make_sea_stack

__all__ = [
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "FLANK_PERMILLE",
    "PROFILE",
    "SILL_MM",
    "VOLUME_CATALOG_VERSION",
    "SeaStackArch",
    "SeaStackCatalog",
    "SeaStackDocument",
    "SeaStackRefused",
    "axis_point",
    "load_sea_stack_catalog",
    "make_sea_stack",
    "read_sea_stack_document",
    "sea_stack_catalog",
    "trunk_radius",
]
