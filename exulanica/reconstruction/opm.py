"""Writing the ``.opm`` container, from Python, for the same decoder the fixtures feed.

``.opm`` had one producer, ``@exulanica/scene-synth``, which writes synthetic fixtures for the
renderer bake-off. This is the second, and it writes what a real photograph turned out to have
been looking at. Both are read by the same decoder in ``@exulanica/atlas-react``, which is the
point: the renderer cannot tell a synthetic fixture from a reconstruction, so a measurement taken
against the fixture is a measurement of the real path.

**This is OPM/2, and OPM/1 is refused rather than upgraded.** ADR-0010 D9: there is no
upgrade-on-read, because nothing in production held a file to upgrade when the version was cut.
The magic stays ``OPM1`` because it names the format and not the version, which is the same
arrangement glTF has; the version is in the header, where a reader that can read the header can
tell whether it can read the rest.

**The section table below is the container, and every offset and stride is computed from it.**
ADR-0010 D2: "Readers compute every offset and stride from the header rather than from a
constant, and a registered optional section is not a version bump. This is what makes the
header's generic shape true and is the only part of the change that prevents the next attribute
from being another version." Under OPM/1 exactly three sections were hardcoded in both
validators and in the decoder, and the stride was the literal 18 in the renderer binding, so the
header's own generic section list was a fiction. One table here, one in the decoder, and
:mod:`exulanica.reconstruction.validation` reads this one rather than restating it.

**The layout is contiguous on purpose, and that is not a detail.** The decoder reports
``planarContiguous`` and the PlayCanvas binding takes a zero-copy path when it is true and a
per-point CPU repack when it is false. PlayCanvas holds exactly one vertex buffer per mesh and
computes its own offsets for a tightly packed planar format, so it cannot be told to read three
attributes from three unrelated places. This writer aligns the START of the first section and
then packs the rest immediately after, so the file is always on the fast path. The TypeScript
writer's per-section sixteen-byte alignment is superseded by name in ADR-0010, for the same
reason: it was contiguous only when the point count happened to be a multiple of four.

The alignment that remains is the alignment that matters: the first section starts on a
sixteen-byte boundary, so a ``Float32Array`` view over it is legal; colour is bytes and needs
none; and ``tags`` begins sixteen bytes per point after that, which is even, so a
``Uint16Array`` view over it is legal too. Every one of those numbers is a consequence of the
table rather than a fact about it, so the writer asserts the property instead of restating the
arithmetic, and a section added in the wrong order fails here rather than in a browser.

**Two fields the synthetic writer has are absent here.** ``seed`` and ``sceneName`` describe a
generated world and there is no honest value for them over a photograph. They are omitted rather
than filled with a zero and an empty string, and the decoder does not read either.
"""

from __future__ import annotations

import json
from typing import Any, Final, Literal

from exulanica.reconstruction.pointmap import PointMap

__all__ = [
    "OPM_MAGIC",
    "OPM_SECTIONS",
    "OPM_VERSION",
    "SUPERSEDED_OPM_VERSION",
    "ColorAlpha",
    "OpmSection",
    "Viewpoint",
    "encode_opm",
]

OPM_MAGIC: Final = b"OPM1"
OPM_VERSION: Final = 2

#: The version this one replaces. Named rather than spelled ``1`` at the refusal site, because
#: the message a reader gets has to say which version it was handed and what to do about it.
SUPERSEDED_OPM_VERSION: Final = 1

_ALIGNMENT: Final = 16

#: What the colour buffer's alpha channel means, declared rather than inferred (ADR-0010 D5).
#:
#: ``support`` is coverage: how much surface one sample was asked to stand for, counted.
#: ``confidence`` is belief. They are not the same quantity and a renderer that sizes a sprite by
#: one of them must not be handed the other. Under OPM/1 both writers declared ``confidence`` and
#: this one had stopped meaning it, and the renderer told them apart by whether a statistics key
#: was present, which is a format flag nobody declared as one.
ColorAlpha = Literal["support", "confidence"]

_ELEMENT_BYTES: Final = {"float32": 4, "uint8": 1, "uint16": 2}


class OpmSection:
    """One planar section's declared shape. The stride is derived, never written down twice."""

    __slots__ = ("components", "name", "normalized", "type")

    def __init__(self, name: str, kind: str, components: int, *, normalized: bool) -> None:
        self.name = name
        self.type = kind
        self.components = components
        self.normalized = normalized

    @property
    def stride(self) -> int:
        """Bytes per point in this section."""
        return _ELEMENT_BYTES[self.type] * self.components

    @property
    def element_bytes(self) -> int:
        """The multiple a typed-array view over this section requires its byte offset to be."""
        return _ELEMENT_BYTES[self.type]


#: THE CONTAINER, in declaration order, which is also the order the bytes are packed in.
#:
#: ``tags`` replaces OPM/1's ``segment`` and is the only structural change (ADR-0010 D3). Two
#: uint16 channels: channel 0 is the segment id, unchanged in meaning and bounded by
#: :data:`~exulanica.reconstruction.pointmap.MAX_SEGMENT_ID`, and channel 1 is a flags word. Four
#: bytes rather than two because WebGPU rejects a vertex stream whose element size is not a
#: multiple of four, outright and silently in a release build, so the binding was already
#: widening the channel with a per-point CPU pass over every point in the corpus. The container
#: now stores what the engine had to be given.
OPM_SECTIONS: Final = (
    OpmSection("position", "float32", 3, normalized=False),
    OpmSection("color", "uint8", 4, normalized=True),
    OpmSection("tags", "uint16", 2, normalized=False),
)

#: The rung a per-image monocular point map stands for. Fixed at 3 by the container itself: a
#: point map is not a splat and writing a 1 here would be describing a file this is not.
_POINT_MAP_RUNG: Final = 3


class Viewpoint:
    """Where the camera stood, in the point map's own frame.

    Always the origin looking down -Z for a monocular reconstruction, because the frame IS the
    camera's. It is written out rather than left implicit because the renderer dollies to it on
    first arrival, and because everything not visible from here is honestly absent: a 2.5D shell
    has observed surfaces on one side only, and a viewer placed anywhere else is looking at the
    back of a photograph.

    ``aspect`` is the SOURCE camera's, and OPM/2 does not redefine it. The model's own working
    grid is a separate declared fact, ``modelImage``, per ADR-0010 D6.
    """

    __slots__ = ("aspect", "fov_y_degrees")

    def __init__(self, fov_y_degrees: float, aspect: float) -> None:
        self.fov_y_degrees = fov_y_degrees
        self.aspect = aspect

    def as_header(self) -> dict[str, Any]:
        return {
            "position": [0.0, 0.0, 0.0],
            "forward": [0.0, 0.0, -1.0],
            "up": [0.0, 1.0, 0.0],
            "fovYDeg": self.fov_y_degrees,
            "aspect": self.aspect,
        }


def _align(value: int) -> int:
    return -(-value // _ALIGNMENT) * _ALIGNMENT


def encode_opm(
    points: PointMap,
    *,
    generator: str,
    viewpoint: Viewpoint,
    source_size: tuple[int, int],
    model_size: tuple[int, int],
    color_alpha: ColorAlpha,
    metric: bool,
) -> bytes:
    """One point map to one self-contained file.

    ``metric`` is carried rather than assumed. A monocular model that recovers true scale writes
    True and a spatial question may be answered from the result; one that recovers shape up to an
    unknown scale writes False, and the island built from it is not metric, which is what makes
    `asMetricLocal` return null and the query path refuse with a stated reason instead of
    estimating a distance.

    ``model_size`` is the grid the points were unprojected from and ``source_size`` is the
    photograph. **Both, because neither can be recovered from the other**: a depth model works at
    a bounded resolution and rounds each dimension to whole pixels independently, so 1500x1000
    becomes 512x341 and the two aspects differ in the third decimal. The renderer needs the model
    grid to rebuild the image lattice for load-time tangent frames, and it needs the source
    frustum to place the camera; under OPM/1 only one of the two was stated and the other was
    guessed at from a point count.

    ``color_alpha`` has no default. A writer that did not say what it put in the alpha channel is
    the defect ADR-0010 D5 exists to close, and a default would let one not say by not thinking.
    """
    count = points.count
    sizes = tuple(count * section.stride for section in OPM_SECTIONS)

    def header_for(offsets: tuple[int, ...]) -> dict[str, Any]:
        low, high = points.bounds()
        return {
            "format": "exulanica-point-map",
            "version": OPM_VERSION,
            "generator": generator,
            "pointCount": count,
            "rung": _POINT_MAP_RUNG,
            "frame": "local",
            "up": "+Y",
            "forward": "-Z",
            "units": "metres",
            "metric": metric,
            "viewpoint": viewpoint.as_header(),
            "sourceImage": {"width": source_size[0], "height": source_size[1]},
            "modelImage": {"width": model_size[0], "height": model_size[1]},
            "bounds": {"min": list(low), "max": list(high)},
            "colorAlpha": color_alpha,
            # NO ``maxSegmentId`` FIELD, and its absence is ADR-0010 D3 read exactly. The bound
            # is a property of the format that both validators enforce, not a number a writer
            # gets to claim: a header field would either be enforced, letting a file declare a
            # range the shaders cannot index, or ignored, which is precisely "a header edit that
            # the renderer silently ignores". Widening the range is an edit to the semantic table
            # and to MAX_SEGMENT_ID together.
            "segments": [
                {"id": s.id, "name": s.name, "cls": s.cls} for s in points.segments
            ],
            "sections": [
                {
                    "name": section.name,
                    "type": section.type,
                    "components": section.components,
                    "normalized": section.normalized,
                    "byteOffset": offset,
                    "byteLength": size,
                }
                for section, offset, size in zip(OPM_SECTIONS, offsets, sizes, strict=True)
            ],
            "statistics": points.statistics,
        }

    # Two passes. The first measures a header carrying placeholder offsets; the second writes the
    # real ones into a region reserved to be large enough that they cannot move it. Reserving
    # rather than iterating, because a header that grew on the second pass would shift the very
    # offsets it was recording.
    probe = json.dumps(header_for((0,) * len(OPM_SECTIONS)), separators=(",", ":")).encode("utf-8")
    capacity = _align(len(probe) + 96)
    start = _align(8 + capacity)
    offsets: list[int] = []
    cursor = start
    for size in sizes:
        offsets.append(cursor)
        cursor += size
    # The packing is contiguous, so every section after the first inherits its alignment from
    # the strides in front of it. Checked rather than reasoned about: a reordering of the table
    # that broke a typed-array view would otherwise produce a file no decoder can open, and the
    # failure would land in a browser rather than here. `validate_opm` asks the same question of
    # the finished bytes, which is the check that stands in front of a durable artifact; this one
    # names the table entry that did it.
    for section, offset in zip(OPM_SECTIONS, offsets, strict=True):
        if offset % section.element_bytes:
            raise ValueError(
                f"the {section.name} section lands at byte {offset}, which no "
                f"{section.type} view may start at; the section order or a stride is wrong"
            )

    header = json.dumps(header_for(tuple(offsets)), separators=(",", ":")).encode("utf-8")
    if len(header) > capacity:
        raise ValueError("the .opm header exceeded its reserved capacity")

    out = bytearray(cursor)
    out[0:4] = OPM_MAGIC
    out[4:8] = len(header).to_bytes(4, "little")
    out[8 : 8 + len(header)] = header
    # Spaces rather than zeroes, so the JSON stays readable in a hex dump.
    for index in range(8 + len(header), start):
        out[index] = 0x20
    out[start:] = points.packed_bytes()
    return bytes(out)
