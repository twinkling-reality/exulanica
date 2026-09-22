"""Synthetic boards, some whole and some partly hidden, for asking whether the model can tell.

    python scripts/make_sign_completeness_probe.py OUT_DIR

A proposal can only be made to depend on whether a sign is complete if the model can see whether
it is complete. This corpus asks that and nothing else. Each photograph carries one nameplate:

*   **whole**: every letter visible. A third of these have a tree canopy drawn beside the board
    without touching it, so that "there is a tree near the sign" cannot pass for "the sign is
    partly hidden".
*   **covered**: a canopy drawn over part of the lettering, hiding the last word, the first word,
    or the middle of a single long word. This is the case the held-out split failed on.
*   **cut**: the board runs past the right edge of the photograph, so the lettering stops at the
    frame.

The names are new and appear in no other split. Development material only: no photograph here is
ever used to judge a wording.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_place_photographs import (
    HEIGHT, HORIZON, NOTICES, WIDTH, _bench, _box, _car, _facade, _font, _lamppost, photographic,
)

#: (state, how, text). ``how`` says where the cover goes for a covered board.
PROBE: tuple[tuple[str, str, str], ...] = (
    ("whole", "plain", "ASHWORTH HALL"),
    ("whole", "plain", "BELLMONT ROW"),
    ("whole", "plain", "CRANMORE HOUSE"),
    ("whole", "plain", "DUNSTAN ROW"),
    ("whole", "plain", "EVERLEIGH MEWS"),
    ("whole", "plain", "FAIRHOLME"),
    ("whole", "plain", "GLENARM HOUSE"),
    ("whole", "plain", "HOLLINS YARD"),
    ("whole", "tree_beside", "IVYBRIDGE HALL"),
    ("whole", "tree_beside", "JUNIPER COURT"),
    ("whole", "tree_beside", "KINGSMERE"),
    ("whole", "tree_beside", "LOXLEY HOUSE"),
    ("partial", "cover_last", "MARCHMONT HOUSE"),
    ("partial", "cover_last", "NEWBOLD COURT"),
    ("partial", "cover_last", "OAKLANDS HALL"),
    ("partial", "cover_last", "PRESTWICK ROW"),
    ("partial", "cover_first", "QUARRYDALE MEWS"),
    ("partial", "cover_first", "ROSLIN HOUSE"),
    ("partial", "cover_middle", "SANDRINGHAM"),
    ("partial", "cover_middle", "THORNBURY"),
    ("partial", "cut", "UPPERTHORPE TERRACE"),
    ("partial", "cut", "VANBRUGH CRESCENT"),
    ("partial", "cut", "WHITLOCK GARDENS"),
    ("partial", "cut", "YARDLEY BUILDINGS"),
)

BOARD = (340, 184, 940, 284)


def _canopy(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> dict[str, Any]:
    draw.ellipse(box, fill=(52, 118, 58))
    trunk_x = (box[0] + box[2]) // 2
    draw.rectangle([trunk_x - 16, box[3] - 20, trunk_x + 16, HORIZON + 30], fill=(96, 66, 42))
    return {"what": "tree", "box": _box(box[0], box[1], box[2], HORIZON + 30)}


def _cut_board(draw: ImageDraw.ImageDraw, text: str) -> list[dict[str, Any]]:
    """A building whose nameplate runs past the right edge of the photograph."""
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
    # Placed so that about a third of the lettering is past the frame, whatever the name's
    # length. A fixed start let two of the first four names end before the edge, which made
    # them whole boards recorded as cut ones.
    span = draw.textbbox((0, 0), text, font=font)
    width = span[2] - span[0]
    draw.text((WIDTH - (2 * width) // 3, top + 52), text, fill=(244, 240, 228), font=font)
    return [{"what": "building", "box": _box(left, top, WIDTH, HORIZON)},
            {"what": "sign", "box": _box(board[0], board[1], WIDTH, board[3])}]


def scene(index: int, state: str, how: str, text: str) -> tuple[Image.Image, dict[str, Any]]:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / HEIGHT
        above = (int(126 + 78 * t), int(168 + 54 * t), int(226 - 34 * t))
        below = (int(104 + 26 * t), int(112 + 18 * t), int(96 + 12 * t))
        draw.line([(0, y), (WIDTH, y)], fill=above if y < HORIZON else below)

    drawn: list[dict[str, Any]] = []
    if how == "cut":
        drawn += _cut_board(draw, text)
    else:
        drawn += _facade(draw, text)
        font = _font(58)
        whole = draw.textbbox((0, 0), text, font=font)
        width = whole[2] - whole[0]
        start = (BOARD[0] + BOARD[2]) // 2 - width // 2
        if how == "tree_beside":
            # Beside the board, not over it: a canopy that ends short of the board's left edge.
            drawn.append(_canopy(draw, (60, 120, BOARD[0] - 30, 330)))
        elif how == "cover_last":
            first = draw.textbbox((0, 0), text.split()[0] + " ", font=font)
            drawn.append(_canopy(draw, (start + (first[2] - first[0]) - 6, BOARD[1] - 70,
                                        BOARD[2] + 60, BOARD[3] + 90)))
        elif how == "cover_first":
            first = draw.textbbox((0, 0), text.split()[0], font=font)
            drawn.append(_canopy(draw, (BOARD[0] - 60, BOARD[1] - 70,
                                        start + (first[2] - first[0]) + 8, BOARD[3] + 90)))
        elif how == "cover_middle":
            third = width // 3
            drawn.append(_canopy(draw, (start + third, BOARD[1] - 70,
                                        start + 2 * third, BOARD[3] + 90)))
    drawn.append(_bench(draw, 380 + (index * 37) % 90, HORIZON + 150))
    if how != "cut":
        drawn.append(_lamppost(draw, 1010 - (index * 19) % 50, HORIZON + 120))
    drawn.append(_car(draw, 640 + (index * 29) % 80, HORIZON + 210,
                      [(168, 54, 48), (48, 82, 156), (206, 172, 56)][index % 3]))
    small = _font(20)
    draw.rectangle([0, HEIGHT - 34, WIDTH, HEIGHT], fill=(16, 16, 18))
    draw.text((14, HEIGHT - 28), NOTICES["plain"], fill=(226, 226, 226), font=small)
    return image, {"index": index, "state": state, "how": how, "text": text, "objects": drawn}


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    truths = []
    for index, (state, how, text) in enumerate(PROBE):
        image, truth = scene(index, state, how, text)
        image = photographic(image, index)
        exif = Image.Exif()
        exif[0x0110] = "Synthetic place camera"
        name = f"probe-{index + 1:02d}-{state}-{how}.jpg"
        image.save(out / name, "JPEG", quality=82, exif=exif)
        truth["file"] = name
        truths.append(truth)
    (out / "ground-truth-probe.json").write_text(json.dumps(truths, indent=2, sort_keys=True) + "\n")
    print(f"{len(truths)} probe photographs in {out}")


if __name__ == "__main__":
    main()
