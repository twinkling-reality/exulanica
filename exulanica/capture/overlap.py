"""Whether a set of photographs overlaps, measured cheaply and in integers, before any run.

A reconstruction registers a photograph by matching it against the photographs it has already
placed, so a set rebuilds only when its photographs overlap each other in a chain that reaches
all of them. The retained measurement that decides this lane (2026-09-11, recorded in
``docs/capture-overlap-and-recovery-state.md``) is that overlap decides and count does not:
twelve photographs of one rock registered twelve of twelve at one spacing and seven of twelve at
a wider one. This module measures that overlap directly, with a descriptor cheap enough to run
before anything is spent.

Three decisions shape it.

**Standard library and Pillow, and nothing else.** numpy, torch, OpenCV and pycolmap are behind
extras, and in-process torch after COLMAP aborts the whole test process. A verdict whose purpose
is to be cheaper than the run it prevents must import cleanly on an instance that has none of
them, and ``tests/test_capture_overlap.py`` checks ``sys.modules`` in a fresh process to hold
that. Bytes become pixels only through ``exulanica.corpus.decode``, the repository's one decoder,
which applies the shared pixel budget and brings the core HEIF decoder with it.

**Integers from the decoded pixels onward.** ``exulanica.canonical`` refuses a float in a digest
input, and the verdict is a digest input. The luminance conversion, ``BoxBlur`` with an integer
radius, the rank filters and the channel operations all work on 8-bit integers, and the
descriptor bits, positions and counts derived from them are Python integers. The one step whose
coefficients Pillow computes in floating point is the ``BOX`` resize; they are fixed by the image
dimensions alone, so it is deterministic on one platform and library build. That it gives
identical bytes across platforms is not verified here and is recorded as such.

**A photograph that cannot be measured is named, never defaulted.** It carries a reason from a
closed list and it is not a node of the graph. A blank descriptor would be a photograph that
overlaps nothing, which is a claim about it, and the claim would be false.

The descriptor is a binary comparison descriptor at corners of a 256-pixel image: a four-way
minimum of directional differences finds corners (a straight edge has no difference along its own
direction), a fixed comparison pattern derived from SHA-256 describes each, and a pair of
photographs scores the number of mutual nearest matches that another match nearby agrees with.
A match that did not move is not counted, because a static background (the turntable under the
calibration rock) matches in every pair and carries no parallax a reconstruction could use.
"""

from __future__ import annotations

import hashlib
import re
import struct
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from PIL import Image, ImageChops, ImageFilter, ImageOps

from exulanica.canonical import round_half_down
from exulanica.corpus.decode import UNREADABLE, open_sensor

__all__ = [
    "DESCRIPTOR_PROFILE",
    "UNAVAILABLE_REASONS",
    "DescriptorParameters",
    "OverlapGraph",
    "OverlapMeasurement",
    "Photograph",
    "PhotographFeatures",
    "extract_features",
    "measure_overlap",
    "overlap_graph",
    "pair_score",
]

DESCRIPTOR_PROFILE: Final = "exulanica.capture-overlap-descriptor/v1"

UnavailableReason = Literal[
    "unreadable",
    "undecodable",
    "decompression_limit",
    "mirrored_orientation",
    "unsupported_pixel_format",
    "too_small",
]

#: Why a photograph was not measured. Closed, so a failure nobody anticipated raises rather than
#: arriving as a sentence the instruction vocabulary cannot read.
UNAVAILABLE_REASONS: Final[tuple[UnavailableReason, ...]] = (
    "unreadable",
    "undecodable",
    "decompression_limit",
    "mirrored_orientation",
    "unsupported_pixel_format",
    "too_small",
)

_ORIENTATION_TAG: Final = 0x0112
#: The four EXIF orientations that include a reflection. The ingest path refuses mirrored
#: originals, so this module does not invent a handling for them: it reports them.
_MIRRORED: Final = frozenset({2, 4, 5, 7})
#: Pixel formats whose conversion to 8-bit luminance is exact integer arithmetic in Pillow.
#: Sixteen-bit and floating point images are refused rather than squeezed through a scaling
#: nobody calibrated against.
_MODES: Final = frozenset(
    {"1", "L", "LA", "La", "P", "PA", "RGB", "RGBA", "RGBX", "RGBa", "CMYK", "YCbCr"}
)
#: The four directions whose minimum difference is the corner response. A straight edge has no
#: difference along itself, so the minimum over four directions is small on any edge and large
#: only where intensity changes every way at once.
_DIRECTIONS: Final = ((1, 0), (0, 1), (1, 1), (1, -1))
_NONZERO_TO_WHITE: Final = [0] + [255] * 255


@dataclass(frozen=True, slots=True)
class DescriptorParameters:
    """Every number the descriptor and the pair score depend on, recorded in the verdict.

    The defaults were selected on the pairwise angle curve of the calibration series (see the
    document named in the module docstring), not on the four measured capture outcomes.
    """

    long_side: int = 256
    keypoints: int = 160
    bits: int = 128
    radius: int = 8
    smoothing_radius: int = 1
    suppression_size: int = 5
    response_floor: int = 3
    max_hamming: int = 32
    ratio_percent: int = 80
    static_px: int = 1
    support_cell_px: int = 32
    support_min: int = 2

    def __post_init__(self) -> None:
        for name in self.__slots__:
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"descriptor parameter {name} must be a non-negative int")
        if self.suppression_size % 2 != 1 or self.support_min < 1 or self.bits < 1:
            raise ValueError("suppression_size is odd, support_min and bits are positive")

    def record(self) -> dict[str, int | str]:
        return {"profile": DESCRIPTOR_PROFILE} | {
            name: getattr(self, name) for name in self.__slots__
        }

    @property
    def margin(self) -> int:
        return self.radius + 2

    @property
    def minimum_side(self) -> int:
        """The shortest working side that still leaves an interior to find corners in."""
        return 2 * self.margin + self.suppression_size


@dataclass(frozen=True, slots=True)
class Photograph:
    """One photograph to measure: the caller's name for it and how to read its bytes.

    ``ref`` is what the verdict calls this photograph, and the set is ordered by it, so the verdict
    depends on which photographs were given and not on the order they were given in. A capture
    id is the ordinary ref; a file name is enough for a set that has not been admitted yet.
    """

    ref: str
    read: Callable[[], bytes] = field(repr=False)

    @classmethod
    def from_path(cls, ref: str, path: str | Path) -> Photograph:
        return cls(ref, Path(path).read_bytes)

    @classmethod
    def from_bytes(cls, ref: str, data: bytes) -> Photograph:
        payload = bytes(data)
        return cls(ref, lambda: payload)


@dataclass(frozen=True, slots=True)
class PhotographFeatures:
    """What was measured about one photograph, or the named reason nothing was.

    ``sha256`` names the exact bytes the features were derived from, read once, so the verdict
    cannot describe one file and cite another. It is None only when the bytes could not be read.
    """

    ref: str
    sha256: str | None
    state: Literal["measured", "unavailable"]
    reason: UnavailableReason | None
    width: int
    height: int
    keypoints: tuple[tuple[int, int, int], ...] = field(repr=False)

    def record(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "sha256": self.sha256,
            "state": self.state,
            "reason": self.reason,
            "width": self.width,
            "height": self.height,
            "keypoints": len(self.keypoints),
        }


def _unavailable(ref: str, sha256: str | None, reason: UnavailableReason) -> PhotographFeatures:
    return PhotographFeatures(ref, sha256, "unavailable", reason, 0, 0, ())


def _pattern(parameters: DescriptorParameters) -> tuple[tuple[int, int, int, int], ...]:
    """The fixed comparison pattern, derived from SHA-256 rather than from ``random``.

    Each entry compares two points of the patch around a corner. The seed string names the
    descriptor profile, so a second profile gets a second pattern and never silently shares one.
    """
    span = 2 * parameters.radius + 1
    out: list[tuple[int, int, int, int]] = []
    counter = 0
    while len(out) < parameters.bits:
        digest = hashlib.sha256(f"{DESCRIPTOR_PROFILE}/pattern/{counter}".encode()).digest()
        counter += 1
        for offset in range(0, 32, 4):
            ax, ay, bx, by = (
                value % span - parameters.radius for value in digest[offset : offset + 4]
            )
            if (ax, ay) != (bx, by) and len(out) < parameters.bits:
                out.append((ax, ay, bx, by))
    return tuple(out)


def _working_size(width: int, height: int, long_side: int) -> tuple[int, int]:
    if width >= height:
        return long_side, max(1, round_half_down(height * long_side, width))
    return max(1, round_half_down(width * long_side, height)), long_side


def _decode(data: bytes, parameters: DescriptorParameters) -> Image.Image | UnavailableReason:
    """Bounded pixels through the repository's one decoder, upright, grey and 256 pixels long.

    ``exulanica.corpus.decode.open_sensor`` is the only place a photograph becomes pixels, because
    Pillow's pixel budget and its decompression-bomb promotion are interpreter-global, and a second
    door would inherit whatever the last import set. So this never opens bytes itself. The frame
    is reduced to luminance and to the working size in its stored grid first, and the EXIF
    orientation is applied to the small copy, which carries the same metadata.
    """
    try:
        with open_sensor(data) as opened:
            orientation = opened.getexif().get(_ORIENTATION_TAG, 1)
            if orientation in _MIRRORED:
                return "mirrored_orientation"
            if opened.mode not in _MODES:
                return "unsupported_pixel_format"
            if max(opened.size) < parameters.long_side:
                return "too_small"
            stored = _working_size(*opened.size, parameters.long_side)
            grey = opened.convert("L")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "decompression_limit"
    except (*UNREADABLE, SyntaxError, EOFError, struct.error):
        return "undecodable"
    if min(stored) < parameters.minimum_side:
        return "too_small"
    if grey.size != stored:
        grey = grey.resize(stored, Image.Resampling.BOX)
    return ImageOps.exif_transpose(grey)


def extract_features(
    photograph: Photograph, parameters: DescriptorParameters
) -> PhotographFeatures:
    """Decode one photograph and describe its strongest corners, or name why it could not be."""
    try:
        data = photograph.read()
    except OSError:
        return _unavailable(photograph.ref, None, "unreadable")
    sha256 = hashlib.sha256(data).hexdigest()
    decoded = _decode(data, parameters)
    if isinstance(decoded, str):
        return _unavailable(photograph.ref, sha256, decoded)
    width, height = decoded.size
    smooth = (
        decoded.filter(ImageFilter.BoxBlur(parameters.smoothing_radius))
        if parameters.smoothing_radius
        else decoded
    )
    response = None
    for dx, dy in _DIRECTIONS:
        forward = ImageChops.offset(smooth, dx, dy)
        backward = ImageChops.offset(smooth, -dx, -dy)
        energy = ImageChops.difference(forward, backward).filter(ImageFilter.BoxBlur(1))
        response = energy if response is None else ImageChops.darker(response, energy)
    assert response is not None
    # Zero the border, so every surviving corner has a full patch around it and the offsets
    # above, which wrap at the edges, never reach a descriptor.
    margin = parameters.margin
    interior = Image.new("L", (width, height), 0)
    interior.paste(
        response.crop((margin, margin, width - margin, height - margin)), (margin, margin)
    )
    peaks = interior.filter(ImageFilter.MaxFilter(parameters.suppression_size))
    not_peak = ImageChops.difference(interior, peaks).point(_NONZERO_TO_WHITE)
    weak = interior.point([255 if value < parameters.response_floor else 0 for value in range(256)])
    rejected = ImageChops.lighter(not_peak, weak).tobytes()
    strength = interior.tobytes()
    # Strongest first, then raster order, so equal responses resolve the same way every time.
    corners = sorted(
        (-strength[match.start()], match.start()) for match in re.finditer(b"\x00", rejected)
    )[: parameters.keypoints]
    pixels = smooth.tobytes()
    offsets = [(ay * width + ax, by * width + bx) for ax, ay, bx, by in _pattern(parameters)]
    keypoints = []
    for _, position in corners:
        bits = 0
        for first, second in offsets:
            bits = (bits << 1) | (pixels[position + first] < pixels[position + second])
        keypoints.append((position % width, position // width, bits))
    return PhotographFeatures(
        photograph.ref, sha256, "measured", None, width, height, tuple(keypoints)
    )


def pair_score(
    first: PhotographFeatures, second: PhotographFeatures, parameters: DescriptorParameters
) -> int:
    """How many matches between two photographs moved together with another match nearby.

    A match is a mutual nearest neighbour within ``max_hamming`` whose distance is below
    ``ratio_percent`` of the next best. It counts when another counted match starts in the same
    ``support_cell_px`` cell of the first photograph and moved by the same cell-sized step, which
    is the cheapest geometric agreement that a pair of coincidences rarely reaches and a real
    overlap reaches everywhere. The whole matrix is computed rather than sampled: it is the
    dominant cost, and pruning it lost real edges when it was measured.
    """
    left, right = first.keypoints, second.keypoints
    if len(left) < 2 or len(right) < 2:
        return 0
    right_bits = [bits for _, _, bits in right]
    rows = [list(map(int.bit_count, map(bits.__xor__, right_bits))) for _, _, bits in left]
    column_best = [column.index(min(column)) for column in zip(*rows, strict=True)]
    cell = parameters.support_cell_px
    keys = []
    for index, row in enumerate(rows):
        best = min(row)
        if best > parameters.max_hamming:
            continue
        match = row.index(best)
        if column_best[match] != index:
            continue
        runner_up = min(row[:match] + row[match + 1 :])
        if best * 100 > runner_up * parameters.ratio_percent:
            continue
        x, y, _ = left[index]
        dx = right[match][0] - x
        dy = right[match][1] - y
        if abs(dx) <= parameters.static_px and abs(dy) <= parameters.static_px:
            continue
        keys.append((x // cell, y // cell, dx // cell, dy // cell))
    support = Counter(keys)
    return sum(1 for key in keys if support[key] >= parameters.support_min)


@dataclass(frozen=True, slots=True)
class OverlapMeasurement:
    """Every photograph's features and every measured pair's score, before any threshold.

    ``photographs`` is ordered by ref. ``nodes`` indexes the measured ones, and ``pair_scores`` is
    the upper triangle over ``nodes`` in row-major order. A photograph that could not be measured
    is in ``photographs`` and in no pair.
    """

    parameters: DescriptorParameters
    photographs: tuple[PhotographFeatures, ...]
    nodes: tuple[int, ...]
    pair_scores: tuple[int, ...]

    def score(self, first: int, second: int) -> int:
        """The score of two measured photographs, by their positions in ``photographs``."""
        a, b = sorted((self.nodes.index(first), self.nodes.index(second)))
        if a == b:
            raise ValueError("a photograph is not paired with itself")
        count = len(self.nodes)
        return self.pair_scores[a * count - a * (a + 1) // 2 + (b - a - 1)]

    def subset(self, refs: Iterable[str]) -> OverlapMeasurement:
        """The measurement this subset would have produced, without measuring anything again.

        Exact rather than approximate: a pair's score depends on its two photographs alone.
        """
        wanted = set(refs)
        positions = [i for i, item in enumerate(self.photographs) if item.ref in wanted]
        if len(positions) != len(wanted):
            raise KeyError(sorted(wanted - {item.ref for item in self.photographs}))
        kept = [i for i in positions if i in self.nodes]
        scores = tuple(
            self.score(kept[a], kept[b]) for a in range(len(kept)) for b in range(a + 1, len(kept))
        )
        renumber = {old: new for new, old in enumerate(positions)}
        return OverlapMeasurement(
            parameters=self.parameters,
            photographs=tuple(self.photographs[i] for i in positions),
            nodes=tuple(renumber[i] for i in kept),
            pair_scores=scores,
        )


def measure_overlap(
    photographs: Sequence[Photograph], parameters: DescriptorParameters
) -> OverlapMeasurement:
    """Measure every photograph once and every pair of measured photographs once."""
    refs = [photograph.ref for photograph in photographs]
    if any(type(ref) is not str or not ref for ref in refs):
        raise ValueError("every photograph needs a non-empty string ref")
    if len(set(refs)) != len(refs):
        raise ValueError("two photographs share a ref, so the set is not a set")
    ordered = sorted(photographs, key=lambda photograph: photograph.ref)
    features = tuple(extract_features(photograph, parameters) for photograph in ordered)
    nodes = tuple(i for i, item in enumerate(features) if item.state == "measured")
    scores = tuple(
        pair_score(features[nodes[a]], features[nodes[b]], parameters)
        for a in range(len(nodes))
        for b in range(a + 1, len(nodes))
    )
    return OverlapMeasurement(parameters, features, nodes, scores)


Structure = Literal["too_few", "scatter", "islands", "one_chain"]


@dataclass(frozen=True, slots=True)
class OverlapGraph:
    """The thresholded graph and the integers everything downstream reads.

    ``structure`` says whether the set is one chain, several islands or a scatter. Whether a
    chain comes back round to where it started is deliberately NOT here: two readings of that
    from the thresholded graph were measured against arcs of the calibration turntable whose
    extent is known, and they misread 3 and 2 of 22 with this decoder and 7 and 6 of 23 with an
    earlier draft-scaled decode. A chance edge between two far photographs is enough to make an
    open arc look closed, and a shape whose reading moves that much with a decode detail is not
    reported as established.
    """

    measurement: OverlapMeasurement
    edge_min_score: int
    edges: tuple[tuple[int, int], ...]
    components: tuple[tuple[int, ...], ...]
    structure: Structure

    @property
    def photograph_count(self) -> int:
        return len(self.measurement.photographs)

    @property
    def measured_count(self) -> int:
        return len(self.measurement.nodes)

    @property
    def largest_component(self) -> int:
        return len(self.components[0]) if self.components else 0

    @property
    def groups(self) -> int:
        """Components that contain at least one overlapping pair."""
        return sum(1 for component in self.components if len(component) > 1)

    @property
    def isolated(self) -> int:
        """Measured photographs that overlap no other photograph at all."""
        return sum(1 for component in self.components if len(component) == 1)

    def record(self) -> dict[str, object]:
        return {
            "edge_min_score": self.edge_min_score,
            "photographs": [item.record() for item in self.measurement.photographs],
            "nodes": list(self.measurement.nodes),
            "pair_scores": list(self.measurement.pair_scores),
            "edges": [list(edge) for edge in self.edges],
            "components": [list(component) for component in self.components],
            "photograph_count": self.photograph_count,
            "measured_count": self.measured_count,
            "edge_count": len(self.edges),
            "largest_component": self.largest_component,
            "groups": self.groups,
            "isolated": self.isolated,
            "structure": self.structure,
        }


def _components(nodes: Sequence[int], edges: Sequence[tuple[int, int]]) -> list[tuple[int, ...]]:
    parent = {node: node for node in nodes}

    def root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for a, b in edges:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, list[int]] = {}
    for node in nodes:
        groups.setdefault(root(node), []).append(node)
    return sorted((tuple(sorted(group)) for group in groups.values()), key=lambda g: (-len(g), g))


def overlap_graph(measurement: OverlapMeasurement, edge_min_score: int) -> OverlapGraph:
    """Threshold the pair scores into edges and read the graph's shape off them."""
    nodes = measurement.nodes
    count = len(nodes)
    edges = []
    cursor = 0
    for a in range(count):
        for b in range(a + 1, count):
            if measurement.pair_scores[cursor] >= edge_min_score:
                edges.append((nodes[a], nodes[b]))
            cursor += 1
    components = _components(nodes, edges)
    groups = sum(1 for component in components if len(component) > 1)
    structure: Structure
    if count < 2:
        structure = "too_few"
    elif not edges:
        structure = "scatter"
    elif groups > 1:
        structure = "islands"
    else:
        structure = "one_chain"
    return OverlapGraph(
        measurement=measurement,
        edge_min_score=edge_min_score,
        edges=tuple(edges),
        components=tuple(components),
        structure=structure,
    )
