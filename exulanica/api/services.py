"""What a running instance is wired to, resolved once at startup rather than per request.

Four things, and the interesting one is the second.

*   **A write database and a read database.** The Selection executor is specified to connect as
    ``exulanica_ro``, "a non-owner role that owns nothing and lacks BYPASSRLS", so that the step of
    the pipeline running a plan derived from model output cannot write whatever happened
    upstream of it. That is a second connection string, and when it is absent this says so at
    startup instead of quietly running queries as the writer. A defence that is off and silent
    is worse than one that is absent, because it still reads as present.
*   **The object store**, which is what an evidence citation resolves against.
*   **The model client**, built lazily. Model-dependent endpoints need a configured client, and
    an instance with no credential should serve the other endpoints rather than refuse to start.
*   **Whether this instance drains the derivative queue.** ``POST /intake`` runs the intake stage
    in the request and queues the rest by capture id, so something has to drain it. In one
    process that is a daemon thread here. An instance that leaves it to somebody else says so in
    ``/readyz``, because a queue nobody drains and a queue drained elsewhere look identical from
    the outside and only one of them is a deployment.

Nothing here is a global. The application holds one :class:`Services` and hands it to routes
through a dependency, so a test builds its own and a second instance in one process is possible
rather than a thing that would need to be discovered.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from exulanica.api.account_runtime import AccountRuntime, load_account_runtime
from exulanica.api.authorisation import API_TOKENS_ENV, TokenDirectory, load_token_directory
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import DATABASE_URL_ENV, Database
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.epistemics.caption_embeddings import CaptionEmbeddingPass
from exulanica.ingest.vision import NebiusVisionModel
from exulanica.ingest.worker import DerivativeWorker, lease_seconds_for
from exulanica.models.client import ModelClient
from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
from exulanica.models.manifest import Role
from exulanica.store.base import ContentAddressedStore
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import BLOB_NAMESPACE, material_stores
from exulanica.world.material_recipes import MaterialRuntime
from exulanica.world.texture_assets import load_material_catalog

if TYPE_CHECKING:
    from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime
    from exulanica.world.society_decisions import SocietyDecisionProvider

__all__ = [
    "DATA_DIR_ENV",
    "DERIVATIVE_WORKER_ENV",
    "READONLY_DATABASE_URL_ENV",
    "SOCIETY_CONTROL_WORKER_ENV",
    "Services",
    "build_services",
]

#: The connection string the Selection executor uses. Optional, and its absence is reported.
READONLY_DATABASE_URL_ENV: Final = env_name("READONLY_DATABASE_URL")

#: Where the content-addressed store lives. The same directory the ingest CLI writes.
DATA_DIR_ENV: Final = env_name("DATA_DIR")

#: Set to ``0``, ``false`` or ``off`` to serve the API without draining the derivative queue in
#: this process. Anything else, including absence, runs it: an instance serving ``POST /intake``
#: with nothing draining the queue is an upload that never finishes, and that is the wrong
#: default to arrive at by saying nothing.
DERIVATIVE_WORKER_ENV: Final = env_name("DERIVATIVE_WORKER")

#: Account-wide society playback remains off unless the host opts in. Static
#: ``society_control_workspaces`` remain an independent, narrower enablement path.
SOCIETY_CONTROL_WORKER_ENV: Final = env_name("SOCIETY_CONTROL_WORKER")


@dataclass(frozen=True, slots=True)
class Services:
    """Everything a request might need, and a note about what is not configured."""

    database: Database
    readonly_database: Database
    store: ContentAddressedStore
    tokens: TokenDirectory
    #: True when the executor is running as the writer because no read-only role was configured.
    executor_shares_the_write_role: bool
    #: None when no model credential is configured. Model-dependent endpoints say so.
    model_client: ModelClient | None
    #: The only directory whose already-local files the environment admission route may name.
    #: None disables that write surface while retaining metadata and byte reads.
    environment_admission_root: Path | None = None
    #: True when this process drains the derivative queue itself. Defaulted to False so that a
    #: hand-constructed Services, which is how every test builds one, does not start a thread
    #: nobody asked for. ``build_services`` reads the environment and defaults the other way.
    runs_derivative_worker: bool = False
    #: Independent of the database and blob backups, set by the offline restore protocol.
    restore_state_path: Path | None = None
    #: Optional explicit scoped district/affordance adapter, configured by the host.
    society_runtime: SocietyRuntime | None = None
    #: Explicit server-selected provider for bounded social choices. No automatic promotion.
    society_decision_provider: SocietyDecisionProvider | None = None
    #: Explicit family definitions and current source authority for version-scoped appearance.
    character_appearance: CharacterAppearanceRuntime | None = None
    #: The published material catalog and each workspace's bake namespace. None when this
    #: instance was started without ``assets/textures``, which ``warnings`` says.
    materials: MaterialRuntime | None = None
    #: Dedicated account persistence and verified Google browser sessions, when configured.
    accounts: AccountRuntime | None = None
    #: Explicit host allowlist. Empty leaves automatic society playback disabled.
    society_control_workspaces: tuple[uuid.UUID, ...] = ()
    #: Explicit host opt-in to discover all currently active account-owned workspaces.
    runs_society_control_worker: bool = False
    society_base_tick_interval_ms: int = 1000

    @property
    def society_control_enabled(self) -> bool:
        return self.runs_society_control_worker or bool(self.society_control_workspaces)

    def build_society_control_worker(self) -> SocietyControlWorker | None:
        if not self.society_control_enabled:
            return None
        if self.society_runtime is None:
            raise ValueError("society playback requires a configured current-input runtime")
        if self.runs_society_control_worker and self.accounts is None:
            raise ValueError("account-wide society playback requires configured accounts")
        return SocietyControlWorker(
            self.database,
            runtime=self.society_runtime,
            workspaces=self.society_control_workspaces,
            workspace_source=(
                self.accounts.active_owned_workspaces
                if self.runs_society_control_worker and self.accounts is not None
                else None
            ),
            base_tick_interval_ms=self.society_base_tick_interval_ms,
        )

    @property
    def warnings(self) -> tuple[str, ...]:
        """What this instance is running without. Surfaced by ``/readyz``, never swallowed."""
        notes: list[str] = []
        if self.executor_shares_the_write_role:
            notes.append(
                f"{READONLY_DATABASE_URL_ENV} is not set, so the Selection executor is running "
                "as the write role. Row-level security still applies, but the read-only "
                "guarantee this instance would otherwise have does not."
            )
        if self.model_client is None:
            notes.append(
                "no model credential is configured, so the endpoints that plan a Selection from "
                "a question or compose an answer will refuse rather than guess."
            )
        if not self.runs_derivative_worker:
            notes.append(
                f"{DERIVATIVE_WORKER_ENV} is off, so this process serves POST /intake and does "
                "not drain what that route queues. Uploaded photographs are in the library and "
                "their rendition, vision and depth stages will not run until something else "
                "drains the queue."
            )
        elif self.model_client is None:
            notes.append(
                "the derivative worker is running without a vision model, so uploaded "
                "photographs get a rendition and no observations. A later pass with a "
                "credential configured completes them: every stage is keyed by content and "
                "re-running costs nothing for the stages that already ran."
            )
        if self.materials is None:
            notes.append(
                "the published material catalog is not readable here, so the /materials routes "
                "answer 503 and no recipe can be created or baked."
            )
        if self.runs_derivative_worker:
            notes.append(
                "the derivative worker runs no depth model, so an uploaded photograph is a rung "
                "4 region until `exulanica-ingest --reconstruct` runs over the same corpus. That "
                "is a real rung with a real experience, and reconstruction quality never "
                "participates in the truth guarantee."
            )
        return tuple(notes)

    def build_derivative_worker(self) -> DerivativeWorker | None:
        """The thread that finishes what ``POST /intake`` starts, or None when it is off.

        **The worker is handed workspace UUIDs and an optional callback.**
        ``exulanica.ingest`` sits under ``exulanica.api`` in the layers contract, so the callback
        stays owned here and opens the dedicated account-role connection. The ingest worker sees
        only the returned UUID snapshot, then opens its ordinary workspace-scoped world
        connections. It never imports account or bearer-token code.

        **No depth model**, deliberately. The reconstruction stack is a large optional
        dependency and an API image that carries it is a different image. An uploaded photograph
        is therefore rung 4 until a reconstruction pass runs, which ``warnings`` states rather
        than leaves to be discovered.

        **The constructor computes the lease from the configured client.** How
        long a claimant may be silent depends on the longest model call it can be inside, and
        that is a property of the client rather than of the role: this builds ``ModelClient()``
        with a 180 second timeout and one attempt while ``exulanica-ingest`` builds one with three,
        so a lease typed as a constant would be right for one of them.
        A beat precedes the caption vector pass, so the lease covers the maximum vision or
        caption vector budget per gap, rather than their sum. The same expression
        decides whether there is a model at all, so the two cannot disagree: no client
        means no vision model and the floor, and that is a stated deployment rather than an
        oversight. Reading a budget off the vision model instead would mean widening a protocol
        whose whole point is that the pipeline needs two things from a model, and would break
        every fake in the suite at runtime.
        """
        if not self.runs_derivative_worker:
            return None
        return DerivativeWorker(
            self.database,
            self.store,
            self.tokens.workspaces,
            workspace_source=(
                self.accounts.active_owned_workspaces if self.accounts is not None else None
            ),
            vision=NebiusVisionModel(self.model_client) if self.model_client else None,
            embedding_pass=CaptionEmbeddingPass(self.model_client) if self.model_client else None,
            lease_seconds=lease_seconds_for(
                max(
                    self.model_client.worst_case_seconds(role)
                    for role in (Role.VISION, Role.EMBEDDING)
                )
                if self.model_client
                else None
            ),
        )


def build_services(
    environ: Mapping[str, str] | None = None, *, model_client: ModelClient | None = None
) -> Services:
    """Resolve configuration into services, or fail at startup with the reason.

    ``model_client`` is injectable so a test can supply a scripted one. Everything else comes
    from the environment, because it is deployment configuration rather than a decision the
    code gets to make.
    """
    environ = os.environ if environ is None else environ
    database = Database.from_env(environ)
    readonly_url = env_get("READONLY_DATABASE_URL", environ)
    data_dir = resolve_data_dir(environ)
    accounts = load_account_runtime(environ)
    tokens = (
        TokenDirectory(sessions={})
        if accounts is not None and API_TOKENS_ENV not in environ
        else load_token_directory(environ)
    )

    client = model_client
    if client is None and environ.get("NEBIUS_API_KEY"):
        client = ModelClient()

    return Services(
        database=database,
        readonly_database=Database(url=readonly_url) if readonly_url else database,
        store=LocalContentAddressedStore(data_dir / BLOB_NAMESPACE),
        tokens=tokens,
        executor_shares_the_write_role=readonly_url is None,
        model_client=client,
        accounts=accounts,
        environment_admission_root=data_dir / "environment-inbox",
        materials=_material_runtime(data_dir, environ),
        runs_derivative_worker=_enabled(env_get("DERIVATIVE_WORKER", environ)),
        runs_society_control_worker=_explicitly_enabled(env_get("SOCIETY_CONTROL_WORKER", environ)),
        restore_state_path=(
            Path(value) if (value := env_get("RESTORE_STATE_PATH", environ)) else None
        ),
    )


def _material_runtime(data_dir: Path, environ: Mapping[str, str]) -> MaterialRuntime | None:
    """The published makers and each workspace's bake namespace, when the catalog is here.

    ``EXULANICA_TEXTURE_DIRECTORY`` names the catalog in an image; a checkout finds its own. The
    catalog is verified against its pins on the way in, so a directory that is present but not
    the reviewed one raises :class:`TextureCatalogError` and stops startup, rather than being
    reported as absent. Only a missing catalog is an absence, and ``warnings`` says so.
    """
    directory = env_get("TEXTURE_DIRECTORY", environ)
    try:
        catalog = load_material_catalog(Path(directory)) if directory else load_material_catalog()
    except FileNotFoundError:
        return None
    return MaterialRuntime(catalog=catalog, stores=material_stores(data_dir))


def _enabled(value: str | None) -> bool:
    """Absent means on. Only an explicit off is off, and it has to be spelled like one."""
    return (value or "").strip().lower() not in ("0", "false", "off", "no")


def _explicitly_enabled(value: str | None) -> bool:
    """Parse an opt-in switch; absence and explicit false are both safely off."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "0", "false", "off", "no"):
        return False
    if normalized in ("1", "true", "on", "yes"):
        return True
    raise ValueError(f"{SOCIETY_CONTROL_WORKER_ENV} must be an explicit boolean")


def describe_configuration(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """What an operator needs to set, and whether it is set. Never the values themselves."""
    environ = os.environ if environ is None else environ
    names = (
        DATABASE_URL_ENV,
        READONLY_DATABASE_URL_ENV,
        DATA_DIR_ENV,
        DERIVATIVE_WORKER_ENV,
        SOCIETY_CONTROL_WORKER_ENV,
        API_TOKENS_ENV,
        "NEBIUS_API_KEY",
        "EXULANICA_GOOGLE_CLIENT_ID",
        "EXULANICA_GOOGLE_CLIENT_SECRET",
        "EXULANICA_GOOGLE_CALLBACK_URI",
        "EXULANICA_GOOGLE_RETURN_URIS",
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS",
        "EXULANICA_ACCOUNT_DATABASE_URL",
        EGRESS_ALLOWLIST_ENV,
    )
    return {
        name: (
            "set"
            if (
                env_get(name.removeprefix("EXULANICA_"), environ)
                if name.startswith("EXULANICA_")
                else environ.get(name)
            )
            else "missing"
        )
        for name in names
    }
