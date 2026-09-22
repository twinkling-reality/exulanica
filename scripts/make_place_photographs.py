"""Synthetic photographs of places, with the ground truth of what was drawn.

    python scripts/make_place_photographs.py OUT_DIR [--split development|held_out]

No personal photograph is ever used. Each scene is drawn from a fixed recipe, so the bytes and
the ground truth are the same on every run, and every claim about an omission or an unsupported
observation is checked against what this module actually drew rather than against a reading of
the picture.

Two kinds of scene, because a vision measurement needs both arms:

*   a **signed** scene carries a legible place name on a facade board, which is the only thing
    that entitles the vision pass to propose a place
    (``exulanica/ingest/vision.py`` instructs it to propose one only from signage or a
    distinctive landmark);
*   an **unsigned** scene carries the same kinds of object and no name anywhere, so a proposed
    place from it is an unsupported observation and not a success.

The ground truth records normalised boxes. Scoring compares boxes, never words: a detector's
vocabulary and a scene recipe's vocabulary disagree even when both are right about where a thing
is, so a word-matched score measures the vocabulary rather than the detection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1280, 960
HORIZON = int(HEIGHT * 0.62)

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)

#: Place names invented for this corpus. They name nothing real, which is the point: a model that
#: recognises one of these from world knowledge rather than from the board is not reading the
#: photograph.
DEVELOPMENT = (
    ("MERIDIAN HALL", True),
    ("KESTREL YARD", True),
    ("", False),
    ("ALDER COURT", True),
    ("", False),
    ("BRAMBLE WHARF", True),
)
HELD_OUT = (
    ("VESPER ARCADE", True),
    ("", False),
    ("QUILLON BATHS", True),
    ("HARROW FIELDS", True),
    ("", False),
    ("SABLE ROTUNDA", True),
    ("TINDALE LOCK", True),
    ("", False),
    ("MARLOW GRANARY", True),
    ("", False),
)


def _font(size: int) -> Any:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise SystemExit(
        "no TrueType font found; a bitmap fallback renders text too small to be legible and a "
        "measurement of an illegible sign measures the renderer"
    )


#: Which drawn objects the primary score counts. A facade carries eight windows and a door,
#: and a describer that says "a building with windows" has not omitted eight things; counting
#: them as eight omissions would measure the recipe's appetite for detail rather than the
#: model's. The detail tier is still recorded and reported, separately and without a threshold.
SALIENT = frozenset({"building", "sign", "tree", "bench", "lamppost", "car"})


def _box(x0: int, y0: int, x1: int, y1: int) -> dict[str, float]:
    return {
        "x": round(x0 / WIDTH, 6),
        "y": round(y0 / HEIGHT, 6),
        "w": round((x1 - x0) / WIDTH, 6),
        "h": round((y1 - y0) / HEIGHT, 6),
    }


def _tree(draw: ImageDraw.ImageDraw, x: int, base: int, scale: float) -> dict[str, Any]:
    trunk_w, trunk_h = int(26 * scale), int(120 * scale)
    canopy = int(150 * scale)
    draw.rectangle([x - trunk_w // 2, base - trunk_h, x + trunk_w // 2, base], fill=(96, 66, 42))
    top = base - trunk_h - canopy
    draw.ellipse([x - canopy // 2, top, x + canopy // 2, top + canopy], fill=(58, 128, 62))
    return {"what": "tree", "box": _box(x - canopy // 2, top, x + canopy // 2, base)}


def _bench(draw: ImageDraw.ImageDraw, x: int, base: int) -> dict[str, Any]:
    draw.rectangle([x, base - 46, x + 190, base - 30], fill=(140, 96, 54))
    draw.rectangle([x, base - 96, x + 190, base - 80], fill=(140, 96, 54))
    draw.rectangle([x + 10, base - 30, x + 24, base], fill=(70, 70, 74))
    draw.rectangle([x + 166, base - 30, x + 180, base], fill=(70, 70, 74))
    return {"what": "bench", "box": _box(x, base - 96, x + 190, base)}


def _lamppost(draw: ImageDraw.ImageDraw, x: int, base: int) -> dict[str, Any]:
    draw.rectangle([x - 7, base - 300, x + 7, base], fill=(58, 60, 66))
    draw.ellipse([x - 34, base - 342, x + 34, base - 286], fill=(248, 236, 176))
    return {"what": "lamppost", "box": _box(x - 34, base - 342, x + 34, base)}


def _car(draw: ImageDraw.ImageDraw, x: int, base: int, colour: tuple[int, int, int]) -> dict[str, Any]:
    draw.rectangle([x, base - 74, x + 250, base - 26], fill=colour, outline=(28, 28, 30), width=3)
    draw.polygon(
        [(x + 52, base - 74), (x + 92, base - 118), (x + 178, base - 118), (x + 208, base - 74)],
        fill=colour, outline=(28, 28, 30),
    )
    draw.ellipse([x + 34, base - 44, x + 86, base + 8], fill=(26, 26, 28))
    draw.ellipse([x + 168, base - 44, x + 220, base + 8], fill=(26, 26, 28))
    return {"what": "car", "box": _box(x, base - 118, x + 250, base + 8)}


def _facade(draw: ImageDraw.ImageDraw, sign_text: str) -> list[dict[str, Any]]:
    """A building, and on a signed scene the board that names it."""
    left, right = 300, 980
    top = 150
    draw.rectangle([left, top, right, HORIZON], fill=(206, 198, 186), outline=(92, 88, 82), width=5)
    drawn = [{"what": "building", "box": _box(left, top, right, HORIZON)}]
    for row in range(2):
        for column in range(4):
            wx = left + 44 + column * 156
            wy = top + 190 + row * 150
            draw.rectangle([wx, wy, wx + 104, wy + 106], fill=(118, 150, 178),
                           outline=(64, 62, 60), width=3)
            drawn.append({"what": "window", "box": _box(wx, wy, wx + 104, wy + 106)})
    door_x = left + 296
    draw.rectangle([door_x, HORIZON - 172, door_x + 96, HORIZON], fill=(86, 60, 40),
                   outline=(48, 36, 26), width=3)
    drawn.append({"what": "door", "box": _box(door_x, HORIZON - 172, door_x + 96, HORIZON)})
    if sign_text:
        board = [left + 40, top + 34, right - 40, top + 134]
        draw.rectangle(board, fill=(22, 36, 58), outline=(232, 226, 210), width=4)
        font = _font(58)
        span = draw.textbbox((0, 0), sign_text, font=font)
        draw.text(
            ((board[0] + board[2]) // 2 - (span[2] - span[0]) // 2,
             (board[1] + board[3]) // 2 - (span[3] - span[1]) // 2 - span[1]),
            sign_text, fill=(244, 240, 228), font=font,
        )
        drawn.append({"what": "sign", "box": _box(*board)})
    return drawn


NOTICES = {
    "plain": "SYNTHETIC TEST IMAGE",
    "asserts_no_place": "SYNTHETIC IMAGE - GENERATED LOCALLY - NO REAL PLACE, NO PERSON",
}



def photographic(image: Image.Image, index: int) -> Image.Image:
    """Make a drawn scene carry the surface a camera leaves on a photograph.

    The vision role declined to propose a place from every signed scene in the first corpus while
    transcribing the board correctly, and its own scene description called the picture a
    "flat, vector-style illustration". That is a hypothesis about the rendering, not about the
    sign, and this function exists so the hypothesis can be tested instead of argued: the same
    geometry and the same board, with sensor noise, a lens blur, a vignette and a lower JPEG
    quality. Nothing here adds or removes a drawn object, so the ground truth is unchanged.
    """
    rng = np.random.default_rng(index)
    array = np.asarray(image.filter(ImageFilter.GaussianBlur(0.6)), dtype=np.float32)
    height, width, _ = array.shape
    array += rng.normal(0.0, 6.0, array.shape)
    ys = (np.linspace(-1.0, 1.0, height) ** 2)[:, None]
    xs = (np.linspace(-1.0, 1.0, width) ** 2)[None, :]
    array *= (1.0 - 0.28 * np.clip(ys + xs, 0.0, 1.0))[:, :, None]
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


def scene(index: int, sign_text: str, notice_kind: str = "plain") -> tuple[Image.Image, dict[str, Any]]:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / HEIGHT
        above = (int(126 + 78 * t), int(168 + 54 * t), int(226 - 34 * t))
        below = (int(104 + 26 * t), int(112 + 18 * t), int(96 + 12 * t))
        draw.line([(0, y), (WIDTH, y)], fill=above if y < HORIZON else below)

    drawn = _facade(draw, sign_text)
    drawn.append(_tree(draw, 150 + (index * 31) % 70, HORIZON + 40, 1.0))
    drawn.append(_tree(draw, 1130 - (index * 23) % 60, HORIZON + 26, 0.8))
    drawn.append(_bench(draw, 380 + (index * 37) % 90, HORIZON + 150))
    drawn.append(_lamppost(draw, 1010 - (index * 19) % 50, HORIZON + 120))
    drawn.append(_car(draw, 640 + (index * 29) % 80, HORIZON + 210,
                      [(168, 54, 48), (48, 82, 156), (206, 172, 56)][index % 3]))

    # The synthetic notice, small and at the very bottom edge so it cannot be mistaken for the
    # place board. It is recorded as ground truth text too, because the model may transcribe it
    # and a transcription of something genuinely in the frame is not an invention.
    #
    # The wording matters and it is why this is a parameter. The first corpus drawn here carried
    # "SYNTHETIC IMAGE - GENERATED LOCALLY - NO REAL PLACE, NO PERSON", and the vision pass read
    # that line, transcribed it correctly, and then proposed no place at all from a legible
    # board. A notice that asserts there is no real place is evidence about the photograph, not
    # decoration, and a corpus that carries it cannot measure whether a model proposes a place
    # from signage. NOTICES["plain"] marks the image as synthetic without making that assertion;
    # NOTICES["asserts_no_place"] is kept so the difference can be measured rather than assumed.
    notice = NOTICES[notice_kind]
    small = _font(20)
    draw.rectangle([0, HEIGHT - 34, WIDTH, HEIGHT], fill=(16, 16, 18))
    draw.text((14, HEIGHT - 28), notice, fill=(226, 226, 226), font=small)

    truth = {
        "index": index,
        "sign_text": sign_text or None,
        "place_name_is_visible": bool(sign_text),
        "people_drawn": 0,
        "notice_text": notice,
        "notice_kind": notice_kind,
        "objects": [dict(item, tier="salient" if item["what"] in SALIENT else "detail")
                    for item in drawn],
        "width": WIDTH,
        "height": HEIGHT,
    }
    return image, truth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--split", choices=("development", "held_out"), default="development")
    parser.add_argument("--notice", choices=tuple(NOTICES), default="plain")
    parser.add_argument("--photographic", action="store_true",
                        help="apply camera-like noise, blur and vignette")
    arguments = parser.parse_args()
    recipes = DEVELOPMENT if arguments.split == "development" else HELD_OUT
    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)
    truths = []
    for index, (sign_text, _signed) in enumerate(recipes):
        image, truth = scene(index, sign_text, arguments.notice)
        if arguments.photographic:
            image = photographic(image, index)
        truth['photographic'] = bool(arguments.photographic)
        exif = Image.Exif()
        exif[0x0110] = "Synthetic place camera"
        exif[0x9003] = f"2026:09:22 1{index}:0{index}:00"
        name = f"{arguments.split}-{index + 1:02d}.jpg"
        image.save(out / name, "JPEG", quality=82 if arguments.photographic else 92,
                   exif=exif)
        truth["file"] = name
        truth["split"] = arguments.split
        truths.append(truth)
    (out / f"ground-truth-{arguments.split}.json").write_text(
        json.dumps(truths, indent=2, sort_keys=True) + "\n"
    )
    print(f"{len(truths)} photographs and their ground truth in {out}")


if __name__ == "__main__":
    main()
