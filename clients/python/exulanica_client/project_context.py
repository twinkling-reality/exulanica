"""``python -m exulanica_client.project_context``: keep a world project, then resume it elsewhere.

Standard library only, like the rest of this client. Two commands, meant to run as two separate
processes that share nothing but the server and a small note of ids:

* ``record`` starts a project on a saved world, keeps a goal, an open question and a decision that
  names the newest accepted edit of the world's version, and writes the ids to ``--note``.
* ``resume`` reads the note and opens the project as any client would: it checks the decision still
  names the same edit, by id and result digest, and that the version's own history agrees; corrects
  the goal; deletes the question; assembles the bounded context; and checks the deleted words are
  in no read that follows.

Exit 0 when every check holds, 3 when one does not or the server refuses, 2 on a usage error. The
token is read from an environment variable and never written; ``--transcript`` keeps every
exchange without it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .client import ApiRefusal, ClientError, Exchange, WorldClient

__all__ = ["main", "record", "resume"]

_EXIT_CONFIRMED = 0
_EXIT_USAGE = 2
_EXIT_STOPPED = 3
#: The route that records an edit when a reviewed object is applied through a composition.
_APPLY = "POST /world/versions/{version_id}/compositions/apply"


def _projects(world_id: str) -> dict[str, str]:
    return {"world_id": world_id}


def _ok(
    client: WorldClient,
    method: str,
    path: str,
    *,
    world_id: str,
    body: object = None,
    expected: Sequence[int] = (200, 201),
) -> Any:
    status, answer = client.request(method, path, query=_projects(world_id), body=body)
    if status not in expected:
        raise ApiRefusal(method, path, status, answer)
    return answer


def record(
    client: WorldClient, *, entry_id: str, question: str, operation: str = _APPLY
) -> dict[str, Any]:
    """Start a project on a saved world and keep three items; return the note ``resume`` reads."""
    saved = client.saved_world(entry_id)
    world_id, version_id = saved["world_id"], saved["authored_version_id"]
    version = client.version(version_id, world_id=world_id)
    if not version["edits"]:
        raise ClientError("the saved world has no accepted edit for a decision to name")
    edit = max(version["edits"], key=lambda e: e["edit_seq"])
    reference = {
        "kind": "world_edit",
        "operation": operation,
        "world_id": world_id,
        "version_id": version_id,
        "edit_id": edit["edit_id"],
        "edit_seq": edit["edit_seq"],
        "result_state_sha256": edit["result_state_sha256"],
    }
    project = _ok(
        client,
        "POST",
        "/world/projects",
        world_id=world_id,
        body={
            "title": "Resumed elsewhere",
            "version_id": version_id,
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    items: dict[str, str] = {}
    revision = project["revision"]
    for name, body in (
        ("goal", {"kind": "goal", "basis": "user_statement", "text": "People rest here"}),
        ("question", {"kind": "question", "basis": "user_statement", "text": question}),
        (
            "decision",
            {
                "kind": "decision",
                "basis": "recorded_outcome",
                "text": "Kept the newest edit",
                "references": [reference],
            },
        ),
    ):
        made = _ok(
            client,
            "POST",
            f"/world/projects/{project['project_id']}/items",
            world_id=world_id,
            body={"base_revision": revision, "idempotency_key": str(uuid.uuid4()), **body},
        )
        items[name] = made["item_id"]
        revision = made["project_revision"]
    return {
        "world_id": world_id,
        "project_id": project["project_id"],
        "items": items,
        "reference": reference,
        "question": question,
    }


def resume(client: WorldClient, note: dict[str, Any]) -> list[dict[str, Any]]:
    """Open the project from its note alone and check it; every check says whether it holds."""
    world_id, project_id = note["world_id"], note["project_id"]
    base = f"/world/projects/{project_id}"
    checks: list[dict[str, Any]] = []

    def check(name: str, holds: bool) -> None:
        checks.append({"check": name, "holds": bool(holds)})

    project = _ok(client, "GET", base, world_id=world_id, expected=(200,))
    check("the project's version is available", project["binding"]["state"] == "available")
    items = _ok(client, "GET", f"{base}/items", world_id=world_id, expected=(200,))
    decision = next((i for i in items if i["item_id"] == note["items"]["decision"]), None)
    kept = None if decision is None else decision["references"][0]
    check(
        "the decision names the same edit",
        kept is not None and kept["reference"] == note["reference"],
    )
    check(
        "the edit's authority reads it available", kept is not None and kept["state"] == "available"
    )
    reference = note["reference"]
    version = client.version(reference["version_id"], world_id=world_id)
    edit = next((e for e in version["edits"] if e["edit_id"] == reference["edit_id"]), None)
    check(
        "the version's own history holds the edit and its result",
        edit is not None and edit["result_state_sha256"] == reference["result_state_sha256"],
    )

    corrected = _ok(
        client,
        "POST",
        f"{base}/items/{note['items']['goal']}/corrections",
        world_id=world_id,
        body={
            "base_revision": project["revision"],
            "text": "People rest in the shade",
            "note": "shade matters",
        },
    )
    check("the correction is the goal's second revision", corrected["revision"] == 2)
    status, _answer = client.request(
        "DELETE", f"{base}/items/{note['items']['question']}", query=_projects(world_id)
    )
    check("the question is deleted", status == 200)
    context = _ok(client, "GET", f"{base}/context", world_id=world_id, expected=(200,))
    texts = [entry["text"] for entry in context["entries"]]
    check("the context holds the corrected goal", "People rest in the shade" in texts)
    reads = [
        json.dumps(context),
        json.dumps(_ok(client, "GET", f"{base}/items", world_id=world_id, expected=(200,))),
        json.dumps(_ok(client, "GET", base, world_id=world_id, expected=(200,))),
    ]
    check("the deleted question is in no read", all(note["question"] not in r for r in reads))
    status, _answer = client.request(
        "GET", f"{base}/items/{note['items']['question']}/history", query=_projects(world_id)
    )
    check("the deleted question has no history to read", status == 404)
    return checks


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m exulanica_client.project_context")
    parser.add_argument("command", choices=("record", "resume"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--note", type=Path, required=True)
    parser.add_argument("--entry-id", help="the saved world to start the project on (record)")
    parser.add_argument("--question", default="Will anyone sit there?")
    parser.add_argument("--token-env", default="EXULANICA_TOKEN")
    parser.add_argument("--transcript", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    token = os.environ.get(args.token_env, "")
    if not token or (args.command == "record" and not args.entry_id):
        print(f"set {args.token_env}, and give --entry-id to record", file=sys.stderr)
        return _EXIT_USAGE
    exchanges: list[dict[str, Any]] = []

    def keep(exchange: Exchange) -> None:
        exchanges.append(
            {
                "method": exchange.method,
                "path": exchange.path,
                "query": dict(exchange.query),
                "status": exchange.status,
                "request_body": exchange.request_body,
                "response_body": exchange.response_body,
            }
        )

    result: dict[str, Any] = {"command": args.command}
    try:
        client = WorldClient(args.base_url, token, on_exchange=keep)
        if args.command == "record":
            note = record(client, entry_id=args.entry_id, question=args.question)
            args.note.write_text(json.dumps(note, indent=2, sort_keys=True) + "\n")
            result["result"] = "recorded"
            code = _EXIT_CONFIRMED
        else:
            checks = resume(client, json.loads(args.note.read_text()))
            result["checks"] = checks
            failed = [c["check"] for c in checks if not c["holds"]]
            for c in checks:
                print(f"  {'holds' if c['holds'] else 'FAILS'}: {c['check']}")
            result["result"] = "confirmed" if not failed else "not confirmed"
            code = _EXIT_CONFIRMED if not failed else _EXIT_STOPPED
    except (ApiRefusal, ClientError) as stopped:
        print(f"stopped: {stopped}", file=sys.stderr)
        result.update({"result": "stopped", "reason": str(stopped)})
        code = _EXIT_STOPPED
    result["exchanges"] = exchanges
    if args.transcript is not None:
        args.transcript.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"result: {result['result']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
