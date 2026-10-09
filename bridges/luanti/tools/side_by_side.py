"""Put a game window's picture and a world's picture of the same moment side by side.

    <checkout>/.venv/bin/python bridges/luanti/tools/side_by_side.py PLAN OUT

``PLAN`` is a JSON file naming each pair: ``{"pairs": [{"name": "1-crossing", "left": {"file":
"...", "words": "..."}, "right": {"file": "...", "words": "..."}}]}``, files relative to the plan's
folder or absolute, words the caption under each picture. Each pair becomes ``OUT/<name>.jpg``:
both pictures scaled to one height on a dark ground, each with its words beneath.
``OUT/side-by-side.json`` lists every picture made with its digest and the digests of the two it
was made from, so a record can name them.

The pictures a pair is made from keep their own licences (a game's art stays under the game's), so
the pictures made here are kept beside them and never committed. The captions' lettering is Barlow
(SIL Open Font License), from the repository's assets/fonts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CHECKOUT = Path(__file__).resolve().parents[3]
FONT = CHECKOUT / "assets" / "fonts" / "barlow" / "Barlow-SemiBold.ttf"
#: The height each picture is drawn at, in pixels.
HEIGHT = 720
#: The space around and between the pictures, and the band for the words under them, in pixels.
MARGIN = 24
GAP = 24
WORDS_BAND = 72
WORDS_SIZE = 26
GROUND = (14, 10, 26)
INK = (236, 232, 244)
#: A JPEG at this quality, the one the repository's browser captures use.
QUALITY = 85


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scaled(path: Path) -> Image.Image:
    with Image.open(path) as image:
        picture = image.convert("RGB")
    width = round(picture.width * HEIGHT / picture.height)
    return picture.resize((width, HEIGHT), Image.Resampling.LANCZOS)


def _fitted(draw: ImageDraw.ImageDraw, words: str, font: Any, width: int) -> str:
    """The words, cut with an ellipsis where they would run past ``width``."""
    if draw.textlength(words, font=font) <= width:
        return words
    while words and draw.textlength(words + "...", font=font) > width:
        words = words[:-1]
    return words.rstrip() + "..."


def compose(left: Path, right: Path, left_words: str, right_words: str, out: Path) -> None:
    pictures = [_scaled(left), _scaled(right)]
    width = 2 * MARGIN + GAP + sum(picture.width for picture in pictures)
    sheet = Image.new("RGB", (width, 2 * MARGIN + HEIGHT + WORDS_BAND), GROUND)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(FONT), WORDS_SIZE)
    x = MARGIN
    for picture, words in zip(pictures, (left_words, right_words), strict=True):
        sheet.paste(picture, (x, MARGIN))
        draw.text(
            (x, MARGIN + HEIGHT + WORDS_BAND // 2),
            _fitted(draw, words, font, picture.width),
            font=font,
            fill=INK,
            anchor="lm",
        )
        x += picture.width + GAP
    sheet.save(out, "JPEG", quality=QUALITY)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("plan", type=Path)
    parser.add_argument("out", type=Path)
    arguments = parser.parse_args(argv)
    plan = json.loads(arguments.plan.read_text())
    arguments.out.mkdir(parents=True, exist_ok=True)
    made = []
    for pair in plan["pairs"]:
        sides = {side: arguments.plan.parent / pair[side]["file"] for side in ("left", "right")}
        out = arguments.out / f"{pair['name']}.jpg"
        compose(sides["left"], sides["right"], pair["left"]["words"], pair["right"]["words"], out)
        made.append(
            {
                "file": out.name,
                "sha256": _digest(out),
                "from": {
                    side: {"file": path.name, "sha256": _digest(path)}
                    for side, path in sides.items()
                },
                "words": {side: pair[side]["words"] for side in ("left", "right")},
            }
        )
    (arguments.out / "side-by-side.json").write_text(
        json.dumps({"profile": "exulanica-gate.side-by-side/v1", "pictures": made}, indent=2) + "\n"
    )
    print(json.dumps({"out": str(arguments.out), "pictures": len(made)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
