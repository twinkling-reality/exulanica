"""A visitor's own copy of a showcase world is the world a sentence made, alive as it lived.

A showcase world's document holds what the sentence's draft decided and the made world's identity
and receipt digest (:mod:`exulanica.world.showcase_worlds`). ``POST /worlds/showcase/{showcase}``
makes it in the caller's own workspace with no model call; the control is the installation's own
world of the same document, whose receipt the copy must match byte for byte. The copy is brought to
life as the made world was (its society, the cast's models), once: asked again, the workspace's
copy is answered as the visitor left it.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.world import showcase_worlds as catalog
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.saved_entries import SavedWorldEntryRepository

from personal_world_support import STRANGER_TOKEN
from test_society_made_world import made as imported_made  # noqa: F401

CAST_MODEL = {
    "provider": "nebius_token_factory",
    "model_id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
}


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _document(key: str, world_id: str, receipt_sha256: str) -> dict:
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
    }


def _served(tmp_path, monkeypatch, document: dict) -> None:
    """Serve ``document`` alone, locked at its digest, as the installation's showcase catalog."""
    directory = tmp_path / "showcase"
    directory.mkdir(exist_ok=True)
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
    served = catalog.showcase_worlds(directory, lock)
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
    _served(tmp_path, monkeypatch, _document("seaside", world_id, digest))

    made_now = api.post("/worlds/showcase/seaside", {}, token=STRANGER_TOKEN)
    assert made_now.status_code == 201, made_now.text
    body = made_now.json()
    assert body["made"] is True and body["incomplete"] == []
    copy = body["entry"]
    assert copy["world_id"] == world_id and copy["entry_id"] != str(original.entry_id)
    stranger = api.client.app.state.services.tokens.session_for(STRANGER_TOKEN).workspace_id
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
        chosen = connection.execute(
            "select document from world_society_model_choice where workspace_id=%s and world_id=%s",
            (stranger, world_id),
        ).fetchall()
    # The same world, by its receipt; alive on the document's engine; its cast given its model.
    assert copied == digest
    assert society["engine_version"] == "exulanica-society/v5"
    assert [row["document"]["decider"]["model_id"] for row in chosen] == [CAST_MODEL["model_id"]]

    # Asked again: the copy the workspace holds, as it stands, dressed nothing more.
    again = api.post("/worlds/showcase/seaside", {}, token=STRANGER_TOKEN)
    assert again.status_code == 200, again.text
    assert again.json()["made"] is False and again.json()["entry"]["entry_id"] == copy["entry_id"]
    with api.database.session(stranger) as connection:
        count = connection.execute(
            "select count(*) n from world_society_model_choice where workspace_id=%s", (stranger,)
        ).fetchone()["n"]
    assert count == 1

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


def test_the_shipped_showcase_worlds_read():
    served = catalog.showcase_worlds()
    assert served, "the installation serves showcase worlds"
    for key, world in served.items():
        assert world.key == key and world.cast
