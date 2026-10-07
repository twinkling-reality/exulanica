"""The door as one process runs it: its bridges, its database, and what it tells itself.

:class:`DoorRuntime` is built once per process from the deployment's settings
(:func:`exulanica.door.bridges.load_bridge_directory`) and held by the application's services. Its
routes and the decision host's asker share its :class:`~exulanica.door.notices.Notices`, so an ask
the host writes wakes its bridge's held poll at once, and an answer a route stores wakes the asker.
Where the deployment has accounts, ``open_to`` says whether a workspace is open (its owner's account
and membership stand and it is not disabled), read through the account role each time it is asked:
a closed workspace's credentials and invites open nothing and its grants' programs are not asked.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
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
    open_to: Callable[[uuid.UUID], bool] | None = None

    def asker(self) -> DoorAsker:
        """The external asker the decision host is given."""
        return DoorAsker(
            database=self.database,
            notices=self.notices,
            bridges=self.bridges,
            open_to=self.open_to,
        )


def door_runtime(
    database: Database,
    environ: Mapping[str, str] | None = None,
    open_to: Callable[[uuid.UUID], bool] | None = None,
) -> DoorRuntime:
    """The door for this process, with the bridges its environment declares (none when unset), and
    whether a workspace is open where the deployment has accounts."""
    return DoorRuntime(database=database, bridges=load_bridge_directory(environ), open_to=open_to)
