"""The capture plan: which camera stood where, when, and what the file will claim about it.

Everything a generated photograph will assert about itself is decided here and recorded, so the
manifest the generator writes is the plan rather than a description written after the fact. That
matters for `docs/evaluation-methodology.md`: a ground truth derived from the same run that
produced the images cannot drift from them.

Four properties are arranged deliberately rather than left to chance, because each one is a code
path the ingest pipeline has and that a tidy corpus would never reach.

*   **Two visits to one place, months apart.** Scene grouping clusters on time and position, so a
    place photographed twice must produce two groups and not one. A corpus visited once cannot
    tell a working clusterer from one that returns everything.
*   **A device that writes no UTC offset.** `exulanica/ingest/exif.py` carries a 26-hour
    uncertainty for exactly this case and it is the common one in real libraries. Half this
    corpus is shot on a device that writes `OffsetTimeOriginal` and half on one that does not.
*   **Photographs with no GPS at all.** The indoor trip has no fix, which is what actually
    happens indoors, and it forces grouping to fall back to time alone.
*   **Orientations including mirrored ones.** Four of the eight EXIF orientation values include a
    flip, and `media_track.rotation` cannot express one. The corpus contains mirrored frames so
    that the normalisation path is exercised rather than assumed.

**The coordinates are fabricated.** They are internally consistent, far enough apart to cluster
separately and close enough together to be one city, and they point at no place anybody has been.
Nothing in this package should ever be read as a record of somewhere real.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from dataclasses import dataclass
from typing import Final

from exulanica.corpus.render import Camera, Vec3
from exulanica.corpus.world import PLACES

__all__ = ["DEVICES", "TRIPS", "Device", "FramePlan", "Trip", "build_plan"]

#: Landscape and portrait display sizes. The sensor image may be the other way round; see
#: `photograph.py`, which writes sensor pixels and the orientation tag that uprights them.
_LANDSCAPE: Final = (1600, 1200)
_PORTRAIT: Final = (1200, 1600)

#: Roughly a metre of jitter, in ten-millionths of a degree. Latitude is uniform; longitude is
#: not, but at these latitudes the difference is well inside the error a consumer fix carries
#: anyway, and the corpus is not claiming survey accuracy.
_METRE_E7: Final = 90


@dataclass(frozen=True, slots=True)
class Device:
    """A camera, as the EXIF will describe it.

    The make and model are deliberately not a real manufacturer's. A synthetic file carrying
    `Apple` and `iPhone 15` would be a fabricated record of a device that exists, and this corpus
    has to be recognisable as synthetic from the bytes alone rather than from where it is stored.
    """

    key: str
    make: str
    model: str
    writes_offset: bool
    writes_subsecond: bool
    horizontal_fov_degrees: float


DEVICES: dict[str, Device] = {
    "a": Device(
        key="a",
        make="Exulanica",
        model="Synthetic Camera A",
        writes_offset=True,
        writes_subsecond=True,
        horizontal_fov_degrees=66.0,
    ),
    # No offset tag and no sub-second tag: the common older-device case, and the one that makes
    # the recorded instant uncertain to 26 hours rather than to one second.
    "b": Device(
        key="b",
        make="Exulanica",
        model="Synthetic Camera B",
        writes_offset=False,
        writes_subsecond=False,
        horizontal_fov_degrees=58.0,
    ),
}


@dataclass(frozen=True, slots=True)
class Trip:
    """One visit to one place: a device, a start time, a position, and what was carried."""

    key: str
    place_key: str
    device_key: str
    local_start: dt.datetime
    utc_offset: dt.timedelta
    gps_centroid_e7: tuple[int, int] | None
    altitude_mm: int | None
    subjects: tuple[str, ...]


#: Five visits to three places. The courtyard and the harbour are each visited twice, five months
#: apart and on different devices, which is what gives continuity two separate captures of one
#: place to recognise. Every subject appears in at least two places and at least two visits.
TRIPS: tuple[Trip, ...] = (
    Trip(
        key="courtyard-spring",
        place_key="courtyard",
        device_key="a",
        local_start=dt.datetime(2026, 4, 18, 10, 14, 6),
        utc_offset=dt.timedelta(hours=1),
        gps_centroid_e7=(514512340, -1234560),
        altitude_mm=24000,
        subjects=("satchel", "thermos"),
    ),
    Trip(
        key="harbour-spring",
        place_key="harbour",
        device_key="a",
        local_start=dt.datetime(2026, 4, 18, 15, 42, 51),
        utc_offset=dt.timedelta(hours=1),
        gps_centroid_e7=(514398120, -1471880),
        altitude_mm=6000,
        subjects=("thermos",),
    ),
    # Indoors, so no fix. Grouping has only the clock for this one, which is the point of it.
    Trip(
        key="kitchen-spring",
        place_key="kitchen",
        device_key="a",
        local_start=dt.datetime(2026, 4, 18, 19, 20, 33),
        utc_offset=dt.timedelta(hours=1),
        gps_centroid_e7=None,
        altitude_mm=None,
        subjects=("satchel", "lantern"),
    ),
    Trip(
        key="courtyard-autumn",
        place_key="courtyard",
        device_key="b",
        local_start=dt.datetime(2026, 9, 26, 14, 5, 12),
        utc_offset=dt.timedelta(hours=1),
        gps_centroid_e7=(514512340, -1234560),
        altitude_mm=24000,
        subjects=("satchel", "lantern"),
    ),
    Trip(
        key="harbour-autumn",
        place_key="harbour",
        device_key="b",
        local_start=dt.datetime(2026, 9, 27, 9, 31, 40),
        utc_offset=dt.timedelta(hours=1),
        gps_centroid_e7=(514398120, -1471880),
        altitude_mm=6000,
        subjects=("thermos", "lantern"),
    ),
)


@dataclass(frozen=True, slots=True)
class FramePlan:
    """One photograph, entirely decided before a pixel is drawn.

    `utc_instant` is the truth, and it is in the manifest rather than in the file. When the
    device writes no offset tag, the file records a local time with no zone and the pipeline is
    correct to treat the instant as unknown within 26 hours; an evaluation that wanted to score
    that has to be told the answer separately, which is what this field is for.
    """

    trip_key: str
    place_key: str
    ordinal: int
    filename: str
    camera: Camera
    #: subject key, where it was put, and how it was turned. Ground truth for continuity.
    subject_placements: tuple[tuple[str, Vec3, float], ...]
    device_key: str
    local_time: dt.datetime
    subsecond: int | None
    #: Written into the file only when the device writes one. `None` means the file says nothing.
    written_offset: dt.timedelta | None
    utc_instant: dt.datetime
    gps_e7: tuple[int, int] | None
    altitude_mm: int | None
    exif_orientation: int
    display_size: tuple[int, int]
    grain_seed: int


#: Orientations forced somewhere in the corpus regardless of what chance would have produced.
#: Two of the three include a mirror, which is the half of the orientation table that
#: `media_track.rotation` cannot express and that a corpus of upright frames never reaches.
_FORCED_ORIENTATIONS: Final[dict[int, int]] = {2: 2, 5: 7, 11: 3}


def _orientation_for(ordinal: int, portrait: bool, rng: random.Random) -> int:
    """What the file will claim, given what the picture actually is.

    A portrait photograph is a landscape sensor readout plus a quarter turn, which is what a
    phone does and why the tag exists at all. Forced values override, so the mirrored branch is
    present in every generated corpus rather than only in most of them.
    """
    if ordinal in _FORCED_ORIENTATIONS:
        return _FORCED_ORIENTATIONS[ordinal]
    if portrait:
        return rng.choice((6, 8))
    return 1


def build_plan(*, seed: int, frames_per_trip: int) -> list[FramePlan]:
    """Every frame in the corpus, deterministically.

    One `Random` for the whole run rather than one per trip: the sequence is consumed in a fixed
    order, so the same seed produces the same corpus, and a different seed produces a different
    one all the way through rather than five correlated variations.
    """
    if frames_per_trip < 3:
        raise ValueError("a trip needs at least three frames to overlap at all")
    rng = random.Random(seed)
    frames: list[FramePlan] = []

    for trip in TRIPS:
        place = PLACES[trip.place_key]
        device = DEVICES[trip.device_key]
        clock = trip.local_start
        # The arc the camera walks. Consecutive frames overlap because consecutive angles are
        # close, which is the property reconstruction needs and a scattered camera would not have.
        sweep = 250.0 if not place.indoors else 130.0
        start_angle = rng.uniform(0.0, 360.0)
        # Decided once per visit. A subject that moved between frames of one visit would break
        # the property the whole corpus rests on: that every frame of a trip is a projection of
        # ONE arrangement. It is also what makes the frames genuinely reconstructable.
        placements = tuple(
            (
                key,
                place.subject_positions[index % len(place.subject_positions)],
                rng.uniform(0.0, 360.0),
            )
            for index, key in enumerate(trip.subjects)
        )

        for ordinal in range(frames_per_trip):
            fraction = ordinal / max(1, frames_per_trip - 1)
            angle = start_angle + sweep * fraction + rng.uniform(-4.0, 4.0)
            radius = place.orbit_radius * rng.uniform(0.82, 1.18)
            radians = math.radians(angle)
            eye = (
                place.orbit_centre[0] + radius * math.cos(radians),
                place.orbit_centre[1] + radius * math.sin(radians),
                place.eye_height + rng.uniform(-0.10, 0.14),
            )
            target = (
                place.orbit_centre[0] + rng.uniform(-0.7, 0.7),
                place.orbit_centre[1] + rng.uniform(-0.7, 0.7),
                place.orbit_centre[2] + rng.uniform(-0.25, 0.25),
            )

            portrait = rng.random() < 0.28
            orientation = _orientation_for(ordinal, portrait, rng)
            size = _PORTRAIT if portrait else _LANDSCAPE

            clock = clock + dt.timedelta(seconds=rng.randint(7, 95))
            subsecond = rng.randint(0, 99) if device.writes_subsecond else None
            frames.append(
                FramePlan(
                    trip_key=trip.key,
                    place_key=trip.place_key,
                    ordinal=ordinal,
                    filename=f"{trip.key}-{ordinal:03d}.jpg",
                    camera=Camera(
                        eye=eye,
                        target=target,
                        horizontal_fov_degrees=device.horizontal_fov_degrees,
                        width=size[0],
                        height=size[1],
                    ),
                    subject_placements=placements,
                    device_key=device.key,
                    local_time=clock,
                    subsecond=subsecond,
                    written_offset=trip.utc_offset if device.writes_offset else None,
                    utc_instant=(clock - trip.utc_offset).replace(tzinfo=dt.UTC),
                    gps_e7=_jitter(trip.gps_centroid_e7, rng),
                    altitude_mm=trip.altitude_mm,
                    exif_orientation=orientation,
                    display_size=size,
                    grain_seed=rng.randrange(2**31),
                )
            )
    return frames


def _jitter(centroid: tuple[int, int] | None, rng: random.Random) -> tuple[int, int] | None:
    """A fix a few metres from the centroid, or no fix at all.

    Not a constant repeated per frame: a cluster whose members all share one coordinate would let
    a grouping radius of zero look correct.
    """
    if centroid is None:
        return None
    return (
        centroid[0] + rng.randint(-9 * _METRE_E7, 9 * _METRE_E7),
        centroid[1] + rng.randint(-9 * _METRE_E7, 9 * _METRE_E7),
    )
