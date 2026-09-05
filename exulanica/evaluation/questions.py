"""Frozen synthetic questions, whose gold answers come only from the drawing manifest.

This is not OGC-1 L9 and not a model-produced plan fixture. The optional plans are declared
compiler inputs. Object appearance queries deliberately measure the whole lexical retrieval
path, including missed detector captions; they do not measure entity identity or person recall.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from exulanica.canonical import canonical_json
from exulanica.evaluation.ground_truth import GroundTruth, _instant

PROFILE = "exulanica.synthetic-gold-questions/v1"


class GoldQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str
    question: str
    dimension: Literal["time", "object", "place", "modality"]
    context: dict[str, str] = Field(default_factory=dict)
    answerability: Literal["answerable", "not_captured", "not_in_modality"]
    expected_photo_sha256: tuple[str, ...]
    expected_capture_count: int
    plan: dict[str, Any] | None = None
    blocked_on: str | None = None


class GoldQuestions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["exulanica.synthetic-gold-questions/v1"] = PROFILE
    corpus_id: Literal["SYNTH-1"] = "SYNTH-1"
    synthetic: Literal[True] = True
    manifest_sha256: str
    questions: tuple[GoldQuestion, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()

    def write(self, path: str | Path) -> None:
        with Path(path).open("x", encoding="utf-8") as handle:
            handle.write(self.model_dump_json(indent=2) + "\n")

    @classmethod
    def read(cls, path: str | Path, truth: GroundTruth) -> GoldQuestions:
        result = cls.model_validate(json.loads(Path(path).read_bytes()))
        if result.manifest_sha256 != truth.manifest_sha256:
            raise ValueError("gold questions name a different corpus manifest")
        if result != derive_questions(truth):
            raise ValueError("gold questions disagree with manifest-derived answers or rules")
        return result


def derive_questions(truth: GroundTruth) -> GoldQuestions:
    """A fixed rule over all manifest frames, independent of what a workspace retrieved.

    Never intersect the gold set with ingested rows: missing ingestion must remain visible. The
    question scorer requires an exact corpus workspace before it measures a question. Unknown
    offset frames are excluded only from absolute-time questions, not from object/place truth.
    """
    if not truth.synthetic:
        raise ValueError("generated questions require an explicitly synthetic corpus")
    if not truth.frames or len(truth.by_hash) != len(truth.frames):
        raise ValueError("a question corpus needs nonempty, unique photo addresses")
    questions: list[GoldQuestion] = []

    def add(
        key: str,
        text: str,
        dimension: str,
        hashes: list[str],
        *,
        plan: dict[str, Any] | None = None,
        context: dict[str, str] | None = None,
        blocked_on: str | None = None,
        answerability: str | None = None,
    ) -> None:
        gold = sorted(hashes)
        questions.append(
            GoldQuestion(
                question_id=key,
                question=text,
                dimension=dimension,
                context=context or {},
                answerability=answerability or ("answerable" if gold else "not_captured"),
                expected_photo_sha256=tuple(gold),
                expected_capture_count=len(gold),
                plan=plan,
                blocked_on=blocked_on,
            )
        )

    timed = [
        (frame, _instant(frame.utc_instant or ""))
        for frame in truth.frames
        if frame.instant_is_recoverable_from_the_file
    ]
    if any(instant is None for _, instant in timed):
        raise ValueError("a recoverable manifest frame must carry an absolute instant")
    for trip in truth.trips:
        instants = sorted(instant for frame, instant in timed if frame.trip == trip)
        if not instants:
            continue
        start, end = instants[0], instants[-1] + dt.timedelta(seconds=1)
        for suffix, low, high in (
            ("whole", start, end),
            ("before", start - dt.timedelta(seconds=1), start),
        ):
            add(
                f"time:{trip}:{suffix}",
                f"Which photographs were captured from {low.isoformat()} inclusive to "
                f"{high.isoformat()} exclusive?",
                "time",
                [f.sha256 for f, instant in timed if low <= instant < high],
                context={"trip": trip},
                plan={
                    "intent": "captures",
                    "time": [
                        {
                            "start": low.isoformat(),
                            "end": high.isoformat(),
                        }
                    ],
                    "limit": 24,
                },
            )
    for subject in truth.subjects:
        labels = truth.subject_labels.get(subject, ())
        add(
            f"object:{subject}",
            f"Which photographs show {labels[0] if labels else subject}?",
            "object",
            [frame.sha256 for frame in truth.frames if subject in frame.subjects],
            context={"subject": subject},
            plan={"intent": "captures", "semantic_query": labels[0], "limit": 24}
            if labels
            else None,
            blocked_on=None if labels else "The manifest has no appearance phrase for this object.",
        )
    for place in truth.places:
        add(
            f"place:{place}",
            f"Which photographs were made at the synthetic place {place}?",
            "place",
            [frame.sha256 for frame in truth.frames if frame.place == place],
            context={"place": place},
            blocked_on="A place filter requires a human-confirmed place entity; the harness "
            "does not manufacture that decision from the manifest.",
        )
    add(
        "modality:speech",
        "What was said while these photographs were taken?",
        "modality",
        [],
        answerability="not_in_modality",
        blocked_on="Still images carry no speech evidence, "
        "and NOT_IN_MODALITY has no production question-path producer. M3 remains blocked.",
    )
    return GoldQuestions(manifest_sha256=truth.manifest_sha256, questions=tuple(questions))
