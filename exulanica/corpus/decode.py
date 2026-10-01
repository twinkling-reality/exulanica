"""The one place a photograph becomes pixels, and the pixel budget that applies when it does.

"The one place" is a claim about call sites and it is checkable: ``Image.open`` appears in this
shared corpus module and nowhere else under ``exulanica/``. Ingest calls its compatibility
facade to apply EXIF orientation; reconstruction reads raw sensor pixels for JPEG/PNG and
recorded normalized PNGs for HEIF,
so COLMAP calibration keeps the exact staged pixel coordinate convention. Both paths share this
exact budget and
single-frame policy. It has not always been true. ``ingest/resolve.py``
used to open and load an original itself, on the path of a synchronous route, with no budget
comparison in front of it, and it was protected only by the process-wide state below happening
to have been installed by some other import. It now calls :func:`open_upright`, and the reason
it must is the measurement in the warning-filter paragraph below.

Two settings here are **interpreter-global**, which is the whole reason this module exists
rather than the two lines living wherever an image is next opened:

*   ``Image.MAX_IMAGE_PIXELS`` is a module attribute on ``PIL.Image``. Setting it twice with two
    different numbers means the effective limit is whichever module was imported last, which is
    a limit nobody chose.
*   ``warnings.simplefilter`` mutates the process-wide warning filters. Pillow *raises*
    ``DecompressionBombError`` only past **twice** the limit and merely *warns* between one and
    two times it, so without promoting that warning a file at 1.5x the budget decodes in full
    and a line appears on stderr that no request ever sees.

**The explicit size check below is not redundant with that filter**, and this is the whole
reason it is written out. Warning filters are process state that anything may reset:
``warnings.resetwarnings()``, a ``-W`` flag, a test runner configuring its own filters, a
library being helpful. Any of those silently removes the promotion, and the symptom is not an
error, it is a large file quietly decoded. So the budget is enforced by comparing two integers,
which nothing can reset, and the filter stays because it is what makes Pillow's own message the
one a caller sees when it fires first.

Both halves are measured, and they fail in opposite directions, which is why both are here. A
header declaring 66,015,625 pixels, 1.031x the budget and inside Pillow's warn-only band, was
refused by a bare ``Image.open`` while the promotion stood, and after ``resetwarnings()`` the
same bare ``Image.open`` **returned an image of size (8125, 8125)** while :func:`probe` on the
identical bytes still refused with the pixel count in the message. That is the exact shape of
the danger: the promotion covers callers this module cannot see, the comparison covers this
module when the promotion has been wiped, and neither covers the other's case.
``tests/test_intake_upload.py`` holds both claims, the second in a subprocess, because pytest
installs ``simplefilter("always")`` around every test and would otherwise be testing its own
filters rather than this module's.

**The budget is below Pillow's default, and the direction matters.** Assigning
``Image.MAX_IMAGE_PIXELS`` raises or lowers Pillow's own ceiling process-wide, so a number above
its default silently makes every caller in the process more permissive than Pillow intended,
including the corpus renderer and the command line. 89478485 is Pillow's default;
:data:`MAX_PIXELS` is below it.

**The number is an arithmetic about memory, not a claim about cameras, and the arithmetic is
measured rather than assumed.** Pillow does not store `RGB` at a byte per channel. It stores it
at **four** bytes per pixel, with the fourth unused, so a frame costs `4 x pixels` and not
`3 x pixels`. The orientation transform in ``extract_exif_facts`` allocates a second buffer of
the same size, because ``ImageOps.exif_transpose`` returns a copy even at orientation 1. At 64
megapixels that is about **256 MB decoded and about 512 MB at peak**, in a request thread.

Measured on this repository's own interpreter, CPython 3.11.6 on arm64 with Pillow 12.3.0, one
fresh process per figure so a peak counter cannot be reading a recycled allocator arena: an
8000x8000 JPEG decoded at 4.015 bytes per pixel (257.0 MB), the transpose copy cost a further
4.003 bytes per pixel (256.2 MB), and the peak over the pair was 515.4 MB. Repeated: 4.011,
4.003, 514.8 MB. The fourth byte is confirmed by the modes costing the same: one 64 megapixel
frame is 64.1 MB as `L`, 256.3 MB as `RGB` and 256.2 MB as `RGBA`, so `RGB` pays for a band it
does not have. A larger frame, a stitched panorama or a medium-format original, is refused with
its own pixel count in the message, and the number here is one line to raise deliberately.

**How many decode at once is bounded too, per process.** The pixel budget bounds one decode; a
synchronous route runs in the ASGI server's threadpool, so without a second bound the aggregate
would be that budget times the number of threads (40 x 512 MB, about 20 GiB, at anyio's default).
:func:`decoding` is that second bound: a process-wide count of decodes in progress, taken before
the pixels are loaded and held through the orientation copy, so a process holds at most
``limit`` decode peaks at a time. The API sets the limit at startup from ``EXULANICA_API_DECODES``;
every other process keeps :data:`DEFAULT_DECODES`. It is reentrant within a thread, so a caller
already holding it (``open_upright`` calling :func:`open_sensor`) cannot wait on itself.

**It waits, boundedly, and then refuses.** A decode over the limit waits at most
:data:`DECODE_WAIT_SECONDS` for a turn, then raises :class:`DecodeBusy`, which is not in
:data:`UNREADABLE`, so nothing reads it as a bad photograph. Waiting holds the waiting thread, and
that is acceptable only because both conditions that made it unacceptable are gone: liveness does
not use the request threadpool, and the threads that can wait here are requests the API admitted,
already bounded below the thread limit (``exulanica.api.admission``). ``docs/deployment.md``
section 5.4.4 carries the arithmetic and the sizing it implies.

**And it does not bound the number of bytes.** A file can be small and decode enormous, which is
what a decompression bomb is, and it can be enormous and decode to nothing. The byte bound
belongs to whoever is reading the bytes: the upload route bounds a part, and the command line
reads files a person chose off their own disk.
"""

from __future__ import annotations

import io
import re
import threading
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from pi_heif import __version__ as heif_version
from pi_heif import libheif_info, register_heif_opener
from PIL import Image, UnidentifiedImageError
from PIL import __version__ as pillow_version

__all__ = [
    "DECODE_WAIT_SECONDS",
    "DEFAULT_DECODES",
    "MAX_PIXELS",
    "UNREADABLE",
    "DecodeBusy",
    "configure_decode_concurrency",
    "decode_counts",
    "decoding",
    "open_sensor",
    "probe",
]

#: The largest frame this pipeline will decode, in pixels. 64 megapixels: past every phone and
#: every consumer camera, below Pillow's own 89478485 default so that assigning it below tightens
#: rather than loosens, and about 512 MB at peak to decode and turn upright. That last number is
#: measured, at 4 bytes per pixel twice over rather than the 3 an RGB frame looks like it costs.
MAX_PIXELS: Final = 64_000_000

# libheif applies HEIF container transforms; its Pillow adapter clears consumed EXIF
# orientation. Do not restore that tag or apply the container transform a second time.
# No thumbnail, auxiliary/depth-image decoding or encoder registration is needed.
register_heif_opener(thumbnails=False, depth_images=False, aux_images=False, decode_threads=1)

Image.MAX_IMAGE_PIXELS = MAX_PIXELS
warnings.simplefilter("error", Image.DecompressionBombWarning)

#: Everything that means "these bytes are not a photograph this pipeline can read".
#:
#: ``DecompressionBombError`` is in here because it is neither ``UnidentifiedImageError`` nor
#: ``OSError``: it derives straight from ``Exception``, so a handler catching the other two lets
#: it past and the refusal arrives as an unclassified failure with no pixel count in it.
#: ``DecompressionBombWarning`` is here because the filter above turns it into a raise, and a
#: warning promoted to an error is not an ``OSError`` either.
#:
#: ``ValueError`` is here because **Pillow dispatches on magic bytes, not on the file name**, so
#: bytes named ``a.jpg`` reach whichever plugin their first bytes match, and a plugin failing on
#: its own header does not raise ``UnidentifiedImageError``. Measured: a thirty-byte part named
#: ``a.jpg`` beginning ``P6\n99999999999999999999 1\n255\n`` reaches ``PpmImagePlugin`` and
#: raises ``ValueError: Token too long in file header``. That is still "these bytes are not a
#: photograph", and a handler that let it past turned a refusal into a 500.
UNREADABLE: Final = (
    UnidentifiedImageError,
    Image.DecompressionBombError,
    Image.DecompressionBombWarning,
    OSError,
    ValueError,
)

#: Decodes one process holds at once when nothing configures it: every process but the API, which
#: sets its own from ``EXULANICA_API_DECODES``. Two decode peaks at the pixel budget are about 1 GB.
DEFAULT_DECODES: Final = 2

#: The longest a decode waits for a turn before :class:`DecodeBusy`.
DECODE_WAIT_SECONDS: Final = 20.0


class DecodeBusy(Exception):
    """This process was already decoding as many photographs as it allows, for longer than a
    decode waits. Nothing was decoded, so the same work can be asked for again.

    A plain ``Exception``: this module imports nothing from the package, ``exulanica.errors``
    included, and it must not be an ``OSError`` or ``ValueError``, which :data:`UNREADABLE` reads
    as a photograph this pipeline cannot open.
    """


class _DecodeBound:
    """A process-wide count of decodes in progress, reentrant within one thread."""

    def __init__(self, limit: int, wait_seconds: float) -> None:
        self._condition = threading.Condition()
        self._limit = limit
        self._wait_seconds = wait_seconds
        self._in_use = 0
        self._peak = 0
        self._waited = 0
        self._refused = 0
        self._depth = threading.local()

    def configure(self, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("the decode limit must be a whole number of at least 1")
        with self._condition:
            self._limit = limit
            self._condition.notify_all()

    @contextmanager
    def hold(self) -> Iterator[None]:
        depth = getattr(self._depth, "value", 0)
        if depth:
            self._depth.value = depth + 1
            try:
                yield
            finally:
                self._depth.value = depth
            return
        deadline = time.monotonic() + self._wait_seconds
        with self._condition:
            waited = False
            while self._in_use >= self._limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._refused += 1
                    raise DecodeBusy(
                        f"this process was already decoding as many photographs as it allows "
                        f"({self._limit}) for {self._wait_seconds:g} seconds; nothing was decoded"
                    )
                waited = True
                self._condition.wait(remaining)
            self._in_use += 1
            self._peak = max(self._peak, self._in_use)
            self._waited += waited
        self._depth.value = 1
        try:
            yield
        finally:
            self._depth.value = 0
            with self._condition:
                self._in_use -= 1
                self._condition.notify()

    def counts(self) -> dict[str, Any]:
        with self._condition:
            return {
                "limit": self._limit,
                "in_use": self._in_use,
                "peak": self._peak,
                "waited": self._waited,
                "refused": self._refused,
            }


_BOUND: Final = _DecodeBound(DEFAULT_DECODES, DECODE_WAIT_SECONDS)


def decoding() -> Any:
    """Hold one of this process's decode turns for the ``with`` block. See the module docstring."""
    return _BOUND.hold()


def configure_decode_concurrency(limit: int) -> None:
    """Set how many photographs this process decodes at once."""
    _BOUND.configure(limit)


def decode_counts() -> dict[str, Any]:
    """The limit, the decodes in progress, the most at once, and how many waited or were refused."""
    return _BOUND.counts()


def probe(data: bytes) -> tuple[int, int]:
    """The frame's dimensions from its header alone, or a refusal. No decode.

    What an upload route needs and all it needs: whether these bytes are an image of a format
    this pipeline reads, and whether the frame is inside the budget. Both answers come out of
    the header, so a photograph too large to decode is refused for the price of parsing one,
    and the one decode that does happen happens once, later, in the pipeline.
    """
    with Image.open(io.BytesIO(data)) as opened:
        return _within_budget(opened)


def open_sensor(data: bytes) -> Image.Image:
    """Decode one bounded photograph in the decoder's native pixel grid.

    JPEG/PNG retain the encoded sensor grid and EXIF metadata. HEIF is different: libheif
    applies container transforms and its Pillow adapter clears consumed EXIF orientation.
    Those pixels are already in the transformed display grid, not an unrotated sensor grid.
    HEIF must reach pose through its recorded normalized PNG, whose orientation is one.
    Callers must not restore consumed orientation or implicitly transpose these pixels.
    The caller owns the image and should close it (or use it as a context manager). Ingest's
    compatibility facade applies its existing explicit orientation transform after this call.

    Header dimensions and frame count are checked before loading, and the load takes one of the
    process's decode turns (:func:`decoding`), so it may wait and may raise :class:`DecodeBusy`.
    On failure, the opened image is closed; successful returns keep any in-memory metadata stream
    needed by Pillow plugins.
    """
    opened = Image.open(io.BytesIO(data))
    try:
        _within_budget(opened)
        with decoding():
            opened.load()
        _within_budget(opened)
    except BaseException:
        opened.close()
        raise
    return opened


def _single_frame(image: Image.Image) -> None:
    """Refuse a container holding more than one frame, rather than addressing only the first.

    This is the "motion photographs and bursts" item that ``docs/domain-and-evidence-model.md``
    section 1.5 records as an inspection rather than a design question, closed by refusing.

    A photograph is modelled as a single-sample ``img`` track whose interval is ``[0, 1)``. An
    animated GIF, a multi-frame WebP or a motion photograph is not that: it carries a real
    sequence with real presentation times, and the general video path applies to it unchanged.
    Ingesting one today would silently keep the first frame, store a ``capture`` whose
    ``pixel_size_is`` and EXIF describe the whole file, and address every span at ``img`` on a
    blob whose other frames nothing can cite. The evidence would be wrong rather than missing.

    So it fails closed until the video preconditions in
    ``docs/evaluation/2026-09-04-readiness-and-architecture-audit.json`` are met. The refusal is
    the cheap half of that gate: the expensive half is the video track path itself.
    """
    frames = getattr(image, "n_frames", 1)
    if isinstance(frames, int) and frames > 1:
        raise ValueError(
            f"this container holds {frames} frames and a photograph is modelled as a single "
            "sample. A motion photograph, burst or animation carries a real v:0 track with real "
            "presentation times, and the general video path applies to it unchanged. Refusing "
            "rather than keeping frame one and addressing it as the whole file."
        )


def _within_budget(image: Image.Image) -> tuple[int, int]:
    """The one comparison that enforces :data:`MAX_PIXELS`. Returns the size when it passes."""
    _single_frame(image)
    width, height = image.size
    pixels = width * height
    if pixels > MAX_PIXELS:
        raise Image.DecompressionBombError(
            f"image size ({width}x{height} = {pixels} pixels) exceeds this pipeline's limit "
            f"of {MAX_PIXELS} pixels"
        )
    return width, height


def decoder_inventory() -> dict[str, str]:
    """Actual compiled decoder identities, bound into the normalized stage registry and receipt."""
    libraries = libheif_info()
    version = re.search(r"version ([0-9][^ ]*)", libraries["decoders"].get("libde265", ""))
    if heif_version != "1.4.0" or version is None:
        raise ValueError("the reviewed HEIF decoder is unavailable")
    return {
        "pi-heif": heif_version,
        "libheif": libraries["libheif"],
        "libde265": version[1],
        "pillow": pillow_version,
    }
