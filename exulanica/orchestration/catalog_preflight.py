"""The deployment's model catalog gate, ``exulanica-preflight``, with the decision roles.

``exulanica/models/preflight.py`` checks every model identifier the manifest reaches against its
provider's catalog, and holds each bound role's models to that role's use cases. The roles a world
chooses a model for are declared by the decision role registry, which sits above the model
package, so the model package's check cannot hold their models to their use cases by itself. This
command gives it the registry's roles: it is the ``exulanica-preflight`` console script that
``docs/deployment.md`` (section 7.3) wires into the build, the offline check and the scheduled
one, and runnable as ``python -m exulanica.orchestration.catalog_preflight``.
"""

from __future__ import annotations

from collections.abc import Sequence

from exulanica.models import preflight
from exulanica.world.decision_roles import decision_roles

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Check the manifest against its providers' catalogs, with every registered role's needs."""
    return preflight.main(argv, chosen=decision_roles().chosen)


if __name__ == "__main__":
    raise SystemExit(main())
