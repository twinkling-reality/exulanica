"""One module per surface. Every route validates and delegates, and none of them decides.

``routable_paths`` lives here rather than in the test that first needed it, because it is a
property of this package: what its routes actually are, however the framework nests them. Two
callers read it downward, the authorisation sweep in ``tests/test_api.py`` and M10 in
``exulanica.evaluation``, and M10's specification is the reason it must be generated rather than
hand-enumerated: "table-driven, generated from the router, so a new route without a test fails
CI." A second copy would be a second thing that can go blind.
"""

from __future__ import annotations

__all__ = ["routable_paths"]


def routable_paths(app: object) -> list[tuple[str, str]]:
    """Every routable (method, path) in the application, however the framework nests them.

    THIS WALKS A TREE AND IT DID NOT USED TO. FastAPI 0.141 stopped flattening an included
    router's routes into ``app.routes`` and started storing an ``_IncludedRouter`` wrapper there
    instead. The previous version of this function iterated ``app.routes`` one level deep and
    read ``.methods`` off each entry, so from that release onward it saw the four documentation
    routes and six wrappers with no ``methods`` attribute, and returned only the documentation
    routes. Every one of those is in ``PUBLIC_ROUTES``, so the coverage check below computed an
    empty list of uncovered routes and passed, on an application whose entire authenticated
    surface it could no longer see.

    That is the failure this file's own docstring says it exists to prevent, and it is the
    failure mode a private known-defects note records twice: a test that passes without
    exercising its case. It was found by adding a route and noticing the suite stayed green.

    So the walk is recursive over anything that carries routes, and
    ``tests/test_api.py::test_the_route_sweep_can_actually_see_the_application`` asserts the walk
    found the surface by name rather than trusting that it did.
    """
    found: list[tuple[str, str]] = []
    seen: set[int] = set()
    stack = [app]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        for attribute in ("routes", "original_router"):
            nested = getattr(node, attribute, None)
            if nested is None:
                continue
            stack.extend(nested if isinstance(nested, list) else [nested])
        path = getattr(node, "path", None)
        if path is None:
            continue
        for method in sorted(getattr(node, "methods", set()) - {"HEAD", "OPTIONS"}):
            found.append((method, path))
    return sorted(set(found))
