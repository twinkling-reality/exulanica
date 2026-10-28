"""A visitor's own copy of a showcase world is the world a sentence made, alive as it lived.

A showcase world's document holds what the sentence's draft decided and the made world's identity
and receipt digest (:mod:`exulanica.world.showcase_worlds`). ``POST /worlds/showcase/{showcase}``
makes it in the caller's own workspace with no model call; the control is the installation's own
world of the same document, whose receipt the copy must match byte for byte. The copy is brought to
life as the made world was (its society, the cast's models), once, and opens playing; its painting
is kept for it as a record, and its document's card picture, the engine's own first view of the
world, as its card picture, current for the copy as made, unless the copy was left in the host's
look. Asked again, the workspace's copy is answered as the visitor left it. A document whose
painting's or picture's bytes or look's setting the host cannot hold is refused when the catalog
loads, never at a visitor's copy. A copy's painting is deleted with its world by G1's identity
trigger, which ``test_world_erasure_postgres.py`` holds for every painting row.

The catalog's reads (``GET /worlds/showcase`` and a card picture's bytes) answer the installation's
own documents to any session, a guest's included, the same for every workspace; they take no
connection, so those tests need no database.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import GUEST_PERMISSIONS
from exulanica.api.services import Services
from exulanica.canonical import sha256_of_canonical
from exulanica.db.session import Database
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import showcase_worlds as catalog
from exulanica.world.errors import StyleWriteBusy
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.saved_entry_pictures import checked_picture
from exulanica.world.society_control_repository import open_session_receipt
from fastapi.testclient import TestClient

from personal_world_support import STRANGER_TOKEN
from test_society_made_world import made as imported_made  # noqa: F401
from tests_support_api import EVERY_PERMISSION

CAST_MODEL = {
    "provider": "nebius_token_factory",
    "model_id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
}
#: A shipped showcase world, whose painting, card picture and look the tests below lend to others.
SHIPPED = json.loads((catalog.SHOWCASE_DIRECTORY / "mountain-town.v4.json").read_text())


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _document(key: str, world_id: str, receipt_sha256: str, **more) -> dict:
    return {
        "profile": catalog.PROFILE,
        "key": key,
        "version": 1,
        "title": "A small town by the sea",
        "sentence": "a small town by the sea",
        "world": {
            "world_id": world_id,
            "made_by": "town",
            "recipe": "small_town",
            "values": {},
            "kind": None,
            "land": None,
            "receipt_sha256": receipt_sha256,
        },
        "look": None,
        "society": {"engine": "exulanica-society/v5"},
        "cast": [{"ordinal": 0, "model": CAST_MODEL}],
        "made": {"date": "2026-10-26"},
        **more,
    }


def _catalog(
    tmp_path,
    document: dict,
    painting_bytes: bytes | None = None,
    picture_bytes: bytes | None = None,
):
    """``document`` alone, locked at its digest, as a showcase catalog; its paintings' and its
    picture's bytes the shipped ones unless ``painting_bytes`` or ``picture_bytes`` stands in."""
    directory = tmp_path / "showcase"
    for folder, records, stand_in in (
        ("paintings", document.get("paintings", []), painting_bytes),
        ("pictures", [document["picture"]] if document.get("picture") else [], picture_bytes),
    ):
        (directory / folder).mkdir(parents=True, exist_ok=True)
        for record in records:
            name = f"{record['sha256']}.jpg"
            if stand_in is None:
                shutil.copyfile(
                    catalog.SHOWCASE_DIRECTORY / folder / name, directory / folder / name
                )
            else:
                (directory / folder / name).write_bytes(stand_in)
    (directory / f"{document['key']}.v{document['version']}.json").write_text(json.dumps(document))
    lock = directory / "showcase-worlds.lock.json"
    lock.write_text(
        json.dumps(
            {
                "profile": catalog.LOCK_PROFILE,
                "worlds": [
                    {
                        "key": document["key"],
                        "version": document["version"],
                        "sha256": sha256_of_canonical(document).hex(),
                    }
                ],
            }
        )
    )
    return directory, lock


def _served(tmp_path, monkeypatch, document: dict) -> None:
    """Serve ``document`` alone as the installation's showcase catalog."""
    served = catalog.showcase_worlds(*_catalog(tmp_path, document))
    monkeypatch.setattr(
        "exulanica.api.routes.showcase_worlds.showcase_world", lambda key: served.get(key)
    )


def _made_world(api) -> tuple[str, str, uuid.UUID]:
    """The made world, the installation's own, of the identity its draft fixed: that identity, its
    receipt's digest and its entry."""
    owner = api.repository.workspace_id
    world_id = f"world:generated:{uuid.uuid4()}"
    with api.database.session(owner) as connection:
        original = SavedWorldEntryRepository(connection, owner, api.store).create_generated(
            title="A small town by the sea",
            recipe_key="small_town",
            created_by=uuid.uuid4(),
            values={},
            fixed_world_id=world_id,
        )
        digest, _ = generation_receipt(
            connection, owner, original.world_id, original.source_snapshot_id
        )
    return world_id, digest, original.entry_id


def _card_picture(api, entry_id: str) -> dict | None:
    """The card picture a page is told the visitor's copy has, as Your worlds lists it."""
    listed = api.get("/world-entries", token=STRANGER_TOKEN)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    entries = body if isinstance(body, list) else body["entries"]
    return next(one for one in entries if one["entry_id"] == entry_id)["picture"]


@pytest.mark.postgres
def test_a_visitor_s_copy_is_the_made_world_brought_to_life_once(made, tmp_path, monkeypatch):
    api = made
    world_id, digest, original = _made_world(api)
    painting = SHIPPED["paintings"][0]
    _served(
        tmp_path,
        monkeypatch,
        _document("seaside", world_id, digest, paintings=[painting], picture=SHIPPED["picture"]),
    )

    made_now = api.post("/worlds/showcase/seaside", {}, token=STRANGER_TOKEN)
    assert made_now.status_code == 201, made_now.text
    body = made_now.json()
    assert body["made"] is True and body["incomplete"] == []
    copy = body["entry"]
    assert copy["world_id"] == world_id and copy["entry_id"] != str(original)
    stranger = api.client.app.state.services.tokens.session_for(STRANGER_TOKEN).workspace_id

    def held() -> dict:
        with api.database.session(stranger) as connection:
            entry = SavedWorldEntryRepository(connection, stranger, api.store).entry(
                uuid.UUID(copy["entry_id"])
            )
            copied, _ = generation_receipt(
                connection, stranger, entry.world_id, entry.source_snapshot_id
            )
            society = connection.execute(
                "select society_id, engine_version from world_society "
                "where workspace_id=%s and world_id=%s",
                (stranger, world_id),
            ).fetchone()
            return {
                "receipt": copied,
                "society": society,
                "chosen": connection.execute(
                    "select document from world_society_model_choice "
                    "where workspace_id=%s and world_id=%s",
                    (stranger, world_id),
                ).fetchall(),
                "mode": connection.execute(
                    "select mode from world_society_control "
                    "where workspace_id=%s and society_id=%s",
                    (stranger, society["society_id"]),
                ).fetchone()["mode"],
                # A copy plays the routine alone: no living session asks the cast's models.
                "session": open_session_receipt(connection, stranger, society["society_id"]),
                "paintings": connection.execute(
                    "select sha256, view, camera from world_painting "
                    "where workspace_id=%s and world_id=%s",
                    (stranger, world_id),
                ).fetchall(),
            }

    first = held()
    # The same world, by its receipt; alive on the document's engine; its cast given its model;
    # playing from its first frame; its painting kept, painted from the camera recorded.
    assert first["receipt"] == digest
    assert first["society"]["engine_version"] == "exulanica-society/v5"
    assert [row["document"]["decider"]["model_id"] for row in first["chosen"]] == [
        CAST_MODEL["model_id"]
    ]
    assert first["mode"] == "playing" and first["session"] is None
    assert [(row["sha256"], row["view"]) for row in first["paintings"]] == [
        (painting["sha256"], painting["view"])
    ]
    assert first["paintings"][0]["camera"] == json.loads(painting["camera"])
    # Its card picture is its document's, the engine's own first view of the world, kept as the
    # copy's own and current for the copy as made, so a page shows it before any has drawn it.
    card = _card_picture(api, copy["entry_id"])
    assert card is not None and card["sha256"] == SHIPPED["picture"]["sha256"]
    assert card["current"] is True

    # Asked again: the copy the workspace holds, as it stands, dressed nothing more.
    again = api.post("/worlds/showcase/seaside", {}, token=STRANGER_TOKEN)
    assert again.status_code == 200, again.text
    assert again.json()["made"] is False and again.json()["entry"]["entry_id"] == copy["entry_id"]
    after = held()
    assert len(after["chosen"]) == 1 and len(after["paintings"]) == 1
    assert _card_picture(api, copy["entry_id"]) == card

    # A key the installation does not serve is answered alike for everyone.
    for token in (None, STRANGER_TOKEN):
        kwargs = {"token": token} if token else {}
        unknown = api.post("/worlds/showcase/nowhere", {}, **kwargs)
        assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_showcase_world"


@pytest.mark.postgres
def test_a_copy_left_in_the_host_s_look_keeps_no_card_picture(made, tmp_path, monkeypatch):
    """The picture shows the world in its document's look: a copy whose look could not be named
    (a busy write leaves it in the host's) keeps none, and waits for a page to draw it."""
    api = made
    world_id, digest, _ = _made_world(api)
    document = _document(
        "seaside", world_id, digest, look=SHIPPED["look"], picture=SHIPPED["picture"]
    )
    _served(tmp_path, monkeypatch, document)

    def busy(*_args, **_kwargs):
        raise StyleWriteBusy("another write holds the world's look")

    monkeypatch.setattr("exulanica.world.creation_look.name_creation_look", busy)
    made_now = api.post("/worlds/showcase/seaside", {}, token=STRANGER_TOKEN)
    assert made_now.status_code == 201, made_now.text
    assert _card_picture(api, made_now.json()["entry"]["entry_id"]) is None


def test_a_document_the_lock_does_not_name_at_its_digest_is_refused(tmp_path):
    document = _document("seaside", f"world:generated:{uuid.uuid4()}", "a" * 64)
    directory = tmp_path / "showcase"
    directory.mkdir()
    (directory / "seaside.v1.json").write_text(json.dumps(document))
    lock = directory / "showcase-worlds.lock.json"
    lock.write_text(
        json.dumps(
            {
                "profile": catalog.LOCK_PROFILE,
                "worlds": [{"key": "seaside", "version": 1, "sha256": "b" * 64}],
            }
        )
    )
    with pytest.raises(catalog.ShowcaseWorldsInvalid, match="is not the document"):
        catalog.showcase_worlds(directory, lock)


def test_a_painting_whose_bytes_are_not_its_record_is_refused_when_the_catalog_loads(tmp_path):
    document = _document(
        "seaside", f"world:generated:{uuid.uuid4()}", "a" * 64, paintings=SHIPPED["paintings"]
    )
    other = (catalog.SHOWCASE_DIRECTORY / "paintings").glob("*.jpg")
    stranger = next(path for path in other if path.stem != SHIPPED["paintings"][0]["sha256"])
    with pytest.raises(catalog.ShowcaseWorldsInvalid, match="paintings"):
        catalog.showcase_worlds(*_catalog(tmp_path, document, stranger.read_bytes()))


def test_a_card_picture_whose_bytes_are_not_its_record_is_refused_when_the_catalog_loads(tmp_path):
    document = _document(
        "seaside", f"world:generated:{uuid.uuid4()}", "a" * 64, picture=SHIPPED["picture"]
    )
    other = (catalog.SHOWCASE_DIRECTORY / "pictures").glob("*.jpg")
    stranger = next(path for path in other if path.stem != SHIPPED["picture"]["sha256"])
    with pytest.raises(catalog.ShowcaseWorldsInvalid, match="picture"):
        catalog.showcase_worlds(*_catalog(tmp_path, document, picture_bytes=stranger.read_bytes()))


def test_a_setting_the_pack_cannot_wear_is_refused_when_the_catalog_loads(tmp_path):
    look = {
        **SHIPPED["look"],
        "setting": {
            **SHIPPED["look"]["setting"],
            "surfaces": {
                "no_such.role": {"srgb8": [10, 20, 30]},
            },
        },
    }
    document = _document("seaside", f"world:generated:{uuid.uuid4()}", "a" * 64, look=look)
    with pytest.raises(catalog.ShowcaseWorldsInvalid, match=r"look\.setting"):
        catalog.showcase_worlds(*_catalog(tmp_path, document))


def test_the_shipped_showcase_worlds_read():
    served = catalog.showcase_worlds()
    assert served, "the installation serves showcase worlds"
    for key, world in served.items():
        assert world.key == key and world.cast
        # Each keeps its painting as a record for every copy, shown on no page.
        assert world.paintings and all(painting.view == "orbit" for painting in world.paintings)
        # Each carries its card picture, the engine's own first view of it, at a card's largest.
        assert world.picture is not None and world.picture.media_type == "image/jpeg"
        assert checked_picture(world.picture.data, "image/jpeg")[:2] == (1280, 720)


GUEST = "showcase-guest-token-long-enough-to-be-accepted"
OWNER = "showcase-owner-token-long-enough-to-be-accepted"


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _locked_documents() -> list[dict]:
    """The documents the lock serves, read from the files, by key."""
    lock = json.loads(catalog.SHOWCASE_LOCK.read_text(encoding="utf-8"))
    return [
        json.loads(
            (catalog.SHOWCASE_DIRECTORY / f"{one['key']}.v{one['version']}.json").read_text(
                encoding="utf-8"
            )
        )
        for one in sorted(lock["worlds"], key=lambda one: one["key"])
    ]


@pytest.fixture(name="reader")
def _reader(tmp_path) -> TestClient:
    # Never connected: the catalog's reads take no connection, and a token resolves without one.
    unused = Database(url="postgresql://unused.invalid/none")
    # A guest's browser session holds GUEST_PERMISSIONS; a token holding exactly those reaches
    # what the guest's session reaches, since the floor decides from what is held. Each token is
    # its own workspace.
    grants = {GUEST: sorted(str(one) for one in GUEST_PERMISSIONS), OWNER: EVERY_PERMISSION}
    tokens = load_token_directory(
        {
            "EXULANICA_API_TOKENS": json.dumps(
                {
                    token: {
                        "workspace_id": str(uuid.uuid4()),
                        "actor": str(uuid.uuid4()),
                        "permissions": permissions,
                    }
                    for token, permissions in grants.items()
                }
            )
        }
    )
    services = Services(
        database=unused,
        readonly_database=unused,
        store=LocalContentAddressedStore(tmp_path / "store"),
        tokens=tokens,
        executor_shares_the_write_role=True,
        model_client=None,
    )
    # Not entered as a context manager: the lifespan checks a database these routes never need.
    return TestClient(create_app(services, verify=False))


def test_the_catalog_is_the_installation_s_documents_alike_for_a_guest_and_an_owner(reader):
    documents = _locked_documents()
    assert documents, "the installation serves showcase worlds"
    expected = {
        "worlds": [
            {
                "key": document["key"],
                "title": document["title"],
                "sentence": document["sentence"],
                "world_id": document["world"]["world_id"],
                "picture": {
                    name: document["picture"][name]
                    for name in ("sha256", "media_type", "width", "height")
                },
            }
            for document in documents
        ]
    }
    assert reader.get("/worlds/showcase").status_code == 401
    for token in (GUEST, OWNER):
        listed = reader.get("/worlds/showcase", headers=_as(token))
        assert listed.status_code == 200, listed.text
        # Two workspaces read the same catalog: it names nothing of either.
        assert listed.json() == expected
        assert listed.headers["cache-control"] == "private, no-store"


def test_a_card_picture_is_served_by_its_own_digest_alone(reader):
    first, second = _locked_documents()[:2]
    digest = first["picture"]["sha256"]
    address = f"/worlds/showcase/{first['key']}/picture"
    picture = reader.get(address, params={"sha256": digest}, headers=_as(GUEST))
    assert picture.status_code == 200, picture.text
    assert picture.headers["content-type"] == first["picture"]["media_type"]
    kept = catalog.SHOWCASE_DIRECTORY / "pictures" / f"{digest}.jpg"
    assert picture.content == kept.read_bytes()
    assert hashlib.sha256(picture.content).hexdigest() == digest
    assert picture.headers["etag"] == f'"{digest}"'
    assert reader.get(address, params={"sha256": digest}).status_code == 401
    # Another world's picture is not this world's, and a key the installation does not serve is
    # refused as its copy is.
    other = reader.get(address, params={"sha256": second["picture"]["sha256"]}, headers=_as(GUEST))
    assert other.status_code == 404 and other.json()["code"] == "picture_not_found"
    unknown = reader.get(
        "/worlds/showcase/nowhere/picture", params={"sha256": digest}, headers=_as(GUEST)
    )
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_showcase_world"
