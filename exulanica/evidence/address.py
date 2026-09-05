"""The evidence address: the one type the rest of Exulanica resolves against.

An address is ``(content hash of the original bytes, track key, exact half-open interval on the
canonical nanosecond axis)``, optionally refined by a normalised region and a character range in
a versioned text artifact. It is never a frame ordinal, never a byte offset, never a segment
index in a derivative, and never a pointer into a transcript. Those are all functions of the
decoder, the filter graph or the pipeline version, so they change under regeneration while the
bytes do not.

The consequence that makes the rest of the system safe to iterate on: **a full pipeline
regeneration changes zero addresses.** Nothing in this module has a field that a derivative
could move.

A photograph is the degenerate case and is not a special shape. It is a single-sample ``img``
track carrying the interval ``[0, 1)``, so the same overlap, tombstone and co-presence code
paths run over photographs as over video, and the digest tuple never has to grow a field later.

Two renderings, and they are not the same thing:

*   ``span_digest`` is the **identity**. SHA-256 over the canonical JSON of the address tuple,
    with ``hint`` and ``span_id`` excluded, because the digest must be a function of the address
    and not of the row that happens to hold it.
*   ``to_uri()`` is a **rendering**, the permalink form. It is designed to be lossless, so it
    parses back to an address with the same digest, which is what lets a citation string stay
    valid forever.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final
from urllib.parse import quote, unquote

from exulanica.canonical import sha256_of_canonical
from exulanica.errors import InvalidAddressError, LossyAddressError
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import DisplayGeometry, Rect, Region
from exulanica.evidence.timebase import (
    PHOTOGRAPH_INTERVAL,
    TimeInterval,
    ns_to_seconds,
    seconds_to_ns,
)

__all__ = [
    "IMAGE_TRACK_KEY",
    "SPAN_FORMAT_VERSION",
    "URI_SCHEME",
    "EvidenceAddress",
    "Modality",
    "TextAnchor",
    "parse_uri",
]

#: Frozen at v1 and extended additively only. A change here is a product-wide event: it
#: invalidates every stored citation token, every permalink and every archived answer.
SPAN_FORMAT_VERSION: Final = 1

IMAGE_TRACK_KEY: Final = "img"
URI_SCHEME: Final = "exulanica"

_TRACK_RE: Final = re.compile(r"^(img|[va]:(?:0|[1-9][0-9]{0,3}))$")
_URI_RE: Final = re.compile(
    r"^exulanica://blob/(?P<ni>ni:///sha-256;[A-Za-z0-9_-]{43})/(?P<track>[A-Za-z0-9_:.-]+)"
    r"#(?P<fragment>.*)$"
)
#: A quote longer than this is not put in a URI. See ``to_uri``.
_MAX_ENCODED_EXACT: Final = 512


class Modality(StrEnum):
    """The five citation kinds. Inside ``span_digest``, so these strings are frozen."""

    STILL_IMAGE = "still_image"
    FRAME_REGION = "frame_region"
    VIDEO_TIME = "video_time"
    AUDIO_TIME = "audio_time"
    TRANSCRIPT_TEXT = "transcript_text"


_VISUAL_TRACK_MODALITIES: Final = frozenset(
    {Modality.STILL_IMAGE, Modality.FRAME_REGION, Modality.VIDEO_TIME}
)


def validate_track_key(track_key: str) -> str:
    """Accept ``img``, ``v:N`` or ``a:N``, and nothing else."""
    if not isinstance(track_key, str) or _TRACK_RE.match(track_key) is None:
        raise InvalidAddressError(f"track key must be 'img', 'v:N' or 'a:N', got {track_key!r}")
    return track_key


@dataclass(frozen=True, slots=True, order=True)
class TextAnchor:
    """A character range in a versioned text artifact.

    The character range is a highlight convenience. The address is the media time range, which
    is why a text span is required to carry one in addition to this. When the artifact is
    regenerated at a new model version the span is not rewritten; a separate
    ``anchor_resolution`` row maps it onto the new artifact, and a failed re-anchor degrades the
    highlight without invalidating the citation.
    """

    artifact_id: uuid.UUID
    char_start: int
    char_end: int
    exact: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, uuid.UUID):
            raise InvalidAddressError("text anchor artifact_id must be a uuid.UUID")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise InvalidAddressError(
                f"character range must be non-empty and half-open: "
                f"[{self.char_start}, {self.char_end})"
            )

    def as_digest_input(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_id": str(self.artifact_id),
            "char_start": self.char_start,
            "char_end": self.char_end,
        }
        if self.exact is not None:
            payload["exact"] = self.exact
        return payload


@dataclass(frozen=True, slots=True, eq=False)
class EvidenceAddress:
    """The address of a piece of evidence. Immutable, hashable, totally ordered.

    Equality is digest equality, so two addresses are equal exactly when they would produce the
    same ``span_digest``, which is exactly when they name the same evidence. Ordering is
    lexicographic over ``(blob, track, start, end, modality, region, anchor)``, which gives a
    list of citations one deterministic playback order.
    """

    blob_id: BlobId
    track_key: str
    interval: TimeInterval
    modality: Modality
    region: Region | None = None
    text_anchor: TextAnchor | None = None
    span_format_version: int = SPAN_FORMAT_VERSION

    _digest: bytes = field(init=False, repr=False, compare=False, default=b"")

    def __post_init__(self) -> None:
        if not isinstance(self.blob_id, BlobId):
            raise InvalidAddressError("blob_id must be a BlobId")
        if not isinstance(self.interval, TimeInterval):
            raise InvalidAddressError("interval must be a TimeInterval")
        object.__setattr__(self, "track_key", validate_track_key(self.track_key))
        object.__setattr__(self, "modality", Modality(self.modality))
        if self.span_format_version != SPAN_FORMAT_VERSION:
            raise InvalidAddressError(
                f"unknown span_format_version {self.span_format_version}; this build writes and "
                f"reads v{SPAN_FORMAT_VERSION}"
            )
        self._validate_shape()
        object.__setattr__(self, "_digest", sha256_of_canonical(self.as_digest_input()))

    # -- shape rules, mirroring the check constraints in migration 0001 ------------------

    def _validate_shape(self) -> None:
        modality = self.modality
        track = self.track_key
        if modality is Modality.TRANSCRIPT_TEXT and self.text_anchor is None:
            raise InvalidAddressError("a transcript_text span must carry a text anchor")
        if modality is not Modality.TRANSCRIPT_TEXT and self.text_anchor is not None:
            raise InvalidAddressError(
                f"a text anchor is only meaningful on transcript_text, not {modality}"
            )
        if modality is Modality.FRAME_REGION and self.region is None:
            raise InvalidAddressError("a frame_region span must carry a region")
        if self.region is not None and modality is not Modality.FRAME_REGION:
            raise InvalidAddressError(
                f"a region refines a span into frame_region; {modality} may not carry one. "
                "This keeps the modality recoverable from the address shape."
            )
        if modality is Modality.STILL_IMAGE and track != IMAGE_TRACK_KEY:
            raise InvalidAddressError(f"still_image lives on the '{IMAGE_TRACK_KEY}' track")
        if modality is Modality.VIDEO_TIME and not track.startswith("v:"):
            raise InvalidAddressError("video_time lives on a 'v:N' track")
        if modality is Modality.AUDIO_TIME and not track.startswith("a:"):
            raise InvalidAddressError("audio_time lives on an 'a:N' track")
        if modality in _VISUAL_TRACK_MODALITIES and track.startswith("a:"):
            raise InvalidAddressError(f"{modality} cannot address an audio track")
        if modality is Modality.TRANSCRIPT_TEXT and track == IMAGE_TRACK_KEY:
            # ADR-0016. A photograph has no transcript. Text read off a surface is addressed by
            # the pixels it was read from, which is a region, and it is carried as an
            # `ocr_text_is` assertion over that region. Allowing transcript_text here would
            # create a second address shape for the same fact, and `modality` is inside
            # span_digest, so re-labelling later is a v2 span format rather than a rename.
            raise InvalidAddressError(
                f"transcript_text cannot address the '{IMAGE_TRACK_KEY}' track: a photograph "
                "has no transcript. Text read off a photograph is a frame_region span carrying "
                "an ocr_text_is assertion. A text-anchored OCR artifact, if one is ever needed, "
                "takes its own additive modality value rather than this one."
            )
        if self.region is not None and track == IMAGE_TRACK_KEY and self.region.display.rotation:
            # ADR-0012. A photograph's display space IS its upright pixel space, because ingest
            # normalises orientation once and stores the result. A region claiming a rotated
            # display space is not a stale row to repair later: the address denotes the wrong
            # pixels, and `region` is inside span_digest, so it would be permanent.
            raise InvalidAddressError(
                f"a region on the '{IMAGE_TRACK_KEY}' track must carry display.rotation 0, got "
                f"{self.region.display.rotation}. Photograph pixels are normalised upright at "
                "ingest, so there is no second rotation for a reader to apply."
            )

    # -- construction helpers ------------------------------------------------------------

    @classmethod
    def photograph(cls, blob_id: BlobId, *, region: Region | None = None) -> EvidenceAddress:
        """The degenerate case: a whole photograph, or a region within one.

        The interval is ``[0, 1)`` nanoseconds. It is a structural placeholder and says nothing
        about the content: an exposure duration is deliberately not used, because that would
        make the address depend on an optional metadata field that an editor may have rewritten.
        """
        return cls(
            blob_id=blob_id,
            track_key=IMAGE_TRACK_KEY,
            interval=PHOTOGRAPH_INTERVAL,
            modality=Modality.FRAME_REGION if region is not None else Modality.STILL_IMAGE,
            region=region,
        )

    # -- identity --------------------------------------------------------------------------

    def as_digest_input(self) -> dict[str, Any]:
        """The canonical tuple. ``hint`` and ``span_id`` are absent by construction."""
        payload: dict[str, Any] = {
            "span_format_version": self.span_format_version,
            # Hex rather than raw bytes, because the digest input must be JSON. Lowercase hex
            # is chosen over base64url so the value is identical to what the database prints.
            "blob_sha256": self.blob_id.hex,
            "track_key": self.track_key,
            "t_start_ns": self.interval.start_ns,
            "t_end_ns": self.interval.end_ns,
            "modality": str(self.modality),
        }
        if self.region is not None:
            payload["region"] = self.region.as_digest_input()
        if self.text_anchor is not None:
            payload["text_anchor"] = self.text_anchor.as_digest_input()
        return payload

    @property
    def span_digest(self) -> bytes:
        """SHA-256 of the canonical address tuple. 32 raw bytes."""
        return self._digest

    @property
    def span_digest_hex(self) -> str:
        return self._digest.hex()

    # -- rendering -------------------------------------------------------------------------

    def to_uri(self, *, allow_lossy: bool = False) -> str:
        """Render the permalink form.

        Lossless for every modality in the photograph corpus, so ``parse_uri(a.to_uri()) == a``.
        The only value that can force a loss is a very long ``exact`` quote on a transcript
        span; ``LossyAddressError`` is raised rather than emitting a citation string that would
        parse back to a different digest.
        """
        parts = [
            f"v={self.span_format_version}",
            f"m={self.modality}",
            f"t={ns_to_seconds(self.interval.start_ns)},{ns_to_seconds(self.interval.end_ns)}",
        ]
        if self.region is not None:
            parts.append(f"xywh=percent:{self.region.rect.as_percent_string()}")
            display = self.region.display
            parts.append(
                f"disp={display.w}x{display.h},{display.rotation},"
                f"{display.sar_num}:{display.sar_den}"
            )
        if self.text_anchor is not None:
            anchor = self.text_anchor
            parts.append(f"text={anchor.artifact_id},{anchor.char_start},{anchor.char_end}")
            if anchor.exact is not None:
                encoded = quote(anchor.exact, safe="")
                if len(encoded) > _MAX_ENCODED_EXACT and not allow_lossy:
                    raise LossyAddressError(
                        f"the exact quote encodes to {len(encoded)} characters, over the "
                        f"{_MAX_ENCODED_EXACT} limit. It is an input to span_digest, so omitting "
                        "it would produce a URI that parses back to a different address. Pass "
                        "allow_lossy=True only where the digest is carried separately."
                    )
                if len(encoded) <= _MAX_ENCODED_EXACT:
                    parts.append(f"exact={encoded}")
        fragment = "&".join(parts)
        return f"{URI_SCHEME}://blob/{self.blob_id.ni_uri}/{self.track_key}#{fragment}"

    def __str__(self) -> str:
        return self.to_uri(allow_lossy=True)

    def __repr__(self) -> str:
        return (
            f"EvidenceAddress({self.blob_id.hex[:12]}... {self.track_key} "
            f"{self.interval} {self.modality})"
        )

    # -- equality and ordering ---------------------------------------------------------------

    def _sort_key(self) -> tuple[Any, ...]:
        region_key: tuple[Any, ...] = ()
        if self.region is not None:
            rect, display = self.region.rect, self.region.display
            region_key = (
                rect.x_ppm,
                rect.y_ppm,
                rect.w_ppm,
                rect.h_ppm,
                display.w,
                display.h,
                display.rotation,
            )
        anchor_key: tuple[Any, ...] = ()
        if self.text_anchor is not None:
            anchor_key = (
                str(self.text_anchor.artifact_id),
                self.text_anchor.char_start,
                self.text_anchor.char_end,
            )
        return (
            self.blob_id.digest,
            self.track_key,
            self.interval.start_ns,
            self.interval.end_ns,
            str(self.modality),
            region_key,
            anchor_key,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EvidenceAddress):
            return NotImplemented
        return self._digest == other._digest

    def __hash__(self) -> int:
        return hash(self._digest)

    def __lt__(self, other: EvidenceAddress) -> bool:
        if not isinstance(other, EvidenceAddress):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __le__(self, other: EvidenceAddress) -> bool:
        if not isinstance(other, EvidenceAddress):
            return NotImplemented
        return self == other or self._sort_key() < other._sort_key()

    def __gt__(self, other: EvidenceAddress) -> bool:
        if not isinstance(other, EvidenceAddress):
            return NotImplemented
        return other.__lt__(self)

    def __ge__(self, other: EvidenceAddress) -> bool:
        if not isinstance(other, EvidenceAddress):
            return NotImplemented
        return other.__le__(self)


# -- parsing ----------------------------------------------------------------------------------


def _parse_fragment(fragment: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for chunk in fragment.split("&"):
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep:
            raise InvalidAddressError(f"malformed fragment component {chunk!r}")
        if key in pairs:
            raise InvalidAddressError(f"duplicate fragment key {key!r}")
        pairs[key] = value
    return pairs


def _parse_display(text: str) -> DisplayGeometry:
    try:
        size, rotation, sar = text.split(",")
        width, height = size.split("x")
        sar_num, sar_den = sar.split(":")
        return DisplayGeometry(
            w=int(width),
            h=int(height),
            rotation=int(rotation),
            sar_num=int(sar_num),
            sar_den=int(sar_den),
        )
    except ValueError as exc:
        raise InvalidAddressError(f"malformed disp component {text!r}: {exc}") from exc


def _infer_modality(track_key: str, has_region: bool, has_text: bool) -> Modality:
    """Read modality off the address shape, for URIs written before ``m=`` existed."""
    if has_text:
        return Modality.TRANSCRIPT_TEXT
    if has_region:
        return Modality.FRAME_REGION
    if track_key == IMAGE_TRACK_KEY:
        return Modality.STILL_IMAGE
    if track_key.startswith("v:"):
        return Modality.VIDEO_TIME
    return Modality.AUDIO_TIME


def parse_uri(uri: str) -> EvidenceAddress:
    """Parse the permalink form back into an address.

    ``v=`` and ``m=`` are optional: a URI without them is read as span format v1 with the
    modality inferred from the address shape, which is what the shape rules on
    ``EvidenceAddress`` guarantee is unambiguous. That keeps the shorter form shown in the
    domain document readable forever.
    """
    match = _URI_RE.match(uri.strip())
    if match is None:
        raise InvalidAddressError(f"not an Exulanica evidence URI: {uri!r}")
    blob_id = BlobId.from_ni_uri(match.group("ni"))
    track_key = validate_track_key(match.group("track"))
    fields = _parse_fragment(match.group("fragment"))

    if "t" not in fields:
        raise InvalidAddressError("evidence URI has no t= interval")
    start_text, sep, end_text = fields["t"].partition(",")
    if not sep:
        raise InvalidAddressError(
            "evidence URI carries a single time point; an address is always an interval"
        )
    interval = TimeInterval(seconds_to_ns(start_text), seconds_to_ns(end_text))

    region: Region | None = None
    if "xywh" in fields:
        value = fields["xywh"]
        if not value.startswith("percent:"):
            raise InvalidAddressError(
                f"xywh must be normalised, so it must start with 'percent:', got {value!r}"
            )
        if "disp" not in fields:
            raise InvalidAddressError(
                "a region URI must carry disp=, because the display geometry a region is "
                "normalised against is an input to span_digest"
            )
        region = Region(
            rect=Rect.from_percent_string(value.removeprefix("percent:")),
            display=_parse_display(fields["disp"]),
        )

    anchor: TextAnchor | None = None
    if "text" in fields:
        try:
            artifact_text, char_start, char_end = fields["text"].split(",")
            anchor = TextAnchor(
                artifact_id=uuid.UUID(artifact_text),
                char_start=int(char_start),
                char_end=int(char_end),
                exact=unquote(fields["exact"]) if "exact" in fields else None,
            )
        except ValueError as exc:
            raise InvalidAddressError(f"malformed text component: {exc}") from exc

    version = int(fields.get("v", SPAN_FORMAT_VERSION))
    modality = (
        Modality(fields["m"])
        if "m" in fields
        else _infer_modality(track_key, region is not None, anchor is not None)
    )
    return EvidenceAddress(
        blob_id=blob_id,
        track_key=track_key,
        interval=interval,
        modality=modality,
        region=region,
        text_anchor=anchor,
        span_format_version=version,
    )
