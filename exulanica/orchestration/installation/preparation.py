"""``exulanica-asset-preparation`` as an installation runs it: the preparers its profile installs.

The worker itself (:mod:`exulanica.world.asset_preparation_command`) runs every registered
preparer its host can. An installation's profile may say which run (``components.preparation``,
``preparers``), and the installation's facts report each one by that declaration, so the process
that runs them takes its set from the same declaration and refuses to start, by name, when it
cannot honour it. That check needs the profile, which the world layer may not import, so it lives
here, above both.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from exulanica.api.installation import load_installation
from exulanica.world.asset_preparation import PREPARERS, Preparer
from exulanica.world.asset_preparation_command import main as worker_main

__all__ = ["PreparerDeclarationRefused", "declared_preparers", "main"]


class PreparerDeclarationRefused(ValueError):
    """The installation's profile and this process disagree about which preparers run here."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def declared_preparers(environ: Mapping[str, str]) -> Mapping[tuple[str, int], Preparer]:
    """The preparers this process runs: the ones the profile installs, each registered and able to
    run here; every registered one where no profile, or a profile naming none, is set."""
    profile = load_installation(environ).profile
    if profile is None:
        return PREPARERS
    component = profile.components["preparation"]
    if not component.installed:
        raise PreparerDeclarationRefused(
            "preparation_not_installed",
            f"profile {profile.id} does not install preparation, so nothing here runs",
        )
    if component.preparers is None:
        return PREPARERS
    registered = {f"{key[0]}@{key[1]}": (key, preparer) for key, preparer in PREPARERS.items()}
    chosen: dict[tuple[str, int], Preparer] = {}
    for pin, spec in sorted(component.preparers.items()):
        if not spec.installed:
            continue
        if pin not in registered:
            raise PreparerDeclarationRefused(
                "declared_preparer_unknown",
                f"profile {profile.id} installs {pin}, which no code registers",
            )
        key, preparer = registered[pin]
        if spec.reason is not None or not preparer.available():
            raise PreparerDeclarationRefused(
                "declared_preparer_unavailable",
                f"profile {profile.id} installs {pin}, and this process cannot run it",
            )
        chosen[key] = preparer
    return MappingProxyType(chosen)


def main(argv: list[str] | None = None) -> int:
    return worker_main(argv, preparers=declared_preparers)
