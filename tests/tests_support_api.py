"""Building a Database pointed at the harness's throwaway schema.

The API resolves its own connections through :class:`exulanica.db.session.Database`, so a test
cannot hand it an already-open connection the way the repository tests do. The schema goes on
the search path inside the URL instead, which is the same mechanism the command line tests use
and for the same reason: there is no connection object to issue a statement on.
"""

from __future__ import annotations

import urllib.parse

from exulanica.db.session import Database
from exulanica.env import env_get

__all__ = ["scratch_database"]


def scratch_database(scratch: str) -> Database:
    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    options = urllib.parse.quote(f"-csearch_path={scratch},public", safe="")
    return Database(url=f"{base}{'&' if '?' in base else '?'}options={options}")
