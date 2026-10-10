"""Cut the demo's film from recorded takes, by a cut list that is data.

    uv run python scripts/demo/cut_film.py <cut-list.json> --out <film.mp4> [--dry-run]

A cut list (``exulanica.film-cut/v1``) states the frame (width, height, frames a second), the font
(a file, relative to the cut list), the ground and ink colours, and in order the film's parts: a
card (lines of words on the film's ground, for a number of seconds) or a stretch of a take (a file
relative to the cut list, its in and out points in seconds, a speed, and a caption). A stretch
played faster than it was recorded carries its speed on screen ("4x"), so nothing is quietly
hurried, and a take is fitted inside the frame without stretching. A stretch may also state a
``crop`` (the part of the take's own picture it shows, ``[x, y, w, h]``), ``insets`` (parts of the
same picture shown again larger on top of it, each a ``crop``, where it lies ``at`` ``[x, y]``, its
``width``, and optionally ``from_s`` and ``to_s`` within the stretch), and a ``side`` (a panel beside
the take with a ``title``, an optional ``note`` and ``lines`` that each appear ``at`` their second
of the stretch, in a ``tone``: plain, dim or hot), for what happened outside the page: another
program's own log, a game's own words. Cards, captions and panels are drawn
here as pictures with the cut list's font and laid over the takes by ffmpeg, so the film needs no
ffmpeg built with a text renderer. The script names no scene, beat or caption: everything it shows
comes from the cut list. ``--dry-run`` draws the pictures and prints the ffmpeg command instead of
running it.

Pillow draws; ffmpeg 6 or later on the path cuts.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CUT_PROFILE = "exulanica.film-cut/v1"
#: The most a stretch may be sped up: beyond it a viewer cannot follow what happens.
SPEED_MAXIMUM = 8
#: The share of the frame's width a side panel takes when it states none, and the shares it may state.
SIDE_SHARE = 0.38
SIDE_SHARES = (0.25, 0.5)
TONES = ("plain", "dim", "hot")
#: The colour of a hot line and of an inset's edge when the cut list states no ``accent``.
ACCENT = "#ffd24a"
_COLOUR = re.compile(r"#[0-9a-f]{6}")


class CutRefused(ValueError):
    """A cut list this script will not cut, by what is wrong."""


def read_cut(path: Path) -> dict[str, Any]:
    cut = json.loads(path.read_text(encoding="utf-8"))
    if cut.get("profile") != CUT_PROFILE:
        raise CutRefused(f"{path} is not an {CUT_PROFILE} document")
    frame = cut["frame"]
    if any(type(frame[k]) is not int or frame[k] <= 0 for k in ("width", "height", "fps")):
        raise CutRefused("the frame states a whole width, height and frames a second")
    for key in ("ground", "ink"):
        if _COLOUR.fullmatch(cut[key]) is None:
            raise CutRefused(f"{key} is a colour written #rrggbb")
    if not cut["parts"]:
        raise CutRefused("a film has at least one part")
    for index, part in enumerate(cut["parts"]):
        where = f"parts[{index}]"
        if part["kind"] == "card":
            if not part["lines"] or not part["seconds"] > 0:
                raise CutRefused(f"{where}: a card states its lines and how long it shows")
        elif part["kind"] == "take":
            if not 0 <= part["in_s"] < part["out_s"]:
                raise CutRefused(f"{where}: a take ends after it starts")
            if type(part["speed"]) is not int or not 1 <= part["speed"] <= SPEED_MAXIMUM:
                raise CutRefused(f"{where}: a whole speed from 1 to {SPEED_MAXIMUM}")
            _read_extras(where, part, frame)
        else:
            raise CutRefused(f"{where}: a part is a card or a take")
    return cut


def _box(where: str, value: object) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(n) is not int or n < 0 for n in value)
        or value[2] == 0
        or value[3] == 0
    ):
        raise CutRefused(f"{where}: a crop is four whole numbers, x, y, width and height")


def _read_extras(where: str, part: Mapping[str, Any], frame: Mapping[str, int]) -> None:
    """A take's optional crop, insets and side panel, each refused by what is wrong with it."""
    length = (part["out_s"] - part["in_s"]) / part["speed"]
    if "crop" in part:
        _box(f"{where}.crop", part["crop"])
    for index, inset in enumerate(part.get("insets", [])):
        here = f"{where}.insets[{index}]"
        _box(f"{here}.crop", inset.get("crop"))
        at, wide = inset.get("at"), inset.get("width")
        if not isinstance(at, list) or len(at) != 2 or any(type(n) is not int or n < 0 for n in at):
            raise CutRefused(f"{here}: an inset lies at a whole x and y of the frame")
        if type(wide) is not int or not 0 < wide <= frame["width"] - at[0]:
            raise CutRefused(f"{here}: an inset's width fits the frame from where it lies")
        start, end = inset.get("from_s", 0), inset.get("to_s", length)
        if not 0 <= start < end <= length:
            raise CutRefused(f"{here}: an inset shows within its stretch")
    side = part.get("side")
    if side is None:
        return
    if not side.get("title") or not side.get("lines"):
        raise CutRefused(f"{where}.side: a side panel states its title and its lines")
    low, high = SIDE_SHARES
    if not low <= side.get("share", SIDE_SHARE) <= high:
        raise CutRefused(f"{where}.side: a side panel takes {low} to {high} of the frame's width")
    for index, line in enumerate(side["lines"]):
        here = f"{where}.side.lines[{index}]"
        if not line.get("text") or not 0 <= line.get("at", -1) < length:
            raise CutRefused(f"{here}: a line states its words and appears within its stretch")
        if line.get("tone", "plain") not in TONES:
            raise CutRefused(f"{here}: a line's tone is one of {', '.join(TONES)}")


def seconds(cut: Mapping[str, Any]) -> float:
    """How long the film runs, from the cut list alone."""
    total = 0.0
    for part in cut["parts"]:
        if part["kind"] == "card":
            total += part["seconds"]
        else:
            total += (part["out_s"] - part["in_s"]) / part["speed"]
    return total


def _rgb(colour: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16), alpha)


def _size(frame: Mapping[str, int]) -> int:
    """The film's text size, in pixels, for its frame."""
    return max(24, frame["height"] // 30)


def draw_card(cut: Mapping[str, Any], lines: Sequence[str], font: Path) -> Image.Image:
    """A card: its first line large, the rest below, centred on the film's ground."""
    frame = cut["frame"]
    width, height, size = frame["width"], frame["height"], _size(frame)
    image = Image.new("RGB", (width, height), _rgb(cut["ground"])[:3])
    pen = ImageDraw.Draw(image)
    faces = [
        ImageFont.truetype(str(font), round(size * (1.6 if n == 0 else 1.0)))
        for n in range(len(lines))
    ]
    step = round(size * 1.6)
    top = height // 2 - step * len(lines) // 2
    for n, (line, face) in enumerate(zip(lines, faces, strict=True)):
        pen.text((width // 2, top + n * step), line, font=face, fill=_rgb(cut["ink"]), anchor="mm")
    return image


def draw_overlay(
    cut: Mapping[str, Any], caption: str | None, speed: int, font: Path
) -> Image.Image:
    """What lies over a take: its caption in a box at the foot of the frame, and its speed at the
    top right when it plays faster than it was recorded; transparent elsewhere."""
    frame = cut["frame"]
    width, height, size = frame["width"], frame["height"], _size(frame)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    face = ImageFont.truetype(str(font), size)
    box = _rgb(cut["ground"], round(255 * 0.72))
    if caption:
        left, top, right, bottom = pen.textbbox(
            (width // 2, height - 2 * size), caption, font=face, anchor="mm"
        )
        margin = size // 2
        pen.rectangle((left - margin, top - margin, right + margin, bottom + margin), fill=box)
        pen.text(
            (width // 2, height - 2 * size), caption, font=face, fill=_rgb(cut["ink"]), anchor="mm"
        )
    if speed != 1:
        mark = f"{speed}x"
        left, top, right, bottom = pen.textbbox((width - size, size), mark, font=face, anchor="ra")
        margin = size // 3
        pen.rectangle((left - margin, top - margin, right + margin, bottom + margin), fill=box)
        pen.text((width - size, size), mark, font=face, fill=_rgb(cut["ink"]), anchor="ra")
    return image


def side_width(cut: Mapping[str, Any], side: Mapping[str, Any] | None) -> int:
    """How many of the frame's pixels a take's side panel takes: none without one, else an even
    number, so the take beside it keeps an even width."""
    if side is None:
        return 0
    return round(cut["frame"]["width"] * side.get("share", SIDE_SHARE)) // 2 * 2


def draw_side(
    cut: Mapping[str, Any], side: Mapping[str, Any], font: Path
) -> tuple[Image.Image, list[Image.Image]]:
    """A side panel: its ground with the title and the note, and one picture for each line holding
    that line alone where it stands, so a line is laid over the film from its own second. Words are
    wrapped to the panel; everything right of the panel is transparent."""
    frame = cut["frame"]
    width, height, size = frame["width"], frame["height"], _size(frame)
    wide = side_width(cut, side)
    margin = size
    room = wide - 2 * margin
    title_face = ImageFont.truetype(str(font), round(size * 1.05))
    face = ImageFont.truetype(str(font), round(size * 0.8))
    accent = _rgb(cut.get("accent", ACCENT))
    ink = _rgb(cut["ink"])
    tones = {"plain": ink, "dim": (*ink[:3], 150), "hot": accent}
    panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pen = ImageDraw.Draw(panel)
    ground = _rgb(cut["ground"])
    pen.rectangle((0, 0, wide - 1, height - 1), fill=tuple(max(0, c - 12) for c in ground[:3]))

    def wrapped(words: str, with_face: ImageFont.FreeTypeFont) -> list[str]:
        rows: list[str] = []
        for paragraph in words.split("\n"):
            row = ""
            for word in paragraph.split(" "):
                longer = word if not row else f"{row} {word}"
                if row and pen.textlength(longer, font=with_face) > room:
                    rows.append(row)
                    row = word
                else:
                    row = longer
            rows.append(row)
        return rows

    top = margin
    for row in wrapped(side["title"], title_face):
        pen.text((margin, top), row, font=title_face, fill=accent)
        top += round(size * 1.4)
    for row in wrapped(side.get("note", ""), face) if side.get("note") else []:
        pen.text((margin, top), row, font=face, fill=tones["dim"])
        top += round(size * 1.05)
    top += size // 2
    lines: list[Image.Image] = []
    for line in side["lines"]:
        picture = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        line_pen = ImageDraw.Draw(picture)
        for row in wrapped(line["text"], face):
            line_pen.text((margin, top), row, font=face, fill=tones[line.get("tone", "plain")])
            top += round(size * 1.05)
        top += size // 4
        lines.append(picture)
    return panel, lines


def command(cut: Mapping[str, Any], base: Path, pictures: Path, out: Path) -> list[str]:
    """Draw every card and overlay into ``pictures`` and return the ffmpeg command that cuts the
    film: one filter graph, every part fitted to the frame, then joined in order."""
    frame = cut["frame"]
    width, height, fps = frame["width"], frame["height"], frame["fps"]
    ground = "0x" + cut["ground"][1:]
    font = base / cut["font"]
    pictures.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    chains: list[str] = []
    count = 0

    def add(*arguments: str) -> int:
        nonlocal count
        inputs.extend(arguments)
        count += 1
        return count - 1

    for n, part in enumerate(cut["parts"]):
        if part["kind"] == "card":
            card = pictures / f"card-{n:02d}.png"
            draw_card(cut, part["lines"], font).save(card)
            i = add(
                "-loop", "1", "-framerate", str(fps), "-t", str(part["seconds"]), "-i", str(card)
            )
            chains.append(f"[{i}:v]scale={width}:{height},setsar=1,fps={fps},format=yuv420p[p{n}]")
            continue
        overlay = pictures / f"over-{n:02d}.png"
        draw_overlay(cut, part.get("caption"), part["speed"], font).save(overlay)
        take = add("-i", str(base / part["file"]))
        side, insets, crop = part.get("side"), part.get("insets", []), part.get("crop")
        beside = side_width(cut, side)
        room = width - beside
        # The take, cut to its stretch, then once for the frame and once for each inset.
        cut_to = (
            f"[{take}:v]trim=start={part['in_s']}:end={part['out_s']},"
            f"setpts=(PTS-STARTPTS)/{part['speed']}"
        )
        if insets:
            copies = "".join(f"[c{n}_{k}]" for k in range(len(insets)))
            chains.append(f"{cut_to},split={len(insets) + 1}[m{n}]{copies}")
            cut_to = f"[m{n}]null"
        shown = "" if crop is None else f",crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}"
        left = "(ow-iw)/2" if beside == 0 else f"{beside}+({room}-iw)/2"
        chains.append(
            f"{cut_to}{shown},"
            f"scale={room}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:{left}:(oh-ih)/2:color={ground},setsar=1,fps={fps}[t{n}]"
        )
        last = f"t{n}"
        edge = "0x" + cut.get("accent", ACCENT)[1:]
        border = max(2, height // 270)
        for k, inset in enumerate(insets):
            x, y, w, h = inset["crop"]
            inner = (inset["width"] - 2 * border) // 2 * 2
            start = inset.get("from_s", 0)
            end = inset.get("to_s", (part["out_s"] - part["in_s"]) / part["speed"])
            chains.append(
                f"[c{n}_{k}]crop={w}:{h}:{x}:{y},scale={inner}:-2,"
                f"pad=iw+{2 * border}:ih+{2 * border}:{border}:{border}:color={edge},"
                f"setsar=1,fps={fps}[i{n}_{k}];"
                f"[{last}][i{n}_{k}]overlay={inset['at'][0]}:{inset['at'][1]}:"
                f"enable='between(t,{start},{end})'[u{n}_{k}]"
            )
            last = f"u{n}_{k}"
        if side is not None:
            panel, lines = draw_side(cut, side, font)
            drawn = [(pictures / f"side-{n:02d}.png", panel, None)]
            drawn += [
                (pictures / f"side-{n:02d}-line-{k:02d}.png", picture, side["lines"][k]["at"])
                for k, picture in enumerate(lines)
            ]
            for k, (path, picture, at) in enumerate(drawn):
                picture.save(path)
                i = add("-loop", "1", "-framerate", str(fps), "-i", str(path))
                when = "" if at is None else f":enable='gte(t,{at})'"
                chains.append(f"[{last}][{i}:v]overlay=0:0:shortest=1{when}[s{n}_{k}]")
                last = f"s{n}_{k}"
        over = add("-loop", "1", "-framerate", str(fps), "-i", str(overlay))
        chains.append(f"[{last}][{over}:v]overlay=0:0:shortest=1,format=yuv420p[p{n}]")
    joined = "".join(f"[p{n}]" for n in range(len(cut["parts"])))
    chains.append(f"{joined}concat=n={len(cut['parts'])}:v=1:a=0[film]")
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chains), "-map", "[film]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("cut", type=Path, help="the cut list")
    parser.add_argument("--out", type=Path, required=True, help="the film to write")
    parser.add_argument("--dry-run", action="store_true", help="print the ffmpeg command only")
    args = parser.parse_args(argv)
    try:
        cut = read_cut(args.cut)
    except CutRefused as refused:
        print(f"not cut: {refused}", file=sys.stderr)
        return 1
    pictures = args.out.with_name(args.out.stem + "-pictures")
    run = command(cut, args.cut.parent, pictures, args.out)
    print(f"{seconds(cut):.1f} s of film from {len(cut['parts'])} parts", file=sys.stderr)
    if args.dry_run:
        print(shlex.join(run))
        return 0
    if shutil.which("ffmpeg") is None:
        print("ffmpeg is not on the path", file=sys.stderr)
        return 2
    return subprocess.run(run, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
