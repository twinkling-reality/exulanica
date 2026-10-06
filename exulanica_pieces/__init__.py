"""Generated pieces as data: the formats the product, the GPU job and the pack tooling all share.

A piece is a static object a model makes for a style pack's look role, fitted to a world kind's
slot. This package holds what every side must agree on, once:

- ``vocabulary``, ``budgets``, ``colour``, ``records`` and ``canonical``: the look roles, the
  style pack format's piece budgets, the sRGB-to-linear colour table, the request, job and receipt
  records with their strict readers, seeds and cache keys. Plain Python, no numpy, so the product
  can import them.
- ``geometry``: orienting, fitting, simplifying and colouring a mesh, and writing it as a
  ``exulanica.static-glb/v1`` container. It needs numpy, which the product does not install, so
  only the GPU job and tooling import it.

It imports nothing of the product and nothing of ``ml/``; import contracts in ``pyproject.toml``
and ``tests/test_pieces_boundary.py`` hold all three rules.
"""
