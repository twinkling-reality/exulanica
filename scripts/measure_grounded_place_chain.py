"""Drive one grounded Companion answer about a place end to end, through product routes only.

    python scripts/measure_grounded_place_chain.py --state STATE.json --photos DIR \
        --place FILE --control FILE --walker CONTENT_PREREQUISITES.py --out OUT.json

The chain, in order, each step an HTTP request with the runtime's synthetic token:

1.  ``POST /intake``: a photograph carrying a legible place name, and a control carrying no text.
2.  ``POST /personal-admission``: detection permission and a model right for the vision and
    embedding roles, which is what lets the vision stage send the bytes at all.
3.  The derivative job: the vision pass proposes a place, which writes a place-class occurrence.
    The exact stored observation for each photograph is read back, because no route serves it.
4.  ``POST /identity/name`` on that occurrence: the review decision that makes a place-class
    memory entity. Made here by this driver acting as the synthetic account holder, never by a
    person, and recorded as such.
5.  The admitted place, through the environment routes, by lane D's walker, which also confirms
    ``POST /selection/place-bridges`` from the admitted place to the memory place entity.
6.  ``POST /selection/ask`` with that city selection: the deterministic CONTENT answer, now with a
    bridge behind it.
7.  ``POST /selection/ask`` with a question in words: the planner and the composer, which are the
    only two places a model takes part in answering.

Every model call the answer path reports is kept with its latency, tokens and cost. The vision and
embedding calls are read from the stored artifacts and job events. Nothing is written except
through a product route.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_vision_observations import Runtime


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--photos", required=True)
    parser.add_argument("--place", required=True, help="the photograph carrying a place name")
    parser.add_argument("--control", required=True, help="a photograph carrying no text")
    parser.add_argument("--walker", required=True, help="lane D's content_prerequisites.py")
    parser.add_argument("--question", default=None)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()

    runtime = Runtime(Path(arguments.state))
    photos = Path(arguments.photos)
    steps: list[dict[str, Any]] = []

    def step(name: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        started = time.monotonic()
        status, response = runtime.call(method, path, body)
        steps.append({"step": name, "request": f"{method} {path}", "body": body,
                      "status": status, "wall_ms": round((time.monotonic() - started) * 1000),
                      "response": response})
        print(f"{status}  {round((time.monotonic() - started) * 1000):>6} ms  {name}")
        return status, response

    # 1. Intake.
    captures: dict[str, dict[str, Any]] = {}
    for role, name in (("place", arguments.place), ("control", arguments.control)):
        started = time.monotonic()
        status, body = runtime.upload(photos / name)
        steps.append({"step": f"upload the {role} photograph", "request": "POST /intake",
                      "status": status, "wall_ms": round((time.monotonic() - started) * 1000),
                      "response": body})
        print(f"{status}  upload {role} {name}")
        if status != 202 or not body["accepted"]:
            raise SystemExit(f"{name} was not accepted: {status} {body}")
        captures[role] = {**body["accepted"][0], "file": name,
                          "bytes": (photos / name).stat().st_size}

    # 2. Detection permission and model rights.
    status, admission = step("record detection permission and model rights", "POST",
                             "/personal-admission", {
        "members": [{"capture_id": c["capture_id"], "sha256": c["blob_sha256"],
                     "bytes": c["bytes"], "review": "not-reviewed", "edits": []}
                    for c in captures.values()],
        "purpose": "Lane M: one grounded Companion answer about a place, end to end, on "
                   "synthetic photographs",
        "authority": {"account_authority_basis": "synthetic images drawn by "
                      "scripts/make_place_signage_photographs.py; no personal photograph",
                      "authorized_at": "2026-09-22T00:00:00Z",
                      "valid_until": "2026-09-23T12:00:00Z"},
        "recorded_at": "2026-09-22T18:00:00Z",
        "operation": "detect",
        "model_rights": [{"role": "vision", "valid_until": "2026-09-23T12:00:00Z"},
                         {"role": "embedding", "valid_until": "2026-09-23T12:00:00Z"}],
    })
    if status != 202:
        raise SystemExit(f"admission refused: {status} {admission}")

    # 3. The derivative job, and exactly what the vision pass returned.
    started = time.monotonic()
    terminal = runtime.await_job(admission["queued_job_id"])
    job_ms = round((time.monotonic() - started) * 1000)
    _, events = runtime.call("GET",
                             f"/operations/derivative-jobs/{admission['queued_job_id']}/events")
    steps.append({"step": "derivative job to a terminal event", "wall_ms": job_ms,
                  "terminal": terminal, "events": events})
    print(f"job {terminal['event_type']} in {job_ms} ms")
    if terminal["event_type"] != "job_succeeded":
        raise SystemExit(f"derivative job did not succeed: {terminal}")
    observations = runtime.vision_artifacts([c["capture_id"] for c in captures.values()])

    _, graph = step("read the graph", "GET", "/graph")
    by_capture: dict[str, list[dict[str, Any]]] = {}
    for occurrence in graph["occurrences"]:
        by_capture.setdefault(occurrence["capture_id"], []).append(occurrence)
    place_occurrences = [o for o in by_capture.get(captures["place"]["capture_id"], [])
                         if o["occurrence_class"] == "place"]
    control_places = [o for o in by_capture.get(captures["control"]["capture_id"], [])
                      if o["occurrence_class"] == "place"]
    proposal = observations[captures["place"]["capture_id"]]["observation"]["proposed_place"]
    if not place_occurrences or proposal is None:
        raise SystemExit("the vision pass proposed no place, so the chain stops before an entity")

    # 4. The review decision that makes a place-class memory entity.
    status, named = step("name the place occurrence (driver acting as the synthetic account "
                         "holder)", "POST", "/identity/name", {
        "occurrence_id": place_occurrences[0]["occurrence_id"],
        "display_name": proposal["label"],
    })
    if status != 200:
        raise SystemExit(f"naming refused: {status} {named}")
    _, catalogue = step("list the named entities", "GET", "/selection/catalogue")

    # 5. The admitted place and the bridge, by lane D's walker.
    walker_out = Path(arguments.out).with_suffix(".walker.json")
    started = time.monotonic()
    walked = subprocess.run([sys.executable, arguments.walker, arguments.state, str(walker_out)],
                            capture_output=True, text=True, check=False)
    walker = json.loads(walker_out.read_text()) if walker_out.exists() else {}
    steps.append({"step": "admitted place and bridge (lane D walker)",
                  "wall_ms": round((time.monotonic() - started) * 1000),
                  "exit": walked.returncode, "stdout": walked.stdout[-2000:]})
    print(walked.stdout[-800:])
    # The walker names its own ids at the top level; the admission id is chosen by the client,
    # so no response carries it.
    admission_id = walker.get("admission_id")
    feature_id = walker.get("feature_id")
    canonical_place_id = walker.get("place_id")
    _, bridges = step("list confirmed bridges", "GET", "/selection/place-bridges")

    # 6. The deterministic CONTENT answer for the admitted place, with a bridge behind it.
    content = None
    if admission_id and feature_id:
        _, content = step("ask with the admitted place selected (CONTENT)", "POST",
                          "/selection/ask", {
            "question": "What is here?",
            "city_context": {"admission_id": admission_id, "feature_id": feature_id},
        })

    # 7. A question in words about the personal place.
    question = arguments.question or f"What do my photographs show at {proposal['label']}?"
    _, worded = step("ask a question in words", "POST", "/selection/ask", {"question": question})

    Path(arguments.out).write_text(json.dumps({
        "measurement_note": "A MEASUREMENT OF THE CHAIN under an UNADOPTED vision prompt. The "
                            "prompt that produced the proposal failed its pre-registered "
                            "held-out gate and is not adopted.",
        "captures": captures,
        "vision_observations": {role: observations.get(c["capture_id"])
                                for role, c in captures.items()},
        "place_occurrences": place_occurrences,
        "control_place_occurrences": control_places,
        "named": named,
        "catalogue": catalogue,
        "walker_steps": walker.get("steps", []),
        "canonical_place_id": canonical_place_id,
        "admission_id": admission_id,
        "feature_id": feature_id,
        "bridges": bridges,
        "content_answer": content,
        "question": question,
        "worded_answer": worded,
        "steps": steps,
    }, indent=2, sort_keys=True, default=str) + "\n")
    print(f"wrote {arguments.out}")


if __name__ == "__main__":
    main()
