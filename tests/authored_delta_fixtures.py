"""Fixed authored deltas of every schema version, for digest goldens and layout tests.

Every value is written out, so a digest over these is a function of the canonical document rule
and nothing else: no clock, no random id, no database.
"""

from __future__ import annotations

import uuid

from exulanica.world import (
    AuthoredObject,
    ElementOverride,
    EnvironmentInstance,
    EnvironmentSelection,
    EnvironmentSourceBinding,
    ObjectBehaviour,
    ObjectOrigin,
    PointMapInstance,
    PointMapModel,
    PointMapSourceBinding,
    SourceAnchor,
    Transform,
)

CUBE = "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9"


def _uuid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


OBJECTS = (
    AuthoredObject(
        object_id="object:lantern",
        asset_sha256=CUBE,
        region_id="region-a",
        transform=Transform(1_200, 0, -450, 785_398, 1_000),
        origin=ObjectOrigin("authored", "fictional"),
        behaviour=ObjectBehaviour(
            "motion.bounded-path",
            1,
            {"travel_mm": 2_000, "period_milliseconds": 4_000, "axis": "x", "easing": "smooth"},
        ),
    ),
    AuthoredObject(
        object_id="object:bench",
        asset_sha256=CUBE,
        region_id="region-b",
        transform=Transform(-3_000, 0, 2_000, 0, 2_000),
        origin=ObjectOrigin("authored", "personal"),
        removed=True,
    ),
)

OVERRIDES = (
    ElementOverride("element:region-b:root", suppressed=True),
    ElementOverride(
        "element:region-a:root", suppressed=False, transform=Transform(500, 0, 0, 1_570_796, 1_000)
    ),
)


def _environment_source(*, feature: bool) -> EnvironmentSourceBinding:
    return EnvironmentSourceBinding(
        admission_id=_uuid(0x10),
        render_asset_id=_uuid(0x11),
        publication_id=_uuid(0x13) if feature else None,
        source_sha256="1" * 64,
        source_receipt_sha256="2" * 64,
        render_sha256="3" * 64,
        render_receipt_sha256="4" * 64,
        index_sha256="5" * 64 if feature else None,
        index_receipt_sha256="6" * 64 if feature else None,
        publication_receipt_sha256="7" * 64 if feature else None,
        place_id=_uuid(0x12),
        frame={"name": "grid", "axis_order": ["east", "north", "height"]},
        bounds={
            "kind": "bbox",
            "frame_name": "grid",
            "coordinate_scale": 1000,
            "coordinates": [0, 0, 0, 100, 100, 100] if feature else [0, 0, 0, 10, 10, 10],
        },
        anchor=SourceAnchor("grid", 1000, (5, 5, 0)),
        selection=(
            EnvironmentSelection("feature", "a" * 32, 7)
            if feature
            else EnvironmentSelection("whole_asset")
        ),
    )


WHOLE_ASSET = EnvironmentInstance(
    instance_id="environment:corridor",
    source=_environment_source(feature=False),
    region_id="region-a",
    transform=Transform(0, 0, 0, 0, 1_000),
    origin=ObjectOrigin("authored", "fictional"),
)

FEATURE = EnvironmentInstance(
    instance_id="environment:building",
    source=_environment_source(feature=True),
    region_id="region-b",
    transform=Transform(4_000, 0, -1_000, 3_141_593, 500),
    origin=ObjectOrigin("authored", "fictional"),
    removed=True,
)

POINT_MAP = PointMapInstance(
    instance_id="point-map:kitchen",
    source=PointMapSourceBinding(
        entry_id=_uuid(0x20),
        attachment_id=_uuid(0x21),
        capture_id=_uuid(0x22),
        source_sha256="8" * 64,
        authorization_id=_uuid(0x23),
        authorization_evidence_sha256="9" * 64,
        screening_id=_uuid(0x24),
        screening_receipt_sha256="a" * 64,
        right_id=_uuid(0x25),
        right_receipt_sha256="b" * 64,
        model=PointMapModel("local", "depth", "test/plane-depth", "1" * 40, "local-process"),
        artifact_id=_uuid(0x26),
        point_map_sha256="c" * 64,
        byte_size=4_096,
        container="opm/2",
        stage_version=2,
        rung=3,
        declared_metric=False,
        declared_fov_y_microdegrees=60_000_000,
    ),
    region_id="region-a",
    transform=Transform(1_200, 0, -450, 785_398, 1_000),
    origin=ObjectOrigin("authored", "personal"),
)

#: Name -> (objects, element overrides, environment instances, point map instances).
DELTAS = {
    "empty": ((), (), (), ()),
    "v1": (OBJECTS, OVERRIDES, (), ()),
    "v2-whole-asset": (OBJECTS, OVERRIDES, (WHOLE_ASSET,), ()),
    "v2-feature": ((), (), (FEATURE,), ()),
    "v3-point-maps-only": ((), (), (), (POINT_MAP,)),
    "v3-with-environments": (OBJECTS, OVERRIDES, (FEATURE, WHOLE_ASSET), (POINT_MAP,)),
}
