"""Explicitly synthetic test definitions, never loaded by the application."""

import hashlib

from exulanica.world.character_appearance import CharacterFamily, CharacterRecipe


def family(**changes):
    data = dict(
        family_id="test-human/v1",
        family_revision="test-revision-1",
        schema_revision="test-schema-1",
        rig_id="test-rig",
        rig_revision="1",
        rig_sha256="1" * 64,
        producer="test-preparer",
        producer_revision="1",
        sources=[dict(reference="test:source", revision="test-source-1", content_sha256="2" * 64)],
        permitted_uses=["authored-avatar", "synthetic-inhabitant"],
        parameters=[
            dict(key="height", kind="integer", minimum=145, maximum=205, default=175),
            dict(key="clothing", kind="choice", choices=["shirt", "coat"], default="shirt"),
            dict(key="color", kind="color", default="#eeeeee"),
        ],
    )
    data.update(changes)
    return CharacterFamily.model_validate(data)


def recipe(definition=None, **changes):
    definition = definition or family()
    data = dict(
        family_id=definition.family_id,
        family_sha256=definition.sha256,
        parameters={p.key: p.default for p in definition.parameters},
        seed=0,
    )
    data.update(changes)
    return CharacterRecipe.model_validate(data)


def sha(data):
    return hashlib.sha256(data).hexdigest()
