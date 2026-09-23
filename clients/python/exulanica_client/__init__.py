"""A small client for a person's world through the Exulanica HTTP API, standard library only.

It reads what the person saved, finds out from the server which edits, behaviours and assets it
supports, and submits edits through the same authenticated routes the application uses, with
nothing from the application's private state. ``python -m exulanica_client walkthrough`` runs the
whole proof; :class:`WorldClient` is the part to build on.
"""

from __future__ import annotations

from .client import ApiRefusal, ClientError, Exchange, WorldClient
from .discovery import Behaviour, Operation, reviewed_behaviours, version_edits

__all__ = [
    "ApiRefusal",
    "Behaviour",
    "ClientError",
    "Exchange",
    "Operation",
    "WorldClient",
    "reviewed_behaviours",
    "version_edits",
]
