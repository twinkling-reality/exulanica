"""Freeze and score Companion evidence without opening a database or spending money.

Run ``uv run python scripts/measure_companion_acceptance.py --out DIRECTORY`` once to freeze
questions and support before comparison. The manifest uses only retained first-place evidence.
No captions, names, dates or vectors are generated here. ``score_comparison`` consumes paired
observations from the application, while ``compare_retrieval`` uses the existing executor under
an externally supplied database lease. Neither supplies a hosted model client or opens a URL.

Live dispatch remains with the activated application's owner: supply this manifest digest in a
written run cap, enforce that cap on the application's existing ModelClient, and retain the HTTP
requests/responses plus provider request accounting. Successful-result API call logs alone omit
failed attempts. An omitted human answer review or citation probe stays unknown, never a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.evidence import BlobId, parse_uri
from exulanica.models.errors import BudgetExceededError
from exulanica.selection import SelectionPlan, build_packet, execute, validate

ROOT = Path(__file__).resolve().parents[1]
MATCHING = "docs/evaluation/2026-09-11-companion-matching.json"
FIRST_PLACE = "docs/evaluation/2026-09-11-first-place.json"
WIRE = "docs/evaluation/artifacts/2026-09-11-first-place/companion/ask-2.json"
PROFILE = "exulanica.companion-acceptance-input/v1"


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def bound_file(root: Path, path: str) -> dict:
    data = (root / path).read_bytes()
    return {"path": path, "byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_record(root: Path, path: str) -> dict:
    envelope = json.loads((root / path).read_bytes())
    if envelope["record_sha256"] != digest(envelope["record"]):
        raise ValueError(f"record digest mismatch: {path}")
    return envelope["record"]


def frozen_input(root: Path = ROOT) -> dict:
    """Join by capture id and content address, never photograph ordering or file names."""
    matching = read_record(root, MATCHING)["corpora"]["first_place"]
    source = read_record(root, FIRST_PLACE)
    wire_binding = next(a for a in source["artifacts"] if a["path"] == WIRE)
    if bound_file(root, WIRE) != wire_binding:
        raise ValueError("retained wire digest mismatch")
    wire = json.loads((root / WIRE).read_bytes())["body"]
    captures = {c["capture_id"]: c for c in wire["selection"]["captures"]}
    approved_digests = {p["sha256"] for p in source["corpus"]["photographs"]}
    corpus = []
    for caption in matching["captions"]:
        capture = captures[caption["capture_id"]]
        sha = BlobId.from_ni_uri(capture["blob"]).hex
        if sha not in approved_digests:
            raise ValueError("wire photograph outside the authorized corpus")
        if caption["assertion_id"] not in {s["assertion_id"] for s in capture["support"]}:
            raise ValueError("caption assertion differs from retained wire support")
        corpus.append(
            {
                **caption,
                "source_sha256": sha,
                "captured_at": capture["captured_at"],
                "caption_sha256": hashlib.sha256(caption["text"].encode()).hexdigest(),
            }
        )
    corpus.sort(key=lambda c: c["capture_id"])
    all_ids = [c["capture_id"] for c in corpus]
    questions = []

    def add(key, question, terms, kind, rubric, *, split="development", supported=True):
        questions.append(
            {
                "id": key,
                "question": question,
                "split": split,
                "kind": kind,
                "retrieval_plan": SelectionPlan(
                    intent="captures", semantic_query=terms, limit=24
                ).model_dump(mode="json"),
                "expected_capture_ids": all_ids if supported else [],
                "expected_support": [
                    {
                        "capture_id": c["capture_id"],
                        "source_sha256": c["source_sha256"],
                        "caption_sha256": c["caption_sha256"] if kind == "visual" else None,
                    }
                    for c in corpus
                ]
                if supported
                else [],
                "must_abstain": not supported,
                "answer_rubric": rubric,
            }
        )

    add(
        "mountain",
        "Which of my photos show a snow-covered mountain?",
        "snow mountain",
        "visual",
        "All three captions describe snow-covered or snow-dusted mountain slopes.",
    )
    add(
        "clothing",
        "What cold-weather clothing do the people have on?",
        "cold weather clothing",
        "visual",
        "Heavy coveralls and insulated jackets; reflective bands/strips. Do not infer brands.",
    )
    add(
        "headgear",
        "Where can I see protective headgear?",
        "protective headgear",
        "visual",
        "Dark helmets are held in all three captions. Do not say they are wearing the helmets.",
    )
    add(
        "count",
        "How many photographs are there?",
        None,
        "count",
        "Exactly three photographs, citing the selection capture_count value and source evidence.",
    )
    add(
        "date",
        "When were these photographs taken?",
        None,
        "date",
        "2025-12-02 from captured_at; 13:43:33 through 13:43:36 UTC if times are given.",
    )
    add(
        "place",
        "What is the name of this mountain?",
        None,
        "missing_place",
        "Decline to name the mountain. Snowy landscape description cannot establish a proper name.",
        supported=False,
    )
    add(
        "identity",
        "What are the names of the people in these photographs?",
        None,
        "missing_identity",
        "Decline to name people. Likeness review and person counts are not names.",
        supported=False,
    )
    add(
        "penguins",
        "Which photos show penguins on a beach?",
        "penguin beach",
        "missing_visual",
        "No caption supports penguins or a beach; abstain.",
        supported=False,
    )
    add(
        "clothing_rephrase",
        "What are they wearing to keep warm?",
        "wearing keep warm",
        "visual",
        "Coveralls and insulated jackets; no invented brands or temperatures.",
        split="holdout",
    )
    add(
        "headgear_rephrase",
        "Which pictures show people holding safety helmets?",
        "people holding safety helmets",
        "visual",
        "All three captions show held dark helmets.",
        split="holdout",
    )
    add(
        "sky",
        "Where is the sky glowing orange?",
        "sky orange",
        "visual",
        "All three captions describe orange sky near the horizon. Sunrise versus sunset is uncertain.",
        split="holdout",
    )
    add(
        "place_rephrase",
        "Which named landmark did we visit?",
        None,
        "missing_place",
        "Decline to name a landmark; captions and GPS do not supply a confirmed name.",
        split="holdout",
        supported=False,
    )
    record = {
        "profile": PROFILE,
        "workspace_id": matching["workspace_id"],
        "eligibility": "Retained authorized snapshot; live currency must be verified under lease.",
        "source_files": [bound_file(root, p) for p in (MATCHING, FIRST_PLACE, WIRE)],
        "corpus": corpus,
        "corpus_sha256": digest(corpus),
        "questions": questions,
        "holdout_policy": "No prompt, threshold or query tuning on holdouts; report every row.",
        "scoring_policy": "Retrieval coverage is separate from human answer review and citation access.",
        "live_current": None,
    }
    return {"record": record, "record_sha256": digest(record)}


def verify_input(frozen: dict, root: Path = ROOT) -> dict:
    if frozen.get("record_sha256") != digest(frozen["record"]):
        raise ValueError("frozen input digest mismatch")
    # A self-consistently rehashed edited gold set must not become a different experiment.
    if frozen != frozen_input(root):
        raise ValueError("input differs from the fixed questions and retained support")
    return frozen["record"]


def compare_retrieval(connection, session, plan, *, query_embedding):
    """A leased, already scoped connection; identical plan/corpus in both real executor arms.

    Caller must hold a stable database snapshot for the pair. A scripted vector only tests
    mechanics, regardless of how well it ranks. No query embedding is generated by this helper.
    """
    if query_embedding is None and plan.semantic_query:
        raise ValueError("fused comparison requires an actual or explicitly scripted query vector")
    validated = validate(connection, plan, session)
    observations = {}
    for arm, vector in (("lexical", None), ("fused", query_embedding)):
        result = execute(connection, validated, query_embedding=vector)
        packet = build_packet(connection, result, workspace_id=session.workspace_id)
        observations[arm] = {
            "capture_ids": [str(c.capture_id) for c in result.captures],
            "citable_capture_ids": sorted({str(i.capture_id) for i in packet.items}),
            "total_matched": result.total_matched,
            "truncated": result.truncated,
        }
    return observations


def score_observation(question: dict, observation: dict | None, corpus: list[dict]) -> dict:
    """Score independently observed retrieval, human correctness and citation access.

    Review is nullable. An all-meta irrelevant response does not automatically pass abstention.
    An HTTP 200, valid citation token or word overlap does not certify factual correctness.
    """
    if observation is None:
        return {
            "executed": False,
            "retrieval_coverage": None,
            "answer_correct": None,
            "citations_accessible": None,
            "failures": [],
            "unexecuted": ["observation"],
        }
    failures = []
    body = observation.get("body") or {}
    selection = body.get("selection")
    actual = None if selection is None else {c["capture_id"] for c in selection["captures"]}
    expected = set(question["expected_capture_ids"])
    eligible = {c["capture_id"] for c in corpus}
    coverage = None
    if actual is not None:
        if actual - eligible:
            failures.append("retrieved_outside_frozen_corpus")
        if expected:
            coverage = {"k": len(actual & expected), "n": len(expected)}
            if not expected <= actual:
                failures.append("retrieval_missed_support")
        # Missing names can legitimately retrieve photographs. Do not label this a retrieval miss.
    if observation.get("status") != 200:
        failures.append("application_http_failure")
    clauses = body.get("answer", {}).get("clauses", [])
    tokens = {t.strip().strip("[]") for c in clauses for t in c.get("citations", [])}
    citations = body.get("citations", {})
    if any(t not in citations for t in tokens):
        failures.append("unresolved_citation_token")
    allowed_hashes = {c["source_sha256"] for c in corpus}
    for token in tokens & citations.keys():
        try:
            if parse_uri(citations[token]).blob_id.hex not in allowed_hashes:
                failures.append("citation_outside_frozen_corpus")
        except ValueError:
            failures.append("invalid_citation_uri")
    if expected and not tokens:
        failures.append("supported_answer_without_citations")
    if any(c.get("type") == "historical" for c in clauses) and question["must_abstain"]:
        failures.append("unsupported_historical_claim")
    review = observation.get("human_review")
    verdict = None if review is None else review.get("correct")
    if verdict is not None and (type(verdict) is not bool or not review.get("rationale")):
        raise ValueError("human review requires a boolean verdict and rationale")
    if verdict is False:
        failures.append("answer_incorrect")
    probes = observation.get("citation_probes", {})
    statuses = [probes.get(citations[t]) for t in tokens if t in citations]
    accessible = (
        None
        if not statuses or any(s is None for s in statuses)
        else all(s == 200 for s in statuses)
    )
    if accessible is False:
        failures.append("citation_inaccessible")
    return {
        "executed": True,
        "retrieval_coverage": coverage,
        "answer_correct": verdict,
        "citations_accessible": accessible,
        "failures": sorted(set(failures)),
        "unexecuted": (["human_review"] if verdict is None else [])
        + (["citation_access"] if expected and accessible is None else []),
    }


def score_comparison(frozen: dict, observations: list[dict], root: Path = ROOT) -> dict:
    record = verify_input(frozen, root)
    indexed = {}
    questions = {q["id"]: q for q in record["questions"]}
    for observation in observations:
        key = (observation["question_id"], observation["arm"])
        if key[0] not in questions or key[1] not in ("lexical", "fused") or key in indexed:
            raise ValueError("unknown or duplicate comparison observation")
        if observation.get("input_sha256") != frozen["record_sha256"]:
            raise ValueError("observation belongs to a different frozen comparison")
        if observation.get("corpus_sha256") != record["corpus_sha256"]:
            raise ValueError("arms must use the same frozen corpus")
        if observation.get("response_kind") not in ("scripted", "live"):
            raise ValueError("responses must distinguish scripted from live")
        indexed[key] = observation
    rows = []
    for q in questions.values():
        arms = {
            arm: score_observation(q, indexed.get((q["id"], arm)), record["corpus"])
            for arm in ("lexical", "fused")
        }
        regressions = []
        left, right = arms["lexical"], arms["fused"]
        if (
            left["retrieval_coverage"] is not None
            and right["retrieval_coverage"] is not None
            and right["retrieval_coverage"]["k"] < left["retrieval_coverage"]["k"]
        ):
            regressions.append("retrieval_coverage")
        for metric in ("answer_correct", "citations_accessible"):
            if left[metric] is True and right[metric] is False:
                regressions.append(metric)
        rows.append(
            {"question_id": q["id"], "split": q["split"], "fused_regressions": regressions, **arms}
        )
    return {
        "profile": "exulanica.companion-acceptance-measurement/v1",
        "input_sha256": frozen["record_sha256"],
        "rows": rows,
        "live_quality_passed": False,
        "status": "prepared_pending_live_comparison_and_human_review",
        "note": "No aggregate promotion: inspect every failure, holdout and unexecuted gate.",
    }


def request_totals(requests: list[dict]) -> dict:
    """Raw provider attempts, including retries/errors. Missing usage or price stays null."""

    def total(key):
        values = [r.get(key) for r in requests]
        return None if any(v is None for v in values) else sum(values)

    costs = [r.get("cost_usd") for r in requests]
    return {
        "request_count": len(requests),
        "latency_ms": total("latency_ms"),
        "prompt_tokens": total("prompt_tokens"),
        "completion_tokens": total("completion_tokens"),
        "cost_usd": None
        if any(c is None for c in costs)
        else str(sum((Decimal(c) for c in costs), Decimal(0))),
    }


class RequestRecorder:
    """Instrument the existing ModelClient transport, including failed/retried HTTP attempts.

    This is not a model client. The activated app still owns its ModelClient and BudgetGuard.
    A caller supplies the written run cap bound to this manifest; no defaults authorize a run.
    Headers, URL, caption inputs, vectors and model text are not copied into accounting rows.
    Retain application wire answers separately for human review.
    """

    def __init__(self, transport, manifest, frozen, cap, budget):
        verify_input(frozen)
        if cap.get("input_sha256") != frozen["record_sha256"]:
            raise ValueError("run cap must bind the frozen corpus and questions")
        if not cap.get("run_id") or not cap.get("authorization_reference"):
            raise ValueError("written per-run authorization reference required")
        if type(cap.get("max_requests")) is not int or cap["max_requests"] <= 0:
            raise ValueError("positive request cap required")
        spend = Decimal(cap.get("max_usd", "NaN"))
        if not spend.is_finite() or spend <= 0 or not cap.get("models"):
            raise ValueError("positive spend cap and explicit models required")
        if budget.ceiling_usd != spend or budget.max_calls != cap["max_requests"]:
            raise ValueError("application BudgetGuard must match the written run cap")
        self.budget = budget
        self.transport, self.manifest, self.cap = transport, manifest, dict(cap)
        self.requests = []

    def _refuse(self, reason):
        raise BudgetExceededError(
            reason,
            spent_usd=request_totals(self.requests)["cost_usd"],
            ceiling_usd=self.cap["max_usd"],
        )

    def get_json(self, url, **kwargs):
        return self.transport.get_json(url, **kwargs)

    def post_json(self, url, *, headers, payload, timeout):
        requested = payload.get("model")
        if requested not in self.cap["models"]:
            self._refuse("model outside the written run cap")
        if len(self.requests) >= self.cap["max_requests"]:
            self._refuse("per-run HTTP request cap reached")
        totals = request_totals(self.requests)
        # Unknown usage may already have consumed the remainder: refuse the next request.
        if totals["cost_usd"] is None or Decimal(totals["cost_usd"]) >= Decimal(
            self.cap["max_usd"]
        ):
            self._refuse("per-run spend is exhausted or unavailable")
        projected = self.budget.estimate_usd(
            self.manifest.spec(requested),
            prompt_chars=len(json.dumps(payload)),
            max_tokens=payload.get("max_tokens", 0),
        )
        if Decimal(totals["cost_usd"]) + projected > Decimal(self.cap["max_usd"]):
            self._refuse("next request could exceed the per-run spend cap")
        row = {
            "ordinal": len(self.requests) + 1,
            "run_id": self.cap["run_id"],
            "requested_model": requested,
            "served_model": None,
            "status": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "cost_usd": None,
            "latency_ms": None,
            "error_type": None,
        }
        self.requests.append(row)
        started = perf_counter()
        try:
            response = self.transport.post_json(
                url, headers=headers, payload=payload, timeout=timeout
            )
            row["status"] = response.status_code
            try:
                body = response.json_body()
            except Exception:
                body = {}
            if isinstance(body, Mapping):
                echo = body.get("model")
                row["served_model"] = echo if isinstance(echo, str) and echo else None
                usage = body.get("usage")
                if isinstance(usage, Mapping):
                    for key in ("prompt_tokens", "completion_tokens"):
                        value = usage.get(key)
                        if type(value) is int and value >= 0:
                            row[key] = value
                    # Embeddings report prompt_tokens only; they have no completion channel.
                    if "input" in payload and row["prompt_tokens"] is not None:
                        row["completion_tokens"] = 0
                if row["prompt_tokens"] is not None and row["completion_tokens"] is not None:
                    row["cost_usd"] = str(
                        self.manifest.spec(requested).cost_usd(
                            prompt_tokens=row["prompt_tokens"],
                            completion_tokens=row["completion_tokens"],
                        )
                    )
            return response
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            raise
        finally:
            row["latency_ms"] = round((perf_counter() - started) * 1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    frozen = frozen_input()
    for name, value in (
        ("input-manifest.json", frozen),
        ("measurements.json", score_comparison(frozen, [])),
    ):
        with (args.out / name).open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(value).decode() + "\n")
    print(f"Frozen {len(frozen['record']['questions'])} questions; no database or hosted calls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
