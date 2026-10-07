"""The reference_vision role's timeout basis: one call per code-made drawing, the picture prompt as sent.

    uv run python scripts/measure_reference_vision_latency.py --record RECORD.json \
        --answers ANSWERS.json --as-run AS_RUN.py.txt --env PATH/TO/.env

Twelve drawings are made here by code (houses, roofs, boats, water, trees, hills: no person, no
lettering, no photograph), each sent as the rendition production sends, once, to
``openbmb/MiniCPM-V-4_5`` with no fallback and no cache, under the reference picture prompt and its
strict schema. A call is timed around the client call, as the latency survey reads a call row.

Two files are written, and they are not the same kind of thing:

* ``--record`` is the evidence the manifest's timeout basis quotes: per call the drawing's digest,
  the latency, the tokens and USD, the served model and its attempts; the run's tree and window;
  and ``measured.roles.reference_vision.primary_measured``, the shape
  ``tests/test_models_call_bounds.py`` reads. It holds no answer.
* ``--answers`` is what each answer said (``use``, ``reason`` and the notes). That is a measure of
  the model's quality, kept out of the record until the provider's terms are read for it.

The spend is bounded twice: a budget guard at USD 0.02 on Nebius Token Factory, and a transport
that sends at most twelve requests, each carrying exactly one image whose digest is one of the
drawings made here. The model key is read from ``--env`` into this process only, never printed.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from exulanica.canonical import canonical_json
from exulanica.ingest.derivatives import render
from exulanica.ingest.stages import stage
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ModelError
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest
from exulanica.models.messages import image_part, text_part
from exulanica.models.transport import HttpxTransport

ROOT = Path(__file__).resolve().parents[1]
MODEL = "openbmb/MiniCPM-V-4_5"
DRAWINGS = 12
CEILING_USD = Decimal("0.02")
MAX_TOKENS = 512
IMAGE_PROMPT_TOKENS = 800
ORIGIN = "https://api.tokenfactory.nebius.com"
ASPECTS = (
    "buildings",
    "materials_and_colour",
    "landscape_and_plants",
    "food_and_goods",
    "vehicles_and_boats",
    "scale",
)
REASONS = ("shows_people", "shows_text", "not_a_place")
INSTRUCTIONS = (
    "You write drafting notes for an invented world from one picture a person gave of a place or "
    "things they like. A drawing or painting of a place counts as a place. Look only at places and "
    "things: buildings, materials and colours, landscape and plants, food and goods, vehicles and "
    "boats, and rough sizes. First set refuse. Set it to shows_people if the picture shows any "
    "person or part of a person; to shows_text if it shows readable writing, a document or a "
    "screen; to not_a_place if it shows no place or things to draw on. Write null when no reason "
    "applies. When refuse is null, write 1 to 6 notes, each at most 80 characters, in your own "
    "words, about one of the listed aspects; when refuse is set, write no notes. Never describe a "
    "person, never read or copy any writing, and never name or guess a place, a company or a brand."
)
USER_TEXT = "The aspects:\n" + "\n".join(f"- {key}" for key in ASPECTS) + "\nThe picture:"


class PictureNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aspect: Literal[ASPECTS]  # type: ignore[valid-type]
    text: str = Field(min_length=1, max_length=80)


class PictureReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refuse: Literal[REASONS] | None  # type: ignore[valid-type]
    notes: list[PictureNote] = Field(max_length=6)


def drawing(index: int) -> Image.Image:
    """A place drawn by code from ``index``: sky, hills, water, houses, trees and a boat."""
    draw_random = random.Random(f"reference-vision-probe/{index}")
    image = Image.new("RGB", (1024, 768), (150 + draw_random.randrange(80), 190, 235))
    pen = ImageDraw.Draw(image)
    horizon = 360 + draw_random.randrange(120)
    for _ in range(2 + draw_random.randrange(3)):
        x = draw_random.randrange(-200, 1024)
        width = 300 + draw_random.randrange(400)
        green = (60 + draw_random.randrange(60), 120 + draw_random.randrange(60), 60)
        pen.polygon(
            [
                (x, horizon),
                (x + width // 2, horizon - 80 - draw_random.randrange(140)),
                (x + width, horizon),
            ],
            fill=green,
        )
    if index % 2 == 1:
        pen.rectangle([0, horizon + 140, 1024, 768], fill=(110, 150, 70))
    if index % 2 == 0:
        pen.rectangle([0, horizon + 140, 1024, 768], fill=(40, 90, 150))
        hull = 120 + draw_random.randrange(600)
        pen.polygon(
            [
                (hull, horizon + 200),
                (hull + 160, horizon + 200),
                (hull + 130, horizon + 240),
                (hull + 30, horizon + 240),
            ],
            fill=(120, 70, 40),
        )
        pen.line(
            [(hull + 80, horizon + 200), (hull + 80, horizon + 110)], fill=(90, 60, 30), width=6
        )
        pen.polygon(
            [(hull + 84, horizon + 115), (hull + 84, horizon + 190), (hull + 140, horizon + 190)],
            fill=(235, 230, 215),
        )
    ground = (200 + draw_random.randrange(40), 180 + draw_random.randrange(40), 140)
    pen.rectangle([0, horizon, 1024, horizon + 140], fill=ground)
    for _ in range(3 + draw_random.randrange(4)):
        left = draw_random.randrange(0, 900)
        width = 80 + draw_random.randrange(90)
        height = 70 + draw_random.randrange(120)
        base = horizon + 20 + draw_random.randrange(100)
        wall = draw_random.choice(
            [(245, 245, 240), (230, 200, 160), (200, 120, 90), (180, 180, 175)]
        )
        pen.rectangle([left, base - height, left + width, base], fill=wall, outline=(90, 90, 90))
        roof = draw_random.choice([(170, 60, 50), (60, 90, 160), (110, 110, 110)])
        if draw_random.random() < 0.3:
            pen.pieslice(
                [left, base - height - width // 2, left + width, base - height + width // 2],
                180,
                360,
                fill=roof,
            )
        else:
            pen.polygon(
                [
                    (left - 10, base - height),
                    (left + width // 2, base - height - 50),
                    (left + width + 10, base - height),
                ],
                fill=roof,
            )
        door = left + width // 2 - 10
        pen.rectangle([door, base - 36, door + 20, base], fill=(40, 70, 140))
        for row in range(max(1, height // 45)):
            y = base - height + 15 + row * 40
            if y + 18 < base - 40:
                pen.rectangle([left + 12, y, left + 28, y + 18], fill=(60, 60, 80))
                pen.rectangle([left + width - 28, y, left + width - 12, y + 18], fill=(60, 60, 80))
    for _ in range(2 + draw_random.randrange(5)):
        x = draw_random.randrange(0, 1000)
        y = horizon + 10 + draw_random.randrange(110)
        pen.rectangle([x, y - 40, x + 8, y], fill=(100, 70, 40))
        pen.ellipse(
            [x - 26, y - 90, x + 34, y - 30], fill=(40 + draw_random.randrange(40), 120, 50)
        )
    return image


def rendition(image: Image.Image) -> bytes:
    """The bytes production sends for a picture: the rendition stage of the image."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return render(Image.open(io.BytesIO(buffer.getvalue())), stage("rendition")).data


class DrawingsOnly:
    """Sends a request only when it carries exactly one image that is one of the drawings here, and
    at most ``limit`` requests in all."""

    def __init__(self, inner: Any, drawings: frozenset[str], limit: int) -> None:
        self._inner = inner
        self._drawings = drawings
        self._left = limit
        self.sent = 0

    def post_json(
        self, url: str, *, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float
    ) -> Any:
        images = [
            part["image_url"]["url"]
            for message in payload.get("messages", ())
            for part in (message.get("content") if isinstance(message.get("content"), list) else ())
            if isinstance(part, Mapping) and part.get("type") == "image_url"
        ]
        if len(images) != 1:
            raise ModelError(f"a probe request carries exactly one drawing, not {len(images)}")
        prefix = "data:image/jpeg;base64,"
        if not images[0].startswith(prefix):
            raise ModelError("a probe drawing is sent as bytes")
        sent = hashlib.sha256(base64.b64decode(images[0][len(prefix) :])).hexdigest()
        if sent not in self._drawings:
            raise ModelError("the image is not one of the probe's drawings")
        if self._left <= 0:
            raise ModelError("the probe has sent every request it may")
        self._left -= 1
        self.sent += 1
        return self._inner.post_json(url, headers=headers, payload=payload, timeout=timeout)

    def get_json(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Any:
        raise ModelError("the probe reads nothing")


class ProbeDrawings:
    """The request policy for this probe: no photograph, one image, the texts as written here."""

    def admit(self, request: Any) -> Sequence[str]:
        if request.photographs or request.images != 1:
            raise ModelError("a probe request names no photograph and carries one drawing")
        if tuple(request.texts) != (USER_TEXT,):
            raise ModelError("a probe request carries only the probe's own words")
        return request.texts


def _percentile(sorted_ms: list[int], fraction: float) -> int:
    """Nearest rank, as scripts/survey_hosted_call_latency.py reads one."""
    rank = -(-len(sorted_ms) * round(fraction * 100) // 100)
    return sorted_ms[max(rank, 1) - 1]


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def _key(env_file: Path) -> str:
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "NEBIUS_API_KEY":
            return value.strip().strip('"').strip("'")
    raise SystemExit("the env file names no NEBIUS_API_KEY")


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--as-run", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    arguments = parser.parse_args()

    script = Path(__file__).resolve()
    arguments.as_run.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(script, arguments.as_run)
    images = [rendition(drawing(index)) for index in range(DRAWINGS)]
    digests = [hashlib.sha256(image).hexdigest() for image in images]

    base = load_manifest()
    roles = dict(base.roles)
    roles[Role.VISION] = dataclasses.replace(
        base[Role.VISION], primary=base.spec(MODEL), fallback=None
    )
    manifest = dataclasses.replace(base, roles=roles)
    os.environ["EXULANICA_EGRESS_ALLOWLIST"] = json.dumps([ORIGIN])
    transport = DrawingsOnly(HttpxTransport(), frozenset(digests), DRAWINGS)
    client = ModelClient(
        api_key=_key(arguments.env),
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=CEILING_USD),
        policy=ProbeDrawings(),
    )
    prompt_sha256 = hashlib.sha256(
        canonical_json({"instructions": INSTRUCTIONS, "user": USER_TEXT, "max_tokens": MAX_TOKENS})
    ).hexdigest()

    started = _now()
    calls: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    stopped: str | None = None
    for digest, image in zip(digests, images, strict=True):
        messages = [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": [text_part(USER_TEXT), image_part(image)]},
        ]
        clock = time.monotonic()
        try:
            result = client.structured(
                Role.VISION,
                messages,
                PictureReading,
                prompt_version="reference-picture-probe-2",
                max_tokens=MAX_TOKENS,
                image_prompt_tokens=IMAGE_PROMPT_TOKENS,
                arrays_last=True,
            )
        except BudgetExceededError:
            # Nothing was sent: the guard reserves a call's worst case before it leaves, and the
            # client counts an image's base64 characters as prompt text, so the reservation is far
            # above a call's cost. The run stops at the first call it may not reserve.
            stopped = "the budget guard could not reserve another call within the ceiling"
            break
        except ModelError as error:
            latency = round((time.monotonic() - clock) * 1000)
            calls.append(
                {"drawing_sha256": digest, "latency_ms": latency, "failure": type(error).__name__}
            )
            answers.append(
                {"drawing_sha256": digest, "failure": f"{type(error).__name__}: {str(error)[:300]}"}
            )
            continue
        latency = round((time.monotonic() - clock) * 1000)
        usage = result.call.usage
        calls.append(
            {
                "drawing_sha256": digest,
                "latency_ms": latency,
                "role": "reference_vision",
                "served_model": result.call.served_model_id,
                "attempts": result.call.attempts,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "usd": f"{usage.usd:.8f}",
            }
        )
        answers.append({"drawing_sha256": digest, **result.value.model_dump(mode="json")})
    ended = _now()

    answered = sorted(
        call["latency_ms"]
        for call in calls
        if "failure" not in call and call["served_model"] == MODEL and call["attempts"] == 1
    )
    spent = client.budget.spent_usd
    tree_diff = _git("diff", "--binary", "HEAD")
    body: dict[str, Any] = {
        "kind": "exulanica.reference-vision-latency/v1",
        "purpose": "the reference_vision role's timeout basis: one call per code-made drawing, timed around the client call",
        "corpus": {
            "class": "synthetic",
            "made_by": "code in the script as run: houses, roofs, boats, water, trees and hills; no person, no lettering, no photograph",
            "drawings_sha256": digests,
            "sent_as": "the rendition stage's bytes",
        },
        "model": MODEL,
        "provider": "nebius_token_factory",
        "fallback": None,
        "prompt_sha256": prompt_sha256,
        "calls": calls,
        "measured": {
            "roles": {
                "reference_vision": {
                    "primary": MODEL,
                    "primary_measured": {
                        "rows": len(answered),
                        "p50_ms": _percentile(answered, 0.5) if answered else None,
                        "p99_ms": _percentile(answered, 0.99) if answered else None,
                        "longest_ms": answered[-1] if answered else None,
                    },
                }
            }
        },
        "bound_usd": str(CEILING_USD),
        "spent_usd": f"{spent:.8f}",
        "within_bound": spent <= CEILING_USD,
        "requests_sent": transport.sent,
        "stopped": stopped,
        "head": _git("rev-parse", "HEAD").decode().strip(),
        "tree": {
            "head": _git("rev-parse", "HEAD").decode().strip(),
            "diff_head_sha256": hashlib.sha256(tree_diff).hexdigest(),
            "differs": sorted(_git("diff", "--name-only", "HEAD").decode().split()),
        },
        "script_as_run": arguments.as_run.resolve().relative_to(ROOT).as_posix()
        if arguments.as_run.resolve().is_relative_to(ROOT)
        else arguments.as_run.name,
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        "window": {"started": started, "ended": ended},
        "answers": "kept outside this record: what each answer said is a quality measure of the model",
    }
    arguments.record.parent.mkdir(parents=True, exist_ok=True)
    arguments.record.write_text(
        json.dumps(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": body,
                "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    arguments.answers.parent.mkdir(parents=True, exist_ok=True)
    arguments.answers.write_text(
        json.dumps({"answers": answers}, indent=2) + "\n", encoding="utf-8"
    )
    measured = body["measured"]["roles"]["reference_vision"]["primary_measured"]
    print(
        f"sent {transport.sent}, answered {len(answered)}, spent USD {spent:.8f} on Nebius Token Factory"
    )
    print(
        f"rows {measured['rows']} p50 {measured['p50_ms']} p99 {measured['p99_ms']} longest {measured['longest_ms']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
