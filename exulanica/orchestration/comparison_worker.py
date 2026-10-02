"""Play the comparisons started from the application in a process of its own.

    EXULANICA_BUDGET_USD=<bound> python -m exulanica.orchestration.comparison_worker

The same worker the API's lifespan starts in a thread (:mod:`exulanica.api.society_comparison_
worker`), for the workspaces ``EXULANICA_SOCIETY_CONTROL_WORKSPACES`` lists, until it is
interrupted or terminated; a run it is playing then is closed at its next minute, or left for the
next claim when it has asked nothing. Run it with ``EXULANICA_COMPARISON_WORKER=process`` set on
the API, which then serves starts without playing them, so one host plays each start. This process
does nothing else, so its asks keep none of its model budget back for other work, as the local
compare command keeps none; each comparison still plays under the bound its owner stated. The
model's key is read from the environment by the application's own client, and the database is the
one ``EXULANICA_DATABASE_URL`` names. It plays nothing on a database whose recorded migrations
differ from this package's, or through a connection for which row-level security is no boundary,
checked before anything is claimed as the API and the derivative workers check at their start.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Sequence

from exulanica.api.services import build_services
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    services = build_services(spending_label="comparison-worker")
    verify_schema(services.database)
    with services.database.unscoped() as connection:
        assert_runtime_role(connection)
    worker = services.build_comparison_worker(keeps_share=False)
    if worker is None:
        raise SystemExit(
            "this environment plays no comparison: it configures no society runtime or lists no "
            "workspace in EXULANICA_SOCIETY_CONTROL_WORKSPACES"
        )
    stop = threading.Event()
    for received in (signal.SIGINT, signal.SIGTERM):
        signal.signal(received, lambda _number, _frame: stop.set())
    worker.run(stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
