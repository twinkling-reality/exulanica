#!/usr/bin/env python3
"""Exercise production person withdrawal over one exact synthetic scene."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from exulanica.evaluation.person_withdrawal import (
    PersonWithdrawalExercise,
    exercise_synthetic_person_withdrawal,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--purge-database-url", required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--workspace-id", type=uuid.UUID, required=True)
    parser.add_argument("--scene-id", type=uuid.UUID, required=True)
    parser.add_argument("--capture-id", type=uuid.UUID, required=True)
    parser.add_argument("--expected-current-job-id", type=uuid.UUID, required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--actor-id", type=uuid.UUID, required=True)
    parser.add_argument("--git-head", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--resume-started-git-head")
    args = parser.parse_args()
    result = exercise_synthetic_person_withdrawal(
        PersonWithdrawalExercise(
            database_url=args.database_url,
            purge_database_url=args.purge_database_url,
            store_root=args.store_root,
            workspace_id=args.workspace_id,
            scene_id=args.scene_id,
            capture_id=args.capture_id,
            expected_current_job_id=args.expected_current_job_id,
            expected_source_manifest_sha256=args.expected_source_manifest_sha256,
            expected_source_sha256=args.expected_source_sha256,
            actor_id=args.actor_id,
            git_head=args.git_head,
            output_directory=args.output_directory,
            report_path=args.report,
            interrupted_run_git_head=args.resume_started_git_head,
        )
    )
    print(json.dumps({"record_sha256": result["record_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
