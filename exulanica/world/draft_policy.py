"""How many drafts of a place may run and start: chosen budgets, stated as one versioned document.

A draft of a place from a person's words holds a thread of the API process while a model reasons
and spends the hosted allowance. How many may run at once in a process and in a workspace, and how
many one person may start in an hour, are budgets a deployment chooses, never head counts fixed in
code: each is a figure of ``world-draft-policy.v1.json`` with its reason, and a deployment states
its own in the environment variable the policy names. A variable that is not a whole number of at
least 1 is refused by name, never read as no bound. The server reads every one as it starts
(:meth:`WorldDraftPolicy.check`), so a bad figure stops the start by name, and reads the figure
again at each ask.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

__all__ = [
    "BUDGETS",
    "WORLD_DRAFT_POLICY",
    "WorldDraftPolicy",
    "current_world_draft_policy",
    "load_world_draft_policy",
]

#: Every budget the policy states, and whether a guest has a figure of their own.
BUDGETS: Final[Mapping[str, bool]] = MappingProxyType(
    {"drafts_at_once": False, "workspace_drafts_at_once": False, "starts_an_hour": True}
)
_SCOPES: Final = frozenset({"process", "workspace", "person"})


@dataclass(frozen=True, slots=True)
class WorldDraftPolicy:
    """The budgets drafts of a place are held to, as one versioned document."""

    policy_id: str
    version: int
    budgets: Mapping[str, Mapping[str, Any]]

    def figure(
        self, budget: str, *, guest: bool = False, environ: Mapping[str, str] | None = None
    ) -> int:
        """The figure of ``budget`` for a signed-in person or a guest: the deployment's own where
        its variable states a whole number of at least 1, else the policy's."""
        stated = self.budgets[budget]
        mine = guest and BUDGETS[budget]
        name = stated["guest_environment" if mine else "environment"]
        value = (os.environ if environ is None else environ).get(name, "").strip()
        if not value:
            return int(stated["guest_figure" if mine else "figure"])
        if not value.isascii() or not value.isdigit() or int(value) < 1:
            raise ValueError(f"{name} must be a whole number of at least 1, not {value!r}")
        return int(value)

    def check(self, environ: Mapping[str, str] | None = None) -> None:
        """Read every figure a deployment may state, a guest's too, and refuse by name the first
        that is no whole number of at least 1: asked as a server starts."""
        for budget, guest in BUDGETS.items():
            self.figure(budget, environ=environ)
            if guest:
                self.figure(budget, guest=True, environ=environ)


def _whole(path: Path, where: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(
            f"{path.name} states {where} as {value!r}; a figure is a whole number >= 1"
        )
    return value


def load_world_draft_policy(path: Path) -> WorldDraftPolicy:
    """Read and check a policy document: exactly the budgets :data:`BUDGETS` names, each with its
    scope, a figure of at least 1, the variable a deployment states its own in, and a reason."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if set(document) != {"policy_id", "version", "budgets"}:
        raise ValueError(f"{path.name} must state policy_id, version and budgets only")
    version = document["version"]
    if type(version) is not int or version < 1:
        raise ValueError(f"{path.name} needs a positive integer version")
    budgets = document["budgets"]
    if not isinstance(budgets, dict) or set(budgets) != set(BUDGETS):
        raise ValueError(f"{path.name} must state exactly the budgets {sorted(BUDGETS)}")
    names: list[str] = []
    for key, guest in BUDGETS.items():
        stated = budgets[key]
        fields = {"scope", "figure", "environment", "reason"}
        fields |= {"guest_figure", "guest_environment"} if guest else set()
        if not isinstance(stated, dict) or set(stated) != fields:
            raise ValueError(f"{path.name} must state {', '.join(sorted(fields))} for {key}")
        if stated["scope"] not in _SCOPES:
            raise ValueError(f"{path.name} counts {key} per {stated['scope']!r}")
        _whole(path, f"{key}.figure", stated["figure"])
        names.append(stated["environment"])
        if guest:
            _whole(path, f"{key}.guest_figure", stated["guest_figure"])
            names.append(stated["guest_environment"])
        if not isinstance(stated["reason"], str) or not stated["reason"].strip():
            raise ValueError(f"{path.name} must give a reason for {key}")
    if len(set(names)) != len(names) or not all(
        isinstance(name, str) and name.startswith("EXULANICA_") for name in names
    ):
        raise ValueError(f"{path.name} names each figure's own EXULANICA_ variable, once")
    return WorldDraftPolicy(
        policy_id=str(document["policy_id"]),
        version=version,
        budgets=MappingProxyType(
            {key: MappingProxyType(dict(value)) for key, value in budgets.items()}
        ),
    )


#: The policy every draft of a place is held to.
WORLD_DRAFT_POLICY: WorldDraftPolicy = load_world_draft_policy(
    Path(__file__).with_name("world-draft-policy.v1.json")
)


def current_world_draft_policy() -> WorldDraftPolicy:
    """The policy in force, read when it is asked for rather than bound when a module loads."""
    return WORLD_DRAFT_POLICY
