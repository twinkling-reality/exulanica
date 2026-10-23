"""A creature drafted from a person's words: a request kept as a row, played by a job (0184).

``POST /things/creatures`` queues a draft (:func:`create_draft`) and answers at once; a worker in
the API process (:class:`CreatureDraftWorker`) claims the draft's job, asks the creature drafter
(:func:`exulanica.selection.creature_drafting.draft_creature`, role ``creature_drafter``) and keeps
a creature the checks pass in the workspace's own store
(:meth:`exulanica.world.thing_store.ThingStore.keep_creature`); ``GET
/things/creatures/drafts/{draft_id}`` reads the draft as it goes.

The job is claimed as a reference job is (:mod:`exulanica.references.store`): ``for update skip
locked``, a lease and a claim token, at most :data:`MAXIMUM_CLAIMS` claims, and every write that
ends a draft names its claim token, so a worker that lost its lease ends nothing. A job stranded
every time it was claimed, or queued and never taken for :data:`QUEUED_EXPIRY_SECONDS`, is ended as
failed. Every path that locks both rows locks the job's first, then the draft's.

The job's payload holds what the work needs and nothing more: the draft's id, and the person's words
as they are sent, every saved name already replaced, with the placeholders that replaced them. Every
end of a draft blanks the words, and the draft keeps nothing of them, not even their digest: a
digest of a short sentence is the sentence. A kept draft names its kind by the digest of the kind's
document alone, so erasing the creature (``thing_erasure``) leaves the draft naming a kind nobody
holds, and a refused draft names a code and a field of the drafter's form, never a sentence: a
person reads the code's fixed sentence (:func:`refusal_sentence`), as a check's own sentence may
quote the drafted label. A draft is queued only for a workspace a worker here serves, and at most
:data:`MAX_OPEN_PER_ACTOR` unfinished and :data:`MAX_PER_ACTOR_HOUR` in an hour for any one
requester, since each spends model calls. Only its requester reads a draft through the routes.
Spending is keyed by the job, so under durable spending a job taken again after a crash is admitted
under the same key and the authority refuses what already happened rather than paying for it
twice; under process spending the key is not checked, and a job taken again may pay again, once
for each of its at most :data:`MAXIMUM_CLAIMS` claims. Every API process of an installation carries
the same creature settings, since each ends at startup the drafts of the workspaces it knows but
does not serve (:func:`end_unserved`).

A workspace tombstone ends the workspace's unfinished drafts in its own transaction (a trigger on
``tombstone``): each queued or running job is cancelled with its words blanked, and its draft ends
``cancelled``, failure ``workspace_deleted``. A draft is asked under the workspace's lock and never
once that tombstone is written (:func:`create_draft`). A worker that drafted for a cancelled draft
reads that its claim is gone and keeps nothing; a call it already sent finishes at the provider, and
its answer is discarded.

A draft that keeps its creature then asks for that creature's made look in its owner's name
(:func:`exulanica.world.creature_look_jobs.ask_on_keep`), so a made look is the default way a kept
creature looks: a queued look job spends nothing, an operator's run makes it, and the creature wears
its sketch until then. The draft has ended ``kept`` before the ask, which never undoes it: an owner
at their look limits, a workspace being erased or a creature erased since asks nothing. A draft
conditioned on a reference asks nothing here, as its words may carry what notes read from a picture;
its owner may still ask for the look.

An optional reference ID is kept on the draft, never as copied note text in its job. Only the
requester's completed or partial web notes for things may condition the draft. Usage distinguishes
a response to that request, possible delivery without a response, and known non-delivery; neither
the record nor the resulting origin ingredient claims a reference caused a particular field.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable, Collection, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Final, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.env import env_name
from exulanica.epistemics.saved_names import PLACEHOLDER, redact_names, saved_names
from exulanica.errors import ExulanicaError, TombstonedError
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ModelError
from exulanica.models.manifest import Manifest, Role, load_manifest
from exulanica.models.policy import HostedRequestPolicy, HostedRequestRefused
from exulanica.models.request_envelopes import request_bytes_at_most
from exulanica.models.spending import (
    BUDGET_EXCEEDED,
    HELD_CLOSED,
    SpendingRefused,
    spending_request_key,
)
from exulanica.models.usage import USD_QUANTUM, CallOutcome, CallUsage, CostBasis, usd_string
from exulanica.references import store as reference_store
from exulanica.references.bundle import BASES, THINGS_PICTURE_PROFILE
from exulanica.references.drafting import prompts_for_request
from exulanica.references.for_drafting import (
    NotesForDraft,
    NotesRefused,
    PictureNotesAuthority,
    notes_for_draft,
)
from exulanica.selection.calls import CallLog
from exulanica.selection.creature_drafting import (
    CHECK_SENTENCES,
    DRAFT_ATTEMPTS,
    DRAFTER_ROLE,
    NOT_DRAFTED_SENTENCE,
    CreatureDraftRefusalCode,
    creature_drafting_prompt,
    draft_creature,
    draft_form,
)
from exulanica.spending.status import SpendingRefusals
from exulanica.store.base import ContentAddressedStore
from exulanica.things.bodies import body_grammar
from exulanica.things.lines import check_line
from exulanica.world.creature_look_jobs import ask_on_keep
from exulanica.world.thing_store import STORE_CODES, ThingStore, ThingStoreRefused
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "CANCELLATION_CODES",
    "CREATURES_NOT_RUN_HERE",
    "CREATURE_WORKER_ENV",
    "CREATURE_WORKSPACES_ENV",
    "FAILURE_CODES",
    "FINISHED",
    "JOB_KIND",
    "LEASE_SECONDS",
    "LISTED",
    "MAXIMUM_CLAIMS",
    "MAX_OPEN_PER_ACTOR",
    "MAX_PER_ACTOR_HOUR",
    "MAX_WORDS_CHARACTERS",
    "MODELS_NOT_CONFIGURED",
    "OFFER_REFUSALS",
    "QUEUED_EXPIRY_SECONDS",
    "ClaimedDraft",
    "CreatureDraft",
    "CreatureDraftWorker",
    "CreatureSettingRefused",
    "DraftLimitReached",
    "DraftNotOffered",
    "abandon_stranded",
    "claim",
    "create_draft",
    "creature_workspaces",
    "draft_limits",
    "draft_spend",
    "end_unserved",
    "expire_unclaimed",
    "finish",
    "list_drafts",
    "plays_creatures_here",
    "price_at_most",
    "read_draft",
    "refusal_codes",
    "refusal_field",
    "refusal_sentence",
    "refusal_sentences",
    "spending_key",
]

_LOG = logging.getLogger(__name__)

JOB_KIND: Final = "creature_draft"
#: A draft is a form and at most one repair, each bounded by the creature drafter's timeout; the
#: lease outlasts both twice over, so a slow call never loses the claim, and a dead worker's job is
#: taken again within the lease.
LEASE_SECONDS: Final = 900
MAXIMUM_CLAIMS: Final = 2
#: A queued draft no worker has taken in this long is ended as failed (``expired``): a worker polls
#: every second, so ten minutes untaken means none is coming. One worker thread plays one draft at
#: a time across every listed workspace, each up to about 100 seconds (a call and its repair at the
#: drafter's timeout), so a queue of more than about six such drafts can end its last ones as
#: expired while the worker is still on its way; one open draft per requester bounds the queue by
#: the number of people asking.
QUEUED_EXPIRY_SECONDS: Final = 600
#: A person's words for one creature: a line, as the drafter's form states its own.
MAX_WORDS_CHARACTERS: Final = 400
#: One requester's unfinished drafts, and drafts in the last hour: each spends up to two model
#: calls, so one requester cannot queue without end.
MAX_OPEN_PER_ACTOR: Final = 1
MAX_PER_ACTOR_HOUR: Final = 20
FINISHED: Final = ("kept", "refused", "failed", "cancelled")
#: How a worker ends a draft; only a workspace tombstone cancels one (a trigger on ``tombstone``).
_ENDS: Final = ("kept", "refused", "failed")
#: Why a draft was cancelled, by code: its workspace was erased, which ends every unfinished draft.
CANCELLATION_CODES: Final = ("workspace_deleted",)
#: Why a draft could not be made, by code: the drafter did not answer, the spending authority
#: (``spending_suspended`` while it is held closed until an operator acts, nothing spent;
#: ``spending_refused`` otherwise) or the workspace's rules refused the request, or no worker took
#: the draft (queued too long, stranded, or its workspace not served here).
FAILURE_CODES: Final = (
    "drafter_unavailable",
    "expired",
    "not_served",
    "request_refused",
    "reference_withdrawn",
    "spending_refused",
    "spending_suspended",
    "stranded",
)
CREATURES_NOT_RUN_HERE: Final = "creatures_not_run_here"
MODELS_NOT_CONFIGURED: Final = "models_not_configured"
#: Why a workspace may not ask for a creature here, by code: no worker here drafts its creatures,
#: this process has no model client to draft them with, the durable authority would refuse the
#: drafter's first attempt (``budget_exceeded``), or it is held closed until an operator acts
#: (``spending_suspended``: spending paused, not spent; :func:`offer_spending_refusal`).
OFFER_REFUSALS: Final = (
    CREATURES_NOT_RUN_HERE,
    MODELS_NOT_CONFIGURED,
    BUDGET_EXCEEDED,
    HELD_CLOSED,
)
#: The most drafts a listing answers, newest first.
LISTED: Final = 20
_JOB_STATE: Final = {"kept": "done", "refused": "done", "failed": "failed"}
#: The lock seed that counts one requester's drafts, so two racing requests see each other.
_REQUESTER_LOCK_SEED: Final = 880160
_DURATION: Final = (
    "duration_ms=greatest(0, (extract(epoch from (now() - created_at)) * 1000)::bigint)"
)
#: The payload a job keeps once its draft has ended: the draft's id and nothing of the words.
_BLANKED: Final = "payload=jsonb_build_object('draft_id', payload->'draft_id')"
_COLUMNS: Final = (
    "draft_id, owner_actor_id, job_id, status, kind_sha256, refusal_code, refusal_field, failure, "
    "model_id, created_at, started_at, finished_at, reference_id, reference_usage"
)
#: The code whose fixed sentence says only that a movement is not built; the grammar states each
#: movement's own sentence, which a refusal naming that movement's field reads instead.
_MOVEMENT_UNBUILT: Final = "creature_movement_unbuilt"


def refusal_sentences() -> Mapping[str, str]:
    """Every code a refused draft may name, with the fixed sentence a person reads for it: a
    check's (the drafter tells the model each one), the store's, and the drafter's own when no check
    is named. Closed: a refusal outside it is carried as ``creature_not_drafted``."""
    return {
        **CHECK_SENTENCES,
        **STORE_CODES,
        CreatureDraftRefusalCode.NOT_DRAFTED.value: NOT_DRAFTED_SENTENCE,
    }


def refusal_codes() -> tuple[str, ...]:
    """Every code a refused draft may name, in order."""
    return tuple(sorted(refusal_sentences()))


def refusal_field(where: str) -> str | None:
    """The field of the drafter's form a check refused, or None where the refusal names no one
    field (the whole creature, or several fields): only the form's own field names are kept."""
    return where if where in draft_form().model_fields else None


def refusal_sentence(code: str, field: str | None = None) -> str:
    """The sentence a person reads for a refused draft, from its code and field alone, never from
    the request: a movement this world has not built yet in the grammar's own sentence for that
    movement, and every other code in its check's, the store's or the drafter's sentence."""
    if code == _MOVEMENT_UNBUILT and field is not None and field.startswith("moves_"):
        spec = body_grammar().movements.get(field.removeprefix("moves_"))
        if spec is not None and spec.get("refusal"):
            return str(spec["refusal"])
    return refusal_sentences().get(code, NOT_DRAFTED_SENTENCE)


def spending_key(job_id: uuid.UUID) -> str:
    """The key a draft's attempts are admitted under, counted from one in the order they are made
    (:func:`~exulanica.models.spending.spending_request_key`): its job's, stable across a claim
    taken again."""
    return f"creature:{job_id}"


def _answer_tokens(manifest: Manifest) -> int:
    """The drafter's answer bound: the manifest's limit for its role, else the role's default."""
    binding = manifest[DRAFTER_ROLE]
    return binding.default_max_tokens if binding.max_tokens is None else binding.max_tokens.value


def draft_limits(manifest: Manifest) -> dict[Role, tuple[int, int]] | None:
    """The request bound and answer bound a draft's attempts are held to, as its price states
    them: the drafter's request envelope (:mod:`exulanica.models.request_envelopes`) and answer
    bound, for the client's chain to refuse any attempt beyond before it is sent; None where the
    catalog names no envelope for the drafter, whose price is then a whole context window."""
    envelope = request_bytes_at_most(DRAFTER_ROLE)
    return None if envelope is None else {DRAFTER_ROLE: (envelope, _answer_tokens(manifest))}


def price_at_most(manifest: Manifest, wire_attempts: int) -> dict[str, Any]:
    """The most one draft may be charged, a decimal string, with the account it is charged to and
    its basis.

    Each dispatch is priced at the drafter's request envelope of input (never more than the
    model's context window) and the route's answer bound, at the manifest's prices: the draft's
    attempts run under those two bounds (:func:`draft_limits`), and the client's chain refuses one
    beyond either before it is sent, so neither an attempt's reported cost nor the reservation one
    of unknown outcome keeps passes it. A draft is a form and one repair (``DRAFT_ATTEMPTS``), each
    sent at most ``wire_attempts`` times (every fallback and retry of the client), all priced at
    the route's dearest model. Where the catalog names no envelope for the drafter, each dispatch
    is priced at a whole context window, as no request can pass that either.
    """
    binding = manifest[DRAFTER_ROLE]
    answer = _answer_tokens(manifest)
    envelope = request_bytes_at_most(DRAFTER_ROLE)
    inputs = {
        spec.model_id: spec.context_window_tokens
        if envelope is None
        else min(envelope, spec.context_window_tokens)
        for spec in binding.chain
    }
    each = max(
        spec.cost_usd(prompt_tokens=inputs[spec.model_id], completion_tokens=answer)
        for spec in binding.chain
    )
    dispatches = DRAFT_ATTEMPTS * wire_attempts
    return {
        "usd_at_most": usd_string(
            (each * dispatches).quantize(USD_QUANTUM, rounding=ROUND_CEILING)
        ),
        "provider": binding.provider,
        "provider_description": manifest.provider(binding.provider).description,
        "basis": {
            "kind": "full_context_ceiling" if envelope is None else "request_envelope_ceiling",
            "attempts_at_most": DRAFT_ATTEMPTS,
            "wire_attempts_per_attempt_at_most": wire_attempts,
            "input_tokens_at_most": max(inputs.values()),
            "answer_tokens_at_most": answer,
        },
    }


def offer_spending_refusal(refusals: SpendingRefusals | None, client: ModelClient) -> str | None:
    """Why the durable authority would refuse a draft's first attempt, by code, before anyone types:
    ``spending_suspended`` while it is held closed for the drafter's provider, ``budget_exceeded``
    where it refuses that provider otherwise (spent, not granted, revoked or expired) or what is
    left is below one attempt's floor; None where it would admit one, or in a process no durable
    authority admits. A draft asks its route's first model and the chain never falls back on a
    refusal, so that model's provider answers. The floor is the answer bound and the prompt's own
    instructions at the model's prices, which the rendered instructions and the words only add to,
    so a remainder below it admits no attempt."""
    if refusals is None:
        return None
    binding = load_manifest()[DRAFTER_ROLE]
    spec = binding.primary
    refused = refusals.by_provider.get(spec.provider)
    if refused is not None:
        return refused.problem_code
    left = refusals.available_usd.get(spec.provider)
    answer = binding.default_max_tokens if binding.max_tokens is None else binding.max_tokens.value
    floor = client.budget.estimate_usd(
        spec, prompt_chars=len(creature_drafting_prompt().instructions), max_tokens=answer
    )
    return BUDGET_EXCEEDED if left is not None and left < floor else None


#: What the spending authority recorded of one draft's attempts, from migration 0124's
#: reservations under the draft's key: what those that ended settled at, and what those still under
#: way hold.
_SPEND_SQL: Final = (
    "select coalesce(sum(settled_usd) filter (where state not in ('admitted', 'dispatched')), 0) "
    "as spent, coalesce(sum(reserved_usd) filter (where state in ('admitted', 'dispatched')), 0) "
    "as held from spending_reservation where workspace_id=%s and starts_with(request_key, %s)"
)


def draft_spend(
    connection: psycopg.Connection, workspace_id: uuid.UUID, draft: CreatureDraft
) -> dict[str, str]:
    """What the durable spending authority recorded of a draft's attempts, never an estimate:
    ``spent_usd``, what those that ended settled at (a reported cost, nothing for one that never
    left, the whole reservation of one whose outcome is unknown, or what an operator reconciled it
    to), and ``held_usd``, what those still under way hold; both zero before the first. Only a
    durable authority keeps attempts: under a process's own budget there is nothing to read."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            _SPEND_SQL, (workspace_id, f"{spending_key(draft.job_id)}#")
        ).fetchone()
    assert row is not None
    return {
        "spent_usd": usd_string(Decimal(row["spent"])),
        "held_usd": usd_string(Decimal(row["held"])),
    }


#: Absent or on, this process plays creature drafts in a thread; ``off`` (or ``0``, ``false``,
#: ``no``), nobody does, and a draft is refused before it is queued.
CREATURE_WORKER_ENV: Final = env_name("CREATURE_WORKER")
#: A JSON array of the workspace ids whose people may draft creatures here. Absent, none may: each
#: draft spends model calls on the installation's account.
CREATURE_WORKSPACES_ENV: Final = env_name("CREATURE_WORKSPACES")


class CreatureSettingRefused(ValueError):
    """A creature setting this process will not start with, named by code and variable."""

    def __init__(self, code: str, variable: str) -> None:
        super().__init__(f"{code}: {variable}")
        self.code = code
        self.variable = variable


def plays_creatures_here(value: str | None) -> bool:
    """Whether this process plays creature drafts (``EXULANICA_CREATURE_WORKER``)."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "1", "true", "on", "yes", "here"):
        return True
    if normalized in ("0", "false", "off", "no"):
        return False
    raise CreatureSettingRefused("creature_worker_not_recognised", CREATURE_WORKER_ENV)


def creature_workspaces(value: str | None) -> tuple[uuid.UUID, ...]:
    """The workspaces whose people may draft creatures (``EXULANICA_CREATURE_WORKSPACES``), or a
    named refusal of a list half read."""
    if value is None or not value.strip():
        return ()
    try:
        document = json.loads(value)
    except json.JSONDecodeError:
        raise CreatureSettingRefused(
            "creature_workspaces_not_json", CREATURE_WORKSPACES_ENV
        ) from None
    if not isinstance(document, list):
        raise CreatureSettingRefused("creature_workspaces_not_array", CREATURE_WORKSPACES_ENV)
    workspaces: list[uuid.UUID] = []
    for entry in document:
        try:
            if not isinstance(entry, str):
                raise ValueError(entry)
            workspaces.append(uuid.UUID(entry))
        except ValueError:
            raise CreatureSettingRefused(
                "creature_workspaces_not_uuid", CREATURE_WORKSPACES_ENV
            ) from None
    return tuple(sorted(set(workspaces)))


class DraftNotOffered(ExulanicaError):
    """Creatures are not drafted for this workspace here, so no draft is queued for it."""


class DraftLimitReached(ExulanicaError):
    """This requester already has as many drafts open, or made this hour, as one may."""


@dataclass(frozen=True, slots=True)
class CreatureDraft:
    draft_id: uuid.UUID
    owner_actor_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    #: The digest of the kept kind's document; the kind itself may since have been erased.
    kind_sha256: str | None
    refusal_code: str | None
    refusal_field: str | None
    failure: str | None
    model_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    reference_id: uuid.UUID | None
    reference_usage: Mapping[str, Any] | None

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


def _draft(row: Mapping[str, Any]) -> CreatureDraft:
    return CreatureDraft(**{name: row[name] for name in CreatureDraft.__slots__})


def read_draft(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    draft_id: uuid.UUID,
    *,
    owner_actor_id: uuid.UUID | None = None,
) -> CreatureDraft | None:
    """The draft, or None. With ``owner_actor_id``, only that requester's: anyone else's reads as
    one that does not exist."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from creature_draft where workspace_id=%s and draft_id=%s "
            "and (%s::uuid is null or owner_actor_id=%s::uuid)",
            (workspace_id, draft_id, owner_actor_id, owner_actor_id),
        ).fetchone()
    return None if row is None else _draft(row)


def list_drafts(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    owner_actor_id: uuid.UUID,
    limit: int = LISTED,
) -> tuple[CreatureDraft, ...]:
    """A requester's drafts, newest first, at most ``limit``: a reload or a second tab finds one
    still running."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            f"select {_COLUMNS} from creature_draft where workspace_id=%s and owner_actor_id=%s "
            "order by created_at desc, draft_id limit %s",
            (workspace_id, owner_actor_id, limit),
        ).fetchall()
    return tuple(_draft(row) for row in rows)


def create_draft(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    offered_to: Collection[uuid.UUID],
    owner_actor_id: uuid.UUID,
    words: str,
    sent: str,
    placeholders: Mapping[Any, str],
    reference_id: uuid.UUID | None = None,
) -> CreatureDraft:
    """A new draft and its queued job.

    ``words`` are the person's as typed, held to the line rule and never kept, ``sent`` the same
    words with every saved name replaced and ``placeholders`` the record of those replacements,
    which the job hands the boundary. ``offered_to`` is every workspace a worker here takes
    creature drafts for; a draft for any other is :class:`DraftNotOffered`, so its words are never
    queued for nobody. The workspace's lock is taken first, and a workspace being erased (a
    ``workspace`` tombstone) drafts nothing more (:class:`TombstonedError`): a draft and its
    workspace's tombstone never interleave, so the tombstone either finds the draft committed and
    cancels it, or the draft finds the tombstone and no job holds the words."""
    if workspace_id not in offered_to:
        raise DraftNotOffered("creatures are not drafted for this workspace here")
    check_line(words, maximum=MAX_WORDS_CHARACTERS)
    draft_id = uuid.uuid4()
    payload = {
        "draft_id": str(draft_id),
        "sent": sent,
        "placeholders": {str(entity): label for entity, label in placeholders.items()},
    }
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        lock_workspace(connection, workspace_id)
        if cursor.execute(
            "select 1 from tombstone where workspace_id=%s and scope='workspace' limit 1",
            (workspace_id,),
        ).fetchone():
            raise TombstonedError(
                "tombstoned: the workspace has been deleted and drafts nothing more"
            )
        cursor.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, %s))",
            (f"{workspace_id}:{owner_actor_id}", _REQUESTER_LOCK_SEED),
        )
        counts = cursor.execute(
            "select count(*) filter (where finished_at is null) as open, "
            "count(*) filter (where created_at > now() - interval '1 hour') as hour "
            "from creature_draft where workspace_id=%s and owner_actor_id=%s",
            (workspace_id, owner_actor_id),
        ).fetchone()
        assert counts is not None
        if counts["open"] >= MAX_OPEN_PER_ACTOR or counts["hour"] >= MAX_PER_ACTOR_HOUR:
            raise DraftLimitReached("this requester has as many creature drafts as one may")
        job = cursor.execute(
            "insert into job (workspace_id, kind, payload) values (%s, %s, %s) returning job_id",
            (workspace_id, JOB_KIND, Jsonb(payload)),
        ).fetchone()
        assert job is not None
        row = cursor.execute(
            "insert into creature_draft "
            "(workspace_id, draft_id, owner_actor_id, job_id, reference_id) "
            f"values (%s, %s, %s, %s, %s) returning {_COLUMNS}",
            (workspace_id, draft_id, owner_actor_id, job["job_id"], reference_id),
        ).fetchone()
        assert row is not None
    return _draft(row)


@dataclass(frozen=True, slots=True)
class ClaimedDraft:
    """A claimed job and its draft: what the worker needs, and the token every write names. The
    words are left out of the repr, so they never reach a log line by way of one."""

    workspace_id: uuid.UUID
    job_id: uuid.UUID
    claim_token: uuid.UUID
    attempts: int
    draft: CreatureDraft
    sent: str = field(repr=False)
    placeholders: Mapping[uuid.UUID, str] = field(repr=False)


def _fail_orphan(cursor: psycopg.Cursor[Any], job_id: uuid.UUID) -> None:
    """End a creature job that names no draft of its workspace, so it never blocks the queue."""
    cursor.execute(
        "update job set state='failed', lease_expires_at=null, claim_token=null, "
        "completed_at=now(), failure_class='creature_draft_missing', "
        "last_error='the job names no creature draft of its workspace', "
        + _DURATION
        + ", "
        + _BLANKED
        + " where job_id=%s",
        (job_id,),
    )


def claim(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, worker: str
) -> ClaimedDraft | None:
    """Take the next queued creature job of this workspace, or None when there is none. A job
    naming no draft of its workspace is failed and the next one taken."""
    while True:
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            job = cursor.execute(
                "update job set state='running', claimed_by=%s, claimed_at=now(), "
                "attempts=attempts+1, claim_token=gen_random_uuid(), "
                "lease_expires_at=now()+make_interval(secs => %s) "
                "where job_id=(select job_id from job where workspace_id=%s and kind=%s "
                "and ((state='queued' and run_after<=now()) "
                "or (state='running' and lease_expires_at<now() and attempts<%s)) "
                "order by priority, job_id for update skip locked limit 1) "
                "returning job_id, payload, claim_token, attempts",
                (worker, LEASE_SECONDS, workspace_id, JOB_KIND, MAXIMUM_CLAIMS),
            ).fetchone()
            if job is None:
                return None
            payload = job["payload"]
            try:
                draft_id = uuid.UUID(str(payload["draft_id"]))
                sent = str(payload["sent"])
                placeholders = {
                    uuid.UUID(entity): str(label)
                    for entity, label in payload["placeholders"].items()
                }
            except (AttributeError, KeyError, TypeError, ValueError):
                _fail_orphan(cursor, job["job_id"])
                continue
            row = cursor.execute(
                "update creature_draft set status='running', started_at=coalesce(started_at, "
                "now()) where workspace_id=%s and draft_id=%s "
                f"and job_id=%s and status in ('queued', 'running') returning {_COLUMNS}",
                (workspace_id, draft_id, job["job_id"]),
            ).fetchone()
            if row is None:
                _fail_orphan(cursor, job["job_id"])
                continue
        return ClaimedDraft(
            workspace_id=workspace_id,
            job_id=job["job_id"],
            claim_token=job["claim_token"],
            attempts=int(job["attempts"]),
            draft=_draft(row),
            sent=sent,
            placeholders=placeholders,
        )


def _claim_held(connection: psycopg.Connection, claimed: ClaimedDraft) -> bool:
    """Whether the worker still holds the draft's claim, read without a lock: a draft cancelled
    while it was drafted (its workspace erased) is no longer the worker's to keep."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select 1 as held from job where job_id=%s and claim_token=%s and state='running'",
            (claimed.job_id, claimed.claim_token),
        ).fetchone()
    return row is not None


def _holds(cursor: psycopg.Cursor[Any], claimed: ClaimedDraft) -> bool:
    row = cursor.execute(
        "select 1 from job where job_id=%s and claim_token=%s and state='running' for update",
        (claimed.job_id, claimed.claim_token),
    ).fetchone()
    return row is not None


class _ClaimLost(ExulanicaError):
    """Another worker or workspace erasure ended this worker's authority."""


def _unused_reference(code: str) -> dict[str, Any]:
    return {"state": "not_used", "code": code, "bundle_sha256": None, "notes": 0, "basis": []}


def _reference_usage(notes: NotesForDraft, *, completed: bool) -> dict[str, Any]:
    return {
        "state": "used" if completed else "unknown",
        "code": None if completed else "reference_delivery_unknown",
        "bundle_sha256": notes.provenance["bundle_sha256"],
        "notes": notes.rendered.used,
        "basis": list(notes.rendered.bases),
    }


def _record_reference_usage(
    connection: psycopg.Connection, claimed: ClaimedDraft, usage: Mapping[str, Any]
) -> None:
    """Record only for the current claim, without extending a lock across a model request."""
    with connection.transaction(), connection.cursor() as cursor:
        if not _holds(cursor, claimed):
            raise _ClaimLost()
        cursor.execute(
            "update creature_draft set reference_usage=%s where workspace_id=%s "
            "and draft_id=%s and status='running'",
            (Jsonb(dict(usage)), claimed.workspace_id, claimed.draft.draft_id),
        )


def _guard_reference(
    connection: psycopg.Connection,
    claimed: ClaimedDraft,
    notes: NotesForDraft,
    picture_guard: Callable[[psycopg.Connection], None] | None = None,
) -> None:
    """Inside each store transaction: workspace, optional privacy/lifecycle, claim, reference.

    Picture-note authority uses no right-row or global asset-read lock here. Text-only checks
    retain their reference-row boundary. No lock is held while a provider is called.
    """
    if picture_guard is not None:
        _lock_picture_notes(connection, claimed.workspace_id)
    with connection.cursor() as cursor:
        if not _holds(cursor, claimed):
            raise _ClaimLost()
        cursor.execute(
            "select reference_id from reference_request where workspace_id=%s "
            "and reference_id=%s and owner_actor_id=%s for update",
            (claimed.workspace_id, claimed.draft.reference_id, claimed.draft.owner_actor_id),
        ).fetchone()
    assert claimed.draft.reference_id is not None
    current = notes_for_draft(
        connection,
        claimed.workspace_id,
        claimed.draft.owner_actor_id,
        claimed.draft.reference_id,
        purpose="things",
        bases=notes.rendered.bases,
    )
    if current.provenance != notes.provenance:
        raise NotesRefused("reference_withdrawn")

    if picture_guard is not None:
        picture_guard(connection)


def finish(
    connection: psycopg.Connection,
    claimed: ClaimedDraft,
    *,
    status: str,
    kind_sha256: str | None = None,
    refusal: tuple[str, str | None] | None = None,
    failure: str | None = None,
    model_id: str | None = None,
) -> bool:
    """End the draft and its job, blanking the words; False when the claim was lost.

    ``kind_sha256`` (the kind document's digest) for a kept creature, ``refusal`` (a code and the
    form's field, or None) for one the checks refused, ``failure`` (a code) for one that could not
    be made."""
    if status not in _ENDS:
        raise ValueError(f"a worker ends a draft as one of {_ENDS}")
    code, where = refusal if refusal is not None else (None, None)
    with connection.transaction(), connection.cursor() as cursor:
        if not _holds(cursor, claimed):
            return False
        cursor.execute(
            "update creature_draft set status=%s, kind_sha256=%s, refusal_code=%s, "
            "refusal_field=%s, failure=%s, model_id=%s, finished_at=now() where workspace_id=%s "
            "and draft_id=%s and status='running'",
            (
                status,
                kind_sha256,
                code,
                where,
                failure,
                model_id,
                claimed.workspace_id,
                claimed.draft.draft_id,
            ),
        )
        cursor.execute(
            "update job set state=%s, last_error=%s, failure_class=%s, completed_at=now(), "
            + _DURATION
            + ", lease_expires_at=null, claim_token=null, "
            + _BLANKED
            + " where job_id=%s and claim_token=%s and state='running'",
            (
                _JOB_STATE[status],
                failure,
                None if failure is None else f"creature_{failure}"[:64],
                claimed.job_id,
                claimed.claim_token,
            ),
        )
    return True


def _end_jobs(
    cursor: psycopg.Cursor[Any], workspace_id: uuid.UUID, where: str, failure: str, error: str
) -> int:
    jobs = cursor.execute(
        "update job set state='failed', lease_expires_at=null, claim_token=null, "
        "completed_at=now(), failure_class=%s, last_error=%s, "
        + _DURATION
        + ", "
        + _BLANKED
        + " where workspace_id=%s and kind=%s and "
        + where
        + " returning job_id",
        (f"creature_{failure}", error, workspace_id, JOB_KIND),
    ).fetchall()
    for job in jobs:
        cursor.execute(
            "update creature_draft set status='failed', failure=%s, finished_at=now() "
            "where workspace_id=%s and job_id=%s and status in ('queued', 'running')",
            (failure, workspace_id, job["job_id"]),
        )
    return len(jobs)


def abandon_stranded(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every creature job of this workspace stranded :data:`MAXIMUM_CLAIMS` times, and its
    draft as failed, blanking the words. Returns how many were ended."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            f"state='running' and lease_expires_at<now() and attempts>={MAXIMUM_CLAIMS}",
            "stranded",
            "claimed every time it was allowed and stranded every time",
        )


def expire_unclaimed(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every creature job of this workspace queued and untaken for
    :data:`QUEUED_EXPIRY_SECONDS`, and its draft as failed (``expired``), blanking the words."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            f"state='queued' and created_at < now() - interval '{QUEUED_EXPIRY_SECONDS} seconds'",
            "expired",
            "queued and never taken",
        )


def end_unserved(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """End every unfinished creature job of a workspace this installation does not serve, and its
    draft as failed (``not_served``), blanking the words."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        return _end_jobs(
            cursor,
            workspace_id,
            "state in ('queued', 'running')",
            "not_served",
            "the installation does not draft creatures for this workspace",
        )


class _Database(Protocol):
    def session(self, workspace_id: uuid.UUID) -> AbstractContextManager[psycopg.Connection]: ...


def _lock_picture_notes(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """Privacy currency before lifecycle, before the claim/reference rows; never right rows."""
    connection.execute("select privacy_currency_lock(%s)", (workspace_id,))
    connection.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"caption-vector-lifecycle:{workspace_id}",),
    )


class CreatureDraftWorker:
    """Plays the creature drafts of the workspaces it is given, one at a time per workspace."""

    def __init__(
        self,
        database: _Database,
        *,
        client: ModelClient,
        policy_for: Callable[[uuid.UUID], HostedRequestPolicy],
        looks_for: Callable[[uuid.UUID], ContentAddressedStore],
        workspaces: Callable[[], Iterable[uuid.UUID]],
        worker: str = "creatures",
        picture_notes_authority: PictureNotesAuthority | None = None,
    ) -> None:
        self._database = database
        self._client = client
        self._policy_for = policy_for
        self._looks_for = looks_for
        self._workspaces = workspaces
        self._worker = worker
        self._picture_notes_authority = picture_notes_authority

    def run(self, stop: threading.Event, *, poll_seconds: float = 1.0) -> None:
        """Play every workspace's creature drafts until ``stop`` is set."""
        while not stop.is_set():
            played = False
            for workspace_id in sorted(self._workspaces()):
                if stop.is_set():
                    return
                try:
                    played = self.run_once(workspace_id) is not None or played
                except Exception as failure:  # one workspace's failure never stops the others
                    _LOG.warning("creature draft failed", extra={"failure": type(failure).__name__})
            if not played:
                stop.wait(poll_seconds)

    def run_once(self, workspace_id: uuid.UUID) -> str | None:
        """Play one claimable draft of ``workspace_id``; its final status, or None."""
        with self._database.session(workspace_id) as connection:
            abandon_stranded(connection, workspace_id)
            expire_unclaimed(connection, workspace_id)
            claimed = claim(connection, workspace_id, worker=self._worker)
        if claimed is None:
            return None
        # Keyed by the job alone: a job taken again replays the same key.
        with spending_request_key(spending_key(claimed.job_id)):
            return self._play(claimed)

    def _play(self, claimed: ClaimedDraft) -> str:
        workspace_id = claimed.workspace_id
        client = self._client.with_policy(self._policy_for(workspace_id))
        # Held to the bounds its price states: an attempt larger than either is refused unsent.
        held = draft_limits(client.manifest)
        if held is not None:
            client = client.with_prices({}, limits=held)
        status = "failed"
        kind_sha256: str | None = None
        refusal: tuple[str, str | None] | None = None
        failure: str | None = None
        model_id: str | None = None
        notes: NotesForDraft | None = None
        reference_text: str | None = None
        picture_rights: Mapping[uuid.UUID, tuple[uuid.UUID, ...]] | None = None
        bases: tuple[str, ...] = ("web_description",)
        selected_picture_request = False
        placeholders = dict(claimed.placeholders)
        # A reclaimed job must not call an earlier uncertain dispatch "not used" merely because
        # durable spending refuses its repeated key. Only a known completed request upgrades it.
        prior = claimed.draft.reference_usage
        usage = dict(prior) if prior is not None else None
        observed = False
        uncertain = False

        def record(value: Mapping[str, Any]) -> None:
            nonlocal usage
            with self._database.session(workspace_id) as connection:
                _record_reference_usage(connection, claimed, value)
            usage = dict(value)

        def attempted(call: CallUsage) -> None:
            nonlocal observed, uncertain
            observed = True
            assert notes is not None
            if call.outcome is CallOutcome.COMPLETED:
                record(_reference_usage(notes, completed=True))
            elif (usage is not None and usage["state"] == "used") or uncertain:
                return
            elif call.cost_basis is CostBasis.NOT_SENT:
                record(
                    prior
                    if prior and prior["state"] in ("used", "unknown")
                    else _unused_reference("reference_not_sent")
                )
            else:
                uncertain = True
                record(_reference_usage(notes, completed=False))

        def picture_guard(connection: psycopg.Connection) -> None:
            nonlocal picture_rights
            assert notes is not None and claimed.draft.reference_id is not None
            if self._picture_notes_authority is None:
                raise NotesRefused("reference_withdrawn")
            picture_rights = self._picture_notes_authority(
                connection,
                workspace_id,
                claimed.draft.owner_actor_id,
                claimed.draft.reference_id,
                notes.rendered.photographs,
                picture_rights,
            )

        def before_attempt() -> None:
            assert notes is not None and claimed.draft.reference_id is not None
            with self._database.session(workspace_id) as connection, connection.transaction():
                if notes.rendered.photographs:
                    _lock_picture_notes(connection, workspace_id)
                current = notes_for_draft(
                    connection,
                    workspace_id,
                    claimed.draft.owner_actor_id,
                    claimed.draft.reference_id,
                    purpose="things",
                    bases=bases,
                )
                if current.provenance != notes.provenance:
                    raise NotesRefused("reference_withdrawn")
                if notes.rendered.photographs:
                    picture_guard(connection)
            # Persist uncertainty before dispatch so a crash/reclaim cannot invent non-delivery.
            record(
                usage
                if usage and usage["state"] == "used"
                else _reference_usage(notes, completed=False)
            )

        try:
            with self._database.session(workspace_id) as connection:
                taken = frozenset(
                    row["key"]
                    for row in connection.execute(
                        "select distinct key from thing_kind_version where workspace_id=%s",
                        (workspace_id,),
                    ).fetchall()
                )
                if claimed.draft.reference_id is not None:
                    source = reference_store.read_request(
                        connection,
                        workspace_id,
                        claimed.draft.reference_id,
                        owner_actor_id=claimed.draft.owner_actor_id,
                    )
                    if source is not None and source.purpose == "things":
                        # New selected-picture requests fail closed after withdrawal, including
                        # before their first attempt. Historical web-only fallback stays intact.
                        selected_picture_request = source.prompts_sha256 == prompts_for_request(
                            "things", pictures=True
                        ).sha256 and any(
                            step.get("step") == "read_picture" for step in source.steps
                        )
                        if (
                            source.bundle is not None
                            and source.bundle.get("profile") == THINGS_PICTURE_PROFILE
                        ):
                            selected_picture_request = bool(source.bundle.get("pictures"))
                            if self._picture_notes_authority is not None:
                                bases = BASES
                    try:
                        notes = notes_for_draft(
                            connection,
                            workspace_id,
                            claimed.draft.owner_actor_id,
                            claimed.draft.reference_id,
                            purpose="things",
                            bases=bases,
                        )
                    except NotesRefused as refused:
                        if (
                            prior and prior["state"] in ("used", "unknown")
                        ) or selected_picture_request:
                            raise
                        _record_reference_usage(
                            connection, claimed, _unused_reference(refused.code)
                        )
                    else:
                        if selected_picture_request and self._picture_notes_authority is None:
                            raise NotesRefused("reference_withdrawn")
                        if (
                            prior
                            and prior["state"] in ("used", "unknown")
                            and prior["bundle_sha256"] != notes.provenance["bundle_sha256"]
                        ):
                            raise NotesRefused("reference_withdrawn")
                        sent_notes = redact_names(
                            notes.rendered.text,
                            saved_names(connection, workspace_id),
                            placeholders,
                            reserved=[
                                match.group(0) for match in PLACEHOLDER.finditer(claimed.sent)
                            ],
                        )
                        reference_text = sent_notes.text
                        placeholders.update(sent_notes.placeholders)
            if notes is not None:
                client = client.with_attempts(attempted)
            outcome = draft_creature(
                client,
                claimed.sent,
                role=Role.CREATURE_DRAFTER,
                taken=taken,
                placeholders=placeholders,
                log=CallLog(),
                reference_text=reference_text,
                reference_bundle_sha256=None
                if notes is None
                else str(notes.provenance["bundle_sha256"]),
                before_attempt=None if notes is None else before_attempt,
                photographs=frozenset() if notes is None else notes.rendered.photographs,
            )
            model_id = outcome.model_id
            if outcome.creature is not None:
                with self._database.session(workspace_id) as connection:
                    if not _claim_held(connection, claimed):
                        return "lost"
                    ThingStore(
                        connection, workspace_id, self._looks_for(workspace_id)
                    ).keep_creature(
                        outcome.creature,
                        created_by=claimed.draft.owner_actor_id,
                        guard=None
                        if notes is None
                        else lambda: _guard_reference(
                            connection,
                            claimed,
                            notes,
                            picture_guard if notes.rendered.photographs else None,
                        ),
                    )
                status = "kept"
                kind_sha256 = outcome.creature.kind.sha256
            else:
                assert outcome.refusal is not None
                check = outcome.refusal.check
                status = "refused"
                refusal = (
                    (str(outcome.refusal.code), None)
                    if check is None
                    else (check[0], refusal_field(check[1]))
                )
        except _ClaimLost:
            return "lost"
        except NotesRefused:
            if not observed and not (prior and prior["state"] in ("used", "unknown")):
                try:
                    record(_unused_reference("reference_withdrawn"))
                except _ClaimLost:
                    return "lost"
            failure = "reference_withdrawn"
        except ThingStoreRefused as refused:
            status, refusal = "refused", (refused.code, None)
        except (SpendingRefused, HostedRequestRefused, BudgetExceededError) as refused:
            if notes is not None and not observed:
                try:
                    record(
                        prior
                        if prior and prior["state"] in ("used", "unknown")
                        else _unused_reference("reference_not_sent")
                    )
                except _ClaimLost:
                    return "lost"
            failure = (
                ("spending_suspended" if refused.reason == HELD_CLOSED else "spending_refused")
                if isinstance(refused, SpendingRefused)
                else (
                    "request_refused"
                    if isinstance(refused, HostedRequestRefused)
                    else "drafter_unavailable"
                )
            )
        except ModelError:
            failure = "drafter_unavailable"
        if failure is not None:
            status = "failed"
        if refusal is not None and refusal[0] not in refusal_codes():
            refusal = ("creature_not_drafted", None)
        with self._database.session(workspace_id) as connection:
            finished = finish(
                connection,
                claimed,
                status=status,
                kind_sha256=kind_sha256,
                refusal=refusal,
                failure=failure,
                model_id=model_id,
            )
        if (
            finished
            and status == "kept"
            and kind_sha256 is not None
            and claimed.draft.reference_id is None
        ):
            # The draft has ended kept: its creature's made look is asked for its owner, and
            # an ask refused leaves the creature kept in its sketch.
            with self._database.session(workspace_id) as connection:
                ask_on_keep(
                    connection,
                    workspace_id,
                    kind_sha256=kind_sha256,
                    requested_by=claimed.draft.owner_actor_id,
                )
        return status if finished else "lost"
