"""What this installation is, and what each of its parts can do right now.

An installation profile (``deploy/profiles/<id>.json``, of profile
``exulanica.installation-profile/v1``) declares which processes an installation runs and what each
needs. It names processes, not
features: the capability projection maps operations onto these components, so nothing here is a
second feature registry. It holds no secret, host, domain or account; values stay in the
environment. ``EXULANICA_INSTALLATION_PROFILE`` names the file, and without it an instance is an
undeclared development run whose facts say only what this process can see for itself.

:func:`installation_facts` answers ``exulanica.installation-facts/v1`` from inside the process, on
every capability read, so it is cheap: the static part comes from the profile and settings, and
the part that asks the database or a file is cached for at most :data:`FACTS_CACHE_SECONDS` and
carries ``observed_at``. It never calls a model, never shows a setting's value and never reads a
workspace's content.

The API's runtime role reads through row-level security and cannot see how old another
workspace's queued work is. The maintenance process, which reads every workspace as the read-only
backup role, writes those observations and its own recovery state into a small status file
(``EXULANICA_MAINTENANCE_STATUS_PATH``, profile ``exulanica.maintenance-status/v1``), and this
module reads that file. A status file older than its profile's bound is itself reported, never
trusted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.deletion.restore import MAX_EXPORT_LAG
from exulanica.env import env_get, env_name

if TYPE_CHECKING:
    from exulanica.api.services import Services

__all__ = [
    "COMPONENTS",
    "FACTS_CACHE_SECONDS",
    "FACTS_PROFILE",
    "MAINTENANCE_STATUS_PROFILE",
    "PROFILE_ENV",
    "PROFILE_PROFILE",
    "STATES",
    "Installation",
    "InstallationProfile",
    "InstallationRefused",
    "PreparerSpec",
    "installation_facts",
    "installation_summary",
    "load_installation",
    "load_profile",
    "paid_admission",
]

PROFILE_ENV: Final = env_name("INSTALLATION_PROFILE")
MAINTENANCE_STATUS_ENV: Final = env_name("MAINTENANCE_STATUS_PATH")
PROFILE_PROFILE: Final = "exulanica.installation-profile/v1"
FACTS_PROFILE: Final = "exulanica.installation-facts/v1"
MAINTENANCE_STATUS_PROFILE: Final = "exulanica.maintenance-status/v1"

#: The longest a capability read may see an observation from the database or the status file.
#: ``serving.state`` is never older than this, so a restore that seals the database closes writes
#: within it.
FACTS_CACHE_SECONDS: Final = 5

#: Every component an installation may run, in the order facts list them. Frozen with the
#: capability projection: a new name is a new contract version, not an edit.
COMPONENTS: Final = (
    "database",
    "schema",
    "api",
    "client",
    "maintenance",
    "ingestion",
    "derivatives",
    "pose_scene",
    "preparation",
    "materials",
    "generated_tiles",
    "simulation",
    "comparison",
)

#: A component's state. ``not_installed``, ``unavailable`` and ``refused`` make an operation that
#: needs the component unavailable; ``degraded`` is listed and changes nothing; ``configured`` and
#: ``ready`` are not listed by the projection.
STATES: Final = ("not_installed", "unavailable", "configured", "ready", "degraded", "refused")

#: Components whose queued work only the maintenance process can observe across workspaces.
_QUEUED: Final = (
    "derivatives",
    "pose_scene",
    "preparation",
    "materials",
    "generated_tiles",
    "comparison",
)

#: A preparer as a profile and a preparation row name it: its id and version, ``id@version``.
_PREPARER_PIN: Final = re.compile(r"^[a-z][a-z0-9.-]*@[1-9][0-9]{0,5}$")

_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SETTING: Final = re.compile(r"^(EXULANICA_|NEBIUS_)[A-Z0-9_]{1,64}$")
_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION: Final = re.compile(r"^[0-9a-f]{40}$")
_OWNERS: Final = frozenset({"D3", "R1", "B1", "ST1", "A2", "C7", "F1", "W7", "root"})


class InstallationRefused(ValueError):
    """A profile or status file that cannot be trusted, named by a stable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class PreparerSpec:
    """One preparer as a profile's ``preparation`` component declares it."""

    installed: bool
    #: Why it is not installed, or why, installed, it cannot run, as a stable code.
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """One component as a profile declares it."""

    installed: bool
    #: Installed, but this installation cannot run it, and why, as a stable code.
    unavailable_reason: str | None = None
    #: How old the oldest queued item may be before the component reports ``degraded``.
    queue_bound_seconds: int | None = None
    #: ``preparation`` only: each preparer by its pin (``id@version``). A preparation worker runs
    #: the installed ones and nothing else, and refuses to start when one cannot run. None where
    #: the profile names none: the worker then runs every registered preparer its host can.
    preparers: Mapping[str, PreparerSpec] | None = None


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """The recovery bounds a profile declares; the loss windows the contract states follow them."""

    export_interval_seconds: int
    max_export_lag_seconds: int
    backup_interval_seconds: int
    backup_retention_days: int
    verification_interval_seconds: int
    #: The external restore marker every process of the installation reads (ADR-0019); present
    #: in every profile, so an export and the API can never run without one.
    restore_state_path: str = "/var/lib/exulanica-restore/restore.json"


@dataclass(frozen=True, slots=True)
class InstallationProfile:
    id: str
    version: int
    sha256: str
    store_kind: str
    components: Mapping[str, ComponentSpec]
    recovery: RecoveryPolicy
    settings_owners: Mapping[str, tuple[str, ...]]


def _positive(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InstallationRefused("profile_invalid", f"{where} must be a positive integer")
    return value


def _exact_keys(value: Any, keys: set[str], optional: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InstallationRefused("profile_invalid", f"{where} must be an object")
    missing = keys - value.keys()
    extra = value.keys() - keys - optional
    if missing or extra:
        raise InstallationRefused(
            "profile_invalid", f"{where}: missing {sorted(missing)}, unknown {sorted(extra)}"
        )
    return value


def _preparers(value: Any) -> Mapping[str, PreparerSpec]:
    """``components.preparation.preparers``: each pin's installation, and a reason by code."""
    if not isinstance(value, dict) or not value:
        raise InstallationRefused("profile_invalid", "components.preparation.preparers")
    preparers: dict[str, PreparerSpec] = {}
    for pin, entry in value.items():
        if not isinstance(pin, str) or not _PREPARER_PIN.match(pin):
            raise InstallationRefused(
                "profile_invalid", "components.preparation.preparers: a key is id@version"
            )
        where = f"components.preparation.preparers.{pin}"
        body = _exact_keys(entry, {"installed"}, {"reason"}, where)
        if not isinstance(body["installed"], bool):
            raise InstallationRefused("profile_invalid", f"{where}.installed")
        reason = body.get("reason")
        if reason is not None and (not isinstance(reason, str) or not _CODE.match(reason)):
            raise InstallationRefused("profile_invalid", f"{where}.reason")
        preparers[pin] = PreparerSpec(body["installed"], reason)
    if not any(spec.installed for spec in preparers.values()):
        raise InstallationRefused(
            "profile_invalid", "components.preparation.preparers installs no preparer"
        )
    return MappingProxyType(preparers)


def load_profile(path: Path) -> InstallationProfile:
    """Read and validate a profile, refusing anything it does not state exactly."""
    try:
        document = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise InstallationRefused("profile_unreadable", str(path)) from exc
    body = _exact_keys(
        document,
        {"profile", "id", "version", "store", "components", "recovery", "settings_owners"},
        {"description"},
        "profile",
    )
    if body["profile"] != PROFILE_PROFILE:
        raise InstallationRefused("profile_invalid", f"profile must be {PROFILE_PROFILE}")
    if not isinstance(body["id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", body["id"]):
        raise InstallationRefused("profile_invalid", "id must be a short lowercase name")
    store = _exact_keys(body["store"], {"kind"}, set(), "store")
    if store["kind"] not in ("local", "object"):
        raise InstallationRefused("profile_invalid", "store.kind must be local or object")
    declared = _exact_keys(body["components"], set(COMPONENTS), set(), "components")
    components: dict[str, ComponentSpec] = {}
    for name in COMPONENTS:
        entry = _exact_keys(
            declared[name],
            {"installed"},
            {"unavailable_reason", "queue_bound_seconds"}
            | ({"preparers"} if name == "preparation" else set()),
            f"components.{name}",
        )
        if not isinstance(entry["installed"], bool):
            raise InstallationRefused("profile_invalid", f"components.{name}.installed")
        reason = entry.get("unavailable_reason")
        if reason is not None and (not isinstance(reason, str) or not _CODE.match(reason)):
            raise InstallationRefused("profile_invalid", f"components.{name}.unavailable_reason")
        bound = entry.get("queue_bound_seconds")
        if bound is not None:
            if name not in _QUEUED:
                raise InstallationRefused("profile_invalid", f"{name} has no queue to bound")
            _positive(bound, f"components.{name}.queue_bound_seconds")
        if reason is not None and not entry["installed"]:
            raise InstallationRefused(
                "profile_invalid", f"components.{name} is not installed and so has no reason"
            )
        preparers = _preparers(entry["preparers"]) if "preparers" in entry else None
        if preparers is not None and not entry["installed"]:
            raise InstallationRefused(
                "profile_invalid", f"components.{name} is not installed and so runs no preparer"
            )
        components[name] = ComponentSpec(entry["installed"], reason, bound, preparers)
    for required in ("database", "schema", "api"):
        if not components[required].installed:
            raise InstallationRefused("profile_invalid", f"every installation runs {required}")
    recovery_body = dict(
        _exact_keys(
            body["recovery"],
            {
                "export_interval_seconds",
                "max_export_lag_seconds",
                "backup_interval_seconds",
                "backup_retention_days",
                "verification_interval_seconds",
                "restore_state_path",
            },
            set(),
            "recovery",
        )
    )
    marker = recovery_body.pop("restore_state_path")
    if (
        not isinstance(marker, str)
        or not marker.startswith("/")
        or ".." in Path(marker).parts
        or not marker.endswith(".json")
    ):
        raise InstallationRefused(
            "profile_invalid", "recovery.restore_state_path must be an absolute .json path"
        )
    recovery = RecoveryPolicy(
        **{key: _positive(value, f"recovery.{key}") for key, value in recovery_body.items()},
        restore_state_path=marker,
    )
    if recovery.max_export_lag_seconds > MAX_EXPORT_LAG.total_seconds():
        raise InstallationRefused(
            "profile_invalid", "max_export_lag_seconds is above the restore's ceiling"
        )
    if recovery.max_export_lag_seconds < recovery.export_interval_seconds:
        raise InstallationRefused(
            "profile_invalid", "max_export_lag_seconds is shorter than one export interval"
        )
    owners_body = body["settings_owners"]
    if not isinstance(owners_body, dict) or not set(owners_body) <= _OWNERS:
        raise InstallationRefused("profile_invalid", "settings_owners names an unknown owner")
    owners: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for owner, names in sorted(owners_body.items()):
        if not isinstance(names, list) or not all(
            isinstance(name, str) and _SETTING.match(name) for name in names
        ):
            raise InstallationRefused("profile_invalid", f"settings_owners.{owner}")
        if seen & set(names):
            raise InstallationRefused("profile_invalid", f"a setting has two owners: {owner}")
        seen |= set(names)
        owners[owner] = tuple(names)
    return InstallationProfile(
        id=body["id"],
        version=_positive(body["version"], "version"),
        sha256=hashlib.sha256(canonical_json(document)).hexdigest(),
        store_kind=store["kind"],
        components=components,
        recovery=recovery,
        settings_owners=owners,
    )


@dataclass(slots=True)
class _Cached:
    at: float
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Installation:
    """A process's declared installation: its profile, identity and a short-lived fact cache."""

    profile: InstallationProfile | None
    code_revision: str | None
    images: Mapping[str, str]
    maintenance_status_path: Path | None
    #: The restore marker: the profile's when one is declared, else EXULANICA_RESTORE_STATE_PATH.
    restore_state_path: Path | None = None
    clock: Callable[[], float] = time.monotonic
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _cache: dict[str, _Cached] = field(default_factory=dict, repr=False, compare=False)

    def cached(self, key: str, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """``compute()``'s value, at most :data:`FACTS_CACHE_SECONDS` old."""
        now = self.clock()
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and now - entry.at < FACTS_CACHE_SECONDS:
                return entry.value
        value = compute()
        with self._lock:
            self._cache[key] = _Cached(now, value)
        return value


def load_installation(environ: Mapping[str, str]) -> Installation:
    """The installation this process belongs to. Startup refuses a named profile it cannot read."""
    named = env_get("INSTALLATION_PROFILE", environ)
    profile = load_profile(Path(named)) if named else None
    revision = env_get("CODE_REVISION", environ)
    if revision is not None and not _REVISION.match(revision):
        raise InstallationRefused("identity_invalid", "EXULANICA_CODE_REVISION is not 40 hex")
    images = {}
    for component, suffix in (("backend", "IMAGE_BACKEND"), ("client", "IMAGE_CLIENT")):
        value = env_get(suffix, environ)
        if value is None:
            continue
        if not _DIGEST.match(value):
            raise InstallationRefused("identity_invalid", f"EXULANICA_{suffix} is not a digest")
        images[component] = value
    status = env_get("MAINTENANCE_STATUS_PATH", environ)
    stated = env_get("RESTORE_STATE_PATH", environ)
    marker = Path(stated) if stated else None
    if profile is not None:
        declared = Path(profile.recovery.restore_state_path)
        if marker is not None and marker != declared:
            raise InstallationRefused(
                "restore_state_path_conflict",
                "EXULANICA_RESTORE_STATE_PATH differs from the profile's restore_state_path",
            )
        marker = declared
        configured = env_get("STORE_KIND", environ) or "local"
        if configured != profile.store_kind:
            # Bytes written to another store than the profile's would be outside its backups.
            raise InstallationRefused(
                "store_kind_conflict",
                f"EXULANICA_STORE_KIND is {configured!r} and the profile declares "
                f"{profile.store_kind!r}",
            )
    return Installation(
        profile=profile,
        code_revision=revision,
        images=images,
        maintenance_status_path=Path(status) if status else None,
        restore_state_path=marker,
    )


def _parse_time(value: Any) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _maintenance_status(installation: Installation) -> dict[str, Any]:
    """The maintenance process's newest status, or why there is none. Never raises."""
    path = installation.maintenance_status_path
    if path is None:
        return {"state": "absent", "reason": "maintenance_status_not_configured"}
    try:
        document = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {"state": "absent", "reason": "maintenance_status_missing"}
    except (OSError, ValueError):
        return {"state": "invalid", "reason": "maintenance_status_unreadable"}
    if not isinstance(document, dict) or document.get("profile") != MAINTENANCE_STATUS_PROFILE:
        return {"state": "invalid", "reason": "maintenance_status_unreadable"}
    written = _parse_time(document.get("written_at"))
    if written is None:
        return {"state": "invalid", "reason": "maintenance_status_unreadable"}
    return {"state": "present", "written_at": written, "document": document}


def _observations(services: Services, installation: Installation) -> dict[str, Any]:
    """Everything that asks the database or a file, computed at most once per cache period."""
    from exulanica.db.migrate import applied_migrations
    from exulanica.deletion.restore import RestoreRefused, verify_restore
    from exulanica.evidence.blob import BlobId
    from exulanica.migrations import migrations

    observed: dict[str, Any] = {"observed_at": dt.datetime.now(dt.UTC).isoformat()}
    expected = [migration.version for migration in migrations()]
    observed["schema_expected"] = expected[-1] if expected else None
    try:
        with services.database.unscoped() as connection:
            applied = sorted(applied_migrations(connection))
            control = (
                connection.cursor(row_factory=dict_row)
                .execute("select state from restore_control")
                .fetchone()
            )
        observed["database"] = True
        observed["schema_applied"] = applied[-1] if applied else None
        observed["schema_matches"] = applied == expected
        observed["restore_state"] = control["state"] if control else "none"
    except Exception:
        observed.update(database=False, schema_applied=None, schema_matches=False)
        observed["restore_state"] = "unknown"
    try:
        verify_restore(services.database, services.restore_state_path)
        observed["serving"] = {"state": "open"}
    except RestoreRefused:
        observed["serving"] = {"state": "refused", "reason": "restore_pending"}
    except Exception:
        observed["serving"] = {"state": "refused", "reason": "restore_state_unknown"}
    try:
        services.store.exists(BlobId(b"\x00" * 32))
        observed["store_reachable"] = True
    except Exception:
        observed["store_reachable"] = False
    observed["maintenance"] = _maintenance_status(installation)
    observed["spending"] = _spending_authorities(services)
    observed["process_witness"] = _process_witness(services)
    return observed


def _process_witness(services: Services) -> str | None:
    """This process's own witness directory, when it spends durably: ``marked``, ``unmarked`` (no
    witness directory marker), ``not_configured`` or ``unreadable``. A process without a marked
    directory is refused alone under a witnessed authority; the authority is not suspended."""
    from exulanica.spending.witness import FileSpendingWitness

    if services.spending is None:
        return None
    witness = services.spending.witness
    if witness is None:
        return "not_configured"
    if not isinstance(witness, FileSpendingWitness):
        return "marked"
    try:
        return "unmarked" if witness.directory_id() is None else "marked"
    except Exception:
        return "unreadable"


#: Why this process cannot spend under a witnessed authority, by its own witness state.
_PROCESS_WITNESS_REFUSALS: Final = {
    "not_configured": "witness_not_configured",
    "unmarked": "witness_directory_mismatch",
    "unreadable": "witness_unreadable",
}


def _spending_authorities(services: Services) -> list[dict[str, Any]] | None:
    """Every spending authority's state when this process spends durably, ``None`` otherwise.

    States and witnesses only, never an amount (``spending_authority_facts``).
    """
    from exulanica.spending.config import DURABLE
    from exulanica.spending.status import authority_states

    if services.model_client is None or services.spending_mode != DURABLE:
        return None
    try:
        return authority_states(services.database)
    except Exception:
        return [{"state": "unreadable"}]


def _store_facts(
    services: Services, profile: InstallationProfile | None, observed: Mapping[str, Any]
) -> dict[str, Any]:
    """The store the profile declares, the one this process built, and the latter's own
    description: kinds and check codes, never an endpoint, bucket or credential."""
    declared = profile.store_kind if profile is not None else "local"
    built = services.content_stores
    facts: dict[str, Any] = {"kind": declared, "reachable": observed["store_reachable"]}
    if built is not None:
        facts["configured_kind"] = built.kind
        facts["matches_profile"] = built.kind == declared
        facts["description"] = built.describe()
    return facts


def paid_admission(
    *,
    no_model: bool,
    spending_mode: str | None,
    authorities: list[dict[str, Any]] | None,
    process_witness: str | None = None,
) -> dict[str, Any]:
    """Whether this process can admit a paid model call, and how its spending is bounded.

    A durable authority's allowance is never replenished by a restore: the witness outside the
    database suspends it until an operator reconciles, and the reason is stated here.
    """
    from exulanica.spending.config import DURABLE

    if no_model:
        return {"state": "blocked", "reason": "provider_credential_absent"}
    if spending_mode != DURABLE:
        # One process's ceilings, started again with the process; the provider balance is what
        # bounds spend across restarts.
        return {"state": "open", "spending": "process", "restore_protection": "none"}
    found = authorities or []
    if any(entry.get("state") == "unreadable" for entry in found):
        return {"state": "unknown", "spending": "durable", "reason": "spending_unreadable"}
    entry: dict[str, Any] = {"spending": "durable", "authorities": found}
    if process_witness is not None:
        entry["process_witness"] = process_witness
    active = [authority for authority in found if authority["state"] == "active"]
    refusal = _PROCESS_WITNESS_REFUSALS.get(process_witness or "")
    usable = [
        authority
        for authority in active
        if refusal is None or authority.get("restore_protection") != "witnessed"
    ]
    if usable:
        return {"state": "open", **entry}
    if active and refusal is not None:
        # Every active authority is witnessed and this process cannot write its witness: the
        # process is refused alone, and the authorities stay active for every other process.
        return {
            "state": "blocked",
            "reason": "spending_suspended",
            "process_refusal": refusal,
            **entry,
        }
    suspensions = sorted(
        {authority["suspension"] for authority in found if authority["state"] == "suspended"}
    )
    if suspensions:
        return {
            "state": "blocked",
            "reason": "spending_suspended",
            "suspensions": suspensions,
            **entry,
        }
    return {"state": "blocked", "reason": "no_active_authority", **entry}


def _component(name: str, state: str, reason: str | None = None, **observed: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"component": name, "state": state}
    if reason is not None:
        entry["reason"] = reason
    if observed:
        entry["observed"] = observed
    return entry


def _maintenance_fresh(profile: InstallationProfile | None, status: Mapping[str, Any]) -> bool:
    if status["state"] != "present" or profile is None:
        return False
    age = dt.datetime.now(dt.UTC) - status["written_at"]
    return age <= dt.timedelta(seconds=2 * profile.recovery.export_interval_seconds)


def _queued(
    name: str, spec: ComponentSpec, status: Mapping[str, Any], fresh: bool
) -> dict[str, Any] | None:
    """A queued component's degraded state from maintenance's observation, when there is one."""
    if spec.queue_bound_seconds is None:
        return None
    if not fresh:
        return _component(name, "degraded", "queue_progress_unobserved")
    queues = status["document"].get("queues", {})
    seen = queues.get(name) if isinstance(queues, dict) else None
    oldest = seen.get("oldest_queued_seconds") if isinstance(seen, dict) else None
    if spec.preparers is not None and isinstance(seen, dict):
        # A request for a preparer this installation does not run waits by design, and is not late.
        oldest = _installed_preparers_oldest(spec.preparers, seen.get("preparers"))
    if isinstance(oldest, int) and not isinstance(oldest, bool):
        if oldest > spec.queue_bound_seconds:
            return _component(
                name,
                "degraded",
                "queue_progress_exceeds_bound",
                oldest_queued_seconds=oldest,
                bound_seconds=spec.queue_bound_seconds,
            )
        return None
    return _component(name, "degraded", "queue_progress_unobserved")


def _installed_preparers_oldest(preparers: Mapping[str, PreparerSpec], seen: Any) -> int | None:
    """The oldest wait among the installed preparers' requests, from maintenance's observation."""
    if not isinstance(seen, dict):
        return None
    oldest = 0
    for pin, spec in preparers.items():
        value = seen.get(pin, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if spec.installed:
            oldest = max(oldest, value)
    return oldest


def _preparer_states(
    spec: ComponentSpec, component: Mapping[str, Any]
) -> list[dict[str, Any]] | None:
    """Each declared preparer's state: its own declaration, else the component's state."""
    if spec.preparers is None:
        return None
    states: list[dict[str, Any]] = []
    for pin, preparer in sorted(spec.preparers.items()):
        if not preparer.installed:
            state, reason = "not_installed", preparer.reason
        elif preparer.reason is not None:
            state, reason = "unavailable", preparer.reason
        else:
            state, reason = component["state"], component.get("reason")
        entry: dict[str, Any] = {"preparer": pin, "state": state}
        if reason is not None:
            entry["reason"] = reason
        states.append(entry)
    return states


def _components(
    services: Services, installation: Installation, observed: Mapping[str, Any]
) -> list[dict[str, Any]]:
    profile = installation.profile
    status = observed["maintenance"]
    fresh = _maintenance_fresh(profile, status)
    no_model = services.model_client is None

    def spec(name: str) -> ComponentSpec:
        # Undeclared: say what this process can see, and nothing about other processes.
        if profile is None:
            return ComponentSpec(installed=name in ("database", "schema", "api", "ingestion"))
        return profile.components[name]

    def declared(name: str, running_here: bool = False) -> dict[str, Any]:
        component = spec(name)
        if running_here:
            return _component(name, "ready")
        if not component.installed:
            reason = "undeclared_installation" if profile is None else None
            return _component(name, "not_installed", reason)
        if component.unavailable_reason is not None:
            return _component(name, "unavailable", component.unavailable_reason)
        degraded = _queued(name, component, status, fresh)
        return degraded or _component(name, "configured")

    entries: list[dict[str, Any]] = []
    entries.append(
        _component("database", "ready")
        if observed["database"]
        else _component("database", "unavailable", "database_unreachable")
    )
    if not observed["database"]:
        entries.append(_component("schema", "unavailable", "database_unreachable"))
    elif not observed["schema_matches"]:
        entries.append(
            _component(
                "schema",
                "unavailable",
                "schema_mismatch",
                expected=observed["schema_expected"],
                applied=observed["schema_applied"],
            )
        )
    else:
        entries.append(_component("schema", "ready"))
    entries.append(_component("api", "ready"))
    entries.append(declared("client"))
    if profile is None:
        entries.append(_component("maintenance", "not_installed", "undeclared_installation"))
    elif fresh:
        failures = status["document"].get("failures", [])
        entries.append(
            _component("maintenance", "degraded", str(failures[0]))
            if isinstance(failures, list) and failures and _CODE.match(str(failures[0]))
            else _component("maintenance", "ready")
        )
    else:
        reason = status.get("reason", "maintenance_status_stale")
        entries.append(_component("maintenance", "degraded", reason))
    entries.append(
        _component("ingestion", "degraded", "provider_credential_absent")
        if no_model
        else _component("ingestion", "ready")
    )
    entries.append(declared("derivatives", running_here=services.runs_derivative_worker))
    entries.append(declared("pose_scene"))
    preparation = declared("preparation")
    if (preparers := _preparer_states(spec("preparation"), preparation)) is not None:
        preparation["preparers"] = preparers
    entries.append(preparation)
    if services.materials is None:
        entries.append(_component("materials", "unavailable", "material_catalog_absent"))
    else:
        entries.append(declared("materials"))
    if services.tiles is None:
        entries.append(_component("generated_tiles", "unavailable", "tile_store_absent"))
    else:
        entries.append(declared("generated_tiles"))
    if services.society_runtime is None:
        entries.append(_component("simulation", "unavailable", "society_runtime_absent"))
    elif services.society_control_enabled:
        entries.append(_component("simulation", "ready"))
    else:
        entries.append(_component("simulation", "configured", "advanced_on_request"))
    if no_model:
        entries.append(_component("comparison", "unavailable", "provider_credential_absent"))
    elif services.runs_comparison_worker:
        entries.append(_component("comparison", "ready"))
    elif services.comparisons_played_elsewhere:
        entries.append(declared("comparison"))
    else:
        entries.append(_component("comparison", "unavailable", "comparisons_not_run_here"))
    return entries


def _configuration_sha256(environ: Mapping[str, str] | None) -> str:
    from exulanica.api.services import describe_configuration

    return hashlib.sha256(canonical_json(describe_configuration(environ))).hexdigest()


def installation_facts(
    services: Services, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """This installation's ``exulanica.installation-facts/v1`` document. Cheap; never raises."""
    installation = services.installation or Installation(None, None, {}, None)
    observed = installation.cached("observed", lambda: _observations(services, installation))
    profile = installation.profile
    status = observed["maintenance"]
    fresh = _maintenance_fresh(profile, status)
    document = status.get("document", {}) if fresh else {}
    export = document.get("withdrawal_export") if isinstance(document, dict) else None
    no_model = services.model_client is None
    return {
        "profile": FACTS_PROFILE,
        "observed_at": observed["observed_at"],
        "installation": (
            {"id": profile.id, "version": profile.version, "sha256": profile.sha256}
            if profile is not None
            else None
        ),
        "identity": {
            "code_revision": installation.code_revision,
            "images": dict(installation.images),
            "schema": {
                "expected": observed["schema_expected"],
                "applied": observed["schema_applied"],
            },
            "configuration_sha256": installation.cached(
                "configuration", lambda: {"sha256": _configuration_sha256(environ)}
            )["sha256"],
        },
        "components": _components(services, installation, observed),
        "models": {
            "mode": "no_model" if no_model else "hosted",
            "paid_admission": paid_admission(
                no_model=no_model,
                spending_mode=services.spending_mode,
                authorities=observed.get("spending"),
                process_witness=observed.get("process_witness"),
            ),
        },
        "store": _store_facts(services, profile, observed),
        "recovery": {
            "restore_state": observed["restore_state"],
            "withdrawal_authority": (
                {
                    "kind": "periodic_export",
                    "covered_through": export.get("covered_through"),
                    "lag_seconds": export.get("lag_seconds"),
                }
                if isinstance(export, dict)
                else None
            ),
            "last_verified_backup_at": document.get("last_verified_backup_at")
            if isinstance(document, dict)
            else None,
        },
        "serving": observed["serving"],
    }


def installation_summary(services: Services) -> dict[str, Any]:
    """What unauthenticated readiness may say: the profile, whether it serves, each component.

    ``/readyz`` is public, so it carries no identity, digest, configuration fingerprint or
    recovery time. The whole document is :func:`installation_facts`, served to an authorised
    operator at ``GET /operations/installation`` and read in process by the capability projection.
    """
    facts = installation_facts(services)
    installation = facts["installation"]
    return {
        "installation": (
            {"id": installation["id"], "version": installation["version"]}
            if installation is not None
            else None
        ),
        "serving": {"state": facts["serving"]["state"]},
        "components": [
            {key: entry[key] for key in ("component", "state", "reason") if key in entry}
            for entry in facts["components"]
        ],
    }
