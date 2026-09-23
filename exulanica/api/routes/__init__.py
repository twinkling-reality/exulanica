"""One module per surface. Every route validates and delegates, and none of them decides.

``routable_paths`` lives here rather than in the test that first needed it, because it is a
property of this package: what its routes actually are, however the framework nests them. Its
callers read it downward: the declaration check in :mod:`exulanica.api.permissions`, the
authorisation sweep's coverage check in ``tests/test_route_probes.py``, the reviewed route table
in :mod:`exulanica.api.surface` and M10 in ``exulanica.evaluation``, and M10's specification is
the reason it must be generated rather than hand-enumerated: "table-driven, generated from the
router, so a new route without a test fails CI." A second copy would be a second thing that can
go blind, so ``mounted_routes`` is the one walk and ``routable_paths`` is read from it.
"""

from __future__ import annotations

__all__ = ["mounted_routes", "routable_paths"]


def mounted_routes(app: object) -> list[object]:
    """Every leaf route in the application, in the order requests are matched against them.

    The walk is recursive over anything that carries routes. FastAPI 0.141 stores an
    ``_IncludedRouter`` wrapper in ``app.routes`` instead of flattening included routes, so a
    one-level walk sees documentation routes and wrappers with no ``methods`` and returns only
    the public documentation surface. Every one of those is declared public, so a shallow sweep
    would compute an empty list of uncovered routes and pass on an application whose
    authenticated surface it could not see.

    ``tests/test_route_probes.py::test_the_sweep_can_see_the_application_by_name`` asserts the
    walk found the authenticated surface by name rather than trusting that it did, and
    ``tests/test_api_surface_snapshot.py`` that its order is the order FastAPI builds the OpenAPI
    document in.
    """
    found: list[object] = []
    seen: set[int] = set()

    def visit(node: object) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        for attribute in ("routes", "original_router"):
            nested = getattr(node, attribute, None)
            if nested is None:
                continue
            for child in nested if isinstance(nested, list) else [nested]:
                visit(child)
        if getattr(node, "path", None) is not None:
            found.append(node)

    visit(app)
    return found


def routable_paths(app: object) -> list[tuple[str, str]]:
    """Every routable (method, path) in the application, sorted, from :func:`mounted_routes`."""
    found: list[tuple[str, str]] = []
    for node in mounted_routes(app):
        path = getattr(node, "path", None)
        for method in sorted(getattr(node, "methods", set()) - {"HEAD", "OPTIONS"}):
            found.append((method, path))
    return sorted(set(found))
