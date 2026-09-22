"""Synthetic photographs for measuring when the vision pass proposes a place, and when it must not.

    python scripts/make_place_signage_photographs.py OUT_DIR --split place_development|place_held_out

No personal photograph is ever used. Every scene is drawn from a fixed recipe, so the bytes and
the ground truth are the same on every run.

Two arms, and the second matters more than the first:

*   **positive**: a legible place name on something that names a place, such as a nameplate on a
    building, a street sign, a park sign or a station sign. The vision pass is asked to propose a
    place from exactly this, so a miss here is the defect being fixed.
*   **negative**: no place-identifying text at all; text that names something other than a place
    (a product, a slogan, a person's name on a shirt); and a place board partly hidden, so only
    some of its words are visible. A proposal on any of these is a place the photograph does not
    show, and a prompt that makes the positive arm pass by producing them has made the product
    worse.

The ground truth records, per scene, the words of every text drawn in the frame and, for a
partly hidden board, only the words left visible. That is what makes an invented place countable:
a proposal whose name carries a word nothing in the frame shows was not read from the frame.

The recipes in ``make_place_photographs.py`` are left exactly as they are. A record already binds
those bytes, and this corpus asks a different question.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_place_photographs import (
    HEIGHT,
    HORIZON,
    NOTICES,
    WIDTH,
    _bench,
    _box,
    _car,
    _facade,
    _font,
    _lamppost,
    _tree,
    photographic,
)

#: (kind, arm, words). For a ``partial`` scene the words are (visible, hidden): the hidden ones are
#: drawn and then covered, so the model can see that a board carries more than it can read.
PLACE_DEVELOPMENT: tuple[tuple[str, str, Any], ...] = (
    ("nameplate", "positive", "LANTERN HOUSE"),
    ("street_sign", "positive", "CEDAR LANE"),
    ("park_sign", "positive", "ASHGROVE PARK"),
    ("station_sign", "positive", "WESTBRIDGE STATION"),
    ("no_text", "negative", ""),
    ("product", "negative", "FIZZ COLA"),
    ("slogan", "negative", "THINK BIG"),
    ("person_name", "negative", "SAM"),
    ("partial", "negative", ("OAKHURST", "LIBRARY")),
    ("slogan", "negative", "WELCOME"),
)

PLACE_HELD_OUT: tuple[tuple[str, str, Any], ...] = (
    ("nameplate", "positive", "CORBEL HOUSE"),
    ("nameplate", "positive", "ORCHARD MILL"),
    ("street_sign", "positive", "HARBOUR STREET"),
    ("street_sign", "positive", "LINDEN ROAD"),
    ("park_sign", "positive", "ELMWOOD PARK"),
    ("park_sign", "positive", "WILLOW COMMON"),
    ("station_sign", "positive", "NORTHGATE STATION"),
    ("station_sign", "positive", "FERRYSIDE STATION"),
    ("no_text", "negative", ""),
    ("no_text", "negative", ""),
    ("no_text", "negative", ""),
    ("product", "negative", "NOVA PHONES"),
    ("product", "negative", "DRINK FIZZ"),
    ("slogan", "negative", "SUMMER SALE"),
    ("slogan", "negative", "OPEN LATE"),
    ("person_name", "negative", "MARIA"),
    ("person_name", "negative", "DEV"),
    ("partial", "negative", ("HALCYON", "YARD")),
    ("partial", "negative", ("PENROSE", "GRANARY")),
    ("partial", "negative", ("", "TREVELYAN BATHS")),
)

#: The second experiment (option B). Built after the perception probe showed the model can tell a
#: whole board from a partly hidden one; the first development split held one partly hidden board,
#: which was too few to show a wording's pass on that kind was narrow. These carry more of them,
#: covered and cut by the frame, and every name is new.
PLACE_B_DEVELOPMENT: tuple[tuple[str, str, Any], ...] = (
    ("nameplate", "positive", "ALBURY HOUSE"),
    ("street_sign", "positive", "QUAYSIDE LANE"),
    ("park_sign", "positive", "BROOM PARK"),
    ("station_sign", "positive", "HILLCREST STATION"),
    ("partial", "negative", ("CARRINGTON", "HALL")),
    ("partial", "negative", ("LYNDHURST", "COURT")),
    ("partial_cut", "negative", "UNDERWOOD TERRACE"),
    ("partial_cut", "negative", "PEMBERTON GARDENS"),
    ("no_text", "negative", ""),
    ("product", "negative", "ZEST SODA"),
    ("person_name", "negative", "LEO"),
)

PLACE_B_HELD_OUT: tuple[tuple[str, str, Any], ...] = (
    ("nameplate", "positive", "GRANTHAM HOUSE"),
    ("nameplate", "positive", "ELDERSLIE MILL"),
    ("street_sign", "positive", "MARINER STREET"),
    ("street_sign", "positive", "CHESTNUT ROAD"),
    ("park_sign", "positive", "RAVEN PARK"),
    ("park_sign", "positive", "HAZEL COMMON"),
    ("station_sign", "positive", "EASTWICK STATION"),
    ("station_sign", "positive", "LOWFIELD STATION"),
    ("partial", "negative", ("WESTCOTT", "YARD")),
    ("partial", "negative", ("BRAMWELL", "GRANARY")),
    ("partial", "negative", ("", "SELBORNE BATHS")),
    ("partial_cut", "negative", "ASHCOMBE TERRACE"),
    ("partial_cut", "negative", "NORTHBROOK GARDENS"),
    ("no_text", "negative", ""),
    ("no_text", "negative", ""),
    ("product", "negative", "VOLT CELLS"),
    ("product", "negative", "FRESH MINT"),
    ("slogan", "negative", "BIG SAVINGS"),
    ("person_name", "negative", "ANNA"),
    ("person_name", "negative", "RAJ"),
)

SPLITS = {
    "place_development": PLACE_DEVELOPMENT,
    "place_held_out": PLACE_HELD_OUT,
    "place_b_development": PLACE_B_DEVELOPMENT,
    "place_b_held_out": PLACE_B_HELD_OUT,
}


def _centred(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, size: int,
             fill: tuple[int, int, int]) -> None:
    font = _font(size)
    span = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((box[0] + box[2]) // 2 - (span[2] - span[0]) // 2,
         (box[1] + box[3]) // 2 - (span[3] - span[1]) // 2 - span[1]),
        text, fill=fill, font=font,
    )


def _street_sign(draw: ImageDraw.ImageDraw, text: str, x: int) -> list[dict[str, Any]]:
    base = HORIZON + 170
    draw.rectangle([x - 8, base - 360, x + 8, base], fill=(70, 72, 78))
    blade = (x - 190, base - 360, x + 190, base - 296)
    draw.rectangle(blade, fill=(22, 108, 62), outline=(238, 238, 238), width=4)
    _centred(draw, blade, text, 38, (246, 246, 240))
    return [{"what": "sign", "box": _box(*blade)},
            {"what": "signpost", "box": _box(x - 8, base - 360, x + 8, base)}]


def _park_sign(draw: ImageDraw.ImageDraw, text: str, x: int) -> list[dict[str, Any]]:
    base = HORIZON + 150
    for post in (x - 170, x + 150):
        draw.rectangle([post, base - 210, post + 20, base], fill=(96, 66, 42))
    board = (x - 200, base - 250, x + 200, base - 150)
    draw.rectangle(board, fill=(118, 82, 48), outline=(64, 44, 26), width=5)
    _centred(draw, board, text, 44, (246, 232, 196))
    return [{"what": "sign", "box": _box(*board)}]


def _station(draw: ImageDraw.ImageDraw, text: str) -> list[dict[str, Any]]:
    left, right, top = 260, 1020, 210
    draw.rectangle([left, top, right, HORIZON], fill=(176, 170, 164),
                   outline=(84, 80, 76), width=5)
    draw.rectangle([left + 250, HORIZON - 190, right - 250, HORIZON], fill=(46, 46, 52))
    canopy = (left - 20, top + 150, right + 20, top + 176)
    draw.rectangle(canopy, fill=(60, 64, 72))
    board = (left + 60, top + 40, right - 60, top + 132)
    draw.rectangle(board, fill=(26, 58, 132), outline=(240, 240, 240), width=4)
    _centred(draw, board, text, 50, (250, 250, 250))
    return [{"what": "building", "box": _box(left, top, right, HORIZON)},
            {"what": "sign", "box": _box(*board)}]


def _billboard(draw: ImageDraw.ImageDraw, text: str) -> list[dict[str, Any]]:
    board = (300, 150, 980, 430)
    for pole in (420, 840):
        draw.rectangle([pole, 430, pole + 24, HORIZON + 40], fill=(90, 92, 98))
    draw.rectangle(board, fill=(206, 40, 44), outline=(40, 40, 40), width=6)
    # A drawn bottle, so the board reads as an advertisement for a thing rather than a name.
    draw.rounded_rectangle([340, 190, 420, 400], radius=26, fill=(250, 244, 236))
    draw.rectangle([366, 160, 394, 196], fill=(250, 244, 236))
    _centred(draw, (440, 150, 980, 430), text, 70, (255, 255, 255))
    return [{"what": "billboard", "box": _box(*board)}]


def _banner(draw: ImageDraw.ImageDraw, text: str) -> list[dict[str, Any]]:
    drawn = _facade(draw, "")
    banner = (340, 184, 940, 284)
    draw.rectangle(banner, fill=(238, 196, 40), outline=(60, 50, 20), width=4)
    _centred(draw, banner, text, 56, (30, 30, 34))
    return [*drawn, {"what": "banner", "box": _box(*banner)}]


def _person(draw: ImageDraw.ImageDraw, text: str, x: int) -> dict[str, Any]:
    base = HORIZON + 250
    head = 36
    draw.ellipse([x - head, base - 380, x + head, base - 308], fill=(198, 150, 118))
    torso = (x - 70, base - 304, x + 70, base - 140)
    draw.rectangle(torso, fill=(40, 96, 170))
    draw.rectangle([x - 104, base - 296, x - 72, base - 170], fill=(40, 96, 170))
    draw.rectangle([x + 72, base - 296, x + 104, base - 170], fill=(40, 96, 170))
    draw.rectangle([x - 60, base - 140, x - 12, base], fill=(46, 46, 60))
    draw.rectangle([x + 12, base - 140, x + 60, base], fill=(46, 46, 60))
    _centred(draw, torso, text, 40, (250, 250, 250))
    return {"what": "person", "box": _box(x - 104, base - 380, x + 104, base)}


def _partial(draw: ImageDraw.ImageDraw, visible: str, hidden: str) -> list[dict[str, Any]]:
    """A nameplate whose hidden words are drawn and then covered by a tree canopy."""
    full = f"{visible} {hidden}".strip()
    drawn = _facade(draw, full)
    board = (340, 184, 940, 284)
    font = _font(58)
    whole = draw.textbbox((0, 0), full, font=font)
    start_x = (board[0] + board[2]) // 2 - (whole[2] - whole[0]) // 2
    if visible:
        prefix = draw.textbbox((0, 0), f"{visible} ", font=font)
        cover_from = start_x + (prefix[2] - prefix[0]) - 6
        cover = (cover_from, board[1] - 70, board[2] + 60, board[3] + 90)
    else:
        cover = (board[0] - 40, board[1] - 70, board[2] + 40, board[3] + 90)
    draw.ellipse(cover, fill=(52, 118, 58))
    draw.rectangle([(cover[0] + cover[2]) // 2 - 16, cover[3] - 20,
                    (cover[0] + cover[2]) // 2 + 16, HORIZON + 30], fill=(96, 66, 42))
    drawn.append({"what": "tree", "box": _box(cover[0], cover[1], cover[2], HORIZON + 30)})
    return drawn


def _cut(draw: ImageDraw.ImageDraw, text: str) -> tuple[list[dict[str, Any]], str]:
    """A nameplate running past the right edge, and exactly the lettering left inside the frame.

    A glyph counts as visible once any part of it is inside the frame, because a reader may make
    out a letter the edge has half cut. The words returned are the whole visible words and every
    prefix of the final fragment, so "ASHCOMBE T" and "ASHCOMBE TE" are both readings of what
    is there, while "ASHCOMBE TERRACE" carries a word nothing in the frame shows.
    """
    left, top = 560, 150
    draw.rectangle([left, top, WIDTH + 200, HORIZON], fill=(206, 198, 186),
                   outline=(92, 88, 82), width=5)
    for column in range(4):
        wx = left + 44 + column * 170
        for row in range(2):
            wy = top + 190 + row * 150
            draw.rectangle([wx, wy, wx + 104, wy + 106], fill=(118, 150, 178),
                           outline=(64, 62, 60), width=3)
    board = (left + 40, top + 34, WIDTH + 160, top + 134)
    draw.rectangle(board, fill=(22, 36, 58), outline=(232, 226, 210), width=4)
    font = _font(58)
    width = draw.textbbox((0, 0), text, font=font)[2]
    x0 = WIDTH - (2 * width) // 3
    draw.text((x0, top + 52), text, fill=(244, 240, 228), font=font)
    visible = ""
    for end in range(1, len(text) + 1):
        # The left edge of glyph ``end - 1`` is the right edge of the text before it.
        if x0 + draw.textbbox((0, 0), text[: end - 1], font=font)[2] < WIDTH - 2:
            visible = text[:end]
    visible = visible.strip()
    words = visible.split()
    readings = words[:-1] + [words[-1][:n] for n in range(1, len(words[-1]) + 1)] if words else []
    return ([{"what": "building", "box": _box(left, top, WIDTH, HORIZON)},
             {"what": "sign", "box": _box(board[0], board[1], WIDTH, board[3])}],
            " ".join(readings))


def _words(text: str) -> list[str]:
    return [word for word in text.upper().replace("-", " ").split() if word]


def scene(index: int, kind: str, arm: str, words: Any) -> tuple[Image.Image, dict[str, Any]]:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / HEIGHT
        above = (int(126 + 78 * t), int(168 + 54 * t), int(226 - 34 * t))
        below = (int(104 + 26 * t), int(112 + 18 * t), int(96 + 12 * t))
        draw.line([(0, y), (WIDTH, y)], fill=above if y < HORIZON else below)

    people = 0
    place_name: str | None = None
    board_visible: list[str] = []
    other_text: list[str] = []
    drawn: list[dict[str, Any]] = []
    if kind == "nameplate":
        drawn += _facade(draw, words)
        place_name, board_visible = words, _words(words)
    elif kind == "street_sign":
        drawn += _facade(draw, "")
        drawn += _street_sign(draw, words, 180 + (index * 23) % 60)
        place_name, board_visible = words, _words(words)
    elif kind == "park_sign":
        drawn.append(_tree(draw, 260, HORIZON + 30, 1.3))
        drawn.append(_tree(draw, 1010, HORIZON + 20, 1.2))
        drawn += _park_sign(draw, words, 640)
        place_name, board_visible = words, _words(words)
    elif kind == "station_sign":
        drawn += _station(draw, words)
        place_name, board_visible = words, _words(words)
    elif kind == "no_text":
        drawn += _facade(draw, "")
    elif kind == "product":
        drawn += _billboard(draw, words)
        other_text = _words(words)
    elif kind == "slogan":
        drawn += _banner(draw, words)
        other_text = _words(words)
    elif kind == "person_name":
        drawn += _facade(draw, "")
        drawn.append(_person(draw, words, 1040 - (index * 17) % 60))
        other_text = _words(words)
        people = 1
    elif kind == "partial":
        visible, hidden = words
        drawn += _partial(draw, visible, hidden)
        board_visible = _words(visible)
    elif kind == "partial_cut":
        cut_drawn, visible = _cut(draw, words)
        drawn += cut_drawn
        board_visible = _words(visible)
    else:
        raise ValueError(kind)

    if kind not in ("park_sign", "station_sign"):
        drawn.append(_bench(draw, 380 + (index * 37) % 90, HORIZON + 150))
    if kind not in ("person_name", "street_sign", "partial_cut"):
        drawn.append(_lamppost(draw, 1010 - (index * 19) % 50, HORIZON + 120))
    drawn.append(_car(draw, 640 + (index * 29) % 80, HORIZON + 210,
                      [(168, 54, 48), (48, 82, 156), (206, 172, 56)][index % 3]))

    notice = NOTICES["plain"]
    small = _font(20)
    draw.rectangle([0, HEIGHT - 34, WIDTH, HEIGHT], fill=(16, 16, 18))
    draw.text((14, HEIGHT - 28), notice, fill=(226, 226, 226), font=small)

    truth = {
        "index": index,
        "kind": kind,
        "arm": arm,
        "place_name": place_name,
        # Words a reader can see on the place board. For a partial scene this is the visible
        # part only, which is what bounds an honest proposal.
        "place_board_visible_words": board_visible,
        # Words of text that names something other than a place.
        "other_text_words": other_text,
        "hidden_words": (
            _words(words[1]) if kind == "partial"
            else [w for w in _words(words) if w not in board_visible] if kind == "partial_cut"
            else []
        ),
        "notice_words": _words(notice),
        "people_drawn": people,
        "objects": drawn,
        "width": WIDTH,
        "height": HEIGHT,
    }
    return image, truth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--split", choices=tuple(SPLITS), required=True)
    arguments = parser.parse_args()
    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)
    truths = []
    for index, (kind, arm, words) in enumerate(SPLITS[arguments.split]):
        image, truth = scene(index, kind, arm, words)
        image = photographic(image, index)
        exif = Image.Exif()
        exif[0x0110] = "Synthetic place camera"
        exif[0x9003] = f"2026:09:22 1{index % 10}:0{index % 10}:00"
        name = f"{arguments.split}-{index + 1:02d}-{kind}.jpg"
        image.save(out / name, "JPEG", quality=82, exif=exif)
        truth["file"] = name
        truth["split"] = arguments.split
        truths.append(truth)
    (out / f"ground-truth-{arguments.split}.json").write_text(
        json.dumps(truths, indent=2, sort_keys=True) + "\n"
    )
    print(f"{len(truths)} photographs and their ground truth in {out}")


if __name__ == "__main__":
    main()
