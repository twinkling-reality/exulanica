"""EXIF extraction, and the orientation decision that the rest of the pipeline depends on.

## The orientation problem, stated as it actually occurs

Phone cameras write the sensor readout unrotated and record how to display it in a single EXIF
tag. A pipeline that decodes pixels and ignores that tag processes a portrait photograph
sideways: the vision model describes a rotated scene, and every bounding box it returns lands
on the wrong axis. This is an observed property of real photograph corpora, not a hypothetical.

There are eight orientation values, and **four of them include a mirror**. That is the part
that breaks a naive fix. ``media_track.rotation`` is constrained to ``0 | 90 | 180 | 270`` and
cannot express a flip, and ``docs/domain-and-evidence-model.md`` section 1.5 records the gap as
OPEN and blocking for the v1 freeze, because ``region.display`` is inside ``span_digest``: a
region placed on the wrong side of a mirrored image would be baked into a permanent citation
address.

The document names exactly two acceptable resolutions. **This module takes the second one:
normalise pixels at ingest, and record that it happened.**

Concretely:

*   The rendition handed to any model, and the display space every region is normalised
    against, is the **upright** image. Orientation is applied once, at ingest, by the same
    transform a correct viewer would apply.
*   ``DisplayGeometry`` therefore carries ``rotation = 0`` for photographs, because display
    space *is* the upright pixel space. A region means the same thing to every reader forever,
    with no second transform to apply and no flip to smuggle into a field that cannot hold one.
*   What was applied is recorded outside the digest, on the track row: the EXIF value, the
    clockwise rotation, whether a mirror was applied, and the flag that says normalisation
    happened at ingest. ``probe_json`` keeps the raw tag verbatim.

The alternative branch, widening the column to eight values, was not taken because it leaves
every downstream consumer responsible for applying a transform correctly, and a consumer that
forgets produces a wrong citation rather than a wrong-looking picture.

## Wall clock

EXIF timestamps are not exact and this module never pretends otherwise. It emits a clock anchor
carrying an explicit ``uncertainty_ms``, and the uncertainty is **representational only**:
the resolution of the tag, and the size of the unknown when the file records no UTC offset.
Device clock drift is not included, because it has not been measured. Recording a number that
includes an unmeasured term would be worse than recording one that is honestly incomplete.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from PIL import Image, ImageOps

from exulanica.canonical import round_half_down
from exulanica.errors import ExulanicaError

__all__ = [
    "UNKNOWN_OFFSET_UNCERTAINTY_MS",
    "ClockEstimate",
    "ExifFacts",
    "GpsFix",
    "Orientation",
    "extract_exif_facts",
    "normalise_orientation",
]


class UnreadableImageError(ExulanicaError):
    """The file is not an image this pipeline can decode."""


#: EXIF Orientation, expressed as "mirror horizontally, then rotate this many degrees
#: clockwise". Verified against ``PIL.ImageOps.exif_transpose`` for all eight values by
#: ``tests/test_exif_orientation.py``, rather than trusted from the algebra.
_ORIENTATION_TRANSFORM: Final[dict[int, tuple[bool, int]]] = {
    1: (False, 0),
    2: (True, 0),
    3: (False, 180),
    4: (True, 180),
    5: (True, 270),
    6: (False, 90),
    7: (True, 90),
    8: (False, 270),
}

#: A tag with whole-second resolution cannot place an event closer than one second.
_SECOND_UNCERTAINTY_MS: Final = 1000
#: SubSecTimeOriginal carries fractional seconds; two digits is the common case.
_SUBSECOND_UNCERTAINTY_MS: Final = 10
#: No OffsetTimeOriginal and no GPS time means the timestamp is local with an unknown zone.
#: Real UTC offsets run from -12:00 to +14:00, so the instant is unknown within that span. The
#: number is carried rather than rounded away, because rounding it away is how a photograph
#: ends up confidently dated to the wrong day.
UNKNOWN_OFFSET_UNCERTAINTY_MS: Final = 26 * 60 * 60 * 1000

_ORIENTATION_TAG: Final = 0x0112
_MAKE_TAG: Final = 0x010F
_MODEL_TAG: Final = 0x0110
_SOFTWARE_TAG: Final = 0x0131
_DATETIME_TAG: Final = 0x0132
_EXIF_IFD: Final = 0x8769
_GPS_IFD: Final = 0x8825
_DATETIME_ORIGINAL: Final = 0x9003
_DATETIME_DIGITIZED: Final = 0x9004
_OFFSET_TIME_ORIGINAL: Final = 0x9011
_OFFSET_TIME: Final = 0x9010
_SUBSEC_TIME_ORIGINAL: Final = 0x9291


@dataclass(frozen=True, slots=True)
class Orientation:
    """What the file said, and what was done about it."""

    exif_value: int
    rotation_degrees: int
    mirrored: bool

    @property
    def swaps_axes(self) -> bool:
        return self.rotation_degrees in (90, 270)

    def as_probe(self) -> dict[str, Any]:
        return {
            "exif_orientation": self.exif_value,
            "rotation_degrees_clockwise": self.rotation_degrees,
            "mirrored": self.mirrored,
            # The load-bearing flag. Without it, a later reader cannot tell whether a region is
            # in sensor space or display space, and the two differ by a right angle.
            "normalised_at_ingest": True,
        }


@dataclass(frozen=True, slots=True)
class ClockEstimate:
    """A wall-clock anchor with its uncertainty attached, never a bare timestamp."""

    utc: dt.datetime
    source: str
    uncertainty_ms: int
    assumed_utc: bool

    def __post_init__(self) -> None:
        if self.utc.tzinfo is None:
            raise ValueError("a clock estimate must be timezone aware")
        if self.source not in {
            "container_creation_time",
            "device_rtc",
            "gps",
            "ntp",
            "user_stated",
            "inferred",
        }:
            raise ValueError(f"unknown clock anchor source {self.source!r}")


@dataclass(frozen=True, slots=True)
class GpsFix:
    """A position in integer ten-millionths of a degree, so it never becomes a float.

    1e-7 degrees is about 11 millimetres, far below any consumer GPS fix, and an integer has
    one representation in every JSON writer that will ever read this record.
    """

    lat_e7: int
    lon_e7: int
    altitude_mm: int | None = None
    horizontal_error_mm: int | None = None

    def __post_init__(self) -> None:
        if not -900_000_000 <= self.lat_e7 <= 900_000_000:
            raise ValueError(f"latitude out of range: {self.lat_e7}")
        if not -1_800_000_000 <= self.lon_e7 <= 1_800_000_000:
            raise ValueError(f"longitude out of range: {self.lon_e7}")

    @staticmethod
    def _decimal_text(value_e7: int) -> str:
        sign = "-" if value_e7 < 0 else ""
        whole, frac = divmod(abs(value_e7), 10_000_000)
        return f"{sign}{whole}.{frac:07d}"

    @property
    def lat_text(self) -> str:
        return self._decimal_text(self.lat_e7)

    @property
    def lon_text(self) -> str:
        return self._decimal_text(self.lon_e7)

    def as_object_value(self) -> dict[str, Any]:
        """The ``gps_position_is`` object value: exact integers plus their decimal rendering."""
        payload: dict[str, Any] = {
            "lat": self.lat_text,
            "lon": self.lon_text,
            "lat_e7": self.lat_e7,
            "lon_e7": self.lon_e7,
        }
        if self.altitude_mm is not None:
            payload["altitude_mm"] = self.altitude_mm
        if self.horizontal_error_mm is not None:
            payload["horizontal_error_mm"] = self.horizontal_error_mm
        return payload


@dataclass(frozen=True, slots=True)
class ExifFacts:
    """Everything the bytes themselves say. This is the whole of the ``capture`` class.

    Every field here is a deterministic property of the file. Nothing in it is a model output,
    and nothing in it may be presented as one. A photograph says its size, its device, its
    recorded time and its recorded position, and nothing else: everything else a photograph
    "says" is inference.
    """

    orientation: Orientation
    coded_width: int
    coded_height: int
    display_width: int
    display_height: int
    media_type: str
    codec: str
    camera_make: str | None
    camera_model: str | None
    software: str | None
    clock: ClockEstimate | None
    gps: GpsFix | None
    raw_tags: dict[str, Any]

    @property
    def device_id(self) -> str | None:
        """A human-meaningful device label, or None. Not an identifier the device supplied."""
        parts = [p for p in (self.camera_make, self.camera_model) if p]
        return " ".join(parts) if parts else None

    def as_probe_json(self) -> dict[str, Any]:
        """The verbatim-plus-derived record stored on ``media_track.probe_json``.

        Contains no floats: it is hashed as an artifact, and no two JSON writers agree on how
        to render a float.
        """
        probe: dict[str, Any] = {
            "orientation": self.orientation.as_probe(),
            "coded": {"w": self.coded_width, "h": self.coded_height},
            "display": {"w": self.display_width, "h": self.display_height},
            "media_type": self.media_type,
            "codec": self.codec,
            "exif": self.raw_tags,
        }
        if self.camera_make or self.camera_model:
            probe["device"] = {"make": self.camera_make, "model": self.camera_model}
        if self.software:
            probe["software"] = self.software
        if self.clock is not None:
            probe["clock"] = {
                "utc": self.clock.utc.isoformat(),
                "source": self.clock.source,
                "uncertainty_ms": self.clock.uncertainty_ms,
                "assumed_utc": self.clock.assumed_utc,
            }
        if self.gps is not None:
            probe["gps"] = self.gps.as_object_value()
        return probe


def normalise_orientation(image: Image.Image) -> tuple[Image.Image, Orientation]:
    """Return the upright image and a record of the transform applied.

    The transform itself is ``PIL.ImageOps.exif_transpose``, which is the reference
    implementation of the eight-value table. The table in this module is used only to *record*
    what happened, and a test pins the two together so a divergence is a test failure rather
    than a class of silently rotated citations.
    """
    raw = image.getexif().get(_ORIENTATION_TAG, 1)
    value = raw if isinstance(raw, int) and raw in _ORIENTATION_TRANSFORM else 1
    mirrored, rotation = _ORIENTATION_TRANSFORM[value]
    upright = ImageOps.exif_transpose(image)
    if upright is None:  # pragma: no cover - exif_transpose returns a copy or the original
        upright = image
    return upright, Orientation(exif_value=value, rotation_degrees=rotation, mirrored=mirrored)


def _text(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned or None


def _jsonable(value: Any) -> Any:
    """Make an EXIF value canonical-JSON safe. No floats, ever.

    Rationals become ``"num/den"`` strings rather than decimals: the numerator and denominator
    are what the file actually contains, and reducing them to a decimal loses the distinction
    between a value and its rounding.
    """
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, float):
        return str(Fraction(value).limit_denominator(1_000_000))
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()[:512]}
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if numerator is not None and denominator is not None:
        return f"{int(numerator)}/{int(denominator)}"
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _rational(value: Any) -> Fraction | None:
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if numerator is not None and denominator is not None and int(denominator) != 0:
        return Fraction(int(numerator), int(denominator))
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(value)
    return None


def _degrees_e7(components: Any, ref: Any) -> int | None:
    """Convert an EXIF ``(deg, min, sec)`` triple to signed ten-millionths of a degree."""
    if not isinstance(components, tuple | list) or len(components) != 3:
        return None
    parts = [_rational(component) for component in components]
    degrees, minutes, seconds = parts  # type: ignore[misc]
    if degrees is None or minutes is None or seconds is None:
        return None
    total = degrees + minutes / 60 + seconds / 3600
    scaled = total * 10_000_000
    value = round_half_down(scaled.numerator, scaled.denominator)
    reference = (_text(ref) or "").upper()
    if reference in {"S", "W"}:
        value = -value
    return value


def _parse_exif_datetime(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    cleaned = text.strip().replace("/", ":")
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            return dt.datetime.strptime(cleaned, pattern)
        except ValueError:
            continue
    return None


def _parse_offset(text: str | None) -> dt.timezone | None:
    if not text or len(text) < 6 or text[0] not in "+-":
        return None
    try:
        hours = int(text[1:3])
        minutes = int(text[4:6])
    except ValueError:
        return None
    delta = dt.timedelta(hours=hours, minutes=minutes)
    return dt.timezone(-delta if text[0] == "-" else delta)


def _gps_utc(gps_ifd: dict[int, Any]) -> dt.datetime | None:
    """GPS time is genuinely UTC, which is why it outranks the camera's own clock."""
    date_text = _text(gps_ifd.get(29))
    time_parts = gps_ifd.get(7)
    if not date_text or not isinstance(time_parts, tuple | list) or len(time_parts) != 3:
        return None
    try:
        day = dt.datetime.strptime(date_text.strip().replace("-", ":"), "%Y:%m:%d")
    except ValueError:
        return None
    values = [_rational(part) for part in time_parts]
    if any(value is None for value in values):
        return None
    hours, minutes, seconds = (int(value) for value in values)  # type: ignore[arg-type]
    if not (0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 62):
        return None
    return day.replace(hour=hours, minute=minutes, second=min(seconds, 59), tzinfo=dt.UTC)


def _clock_estimate(
    exif_ifd: dict[int, Any], base: dict[int, Any], gps_ifd: dict[int, Any]
) -> ClockEstimate | None:
    gps_time = _gps_utc(gps_ifd)
    if gps_time is not None:
        return ClockEstimate(
            utc=gps_time,
            source="gps",
            uncertainty_ms=_SECOND_UNCERTAINTY_MS,
            assumed_utc=False,
        )
    naive = (
        _parse_exif_datetime(_text(exif_ifd.get(_DATETIME_ORIGINAL)))
        or _parse_exif_datetime(_text(exif_ifd.get(_DATETIME_DIGITIZED)))
        or _parse_exif_datetime(_text(base.get(_DATETIME_TAG)))
    )
    if naive is None:
        return None
    subsec = _text(exif_ifd.get(_SUBSEC_TIME_ORIGINAL))
    resolution = _SUBSECOND_UNCERTAINTY_MS if subsec else _SECOND_UNCERTAINTY_MS
    offset = _parse_offset(_text(exif_ifd.get(_OFFSET_TIME_ORIGINAL))) or _parse_offset(
        _text(exif_ifd.get(_OFFSET_TIME))
    )
    if offset is not None:
        return ClockEstimate(
            utc=naive.replace(tzinfo=offset).astimezone(dt.UTC),
            source="container_creation_time",
            uncertainty_ms=resolution,
            assumed_utc=False,
        )
    # No zone in the file. The instant is read as UTC because something must be stored, and the
    # size of that assumption is carried in uncertainty_ms rather than hidden.
    return ClockEstimate(
        utc=naive.replace(tzinfo=dt.UTC),
        source="container_creation_time",
        uncertainty_ms=UNKNOWN_OFFSET_UNCERTAINTY_MS,
        assumed_utc=True,
    )


_MEDIA_TYPES: Final[dict[str, str]] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "HEIF": "image/heif",
    "GIF": "image/gif",
}


def extract_exif_facts(image: Image.Image) -> tuple[Image.Image, ExifFacts]:
    """Read every capture-supported fact from an open image, and return it upright.

    The image is returned alongside the facts because orientation normalisation happens here,
    once, and every later stage must work from the upright pixels rather than repeat the
    decision.
    """
    coded_width, coded_height = image.size
    upright, orientation = normalise_orientation(image)
    exif = image.getexif()
    base = {int(k): v for k, v in exif.items()}
    try:
        exif_ifd = {int(k): v for k, v in exif.get_ifd(_EXIF_IFD).items()}
    except (KeyError, ValueError, OSError):  # pragma: no cover - malformed IFD pointer
        exif_ifd = {}
    try:
        gps_ifd = {int(k): v for k, v in exif.get_ifd(_GPS_IFD).items()}
    except (KeyError, ValueError, OSError):  # pragma: no cover - malformed IFD pointer
        gps_ifd = {}

    latitude = _degrees_e7(gps_ifd.get(2), gps_ifd.get(1))
    longitude = _degrees_e7(gps_ifd.get(4), gps_ifd.get(3))
    gps: GpsFix | None = None
    if latitude is not None and longitude is not None:
        altitude = _rational(gps_ifd.get(6))
        altitude_mm = None
        if altitude is not None:
            scaled = altitude * 1000
            altitude_mm = round_half_down(scaled.numerator, scaled.denominator)
            if gps_ifd.get(5) in (1, b"\x01"):  # below sea level
                altitude_mm = -altitude_mm
        error = _rational(gps_ifd.get(31))
        error_mm = None
        if error is not None:
            scaled_error = error * 1000
            error_mm = round_half_down(scaled_error.numerator, scaled_error.denominator)
        gps = GpsFix(
            lat_e7=latitude,
            lon_e7=longitude,
            altitude_mm=altitude_mm,
            horizontal_error_mm=error_mm,
        )

    image_format = (image.format or "").upper()
    facts = ExifFacts(
        orientation=orientation,
        coded_width=coded_width,
        coded_height=coded_height,
        display_width=upright.size[0],
        display_height=upright.size[1],
        media_type=_MEDIA_TYPES.get(image_format, "application/octet-stream"),
        codec=image_format or "unknown",
        camera_make=_text(base.get(_MAKE_TAG)),
        camera_model=_text(base.get(_MODEL_TAG)),
        software=_text(base.get(_SOFTWARE_TAG)),
        clock=_clock_estimate(exif_ifd, base, gps_ifd),
        gps=gps,
        raw_tags={
            "ifd0": {str(k): _jsonable(v) for k, v in sorted(base.items())},
            "exif": {str(k): _jsonable(v) for k, v in sorted(exif_ifd.items())},
            "gps": {str(k): _jsonable(v) for k, v in sorted(gps_ifd.items())},
        },
    )
    return upright, facts
