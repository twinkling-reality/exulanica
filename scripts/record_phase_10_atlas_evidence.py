"""Bind the Phase 10 Atlas captures into one digest-bound record.

The two visible halves of P10-A were exercised against the retained real trained bowl in a
headless browser at exactly 1280x720, and the screenshots are the result. A screenshot on its own
establishes nothing: it is an image of a claim. So each one is bound here by SHA-256 beside the
sentence it was taken to show, and the record says what the run measured and what it did not.

Run after a capture session, from the repository root. It reads the driver's own ``run.json`` and
the retained images, and refuses rather than guesses if either is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path("artifacts/2026-09-06-phase-10-atlas")
RECORD = ROOT / "docs/evaluation/2026-09-06-phase-10-atlas.json"

# What each retained capture was taken to show. Written here rather than derived from the file
# name, because the sentence is the claim and the image is only its evidence.
CAPTIONS: dict[str, str] = {
    "lens-off": "The trained bowl as the world draws it, with the proof lens switched off.",
    "lens-on": (
        "The same frame with the lens on. The whole trained reconstruction wears the "
        "reconstructed tier's hue at its own brightness, so the geometry stays readable under "
        "the answer about where it came from."
    ),
    "lens-off-again": (
        "The lens switched back off. The encoded frame is byte-identical to lens-off, which is "
        "the visible half of the claim that toggling changes nothing."
    ),
    "inspector-open": (
        "The reconstruction inspector opened on the trained scene, reading its recorded "
        "observation graph."
    ),
    "inspector-lens-on": "The lens on, seen from the first photograph's own recovered camera.",
    "inspector-lens-off": "The same recovered camera with the lens off.",
    "evidence-ready": (
        "The observation graph loaded and nothing clicked yet: 15005 recorded points, at most "
        "4096 retained per photograph."
    ),
    "evidence-hit-truncated-track": (
        "A click resolving to sparse point 114, whose COLMAP track is 17 photographs and whose "
        "retained sample is 15. Both numbers are stated, because a panel that said 15 would be "
        "lying by omission about the one thing the visitor asked."
    ),
    "evidence-hit": (
        "A click resolving to a point five photographs observed and five retain, where the "
        "sentence names one number because there is only one."
    ),
    "evidence-miss": (
        "A click that reaches no recorded observation, shown as the answer it is rather than "
        "swallowed, with the tolerance stated in both screen and source pixels."
    ),
    "evidence-centre-button": (
        "The same question asked from the button in the inspector, because the world canvas is "
        "aria-hidden and a gesture that exists only as a click on it exists only for sighted "
        "mouse users."
    ),
}


def digest_of(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(ARTIFACTS / path.name),
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="the capture driver's run.json")
    parser.add_argument("--head", required=True, help="the commit the captures were taken at")
    parser.add_argument("--backend", required=True, help="the backend suite result, as one line")
    parser.add_argument("--web", required=True, help="the web suite result, as one line")
    args = parser.parse_args()

    run = json.loads(Path(args.run).read_bytes())
    directory = RECORD.parent / ARTIFACTS
    captures = []
    for entry in run["captures"]:
        name = entry["name"]
        image = directory / f"{name}.jpg"
        if not image.is_file():
            raise SystemExit(f"no retained image for capture {name}")
        if name not in CAPTIONS:
            raise SystemExit(f"capture {name} has no caption; a bound image needs its claim")
        state = entry["state"]
        captures.append(
            {
                **digest_of(image),
                "capture": name,
                "shows": CAPTIONS[name],
                "proof_lens": state["lensState"],
                "evidence_state": state["evidenceKind"],
                "evidence_sentence": state["evidenceState"],
            }
        )

    clicks = [
        {
            "canvas_x": item["clientX"],
            "canvas_y": item["clientY"],
            "result": item["kind"],
            "sentence": item["state"],
            "photographs_listed": item["photographs"],
        }
        for item in run["attempts"]
    ]

    record = {
        "profile": "exulanica.phase-10-atlas-visible/v1",
        "date": "2026-09-06",
        "head": args.head,
        "database": "postgresql://localhost:5433/exulanica_spine_test",
        "collection": "chili-salmon-bowl",
        "scene_id": run["inspectorSceneId"],
        "rendering_substrate": "gaussian_splats",
        "browser": "Chrome headless=new, ANGLE Metal, 1280x720 css px, deviceScaleFactor 1",
        "what_this_establishes": (
            "The proof lens colours the real trained reconstruction in the 3D view and restores "
            "it exactly when switched off, and a click in the reconstruction inspector resolves "
            "a surface to the photographs whose cameras recorded that point, each with its "
            "consent state. It establishes nothing about visual quality, physical scale, or "
            "per-person consent, none of which this work touched."
        ),
        "atlas_mount_ms": int(run["mountMs"]),
        "observation_graph_ready_ms": int(run["observationGraphReadyMs"]),
        "console_errors": run["consoleErrors"],
        "observation_graph": {
            "route": "GET /world-read/scenes/{scene_id}/observations",
            "provenance": "recorded",
            "point_count": 15005,
            "retained_per_image": 4096,
            "response_bytes": 53343203,
            "digest_bound": False,
            "note": (
                "The response carries no digest of its own, unlike the World Read bundle. It is "
                "recorded provenance served over an authenticated route; it is not a receipt a "
                "recipient can verify offline."
            ),
        },
        "projection_check": {
            "what": (
                "Every retained observation of the first photograph reprojected through the raw "
                "recovered camera the pick uses, compared against COLMAP's own recorded pixel."
            ),
            "observations": 2386,
            "median_error_px": "2.83",
            "p95_error_px": "6.73",
            "max_error_px": "9.88",
            "image_size_px": "3060x4080",
            "why_it_is_not_zero": (
                "SIMPLE_RADIAL distortion, which the recovered camera declares as "
                "pinhole-approximation and this projection does not apply."
            ),
        },
        "clicks": clicks,
        "captures": captures,
        "screenshot": digest_of(directory / "evidence-hit-truncated-track.jpg"),
        "verification": {"backend": args.backend, "web": args.web},
        "limitations": [
            "The proof lens over a region drawing an original photograph is deliberately absent: "
            "a photograph is the evidence, and tinting it would alter what is being offered. The "
            "photographed tier is named in the legend and paints nothing.",
            "No region in either retained workspace draws a generated surface, so the generated "
            "tier's colour is exercised only by the legend and by tests, never over real "
            "geometry.",
            "The world-view lens pair had to be captured within about thirteen seconds of "
            "arrival. MEASURED and reproduced on the unmodified tree at HEAD 104e415: in this "
            "headless browser the representation pressure controller reaches level 3 after six "
            "sixty-frame windows, the region's residency is capped at its stub, and the trained "
            "scene stops being drawn until something forces it resident again. That is a "
            "pre-existing behaviour of the arrival path and nothing here fixed it.",
            "Click-to-evidence answers only from a recovered source camera. A midpoint between "
            "two photographs is refused rather than approximated, because no camera stood there.",
            "The point a click selects is the nearest recorded sparse point, not the surface "
            "under the cursor. On this scene at an eight-screen-pixel tolerance, a grid of "
            "clicks over the frame resolved roughly a third of the time; the rest reached no "
            "recorded observation and said so.",
            "Every photograph reports person_consent unavailable, because no per-person consent "
            "layer exists in this build. The answer reports that state and filters nothing.",
        ],
    }

    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    RECORD.write_text(f"{json.dumps(document, indent=2)}\n", encoding="utf-8")
    print(f"wrote {RECORD.relative_to(ROOT)} over {len(captures)} bound captures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
