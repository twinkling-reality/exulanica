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
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import psycopg

from exulanica.api.account_runtime import AccountRuntime, load_account_runtime
from exulanica.api.admission import AdmissionSettings
from exulanica.api.authorisation import API_TOKENS_ENV, TokenDirectory, load_token_directory
from exulanica.api.comparison_spending import bound_room_refusal
from exulanica.api.composer_rights import photograph_text_right
from exulanica.api.decision_host import (
    DecisionHost,
    answer_tokens,
    host_refusal,
    model_refusal,
    question_refusal,
    share_kept,
)
from exulanica.api.installation import (
    MAINTENANCE_STATUS_ENV,
    PROFILE_ENV,
    Installation,
    installation_facts,
    load_installation,
)
from exulanica.api.kind_drafts import KindDrafts
from exulanica.api.reference_pictures import reference_picture_source
from exulanica.api.signal_comparison_runner import SignalComparisonRunner
from exulanica.api.society_comparison_runner import SocietyComparisonRunner
from exulanica.api.society_comparison_start import development_seeds
from exulanica.api.society_comparison_worker import SocietyComparisonWorker
from exulanica.api.society_control_worker import (
    PlaybackProcess,
    SocietyControlWorker,
    playback_configuration_sha256,
)
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from exulanica.consent.place_name_rights import released_place_names
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
from exulanica.models.client import PROVIDER_CREDENTIAL_ABSENT, ModelClient
from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest
from exulanica.models.spending import SpendingRefused
from exulanica.references import store as reference_store
from exulanica.references.adapters import ReferenceAdapter
from exulanica.references.catalogs import ReferenceSource, web_source
from exulanica.references.settings import (
    configured_adapter,
    plays_references_here,
    reads_pictures_here,
    reference_workspaces,
)
from exulanica.references.worker import ReferenceWorker
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
from exulanica.spending.status import SpendingRefusals, read_spending_refusals
from exulanica.store.base import ContentAddressedStore
from exulanica.store.configured import ContentStores, content_stores
from exulanica.store.namespaces import WorkspaceStores
from exulanica.world.decision_roles import DecisionRole, decision_roles
from exulanica.world.material_recipes import MaterialRuntime
from exulanica.world.society import world_society_seed
from exulanica.world.society_catalogs import ComparisonCatalogs, load_comparison_catalogs
from exulanica.world.society_composition import REVIEWED_REACH_MM, reviewed_affordance_registry
from exulanica.world.society_controls import (
    BASE_TICK_INTERVAL_DIVISOR,
    BASE_TICK_INTERVAL_MAX_MS,
    BASE_TICK_INTERVAL_MIN_MS,
    DEFAULT_BASE_TICK_INTERVAL_MS,
    validate_settings,
)
from exulanica.world.texture_assets import load_material_catalog
from exulanica.world.workspace_assets import WorkspaceAssetRuntime
from exulanica.world.workspace_preparations import RETAINED_BYTES_SETTING, retained_bytes_limit

if TYPE_CHECKING:
    from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime

__all__ = [
    "DATA_DIR_ENV",
    "DERIVATIVE_WORKER_ENV",
    "PLAYBACK_WORKERS_ENV",
    "PLAYBACK_WORKER_ENV",
    "READONLY_DATABASE_URL_ENV",
    "SOCIETY_AUTHORED_WORLDS_ENV",
    "SOCIETY_CONTROL_WORKER_ENV",
    "SOCIETY_CONTROL_WORKSPACES_ENV",
    "SOCIETY_OF_THINGS_ENV",
    "SOCIETY_TICK_INTERVAL_MS_ENV",
    "Services",
    "SocietySettingRefused",
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

#: A JSON array of workspace ids whose playing societies this instance advances, with no
#: accounts. Absent or ``[]`` plays none. Independent of the account-wide switch above.
SOCIETY_CONTROL_WORKSPACES_ENV: Final = env_name("SOCIETY_CONTROL_WORKSPACES")

#: Who plays the societies this host plays (the listed and discovered workspaces above) and seals
#: their coupled traffic. Absent (or an explicit on), this process, in threads. ``process``, a
#: process of its own (``exulanica-playback-worker``), and this one serves the playback controls
#: without playing; ``0``, ``false``, ``off`` or ``no``, nobody, and a society advances only a
#: minute at a time when somebody advances it.
PLAYBACK_WORKER_ENV: Final = env_name("PLAYBACK_WORKER")

#: How many workspaces' claims one playback round runs at once, 1 to 8. Absent means 1: each claim
#: in turn, the behaviour before the setting existed. More lets one workspace's model answers be
#: awaited while another's are; asks stay bounded by the process's model slots either way.
PLAYBACK_WORKERS_ENV: Final = env_name("PLAYBACK_WORKERS")

#: Who plays the comparisons started from the application, for the workspaces this host asks models
#: for. Absent (or an explicit on), this process, in a thread. ``process``, a process of its own
#: (``python -m exulanica.orchestration.comparison_worker``), and this one only serves starts.
#: ``0``, ``false``, ``off`` or ``no``, nobody, and every start is refused
#: (``comparisons_not_played``), since a start nothing plays would hold its world until the end.
COMPARISON_WORKER_ENV: Final = env_name("COMPARISON_WORKER")
#: The states of the installation's ``comparison`` component, as its facts state it, in which a
#: process that leaves its comparisons to another refuses every start (``comparisons_not_played``):
#: the installation's profile declares that process not installed, or unavailable here.
_COMPARISON_PROCESS_ABSENT: Final = frozenset({"not_installed", "unavailable"})
#: How the facts of a process with no profile state a component it cannot see: never a reason to
#: refuse, since that process cannot tell whether another one runs it.
_UNDECLARED: Final = "undeclared_installation"

#: The base wait between simulated minutes, in whole milliseconds, within the bounds
#: ``exulanica.world.society_controls`` declares. Absent means its declared default.
SOCIETY_TICK_INTERVAL_MS_ENV: Final = env_name("SOCIETY_TICK_INTERVAL_MS")

#: Every way a society setting is refused at startup, by the name the refusal carries.
SOCIETY_SETTING_REFUSALS: Final = {
    "society_control_worker_not_boolean": "must be an explicit boolean",
    "society_of_things_not_boolean": "must be an explicit boolean",
    "society_control_workspaces_not_json": "must be a JSON array of workspace ids",
    "society_control_workspaces_not_array": "must be a JSON array of workspace ids",
    "society_control_workspaces_not_uuid": "names an entry that is not a workspace id",
    "society_control_workspaces_duplicate": "names a workspace more than once",
    "society_tick_interval_not_integer": "must be a whole number of milliseconds",
    "comparison_worker_not_recognised": "must be absent, on, process or off",
    "playback_worker_not_recognised": "must be absent, on, process or off",
    "playback_workers_out_of_bounds": "must be absent or a whole number from 1 to 8",
    "society_tick_interval_out_of_bounds": (
        f"must be {BASE_TICK_INTERVAL_MIN_MS} to {BASE_TICK_INTERVAL_MAX_MS} milliseconds and "
        f"divisible by {BASE_TICK_INTERVAL_DIVISOR}, so every speed divides it exactly"
    ),
}


class SocietySettingRefused(ValueError):
    """A society setting in the environment that startup refuses, named by ``code``."""

    def __init__(self, code: str, variable: str) -> None:
        super().__init__(f"{code}: {variable} {SOCIETY_SETTING_REFUSALS[code]}")
        self.code = code
        self.variable = variable


#: A JSON file of host registrations for saved worlds, each naming the place its society binds.
#: Optional: a person can bring inhabitants into a saved world of their own without one, and the
#: society then binds a place derived from the world itself. A registration here takes
#: precedence for the version it names. Nothing is ever registered or created by saving a world;
#: a society exists only once somebody asks for it.
SOCIETY_AUTHORED_WORLDS_ENV: Final = env_name("SOCIETY_AUTHORED_WORLDS")
#: Whether a world's owner may make a society of things through the routes: off unless it is set
#: on, since its people do not yet pick things up, hand them over or follow anybody, and a society
#: made now is one every later version of its engine must keep replaying.
SOCIETY_OF_THINGS_ENV: Final = env_name("SOCIETY_OF_THINGS")

#: The registration file's own profile, so a file written for a later shape is refused here
#: rather than half-read.
AUTHORED_WORLDS_PROFILE: Final = "exulanica.society-authored-worlds/v1"


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
    #: How many workspaces' claims a playback round runs at once (:data:`PLAYBACK_WORKERS_ENV`).
    society_playback_workers: int = 1
    #: Who plays the societies this host plays (:data:`PLAYBACK_WORKER_ENV`): ``here``, this
    #: process; ``process``, the playback worker's process; ``none``, nobody. ``here`` for a
    #: hand-built Services, as before the setting existed; ``build_services`` reads the setting.
    playback_player: Literal["here", "process", "none"] = "here"
    #: Whether the routes make a society of things (:data:`SOCIETY_OF_THINGS_ENV`); off for a
    #: hand-built Services, as for a host that does not set it.
    societies_of_things: bool = False
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

    def decision_host(self) -> DecisionHost | None:
        """What asks the models a society's owner chose before a minute, for every role its engine
        hosts, or None without a society runtime.

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
            client=self.model_client,
            workspaces=frozenset(self.society_control_workspaces),
            policy_for=self.person_decision_policy,
            manifest=load_manifest(),
            manifest_sha256=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            external=None if self.door is None else self.door.asker(),
            discovered=self.watched_workspaces if self.discovers_model_workspaces else None,
            spending_refusals=self.spending_refusals if self.spending is not None else None,
        )

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

    def signal_comparison_refusal(self, workspace_id: uuid.UUID) -> str | None:
        """Why this server starts no signal comparison for a workspace, or None when it may: the
        same host facts a comparison of people is refused by, its seeds the signal catalog's."""
        if not (self.runs_comparison_worker or self.comparisons_played_elsewhere):
            return "comparisons_not_played"
        if not self.asks_models_for(workspace_id):
            return "comparisons_not_run_here"
        if self.model_client is None:
            return PROVIDER_CREDENTIAL_ABSENT
        if self.comparison_process_absent():
            return "comparisons_not_played"
        return None

    def comparison_refusal(self, workspace_id: uuid.UUID) -> str | None:
        """Why this server starts no comparison for a workspace, or None when it may: its seed
        catalog commits no development seed's text (``comparisons_not_set_up``), nothing plays the
        comparisons started here (``comparisons_not_played``), it asks no model for the workspace
        (``comparisons_not_run_here``, :meth:`asks_models_for`), it has no model client, or it
        leaves them to another process the installation does not run
        (:meth:`comparison_process_absent`), which nothing plays either
        (``comparisons_not_played``)."""
        if not self.comparison_seeds:
            return "comparisons_not_set_up"
        if not (self.runs_comparison_worker or self.comparisons_played_elsewhere):
            return "comparisons_not_played"
        if not self.asks_models_for(workspace_id):
            return "comparisons_not_run_here"
        if self.model_client is None:
            return PROVIDER_CREDENTIAL_ABSENT
        if self.comparison_process_absent():
            return "comparisons_not_played"
        return None

    def comparison_process_absent(self) -> bool:
        """Whether this process leaves its comparisons to another one (``process`` in
        :data:`COMPARISON_WORKER_ENV`) that the installation's profile declares not installed or
        unavailable, read from the installation's facts as a capability read reads them
        (:func:`~exulanica.api.installation.installation_facts`): a start would wait for a process
        the installation does not run. Never where this process plays them itself, whatever its
        profile declares, nor in a process composed with no installation, nor where a process with
        no profile cannot see the component."""
        if self.runs_comparison_worker or not self.comparisons_played_elsewhere:
            return False
        if self.installation is None:
            return False
        component = next(
            (
                entry
                for entry in installation_facts(self)["components"]
                if entry["component"] == "comparison"
            ),
            None,
        )
        return (
            component is not None
            and component["state"] in _COMPARISON_PROCESS_ABSENT
            and component.get("reason") != _UNDECLARED
        )

    def comparison_room(self, role: DecisionRole) -> Decimal | None:
        """What this process's model budget has left for a comparison it plays itself, beside
        the share ``role``'s contract keeps for other work; None where another process plays them,
        whose budget this one cannot see."""
        if not self.runs_comparison_worker or self.model_client is None:
            return None
        budget = self.model_client.budget
        keep_usd, _keep_calls = share_kept(budget, role.contract())
        return budget.ceiling_usd - budget.spent_usd - keep_usd

    def comparison_call_room(self, role: DecisionRole) -> int | None:
        """How many calls this process's model budget has left for a comparison it plays itself,
        beside the calls ``role``'s contract keeps for other work; None where another process
        plays them. A comparison can stop at this as it stops at its bound, whatever it spent."""
        if not self.runs_comparison_worker or self.model_client is None:
            return None
        budget = self.model_client.budget
        _keep_usd, keep_calls = share_kept(budget, role.contract())
        return budget.max_calls - budget.billed_calls - keep_calls

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
        queued ones of those it serves. Run at startup, so a workspace dropped from the list, a
        worker set off or a move to a public profile leaves nothing waiting. Returns how many."""
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
        return ended

    def build_reference_worker(self) -> ReferenceWorker | None:
        """What plays the reference jobs of the workspaces that may ask for web notes, or None
        where this process has no model client, no durable spending, no such workspace or no
        source configuration. Each job's requests carry the workspace's rules, with no place's
        name released: a search is not a use a place-name right offers."""
        if (
            self.model_client is None
            or self.spending is None
            or not self.reference_workspaces
            or self.reference_adapter_for is None
            or not self.references_offered_here()
        ):
            return None
        database = self.database
        readonly = self.readonly_database
        workspaces = self.reference_workspaces

        def policy_for(workspace_id: uuid.UUID) -> WorkspaceRequestPolicy:
            # Saved names and rights are read on the read-only database, as a person's decisions
            # read them.
            return self.request_policy(
                workspace_id,
                lambda: readonly.session(workspace_id),
                released_places=no_place_released,
            )

        return ReferenceWorker(
            database,
            client=self.model_client,
            policy_for=policy_for,
            spending=self.spending,
            adapter_for=self.reference_adapter_for,
            workspaces=lambda: workspaces,
            # A person's own pictures are read only where pictures are turned on, from the
            # read-only database as the request policy reads rights.
            picture_source=(
                reference_picture_source(readonly.session, self.store)
                if self.picture_reading_here()
                else None
            ),
        )

    def model_host_refusal(self, workspace_id: uuid.UUID, role: DecisionRole) -> str | None:
        """Why this host asks no model for a workspace's subjects of ``role``, or None when it
        asks them.

        The facts :meth:`decision_host` acts on: the workspaces it asks models for
        (:meth:`asks_models_for`), the process's client, and what is left of its budget and of the
        share the role's decisions may spend. A code from ``HOST_REFUSALS``.
        """
        if not self.asks_models_for(workspace_id):
            return "models_not_run_here"
        return host_refusal(role, self.model_client, load_manifest(), role.contract())

    def provider_refusal(self, provider: str) -> str | None:
        """Why this process asks no model a provider serves, or None when it may ask them."""
        if self.model_client is None:
            return PROVIDER_CREDENTIAL_ABSENT
        return self.model_client.refusals.get(provider)

    def smallest_ask_usd(self) -> dict[str, Decimal]:
        """By provider, the smallest reservation one attempt of any model a person may be given
        takes: its answer bound at its prices with no prompt. A remainder below it admits no ask
        of that provider's models; empty with no model client."""
        client = self.model_client
        if client is None:
            return {}
        floors: dict[str, Decimal] = {}
        for spec in load_manifest().models.values():
            if not (spec.is_chat and spec.answering):
                continue
            usd = client.budget.estimate_usd(spec, max_tokens=answer_tokens(spec) or 0)
            floors[spec.provider] = min(usd, floors.get(spec.provider, usd))
        return floors

    def spending_refusals(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID
    ) -> SpendingRefusals | None:
        """What the durable spending authority would answer a workspace's next attempt, by
        provider, from one read of the workspace's own spending on ``connection``
        (:func:`~exulanica.spending.status.admission_refusal`); None in a process no durable
        authority admits, which spends within its fuse alone (:meth:`model_host_refusal`).

        A provider's refusal is every ask's of a model it serves: an ask goes to its chosen
        model's provider alone (``ModelClient.choose`` walks one model with no fallback), and
        ``ModelChain.walk`` falls back only on ``ModelUnavailableError``, never on a refusal.
        """
        if self.spending is None:
            return None
        return read_spending_refusals(
            connection, workspace_id, witness_configured=self.spending.witness is not None
        )

    def allowance_refusal(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, providers: Iterable[str]
    ) -> SpendingRefused | None:
        """The refusal admission would give the first ask of the first of ``providers`` whose
        allowance is spent (:meth:`spending_refusals`), or None while each has allowance left, or
        in a process no durable authority admits. A plan states it and a start raises it, so the
        two never differ."""
        refusals = self.spending_refusals(connection, workspace_id)
        return None if refusals is None else refusals.first(providers)

    def require_allowance(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, providers: Iterable[str]
    ) -> None:
        """Raise :meth:`allowance_refusal`'s refusal, before anything is written; return while
        each of ``providers`` has allowance left, or in a process no durable authority admits."""
        refused = self.allowance_refusal(connection, workspace_id, providers)
        if refused is not None:
            raise refused

    def bound_room_refusal(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        providers: Iterable[str],
        *,
        usd: Decimal | None,
        calls: int,
    ) -> tuple[str, str] | None:
        """``bound_exceeds_grant`` and why, where a comparison's bound ``usd`` or the ``calls`` it
        can make are more than the live grant of one of ``providers`` has left
        (:func:`~exulanica.api.comparison_spending.bound_room_refusal`); None while each grant
        holds both, or in a process no durable authority admits, where no bound is opened. A plan
        states it and a start is refused by it, after the allowance."""
        if self.spending is None:
            return None
        return bound_room_refusal(connection, workspace_id, providers, usd=usd, calls=calls)

    def choice_refusal(
        self,
        role: DecisionRole,
        model: Mapping[str, str],
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
    ) -> str | None:
        """Why a subject's chosen model is not asked here, or None: a code from MODEL_REFUSALS.

        The question is judged by the workspace's rules as the host judges it, on ``connection``,
        which the caller lends idle.
        """
        refusal = model_refusal(role, self.model_client, load_manifest(), role.contract(), model)
        if refusal is not None or self.model_client is None:
            return refusal
        return question_refusal(
            role,
            self.model_client.with_policy(
                self.request_policy(
                    workspace_id, borrowing(connection), released_places=no_place_released
                )
            ),
            model["model_id"],
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
            workspace_source=(
                self.accounts.active_owned_workspaces if self.accounts is not None else None
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
        accounts=accounts,
        door=door_runtime(database, environ, open_to=_door_open_to(accounts)),
        environment_admission_root=data_dir / "environment-inbox",
        materials=_material_runtime(stores, environ),
        workspace_assets=WorkspaceAssetRuntime(
            stores=stores.workspace_assets, retained_bytes_limit=retained_bytes_limit(environ)
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
        society_playback_workers=_playback_workers(env_get("PLAYBACK_WORKERS", environ)),
        playback_player=playback_player,
        societies_of_things=_explicitly_enabled(
            env_get("SOCIETY_OF_THINGS", environ),
            "society_of_things_not_boolean",
            SOCIETY_OF_THINGS_ENV,
        ),
        comparison_seeds=development_seeds(load_comparison_catalogs()),
        runs_comparison_worker=comparison_player == "here",
        comparisons_played_elsewhere=comparison_player == "process",
        runs_reference_worker=plays_references_here(env_get("REFERENCE_WORKER", environ)),
        reference_workspaces=reference_workspaces(env_get("REFERENCE_WORKSPACES", environ)),
        reference_pictures=reads_pictures_here(env_get("REFERENCE_PICTURES", environ)),
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


def _society_runtime(store: ContentAddressedStore, environ: Mapping[str, str]) -> SocietyRuntime:
    """The society runtime every instance serves, inert until somebody asks for inhabitants.

    It composes a saved world over the ground the world's own snapshot declares when its owner
    brings inhabitants in, and it creates, starts and schedules nothing by itself. District
    bindings are never inferred.

    ``EXULANICA_SOCIETY_AUTHORED_WORLDS`` optionally names a JSON file of host registrations,
    each naming a workspace, a saved world, its authored version, that version's structural
    snapshot, the authored region of that snapshot and the workspace place identity the society
    row binds, and optionally the reviewed reach. Nothing in it is inferred: a file that names a
    world whose snapshot is not an authored starter, or whose region is not that snapshot's own,
    fails at the first request with the reason rather than composing something else. A file that
    is present and malformed stops startup, because an instance that silently ignores a
    registration it was given is the failure this refuses to become.
    """
    path = env_get("SOCIETY_AUTHORED_WORLDS", environ)
    reach_mm = REVIEWED_REACH_MM
    bindings: list[AuthoredWorldSocietyBinding] = []
    if path:
        document = json.loads(Path(path).read_bytes())
        if not isinstance(document, dict) or document.get("profile") != AUTHORED_WORLDS_PROFILE:
            raise ValueError(
                f"{SOCIETY_AUTHORED_WORLDS_ENV} must name a {AUTHORED_WORLDS_PROFILE} file"
            )
        reach_mm = document.get("reach_mm", REVIEWED_REACH_MM)
        bindings = [AuthoredWorldSocietyBinding.model_validate(row) for row in document["worlds"]]
    return SocietyRuntime(
        store=store,
        authored_bindings=bindings,
        reviewed_affordances=reviewed_affordance_registry(reach_mm),
    )


def _material_runtime(stores: ContentStores, environ: Mapping[str, str]) -> MaterialRuntime | None:
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
    return MaterialRuntime(catalog=catalog, stores=stores.materials)


def _character_appearance_runtime(
    store: ContentAddressedStore,
    environ: Mapping[str, str],
    workspace_stores: WorkspaceStores | None = None,
) -> CharacterAppearanceRuntime | None:
    """Saved looks over the character catalogs this host publishes (migration 0131).

    A family is served while a publication that derives it is not withdrawn, and a saved look is
    drawn from the newest served publication deriving exactly its family. Publishing is host
    administration, not startup: ``exulanica-character-catalog publish`` (or
    ``scripts/prepare_character_people.py --import --apply``) imports the containers and records the
    publication with the owner connection, so this instance reads the catalogs from the database
    on every request and a publication or withdrawal takes effect without a restart. With nothing
    published, the families read is empty and saving a look answers 424.

    Bodies a parametric family does not publish are prepared in the workspace's own preparation
    queue, in the workspace asset namespaces (``workspace_stores``; without them no body is
    prepared here). ``EXULANICA_CHARACTER_PREPARER_BLENDER`` and
    ``EXULANICA_CHARACTER_PREPARER_SOURCE`` name the pinned preparation inputs; without them, or
    when they do not verify, a request for a body answers 503 and nothing is queued.
    """
    from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime
    from exulanica.world.character_body_preparations import QueuedCharacterPreparations
    from exulanica.world.character_catalogs import CatalogRegistry
    from exulanica.world.character_preparation import CharacterBodyPreparer, environment_host
    from exulanica.world.workspace_preparations import WorkspacePreparationRepository

    return CharacterAppearanceRuntime(
        families=(),
        authorize_family=lambda _connection, _session, _family: False,
        store=store,
        catalogs=CatalogRegistry(),
        preparations=None
        if workspace_stores is None
        else lambda connection, session: QueuedCharacterPreparations(
            WorkspacePreparationRepository(
                connection, session.workspace_id, session.actor, stores=workspace_stores
            )
        ),
        preparer=None
        if workspace_stores is None
        else CharacterBodyPreparer(hosts=lambda family_id: environment_host(family_id, environ)),
    )


def _playback_player(value: str | None) -> Literal["here", "process", "none"]:
    """Who plays this host's societies (``EXULANICA_PLAYBACK_WORKER``): ``here``, ``process`` or
    ``none``, or a named refusal of anything else."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "1", "true", "on", "yes"):
        return "here"
    if normalized == "process":
        return "process"
    if normalized in ("0", "false", "off", "no"):
        return "none"
    raise SocietySettingRefused("playback_worker_not_recognised", PLAYBACK_WORKER_ENV)


def _comparison_player(value: str | None) -> str:
    """Who plays the comparisons started from the application (``EXULANICA_COMPARISON_WORKER``):
    ``here``, ``process`` or ``none``, or a named refusal of anything else."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "1", "true", "on", "yes"):
        return "here"
    if normalized == "process":
        return "process"
    if normalized in ("0", "false", "off", "no"):
        return "none"
    raise SocietySettingRefused("comparison_worker_not_recognised", COMPARISON_WORKER_ENV)


def _enabled(value: str | None) -> bool:
    """Absent means on. Only an explicit off is off, and it has to be spelled like one."""
    return (value or "").strip().lower() not in ("0", "false", "off", "no")


def _explicitly_enabled(
    value: str | None,
    code: str = "society_control_worker_not_boolean",
    variable: str = SOCIETY_CONTROL_WORKER_ENV,
) -> bool:
    """Parse an opt-in switch; absence and explicit false are both safely off. Anything else is
    refused by ``code``, naming the setting ``variable``."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "0", "false", "off", "no"):
        return False
    if normalized in ("1", "true", "on", "yes"):
        return True
    raise SocietySettingRefused(code, variable)


def _society_control_workspaces(value: str | None) -> tuple[uuid.UUID, ...]:
    """The workspaces this instance plays without accounts, or a named refusal.

    Absence plays none. Anything present must be exactly a JSON array of distinct workspace ids:
    an instance that half-read a list it was given would play some worlds and silently not others.
    """
    if value is None or not value.strip():
        return ()
    try:
        document = json.loads(value)
    except json.JSONDecodeError:
        raise SocietySettingRefused(
            "society_control_workspaces_not_json", SOCIETY_CONTROL_WORKSPACES_ENV
        ) from None
    if not isinstance(document, list):
        raise SocietySettingRefused(
            "society_control_workspaces_not_array", SOCIETY_CONTROL_WORKSPACES_ENV
        )
    workspaces: list[uuid.UUID] = []
    for entry in document:
        try:
            if not isinstance(entry, str):
                raise ValueError(entry)
            workspaces.append(uuid.UUID(entry))
        except ValueError:
            raise SocietySettingRefused(
                "society_control_workspaces_not_uuid", SOCIETY_CONTROL_WORKSPACES_ENV
            ) from None
    if len(set(workspaces)) != len(workspaces):
        raise SocietySettingRefused(
            "society_control_workspaces_duplicate", SOCIETY_CONTROL_WORKSPACES_ENV
        )
    return tuple(workspaces)


def _playback_workers(value: str | None) -> int:
    """How many workspaces' claims a playback round runs at once (:data:`PLAYBACK_WORKERS_ENV`),
    1 when absent, or a named refusal of anything but a whole number from 1 to 8."""
    if value is None or not value.strip():
        return 1
    text = value.strip()
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= 8:
        raise SocietySettingRefused("playback_workers_out_of_bounds", PLAYBACK_WORKERS_ENV)
    return int(text)


def _society_tick_interval_ms(value: str | None) -> int:
    """The host's base wait between simulated minutes, or a named refusal.

    Absence is the declared default. The bounds are the playback module's own, asked rather than
    restated, so a control saved under this base is one that module accepts.
    """
    if value is None or not value.strip():
        return DEFAULT_BASE_TICK_INTERVAL_MS
    text = value.strip()
    if not text.isascii() or not text.isdigit():
        raise SocietySettingRefused(
            "society_tick_interval_not_integer", SOCIETY_TICK_INTERVAL_MS_ENV
        )
    interval = int(text)
    try:
        validate_settings("paused", 1, interval)
    except ValueError:
        raise SocietySettingRefused(
            "society_tick_interval_out_of_bounds", SOCIETY_TICK_INTERVAL_MS_ENV
        ) from None
    return interval


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
        API_TOKENS_ENV,
        *AdmissionSettings.variables(),
        env_name(RETAINED_BYTES_SETTING),
        *sorted({provider.api_key_env for provider in load_manifest().providers.values()}),
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
