"""Read-only retrieval measurement. No model calls and no writes to either database.

Run with EXULANICA_REFERENCE_DATABASE_URL pointing to exulanica_inspect_test. The five recorded
questions are followed by ten natural questions. Distillations are declared inputs, not measured
planner outputs. A real fused comparison remains unavailable without an authorized live budget.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from exulanica.canonical import canonical_json
from exulanica.db.session import set_workspace
from exulanica.selection import Intent, SelectionPlan, Session, execute, validate
from exulanica.selection.packet import build_packet
from psycopg.rows import dict_row

QUESTIONS = [
    ("When were these photographs taken?", None),
    ("How many photographs are there?", None),
    ("What is this place?", None),
    ("Who is in these photographs?", None),
    ("What is the current exchange rate for the pound?", None),
    ("What is this place, and what are the people wearing?", "people wearing"),
    ("Which of my photos show a snow-covered mountain?", "snow mountain"),
    ("What cold-weather clothing do the people have on?", "cold weather clothing"),
    ("Where can I see protective headgear?", "protective headgear"),
    ("Which photos show an icy landscape?", "icy landscape"),
    ("Are there reflective strips on their clothes?", "reflective strips clothes"),
    ("Where is the sky glowing orange?", "sky orange"),
    ("Which pictures show a volcanic crater?", "volcanic crater"),
    ("Is steam rising from a rocky crater?", "steam rocky crater"),
    ("Where are penguins on a beach?", "penguin beach"),
]
WORKSPACES = {
    "first_place": "9e69f7e8-2372-489b-8eb3-b71ea74c16b2",
    "volcanic": "79004d44-ca24-4d17-9eef-56786415e233",
}


def main() -> None:
    url = os.environ["EXULANICA_REFERENCE_DATABASE_URL"]
    root = Path(__file__).resolve().parents[1]
    record = {
        "profile": "exulanica.companion-matching/v1",
        "date": "2026-09-11",
        "base": "d13b01d",
        "predecessor": "docs/evaluation/2026-09-10-companion-proposals.json",
        "predecessor_file_sha256": hashlib.sha256(
            (root / "docs/evaluation/2026-09-10-companion-proposals.json").read_bytes()
        ).hexdigest(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "head_is_what_ran": subprocess.call(["git", "diff", "--quiet", "HEAD", "--",
            "exulanica/selection", "tests/record_companion_matching.py"]) == 0,
        "live_calls": 0,
        "live_cost_usd": "0",
        "prompt_version": "selection-4",
        "distillation_source": "manually declared; planner behavior not live-measured",
        "lexical_minimum": "ceil(distinct English lexemes / 2), at least one",
        "fusion": "equal-weight reciprocal dense ranks with k=60, cosine floor=0.65 (unvalidated)",
        "corpora": {},
        "limitations": [
            "No live-call budget was authorized. Fused model-quality results are null.",
            "Volcanic capture count does not imply caption existence.",
            "Retrieval abstention means zero citable packet items; no composer was run.",
            "The original identity, place-name and exchange-rate questions may need answer-level "
            "abstention even when their unconstrained selections retrieve photographs.",
            "Scripted-vector executor tests establish mechanics, not model retrieval quality.",
            "Capture/workspace physical vector purge is a failing acceptance test awaiting "
            "authorized deletion integration edits. Do not enable live indexing.",
        ],
    }
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
        assert connection.info.dbname == "exulanica_inspect_test"
        connection.execute("set default_transaction_read_only=on")
        for label, raw_workspace in WORKSPACES.items():
            workspace = uuid.UUID(raw_workspace)
            set_workspace(connection, workspace)
            captions = connection.execute(
                "select a.assertion_id, a.subject_ref->>'id' as capture_id, a.object_value as text "
                "from assertion a join predicate p using(predicate_id) "
                "where a.workspace_id=%s and a.status='active' and p.key='caption_is' "
                "order by a.assertion_id",
                (workspace,),
            ).fetchall()
            count = connection.execute(
                "select count(*) as n from capture where workspace_id=%s and deleted_at is null",
                (workspace,),
            ).fetchone()["n"]
            rows = []
            for number, (question, terms) in enumerate(QUESTIONS, 1):
                plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query=terms, limit=24)
                result = execute(
                    connection,
                    validate(
                        connection, plan, Session(workspace_id=workspace, actor=uuid.UUID(int=1))
                    ),
                )
                packet = build_packet(connection, result, workspace_id=workspace)
                rows.append(
                    {
                        "ordinal": number,
                        "question": question,
                        "source": "recorded" if number <= 5 else "additional natural question",
                        "semantic_query": terms,
                        "lexical_only": {
                            "hits": result.total_matched,
                            "capture_ids": [str(c.capture_id) for c in result.captures],
                            "retrieval_abstained": packet.is_empty,
                        },
                        "fused": None,
                        "fused_unavailable_reason": "No live embedding budget authorized",
                    }
                )
            record["corpora"][label] = {
                "workspace_id": str(workspace),
                "capture_count": count,
                "active_caption_count": len(captions),
                "captions": captions,
                "questions": rows,
            }
    paths = [
        "exulanica/selection/executor.py",
        "exulanica/selection/embeddings.py",
        "exulanica/selection/question.py",
        "exulanica/selection/packet.py",
        "tests/record_companion_matching.py",
    ]
    record["measured_files_sha256"] = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths
    }
    out = root / "docs/evaluation/2026-09-11-companion-matching.json"
    out.write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(out)


def seal_record(path: Path, additions: dict) -> str:
    """Bind measured output and retained gate logs without repeating any database work."""
    document = json.loads(path.read_text())
    record = document.get("record", document)
    record.update(additions)
    root = Path(__file__).resolve().parents[1]
    predecessor_path = record.get("predecessor_record", {}).get("path", record["predecessor"])
    predecessor_bytes = (root / predecessor_path).read_bytes()
    predecessor = json.loads(predecessor_bytes)
    predecessor_digest = hashlib.sha256(canonical_json(predecessor["record"])).hexdigest()
    assert predecessor_digest == predecessor["record_sha256"], "predecessor digest mismatch"
    assert predecessor_digest == record["predecessor_record_sha256"]
    assert hashlib.sha256(predecessor_bytes).hexdigest() == record["predecessor_file_sha256"]
    record["predecessor_record"] = {
        "path": predecessor_path, "record_sha256": predecessor_digest,
    }
    for gate in record.get("gates", []):
        actual = hashlib.sha256(gate["stdout_stderr"].encode()).hexdigest()
        assert actual == gate["log_sha256"], f"gate log digest mismatch: {gate['name']}"
    for measured_path, expected in record["measured_files_sha256"].items():
        content = subprocess.check_output(
            ["git", "show", f"{record['head']}:{measured_path}"], cwd=root,
        )
        assert hashlib.sha256(content).hexdigest() == expected, (
            f"measured file differs from recorded head: {measured_path}"
        )
    # Keep command structure without publishing the operator's checkout or runtime paths.
    runtime = Path(sys.executable).parent.parent
    replacements = {
        str(runtime): "{RUNTIME_ENV}",
        os.path.relpath(runtime, root): "{RUNTIME_ENV}",
        str(root): "{MATCHING_CHECKOUT}",
    }

    def scrub(value):
        if isinstance(value, str):
            for local, placeholder in replacements.items():
                value = value.replace(local, placeholder)
            return value
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    scrubbed = scrub(record)
    for old_gate, gate in zip(record.get("gates", []), scrubbed.get("gates", []), strict=True):
        if gate["stdout_stderr"] != old_gate["stdout_stderr"]:
            gate.setdefault("unredacted_log_sha256", old_gate["log_sha256"])
            gate["log_sha256"] = hashlib.sha256(gate["stdout_stderr"].encode()).hexdigest()
    record = scrubbed
    record["path_placeholders"] = {
        "{RUNTIME_ENV}": "The shared virtual environment used by the recorded commands",
        "{MATCHING_CHECKOUT}": "The matching worktree at the recorded tested head",
    }
    assert "/Users/" not in json.dumps(record), "an undeclared personal path remains"
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    path.write_text(json.dumps({
        "profile": "exulanica.digest-bound-record/v1", "record": record,
        "record_sha256": digest,
    }, indent=2) + "\n")
    return digest


if __name__ == "__main__":
    main()
