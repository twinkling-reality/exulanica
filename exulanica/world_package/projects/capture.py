"""Build a checkpoint selection from a running world through its World API, by GET only.

Capture is a client of the API; only apply-back uses the client's write method. It sends the
bearer it is given to the one base URL it is given, never in a URL, log or error, and it imports
nothing from the API package. The world authorizes every read and write; capture itself grants
nothing and writes nothing to the world.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, urlsplit

import httpx

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.models.egress import (
    EgressAllowlist,
    EgressError,
    declared_origin,
    parse_egress_allowlist,
)
from exulanica.models.transport import allowlisted_transport
from exulanica.world.decision_roles import decision_roles
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.placed_things import ThingKindReference, shipped_kind
from exulanica.world.society_decision_contract import situation
from exulanica.world.society_things import THING_NAMESPACE
from exulanica.world.trajectories import export_trajectories
from exulanica.world_package.projects.checkpoint import (
    ProjectError,
    decode,
    digest,
    document,
    evidence_document,
)
from exulanica.world_package.projects.schema import (
    LABEL_MAXIMUM,
    RESIDENT_NAME_MAXIMUM,
    TITLE_MAXIMUM,
    scan_values,
)

_SEGMENT = re.compile(r"^[A-Za-z0-9:._-]{1,200}$")
_NAME = re.compile(r"^[a-zA-Z0-9:._/-]{1,200}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OUTCOMES = {"applied": "applied", "rejected": "refused"}
_MAX_EVENT_PAGES = 64
#: How a being that is no resident of its town came into its society: placed there by a person,
#: or come in from outside.
_NOT_RESIDENTS: Final = ("placed", "crossed")


def read_token(path: Path) -> str:
    """Read a bearer from a regular file into memory. It is never printed or returned upward."""
    if path.is_symlink() or not path.is_file():
        raise ProjectError("token file must be a regular file")
    with path.open("rb") as stream:
        raw = stream.read(8193)
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ProjectError("token file must hold one ASCII line") from exc
    if len(raw) > 8192 or not token or any(c.isspace() for c in token):
        raise ProjectError("token file must hold one ASCII line")
    return token


def _origin(url: str) -> tuple[str, EgressAllowlist]:
    """The one origin capture may reach, as an allowlist of exactly that origin.

    The allowlist names hosts, not addresses: this machine is `http://localhost:PORT`. Plain
    http reaches only localhost; anything else needs https.
    """
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ProjectError("base URL must be scheme://host:port with no credentials or query")
    if parts.path not in ("", "/"):
        raise ProjectError("base URL must name an origin, not a path")
    try:
        origin = declared_origin(url)
        return origin, parse_egress_allowlist([origin])
    except ValueError as exc:
        raise ProjectError(
            "base URL must be http://localhost:PORT or an https host name, not an address"
        ) from exc


def check_origin(url: str) -> str:
    """The one origin a World API client may reach for `url`, or `ProjectError` by name."""
    return _origin(url)[0]


class NothingSelectable(ProjectError):
    """The version holds no placed thing a project can hold yet: nothing to record, no fault."""


def segment(value: str) -> str:
    if not isinstance(value, str) or _SEGMENT.fullmatch(value) is None:
        raise ProjectError("an identifier read from the world has an unsupported form")
    return quote(value, safe=":._-")


class WorldReader:
    """GET-only World API access for one world, with the bearer held in memory."""

    def __init__(
        self,
        base_url: str,
        token: str,
        world_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        origin, egress = _origin(base_url)
        # Every request is held to that one origin immediately before it connects, so the
        # bearer cannot be sent anywhere else, redirects included.
        self._client = httpx.Client(
            base_url=origin,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=False,
            timeout=timeout,
            transport=allowlisted_transport(egress, inner=transport),
        )
        self.world_id = world_id
        segment(world_id)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WorldReader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _send(self, route: str, path: str, params: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.get(path, params=params)
        except (httpx.HTTPError, EgressError) as exc:
            raise ProjectError(f"world API read {route} did not complete") from exc

    @staticmethod
    def _ok(route: str, response: httpx.Response) -> httpx.Response:
        if response.status_code != 200:
            # Neither the body nor the request line is echoed: either may carry selected values.
            raise ProjectError(f"world API refused {route} with status {response.status_code}")
        return response

    @staticmethod
    def _decoded(route: str, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ProjectError(f"world API returned malformed JSON for {route}") from exc

    def _get(self, route: str, path: str, params: dict[str, Any]) -> httpx.Response:
        return self._ok(route, self._send(route, path, params))

    def json(self, route: str, path: str, **params: Any) -> Any:
        return self._decoded(route, self._get(route, path, {"world_id": self.world_id, **params}))

    def json_if_found(self, route: str, path: str, **params: Any) -> Any:
        """As `json`, except that a resource the world answers 404 for is None: it is absent."""
        response = self._send(route, path, {"world_id": self.world_id, **params})
        if response.status_code == 404:
            return None
        return self._decoded(route, self._ok(route, response))

    def holds(self, route: str, path: str) -> bool:
        """Whether the world holds what `path` reads: False where it answers 404 (none, or not
        the reader's workspace's) or 410 (the world was removed); any other refusal is raised."""
        response = self._send(route, path, {"world_id": self.world_id})
        if response.status_code in (404, 410):
            return False
        self._ok(route, response)
        return True

    def json_unless_refused(self, route: str, path: str, code: str, **params: Any) -> Any:
        """As `json_if_found`, except that the world's refusal named `code` (422) is None too:
        what is read does not exist for this world."""
        response = self._send(route, path, {"world_id": self.world_id, **params})
        if response.status_code == 404:
            return None
        if response.status_code == 422:
            try:
                answered = response.json()
            except ValueError:
                answered = None
            if isinstance(answered, dict) and answered.get("code") == code:
                return None
        return self._decoded(route, self._ok(route, response))

    def raw(self, route: str, path: str) -> bytes:
        return self._get(route, path, {}).content

    def post(self, route: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        """One world write, used only by apply-back. Never retried: its outcome may be unknown.

        Returns the status and the decoded body, so a caller can read a refusal's code. Neither
        is echoed in an error, since either may carry selected values.
        """
        try:
            response = self._client.post(path, params={"world_id": self.world_id}, json=body)
        except (httpx.HTTPError, EgressError) as exc:
            raise ProjectError(
                f"world API write {route} did not complete; its outcome may be unknown"
            ) from exc
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None


def subject_id(world_id: str, thing_id: str) -> str:
    """The society's subject identity for a placed thing (`society_things._thing_id`)."""
    return str(uuid.uuid5(THING_NAMESPACE, f"{world_id}:{thing_id}"))


def _name(value: Any, fallback: str = "unrecorded") -> str:
    return value if isinstance(value, str) and _NAME.fullmatch(value) else fallback


def _natural(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


@dataclass
class Capture:
    checkpoint: dict[str, Any]
    dependencies: dict[str, bytes]
    report: dict[str, Any] = field(default_factory=dict)
    # Decision evidence of one session, kept beside the checkpoint (None when there is none).
    evidence: dict[str, Any] | None = None
    # Deterministic training trajectories (exulanica.world-trajectory/v1) for captured decisions.
    trajectories: dict[str, Any] | None = None


def _events(reader: WorldReader, version: str, subjects: set[str]) -> list[dict[str, Any]]:
    """Model decisions the society consumed for the selected subjects, oldest first."""
    found: list[dict[str, Any]] = []
    before = None
    for _ in range(_MAX_EVENT_PAGES):
        params: dict[str, Any] = {"limit": 256}
        if before is not None:
            params["before"] = before
        page = reader.json(
            "GET society events", f"/world/versions/{version}/society/events", **params
        )
        for event in page["events"]:
            body = event.get("document") or {}
            if (
                event.get("event_kind") == "decision_applied"
                and body.get("model")
                and event.get("subject_id") in subjects
            ):
                found.append(event)
        before = page.get("next")
        if before is None:
            return sorted(found, key=lambda e: (e["tick"], e["document"]["decision_seq"]))
    raise ProjectError("society history is longer than capture reads; select fewer records")


def _receipt(receipt: dict[str, Any], event: dict[str, Any] | None) -> dict[str, Any]:
    """The receipt and its minute as codes and numbers, from the record alone: no words."""
    provider = receipt.get("provider") or {}
    cost = provider.get("cost_usd")
    document = {} if event is None else event["document"]
    disposition = document.get("disposition")
    return {
        "status": receipt["status"],
        "reason": _name(receipt.get("reason")),
        "disposition": disposition
        if disposition in ("applied", "rejected", "superseded", "stale")
        else None,
        "disposition_reason": None if document.get("reason") is None else _name(document["reason"]),
        "consumed_tick": None if event is None else _natural(event.get("tick")),
        "served_model_id": provider.get("served_model_id")
        if isinstance(provider.get("served_model_id"), str)
        and _NAME.fullmatch(provider["served_model_id"])
        else None,
        "cost_usd": cost if isinstance(cost, str) else None,
        "cost_known": provider.get("cost_known") is True,
    }


def _readable(
    request: dict[str, Any], receipt: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any]:
    """What the record itself stores, made readable. Nothing from outside the record."""
    context = request["context"]
    proposal = receipt.get("proposal") or {}
    provider = receipt.get("provider") or {}
    cost = provider.get("cost_usd")
    return {
        "situation": "\n".join(situation(context)),
        "options": [option["label"] for option in context["options"]],
        "choice": proposal.get("label"),
        "line": proposal.get("line"),
        "status": receipt["status"],
        "reason": _name(receipt.get("reason")),
        "consumed_tick": event["tick"],
        "disposition": _name(event["document"].get("disposition")),
        "served_model_id": provider.get("served_model_id"),
        "cost_usd": cost if isinstance(cost, str) else None,
        "cost_known": provider.get("cost_known") is True,
    }


_PERSON_STOPS: Final = ("stopped_by_person", "paused_by_person")


def sessions_listing(reader: WorldReader, version: str) -> list[dict[str, Any]] | None:
    """The society's living sessions, newest first, or None where the version has no society."""
    listed = reader.json_if_found(
        "GET living sessions", f"/world/versions/{segment(version)}/society/control/sessions"
    )
    if listed is None:
        return None
    sessions = listed.get("sessions") if isinstance(listed, dict) else None
    if not isinstance(sessions, list):
        raise ProjectError("world API returned a malformed living session list")
    return sessions


def read_session(reader: WorldReader, version: str, which: str) -> dict[str, Any]:
    """One living session as the society read serves it: by id, or the newest for "latest"."""
    base = f"/world/versions/{version}/society/control/sessions"
    if which == "latest":
        listed = reader.json("GET living sessions", base)["sessions"]
        if not listed:
            raise ProjectError("this world has no living session")
        which = listed[0]["session_id"]
    return reader.json("GET living session", f"{base}/{segment(which)}")


def _asked_under(record: Mapping[str, Any]) -> tuple[Any, Any]:
    """The provider and model a decision record was asked under, as its request states them."""
    config = record["request"].get("provider_config") or {}
    return config.get("provider"), config.get("model_id")


def _written(value: Any) -> Any:
    """Words a person wrote, or None where they are absent or look like a local path or a
    credential (the project's value scan would refuse the whole file for them)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        scan_values(value)
    except ValueError:
        return None
    return value


def _kind_label(data: bytes) -> str | None:
    """A made kind's label as its document states it, or None where it states none a checkpoint
    can keep (absent, empty, longer than a label, or shaped like a path or a credential)."""
    try:
        document = decode(data)
    except ProjectError:
        return None
    label = _written(document.get("label")) if isinstance(document, dict) else None
    return label if label is not None and len(label) <= LABEL_MAXIMUM else None


def _title(view: Mapping[str, Any], readable: bool) -> str | None:
    """The version's title as written, kept only with readable text; a longer one than a
    checkpoint holds is left out."""
    title = _written(view.get("title")) if readable else None
    return title if title is not None and len(title) <= TITLE_MAXIMUM else None


def _being(thing: Mapping[str, Any]) -> bool:
    """Whether a placed thing is a being, as the character module decides: a kind its workspace
    keeps always is; a shipped kind is where its document says so."""
    kind = thing["kind"]
    if kind.get("source") == "workspace":
        return True
    try:
        reference = ThingKindReference(kind["kind"], kind["version"], kind["sha256"])
        return shipped_kind(reference).document["class"] == "being"
    except (InvalidThingPlacement, KeyError, TypeError):
        return False


def _characters(
    reader: WorldReader,
    version: str,
    things: Sequence[Mapping[str, Any]],
    readable: bool,
    *,
    cards: bool,
) -> list[dict[str, Any]]:
    """Who the world's owner wrote each selected being to be: the newest record's revision
    always, its words only with readable text. Read in one request
    (``GET .../things/characters``); an API that does not serve it is asked each being's card
    instead, where `cards` says the version has a society to answer them. A being with no record
    has none."""
    beings = [thing for thing in things if not thing.get("removed") and _being(thing)]
    if not beings:
        return []
    listed = reader.json_if_found(
        "GET thing characters", f"/world/versions/{version}/things/characters"
    )
    newest: dict[str, Any] | None = None
    if isinstance(listed, dict) and isinstance(listed.get("characters"), list):
        newest = {
            record.get("placed_id"): record
            for record in listed["characters"]
            if isinstance(record, dict)
        }
    elif not cards:
        return []
    found = []
    for thing in beings:
        if newest is not None:
            held = newest.get(thing["thing_id"])
        else:
            card = reader.json_if_found(
                "GET society thing",
                f"/world/versions/{version}/society/things/"
                f"{subject_id(reader.world_id, thing['thing_id'])}",
            )
            held = card.get("character") if isinstance(card, dict) else None
        if not isinstance(held, dict):
            continue
        revision = held.get("revision")
        if type(revision) is not int or revision < 1:
            continue
        entry: dict[str, Any] = {"thing_id": thing["thing_id"], "revision": revision}
        if readable:
            written = held.get("character") or {}
            entry["words"] = {
                "name": _written(written.get("name")),
                "about": _written(written.get("about")),
            }
        found.append(entry)
    return found


def _role_key(person: Mapping[str, Any]) -> str | None:
    """A resident's role by the town's key: a society of things states it on the resident's
    entry, a living town on the person, an older society only by a word."""
    resident = person.get("resident")
    role = resident.get("role") if isinstance(resident, Mapping) else None
    if not isinstance(role, Mapping):
        role = person.get("role")
    key = role.get("key") if isinstance(role, Mapping) else role
    return key if isinstance(key, str) and _NAME.fullmatch(key) else None


def _residents(
    reader: WorldReader, version: str, wanted: set[str], readable: bool
) -> dict[str, dict[str, Any]]:
    """The town's people among the `wanted` subjects, by subject: each with its role's key and,
    only with readable text, the name its society calls it by (a longer one than a checkpoint
    keeps is left out). A placed being or a visitor is no resident. Read in one request
    (``GET .../society``); a version with no society has none."""
    snapshot = reader.json_if_found("GET society", f"/world/versions/{version}/society")
    state = snapshot.get("state") if isinstance(snapshot, dict) else None
    people = state.get("inhabitants") if isinstance(state, dict) else None
    found: dict[str, dict[str, Any]] = {}
    for person in people if isinstance(people, list) else []:
        if (
            not isinstance(person, dict)
            or person.get("id") not in wanted
            or person.get("came_by") in _NOT_RESIDENTS
        ):
            continue
        entry: dict[str, Any] = {"resident_id": person["id"], "role": _role_key(person)}
        name = _written(person.get("display_name")) if readable else None
        if name is not None and len(name) <= RESIDENT_NAME_MAXIMUM:
            entry["name"] = name
        found[person["id"]] = entry
    return found


def _parts(
    reader: WorldReader,
    version: str,
    state_sha256: str,
    readable: bool,
    known: Mapping[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """A site world's made parts as the version has them, or None where it was not made from a
    world kind (422 ``parts_not_served``). Read again only when the version's state differs from
    the one the project holds them for, since a part's change is an edit of the version; while
    the world is still drawing them the read fails, to be tried at the next poll, and is never
    taken for no parts. Labels only with readable text: a world made from a person's words is
    worded from them. An API that serves no parts read (404) is read as a world with none."""
    if (
        known is not None
        and known.get("state_sha256") == state_sha256
        and isinstance(known.get("parts"), list)
        # Labels are kept with readable text and only with it: a change of that setting reads
        # the parts again.
        and readable == any("label" in p for p in known["parts"])
    ):
        return [dict(part) for part in known["parts"]]
    return read_parts(reader, version, readable=readable)


def read_parts(reader: WorldReader, version: str, *, readable: bool) -> list[dict[str, Any]] | None:
    """One read of a version's made parts as a checkpoint keeps them, or None where it has
    none."""
    answered = reader.json_unless_refused(
        "GET parts", f"/world/versions/{version}/parts", "parts_not_served"
    )
    if answered is None:
        return None
    standing = []
    for part in answered["parts"]:
        entry: dict[str, Any] = {
            "part_id": part["part_id"],
            "kind": part["kind"],
            "centre_mm": [int(part["centre_mm"][0]), int(part["centre_mm"][1])],
            "quarter_turns": int(part["quarter_turns"]),
            "removed": False,
        }
        label = _written(part.get("label")) if readable else None
        if label is not None:
            entry["label"] = label[:500]
        if type(part.get("storeys")) is int and part["kind"] == "building":
            entry["storeys"] = part["storeys"]
        standing.append(entry)
    held = {part["part_id"] for part in standing}
    removed = [
        {
            "part_id": change["identity"],
            "kind": None,
            "centre_mm": None,
            "quarter_turns": int(change["quarter_turns"]),
            "removed": True,
        }
        for change in answered["changes"]
        if change.get("removed") and change["identity"] not in held
    ]
    return standing + removed


def _instant(value: str) -> str:
    """A UTC instant to the second, in the evidence format's one spelling."""
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def living_session_block(session: Mapping[str, Any]) -> dict[str, Any]:
    """The session's receipts and the spending authority's figures; no actor or request ids."""
    opened, closed, used = session["opened"], session["closed"], session["used"]
    return {
        "session_id": session["session_id"],
        "state": session["state"],
        "opened": {
            "tick": opened["start_tick"],
            "at": _instant(opened["opened_at"]),
            "state_sha256": opened["start_state_sha256"],
            "limits": dict(opened["limits"]),
        },
        "closed": None
        if closed is None
        else {
            "tick": closed["end_tick"],
            "at": _instant(closed["closed_at"]),
            "state_sha256": closed["end_state_sha256"],
            "reason": closed["reason"],
            "by": "person" if closed["reason"] in _PERSON_STOPS else "system",
        },
        "spending": {
            "used": {
                "wall_seconds": used["wall_seconds"],
                "minutes": used["minutes"],
                "decisions": used["decisions"],
                "usd": used["usd"],
                "calls": used["calls"],
                "unresolved_count": used["unresolved"]["count"],
                "unresolved_usd": used["unresolved"]["usd"],
            },
            "bounds": [
                {
                    "provider": bound["provider"],
                    "state": bound["state"],
                    "ceiling_usd": bound["ceiling_usd"],
                    "committed_usd": bound["committed_usd"],
                    "committed_calls": bound["committed_calls"],
                    "known_usage_usd": bound["known_usage_usd"],
                    "unresolved_count": bound["unresolved"]["count"],
                    "unresolved_usd": bound["unresolved"]["usd"],
                    "reconciled_usd": bound["reconciled_usd"],
                }
                for bound in session["bounds"]
            ],
        },
    }


def capture(
    reader: WorldReader,
    *,
    version_id: str,
    project_id: str,
    thing_ids: Sequence[str] | None,
    include_models: bool = True,
    include_decisions: bool = True,
    readable: bool = False,
    max_decisions: int = 256,
    licence: str = "unreviewed",
    session_id: str | None = None,
    living_session: str | None = None,
    revisions: Mapping[tuple[str, str, str], str] | None = None,
    parts_known: Mapping[str, Any] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] | None = None,
) -> Capture:
    """Read one version and build the explicitly selected checkpoint and its dependency bytes.

    Only placed things named in `thing_ids` are read into the selection, or, with None, every
    placed thing a checkpoint can hold (none at all is `NothingSelectable`, unless the world was
    made from a world kind and its made parts are kept alone), with their current
    model assignment and the model decisions the society consumed for them. Readable decision
    text is added only when `readable` is set. Shipped kind bytes stay in the installed catalog.
    With `session_id`, decisions go into that session's evidence file instead of the
    checkpoint, which then holds the world and its model assignments only.

    A model assignment's revision is the model the provider served its latest read record; a
    capture that reads no record for it takes the one `revisions` names for that thing, provider
    and model (what the project holds for it), so reading no record never changes it. A session's
    evidence keeps the decisions asked under an earlier model too, each under a binding to the
    model it was asked under; a checkpoint keeps only those of the model chosen now.

    With readable text the checkpoint also keeps the version's title and what the world's owner
    wrote for each selected being (its name and the words about it); without it, only each such
    record's revision, so a change is still seen. Those come from one read of the version's
    character records, or, from an API without it, from each being's card where the version has
    a society. It keeps each made creature's kind's label too, from the kind bytes kept for it.

    A town's own people, who are no placed things, are kept as residents where the project
    follows every thing and a model decides for them or their decisions are kept: each by its
    subject in the society, which its model assignment and decisions name as a thing's are named
    by its placed id, with its role's key, and its name only with readable text. Whoever a choice
    names that no placed thing is, the society is read once to find. A project of chosen things
    keeps those things alone.

    A world made from a world kind also has its made parts kept, as the version has them
    (moved, turned or removed by a person); `parts_known` is what the project holds for them and
    the version state it holds them for, so they are read again only when the version changed.
    """
    note = progress or (lambda _: None)
    version = segment(version_id)
    session = None if living_session is None else read_session(reader, version, living_session)
    coverage = "consumed"
    window: tuple[int, int | None] = (0, None)
    if session is not None:
        closed = session["closed"]
        window = (session["opened"]["start_tick"], None if closed is None else closed["end_tick"])
        session_id = session_id or f"session:{session['session_id']}"
    view = reader.json("GET version", f"/world/versions/{version}")
    if view.get("world_id") != reader.world_id or view.get("version_id") != version_id:
        raise ProjectError("world API returned another world or version")
    if view.get("source_invalidated"):
        raise ProjectError("an invalidated source cannot supply a project checkpoint")
    entries = reader.json("GET world entries", "/world-entries")
    snapshot = next(
        (
            entry["source_snapshot_sha256"]
            for entry in entries
            if entry.get("world_id") == reader.world_id
            and entry.get("source_snapshot_id") == view["source_snapshot_id"]
        ),
        None,
    )
    if not isinstance(snapshot, str) or _DIGEST.fullmatch(snapshot) is None:
        raise ProjectError("the source snapshot digest is served only for a saved world entry")

    placed = {thing["thing_id"]: thing for thing in view["things"]}
    unheld = 0
    if thing_ids is None:
        # Every placed thing a checkpoint can hold; the others are counted, not failed on.
        wanted = sorted(
            thing_id
            for thing_id, thing in placed.items()
            if not thing.get("gone") and "support" not in thing
        )
        unheld = len(placed) - len(wanted)
    else:
        wanted = sorted(set(thing_ids))
        if not wanted or not set(wanted) <= placed.keys():
            raise ProjectError("select at least one thing, all present in the version")
    things = []
    for thing_id in wanted:
        thing = dict(placed[thing_id])
        if thing.pop("gone", False) or "support" in thing:
            raise ProjectError("unavailable kinds and support-bound placements are unsupported")
        thing.pop("profile", None)
        things.append(thing)

    dependencies: dict[str, bytes] = {}
    declared: list[dict[str, str]] = [
        {
            "kind": "source-snapshot",
            "sha256": snapshot,
            "licence": licence,
            "source_id": f"snapshot:{view['source_snapshot_id']}",
        }
    ]

    def declare(kind: str, data: bytes | None, sha: str, source: str) -> None:
        if all(d["sha256"] != sha for d in declared):
            declared.append({"kind": kind, "sha256": sha, "licence": licence, "source_id": source})
        if data is not None:
            dependencies[sha] = data

    for thing in things:
        sha = thing["kind"]["sha256"]
        if thing["kind"].get("source") == "workspace":
            data = reader.raw("GET thing kind", f"/things/kinds/{segment(sha)}")
            if digest(data) != sha:
                raise ProjectError("world API returned kind bytes that do not match their digest")
            declare("thing-kind", data, sha, f"workspace-kind:{sha[:16]}")
            # A made creature is called by its kind's label, its maker's words: kept with
            # readable text alone, from the bytes just read (no other request).
            label = _kind_label(data) if readable else None
            if label is not None:
                thing["label"] = label
        else:
            declare("thing-kind", None, sha, f"kind:{thing['kind']['kind']}")

    subjects = {subject_id(reader.world_id, t["thing_id"]): t["thing_id"] for t in things}
    # A model is assigned only to a thing still in the world: a removed one keeps no assignment,
    # whatever choice the society still lists for it.
    standing = {s for s, thing_id in subjects.items() if not placed[thing_id].get("removed")}
    models: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    # Every binding a decision of this capture is held under, by its digest.
    bindings_used: dict[str, dict[str, Any]] = {}
    residents: dict[str, dict[str, Any]] = {}
    trajectory_inputs: list[dict[str, Any]] = []
    if include_models:
        society = reader.json("GET society models", f"/world/versions/{version}/society/models")
        contract = {
            "catalog_versions": society["contract"]["catalog_versions"],
            "sha256": society["contract"]["sha256"],
        }
        role = decision_roles().for_contract(contract)
        # A town's own people are no placed things: whoever a choice names that no thing placed in
        # the version is, the society is asked about, and its residents are held as themselves,
        # by their subject, as a selected thing is held by its placed id. A project of chosen
        # things keeps those alone.
        placed_subjects = {subject_id(reader.world_id, thing_id) for thing_id in placed}
        others = {
            choice["subject_id"]
            for choice in society.get("choices", [])
            if isinstance(choice.get("subject_id"), str)
            and _NAME.fullmatch(choice["subject_id"])
            and choice["subject_id"] not in placed_subjects
        }
        if others and thing_ids is None:
            residents = _residents(reader, version, others, readable)
            subjects.update({subject: subject for subject in residents})
            standing |= set(residents)
        latest: dict[str, dict[str, Any]] = {}
        for choice in society.get("choices", []):
            decider = choice.get("decider") or {}
            if choice.get("subject_id") in standing and decider.get("kind") == "model":
                held = latest.get(choice["subject_id"])
                if held is None or choice["choice_seq"] > held["choice_seq"]:
                    latest[choice["subject_id"]] = choice
        # A session's evidence keeps every model decision of a selected thing, each under the
        # model it was asked under; a checkpoint keeps only those of the model chosen now.
        asking = set(subjects) if session is not None else set(latest)
        events = _events(reader, version, asking) if include_decisions and asking else []
        consumed = {event["document"]["request_id"]: event for event in events}
        # Each entry: (the minute's event or None, the record, the subject it was asked for).
        records: dict[str, tuple[dict[str, Any] | None, dict[str, Any], str]] = {}
        if (
            session is not None
            and session["decisions_read"]["counted"] == session["decisions_read"]["total"]
        ):
            # The session's list holds every decision asked in its minutes (its total), the
            # unanswered ones too. Each record is still read in full below: the list carries no
            # source record digest, options, choice, latency, tokens or cost. Its decider is the
            # word the read serves (model, person or external), not a decider object.
            coverage = "all"
            asked = [
                (entry["request_id"], entry["subject_id"])
                for entry in session["decisions"]
                if entry.get("decider") == "model" and entry["subject_id"] in asking
            ]
        else:
            asked = [(event["document"]["request_id"], event["subject_id"]) for event in events]
        for request_id, subject in asked[-max_decisions:]:
            record = reader.json(
                "GET society decision",
                f"/world/versions/{version}/society/decisions/{segment(request_id)}",
            )
            base_tick = record["request"]["base_tick"]
            if session is not None and not (
                window[0] <= base_tick and (window[1] is None or base_tick < window[1])
            ):
                continue
            records[request_id] = (consumed.get(request_id), record, subject)
        note(f"read {len(records)} decision records")

        def bind(subject: str, provider: Any, model_id: Any) -> dict[str, Any]:
            """The binding of one thing to one model: its revision is the model the provider
            served the latest record asked under it, else what the project holds for it."""
            served = [
                record["decision"]["provider"].get("served_model_id")
                for _, record, asked_for in records.values()
                if asked_for == subject
                and record.get("decision")
                and _asked_under(record) == (provider, model_id)
            ]
            known = (revisions or {}).get((subjects[subject], provider, model_id))
            manifest = {
                "provider": _name(provider),
                "model_id": _name(model_id),
                "revision": _name(served[-1] if served else known),
            }
            manifest_bytes = canonical_json(manifest)
            contract_bytes = canonical_json(contract)
            declare("decision-contract", contract_bytes, digest(contract_bytes), f"role:{role.key}")
            declare(
                "model-manifest",
                manifest_bytes,
                digest(manifest_bytes),
                f"model:{manifest['provider']}",
            )
            return {
                "thing_id": subjects[subject],
                "role": role.key,
                "contract_sha256": digest(contract_bytes),
                "model_manifest_sha256": digest(manifest_bytes),
                **manifest,
            }

        current = {
            subject: bind(
                subject, choice["decider"].get("provider"), choice["decider"].get("model_id")
            )
            for subject, choice in sorted(latest.items())
        }
        models.extend(current.values())
        for event, record, subject in records.values():
            request, receipt = record["request"], record.get("decision")
            choice = latest.get(subject)
            under = _asked_under(record)
            if (
                receipt is not None
                and choice is not None
                and under
                == (
                    choice["decider"].get("provider"),
                    choice["decider"].get("model_id"),
                )
            ):
                binding = current[subject]
            elif receipt is not None and session is not None:
                binding = bind(subject, *under)
            else:
                skipped["asked under another assignment or unanswered"] = (
                    skipped.get("asked under another assignment or unanswered", 0) + 1
                )
                continue
            options = request["context"]["options"]
            labels = [option["label"] for option in options]
            chosen = (receipt.get("proposal") or {}).get("label")
            disposition = None if event is None else event["document"].get("disposition")
            outcome = _OUTCOMES.get(disposition, "not-applied")
            provider = receipt.get("provider") or {}
            decision = {
                "record_id": f"request:{request['request_id']}",
                "thing_id": subjects[subject],
                "tick": request["base_tick"],
                "binding_sha256": sha256_of_canonical(binding).hex(),
                "source_record_sha256": receipt["document_sha256"],
                "observation_sha256": request["context_sha256"],
                "options": [
                    {
                        "option_id": f"option:{index + 1}",
                        "action": _name(option.get("action") or option.get("action_key")),
                        "target_id": option.get("target_id")
                        if isinstance(option.get("target_id"), str)
                        else None,
                    }
                    for index, option in enumerate(options)
                ],
                "chosen_option_id": f"option:{labels.index(chosen) + 1}"
                if chosen in labels
                else None,
                "outcome": outcome,
                "reason_code": _name(
                    receipt.get("reason")
                    if outcome == "applied" or event is None
                    else event["document"].get("reason")
                ),
                "elapsed_ms": _natural(provider.get("latency_ms")),
                "input_tokens": _natural(provider.get("prompt_tokens")),
                "output_tokens": _natural(provider.get("completion_tokens")),
            }
            if outcome == "applied" and decision["chosen_option_id"] is None:
                skipped["applied without a recorded choice"] = (
                    skipped.get("applied without a recorded choice", 0) + 1
                )
                continue
            decision["receipt"] = _receipt(receipt, event)
            # A request no minute took up has no consumed minute or disposition to read.
            if readable and event is not None:
                decision["readable"] = _readable(request, receipt, event)
            decisions.append(decision)
            bindings_used[decision["binding_sha256"]] = binding
            trajectory_inputs.append(
                {
                    "world_id": reader.world_id,
                    "version_id": version_id,
                    "request": request,
                    "decision": receipt,
                    "event": event,
                    "status": receipt["status"],
                    "disposition": disposition or (
                        "applied" if receipt["status"] == "accepted" else receipt["status"]
                    ),
                    "reason": decision["reason_code"],
                    "branches": list(record.get("branches") or record.get("asks") or ()),
                }
            )

    # A resident is kept where a model decides for them or a decision of theirs is kept.
    decided = {model["thing_id"] for model in models} | {d["thing_id"] for d in decisions}
    kept = [residents[subject] for subject in sorted(residents) if subject in decided]
    characters = _characters(reader, version, things, readable, cards=include_models)
    parts = _parts(reader, version, view["state_sha256"], readable, parts_known)
    if not things and not parts and not kept:
        raise NothingSelectable(
            "this version holds no placed thing, no made part and no resident a model decides "
            "for that a project can hold yet"
        )
    source = {
        "world_id": reader.world_id,
        "version_id": version_id,
        "snapshot_id": view["source_snapshot_id"],
        "state_sha256": view["state_sha256"],
        "snapshot_sha256": snapshot,
    }
    evidence = None
    if session_id is not None and decisions:
        evidence = evidence_document(
            {
                "profile": "exulanica.world-project-evidence/v1",
                "project_id": project_id,
                "session_id": session_id,
                "source": source,
                # The models chosen now, and each earlier one a decision here was asked under.
                "models": [
                    *models,
                    *(binding for binding in bindings_used.values() if binding not in models),
                ],
                "decisions": decisions,
                # Only decisions a minute took up are enumerated (decision_applied events): a
                # request that never got a usable answer and was never consumed is absent.
                "coverage": {"decisions": coverage},
                "captured_at": now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "living_session": None if session is None else living_session_block(session),
            }
        )
        decisions = []
    checkpoint = document(
        {
            "profile": "exulanica.world-project/v1",
            "project_id": project_id,
            "source": source,
            "forked_from": None,
            "region_ids": sorted({thing["region_id"] for thing in things}),
            "things": things,
            "dependencies": declared,
            "models": models,
            "decisions": decisions,
            **({"title": title} if (title := _title(view, readable)) is not None else {}),
            **({"characters": characters} if characters else {}),
            **({"parts": parts} if parts is not None else {}),
            **({"residents": kept} if kept else {}),
        }
    )
    trajectories = (
        export_trajectories(
            trajectory_inputs,
            world_id=reader.world_id,
            version_id=version_id,
        ).to_dict()
        if trajectory_inputs
        else None
    )
    return Capture(
        checkpoint,
        dependencies,
        {
            "things": len(things),
            "things_not_held": unheld,
            "residents": len(kept),
            "models": len(models),
            "decisions": len(evidence["decisions"]) if evidence else len(decisions),
            "decisions_in": "evidence" if evidence else "checkpoint",
            "skipped_decisions": skipped,
            "only_consumed_decisions": True,
            "readable": readable,
            "state_digest_verified": False,
            "source_records_verified": False,
            "world_writes": 0,
        },
        evidence,
        trajectories,
    )
