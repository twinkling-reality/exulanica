"""Notes made from a person's own picture are withdrawn when the picture's right stops or the
picture is deleted (migration 0160 and its follow-ups), whoever writes the stop, and however it
races a job's finish.

A photograph is ingested and admitted as the purge tests admit one, with a right for the picture
reader's chain granted as the product grants it. A finished reference request's bundle names that
picture and right, as the worker writes one. The stop is withdraw_model_right and the deletion is
a tombstone of capture, interval or workspace scope, each written as the runtime role (row security
binds it) and as the owner (a restore and an operator's command write as the owner). The races use
two sessions and wait until one is blocked on the other's advisory lifecycle lock before letting it
go.
"""

from __future__ import annotations

import threading
import time
import uuid

import psycopg
import pytest
from exulanica.db.migrate import provision_workspace
from exulanica.ingest.model_rights import withdraw_model_right
from exulanica.ingest.repository import IngestRepository
from exulanica.models.manifest import Role, load_manifest
from exulanica.references import store
from exulanica.references.bundle import BundleNote, BundlePicture
from exulanica.references.for_drafting import NotesRefused, notes_for_draft

from reference_fixtures import (
    REFERENCE_ACTOR,
    WEB_NOTES,
    finished_reference,
    queued_reference,
    scripted_bundle,
)
from test_purge import _APP_PASSWORD, _APP_ROLE
from test_purge import purged as purged
from test_search_entries_on_stop import ACCOUNT, _authorize, _grant

pytestmark = pytest.mark.postgres

#: A note read from the picture: aspect, text and basis.
_PICTURE_NOTE = ("buildings", "low stone walls around a yard", "own_picture")
#: How long a race waits for one session to block on the other's lock.
_BLOCKED_WITHIN = 10.0


class Pictured:
    """A workspace with one admitted picture, its reader's rights, and the vision right beside."""

    def __init__(self, fixture) -> None:
        self.fixture = fixture
        self.workspace_id = fixture.workspace_id
        repository = fixture.repository
        provision_workspace(repository.connection, fixture.workspace_id)
        self.capture_id = fixture.rows("select capture_id from capture")[0]["capture_id"]
        authorization = _authorize(repository, self.capture_id)
        self.authorization_id = authorization.authorization_id
        manifest = load_manifest()
        self.rights = _grant(
            repository,
            self.capture_id,
            authorization.authorization_id,
            Role.REFERENCE_VISION,
            manifest,
        )
        self.vision = _grant(
            repository, self.capture_id, authorization.authorization_id, Role.VISION, manifest
        )
        self.search = _grant(
            repository, self.capture_id, authorization.authorization_id, Role.EMBEDDING, manifest
        )
        reader = manifest[Role.REFERENCE_VISION].primary
        self.picture = BundlePicture(
            self.capture_id,
            tuple(right.right_id for right in self.rights),
            ("nebius_token_factory", "reference_vision", reader.model_id),
        )

    def bundle(self, pictures=None):
        named = (self.picture,) if pictures is None else pictures
        notes = WEB_NOTES
        if any(picture.picture_id == self.capture_id for picture in named):
            notes = (*WEB_NOTES, BundleNote(*_PICTURE_NOTE, self.capture_id))
        return scripted_bundle(self.workspace_id, notes=notes, pictures=named)

    def finished(self, pictures=None, *, actor: uuid.UUID = REFERENCE_ACTOR) -> uuid.UUID:
        return finished_reference(
            self.fixture.repository.connection,
            self.workspace_id,
            actor=actor,
            bundle=self.bundle(pictures),
        )

    def granted_again(self) -> list:
        """Another reading right on the picture, granted by the same person (ACCOUNT)."""
        return _grant(
            self.fixture.repository,
            self.capture_id,
            self.authorization_id,
            Role.REFERENCE_VISION,
            load_manifest(),
        )

    def request(self, reference_id: uuid.UUID) -> store.ReferenceRequest:
        found = store.read_request(
            self.fixture.repository.connection, self.workspace_id, reference_id
        )
        assert found is not None
        return found

    def runtime(self):
        return self.fixture.database(role=_APP_ROLE, password=_APP_PASSWORD).session(
            self.workspace_id
        )


@pytest.fixture
def pictured(purged) -> Pictured:
    return Pictured(purged)


def _writer(pictured: Pictured, who: str):
    """A connection of the named writer in the workspace's session, and its closing."""
    if who == "owner":
        return _Borrowed(pictured.fixture.repository.connection)
    return pictured.runtime()


class _Borrowed:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *exc) -> None:
        return None


def _stop(connection, workspace_id, right_id) -> None:
    withdraw_model_right(
        IngestRepository(connection, workspace_id), right_id=right_id, withdrawn_by=ACCOUNT
    )


#: Each scope that blocks a capture, as the tombstone's own columns state it.
_SCOPES = {
    "capture": {"scope": "capture"},
    "interval": {"scope": "interval", "track_key": "img", "interval_ns": [(0, 1)]},
    "workspace": {"scope": "workspace"},
}


def _delete(connection, workspace_id, capture_id, scope: str = "capture") -> None:
    named = _SCOPES[scope]
    IngestRepository(connection, workspace_id).insert_tombstone(
        **named,
        capture_id=None if scope == "workspace" else capture_id,
        requested_by=ACCOUNT,
        reason="the person deleted this picture",
    )


def _withdrawn(found: store.ReferenceRequest) -> bool:
    return (found.status, found.bundle, found.bundle_sha256) == ("withdrawn", None, None)


# -- the two writes, by each writer -------------------------------------------------------------


@pytest.mark.parametrize("who", ["runtime", "owner"])
def test_stopping_the_picture_right_withdraws_exactly_the_notes_read_under_it(pictured, who):
    read = pictured.finished()
    web_only = pictured.finished(pictures=())
    other_right = pictured.finished(
        pictures=(BundlePicture(pictured.capture_id, (uuid.uuid4(),), pictured.picture.model),)
    )
    with _writer(pictured, who) as connection:
        if who == "runtime":
            assert connection.execute("select current_user as who").fetchone()["who"] == _APP_ROLE
        _stop(connection, pictured.workspace_id, pictured.rights[0].right_id)
    assert _withdrawn(pictured.request(read))
    assert pictured.request(web_only).status == "complete"
    assert pictured.request(other_right).status == "complete"
    with pytest.raises(NotesRefused) as refused:
        notes_for_draft(
            pictured.fixture.repository.connection,
            pictured.workspace_id,
            REFERENCE_ACTOR,
            read,
            purpose="kind",
            bases=("web_description", "own_picture"),
        )
    assert refused.value.code == "reference_withdrawn"


def test_stopping_a_right_of_another_role_withdraws_nothing(pictured):
    read = pictured.finished()
    with pictured.runtime() as connection:
        for right in pictured.vision:
            _stop(connection, pictured.workspace_id, right.right_id)
    assert pictured.request(read).status == "complete"


@pytest.mark.parametrize(
    ("who", "scope"),
    [("runtime", "capture"), ("owner", "capture"), ("runtime", "interval"), ("owner", "workspace")],
)
def test_deleting_the_picture_withdraws_the_notes_made_from_it(pictured, who, scope):
    read = pictured.finished()
    web_only = pictured.finished(pictures=())
    other_picture = pictured.finished(
        pictures=(BundlePicture(uuid.uuid4(), (uuid.uuid4(),), pictured.picture.model),)
    )
    with _writer(pictured, who) as connection:
        _delete(connection, pictured.workspace_id, pictured.capture_id, scope)
    assert _withdrawn(pictured.request(read))
    assert pictured.request(web_only).status == "complete"
    # A workspace's deletion blocks every picture in it; a capture's or an interval's, its own.
    expected = "withdrawn" if scope == "workspace" else "complete"
    assert pictured.request(other_picture).status == expected


def test_a_tombstone_that_blocks_no_picture_withdraws_nothing(pictured):
    read = pictured.finished()
    # Stopping the search right writes a caption_search tombstone over the picture (0104), which
    # erases search entries and leaves the picture.
    with pictured.runtime() as connection:
        for right in pictured.search:
            _stop(connection, pictured.workspace_id, right.right_id)
    scopes = pictured.fixture.rows("select scope::text as scope from tombstone")
    assert [row["scope"] for row in scopes] == ["caption_search"]
    assert pictured.request(read).status == "complete"


# -- what a withdrawn request may be ------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ("status='complete'", "never changes"),
        ("steps='[]'::jsonb", "never changes"),
    ],
)
def test_a_withdrawn_request_never_changes(pictured, change, words):
    read = pictured.finished()
    with pictured.runtime() as connection:
        _stop(connection, pictured.workspace_id, pictured.rights[0].right_id)
    with pytest.raises(psycopg.errors.CheckViolation, match=words):
        pictured.fixture.repository.connection.execute(
            f"update reference_request set {change} where reference_id=%s", (read,)
        )


@pytest.mark.parametrize(
    "change",
    [
        "status='withdrawn'",
        "status='withdrawn', bundle=null, bundle_sha256=null, steps='[]'::jsonb",
    ],
)
def test_a_request_is_withdrawn_by_clearing_its_bundle_and_nothing_else(pictured, change):
    read = pictured.finished()
    with pytest.raises(psycopg.errors.CheckViolation, match="clears its bundle and nothing else"):
        pictured.fixture.repository.connection.execute(
            f"update reference_request set {change} where reference_id=%s", (read,)
        )


def test_a_queued_request_is_never_withdrawn(pictured):
    queued = queued_reference(pictured.fixture.repository.connection, pictured.workspace_id)
    with pytest.raises(psycopg.errors.CheckViolation, match="queued to running"):
        pictured.fixture.repository.connection.execute(
            "update reference_request set status='withdrawn', finished_at=now() "
            "where reference_id=%s",
            (queued,),
        )


# -- a reading in flight ------------------------------------------------------------------------


def _running(pictured: Pictured, *, actor: uuid.UUID = REFERENCE_ACTOR) -> store.ClaimedRequest:
    connection = pictured.fixture.repository.connection
    reference_id = queued_reference(connection, pictured.workspace_id, actor=actor)
    claimed = store.claim(connection, pictured.workspace_id, worker="withdrawal-test")
    assert claimed is not None and claimed.request.reference_id == reference_id
    return claimed


def _finish(connection, pictured: Pictured, claimed: store.ClaimedRequest) -> str | None:
    bundle = pictured.bundle()
    return store.finish(
        connection,
        claimed,
        status="complete",
        steps=[],
        bundle=bundle.document(),
        bundle_sha256=bundle.digest,
    )


@pytest.mark.parametrize("stopped", ["right", "capture", "interval", "workspace"])
def test_a_finish_after_a_stop_in_flight_ends_withdrawn(pictured, stopped):
    claimed = _running(pictured)
    with pictured.runtime() as connection:
        if stopped == "right":
            _stop(connection, pictured.workspace_id, pictured.rights[0].right_id)
        else:
            _delete(connection, pictured.workspace_id, pictured.capture_id, stopped)
    with pictured.runtime() as connection:
        assert _finish(connection, pictured, claimed) == "withdrawn"
    assert _withdrawn(pictured.request(claimed.request.reference_id))


def test_a_finish_with_nothing_stopped_keeps_its_bundle(pictured):
    claimed = _running(pictured)
    with pictured.runtime() as connection:
        assert _finish(connection, pictured, claimed) == "complete"
    assert pictured.request(claimed.request.reference_id).bundle is not None


class _Session(threading.Thread):
    """One write in a session of its own, reporting its backend so the test can see it wait."""

    def __init__(self, pictured: Pictured, write) -> None:
        super().__init__(daemon=True)
        self.pictured = pictured
        self.write = write
        self.pid: int | None = None
        self.result = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            with self.pictured.runtime() as connection:
                self.pid = connection.info.backend_pid
                self.result = self.write(connection)
        except BaseException as error:  # reported to the test thread
            self.error = error


def _blocked_or_done(pictured: Pictured, session: _Session) -> bool:
    """Whether the session is seen waiting on an advisory lock (the lifecycle lock every stop,
    tombstone and finish takes) within the bound; False when it finished without waiting, never
    waited, or waited on something else, such as a row."""
    deadline = time.monotonic() + _BLOCKED_WITHIN
    while time.monotonic() < deadline:
        if not session.is_alive():
            return False
        if session.pid is not None:
            waiting = pictured.fixture.rows(
                "select 1 from pg_stat_activity where pid=%s and wait_event_type='Lock' "
                "and wait_event='advisory'",
                session.pid,
            )
            if waiting:
                return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("stopped", ["read", "another"])
def test_a_finish_racing_a_stop_it_waited_on_ends_withdrawn(pictured, stopped):
    # The right the bundle was read under, or another reading right the same person holds on it.
    claimed = _running(pictured, actor=ACCOUNT)
    right = pictured.rights[0] if stopped == "read" else pictured.granted_again()[0]
    with pictured.runtime() as stopping, stopping.transaction():
        _stop(stopping, pictured.workspace_id, right.right_id)
        finishing = _Session(pictured, lambda c: _finish(c, pictured, claimed))
        finishing.start()
        assert _blocked_or_done(pictured, finishing), "the finish did not wait on the stop"
    finishing.join(_BLOCKED_WITHIN)
    assert finishing.error is None, finishing.error
    assert finishing.result == "withdrawn"
    assert _withdrawn(pictured.request(claimed.request.reference_id))


@pytest.mark.parametrize("scope", ["capture", "interval", "workspace"])
def test_a_finish_racing_a_deletion_it_waited_on_ends_withdrawn(pictured, scope):
    claimed = _running(pictured)
    with pictured.runtime() as deleting, deleting.transaction():
        _delete(deleting, pictured.workspace_id, pictured.capture_id, scope)
        finishing = _Session(pictured, lambda c: _finish(c, pictured, claimed))
        finishing.start()
        assert _blocked_or_done(pictured, finishing), "the finish did not wait on the deletion"
    finishing.join(_BLOCKED_WITHIN)
    assert finishing.error is None, finishing.error
    assert finishing.result == "withdrawn"


@pytest.mark.parametrize("stopped", ["read", "another", "granted_during"])
def test_a_stop_racing_a_finish_it_waited_on_withdraws_what_the_finish_kept(pictured, stopped):
    # The right the bundle was read under; another reading right its person held on the picture
    # before the finish; or one the person grants while the finish is under way. Each stop waits
    # on the lifecycle lock the finish holds.
    claimed = _running(pictured, actor=ACCOUNT)
    right = None
    if stopped == "read":
        right = pictured.rights[0]
    elif stopped == "another":
        (right,) = pictured.granted_again()
    with pictured.runtime() as finishing:
        with finishing.transaction():
            # The finish's own transaction is a savepoint of this one, so its locks stay held.
            assert _finish(finishing, pictured, claimed) == "complete"
            if right is None:
                (right,) = pictured.granted_again()
            stopping = _Session(
                pictured,
                lambda c: _stop(c, pictured.workspace_id, right.right_id),
            )
            stopping.start()
            assert _blocked_or_done(pictured, stopping), "the stop did not wait on the finish"
        stopping.join(_BLOCKED_WITHIN)
    assert stopping.error is None, stopping.error
    assert _withdrawn(pictured.request(claimed.request.reference_id))


@pytest.mark.parametrize("scope", ["capture", "interval", "workspace"])
def test_a_deletion_racing_a_finish_it_waited_on_withdraws_what_the_finish_kept(pictured, scope):
    claimed = _running(pictured)
    with pictured.runtime() as finishing:
        with finishing.transaction():
            assert _finish(finishing, pictured, claimed) == "complete"
            deleting = _Session(
                pictured, lambda c: _delete(c, pictured.workspace_id, pictured.capture_id, scope)
            )
            deleting.start()
            assert _blocked_or_done(pictured, deleting), "the deletion did not wait on the finish"
        deleting.join(_BLOCKED_WITHIN)
    assert deleting.error is None, deleting.error
    assert _withdrawn(pictured.request(claimed.request.reference_id))


def test_a_partial_finish_after_a_stop_ends_withdrawn(pictured):
    claimed = _running(pictured)
    with pictured.runtime() as connection:
        _stop(connection, pictured.workspace_id, pictured.rights[0].right_id)
    bundle = scripted_bundle(
        pictured.workspace_id,
        notes=WEB_NOTES,
        pictures=(pictured.picture,),
        missed=("search",),
    )
    with pictured.runtime() as connection:
        ended = store.finish(
            connection,
            claimed,
            status="partial",
            steps=[],
            bundle=bundle.document(),
            bundle_sha256=bundle.digest,
        )
    assert ended == "withdrawn"
    assert _withdrawn(pictured.request(claimed.request.reference_id))


_BYPASSING_ROLE = "exulanica_references_bypass_suite"
_BYPASSING_PASSWORD = "references-bypass-suite-password"


@pytest.mark.parametrize("write", ["stop", "delete"])
def test_a_writer_that_bypasses_row_security_withdraws_its_own_workspace_s_notes_only(
    pictured, write
):
    """As a restore writes: a role that is no superuser and bypasses row security, in a session of
    the right's workspace. Another workspace's request naming the same picture and right stays."""
    from exulanica.db.roles import provision_runtime_role
    from exulanica.db.session import set_workspace

    owner = pictured.fixture.repository.connection
    read = pictured.finished()
    elsewhere = uuid.uuid4()
    set_workspace(owner, elsewhere)
    provision_workspace(owner, elsewhere)
    try:
        bundle = scripted_bundle(
            elsewhere,
            notes=(*WEB_NOTES, BundleNote(*_PICTURE_NOTE, pictured.capture_id)),
            pictures=(pictured.picture,),
        )
        other = finished_reference(owner, elsewhere, bundle=bundle)
    finally:
        set_workspace(owner, pictured.workspace_id)
    provision_runtime_role(owner, role=_BYPASSING_ROLE, password=_BYPASSING_PASSWORD)
    owner.execute(f"alter role {_BYPASSING_ROLE} bypassrls")
    database = pictured.fixture.database(role=_BYPASSING_ROLE, password=_BYPASSING_PASSWORD)
    with database.session(pictured.workspace_id) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": True}, role
        if write == "stop":
            _stop(connection, pictured.workspace_id, pictured.rights[0].right_id)
        else:
            _delete(connection, pictured.workspace_id, pictured.capture_id)
    assert _withdrawn(pictured.request(read))
    set_workspace(owner, elsewhere)
    try:
        found = store.read_request(owner, elsewhere, other)
    finally:
        set_workspace(owner, pictured.workspace_id)
    assert found is not None and found.status == "complete"


# -- a stop by the person who asked ---------------------------------------------------------------


def test_stopping_any_of_a_person_s_picture_rights_withdraws_every_request_of_theirs_naming_it(
    pictured,
):
    # Read under the first right; the person later grants the picture again and stops that grant,
    # as when the first right expired. Their request is withdrawn; another person's is not.
    theirs = pictured.finished(actor=ACCOUNT)
    another_person = pictured.finished(actor=REFERENCE_ACTOR)
    (again,) = pictured.granted_again()
    with pictured.runtime() as connection:
        _stop(connection, pictured.workspace_id, again.right_id)
    assert _withdrawn(pictured.request(theirs))
    assert pictured.request(another_person).status == "complete"


def test_a_finish_after_its_person_stopped_another_right_on_the_picture_ends_withdrawn(pictured):
    connection = pictured.fixture.repository.connection
    reference_id = queued_reference(connection, pictured.workspace_id, actor=ACCOUNT)
    claimed = store.claim(connection, pictured.workspace_id, worker="withdrawal-test")
    assert claimed is not None and claimed.request.reference_id == reference_id
    (again,) = pictured.granted_again()
    with pictured.runtime() as stopping:
        _stop(stopping, pictured.workspace_id, again.right_id)
    with pictured.runtime() as finishing:
        assert _finish(finishing, pictured, claimed) == "withdrawn"


def test_a_stop_made_before_the_request_was_asked_withdraws_nothing_new(pictured):
    # A single-row stop, as only a writer outside the withdraw route (an operator's command) can
    # make now: it leaves the person's other reading rights current, and a request asked after it
    # is read under them.
    (again,) = pictured.granted_again()
    with pictured.runtime() as connection:
        _stop(connection, pictured.workspace_id, again.right_id)
    connection = pictured.fixture.repository.connection
    queued_reference(connection, pictured.workspace_id, actor=ACCOUNT)
    claimed = store.claim(connection, pictured.workspace_id, worker="withdrawal-test")
    assert claimed is not None
    with pictured.runtime() as finishing:
        assert _finish(finishing, pictured, claimed) == "complete"


def test_the_list_knows_whether_the_caller_holds_a_current_picture_right(pictured):
    from exulanica.api.routes.references import _holds_picture_right

    connection = pictured.fixture.repository.connection
    assert _holds_picture_right(connection, pictured.workspace_id, ACCOUNT)
    assert not _holds_picture_right(connection, pictured.workspace_id, uuid.uuid4())
    with pictured.runtime() as stopping:
        for right in pictured.rights:
            _stop(stopping, pictured.workspace_id, right.right_id)
    assert not _holds_picture_right(connection, pictured.workspace_id, ACCOUNT)


def test_a_finish_at_another_isolation_level_is_refused(pictured):
    claimed = _running(pictured)
    with (
        pictured.runtime() as connection,
        pytest.raises(psycopg.errors.SerializationFailure, match="READ COMMITTED"),
        connection.transaction(),
    ):
        connection.execute("set transaction isolation level repeatable read")
        _finish(connection, pictured, claimed)
    assert pictured.request(claimed.request.reference_id).status == "running"


def test_the_finish_check_refuses_a_request_it_cannot_find(pictured):
    from psycopg.types.json import Jsonb

    with (
        pictured.runtime() as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="no reference request"),
    ):
        connection.execute(
            "select reference_bundle_withdrawn(%s, %s, %s)",
            (pictured.workspace_id, uuid.uuid4(), Jsonb(pictured.bundle().document())),
        )


def test_a_picture_stop_ends_its_grantor_s_other_reading_rights_and_no_one_else_s(pictured):
    import datetime as dt
    from types import SimpleNamespace

    from exulanica.api.routes.personal_admission import withdraw_right
    from exulanica.ingest.model_rights import grant_model_right
    from exulanica.ingest.personal_admission import role_handoff
    from exulanica.ingest.privacy import authorize_personal_capture

    repository = pictured.fixture.repository
    (again,) = pictured.granted_again()
    someone_else = uuid.uuid4()
    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    authority = authorize_personal_capture(
        repository,
        capture_id=pictured.capture_id,
        actor=someone_else,
        account_authority_basis="I took this photograph too",
        authorization_scope={"purpose": "Find my own photographs by what they show."},
        purpose="Find my own photographs by what they show.",
        authorized_at=now - dt.timedelta(hours=1),
        valid_until=now + dt.timedelta(hours=2),
    )
    handoff = role_handoff("reference_vision")
    (theirs,) = [
        grant_model_right(
            repository,
            capture_id=pictured.capture_id,
            authorization_id=authority.authorization_id,
            identity=identity,
            destination=handoff.destination,
            granted_by=someone_else,
            purpose="Find my own photographs by what they show.",
            valid_until=now + dt.timedelta(minutes=60),
        )
        for identity in handoff.identities
    ]
    with pictured.runtime() as connection:
        ended = withdraw_right(
            again.right_id,
            _BEARER,
            connection,
            SimpleNamespace(workspace_id=pictured.workspace_id, actor=ACCOUNT),
        )
    assert ended["state"] == "ended"
    states = {
        row["right_id"]: row["ended"]
        for row in pictured.fixture.rows(
            "select right_id, withdrawn_at is not null as ended from personal_model_right "
            "where model_role = 'reference_vision'"
        )
    }
    assert states[again.right_id] and all(states[r.right_id] for r in pictured.rights)
    assert states[theirs.right_id] is False


# -- the withdraw route: who stops a picture's reading right, what a stop ends, its locks ----------


class _BearerRequest:
    """What the withdraw route reads of a request a bearer token made: an Authorization header, so
    no membership, as when the route is called directly."""

    def __init__(self) -> None:
        self.headers = {"authorization": "Bearer called-directly"}


_BEARER = _BearerRequest()
_SESSION_COOKIE = "__Host-exulanica-session"


class _OwnerAccounts:
    """The account runtime's methods the app calls, with one browser session: a fixed cookie
    resolving to an ``owner`` membership of the workspace for ``actor``."""

    def __init__(self, cookie: str, workspace_id: uuid.UUID, actor: uuid.UUID) -> None:
        from exulanica.selection.validation import Session

        self.cookie = cookie
        self.session = Session(workspace_id, actor)

    def browser_session(self, request):
        from exulanica.api.account_repository import AccountSession
        from exulanica.api.authorisation import TokenNotAccepted

        if request.cookies.get(_SESSION_COOKIE) != self.cookie:
            raise TokenNotAccepted("browser session was not accepted")
        return AccountSession(uuid.uuid4(), self.session, "c" * 43, None, "owner")

    def authenticate_request(self, request):
        return self.browser_session(request).session

    def active_owned_workspaces(self):
        return ()

    def recent_workspaces(self, _seconds):
        return ()

    def owned_workspace_active(self, _workspace_id) -> bool:
        return True


def _http(
    pictured: Pictured, tmp_path, tokens: dict[str, uuid.UUID], owner: uuid.UUID | None = None
):
    """The app over the runtime role (row security binds it), each token a grant of every
    permission for its actor, and, when ``owner`` is given, a browser session of the workspace's
    owner held by that actor (cookie "owner-cookie")."""
    import json

    from exulanica.api.app import create_app
    from exulanica.api.authorisation import load_token_directory
    from exulanica.api.services import Services
    from fastapi.testclient import TestClient

    from tests_support_api import EVERY_PERMISSION

    fixture = pictured.fixture
    grants = {
        token: {
            "workspace_id": str(pictured.workspace_id),
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        }
        for token, actor in tokens.items()
    }
    services = Services(
        database=fixture.database(role=_APP_ROLE, password=_APP_PASSWORD),
        readonly_database=fixture.database(role=_APP_ROLE, password=_APP_PASSWORD),
        store=fixture.store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=True,
        model_client=None,
        environment_admission_root=tmp_path / "admission",
        accounts=(
            None if owner is None else _OwnerAccounts("owner-cookie", pictured.workspace_id, owner)  # type: ignore[arg-type]
        ),
    )
    return TestClient(create_app(services, verify=False))


def _stop_over_http(http, right_id: uuid.UUID, *, token: str | None = None):
    path = f"/personal-admission/model-rights/{right_id}/withdraw"
    if token is not None:
        return http.post(path, headers={"Authorization": f"Bearer {token}"})
    return http.post(path, headers={"Cookie": f"{_SESSION_COOKIE}=owner-cookie"})


def _reading_states(pictured: Pictured) -> dict[uuid.UUID, tuple[bool, uuid.UUID | None]]:
    """Every reading right on the picture: whether it is withdrawn, and by whom."""
    return {
        row["right_id"]: (row["ended"], row["withdrawn_by"])
        for row in pictured.fixture.rows(
            "select right_id, withdrawn_at is not null as ended, withdrawn_by "
            "from personal_model_right where capture_id = %s and model_role = 'reference_vision'",
            pictured.capture_id,
        )
    }


@pytest.mark.parametrize("who", ["grantor", "owner", "another"])
def test_a_picture_right_is_stopped_only_by_its_grantor_or_the_workspace_s_owner(
    pictured, tmp_path, who
):
    """Over HTTP as the runtime role. The grantor or an owner of the workspace (a browser session
    in the owner role, another actor) ends every reading right the grantor holds on the picture,
    each recorded as withdrawn by the caller, and the answer names the right asked for, here the
    lowest id of them. Anyone else, holding every permission, is answered as for an id nobody
    granted, and nothing changes."""
    (again,) = pictured.granted_again()
    held = sorted([*(right.right_id for right in pictured.rights), again.right_id])
    caller = {"grantor": ACCOUNT, "owner": uuid.uuid4(), "another": uuid.uuid4()}[who]
    tokens = {"grantor-token-long-enough-0000000000": ACCOUNT}
    if who == "another":
        tokens["another-token-long-enough-000000000"] = caller
    with _http(pictured, tmp_path, tokens, owner=caller if who == "owner" else None) as http:
        answered = _stop_over_http(
            http,
            held[0],
            token={"grantor": "grantor-token-long-enough-0000000000", "owner": None}.get(
                who, "another-token-long-enough-000000000"
            ),
        )
    states = _reading_states(pictured)
    if who == "another":
        assert answered.status_code == 404, answered.text
        assert answered.json()["detail"] == "no such model right"
        assert all(ended is False for ended, _by in states.values())
        return
    assert answered.status_code == 200, answered.text
    assert answered.json()["right_id"] == str(held[0])
    assert answered.json()["state"] == "ended"
    assert {right_id: states[right_id] for right_id in held} == {
        right_id: (True, caller) for right_id in held
    }


def test_another_role_s_stop_through_the_route_leaves_the_picture_s_reading_rights(
    pictured, tmp_path
):
    """A stop of the vision right, by its grantor, ends that right alone: the reading rights the
    same person holds on the photograph stay current."""
    (vision,) = pictured.vision[:1]
    with _http(pictured, tmp_path, {"grantor-token-long-enough-0000000000": ACCOUNT}) as http:
        answered = _stop_over_http(
            http, vision.right_id, token="grantor-token-long-enough-0000000000"
        )
    assert answered.status_code == 200, answered.text
    assert answered.json()["right_id"] == str(vision.right_id)
    assert all(ended is False for ended, _by in _reading_states(pictured).values())


def test_a_repeated_stop_ends_only_what_was_granted_before_the_first(pictured):
    """A right stopped alone (a single-row stop, as an operator's command makes) leaves an older
    sibling current: stopping it again through the route ends that sibling. A consent granted after
    the stop is never ended by stopping the old right again."""
    from types import SimpleNamespace

    from exulanica.api.routes.personal_admission import withdraw_right

    session = SimpleNamespace(workspace_id=pictured.workspace_id, actor=ACCOUNT)
    (older,) = pictured.granted_again()
    (stopped,) = pictured.rights[:1]
    with pictured.runtime() as connection:
        _stop(connection, pictured.workspace_id, stopped.right_id)
    assert _reading_states(pictured)[older.right_id][0] is False
    with pictured.runtime() as connection:
        withdraw_right(stopped.right_id, _BEARER, connection, session)
    assert _reading_states(pictured)[older.right_id][0] is True
    (newer,) = pictured.granted_again()
    with pictured.runtime() as connection:
        answered = withdraw_right(stopped.right_id, _BEARER, connection, session)
    assert answered["right_id"] == str(stopped.right_id)
    assert _reading_states(pictured)[newer.right_id] == (False, None)


def test_a_route_stop_locks_its_rights_before_it_takes_the_privacy_lock(pictured):
    """A concurrent stop holds one sibling's row. The route's stop of another right waits on that
    row lock holding no privacy-currency lock (a third session takes it at once), then ends both
    once the row is free, with no deadlock. Were it to withdraw before locking its siblings, it
    would wait on the row while holding privacy-currency: the deadlock the 3c3 review named."""
    from types import SimpleNamespace

    from exulanica.api.routes.personal_admission import withdraw_right

    (sibling,) = pictured.granted_again()
    (stopped,) = pictured.rights[:1]
    session = SimpleNamespace(workspace_id=pictured.workspace_id, actor=ACCOUNT)
    with pictured.runtime() as holder, holder.transaction():
        holder.execute(
            "select 1 from personal_model_right where workspace_id = %s and right_id = %s "
            "for no key update",
            (pictured.workspace_id, sibling.right_id),
        )
        route = _Session(
            pictured,
            lambda connection: withdraw_right(stopped.right_id, _BEARER, connection, session),
        )
        route.start()
        assert _waits_on_a_row(pictured, route), "the route's stop never waited on the held row"
        with pictured.runtime() as third, third.transaction():
            free = third.execute(
                "select pg_try_advisory_xact_lock("
                "hashtextextended('privacy-currency:' || %s::text, 0)) as free",
                (pictured.workspace_id,),
            ).fetchone()
            assert (free["free"] if isinstance(free, dict) else free[0]) is True
    route.join(timeout=_BLOCKED_WITHIN)
    assert not route.is_alive()
    assert route.error is None, route.error
    states = _reading_states(pictured)
    assert states[stopped.right_id][0] is True and states[sibling.right_id][0] is True


def _waits_on_a_row(pictured: Pictured, session: _Session) -> bool:
    """Whether the session is seen waiting on a row lock (a transaction id or a tuple)."""
    deadline = time.monotonic() + _BLOCKED_WITHIN
    while time.monotonic() < deadline:
        if not session.is_alive():
            return False
        if session.pid is not None and pictured.fixture.rows(
            "select 1 from pg_stat_activity where pid = %s and wait_event_type = 'Lock' "
            "and wait_event in ('transactionid', 'tuple')",
            session.pid,
        ):
            return True
        time.sleep(0.05)
    return False
