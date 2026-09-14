"""Liveness and readiness, which are two signals and must not be one.

``deployment.md`` section 6 specifies both, and the distinction is not pedantry: a deployment has
to survive stretches of roughly 46 days unattended, an external probe runs every five minutes, and
the two questions have different costs and different answers.

*   **Liveness**, ``GET /healthz``, costs nothing beyond the process itself and checks only
    that the process is running and can serve a request. No dependency is touched.
*   **Readiness**, ``GET /readyz``, costs one cheap query and one cheap object-store call, and
    checks that the dependencies a request actually needs are reachable.

Three things readiness must not do, from section 6.3, and each is implemented as an absence
rather than as a comment:

*   **It must not call a model.** 13,200 checks over that unattended stretch, each spending
    roughly 200 reasoning tokens before producing any output, and worse, health would then go
    red the day the prepaid balance ran out for a reason that has nothing to do with the service
    being up. There is no model call anywhere in this module.
*   **It must not claim more than it checks.** A 200 from ``/healthz`` says the process is
    alive. It does not say the reasoning model still exists in the catalog; that is the
    scheduled ``exulanica-preflight`` run, and readiness reports the manifest parsing rather than
    the catalog agreeing.
*   **It must not be expensive enough to matter**, because a readiness check that is costly gets
    turned off or becomes the thing that falls over.

Neither endpoint is authorised, and that is the one deliberate exception to "every endpoint is
authorised". A liveness probe that needed a credential would be a liveness probe that goes red
when the credential rotates. Neither returns anything about the contents of any workspace.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from exulanica.api.services import Services, describe_configuration
from exulanica.db.migrate import applied_migrations
from exulanica.migrations import migrations
from exulanica.models.manifest import Role, load_manifest

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness. Touches no dependency.")
def healthz() -> dict[str, str]:
    return {"status": "alive"}


def _worker_check(request: Request, services: Services) -> dict[str, Any]:
    """Is the thing that finishes an upload actually running.

    **Liveness, not configuration.** ``Services.runs_derivative_worker`` says a worker was asked
    for; a thread that started and then died on a connection error says the same thing, and from
    the outside those look identical. What that produces is every upload returning a job id
    nothing will claim, every batch staying open, and every formation subscriber waiting out the
    stream's thirty minute cap for a terminal event that is not coming, while readiness says the
    instance is fine.

    An instance configured NOT to run one is READY, and says so, because draining the queue
    elsewhere is a real deployment. What is never ready is a worker that was asked for and is
    not there.
    """
    if not services.runs_derivative_worker:
        return {
            "ok": True,
            "running": False,
            "proves": (
                "this process was not asked to drain the derivative queue. Something else must, "
                "or POST /intake accepts uploads whose model stages never run"
            ),
        }
    worker = getattr(request.app.state, "derivative_worker", None)
    if worker is None or not worker.alive:
        return {
            "ok": False,
            "running": False,
            "last_error": getattr(worker, "last_error", None),
            "proves": (
                "the derivative worker was asked for and its thread is not running. Uploads are "
                "accepted and never finished"
            ),
        }
    return {
        "ok": True,
        "running": True,
        # A count of polls that raised, from the counter that drove the loop. Never a guess, and
        # non-zero with the thread alive is a real state: it recovered.
        "failed_passes": worker.failed_passes,
        "last_error": worker.last_error,
        "proves": "the poll thread is alive; nothing about whether the queue is empty",
    }


@router.get("/readyz", summary="Readiness. One query, one object-store call, no model call.")
def readyz(request: Request, response: Response) -> dict[str, Any]:
    """Report each check separately, and return 503 when any of them fails.

    Separately, because a single boolean tells an operator at 3am that something is wrong and
    nothing about which thing. The checks are the four in section 6.2, and each one's entry says
    what it proves rather than only whether it passed.
    """
    services: Services = request.app.state.services
    checks: dict[str, Any] = {}

    checks["database"] = _database_check(services)
    checks["schema"] = _schema_check(services)
    checks["object_store"] = _store_check(services)
    checks["model_manifest"] = _manifest_check()
    checks["derivative_worker"] = _worker_check(request, services)
    checks["accounts"] = _account_check(services)
    checks["society_playback"] = _society_check(request, services)

    ready = all(check["ok"] for check in checks.values())
    if not ready:
        response.status_code = 503
    return {
        "ready": ready,
        "checks": checks,
        "warnings": list(services.warnings),
        "configuration": describe_configuration(),
    }


def _account_check(services: Services) -> dict[str, Any]:
    if services.accounts is None:
        return {"ok": True, "configured": False}
    try:
        with services.accounts.repository() as repository:
            repository.connection.execute(
                "select session_sha256 from account_browser_session limit 0"
            )
    except Exception:
        return {"ok": False, "configured": True, "detail": "Account persistence is unavailable"}
    return {
        "ok": True,
        "configured": True,
        "proves": "the account store is reachable; live Google sign-in is not probed",
    }


def _society_check(request: Request, services: Services) -> dict[str, Any]:
    if not services.society_control_enabled:
        return {"ok": True, "configured": False, "running": False}
    thread = getattr(request.app.state, "society_control_thread", None)
    worker = getattr(request.app.state, "society_control_worker", None)
    running = thread is not None and thread.is_alive()
    health = getattr(worker, "health", {"failed_rounds": 0, "last_round_failed": False})
    return {
        "ok": running and not health["last_round_failed"],
        "configured": True,
        "running": running,
        **health,
        "proves": "worker liveness and last round status; no promised simulation delivery rate",
    }


def _database_check(services: Services) -> dict[str, Any]:
    """Proves the server accepted a NEW connection and answered on it. Nothing about the schema.

    The noun matters here more than it usually would, because this sentence leaves the process:
    it is served to an operator over HTTP and a human acts on it. **There is no connection pool
    in this application.** ``orimera/db/session.py`` opens a fresh ``psycopg.connect`` per
    session and ``psycopg_pool`` appears in neither ``pyproject.toml`` nor ``uv.lock``, so a
    check that reported "the pool is not full" was reporting on a component that does not exist.

    What a successful connect does prove is adjacent and real: the server had a free connection
    slot at that instant. That is worth reporting, because slots are the resource this
    deployment can actually run out of, and ``docs/deployment.md`` section 5.4 gives the
    arithmetic. It is not a statement about the next request, which needs its own slot.
    """
    try:
        with services.database.unscoped() as connection:
            connection.execute("select 1")
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "proves": (
            "the database accepted a new connection and answered a query, so the server is up "
            "and had a free connection slot at that moment"
        ),
    }


def _schema_check(services: Services) -> dict[str, Any]:
    """Proves the running code and the running schema agree on a version.

    A mismatch here is the failure that otherwise surfaces much later as a wrong answer: two
    deployments claiming the same version with different tables.
    """
    expected = [migration.version for migration in migrations()]
    try:
        with services.database.unscoped() as connection:
            applied = sorted(applied_migrations(connection))
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    if applied != expected:
        return {
            "ok": False,
            "detail": f"the database has {applied} and this code expects {expected}",
        }
    return {"ok": True, "applied": applied}


def _store_check(services: Services) -> dict[str, Any]:
    """Proves object storage is reachable and configuration points at the right place.

    Deliberately a single existence probe against a key that cannot exist rather than a listing.
    A listing is proportional to the corpus and this runs every five minutes.
    """
    from exulanica.evidence.blob import BlobId

    try:
        services.store.exists(BlobId(b"\x00" * 32))
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "proves": "the store is reachable; nothing about any scene's completeness"}


def _manifest_check() -> dict[str, Any]:
    """Proves the application can name a model. Proves NOTHING about that model still existing.

    That gap is the whole reason ``exulanica-preflight`` is a separate scheduled signal, and
    section 6.3 names it: "a green health check sitting in front of a withdrawn model".
    """
    try:
        manifest = load_manifest()
        resolved = {str(role): manifest[role].primary.model_id for role in Role}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "roles": resolved,
        "does_not_prove": "that any of these identifiers still exists in the live catalog. Run "
        "exulanica-preflight on a schedule for that.",
    }
