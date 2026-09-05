"""Raw calibration pixels and upright ingest share one bounded single-frame decoder."""

from __future__ import annotations

import io
import struct
import warnings
import zlib

import pytest
from exulanica.corpus.decode import MAX_PIXELS, open_sensor, probe
from exulanica.ingest.decode import open_upright
from PIL import Image, ImageOps


@pytest.mark.parametrize("orientation", range(1, 9))
def test_sensor_pixels_preserve_all_exif_orientations_while_ingest_applies_them(orientation):
    original = Image.new("RGB", (3, 2))
    original.putdata(
        [(255, 0, 0), (0, 255, 0), (0, 0, 255), (10, 20, 30), (40, 50, 60), (70, 80, 90)]
    )
    exif = Image.Exif()
    exif[0x0112] = orientation
    encoded = io.BytesIO()
    original.save(encoded, format="PNG", exif=exif)
    data = encoded.getvalue()
    assert probe(data) == (3, 2)
    with open_sensor(data) as raw:
        assert raw.size == original.size
        assert raw.tobytes() == original.tobytes()
        assert raw.getexif()[0x0112] == orientation
        expected_upright = ImageOps.exif_transpose(raw)
    upright, facts = open_upright(data)
    assert upright.size == expected_upright.size
    assert upright.tobytes() == expected_upright.tobytes()
    assert facts.orientation.exif_value == orientation


def _header(width, height):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("decoder", [probe, open_sensor])
def test_budget_refuses_header_before_loading_even_if_warning_filters_are_reset(decoder):
    width, height = 8125, 8125
    assert MAX_PIXELS < width * height < 2 * MAX_PIXELS
    with warnings.catch_warnings():
        warnings.resetwarnings()
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with pytest.raises(Image.DecompressionBombError, match=str(width * height)):
            decoder(_header(width, height))


@pytest.mark.parametrize("decoder", [probe, open_sensor])
def test_multiple_frames_are_refused_at_probe_and_decode(decoder):
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=[Image.new("RGB", (3, 2), "blue")],
        duration=10,
        loop=0,
    )
    with pytest.raises(ValueError, match="2 frames"):
        decoder(buffer.getvalue())


def test_sensor_decoder_loads_pixels_and_refuses_truncated_payload_after_header_probe():
    data = _header(3, 2)
    assert probe(data) == (3, 2)
    with pytest.raises(OSError):
        open_sensor(data)
