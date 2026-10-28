"""A visitor's own copy of a showcase world is the world a sentence made, alive as it lived.

A showcase world's document holds what the sentence's draft decided and the made world's identity
and receipt digest (:mod:`exulanica.world.showcase_worlds`). ``POST /worlds/showcase/{showcase}``
makes it in the caller's own workspace with no model call; the control is the installation's own
world of the same document, whose receipt the copy must match byte for byte. The copy is brought to
life as the made world was (its society, the cast's models), once, and opens playing; its card
painting is kept for it. Asked again, the workspace's copy is answered as the visitor left it.
A document whose painting's bytes or look's setting the host cannot hold is refused when the
catalog loads, never at a visitor's copy. A copy's painting is deleted with its world by G1's
identity trigger, which ``test_world_erasure_postgres.py`` holds for every painting row.
"""

from __future__ import annotations

import json
import shutil
import uuid

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.world import showcase_worlds as catalog
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.society_control_repository import open_session_receipt

from personal_world_support import STRANGER_TOKEN
from test_society_made_world import made as imported_made  # noqa: F401

CAST_MODEL = {
    "provider": "nebius_token_factory",
    "model_id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
}
#: A shipped showcase world, whose card painting and look the tests below lend a test world.
SHIPPED = json.loads((catalog.SHOWCASE_DIRECTORY / "mountain-town.v3.json").read_text())


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


def _catalog(tmp_path, document: dict, painting_bytes: bytes | None = None):
    """``document`` alone, locked at its digest, as a showcase catalog; its paintings' bytes the
    shipped ones unless ``painting_bytes`` stands in for them."""
    directory = tmp_path / "showcase"
    (directory / "paintings").mkdir(parents=True, exist_ok=True)
    for painting in document.get("paintings", []):
        name = f"{painting['sha256']}.jpg"
        if painting_bytes is None:
            shipped = catalog.SHOWCASE_DIRECTORY / "paintings" / name
            shutil.copyfile(shipped, directory / "paintings" / name)
        else:
            (directory / "paintings" / name).write_bytes(painting_bytes)
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


@pytest.mark.postgres
def test_a_visitor_s_copy_is_the_made_world_brought_to_life_once(made, tmp_path, monkeypatch):
    api = made
    owner = api.repository.workspace_id
    world_id = f"world:generated:{uuid.uuid4()}"
    # The made world: the installation's own, of the identity its draft fixed.
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
    painting = SHIPPED["paintings"][0]
    _served(tmp_path, monkeypatch, _document("seaside", world_id, digest, paintings=[painting]))

    made_now = api.post("/worlds/showcase/seaside", {}, token=STRANGER_TOKEN)
    assert made_now.status_code == 201, made_now.text
    body = made_now.json()
    assert body["made"] is True and body["incomplete"] == []
    copy = body["entry"]
    assert copy["world_id"] == world_id and copy["entry_id"] != str(original.entry_id)
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
    # playing from its first frame; its card painting kept, painted from the camera recorded.
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

    # Asked again: the copy the workspace holds, as it stands, dressed nothing more.
    again = api.post("/worlds/showcase/seaside", {}, token=STRANGER_TOKEN)
    assert again.status_code == 200, again.text
    assert again.json()["made"] is False and again.json()["entry"]["entry_id"] == copy["entry_id"]
    after = held()
    assert len(after["chosen"]) == 1 and len(after["paintings"]) == 1

    # A key the installation does not serve is answered alike for everyone.
    for token in (None, STRANGER_TOKEN):
        kwargs = {"token": token} if token else {}
        unknown = api.post("/worlds/showcase/nowhere", {}, **kwargs)
        assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_showcase_world"


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
        # Each wears its card painting, kept for every copy.
        assert world.paintings and all(painting.view == "orbit" for painting in world.paintings)
