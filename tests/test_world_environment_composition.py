from __future__ import annotations

import uuid

from exulanica.canonical import canonical_json
from exulanica.world import (
    EnvironmentInstance,
    EnvironmentSelection,
    EnvironmentSourceBinding,
    ObjectOrigin,
    SourceAnchor,
    Transform,
    canonical_delta_document,
    delta_sha256,
)


def _instance(instance_id: str) -> EnvironmentInstance:
    source = EnvironmentSourceBinding(
        admission_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        render_asset_id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
        publication_id=None,
        source_sha256="1" * 64,
        source_receipt_sha256="2" * 64,
        render_sha256="3" * 64,
        render_receipt_sha256="4" * 64,
        index_sha256=None,
        index_receipt_sha256=None,
        publication_receipt_sha256=None,
        place_id=uuid.UUID("00000000-0000-0000-0000-000000000012"),
        frame={"name": "grid", "axis_order": ["east", "north", "height"]},
        bounds={
            "kind": "bbox",
            "frame_name": "grid",
            "coordinate_scale": 1000,
            "coordinates": [0, 0, 0, 10, 10, 10],
        },
        anchor=SourceAnchor("grid", 1000, (5, 5, 0)),
        selection=EnvironmentSelection("whole_asset"),
    )
    return EnvironmentInstance(
        instance_id=instance_id,
        source=source,
        region_id="region-a",
        transform=Transform(0, 0, 0, 0, 1000),
        origin=ObjectOrigin("authored", "fictional"),
    )


def test_no_environment_rows_preserve_the_exact_schema_v1_bytes_and_digest() -> None:
    document = canonical_delta_document((), ())
    assert canonical_json(document) == b'{"element_overrides":[],"objects":[],"schema_version":1}'
    assert delta_sha256((), ()) == (
        "b42557ee1fc8f83170fd24e88748dcbbcf5879fbc45f02df62b6c298b420f8fa"
    )


def test_environment_rows_select_schema_v2_and_sort_by_instance_id() -> None:
    document = canonical_delta_document(
        (), (), (_instance("environment:z"), _instance("environment:a"))
    )
    assert document["schema_version"] == 2
    assert [row["instance_id"] for row in document["environment_instances"]] == [
        "environment:a",
        "environment:z",
    ]
    assert delta_sha256((), (), (_instance("environment:z"), _instance("environment:a"))) == (
        delta_sha256((), (), (_instance("environment:a"), _instance("environment:z")))
    )


def test_availability_is_not_part_of_canonical_authored_state() -> None:
    available = _instance("environment:a")
    withdrawn = EnvironmentInstance(
        instance_id=available.instance_id,
        source=available.source,
        region_id=available.region_id,
        transform=available.transform,
        origin=available.origin,
        availability="withdrawn",
    )
    assert delta_sha256((), (), (available,)) == delta_sha256((), (), (withdrawn,))
