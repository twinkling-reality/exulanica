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
from exulanica.world.society_decision_contract import situation
from exulanica.world.society_things import THING_NAMESPACE
from exulanica.world_package.projects.checkpoint import (
    ProjectError,
    digest,
    document,
    evidence_document,
)

_SEGMENT = re.compile(r"^[A-Za-z0-9:._-]{1,200}$")
_NAME = re.compile(r"^[a-zA-Z0-9:._/-]{1,200}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OUTCOMES = {"applied": "applied", "rejected": "refused"}
_MAX_EVENT_PAGES = 64


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

    def _get(self, route: str, path: str, params: dict[str, Any]) -> httpx.Response:
        try:
            response = self._client.get(path, params=params)
        except (httpx.HTTPError, EgressError) as exc:
            raise ProjectError(f"world API read {route} did not complete") from exc
        if response.status_code != 200:
            # Neither the body nor the request line is echoed: either may carry selected values.
            raise ProjectError(f"world API refused {route} with status {response.status_code}")
        return response

    def json(self, route: str, path: str, **params: Any) -> Any:
        response = self._get(route, path, {"world_id": self.world_id, **params})
        try:
            return response.json()
        except ValueError as exc:
            raise ProjectError(f"world API returned malformed JSON for {route}") from exc

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


def read_session(reader: WorldReader, version: str, which: str) -> dict[str, Any]:
    """One living session as the society read serves it: by id, or the newest for "latest"."""
    base = f"/world/versions/{version}/society/control/sessions"
    if which == "latest":
        listed = reader.json("GET living sessions", base)["sessions"]
        if not listed:
            raise ProjectError("this world has no living session")
        which = listed[0]["session_id"]
    return reader.json("GET living session", f"{base}/{segment(which)}")


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
    thing_ids: Sequence[str],
    include_models: bool = True,
    include_decisions: bool = True,
    readable: bool = False,
    max_decisions: int = 256,
    licence: str = "unreviewed",
    session_id: str | None = None,
    living_session: str | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] | None = None,
) -> Capture:
    """Read one version and build the explicitly selected checkpoint and its dependency bytes.

    Only placed things named in `thing_ids` are read into the selection, with their current model
    assignment and the model decisions the society consumed for them. Readable decision text is
    added only when `readable` is set. Shipped kind bytes stay in the installed catalog.
    With `session_id`, decisions go into that session's evidence file instead of the
    checkpoint, which then holds the world and its model assignments only.
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
        else:
            declare("thing-kind", None, sha, f"kind:{thing['kind']['kind']}")

    subjects = {subject_id(reader.world_id, t["thing_id"]): t["thing_id"] for t in things}
    models: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    if include_models:
        society = reader.json("GET society models", f"/world/versions/{version}/society/models")
        contract = {
            "catalog_versions": society["contract"]["catalog_versions"],
            "sha256": society["contract"]["sha256"],
        }
        role = decision_roles().for_contract(contract)
        latest: dict[str, dict[str, Any]] = {}
        for choice in society.get("choices", []):
            decider = choice.get("decider") or {}
            if choice.get("subject_id") in subjects and decider.get("kind") == "model":
                held = latest.get(choice["subject_id"])
                if held is None or choice["choice_seq"] > held["choice_seq"]:
                    latest[choice["subject_id"]] = choice
        events = _events(reader, version, set(latest)) if include_decisions and latest else []
        consumed = {event["document"]["request_id"]: event for event in events}
        # Each entry: (the minute's event or None, the record, the subject it was asked for).
        records: dict[str, tuple[dict[str, Any] | None, dict[str, Any], str]] = {}
        if (
            session is not None
            and session["decisions_read"]["counted"] == session["decisions_read"]["total"]
        ):
            # The session's list holds every decision asked in its minutes (its total), the
            # unanswered ones too. Each record is still read in full below: the list carries no
            # source record digest, options, choice, latency, tokens or cost.
            coverage = "all"
            asked = [
                (entry["request_id"], entry["subject_id"])
                for entry in session["decisions"]
                if (entry.get("decider") or {}).get("kind") == "model"
                and entry["subject_id"] in latest
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
        for subject, choice in sorted(latest.items()):
            decider = choice["decider"]
            served = [
                record["decision"]["provider"].get("served_model_id")
                for _, record, asked_for in records.values()
                if asked_for == subject and record.get("decision")
            ]
            manifest = {
                "provider": _name(decider.get("provider")),
                "model_id": _name(decider.get("model_id")),
                "revision": _name(served[-1] if served else None),
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
            binding = {
                "thing_id": subjects[subject],
                "role": role.key,
                "contract_sha256": digest(contract_bytes),
                "model_manifest_sha256": digest(manifest_bytes),
                **manifest,
            }
            models.append(binding)
            binding_sha256 = sha256_of_canonical(binding).hex()
            for event, record, asked_for in records.values():
                if asked_for != subject:
                    continue
                request, receipt = record["request"], record.get("decision")
                config = request.get("provider_config") or {}
                if receipt is None or (config.get("provider"), config.get("model_id")) != (
                    decider.get("provider"),
                    decider.get("model_id"),
                ):
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
                    "binding_sha256": binding_sha256,
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
                "models": models,
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
        }
    )
    return Capture(
        checkpoint,
        dependencies,
        {
            "things": len(things),
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
    )
