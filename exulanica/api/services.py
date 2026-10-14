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
    The client is shared by every workspace and carries no policy, so it sends nothing by itself:
    a route sends through :meth:`Services.hosted_model`, which attaches the workspace's rules
    (:class:`~exulanica.epistemics.hosted_requests.WorkspaceRequestPolicy`), and the derivative
    worker's passes attach them per capture.
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

import hashlib
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import psycopg

from exulanica.api.account_runtime import (
    GUEST_PLAY_SECONDS_DEFAULT,
    AccountRuntime,
    load_account_runtime,
)
from exulanica.api.admission import AdmissionSettings
from exulanica.api.authorisation import API_TOKENS_ENV, TokenDirectory, load_token_directory
from exulanica.api.composer_rights import photograph_text_right
from exulanica.api.decision_host import (
    DecisionHost,
    answer_tokens,
    host_refusal,
    model_refusal,
    question_refusal,
)
from exulanica.api.installation import (
    MAINTENANCE_STATUS_ENV,
    PROFILE_ENV,
    Installation,
    load_installation,
)
from exulanica.api.instance_settings import (
    _COST_SCALE as _COST_SCALE,
)
from exulanica.api.instance_settings import (
    COMPARISON_WORKER_ENV as COMPARISON_WORKER_ENV,
)
from exulanica.api.instance_settings import (
    DATA_DIR_ENV,
    DERIVATIVE_WORKER_ENV,
    KINDS_FROM_PEOPLE_ENV,
    PLAYBACK_WORKER_ENV,
    PLAYBACK_WORKERS_ENV,
    READONLY_DATABASE_URL_ENV,
    SOCIETY_AUTHORED_WORLDS_ENV,
    SOCIETY_CONTROL_WORKER_ENV,
    SOCIETY_CONTROL_WORKSPACES_ENV,
    SOCIETY_MINUTE_COST_SCALE_ENV,
    SOCIETY_OF_THINGS_ENV,
    SOCIETY_TICK_INTERVAL_MS_ENV,
    WORLDS_ON_LAND_ENV,
    SocietySettingRefused,
    _comparison_player,
    _enabled,
    _explicitly_enabled,
    _kinds_from_people,
    _minute_cost_scale_milli,
    _playback_player,
    _playback_workers,
    _society_control_workspaces,
    _society_opening,
    _society_tick_interval_ms,
    _style_pack_uploads,
)
from exulanica.api.instance_settings import (
    SOCIETY_SETTING_REFUSALS as SOCIETY_SETTING_REFUSALS,
)
from exulanica.api.kind_drafts import KindDrafts
from exulanica.api.runtime_wiring import (
    AUTHORED_WORLDS_PROFILE as AUTHORED_WORLDS_PROFILE,
)
from exulanica.api.runtime_wiring import (
    _character_appearance_runtime,
    _material_runtime,
    _society_runtime,
)
from exulanica.api.service_refusals import ServiceRefusals
from exulanica.api.signal_comparison_runner import SignalComparisonRunner
from exulanica.api.society_comparison_runner import SocietyComparisonRunner
from exulanica.api.society_comparison_start import development_seeds
from exulanica.api.society_comparison_worker import SocietyComparisonWorker
from exulanica.api.society_control_worker import (
    PlaybackProcess,
    SocietyControlWorker,
    playback_configuration_sha256,
)
from exulanica.api.society_opening import (
    OPENING_OFF,
    SOCIETY_OPENING_ENV,
    SocietyOpening,
)
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.api.worker_factories import WorkerFactories
from exulanica.consent.place_name_rights import released_place_names
from exulanica.db.account_workspaces import PacedWorkspaces
from exulanica.db.session import DATABASE_URL_ENV, Database
from exulanica.door.runtime import DoorRuntime, door_runtime
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.epistemics.caption_embeddings import CaptionEmbeddingPass
from exulanica.epistemics.hosted_requests import (
    ReleasedPlaces,
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.ingest.vision import NebiusVisionModel
from exulanica.ingest.worker import DerivativeWorker, lease_seconds_for
from exulanica.models.client import ModelClient
from exulanica.models.egress import (
    EGRESS_ALLOWLIST_ENV,
    EgressConfigurationError,
    load_egress_allowlist,
)
from exulanica.models.errors import ModelError
from exulanica.models.manifest import MANIFEST_PATH, Manifest, Role, load_manifest
from exulanica.references import store as reference_store
from exulanica.references.adapters import ReferenceAdapter
from exulanica.references.catalogs import ReferenceSource, web_source
from exulanica.references.settings import (
    configured_adapter,
    plays_references_here,
    reads_pictures_here,
    reference_workspaces,
)
from exulanica.selection import creature_drafts
from exulanica.selection.creature_drafts import (
    creature_workspaces,
    plays_creatures_here,
)
from exulanica.spending import (
    DURABLE,
    PROCESS,
    SPENDING_ENV,
    WITNESS_DIR_ENV,
    DurableSpending,
    FileSpendingWitness,
    SpendingConfigurationError,
    durable_spending_from_env,
    spending_mode,
)
from exulanica.store.base import ContentAddressedStore
from exulanica.store.configured import ContentStores, content_stores
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.material_recipes import MaterialRuntime
from exulanica.world.society import world_society_seed
from exulanica.world.society_catalogs import ComparisonCatalogs, load_comparison_catalogs
from exulanica.world.society_controls import (
    DEFAULT_BASE_TICK_INTERVAL_MS,
    SPEEDS,
)
from exulanica.world.society_minute_cost import COST_SCALE_UNIT_MILLI, HostMinute
from exulanica.world.workspace_assets import WorkspaceAssetRuntime
from exulanica.world.workspace_preparations import RETAINED_BYTES_SETTING, retained_bytes_limit
from exulanica.world.workspace_style_packs import WorkspaceStylePackRuntime

if TYPE_CHECKING:
    from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime

__all__ = [
    "DATA_DIR_ENV",
    "DERIVATIVE_WORKER_ENV",
    "KINDS_FROM_PEOPLE_ENV",
    "PLAYBACK_WORKERS_ENV",
    "PLAYBACK_WORKER_ENV",
    "READONLY_DATABASE_URL_ENV",
    "SOCIETY_AUTHORED_WORLDS_ENV",
    "SOCIETY_CONTROL_WORKER_ENV",
    "SOCIETY_CONTROL_WORKSPACES_ENV",
    "SOCIETY_MINUTE_COST_SCALE_ENV",
    "SOCIETY_OF_THINGS_ENV",
    "SOCIETY_TICK_INTERVAL_MS_ENV",
    "Services",
    "SocietySettingRefused",
    "build_services",
]


_LOG = logging.getLogger(__name__)

#: How long one read of the workspaces a host plays and asks models for is used again, in seconds:
#: a route's refusal and every model ask's check, and the account role answers at most this often.
WATCHED_READ_SECONDS: Final = 5.0

#: How long the last good read is still used while reads fail, in seconds; after it, none is
#: watched, so a stalled account database never keeps a departed visitor's models asked.
WATCHED_STALE_SECONDS: Final = 60.0


class WatchedRead:
    """The last read of :meth:`AccountRuntime.watched_workspaces`, used again for
    :data:`WATCHED_READ_SECONDS`. A read that fails is not tried again for that long either, so
    callers do not queue one after another on a stalled account database; meanwhile the last good
    read stands for at most :data:`WATCHED_STALE_SECONDS`, and then none. The failure is logged by
    its class alone."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        #: When it was last asked, when it last answered, and that answer.
        self._asked: float | None = None
        self._good: tuple[float, frozenset[uuid.UUID]] | None = None

    def get(self, read: Callable[[], frozenset[uuid.UUID]]) -> frozenset[uuid.UUID]:
        with self._lock:
            now = self._clock()
            if self._asked is None or now - self._asked >= WATCHED_READ_SECONDS:
                try:
                    self._good = (now, read())
                except Exception as exc:
                    _LOG.warning(
                        "the watched workspaces could not be read: %s", type(exc).__qualname__
                    )
                # Stamped once the read has ended, so a read that took its whole timeout is not
                # tried again at once by the caller after it.
                self._asked = now = self._clock()
            if self._good is None or now - self._good[0] >= WATCHED_STALE_SECONDS:
                return frozenset()
            return self._good[1]


class _RuntimeAccounts:
    """The API's account runtime as a paced source reads it (PacedWorkspaces)."""

    def __init__(self, accounts: AccountRuntime) -> None:
        self._accounts = accounts

    def __call__(self) -> frozenset[uuid.UUID]:
        return self._accounts.active_owned_workspaces()

    def recent(self, guest_seconds: int) -> frozenset[uuid.UUID]:
        return self._accounts.recent_workspaces(guest_seconds)


@dataclass(frozen=True, slots=True)
class Services(ServiceRefusals, WorkerFactories):
    """Everything a request might need, and a note about what is not configured."""

    database: Database
    readonly_database: Database
    store: ContentAddressedStore
    tokens: TokenDirectory
    #: True when the executor is running as the writer because no read-only role was configured.
    executor_shares_the_write_role: bool
    #: None when no model credential is configured. Model-dependent endpoints say so.
    model_client: ModelClient | None
    #: Where no model credential is configured and the egress allowlist admits a provider on this
    #: computer (``Provider.on_this_computer``): a client that serves no manifest-bound role and
    #: asks only the models a world chose, refusing every other provider by name. None otherwise;
    #: every endpoint reading :attr:`model_client` still finds none. See :attr:`decision_client`.
    choice_client: ModelClient | None = None
    #: The only directory whose already-local files the environment admission route may name.
    #: None disables that write surface while retaining metadata and byte reads.
    environment_admission_root: Path | None = None
    #: True when this process drains the derivative queue itself. Defaulted to False so that a
    #: hand-constructed Services, which is how every test builds one, does not start a thread
    #: nobody asked for. ``build_services`` reads the environment and defaults the other way.
    runs_derivative_worker: bool = False
    #: Independent of the database and blob backups, set by the offline restore protocol.
    restore_state_path: Path | None = None
    #: The installation this process belongs to (``exulanica.api.installation``): its declared
    #: profile, identity and fact cache. None in tests and one-off tools that declare nothing.
    installation: Installation | None = None
    #: The society composition and authorization adapter. ``build_services`` always configures
    #: one; district bindings and host saved-world registrations are the host's to add.
    society_runtime: SocietyRuntime | None = None
    #: The seed a new society in a world starts from, from the workspace and the world's id. The
    #: server derives it (:func:`~exulanica.world.society.world_society_seed`); no request names
    #: one. A measurement that runs chosen seeds through the routes builds its own Services.
    society_seed: Callable[[uuid.UUID, str], str] = world_society_seed
    #: Explicit family definitions and current source authority for version-scoped appearance.
    character_appearance: CharacterAppearanceRuntime | None = None
    #: The published material catalog and each workspace's bake namespace. None when this
    #: instance was started without ``assets/textures``, which ``warnings`` says.
    materials: MaterialRuntime | None = None
    #: Each workspace's own admitted assets and prepared outputs (migration 0126). None in a
    #: hand-built Services, which makes the workspace asset routes answer 503.
    workspace_assets: WorkspaceAssetRuntime | None = None
    #: Each workspace's own style packs (migration 0173). None in a hand-built Services, which
    #: makes the workspace style pack routes answer 503.
    workspace_style_packs: WorkspaceStylePackRuntime | None = None
    #: The one store baked tiles live in, shared by every workspace because a baked tile is a
    #: pure function of public inputs (migration 0072). None in a hand-built Services, which
    #: makes the tile routes answer 503 rather than reach a store nobody configured.
    tiles: ContentAddressedStore | None = None
    #: Every namespace's store, as built for this process: the installation facts report its
    #: kind and description (no endpoint, bucket or credential).
    content_stores: ContentStores | None = None
    #: Dedicated account persistence and verified Google browser sessions, when configured.
    accounts: AccountRuntime | None = None
    #: The door for outside programs: the bridges ``EXULANICA_DOOR_BRIDGES`` declares, their
    #: grants' channels and the asker the decision host is given. None in a hand-built Services,
    #: which makes the door's routes refuse every door credential and its owner routes answer 503.
    door: DoorRuntime | None = None
    #: The kinds of world being drafted from people's words in this process, as jobs the page
    #: polls (:mod:`exulanica.api.kind_drafts`). Each Services holds its own.
    kind_drafts: KindDrafts = field(default_factory=KindDrafts)
    #: Explicit host allowlist. Empty leaves automatic society playback disabled.
    #: ``build_services`` reads it from ``EXULANICA_SOCIETY_CONTROL_WORKSPACES``.
    society_control_workspaces: tuple[uuid.UUID, ...] = ()
    #: Explicit host opt-in to discover all currently active account-owned workspaces.
    runs_society_control_worker: bool = False
    #: ``build_services`` reads it from ``EXULANICA_SOCIETY_TICK_INTERVAL_MS``.
    society_base_tick_interval_ms: int = DEFAULT_BASE_TICK_INTERVAL_MS
    #: How this host's machine compares with the measured ones, in thousandths
    #: (:data:`SOCIETY_MINUTE_COST_SCALE_ENV`); ``build_services`` reads it from the environment.
    society_minute_cost_scale_milli: int = COST_SCALE_UNIT_MILLI
    #: How many workspaces' claims a playback round runs at once (:data:`PLAYBACK_WORKERS_ENV`).
    society_playback_workers: int = 1
    #: Who plays the societies this host plays (:data:`PLAYBACK_WORKER_ENV`): ``here``, this
    #: process; ``process``, the playback worker's process; ``none``, nobody. ``here`` for a
    #: hand-built Services, as before the setting existed; ``build_services`` reads the setting.
    playback_player: Literal["here", "process", "none"] = "here"
    #: Whether the routes make a society of things (:data:`SOCIETY_OF_THINGS_ENV`); off for a
    #: hand-built Services, as for a host that does not set it.
    societies_of_things: bool = False
    #: Whether the routes take and keep a kind of place from a person, drafted or uploaded
    #: (:data:`KINDS_FROM_PEOPLE_ENV`); off for a hand-built Services, as for a host that does
    #: not set it.
    kinds_from_people: bool = False
    #: Whether a place made from a sentence stands on land (:data:`WORLDS_ON_LAND_ENV`); off for a
    #: hand-built Services, as for a host that does not set it.
    worlds_on_land: bool = False
    #: How a society that is made opens (:data:`SOCIETY_OPENING_ENV`, read by
    #: :mod:`exulanica.api.society_opening`): advanced until a share of its people is outdoors or,
    #: for a society of things, doing something, or not at all. Nothing for a hand-built
    #: Services, as before the setting existed; ``build_services`` reads the setting, whose default
    #: is the opening policy's (on).
    society_opening: SocietyOpening = OPENING_OFF
    #: The development seeds comparisons started from the application run on, in the seed
    #: catalog's order; ``build_services`` takes them from the seed catalog a new comparison is
    #: defined under, which commits their text.
    comparison_seeds: tuple[str, ...] = ()
    #: The catalogs a comparison is defined and scored under; None for the committed ones.
    comparison_catalogs: ComparisonCatalogs | None = None
    #: True when this process plays the comparisons started from the application; off for a
    #: hand-constructed Services, as the derivative worker is.
    runs_comparison_worker: bool = False
    #: True when the configuration names a process of its own that plays them
    #: (``EXULANICA_COMPARISON_WORKER=process``). With neither, no start is accepted.
    comparisons_played_elsewhere: bool = False
    #: True when this process plays the reference jobs requests queue
    #: (``EXULANICA_REFERENCE_WORKER``, on unless set off); off for a hand-constructed Services, as
    #: the derivative worker is.
    runs_reference_worker: bool = False
    #: Whether this process plays creature drafts (``EXULANICA_CREATURE_WORKER``), and for which
    #: workspaces (``EXULANICA_CREATURE_WORKSPACES``): none when absent, as each draft spends model
    #: calls.
    admits_workspace_models: bool = False
    runs_model_probe_worker: bool = False
    model_probe_workspaces: tuple[uuid.UUID, ...] = ()
    runs_creature_worker: bool = False
    creature_workspaces: tuple[uuid.UUID, ...] = ()
    #: The workspaces that may ask for web notes (``EXULANICA_REFERENCE_WORKSPACES``); none when
    #: absent. A source offered to the operator only is offered to these alone.
    reference_workspaces: tuple[uuid.UUID, ...] = ()
    #: Whether listed workspaces may ask for notes from their own pictures
    #: (``EXULANICA_REFERENCE_PICTURES``); off for a hand-constructed Services, and off unless set.
    reference_pictures: bool = False
    #: A reference source's adapter from this process's configuration, or a refusal naming what is
    #: missing; None for a hand-constructed Services.
    reference_adapter_for: Callable[[ReferenceSource], ReferenceAdapter] | None = None
    #: The place-name right's resolver, asked by every workspace policy this instance attaches
    #: whether a confirmed place's name may go to a hand-over. ``build_services`` injects the
    #: right's own (``exulanica.consent.place_name_rights``); the one that releases nothing is
    #: the default of a hand-built instance, so an instance nobody wired to the right sends no
    #: place's name.
    released_place_names: ReleasedPlaces = no_place_released
    #: How much work this process accepts at once (:mod:`exulanica.api.admission`). The declared
    #: defaults for a hand-built instance; ``build_services`` reads ``EXULANICA_API_*`` and
    #: ``EXULANICA_INTAKE_QUEUED_JOBS``.
    admission: AdmissionSettings = field(default_factory=AdmissionSettings)
    #: How this instance spends on hosted models: ``durable``, admitted by the spending authority
    #: every process shares (``spending``), or ``process``, within its own budget fuse alone; None
    #: where it holds no provider credential. ``build_services`` reads ``EXULANICA_SPENDING``.
    spending_mode: str | None = None
    #: The durable spending authority the model client is composed with, when durable.
    spending: DurableSpending | None = None
    #: The last read of the workspaces account discovery plays and asks models for.
    watched: WatchedRead = field(default_factory=WatchedRead, compare=False, repr=False)

    @property
    def society_control_enabled(self) -> bool:
        return self.runs_society_control_worker or bool(self.society_control_workspaces)

    @property
    def decision_client(self) -> ModelClient | None:
        """The client a world's chosen models are asked through, and judged refused or not by:
        the process's model client, or where it has none, the one asking only chosen models
        (:attr:`choice_client`), so a deployment with no model credential can still ask a model
        on this computer. None where neither exists."""
        return self.model_client if self.model_client is not None else self.choice_client

    @property
    def discovers_model_workspaces(self) -> bool:
        """Whether this host asks models for workspaces account discovery finds, beside the ones
        its environment lists: only where discovery is on and spending is durable, so every ask
        is admitted against the asking workspace's own grant. Under process spending nothing but
        the listed workspaces is asked for, since nothing would bound what one visitor spends.
        A durable authority (``spending``) is composed only under durable spending."""
        return (
            self.runs_society_control_worker
            and self.accounts is not None
            and self.spending is not None
        )

    def watched_workspaces(self) -> frozenset[uuid.UUID]:
        """What account discovery plays and asks models for: every active owner's workspace and
        the guests' seen within the play window (:meth:`AccountRuntime.watched_workspaces`),
        read at most every :data:`WATCHED_READ_SECONDS`; empty without accounts."""
        accounts = self.accounts
        if accounts is None:
            return frozenset()
        return self.watched.get(accounts.watched_workspaces)

    def asks_models_for(self, workspace_id: uuid.UUID) -> bool:
        """Whether this host asks models for a workspace: one its environment lists, or one
        account discovery is watching where :attr:`discovers_model_workspaces`."""
        if workspace_id in self.society_control_workspaces:
            return True
        return self.discovers_model_workspaces and workspace_id in self.watched_workspaces()

    def _guest_play(self) -> tuple[int, int] | None:
        """The guests' play window and playing maximum, where discovery plays guests' towns."""
        guest = None if self.accounts is None else self.accounts.guest
        if not self.runs_society_control_worker or guest is None:
            return None
        return guest.play_seconds, guest.playing_maximum

    def request_policy(
        self,
        workspace_id: uuid.UUID,
        connection: Callable[[], AbstractContextManager[psycopg.Connection]],
        *,
        released_places: ReleasedPlaces,
    ) -> WorkspaceRequestPolicy:
        """The workspace's rules for what a hosted request may carry, as this instance applies them.

        ``connection`` lends or opens an idle connection scoped to ``workspace_id``; the policy
        reads the saved names, the photograph rights and the place-name rights on it as each
        request leaves. ``released_places`` is required, so every caller states which place names
        its requests may carry: :attr:`released_place_names` where a use the account holder can
        allow describes those requests, and ``no_place_released`` everywhere else. A caller that
        passed nothing would inherit grants made for somebody else's requests.
        """
        return WorkspaceRequestPolicy(
            workspace_id,
            connection=connection,
            photograph_right=photograph_text_right,
            released_places=released_places,
        )

    def hosted_model(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID
    ) -> ModelClient | None:
        """The model client for one request of one workspace, or None with no credential.

        The process's client with this workspace's rules attached, lent the request's own
        connection, which is idle between the route's queries. A route sends through nothing else.
        """
        if self.model_client is None:
            return None
        # The Companion's routes are this factory's callers, and their requests are the ones the
        # place-name uses offer: exulanica/consent/place-name-uses.v1.json.
        return self.model_client.with_policy(
            self.request_policy(
                workspace_id, borrowing(connection), released_places=self.released_place_names
            )
        )

    def host_minute(self) -> HostMinute:
        """What this host gives a simulated minute: the longest wait it leaves between two
        minutes of a society at play, its base interval at its slowest speed, and its machine's
        scale against the measured ones. Making a society admits its people by it."""
        return HostMinute(
            slowest_minute_ms=self.society_base_tick_interval_ms // min(SPEEDS),
            cost_scale_milli=self.society_minute_cost_scale_milli,
        )

    def decision_host(self) -> DecisionHost | None:
        """What asks the models a society's owner chose before a minute, for every role its engine
        hosts, or None without a society runtime. A model is asked only for a society with an open
        living session, each ask under the session's own bound where spending is durable.

        The workspaces this host's environment lists are asked for, and, where
        :attr:`discovers_model_workspaces`, the ones account discovery watches; any other workspace
        discovery adds is played by its routine alone. Each ask carries the workspace's rules, with
        no place's name released: a role's decision is not a use a place-name right offers.
        """
        if self.society_runtime is None:
            return None
        return DecisionHost(
            database=self.database,
            runtime=self.society_runtime,
            client=self.decision_client,
            workspaces=frozenset(self.society_control_workspaces),
            policy_for=self.person_decision_policy,
            manifest=load_manifest(),
            manifest_sha256=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            external=None if self.door is None else self.door.asker(),
            discovered=self.watched_workspaces if self.discovers_model_workspaces else None,
            spending_refusals=self.spending_refusals if self.spending is not None else None,
            spending=self.spending,
            binding_source=self.workspace_execution_source
            if self.admits_workspace_models
            else None,
        )

    def workspace_choice_manifest(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, engine: str | None
    ) -> Manifest:
        """A read-only offered catalog from replayed evidence, with recorded probe rates."""
        from exulanica.world.workspace_model_bindings import proven_bindings, with_bindings

        manifest = load_manifest()
        if not self.admits_workspace_models or engine is None:
            return manifest
        return with_bindings(manifest, proven_bindings(connection, workspace_id, engine, manifest))

    def workspace_execution_source(
        self, workspace_id: uuid.UUID, engine: str, selected: frozenset[str]
    ) -> tuple[ModelClient, Manifest, str] | None:
        """Fresh prices and a stored source for explicitly chosen, currently proven candidates.

        Provider reads enclose no database session. Final epoch validation and snapshot append
        share the workspace lock; every subsequent candidate ask checks the epoch again.
        """
        import datetime as dt

        from exulanica.world.workspace_lock import lock_workspace
        from exulanica.world.workspace_model_bindings import (
            BindingSnapshotRepository,
            priced_snapshot,
            proven_bindings,
        )

        client = self.model_client
        manifest = load_manifest()
        if not self.admits_workspace_models or client is None or self.spending is None:
            return None
        from exulanica.deletion.restore import RestoreRefused, verify_restore

        try:
            verify_restore(self.readonly_database, self.restore_state_path)
        except RestoreRefused:
            return None
        selected = selected - manifest.models.keys()
        if not selected:
            return None
        with self.readonly_database.session(workspace_id) as connection:
            if connection.execute(
                "select 1 from restore_control where state<>'complete'"
            ).fetchone():
                return None
            bindings = tuple(
                b
                for b in proven_bindings(connection, workspace_id, engine, manifest)
                if b.spec.model_id in selected
            )
        if not bindings:
            return None
        try:
            prices = {}
            for provider in sorted({b.spec.provider for b in bindings}):
                prices.update(client.provider_prices(provider))
            read_at = dt.datetime.now(dt.UTC)
            with self.database.session(workspace_id) as connection, connection.transaction():
                lock_workspace(connection, workspace_id)
                current = tuple(
                    b
                    for b in proven_bindings(connection, workspace_id, engine, manifest)
                    if b.spec.model_id in selected
                )
                if current != bindings:
                    return None
                scoped, document = priced_snapshot(manifest, bindings, prices, read_at=read_at)
                digest = BindingSnapshotRepository(connection, workspace_id).record(document)
        except (ValueError, ModelError, KeyError):
            return None

        def guard() -> bool:
            try:
                verify_restore(self.readonly_database, self.restore_state_path)
            except RestoreRefused:
                return False
            if dt.datetime.now(dt.UTC) - read_at > dt.timedelta(seconds=60):
                return False
            with self.readonly_database.session(workspace_id) as connection:
                if connection.execute(
                    "select 1 from restore_control where state<>'complete'"
                ).fetchone():
                    return False
                current = tuple(
                    b
                    for b in proven_bindings(connection, workspace_id, engine, manifest)
                    if b.spec.model_id in selected
                )
                return current == bindings

        try:
            bound = client.with_chosen_manifest(
                scoped, {b.spec.model_id: (b.role, b.prompt_version) for b in bindings}, guard=guard
            )
        except ValueError:
            return None
        return bound, scoped, digest

    def person_decision_policy(self, workspace_id: uuid.UUID) -> WorkspaceRequestPolicy:
        """The rules any role's decision is asked under, by the host and by a comparison alike:
        the workspace's own, with no place's name released."""
        return self.request_policy(
            workspace_id,
            lambda: self.readonly_database.session(workspace_id),
            released_places=no_place_released,
        )

    def comparison_runner(
        self, workspace_id: uuid.UUID, world_id: str, actor: uuid.UUID
    ) -> SocietyComparisonRunner | None:
        """What defines and runs a comparison of the models that decide for a world's people,
        in one workspace and world as ``actor``; None where no society runtime is configured."""
        if self.society_runtime is None:
            return None
        return SocietyComparisonRunner(
            database=self.database,
            runtime=self.society_runtime,
            client=self.model_client,
            policy_for=self.person_decision_policy,
            manifest=load_manifest(),
            manifest_sha256=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            workspace_id=workspace_id,
            world_id=world_id,
            actor=actor,
            catalogs=self.comparison_catalogs or load_comparison_catalogs(),
        )

    def signal_comparison_runner(
        self, workspace_id: uuid.UUID, world_id: str, actor: uuid.UUID
    ) -> SignalComparisonRunner:
        """What defines and runs a comparison of the models that decide for a town's signals, in
        one workspace and world as ``actor``."""
        return SignalComparisonRunner(
            database=self.database,
            client=self.model_client,
            policy_for=self.person_decision_policy,
            manifest=load_manifest(),
            manifest_sha256=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            workspace_id=workspace_id,
            world_id=world_id,
            actor=actor,
        )

    def build_comparison_worker(self, *, keeps_share: bool) -> SocietyComparisonWorker | None:
        """What plays the comparisons started from the application, for the workspaces this host
        asks models for, or None where it asks models for none or has no society runtime.

        Where :attr:`discovers_model_workspaces`, the watched workspaces are played every round
        and every active account workspace once every few minutes
        (:data:`~exulanica.api.society_comparison_worker.SLOW_SCAN_SECONDS`): a start is made
        only in a watched workspace, and a comparison a visitor started finishes after they
        leave, within its own bound and their grant, while visitors who are not there cost no
        round."""
        accounts = self.accounts
        discovers = self.discovers_model_workspaces and accounts is not None
        if self.society_runtime is None or not (self.society_control_workspaces or discovers):
            return None
        return SocietyComparisonWorker(
            self.database,
            runner_for=self.comparison_runner,
            client=self.model_client,
            manifest=load_manifest(),
            workspaces=self.society_control_workspaces,
            keeps_share=keeps_share,
            signal_runner_for=self.signal_comparison_runner,
            workspace_source=self.watched_workspaces if discovers else None,
            slow_source=(
                accounts.active_owned_workspaces if discovers and accounts is not None else None
            ),
        )

    def references_offered_here(self) -> bool:
        """Whether this installation may offer the web source at all: a source offered to the
        operator only is offered on no installation whose profile is ``public``."""
        source = web_source()
        if source is None:
            return False
        profile = self.installation.profile if self.installation is not None else None
        return source.availability == "everyone" or profile is None or profile.id != "public"

    def serves_references_to(self, workspace_id: uuid.UUID) -> bool:
        """Whether a worker here takes this workspace's reference jobs: references are played here,
        this installation may offer the source, and the workspace is listed."""
        return (
            self.runs_reference_worker
            and self.references_offered_here()
            and workspace_id in self.reference_workspaces
        )

    def pictures_offered_to(self, workspace_id: uuid.UUID) -> bool:
        """Whether this workspace may ask for notes from its own pictures here: references are
        served to it, pictures are turned on, and the installation is not public, whatever the
        web source's catalog entry offers."""
        return self.picture_reading_here() and self.serves_references_to(workspace_id)

    def picture_reading_here(self) -> bool:
        """Whether this process reads a person's pictures at all: pictures are turned on and the
        installation is not public."""
        profile = self.installation.profile if self.installation is not None else None
        return self.reference_pictures and (profile is None or profile.id != "public")

    def sweep_references(self) -> int:
        """End the reference jobs no worker here will take, for every workspace this process knows
        (its tokens', its accounts' and its listed ones), blanking their words; expire the stale
        queued ones of those it serves; clear their searches' query text past its retention. Run at
        startup, so a workspace dropped from the list, a worker set off or a move to a public
        profile leaves nothing waiting. Returns how many jobs it ended."""
        known = set(self.reference_workspaces)
        if self.tokens is not None:
            known |= set(self.tokens.workspaces)
        if self.accounts is not None:
            known |= set(self.accounts.active_owned_workspaces())
        ended = 0
        for workspace_id in sorted(known):
            with self.database.session(workspace_id) as connection:
                if self.serves_references_to(workspace_id):
                    ended += reference_store.expire_unclaimed(connection, workspace_id)
                else:
                    ended += reference_store.end_unserved(connection, workspace_id)
                cleared = reference_store.try_clear_old_queries(connection, workspace_id)
                if isinstance(cleared, reference_store.ClearFailed):
                    _LOG.warning(
                        "clearing old reference queries failed at startup; it is retried",
                        extra={"failure": cleared.failure},
                    )
        return ended

    def serves_creatures_to(self, workspace_id: uuid.UUID) -> bool:
        """Whether a worker here drafts this workspace's creatures: drafts are played here, a model
        client and the looks namespace exist, and the workspace is listed."""
        return (
            self.runs_creature_worker
            and self.model_client is not None
            and self.content_stores is not None
            and workspace_id in self.creature_workspaces
        )

    def creature_offer_refusal(self, workspace_id: uuid.UUID) -> str | None:
        """Why this workspace may not ask for a creature here, by code, or None when it may: this
        process has no model client, or no worker here drafts the workspace's creatures."""
        if self.serves_creatures_to(workspace_id):
            return None
        not_run_here, no_models = creature_drafts.OFFER_REFUSALS
        return no_models if self.model_client is None else not_run_here

    def sweep_creatures(self) -> int:
        """End the creature drafts no worker here will take, for every workspace this process knows,
        blanking their words; expire the stale queued ones of those it serves. Run at startup.
        Returns how many."""
        known = set(self.creature_workspaces)
        if self.tokens is not None:
            known |= set(self.tokens.workspaces)
        if self.accounts is not None:
            known |= set(self.accounts.active_owned_workspaces())
        ended = 0
        for workspace_id in sorted(known):
            with self.database.session(workspace_id) as connection:
                if self.serves_creatures_to(workspace_id):
                    ended += creature_drafts.expire_unclaimed(connection, workspace_id)
                else:
                    ended += creature_drafts.end_unserved(connection, workspace_id)
        return ended

    def model_probes_served(self, workspace_id: uuid.UUID) -> bool:
        return (
            self.runs_model_probe_worker
            and workspace_id in self.model_probe_workspaces
            and self.model_client is not None
            and self.spending is not None
        )

    def model_host_refusal(
        self, workspace_id: uuid.UUID, role: DecisionRole, engine: str | None = None
    ) -> str | None:
        """Why this host asks no model for a workspace's subjects of ``role``, or None when it
        asks them.

        The facts :meth:`decision_host` acts on: the workspaces it asks models for
        (:meth:`asks_models_for`), the process's client, and what is left of its budget and of the
        share the role's decisions may spend, under the contract a society's ``engine`` is asked
        under (the role's own with none). A code from ``HOST_REFUSALS``.
        """
        if not self.asks_models_for(workspace_id):
            return "models_not_run_here"
        return host_refusal(role, self.decision_client, load_manifest(), _asked(role, engine))

    def smallest_reservation_usd(self) -> dict[str, Decimal]:
        """By provider, the smallest reservation one attempt of any model a person may be given
        takes: its answer bound at its prices with no prompt. A remainder below it admits no ask
        of that provider's models; empty with no model client."""
        client = self.decision_client
        if client is None:
            return {}
        floors: dict[str, Decimal] = {}
        for spec in load_manifest().models.values():
            if not (spec.is_chat and spec.answering):
                continue
            usd = client.budget.estimate_usd(spec, max_tokens=answer_tokens(spec) or 0)
            floors[spec.provider] = min(usd, floors.get(spec.provider, usd))
        return floors

    def choice_refusal(
        self,
        role: DecisionRole,
        model: Mapping[str, str],
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        engine: str | None = None,
    ) -> str | None:
        """Why a subject's chosen model is not asked here, or None: a code from MODEL_REFUSALS.

        The question is judged by the workspace's rules as the host judges it, on ``connection``,
        which the caller lends idle: for a society's ``engine``, that engine's description alone.
        """
        manifest = self.workspace_choice_manifest(connection, workspace_id, engine)
        client = self.decision_client
        if (
            client is not None
            and model["model_id"] not in load_manifest().models
            and model["model_id"] in manifest.models
        ):
            client = client.with_chosen_manifest(
                manifest,
                {
                    key: (role.key, role.terms(engine).prompt_version)
                    for key in manifest.models.keys() - load_manifest().models.keys()
                },
            )
        refusal = model_refusal(role, client, manifest, _asked(role, engine), model)
        if refusal is not None or self.decision_client is None:
            return refusal
        assert client is not None
        return question_refusal(
            role,
            client.with_policy(
                self.request_policy(
                    workspace_id, borrowing(connection), released_places=no_place_released
                )
            ),
            model["model_id"],
            engine,
        )

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
                self.accounts.watched_workspaces
                if self.runs_society_control_worker and self.accounts is not None
                else None
            ),
            base_tick_interval_ms=self.society_base_tick_interval_ms,
            before_minute=(None if (host := self.decision_host()) is None else host.before_minute),
            workers=self.society_playback_workers,
            spending=self.spending,
        )

    def playback_configuration_sha256(self) -> str:
        """The digest of what this host's playback plays, which the playback process holds its
        lock under and an API that leaves playback to it reads that lock by."""
        return playback_configuration_sha256(
            self.society_control_workspaces,
            account_discovery=self.runs_society_control_worker,
            base_tick_interval_ms=self.society_base_tick_interval_ms,
            guests=self._guest_play(),
        )

    def playback_process(self) -> PlaybackProcess | None:
        """What this process says of the process that plays its societies, where one does
        (``process`` in :data:`PLAYBACK_WORKER_ENV`); None where this process plays them, where
        nothing plays them, or where playback is not configured."""
        if self.playback_player != "process" or not self.society_control_enabled:
            return None
        return PlaybackProcess(
            self.database,
            workspaces=self.society_control_workspaces,
            account_discovery=self.runs_society_control_worker,
            workspace_source=(
                self.accounts.watched_workspaces
                if self.runs_society_control_worker and self.accounts is not None
                else None
            ),
            base_tick_interval_ms=self.society_base_tick_interval_ms,
            guests=self._guest_play(),
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
            if self.choice_client is not None:
                notes.append(
                    "only models on this computer are asked here: a being whose owner chose one "
                    "is asked it, and a being whose owner chose a hosted model is decided for by "
                    "its routine."
                )
        else:
            # Said only where a playback host asks models for people: for the workspaces the
            # environment lists, or for the watched ones under durable spending; a host enabled by
            # account discovery alone under process spending asks nobody.
            spent = (
                next(
                    (
                        refused
                        for role in (decision_roles().deciding_for("person"),)
                        if (
                            refused := host_refusal(
                                role, self.model_client, load_manifest(), role.contract()
                            )
                        )
                        is not None
                    ),
                    None,
                )
                if self.society_control_workspaces or self.discovers_model_workspaces
                else None
            )
            if spent == "process_budget_spent":
                notes.append(
                    "this process has spent its model budget (EXULANICA_BUDGET_USD or "
                    "EXULANICA_BUDGET_MAX_CALLS): what is left fits no ask of a person's chosen "
                    "model, until it restarts. People a model runs are decided by their routine, "
                    "and nothing is asked for them."
                )
            elif spent == "process_share_spent":
                notes.append(
                    "this process's model budget is down to the part its decision contract keeps "
                    "for other work (process_reserve_percent of EXULANICA_BUDGET_USD and "
                    "EXULANICA_BUDGET_MAX_CALLS): until it restarts, people a model runs are "
                    "decided by their routine, and the rest stays for the Companion and "
                    "ingestion."
                )
            for provider, reason in sorted(self.model_client.refusals.items()):
                notes.append(
                    f"provider {provider} is refused by this process ({reason}), so no model it "
                    "serves is asked here, and a person run by one is decided by their routine."
                )
        if self.model_client is not None and self.spending_mode == PROCESS:
            notes.append(
                f"{SPENDING_ENV} is {PROCESS}: this process spends within its own budget "
                "(EXULANICA_BUDGET_USD and EXULANICA_BUDGET_MAX_CALLS) alone, which a restart or "
                "another process starts again at zero. No durable spending authority admits its "
                "hosted calls."
            )
        if self.spending is not None and self.spending.witness is None:
            notes.append(
                f"{WITNESS_DIR_ENV} is not set, so this process refuses to spend under any "
                "witnessed spending authority. Work that asks no model is unaffected."
            )
        elif (
            self.spending is not None
            and isinstance(self.spending.witness, FileSpendingWitness)
            and self.spending.witness.directory_id() is None
        ):
            notes.append(
                f"{WITNESS_DIR_ENV} names a directory with no witness directory marker, so this "
                "process refuses to spend under any authority whose witness directory is "
                "recorded (witness_directory_mismatch). An operator command writes the marker in "
                "the installation's witness directory. Work that asks no model is unaffected."
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
        if self.character_appearance is None:
            notes.append(
                "no character runtime is configured here, so saving a look answers 424 and a "
                "person's chosen look lasts only as long as their browser keeps it."
            )
        if self.society_runtime is None:
            notes.append(
                "no society runtime is configured, so no world holds inhabitants here and "
                "creating a society answers 424. Nothing already saved is affected: a society "
                "is a simulation started on top of a world, never part of the world itself."
            )
        elif not self.society_control_enabled:
            notes.append(
                "a person can bring inhabitants into a saved world of their own, and nothing "
                "else does: no world holds a society until its owner asks for one. "
                f"{SOCIETY_CONTROL_WORKER_ENV} is off and {SOCIETY_CONTROL_WORKSPACES_ENV} names "
                "no workspace, so a society advances only when somebody advances it, one "
                "simulated minute at a time."
            )
        elif self.playback_player == "process":
            notes.append(
                f"{PLAYBACK_WORKER_ENV} is process: this process plays no society and seals no "
                "traffic. exulanica-playback-worker does, and while no such process runs with "
                "this configuration a world's playback control says playback has stopped."
            )
        elif self.playback_player == "none":
            notes.append(
                f"{PLAYBACK_WORKER_ENV} is off: nothing plays the societies of the workspaces "
                "this host lists, so each advances only when somebody advances it, one simulated "
                "minute at a time."
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
            # Paced as the worker commands are: the workspaces whose people are there every pass,
            # every account workspace once in a while.
            workspace_source=(
                PacedWorkspaces(
                    _RuntimeAccounts(self.accounts),
                    guest_seconds=(
                        self.accounts.guest.play_seconds
                        if self.accounts.guest is not None
                        else GUEST_PLAY_SECONDS_DEFAULT
                    ),
                )
                if self.accounts is not None
                else None
            ),
            vision=NebiusVisionModel(self.model_client) if self.model_client else None,
            embedding_pass=(
                CaptionEmbeddingPass(self.model_client, released_places=self.released_place_names)
                if self.model_client
                else None
            ),
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
    environ: Mapping[str, str] | None = None,
    *,
    model_client: ModelClient | None = None,
    spending_label: str = "api",
) -> Services:
    """Resolve configuration into services, or fail at startup with the reason.

    ``model_client`` is injectable so a test can supply a scripted one. Everything else comes
    from the environment, because it is deployment configuration rather than a decision the
    code gets to make, except the place-name right's resolver: every instance reads the right,
    because what leaves with a place's name is the account holder's decision rather than a
    deployment's. Routes, the society runtime and the derivative worker all ask this one.

    How the instance spends is stated, never defaulted: a process holding a provider credential
    refuses to start without ``EXULANICA_SPENDING`` (:func:`exulanica.spending.spending_mode`).
    Under ``durable`` the model client, an injected one included, is composed with the durable
    spending authority, named on what it reserves by ``spending_label``.
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

    mode = spending_mode(environ, credentials_configured=_role_credentials_set(environ))
    spending = (
        durable_spending_from_env(environ, database, label=spending_label)
        if mode == DURABLE
        else None
    )
    installation = load_installation(environ)
    client = model_client
    if client is None and _role_credentials_set(environ):
        client = ModelClient()
    if client is not None and spending is not None and client.spending_source is None:
        client = client.with_spending_source(spending)
    choice_client = None
    if client is None and _admits_a_provider_on_this_computer(environ):
        choice_client = ModelClient(local_only=True)
        if spending is not None:
            choice_client = choice_client.with_spending_source(spending)
    if (
        accounts is not None
        and accounts.guest is not None
        and client is not None
        and spending is None
    ):
        # A guest's allowance is a grant under the durable authority. Under process spending a
        # visitor has none, and every one of them would spend from the fuse the owners share.
        raise SpendingConfigurationError(
            "a guest entry (EXULANICA_GUEST_ENTRY) with a model credential needs "
            "EXULANICA_SPENDING=durable: under process spending a visitor has no allowance of "
            "their own"
        )
    stores = content_stores(environ, data_dir=data_dir)
    store = stores.blobs
    comparison_player = _comparison_player(env_get("COMPARISON_WORKER", environ))
    playback_player = _playback_player(env_get("PLAYBACK_WORKER", environ))

    return Services(
        database=database,
        readonly_database=Database(url=readonly_url) if readonly_url else database,
        store=store,
        tokens=tokens,
        executor_shares_the_write_role=readonly_url is None,
        model_client=client,
        choice_client=choice_client,
        accounts=accounts,
        door=door_runtime(database, environ, open_to=_door_open_to(accounts)),
        environment_admission_root=data_dir / "environment-inbox",
        materials=_material_runtime(stores, environ),
        workspace_assets=WorkspaceAssetRuntime(
            stores=stores.workspace_assets, retained_bytes_limit=retained_bytes_limit(environ)
        ),
        workspace_style_packs=WorkspaceStylePackRuntime.over(
            stores.workspace_style_packs,
            retained_bytes_limit=retained_bytes_limit(environ),
            uploads=_style_pack_uploads(environ),
            generated_pieces=stores.generated_pieces,
        ),
        character_appearance=_character_appearance_runtime(store, environ, stores.workspace_assets),
        tiles=stores.tiles,
        content_stores=stores,
        society_runtime=_society_runtime(store, environ),
        runs_derivative_worker=_enabled(env_get("DERIVATIVE_WORKER", environ)),
        runs_society_control_worker=_explicitly_enabled(env_get("SOCIETY_CONTROL_WORKER", environ)),
        society_control_workspaces=_society_control_workspaces(
            env_get("SOCIETY_CONTROL_WORKSPACES", environ)
        ),
        society_base_tick_interval_ms=_society_tick_interval_ms(
            env_get("SOCIETY_TICK_INTERVAL_MS", environ)
        ),
        society_minute_cost_scale_milli=_minute_cost_scale_milli(
            env_get("MINUTE_COST_SCALE", environ)
        ),
        society_playback_workers=_playback_workers(env_get("PLAYBACK_WORKERS", environ)),
        playback_player=playback_player,
        societies_of_things=_explicitly_enabled(
            env_get("SOCIETY_OF_THINGS", environ),
            "society_of_things_not_boolean",
            SOCIETY_OF_THINGS_ENV,
        ),
        kinds_from_people=_kinds_from_people(environ),
        worlds_on_land=_explicitly_enabled(
            env_get("WORLDS_ON_LAND", environ), "worlds_on_land_not_boolean", WORLDS_ON_LAND_ENV
        ),
        society_opening=_society_opening(env_get("SOCIETY_OPENING", environ)),
        comparison_seeds=development_seeds(load_comparison_catalogs()),
        runs_comparison_worker=comparison_player == "here",
        comparisons_played_elsewhere=comparison_player == "process",
        runs_reference_worker=plays_references_here(env_get("REFERENCE_WORKER", environ)),
        reference_workspaces=reference_workspaces(env_get("REFERENCE_WORKSPACES", environ)),
        reference_pictures=reads_pictures_here(env_get("REFERENCE_PICTURES", environ)),
        admits_workspace_models=_explicitly_enabled(
            env_get("WORKSPACE_MODELS", environ),
            "workspace_models_not_boolean",
            "EXULANICA_WORKSPACE_MODELS",
        ),
        runs_model_probe_worker=_explicitly_enabled(
            env_get("MODEL_PROBE_WORKER", environ),
            "model_probe_worker_not_boolean",
            "EXULANICA_MODEL_PROBE_WORKER",
        ),
        model_probe_workspaces=tuple(
            uuid.UUID(value.strip())
            for value in (env_get("MODEL_PROBE_WORKSPACES", environ) or "").split(",")
            if value.strip()
        ),
        runs_creature_worker=plays_creatures_here(env_get("CREATURE_WORKER", environ)),
        creature_workspaces=creature_workspaces(env_get("CREATURE_WORKSPACES", environ)),
        reference_adapter_for=lambda source: configured_adapter(source, environ),
        # A declared installation's marker is its profile's; otherwise the setting, if any.
        restore_state_path=installation.restore_state_path,
        installation=installation,
        released_place_names=released_place_names,
        admission=AdmissionSettings.from_env(environ),
        spending_mode=mode,
        spending=spending,
    )


def _door_open_to(accounts: AccountRuntime | None) -> Callable[[uuid.UUID], bool] | None:
    """Whether a workspace is open to the door, where the deployment has accounts: its owner's
    account and owner membership stand and it is not disabled, read for that workspace alone
    through the account role on every call, so a disabled workspace's doors close at their next
    request. An account database that cannot be read refuses the request
    (``account_unavailable``) rather than opening it."""
    if accounts is None:
        return None

    def open_to(workspace_id: uuid.UUID) -> bool:
        return accounts.owned_workspace_active(workspace_id)

    return open_to


def _role_credentials_set(environ: Mapping[str, str]) -> bool:
    """Whether the credential of every provider serving a manifest-bound role is set.

    The variable names are the manifest's (``providers[].api_key_env``), never written here: a
    process without them serves no model and says so in ``Services.warnings``.
    """
    manifest = load_manifest()
    return all(environ.get(name) for name in manifest.credential_variables(manifest.roles))


def _admits_a_provider_on_this_computer(environ: Mapping[str, str]) -> bool:
    """Whether the egress allowlist this process states admits a provider on this computer, whose
    models a world may choose with no credential configured (``Services.choice_client``). An
    absent or unreadable allowlist admits none: it is then refused where a client is built."""
    try:
        egress = load_egress_allowlist(environ)
    except EgressConfigurationError:
        return False
    return any(
        egress.declares(provider.base_url)
        for provider in load_manifest().providers.values()
        if provider.on_this_computer
    )


def describe_configuration(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """What an operator needs to set, and whether it is set. Never the values themselves."""
    environ = os.environ if environ is None else environ
    names = (
        DATABASE_URL_ENV,
        READONLY_DATABASE_URL_ENV,
        DATA_DIR_ENV,
        DERIVATIVE_WORKER_ENV,
        SOCIETY_CONTROL_WORKER_ENV,
        SOCIETY_CONTROL_WORKSPACES_ENV,
        SOCIETY_TICK_INTERVAL_MS_ENV,
        SOCIETY_MINUTE_COST_SCALE_ENV,
        SOCIETY_OPENING_ENV,
        API_TOKENS_ENV,
        *AdmissionSettings.variables(),
        env_name(RETAINED_BYTES_SETTING),
        *sorted(
            {
                provider.api_key_env
                for provider in load_manifest().providers.values()
                if provider.api_key_env is not None
            }
        ),
        "EXULANICA_GOOGLE_CLIENT_ID",
        "EXULANICA_GOOGLE_CLIENT_SECRET",
        "EXULANICA_GOOGLE_CALLBACK_URI",
        "EXULANICA_GOOGLE_RETURN_URIS",
        "EXULANICA_ACCOUNT_BROWSER_ORIGINS",
        "EXULANICA_ACCOUNT_DATABASE_URL",
        EGRESS_ALLOWLIST_ENV,
        PROFILE_ENV,
        MAINTENANCE_STATUS_ENV,
        "EXULANICA_CODE_REVISION",
        "EXULANICA_IMAGE_BACKEND",
        "EXULANICA_IMAGE_CLIENT",
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


def _asked(role: DecisionRole, engine: str | None) -> DecisionContract:
    """The contract ``engine``'s subjects of ``role`` are asked under, as the host asks them; the
    role's own where no engine is named."""
    return role.contract() if engine is None else role.contract(role.terms(engine).versions)
