"""Measure synthetic declared-plan plumbing in a temporary schema of the sole test database.

EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test \
  uv run python scripts/measure_gold_questions.py --corpus /tmp/generated --out /tmp/measurement

Uses the same migrated-schema harness as the tests. Run exclusively: this is an administrative
experiment, not a product ingest entry point. Vision is omitted, so object queries miss their
captions and the resulting failures measure no detector or identity accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.parse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from pg_harness import migrated_schema, open_scratch_connection  # noqa: E402

from exulanica.evaluation.cli import main  # noqa: E402
from exulanica.evaluation.ground_truth import GroundTruth  # noqa: E402
from exulanica.evaluation.question_scorers import score_gold_questions  # noqa: E402
from exulanica.evaluation.questions import GoldQuestions  # noqa: E402
from exulanica.ingest.pipeline import PhotoIngestPipeline  # noqa: E402
from exulanica.ingest.repository import IngestRepository  # noqa: E402
from exulanica.store.local import LocalContentAddressedStore  # noqa: E402

URL = "postgresql://localhost:5433/exulanica_spine_test"


def measure() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--questions",
        type=Path,
        default=ROOT / "tests/fixtures/synthetic-gold-questions/QUESTIONS.json",
    )
    args = parser.parse_args()
    if os.environ.get("EXULANICA_TEST_DATABASE_URL") != URL:
        raise ValueError(f"This experiment permits only EXULANICA_TEST_DATABASE_URL={URL}")
    truth = GroundTruth.read(args.corpus)
    questions = GoldQuestions.read(args.questions, truth)
    args.out.mkdir(parents=True, exist_ok=False)
    with migrated_schema() as (psycopg, owner), tempfile.TemporaryDirectory() as data:
        scratch = owner.execute("select current_schema()").fetchone()[0]
        with open_scratch_connection(psycopg, scratch) as connection:
            workspace = uuid.uuid4()
            repository = IngestRepository(connection, workspace)
            store = LocalContentAddressedStore(Path(data) / "blobs")
            for frame in truth.frames:
                outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
                    args.corpus / frame.filename
                )
                if outcome.error is not None:
                    raise RuntimeError(outcome.error)
            scores = score_gold_questions(connection, workspace, truth, questions)
            opts = urllib.parse.quote(f"-csearch_path={scratch},public", safe="")
            os.environ["EXULANICA_DATABASE_URL"] = URL + "?options=" + opts
            output = io.StringIO()
            code = main(
                [
                    "run",
                    "--corpus",
                    str(args.corpus),
                    "--workspace",
                    str(workspace),
                    "--data-dir",
                    data,
                    "--questions",
                    str(args.questions),
                ],
                output,
            )
            if code != 0:
                raise RuntimeError(output.getvalue())
            (args.out / "report.txt").write_text(output.getvalue())
            record = {
                "profile": "exulanica.synthetic-gold-question-measurement/v1",
                "corpus_id": "SYNTH-1",
                "synthetic": True,
                "manifest_sha256": truth.manifest_sha256,
                "questions_sha256": questions.sha256,
                "frames": len(truth.frames),
                "questions": len(questions.questions),
                "vision": "omitted; capture metadata and rendition only; no model calls",
                "interpretation": "Declared-plan compiler/SQL/answer plumbing. Object retrieval "
                "misses reflect omitted captions; no live-model or identity accuracy measured.",
                "components": {
                    key: None
                    if count is None
                    else {
                        "corpus_id": "SYNTH-1",
                        "k": count.k,
                        "n": count.n,
                        "cases": [
                            {"name": c.name, "passed": c.passed, "evidence": c.evidence}
                            for c in count.cases
                        ],
                    }
                    for key, count in scores.results.items()
                },
                "blocked": scores.blocked,
                "observations": scores.observations,
                "experiment_script": "scripts/measure_gold_questions.py",
                "experiment_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "report_sha256": hashlib.sha256(output.getvalue().encode()).hexdigest(),
            }
            (args.out / "measurement.json").write_text(json.dumps(record, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "frames": record["frames"],
                        "questions": record["questions"],
                        "components": {
                            k: {"k": v["k"], "n": v["n"]} for k, v in record["components"].items()
                        },
                    }
                )
            )


if __name__ == "__main__":
    measure()
