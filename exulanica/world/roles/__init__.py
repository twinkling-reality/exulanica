"""The adapter modules of the decision roles, one module per role and nothing else.

A role's registry entry (``assets/catalogs/roles``) names its adapter by a key, and
:func:`exulanica.world.decision_roles.load_decision_roles` imports that key from this package
alone. Each module declares the one role key it serves and holds the code only that role can have;
everything else a role needs is data. See :mod:`exulanica.world.decision_roles`.
"""
