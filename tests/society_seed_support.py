"""A chosen seed for a society created through the routes, where a test or a measurement needs one.

The create route takes no seed: the server derives each world's own
(:func:`exulanica.world.society.world_society_seed`). A test that holds a society's history to one
computed from a known seed installs that seed on the application's services, the one place the
route reads it from, rather than sending it.
"""

from __future__ import annotations

import dataclasses
from typing import Any


def choose_society_seed(app: Any, seed: str) -> None:
    """Start every society this application creates from ``seed`` instead of its world's own."""
    app.state.services = dataclasses.replace(
        app.state.services, society_seed=lambda _workspace_id, _world_id: seed
    )
