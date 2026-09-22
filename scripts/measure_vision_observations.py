"""Send synthetic photographs through the product routes and score what the vision pass said.

    python scripts/measure_vision_observations.py --state STATE.json --photos DIR \
        --out OUT.json [--label NAME] [--limit N]

Writes through product routes only: ``POST /intake`` and then ``POST /personal-admission``,
which records the detection permission and the model right that the vision stage requires. The
exact bytes the model returned are read back from the artifact the stage stored, because that
artifact is the record of what the model actually said and no route serves it.

Scoring compares boxes, not words. ``scripts/make_place_photographs.py`` drew every object and
recorded where, so an omission and an unsupported observation are countable rather than judged.
A detector's vocabulary and a scene recipe's vocabulary disagree even when both are right about
where a thing is, so a word-matched score would measure the vocabulary.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

#: A reported box counts as the same thing as a drawn box at or above this overlap. Fixed here,
#: before any candidate was compared, because a threshold chosen after seeing the outputs is a
#: threshold chosen to produce a result.
IOU_THRESHOLD = 0.3

#: How long to wait for the queue to drain, in seconds.
DEADLINE = 600


def iou(a: dict[str, float], b: dict[str, float]) -> float:
    ax0, ay0, ax1, ay1 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    overlap = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - overlap
    return 0.0 if union <= 0 else overlap / union


class Runtime:
    """The acceptance runtime, addressed the way a client addresses it."""

    def __init__(self, state_path: Path) -> None:
        state = json.loads(state_path.read_text())
        self.base = f"http://127.0.0.1:{state['ports']['api']}"
        self.token = Path(state["token_file"]).read_text().strip()
        self.workspace = uuid.UUID(state["workspace_id"])
        self.data_dir = Path(state["data_dir"])
        self.owner_url = state["database"]["owner_url_for_evidence_reads"]

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw or b"null")
            except json.JSONDecodeError:
                return error.code, raw.decode("utf-8", "replace")

    def upload(self, photograph: Path) -> tuple[int, Any]:
        boundary = f"----exulanica{uuid.uuid4().hex}"
        body = b"".join((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="files"; filename="{photograph.name}"\r\n'
            .encode(),
            b"Content-Type: image/jpeg\r\n\r\n",
            photograph.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ))
        request = urllib.request.Request(f"{self.base}/intake", data=body, method="POST")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")

    def await_job(self, job_id: str) -> dict[str, Any]:
        end = time.monotonic() + DEADLINE
        while time.monotonic() < end:
            status, events = self.call("GET", f"/operations/derivative-jobs/{job_id}/events")
            if status == 200 and events:
                last = events[-1]
                if last["event_type"] in ("job_succeeded", "job_failed", "job_abandoned"):
                    return last
            time.sleep(3)
        raise SystemExit(f"job {job_id} did not reach a terminal event within {DEADLINE}s")

    def vision_artifacts(self, captures: list[str]) -> dict[str, dict[str, Any]]:
        """The exact stored bytes of each capture's vision observation."""
        import psycopg
        from psycopg.rows import dict_row

        found: dict[str, dict[str, Any]] = {}
        with psycopg.connect(self.owner_url, row_factory=dict_row) as connection:
            connection.execute("select set_config('exulanica.workspace_id',%s,false)",
                               (str(self.workspace),))
            rows = connection.execute(
                "select a.storage_key, c.capture_id from artifact a "
                "join capture c on c.workspace_id=a.workspace_id "
                "and c.blob_sha256=a.source_blob_sha256 "
                "where a.workspace_id=%s and a.kind='vision_observation' "
                "and a.superseded_by is null and c.capture_id = any(%s::uuid[])",
                (self.workspace, captures),
            ).fetchall()
        for row in rows:
            blob = self.data_dir / "blobs" / row["storage_key"]
            found[str(row["capture_id"])] = json.loads(blob.read_bytes())
        return found


def score(truth: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """Count omissions and unsupported observations against what was drawn."""
    observation = document["observation"]
    reported = observation["objects"]
    drawn = truth["objects"]

    def best(item: dict[str, Any]) -> float:
        return max(
            (iou(item["box"], other["box"]) for other in reported if other.get("box")),
            default=0.0,
        )

    def matched(tier: str) -> tuple[int, int, list[str], list[dict[str, Any]]]:
        wanted = [item for item in drawn if item["tier"] == tier]
        overlaps = [{"what": item["what"], "best_iou": round(best(item), 3)} for item in wanted]
        missing = [item["what"] for item in wanted if best(item) < IOU_THRESHOLD]
        return len(wanted), len(wanted) - len(missing), missing, overlaps

    salient_total, salient_found, salient_missing, salient_overlaps = matched("salient")
    detail_total, detail_found, detail_missing, _ = matched("detail")

    unsupported = [
        item["label"] for item in reported
        if not item.get("box")
        or not any(iou(item["box"], other["box"]) >= IOU_THRESHOLD for other in drawn)
    ]

    texts = " | ".join(entry["text"].upper() for entry in observation["legible_text"])
    sign = truth["sign_text"]
    place = observation["proposed_place"]
    return {
        "file": truth["file"],
        "notice_kind": truth["notice_kind"],
        "sign_drawn": sign,
        "salient": {"drawn": salient_total, "reported": salient_found, "missing": salient_missing,
                    # Threshold-free, reported beside the count because one cut cannot tell
                    # "never seen" from "seen and loosely located", and the count alone reads
                    # as the first when the data may say the second.
                    "best_iou_per_drawn_object": salient_overlaps},
        "detail": {"drawn": detail_total, "reported": detail_found, "missing": detail_missing},
        "reported_objects": len(reported),
        "unsupported_objects": unsupported,
        "sign_text_transcribed": None if sign is None else (sign.upper() in texts),
        "notice_transcribed": truth["notice_text"].upper() in texts,
        "people_drawn": truth["people_drawn"],
        "people_reported": len(observation["people"]),
        "place_proposed": place,
        "place_should_be_available": truth["place_name_is_visible"],
        "place_label_matches_sign": (
            None if place is None or sign is None
            else sign.upper() in place["label"].upper() or place["label"].upper() in sign.upper()
        ),
        "usage": document["header"]["usage"],
        "model_id": document["header"]["model_ref"]["model_id"],
        "models_tried": document["header"]["models_tried"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--photos", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="run")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--valid-until", default="2026-09-23T00:00:00Z")
    arguments = parser.parse_args()

    runtime = Runtime(Path(arguments.state))
    photos = Path(arguments.photos)
    truths = {
        entry["file"]: entry
        for path in photos.glob("ground-truth-*.json")
        for entry in json.loads(path.read_text())
    }
    names = sorted(truths)
    if arguments.limit:
        names = names[: arguments.limit]

    members, captures, uploads = [], [], []
    for name in names:
        status, body = runtime.upload(photos / name)
        uploads.append({"file": name, "status": status})
        if status != 202 or not body["accepted"]:
            raise SystemExit(f"{name} was not accepted: {status} {body}")
        part = body["accepted"][0]
        captures.append(part["capture_id"])
        members.append({
            "capture_id": part["capture_id"],
            "sha256": part["blob_sha256"],
            "bytes": (photos / name).stat().st_size,
            "review": "not-reviewed",
            "edits": [],
        })

    status, admission = runtime.call("POST", "/personal-admission", {
        "members": members,
        "purpose": f"Lane M vision measurement: {arguments.label}",
        "authority": {
            "account_authority_basis": (
                "synthetic images drawn by scripts/make_place_photographs.py in this repository; "
                "no personal photograph is involved"
            ),
            "authorized_at": "2026-09-22T00:00:00Z",
            "valid_until": arguments.valid_until,
        },
        "recorded_at": "2026-09-22T16:00:00Z",
        "operation": "detect",
        "model_rights": [
            {"role": "vision", "valid_until": arguments.valid_until},
            {"role": "embedding", "valid_until": arguments.valid_until},
        ],
    })
    if status != 202:
        raise SystemExit(f"admission refused: {status} {admission}")

    terminal = runtime.await_job(admission["queued_job_id"])
    documents = runtime.vision_artifacts(captures)
    scored = [
        score(truths[name], documents[capture])
        for name, capture in zip(names, captures, strict=True)
        if capture in documents
    ]

    record = {
        "label": arguments.label,
        "photographs": len(names),
        # Recorded so a later arm can address the same rows by id rather than by re-deriving
        # them from the file name, which a re-uploaded duplicate would pair wrongly.
        "capture_ids": captures,
        "files": names,
        "uploads": uploads,
        "captures_with_a_vision_artifact": len(scored),
        "terminal_event": {
            "event_type": terminal["event_type"],
            "cost": terminal.get("cost"),
            "duration_ms": terminal.get("duration_ms"),
            "failure_class": terminal.get("failure_class"),
            "message": terminal.get("message"),
        },
        "model_rights_recorded": [
            right["model"] for receipt in admission["receipts"]
            for right in receipt["model_rights"]
        ][:8],
        "iou_threshold": IOU_THRESHOLD,
        "per_photograph": scored,
    }
    Path(arguments.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "label": arguments.label,
        "scored": len(scored),
        "terminal": terminal["event_type"],
        "cost": terminal.get("cost"),
        "places_proposed": sum(1 for s in scored if s["place_proposed"] is not None),
        "out": arguments.out,
    }, indent=2))


if __name__ == "__main__":
    main()
