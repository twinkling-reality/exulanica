"""The demo film's cutter: a cut list is data, and the cut is drawn and joined from it alone.

What is shown here, without ffmpeg or any take: a cut list reads only when every part is a card or a
take with sound figures, and is refused by name otherwise (against a positive control); the film's
length is the cards' seconds plus each take's stretch divided by its speed; every card and overlay
is drawn as a picture at the frame's size, a take played faster carries its speed, and the ffmpeg
command joins every part, in order, at the frame's size and rate; a take may show a part of its
own picture, the same picture again larger on top for some seconds, and a panel beside it whose
lines appear at their seconds, each refused by name when it is faulty, and a take with none of them
is cut as it was.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets/fonts/barlow/Barlow-SemiBold.ttf"


def _cutter():
    spec = importlib.util.spec_from_file_location("cut_film", ROOT / "scripts/demo/cut_film.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cut_film"] = module
    spec.loader.exec_module(module)
    return module


def _cut() -> dict:
    return {
        "profile": "exulanica.film-cut/v1",
        "frame": {"width": 640, "height": 360, "fps": 30},
        "font": str(FONT),
        "ground": "#111725",
        "ink": "#e9edf4",
        "parts": [
            {"kind": "card", "seconds": 2, "lines": ["A title", "a line below it"]},
            {
                "kind": "take",
                "file": "a.mp4",
                "in_s": 1.0,
                "out_s": 5.0,
                "speed": 1,
                "caption": "one",
            },
            {
                "kind": "take",
                "file": "b.mp4",
                "in_s": 0.0,
                "out_s": 8.0,
                "speed": 4,
                "caption": "two",
            },
        ],
    }


def _write(path: Path, cut: dict) -> Path:
    path.write_text(json.dumps(cut), encoding="utf-8")
    return path


def test_a_cut_list_reads_and_a_faulty_one_is_refused_by_name(tmp_path):
    cutter = _cutter()
    cutter.read_cut(_write(tmp_path / "cut.json", _cut()))  # the positive control
    faults = []
    for key, value, words in (
        ("speed", 9, "speed from 1 to 8"),
        ("speed", 1.5, "whole speed"),
        ("out_s", 0.0, "ends after it starts"),  # it starts at 0.0
        ("kind", "clip", "a card or a take"),
    ):
        cut = _cut()
        cut["parts"][2][key] = value
        faults.append((cut, words))
    blank = _cut()
    blank["parts"][0]["lines"] = []
    faults.append((blank, "states its lines"))
    pale = _cut()
    pale["ink"] = "white"
    faults.append((pale, "#rrggbb"))
    for cut, words in faults:
        with pytest.raises(cutter.CutRefused, match=words):
            cutter.read_cut(_write(tmp_path / "faulty.json", cut))


def test_the_film_lasts_its_cards_and_its_takes_at_their_speeds():
    # 2 s of card, 4 s of a take at its own speed, 8 s of a take at four times: 8 s in all.
    assert _cutter().seconds(_cut()) == 8.0


def test_every_part_is_drawn_at_the_frame_and_joined_in_order(tmp_path):
    cutter = _cutter()
    cut = _cut()
    run = cutter.command(cut, tmp_path, tmp_path / "pictures", tmp_path / "film.mp4")
    pictures = sorted((tmp_path / "pictures").iterdir())
    assert [p.name for p in pictures] == ["card-00.png", "over-01.png", "over-02.png"]
    for picture in pictures:
        assert Image.open(picture).size == (640, 360)
    graph = run[run.index("-filter_complex") + 1]
    assert "[p0][p1][p2]concat=n=3:v=1:a=0[film]" in graph
    assert "setpts=(PTS-STARTPTS)/4" in graph and "setpts=(PTS-STARTPTS)/1" in graph
    assert graph.count("scale=640:360") == 3 and graph.count("fps=30") == 3
    # The faster take carries its speed: its overlay differs from the one at its own speed only by
    # the mark at the top right.
    slow, fast = (
        Image.open(tmp_path / "pictures" / name) for name in ("over-01.png", "over-02.png")
    )
    corner = (640 - 120, 0, 640, 60)
    assert slow.crop(corner).getbbox() is None and fast.crop(corner).getbbox() is not None
    same = copy.deepcopy(cut)
    same["parts"][2]["speed"] = 1
    cutter.command(same, tmp_path, tmp_path / "again", tmp_path / "film.mp4")
    assert Image.open(tmp_path / "again" / "over-02.png").crop(corner).getbbox() is None


def _with_extras() -> dict:
    cut = _cut()
    cut["parts"][1].update(
        {
            "crop": [100, 50, 320, 180],
            "insets": [
                {"crop": [0, 0, 100, 60], "at": [400, 20], "width": 200, "from_s": 1.0, "to_s": 3.0}
            ],
            "side": {
                "title": "Its own side",
                "note": "what another program logged",
                "lines": [
                    {"at": 0.5, "text": "the first line"},
                    {"at": 2.0, "text": "the second, said in its own words", "tone": "hot"},
                ],
            },
        }
    )
    return cut


def test_a_take_may_show_a_part_larger_and_a_panel_beside_it_whose_lines_appear(tmp_path):
    cutter = _cutter()
    cut = _with_extras()
    cutter.read_cut(_write(tmp_path / "cut.json", cut))  # the positive control
    run = cutter.command(cut, tmp_path, tmp_path / "pictures", tmp_path / "film.mp4")
    graph = run[run.index("-filter_complex") + 1]
    beside = cutter.side_width(cut, cut["parts"][1]["side"])
    assert beside == 242  # 38 percent of 640, made even
    # The take's own part, fitted in what the panel leaves, to the panel's right.
    assert f"crop=320:180:100:50,scale={640 - beside}:360:" in graph
    assert f"pad=640:360:{beside}+({640 - beside}-iw)/2:(oh-ih)/2" in graph
    # The same picture again, its own part, laid over for its seconds only.
    assert "split=2[m1][c1_0]" in graph and "[c1_0]crop=100:60:0:0," in graph
    assert "overlay=400:20:enable='between(t,1.0,3.0)'" in graph
    # Each line is laid over from its own second; the panel itself the whole stretch.
    assert graph.count("enable='gte(t,") == 2
    assert "enable='gte(t,0.5)'" in graph and "enable='gte(t,2.0)'" in graph
    drawn = sorted(picture.name for picture in (tmp_path / "pictures").iterdir())
    assert drawn == [
        "card-00.png",
        "over-01.png",
        "over-02.png",
        "side-01-line-00.png",
        "side-01-line-01.png",
        "side-01.png",
    ]
    panel = Image.open(tmp_path / "pictures" / "side-01.png")
    assert panel.size == (640, 360)
    assert panel.crop((beside, 0, 640, 360)).getbbox() is None
    assert panel.crop((0, 0, beside, 360)).getbbox() == (0, 0, beside, 360)
    first, second = (
        Image.open(tmp_path / "pictures" / f"side-01-line-0{n}.png").getbbox() for n in (0, 1)
    )
    # A line holds its own words only, inside the panel, the second below the first.
    assert first[2] <= beside and second[2] <= beside and second[1] >= first[3]
    # A take with none of them is cut as it was.
    plain = cutter.command(_cut(), tmp_path, tmp_path / "plain", tmp_path / "film.mp4")
    plain_graph = plain[plain.index("-filter_complex") + 1]
    assert "split" not in plain_graph and "crop=" not in plain_graph
    assert plain_graph.count("pad=640:360:(ow-iw)/2:(oh-ih)/2") == 2


def test_a_faulty_crop_inset_or_side_panel_is_refused_by_name(tmp_path):
    cutter = _cutter()
    faults = []

    def fault(words: str, change) -> None:
        cut = _with_extras()
        change(cut["parts"][1])
        faults.append((cut, words))

    fault("four whole numbers", lambda take: take.update(crop=[1, 2, 3]))
    fault("four whole numbers", lambda take: take.update(crop=[0, 0, 0, 10]))
    fault("fits the frame", lambda take: take["insets"][0].update(width=300))
    fault("at a whole x and y", lambda take: take["insets"][0].update(at=[400]))
    # The stretch lasts 4 s: an inset or a line past it would never show.
    fault("within its stretch", lambda take: take["insets"][0].update(to_s=4.5))
    fault("its title and its lines", lambda take: take["side"].update(title=""))
    fault("appears within its stretch", lambda take: take["side"]["lines"][1].update(at=4.0))
    fault("tone is one of", lambda take: take["side"]["lines"][0].update(tone="loud"))
    fault("of the frame's width", lambda take: take["side"].update(share=0.6))
    for cut, words in faults:
        with pytest.raises(cutter.CutRefused, match=words):
            cutter.read_cut(_write(tmp_path / "faulty.json", cut))
