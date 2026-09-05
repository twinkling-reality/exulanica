"""The one place a photograph becomes pixels, and the pixel budget that applies when it does.

"The one place" is a claim about call sites and it is checkable: ``Image.open`` appears in this
module and nowhere else under ``orimera/``. It has not always been true. ``ingest/resolve.py``
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

**What is NOT bounded, said plainly, and what not to reach for.** This bounds one decode. A
synchronous route runs in the ASGI server's threadpool, so the aggregate is that bound times the
number of threads, and nothing here limits how many decode at once. Measured against uvicorn
rather than read from anyio: 120 concurrent requests to a synchronous handler ran 40 at a time
across 40 distinct worker threads, which is anyio's hard-coded default and nothing in this
deployment chose it. The production composition disables the in-process derivative worker, so
the API-process worst case is 40 x 512 MB, about 20 GiB. Its dedicated derivative worker is a
separate process with one delivery thread and roughly one more 512 MB decode peak.
``docs/deployment.md`` section 5.4.4 carries that arithmetic and the sizing it implies.

**A semaphore around the decode is the wrong repair and was rejected on measurement.** Acquiring
one inside a synchronous handler blocks a thread that is *already* holding one of anyio's 40
tokens, so the requests over the bound do not fail fast: they occupy threads while waiting, and
``/healthz`` is synchronous on the same limiter, so the instance's own liveness probe starves at
exactly the load the semaphore was added to survive. The bound that works is on how many threads
exist, not on what they are allowed to do once they have one.

**And it does not bound the number of bytes.** A file can be small and decode enormous, which is
what a decompression bomb is, and it can be enormous and decode to nothing. The byte bound
belongs to whoever is reading the bytes: the upload route bounds a part, and the command line
reads files a person chose off their own disk.
"""

from __future__ import annotations

import io
import warnings
from typing import Final

from PIL import Image, UnidentifiedImageError

from exulanica.ingest.exif import ExifFacts, extract_exif_facts

__all__ = ["MAX_PIXELS", "UNREADABLE", "open_upright", "probe"]

#: The largest frame this pipeline will decode, in pixels. 64 megapixels: past every phone and
#: every consumer camera, below Pillow's own 89478485 default so that assigning it below tightens
#: rather than loosens, and about 512 MB at peak to decode and turn upright. That last number is
#: measured, at 4 bytes per pixel twice over rather than the 3 an RGB frame looks like it costs.
MAX_PIXELS: Final = 64_000_000

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


def probe(data: bytes) -> tuple[int, int]:
    """The frame's dimensions from its header alone, or a refusal. No decode.

    What an upload route needs and all it needs: whether these bytes are an image of a format
    this pipeline reads, and whether the frame is inside the budget. Both answers come out of
    the header, so a photograph too large to decode is refused for the price of parsing one,
    and the one decode that does happen happens once, later, in the pipeline.
    """
    with Image.open(io.BytesIO(data)) as opened:
        return _within_budget(opened)


def open_upright(data: bytes) -> tuple[Image.Image, ExifFacts]:
    """Decode these bytes and return the upright image and everything the file itself says.

    Raises one of :data:`UNREADABLE` for anything that is not a readable photograph. The caller
    decides what a refusal means; this decides only what a photograph is.

    The size is read from the header and compared before ``load()``, so a frame over the budget
    costs a header parse rather than a decode. ``load()`` is called inside the ``with`` so the
    pixel data is in memory before the file object closes, and the orientation transform happens
    exactly once, here, so no later stage repeats the decision or works from the wrong rotation.
    """
    with Image.open(io.BytesIO(data)) as opened:
        _within_budget(opened)
        opened.load()
        return extract_exif_facts(opened)


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
