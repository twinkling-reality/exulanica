"""Letting the depth model estimate shape from a personal photograph is its own decision.

A screening receipt says the photograph may be looked at and built from. It names no model, so a
person who let a detector find faces has not thereby let a depth network read the same pixels and
publish a point map of their living room. The depth right is that second decision, and these tests
hold the three things that make it a decision rather than a default: it is granted only when it is
asked for, only against the exact wording this server states, and it is visible and revocable
afterwards.
"""


from exulanica.ingest.personal_admission import DEPTH_MODEL_NOTICE, ROLE_NOTICE
from exulanica.ingest.stages.segmentation import DEPTH_ROLE, local_model_role

from test_intake_upload import upload as upload
from test_personal_admission_route import batch, post, reviewing


def depth_rights(body, notice=DEPTH_MODEL_NOTICE):
    return [
        {
            "role": DEPTH_ROLE,
            "valid_until": body["authority"]["valid_until"],
            **({} if notice is None else {"notice": notice}),
        }
    ]


def reviewed(upload, count=2, notice=DEPTH_MODEL_NOTICE):
    body = reviewing(batch(upload, count=count))
    body["model_rights"] = depth_rights(body, notice)
    return body


def test_a_ticked_depth_right_names_the_pinned_checkpoint_and_this_process(upload):
    body = reviewed(upload)
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    pin = local_model_role(DEPTH_ROLE).primary
    for receipt in response.json()["receipts"]:
        (right,) = receipt["model_rights"]
        assert right["model"] == {
            "provider": "local",
            "role": DEPTH_ROLE,
            "model_id": pin.repo_id,
            "revision": pin.revision,
        }
        assert right["destination"] == "local-process"
        assert right["valid_until"][:19] == body["authority"]["valid_until"][:19]
    # One right per photograph, not one per batch: stopping it for one photograph is possible
    # only because each photograph has its own row.
    assert len(upload.rows("select right_id from personal_model_right")) == len(body["members"])


def test_the_wording_the_person_was_shown_is_inside_the_authority_they_granted(upload):
    body = reviewed(upload, count=1)
    assert post(upload, "/personal-admission", body).status_code == 202
    (row,) = upload.rows(
        "select authorization_scope from capture_reconstruction_authorization "
        "where corpus_class='personal'"
    )
    assert row["authorization_scope"]["model_rights"] == [
        {
            "role": DEPTH_ROLE,
            "valid_until": body["authority"]["valid_until"],
            "notice": DEPTH_MODEL_NOTICE,
        }
    ]
    assert row["authorization_scope"]["human_attestation"] == body["attestation"]


def test_an_admission_that_ticks_nothing_grants_no_depth_right(upload):
    body = reviewing(batch(upload))
    body["model_rights"] = []
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    assert all(receipt["model_right_ids"] == [] for receipt in response.json()["receipts"])
    assert upload.rows("select right_id from personal_model_right") == []


def test_a_notice_this_server_did_not_write_is_refused_before_anything_is_written(upload):
    body = reviewed(upload, count=1)
    altered = DEPTH_MODEL_NOTICE.replace("approximate", "exact")
    assert altered != DEPTH_MODEL_NOTICE
    for notice in (
        None,                               # the client showed nothing
        "",                                 # the client showed a blank
        altered,                            # the client showed a claim this server does not make
        DEPTH_MODEL_NOTICE + " ",           # one character
        # One character, invisibly: a typographic apostrophe for a straight one.
        DEPTH_MODEL_NOTICE.replace("Exulanica's", "Exulanica\u2019s"),
    ):
        body["model_rights"] = depth_rights(body, notice)
        response = post(upload, "/personal-admission", body)
        assert response.status_code == 409, (notice, response.text)
    assert upload.rows("select * from personal_model_right") == []
    assert upload.rows("select * from capture_reconstruction_authorization") == []
    # Positive control over the same fixture: the refusals above are the notice and not the body.
    body["model_rights"] = depth_rights(body)
    assert post(upload, "/personal-admission", body).status_code == 202
    assert len(upload.rows("select * from personal_model_right")) == 1


def test_a_notice_cannot_be_attached_to_a_role_this_server_states_none_for(upload):
    body = reviewing(batch(upload, count=1))
    valid_until = body["authority"]["valid_until"]
    assert "vision" not in ROLE_NOTICE
    body["model_rights"] = [
        {"role": "vision", "valid_until": valid_until, "notice": DEPTH_MODEL_NOTICE}
    ]
    assert post(upload, "/personal-admission", body).status_code == 409
    assert upload.rows("select * from personal_model_right") == []
    # The same role without a notice is the behaviour that existed before this lane.
    body["model_rights"] = [{"role": "vision", "valid_until": valid_until}]
    assert post(upload, "/personal-admission", body).status_code == 202


def test_the_photo_owner_sees_the_right_and_can_stop_it(upload):
    body = reviewed(upload, count=1)
    receipt = post(upload, "/personal-admission", body).json()["receipts"][0]
    (right_id,) = receipt["model_right_ids"]

    def state():
        status = upload.get("/personal-admission").json()
        source = next(s for s in status["sources"] if s["capture_id"] == receipt["capture_id"])
        return {right["right_id"]: right["state"] for right in source["model_rights"]}

    assert state() == {right_id: "current"}
    stopped = post(upload, f"/personal-admission/model-rights/{right_id}/withdraw", {})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["state"] == "ended"
    assert state() == {right_id: "ended"}
