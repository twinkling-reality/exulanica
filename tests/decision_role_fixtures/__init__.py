"""A decision role declared in test data alone: a traffic signal at a junction.

This directory is the role's whole footprint: its registry entry and contract catalogs as data, and
one adapter module, :mod:`decision_role_fixtures.junction_signal`, which also holds the toy engine
the role runs in. The tests load it with this package as the adapter package, so nothing in the
product names it.
"""
