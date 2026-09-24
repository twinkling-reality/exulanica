"""A photograph awaiting admission waits for it; its upload's job does not fail.

An upload queues its derivative job before the person has reviewed anything, and a worker that
runs the depth model claims that job at once. Measured in the rehearsal of the personal path: at
a person's pace (upload, look, then admit) every upload's job failed, one PrivacyAdmissionError
per photograph from the depth stage. These tests walk that pace through the real routes and the
real worker: the upload's job ends without a failure and without a point map, the admission
queues the job that runs depth under the exact receipt, and a photograph never admitted keeps no
point map with the reason recorded.
"""

from __future__ import annotations

import datetime as dt
import uuid

from exulanica.ingest.personal_admission import DEPTH_ROLE, role_handoff, role_notices
from exulanica.ingest.stages.depth import AWAITING_ADMISSION
from exulanica.ingest.worker import DerivativeWorker
from exulanica.reconstruction.testing import FlatDepthModel

from test_intake_upload import upload as upload
from test_personal_admission_route import batch, post, reviewing

POINT_MAPS = "select a.artifact_id from artifact a where a.kind = 'point_map'"


class CountingDepth(FlatDepthModel):
    """The flat depth double, stating the checkpoint a depth right granted by the route names."""

    model_handoff = role_handoff(DEPTH_ROLE)

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def predict(self, image):
        self.calls += 1
        return super().predict(image)


def _drain(upload, depth):
    return DerivativeWorker(
        upload.database,
        upload.store,
        frozenset({upload.workspace_id}),
        depth=depth,
        name="depth-awaits-admission",
    ).drain()


def _depth_reasons(upload, capture_id: str) -> list[str]:
    return [
        row["error_message"]
        for row in upload.rows(
            "select e.error_message from pipeline_event e "
            "join pipeline_run r on r.run_id = e.run_id "
            "where r.capture_id = %s and e.stage_key = 'depth' and e.type = 'stage_unavailable' "
            "order by e.event_id",
            uuid.UUID(capture_id),
        )
    ]


def test_an_upload_waits_for_admission_and_the_admission_runs_depth(upload):
    body = batch(upload, count=3)
    captures = [member["capture_id"] for member in body["members"]]
    depth = CountingDepth()

    # The worker claims the upload's job before anybody has looked at the photographs.
    first = _drain(upload, depth)
    assert [outcome.errors for outcome in first] == [[]]
    assert upload.rows("select state from job") == [{"state": "done"}]
    assert not upload.rows(
        "select event_type from derivative_job_event "
        "where event_type in ('capture_failed', 'job_failed')"
    )
    assert depth.calls == 0, "no screening receipt, so nothing reaches the depth model"
    assert upload.rows(POINT_MAPS) == []
    for capture in captures:
        assert _depth_reasons(upload, capture) == [AWAITING_ADMISSION]

    # Then the person reviews two of the three and grants the depth model, through the route.
    admitted = reviewing(body)
    admitted["members"] = admitted["members"][:2]
    valid_until = admitted["authority"]["valid_until"]
    admitted["model_rights"] = [
        {"role": DEPTH_ROLE, "valid_until": valid_until, "notice": role_notices()[DEPTH_ROLE]}
    ]
    response = post(upload, "/personal-admission", admitted)
    assert response.status_code == 202, response.text

    second = _drain(upload, depth)
    assert [outcome.errors for outcome in second] == [[]]
    assert {row["state"] for row in upload.rows("select state from job")} == {"done"}
    assert depth.calls == 2
    assert len(upload.rows(POINT_MAPS)) == 2

    # The third was never admitted: no point map, and the one stated reason is still the wait.
    never = captures[2]
    assert _depth_reasons(upload, never) == [AWAITING_ADMISSION]
    assert not upload.rows(
        "select a.artifact_id from artifact a "
        "join capture c on c.blob_sha256 = a.source_blob_sha256 "
        "where a.kind = 'point_map' and c.capture_id = %s",
        uuid.UUID(never),
    )


def test_an_admission_before_the_claim_runs_depth_in_the_upload_job(upload):
    """The other order the rehearsal saw: the admission lands before the worker claims."""
    body = reviewing(batch(upload, count=1))
    body["model_rights"] = [
        {
            "role": DEPTH_ROLE,
            "valid_until": (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=30)).isoformat(),
            "notice": role_notices()[DEPTH_ROLE],
        }
    ]
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    depth = CountingDepth()
    outcomes = _drain(upload, depth)
    assert [outcome.errors for outcome in outcomes] == [[], []]
    assert depth.calls == 1, "the upload's job computes it and the admission's job reuses it"
    assert len(upload.rows(POINT_MAPS)) == 1
    assert _depth_reasons(upload, body["members"][0]["capture_id"]) == []
