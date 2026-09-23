"""Synthetic photographs for the fourth place-proposal experiment: a model plus a written rule.

    python scripts/make_place_proposal_d_photographs.py OUT_DIR --split place_d_development|place_d_held_out

No personal photograph is ever used, and every scene is drawn from a fixed recipe, so the bytes and
the ground truth are the same on every run. Every place name, product, slogan and personal name
here is new: no word of any text drawn below appears in any split drawn for an earlier experiment
(``make_place_photographs.py``, ``make_place_signage_photographs.py`` and
``make_sign_completeness_probe.py``), and this script refuses to draw if one does. The notice
every scene carries at its bottom edge is the one exception, by design.

The kinds are the ones the earlier experiments failed on or never covered:

*   **positive**, a whole place name: nameplates on buildings, some with a tree beside the board
    and not over it; street blades, one of which a completeness judgement once called partly
    hidden; park signs; station signs; and a street blade with a banner carrying a slogan on the
    building behind it, so that the most prominent sign is not the one naming the place.
*   **negative**, no whole place name: boards covered by a canopy over the last word, over the
    first word, or over the middle of a single word; boards entirely covered; boards cut by the
    edge of the frame; no text; products, including one whose name reads like a place; slogans;
    a personal name on a shirt; and a covered or cut board beside a whole notice board, so that
    the most prominent whole sign is not the one carrying the partial name.

The ground truth records, for each scene, the words of every text drawn and the words a reader can
see, so a proposal carrying a word the frame does not show is countable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_place_photographs as first_corpus
import make_place_signage_photographs as signage_corpus
import make_sign_completeness_probe as probe_corpus
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
    photographic,
)
from make_place_signage_photographs import (
    _banner,
    _billboard,
    _centred,
    _cut,
    _park_sign,
    _partial,
    _person,
    _station,
    _street_sign,
    _words,
)
from make_sign_completeness_probe import BOARD, _canopy

#: (kind, arm, text). A covered kind's text is (visible, hidden) for the last word covered and
#: (hidden, visible) for the first; a two-sign kind's text is (place board, notice or banner).
PLACE_D_DEVELOPMENT: tuple[tuple[str, str, Any], ...] = (
    ("nameplate", "positive", "ARKEN GALLERY"),
    ("nameplate_tree_beside", "positive", "BOWSCALE ROOMS"),
    ("street_sign", "positive", "CATTERLEN RISE"),
    ("street_sign", "positive", "DENTLY VALE"),
    ("park_sign", "positive", "ELSMOR COPSE"),
    ("station_sign", "positive", "FELLGARTH PARKWAY"),
    ("two_signs", "positive", ("GILLA PASSAGE", "FREE REFILLS")),
    ("covered_last", "negative", ("HARTWELD", "BARN")),
    ("covered_first", "negative", ("IRLOW", "TANNERY")),
    ("covered_middle", "negative", "MARRICKHOLME"),
    ("hidden", "negative", "NENTON ROPERY"),
    ("cut", "negative", "OUSEWICK CARILLON"),
    ("cut", "negative", "PLUMWORTH AQUEDUCT"),
    ("no_text", "negative", ""),
    ("product", "negative", "COMET CHIPS"),
    ("person_name", "negative", "KWAME"),
    ("two_signs_cut", "negative", ("QUARNWOOD BELFRY", "MIND THE STEP")),
)

PLACE_D_HELD_OUT: tuple[tuple[str, str, Any], ...] = (
    ("nameplate", "positive", "BELWETH LODGE"),
    ("nameplate", "positive", "CORVANE HOSTEL"),
    ("nameplate", "positive", "DRAY PAVILION"),
    ("nameplate_tree_beside", "positive", "FENWY CHAMBERS"),
    ("nameplate_tree_beside", "positive", "GOLDTHORNE INN"),
    ("street_sign", "positive", "ISLING AVENUE"),
    ("street_sign", "positive", "KILMARROW WAY"),
    ("street_sign", "positive", "LANGTON CLOSE"),
    ("street_sign", "positive", "MOSSVALE DRIVE"),
    ("park_sign", "positive", "NETTLEY GREEN"),
    ("park_sign", "positive", "OSWY HEATH"),
    ("park_sign", "positive", "PINDER WOODS"),
    ("station_sign", "positive", "RUSHMER JUNCTION"),
    ("station_sign", "positive", "STAVENDALE HALT"),
    ("station_sign", "positive", "TREGALLO CENTRAL"),
    ("two_signs", "positive", ("ULVER PARADE", "GRAND OPENING")),
    ("two_signs", "positive", ("VARN SQUARE", "HAPPY HOUR")),
    ("two_signs", "positive", ("WYNDCOL WALK", "BACK SOON")),
    ("covered_last", "negative", ("ABERGLEN", "WORKS")),
    ("covered_last", "negative", ("BRAKEN", "HOSPICE")),
    ("covered_last", "negative", ("CULLER", "ARMOURY")),
    ("covered_first", "negative", ("DUNKER", "FORGE")),
    ("covered_first", "negative", ("EGLING", "SMITHY")),
    ("covered_middle", "negative", "GRIMSTONEBURY"),
    ("hidden", "negative", "HAXTON PRIORY"),
    ("hidden", "negative", "INGLE FOUNDRY"),
    ("cut", "negative", "JESMONDVALE VIADUCT"),
    ("cut", "negative", "KELDHOLLOW OBSERVATORY"),
    ("cut", "negative", "LUDWORTHY COLONNADE"),
    ("cut", "negative", "MELBRAITH ESPLANADE"),
    ("no_text", "negative", ""),
    ("no_text", "negative", ""),
    ("no_text", "negative", ""),
    ("product", "negative", "ORBIT GUM"),
    ("product", "negative", "NIMBUS TEA"),
    ("product", "negative", "FROSTWELL"),
    ("slogan", "negative", "STAY CURIOUS"),
    ("slogan", "negative", "SHOP LOCAL"),
    ("person_name", "negative", "OMAR"),
    ("person_name", "negative", "PRIYA"),
    ("person_name", "negative", "TOMAS"),
    ("two_signs_cut", "negative", ("QUERNHOLT BASTION", "KEEP OFF GRASS")),
    ("two_signs_cut", "negative", ("SKELTHWAITE CITADEL", "QUEUE HERE")),
    ("two_signs_covered", "negative", (("THREL", "MALTINGS"), "DOGS ON LEADS")),
)

SPLITS = {"place_d_development": PLACE_D_DEVELOPMENT, "place_d_held_out": PLACE_D_HELD_OUT}

#: Room kept clear between lettering and the edge of the board it is painted on. Two earlier
#: drawings let a name run off its board, which makes a whole board look cut.
_MARGIN_PX = 12

#: Room kept clear between a whole sign and the edge of the frame. The street blade recipe this
#: corpus inherits places a blade at ``180 + (index * 23) % 60``, 190 pixels either side, so at
#: some indices its left edge lies outside the frame (by 1 pixel at index 3 and 6 pixels at index
#: 8), and a whole sign touching the edge can fairly be judged cut by it.
_FRAME_MARGIN_PX = 24

#: Kinds whose place board runs past the right edge of the frame by design.
_CUT_KINDS = frozenset({"cut", "two_signs_cut"})


def _texts(text: Any) -> list[str]:
    if isinstance(text, str):
        return [text] if text else []
    return [part for item in text for part in _texts(item)]


def _earlier_words() -> set[str]:
    """Every word drawn by an earlier experiment's corpus, from the recipes themselves."""
    drawn: set[str] = set()
    for name, _signed in first_corpus.DEVELOPMENT + first_corpus.HELD_OUT:
        drawn.update(_words(name))
    for split in signage_corpus.SPLITS.values():
        for _kind, _arm, text in split:
            for part in _texts(text):
                drawn.update(_words(part))
    for _state, _how, text in probe_corpus.PROBE:
        drawn.update(_words(text))
    return drawn


def _fit(draw: ImageDraw.ImageDraw, text: str, size: int, width: int, where: str) -> None:
    span = draw.textbbox((0, 0), text, font=_font(size))
    if span[2] - span[0] > width - 2 * _MARGIN_PX:
        raise SystemExit(f"{text!r} does not fit its {where}: redraw with a shorter name")


def _notice_board(draw: ImageDraw.ImageDraw, text: str, x: int) -> dict[str, Any]:
    """A small painted notice on two posts, whole and legible, naming no place."""
    base = HORIZON + 150
    for post in (x - 120, x + 108):
        draw.rectangle([post, base - 170, post + 12, base], fill=(74, 74, 80))
    board = (x - 140, base - 210, x + 140, base - 140)
    _fit(draw, text, 26, board[2] - board[0], "notice board")
    draw.rectangle(board, fill=(236, 236, 228), outline=(40, 40, 44), width=4)
    _centred(draw, board, text, 26, (180, 30, 30))
    return {"what": "sign", "box": _box(*board)}


def _tree_beside(draw: ImageDraw.ImageDraw) -> dict[str, Any]:
    """A canopy that ends short of the board's left edge, as in the probe."""
    return _canopy(draw, (60, 120, BOARD[0] - 30, 330))


def _covered(
    draw: ImageDraw.ImageDraw, text: str, how: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """A nameplate with a canopy over its first word or over the middle of a single word.

    Returns what was drawn and the visible words. A glyph counts as visible once any part of it is
    outside the canopy, as ``_cut`` counts one at the frame edge.
    """
    drawn = _facade(draw, text)
    font = _font(58)
    width = draw.textbbox((0, 0), text, font=font)[2] - draw.textbbox((0, 0), text, font=font)[0]
    start = (BOARD[0] + BOARD[2]) // 2 - width // 2
    if how == "covered_first":
        first = draw.textbbox((0, 0), text.split()[0], font=font)
        drawn.append(
            _canopy(
                draw,
                (BOARD[0] - 60, BOARD[1] - 70, start + (first[2] - first[0]) + 8, BOARD[3] + 90),
            )
        )
        return drawn, text.split()[1:]
    if how == "covered_middle":
        third = width // 3
        cover = (start + third, start + 2 * third)
        drawn.append(_canopy(draw, (cover[0], BOARD[1] - 70, cover[1], BOARD[3] + 90)))
        prefix = "".join(
            text[i]
            for i in range(len(text))
            if start + draw.textbbox((0, 0), text[:i], font=font)[2] < cover[0]
        )
        suffix = "".join(
            text[i]
            for i in range(len(text))
            if start + draw.textbbox((0, 0), text[: i + 1], font=font)[2] > cover[1]
        )
        return drawn, [fragment for fragment in (prefix, suffix) if fragment]
    raise ValueError(f"no covered drawing named {how!r}")


def scene(index: int, kind: str, arm: str, text: Any) -> tuple[Image.Image, dict[str, Any]]:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / HEIGHT
        above = (int(126 + 78 * t), int(168 + 54 * t), int(226 - 34 * t))
        below = (int(104 + 26 * t), int(112 + 18 * t), int(96 + 12 * t))
        draw.line([(0, y), (WIDTH, y)], fill=above if y < HORIZON else below)

    place_name: str | None = None
    board_text: str | None = None
    board_visible: list[str] = []
    other_text: list[str] = []
    hidden: list[str] = []
    people = 0
    drawn: list[dict[str, Any]] = []
    if kind in ("nameplate", "nameplate_tree_beside"):
        _fit(draw, text, 58, BOARD[2] - BOARD[0], "nameplate")
        drawn += _facade(draw, text)
        if kind == "nameplate_tree_beside":
            drawn.append(_tree_beside(draw))
        place_name, board_text, board_visible = text, text, _words(text)
    elif kind == "street_sign":
        _fit(draw, text, 38, 380, "street blade")
        drawn += _facade(draw, "")
        drawn += _street_sign(draw, text, 190 + _FRAME_MARGIN_PX + (index * 23) % 60)
        place_name, board_text, board_visible = text, text, _words(text)
    elif kind == "park_sign":
        _fit(draw, text, 44, 400, "park sign")
        drawn.append(first_corpus._tree(draw, 260, HORIZON + 30, 1.3))
        drawn.append(first_corpus._tree(draw, 1010, HORIZON + 20, 1.2))
        drawn += _park_sign(draw, text, 640)
        place_name, board_text, board_visible = text, text, _words(text)
    elif kind == "station_sign":
        _fit(draw, text, 50, 640, "station board")
        drawn += _station(draw, text)
        place_name, board_text, board_visible = text, text, _words(text)
    elif kind == "two_signs":
        place, slogan = text
        _fit(draw, slogan, 56, 600, "banner")
        _fit(draw, place, 38, 380, "street blade")
        drawn += _banner(draw, slogan)
        drawn += _street_sign(draw, place, 190 + _FRAME_MARGIN_PX + 16)
        place_name, board_text, board_visible = place, place, _words(place)
        other_text = _words(slogan)
    elif kind == "no_text":
        drawn += _facade(draw, "")
    elif kind == "product":
        _fit(draw, text, 70, 540, "billboard")
        drawn += _billboard(draw, text)
        other_text = _words(text)
    elif kind == "slogan":
        _fit(draw, text, 56, 600, "banner")
        drawn += _banner(draw, text)
        other_text = _words(text)
    elif kind == "person_name":
        # The shirt is the torso and both sleeves, which ``_person`` paints one colour.
        _fit(draw, text, 40, 208, "shirt")
        drawn += _facade(draw, "")
        drawn.append(_person(draw, text, 1040 - (index * 17) % 60))
        other_text = _words(text)
        people = 1
    elif kind == "covered_last":
        visible, covered = text
        _fit(draw, f"{visible} {covered}", 58, BOARD[2] - BOARD[0], "nameplate")
        drawn += _partial(draw, visible, covered)
        board_text, board_visible, hidden = f"{visible} {covered}", _words(visible), _words(covered)
    elif kind == "covered_first":
        covered, visible = text
        _fit(draw, f"{covered} {visible}", 58, BOARD[2] - BOARD[0], "nameplate")
        cover_drawn, seen = _covered(draw, f"{covered} {visible}", kind)
        drawn += cover_drawn
        board_text, board_visible, hidden = f"{covered} {visible}", seen, _words(covered)
    elif kind == "covered_middle":
        _fit(draw, text, 58, BOARD[2] - BOARD[0], "nameplate")
        cover_drawn, seen = _covered(draw, text, kind)
        drawn += cover_drawn
        board_text, board_visible, hidden = text, seen, _words(text)
    elif kind == "hidden":
        _fit(draw, text, 58, BOARD[2] - BOARD[0], "nameplate")
        drawn += _partial(draw, "", text)
        board_text, hidden = text, _words(text)
    elif kind == "cut":
        cut_drawn, visible = _cut(draw, text)
        drawn += cut_drawn
        board_text, board_visible = text, _words(visible)
        hidden = [word for word in _words(text) if word not in board_visible]
    elif kind == "two_signs_cut":
        place, notice = text
        cut_drawn, visible = _cut(draw, place)
        drawn += cut_drawn
        drawn.append(_notice_board(draw, notice, 250))
        board_text, board_visible, other_text = place, _words(visible), _words(notice)
        hidden = [word for word in _words(place) if word not in board_visible]
    elif kind == "two_signs_covered":
        (visible, covered), notice = text
        _fit(draw, f"{visible} {covered}", 58, BOARD[2] - BOARD[0], "nameplate")
        drawn += _partial(draw, visible, covered)
        drawn.append(_notice_board(draw, notice, 140 + _FRAME_MARGIN_PX))
        board_text = f"{visible} {covered}"
        board_visible, hidden, other_text = _words(visible), _words(covered), _words(notice)
    else:
        raise ValueError(f"no scene is drawn for the kind {kind!r}")

    # Every sign lies inside the frame with room to spare, except a board cut by the frame on
    # purpose, which is the one that reaches its right edge.
    for item in drawn:
        if item["what"] != "sign":
            continue
        left = item["box"]["x"] * WIDTH
        right = left + item["box"]["w"] * WIDTH
        top = item["box"]["y"] * HEIGHT
        if kind in _CUT_KINDS and right >= WIDTH - 0.5:
            continue
        if (
            left < _FRAME_MARGIN_PX - 0.5
            or right > WIDTH - _FRAME_MARGIN_PX + 0.5
            or (top < _FRAME_MARGIN_PX - 0.5)
        ):
            raise SystemExit(f"a sign in scene {index} ({kind}) touches the frame edge")

    if kind not in ("park_sign", "station_sign"):
        drawn.append(_bench(draw, 380 + (index * 37) % 90, HORIZON + 150))
    if kind not in ("person_name", "street_sign", "two_signs", "cut", "two_signs_cut"):
        drawn.append(_lamppost(draw, 1010 - (index * 19) % 50, HORIZON + 120))
    drawn.append(
        _car(
            draw,
            640 + (index * 29) % 80,
            HORIZON + 210,
            [(168, 54, 48), (48, 82, 156), (206, 172, 56)][index % 3],
        )
    )

    notice = NOTICES["plain"]
    draw.rectangle([0, HEIGHT - 34, WIDTH, HEIGHT], fill=(16, 16, 18))
    draw.text((14, HEIGHT - 28), notice, fill=(226, 226, 226), font=_font(20))

    truth = {
        "index": index,
        "kind": kind,
        "arm": arm,
        "place_name": place_name,
        # Everything painted on the board carrying a place name, including what is covered or cut
        # away. A whole visible word is a word of this that is also among the visible words.
        "board_text": board_text,
        # Words a reader can see on the board carrying a place name, whole or not. For a covered
        # or cut board this is the visible part only.
        "place_board_visible_words": board_visible,
        # Words drawn on the board and then covered or cut away.
        "hidden_words": hidden,
        # Words of whole text that names something other than a place.
        "other_text_words": other_text,
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

    earlier = _earlier_words()
    other_split = {
        word
        for name, recipes in SPLITS.items()
        if name != arguments.split
        for _kind, _arm, text in recipes
        for part in _texts(text)
        for word in _words(part)
    }
    for _kind, _arm, text in SPLITS[arguments.split]:
        for part in _texts(text):
            reused = [word for word in _words(part) if word in earlier or word in other_split]
            if reused:
                raise SystemExit(f"{part!r} reuses {reused}: every word drawn here must be new")

    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)
    truths = []
    for index, (kind, arm, text) in enumerate(SPLITS[arguments.split]):
        image, truth = scene(index, kind, arm, text)
        image = photographic(image, index)
        exif = Image.Exif()
        exif[0x0110] = "Synthetic place camera"
        exif[0x9003] = f"2026:09:23 1{index % 10}:{index % 60:02d}:00"
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
