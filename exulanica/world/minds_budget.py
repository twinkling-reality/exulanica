"""What a world may spend on the model minds of its beings: a budget a person sets.

A world's beings may be given open models as minds (:mod:`exulanica.world.decision_roles`), and
the playback host asks a chosen model at each being's choice points. What bounds that asking, a
world, is its budget for the role: US dollars and decisions in any hour of real time, which is how
the host counts what a world asked (``exulanica.api.decision_host.world_hour``). A person sets it;
each setting is one appended row of ``world_minds_budget`` (migration 0190) naming who set it, and
the newest is the budget. A world nobody set one for has the two figures its role's policy catalog
states (``spend_per_world_hour_microusd``, ``decisions_per_world_hour_maximum``), as every world
had before a budget could be set.

A budget only lowers what the host allows: the process's own budget, a deployment's allowance and
the durable spending authority's grants bound every call whatever is set here. So no figure is
refused for being large; a figure is refused only where it cannot be stored as written.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.decision_roles import DecisionContract, DecisionRole
from exulanica.world.society_planner import input_sha256

__all__ = [
    "BUDGET_REFUSALS",
    "DECISIONS_MAXIMUM",
    "PROFILE",
    "USD_MAXIMUM",
    "MindsBudget",
    "MindsBudgetRefused",
    "MindsBudgetRepository",
    "default_budget",
]

PROFILE: Final = "exulanica.world-minds-budget/v1"
_MICRO: Final = Decimal("0.000001")
#: The most a row's dollar figure may read, as its column's text states it: six whole digits and
#: six decimals. A bound of storage, not of spending: the host's own budgets bound that.
USD_MAXIMUM: Final = Decimal("999999.999999")
#: The most a row's decisions figure may read: what its column's check admits.
DECISIONS_MAXIMUM: Final = 2_147_483_647
BUDGET_REFUSALS: Final[Mapping[str, str]] = {
    "budget_usd_not_a_figure": "the dollars an hour are not a figure that can be recorded: a "
    "decimal number from 0, with at most six decimals",
    "budget_decisions_not_a_figure": "the decisions an hour are not a figure that can be "
    "recorded: a whole number from 0",
    "budget_key_reused": "this request id recorded another budget for this world",
}


class MindsBudgetRefused(Exception):
    """A budget that cannot be recorded, by the code a route answers with."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.detail = BUDGET_REFUSALS[code]
        super().__init__(self.detail)


@dataclass(frozen=True, slots=True)
class MindsBudget:
    """A world's budget for one role's minds: the most its models may be asked, and cost, in any
    hour of real time. ``recorded`` is the row it was read from, or None for the catalog's
    figures, which hold where nobody set one."""

    usd_per_hour: Decimal
    decisions_per_hour: int
    recorded: Mapping[str, Any] | None = None

    @property
    def set_by_a_person(self) -> bool:
        return self.recorded is not None

    def view(self) -> dict[str, Any]:
        """The budget as a read serves it."""
        recorded = self.recorded
        return {
            "profile": PROFILE,
            "usd_per_hour": _usd(self.usd_per_hour),
            "decisions_per_hour": self.decisions_per_hour,
            "hour": "real_time",
            "set_by_a_person": recorded is not None,
            "budget_seq": None if recorded is None else recorded["budget_seq"],
            "set_by": None if recorded is None else recorded["set_by"],
            "recorded_at": None if recorded is None else recorded["recorded_at"],
            "document_sha256": None if recorded is None else recorded["document_sha256"],
        }


def _usd(value: Decimal) -> str:
    return str(value.quantize(_MICRO))


def default_budget(contract: DecisionContract) -> MindsBudget:
    """The budget of a world nobody set one for: the two figures the role's policy states."""
    return MindsBudget(
        Decimal(contract.value("spend_per_world_hour_microusd")) / Decimal(1_000_000),
        int(contract.value("decisions_per_world_hour_maximum")),
    )


def _figures(usd_per_hour: Any, decisions_per_hour: Any) -> tuple[Decimal, int]:
    try:
        usd = Decimal(str(usd_per_hour))
    except (InvalidOperation, ValueError) as exc:
        raise MindsBudgetRefused("budget_usd_not_a_figure") from exc
    if not usd.is_finite() or usd < 0 or usd > USD_MAXIMUM or usd != usd.quantize(_MICRO):
        raise MindsBudgetRefused("budget_usd_not_a_figure")
    if (
        isinstance(decisions_per_hour, bool)
        or not isinstance(decisions_per_hour, int)
        or not 0 <= decisions_per_hour <= DECISIONS_MAXIMUM
    ):
        raise MindsBudgetRefused("budget_decisions_not_a_figure")
    return usd, decisions_per_hour


class MindsBudgetRepository:
    """One world's budgets for its minds, under the workspace's row security."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, *, world_id: str
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id

    def _newest(self, role_key: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "select budget_seq,request_id,document,document_sha256,set_by,recorded_at "
            "from world_minds_budget where workspace_id=%s and world_id=%s and role_key=%s "
            "order by budget_seq desc limit 1",
            (self.workspace_id, self.world_id, role_key),
        ).fetchone()

    def current(self, role: DecisionRole, contract: DecisionContract) -> MindsBudget:
        """The world's budget for ``role`` now: the newest row, or the figures ``contract``
        states where the world has none."""
        row = self._newest(role.key)
        if row is None:
            return default_budget(contract)
        return _read(row)

    def record(
        self,
        role: DecisionRole,
        *,
        request_id: uuid.UUID,
        usd_per_hour: Any,
        decisions_per_hour: Any,
        set_by: uuid.UUID,
    ) -> MindsBudget:
        """Record the world's budget for ``role``, or answer the one this request id already
        recorded. A request id that recorded other figures, or another account's, is refused
        (``budget_key_reused``)."""
        usd, decisions = _figures(usd_per_hour, decisions_per_hour)
        with self.connection.transaction():
            existing = self.connection.execute(
                "select budget_seq,request_id,document,document_sha256,set_by,recorded_at "
                "from world_minds_budget where workspace_id=%s and world_id=%s and role_key=%s "
                "and request_id=%s",
                (self.workspace_id, self.world_id, role.key, request_id),
            ).fetchone()
            if existing is not None:
                held = _read(existing)
                if (
                    held.usd_per_hour != usd
                    or held.decisions_per_hour != decisions
                    or existing["set_by"] != set_by
                ):
                    raise MindsBudgetRefused("budget_key_reused")
                return held
            newest = self._newest(role.key)
            sequence = (0 if newest is None else int(newest["budget_seq"])) + 1
            document: dict[str, Any] = {
                "profile": PROFILE,
                "world_id": self.world_id,
                "role_key": role.key,
                "budget_seq": sequence,
                "request_id": str(request_id),
                "usd_per_hour": _usd(usd),
                "decisions_per_hour": decisions,
                "hour": "real_time",
                "set_by": str(set_by),
            }
            document["document_sha256"] = input_sha256(document)
            row = self.connection.execute(
                "insert into world_minds_budget(workspace_id,world_id,role_key,budget_seq,"
                "request_id,document,document_sha256,set_by) values(%s,%s,%s,%s,%s,%s,%s,%s) "
                "returning budget_seq,request_id,document,document_sha256,set_by,recorded_at",
                (
                    self.workspace_id,
                    self.world_id,
                    role.key,
                    sequence,
                    request_id,
                    Jsonb(document),
                    document["document_sha256"],
                    set_by,
                ),
            ).fetchone()
        assert row is not None
        return _read(row)


def _read(row: Mapping[str, Any]) -> MindsBudget:
    document = row["document"]
    return MindsBudget(
        Decimal(str(document["usd_per_hour"])),
        int(document["decisions_per_hour"]),
        {
            "budget_seq": int(row["budget_seq"]),
            "set_by": str(row["set_by"]),
            "recorded_at": row["recorded_at"].isoformat(),
            "document_sha256": row["document_sha256"],
        },
    )
