"""The door as one process runs it: its bridges, its database, and what it tells itself.

:class:`DoorRuntime` is built once per process from the deployment's settings
(:func:`exulanica.door.bridges.load_bridge_directory`) and held by the application's services. Its
routes and the decision host's asker share its :class:`~exulanica.door.notices.Notices`, so an ask
the host writes wakes its bridge's held poll at once, and an answer a route stores wakes the asker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from exulanica.db.session import Database
from exulanica.door.asker import DoorAsker
from exulanica.door.bridges import BridgeDirectory, load_bridge_directory
from exulanica.door.notices import HeldPolls, Hellos, Notices

__all__ = ["DoorRuntime", "door_runtime"]


@dataclass(frozen=True)
class DoorRuntime:
    """The bridges a deployment admits, over one database, in one process."""

    database: Database
    bridges: BridgeDirectory
    notices: Notices = field(default_factory=Notices)
    polls: HeldPolls = field(default_factory=HeldPolls)
    hellos: Hellos = field(default_factory=Hellos)

    def asker(self) -> DoorAsker:
        """The external asker the decision host is given."""
        return DoorAsker(database=self.database, notices=self.notices, bridges=self.bridges)


def door_runtime(database: Database, environ: Mapping[str, str] | None = None) -> DoorRuntime:
    """The door for this process, with the bridges its environment declares (none when unset)."""
    return DoorRuntime(database=database, bridges=load_bridge_directory(environ))
