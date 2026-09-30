"""CI builds the images that serve judges and boots the API under its judge role."""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "check.yml"
).read_text(encoding="utf-8")


def _image_job(workflow: str) -> str:
    return workflow.split("\n  image:\n", 1)[1]


def _check_image_job(workflow: str) -> None:
    job = _image_job(workflow)
    assert "name: build default API image" in job
    assert "name: build judge backend" in job
    assert "EXULANICA_SYNC_EXTRAS=--extra server" in job
    assert "tags: exulanica-judge-backend:ci" in job
    assert "name: build judge web" in job
    assert "file: deploy/judge/web.Dockerfile" in job
    assert "tags: exulanica-judge-web:ci" in job
    assert job.count("load: true") == 2
    assert job.count("platforms: linux/amd64") == 2
    assert "exulanica-judge-backend:ci exulanica-db" in job
    assert "exulanica-judge-backend:ci exulanica-seed role" in job
    assert "--env EXULANICA_API_TOKENS" in job
    assert "--env EXULANICA_DATABASE_URL=" in job
    assert "--env EXULANICA_READONLY_DATABASE_URL=" in job
    assert "http://127.0.0.1:18080/healthz" in job
    assert "trap cleanup EXIT" in job
    assert "docker rm -f judge-ci-api judge-ci-postgres" in job


def test_ci_builds_both_judge_images_and_boots_the_real_api():
    _check_image_job(WORKFLOW)


@pytest.mark.parametrize(
    "removed",
    [
        "file: deploy/judge/web.Dockerfile",
        "exulanica-judge-backend:ci exulanica-seed role",
        "http://127.0.0.1:18080/healthz",
        "trap cleanup EXIT",
    ],
)
def test_image_job_control_catches_a_missing_step(removed: str):
    assert removed in WORKFLOW
    with pytest.raises(AssertionError):
        _check_image_job(WORKFLOW.replace(removed, "removed", 1))
