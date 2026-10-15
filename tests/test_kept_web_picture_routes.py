"""Keeping a picture a picture search found, and reading and erasing what a workspace keeps, over
HTTP: as the runtime and read-only roles a deployment uses, with the fetch stood in for, so nothing
reaches a network. The search's pictures are held as the job holds them."""

from __future__ import annotations

import io
import uuid

import pytest
from exulanica.references import picture_fetch
from exulanica.references.adapters.base import WebPicture
from exulanica.references.held_pictures import held_pictures
from exulanica.references.picture_fetch import FetchedPicture, PictureFetchRefused
from exulanica.store.configured import local_content_stores
from PIL import Image

from test_reference_routes import OTHER_ACTOR_TOKEN, STRANGER_TOKEN, TOKEN
from test_reference_routes import _bench_alias as _bench_alias
from test_reference_routes import _named_alias as _named_alias
from test_reference_routes import api as api
from test_reference_routes import saved_named as saved_named
from test_reference_routes import spending_bench as spending_bench

pytestmark = pytest.mark.postgres

DUCK = "https://pictures.example/yellow-duck.png"
POND = "https://ponds.example/pond.png"


def _png(colour=(250, 220, 40)) -> bytes:
    written = io.BytesIO()
    Image.new("RGB", (24, 18), colour).save(written, format="PNG")
    return written.getvalue()


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def served(api, tmp_path, monkeypatch):
    client, repository = api
    fetched: list[str] = []

    def fetch(address: str) -> FetchedPicture:
        fetched.append(address)
        return FetchedPicture(_png(), "image/png", 0)

    monkeypatch.setattr(picture_fetch, "fetch_picture", fetch)
    app = client(reference_web_pictures=True, content_stores=local_content_stores(tmp_path))
    made = app.post(
        "/worlds/references",
        json={"purpose": "things", "description": "yellow duck", "web": True, "web_pictures": True},
        headers=_auth(),
    )
    assert made.status_code == 202, made.text
    reference_id = uuid.UUID(made.json()["reference_id"])
    held_pictures().hold(
        repository.workspace_id,
        reference_id,
        (
            WebPicture(DUCK, "pictures.example", "A yellow duck"),
            WebPicture(POND, "ponds.example", None),
        ),
    )
    yield app, reference_id, fetched, repository
    held_pictures().forget(repository.workspace_id, reference_id)


def _keep(app, reference_id, n: int = 1, token: str = TOKEN, **body):
    return app.post(
        f"/worlds/references/{reference_id}/pictures/{n}/keep",
        json={"answer": "private_world_only", **body},
        headers=_auth(token),
    )


def test_a_picked_picture_is_kept_read_and_erased_by_its_keeper(served) -> None:
    app, reference_id, fetched, _repository = served
    kept = _keep(app, reference_id)
    assert kept.status_code == 201, kept.text
    view = kept.json()
    assert fetched == [POND]
    assert (view["address"], view["website"], view["media_type"]) == (
        POND,
        "ponds.example",
        "image/png",
    )
    assert (view["width"], view["height"], view["answer"]) == (24, 18, "private_world_only")
    assert view["reference_id"] == str(reference_id)
    picture = f"/worlds/web-pictures/{view['picture_id']}"
    assert app.get("/worlds/web-pictures", headers=_auth()).json()["pictures"] == [view]
    assert app.get(picture, headers=_auth()).json() == view
    data = app.get(f"{picture}/bytes", headers=_auth())
    assert data.status_code == 200 and data.headers["content-type"] == "image/png"
    assert data.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(data.content)) as read:
        assert read.size == (24, 18)
    # Another workspace reads it as one nobody keeps; another person of this one may not erase it.
    elsewhere = app.get(picture, headers=_auth(STRANGER_TOKEN))
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (404, "unknown_web_picture")
    refused = app.delete(picture, headers=_auth(OTHER_ACTOR_TOKEN))
    assert (refused.status_code, refused.json()["code"]) == (403, "picture_not_yours")
    assert app.delete(picture, headers=_auth()).status_code == 204
    assert app.get(picture, headers=_auth()).status_code == 404
    assert app.get("/worlds/web-pictures", headers=_auth()).json()["pictures"] == []


def test_a_keep_is_refused_by_name_before_anything_is_fetched(served, api) -> None:
    app, reference_id, fetched, _repository = served
    for n, code in ((2, "picture_unknown"),):
        refused = _keep(app, reference_id, n=n)
        assert (refused.status_code, refused.json()["code"]) == (404, code)
    refused = _keep(app, reference_id, answer="licence_allows")
    assert (refused.status_code, refused.json()["code"]) == (422, "licence_missing")
    refused = _keep(app, reference_id, token=OTHER_ACTOR_TOKEN)
    assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
    off = api[0]()
    refused = _keep(off, reference_id)
    assert (refused.status_code, refused.json()["code"]) == (409, "web_pictures_not_offered")
    held_pictures().forget(served[3].workspace_id, reference_id)
    refused = _keep(app, reference_id)
    assert (refused.status_code, refused.json()["code"]) == (404, "pictures_not_held")
    assert fetched == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("picture_host_not_public", 422),
        ("picture_not_an_image", 422),
        ("picture_too_large", 422),
        ("picture_unreachable", 502),
        ("picture_timed_out", 502),
    ],
)
def test_a_fetch_refusal_keeps_nothing_and_is_answered_by_name(
    served, monkeypatch, code, status
) -> None:
    app, reference_id, _fetched, _repository = served

    def refuse(address: str) -> FetchedPicture:
        raise PictureFetchRefused(code)

    monkeypatch.setattr(picture_fetch, "fetch_picture", refuse)
    refused = _keep(app, reference_id)
    assert (refused.status_code, refused.json()["code"]) == (status, code)
    assert DUCK not in refused.text and POND not in refused.text
    assert app.get("/worlds/web-pictures", headers=_auth()).json()["pictures"] == []


def test_bytes_that_are_not_a_picture_are_refused_and_nothing_is_kept(served, monkeypatch) -> None:
    app, reference_id, _fetched, _repository = served
    monkeypatch.setattr(
        picture_fetch,
        "fetch_picture",
        lambda address: FetchedPicture(b"<html>not a picture</html>", "image/png", 0),
    )
    refused = _keep(app, reference_id)
    assert (refused.status_code, refused.json()["code"]) == (422, "picture_not_an_image")
    assert app.get("/worlds/web-pictures", headers=_auth()).json()["pictures"] == []
