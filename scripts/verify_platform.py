# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Platform verification harness for Exulanica.

Runs the first real runtime calls against Nebius Token Factory and archives the
evidence. Until this passes, the project may not claim NVIDIA model use.

Covers experiments X-0a (provenance record), X-0d (multimodal capability), the
catalog preflight, structured-output support, and the tokens-per-image
measurement that dominates the ingestion cost model.

Usage:  uv run scripts/verify_platform.py
"""

import base64
import json
import os
import pathlib
import struct
import sys
import time
import zlib

import httpx

BASE = "https://api.tokenfactory.nebius.com/v1"
CATALOG = "https://tokenfactory.nebius.com/api/public/models_info"
OUT = pathlib.Path(__file__).resolve().parents[1] / ".exulanica" / "experiments" / "platform"

# The model manifest. Every id here is checked against the live catalog before use.
# Roles map to docs/model-and-service-selection.md.
MANIFEST = {
    "reasoning_cheap":  {"id": "nvidia/Nemotron-3_5-Lightning",        "fallback": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"},
    "reasoning_mid":    {"id": "nvidia/nemotron-3-super-120b-a12b",    "fallback": "nvidia/Nemotron-3_5-Lightning"},
    "reasoning_hard":   {"id": "nvidia/Nemotron-3-Ultra-550b-a55b",    "fallback": "nvidia/nemotron-3-super-120b-a12b"},
    "vision":           {"id": "MiniMaxAI/MiniMax-M3",                 "fallback": "openbmb/MiniCPM-V-4_5"},
    "embedding":        {"id": "Qwen/Qwen3-Embedding-8B",              "fallback": None},
}

results = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": []}


def record(name, ok, detail, **extra):
    entry = {"check": name, "ok": ok, "detail": detail, **extra}
    results["checks"].append(entry)
    mark = "PASS" if ok else ("WARN" if ok is None else "FAIL")
    print(f"[{mark}] {name}: {detail}")
    return entry


def png(width, height):
    """Minimal deterministic PNG: a red square on white with a black bar.

    Generated rather than shipped so the repo carries no binary test asset and
    the content is known exactly, which is what makes comprehension checkable.
    """
    rows = []
    for y in range(height):
        row = bytearray([0])  # filter byte
        for x in range(width):
            if height * 0.25 < y < height * 0.75 and width * 0.25 < x < width * 0.55:
                row += bytes([220, 30, 30])       # red block
            elif height * 0.80 < y < height * 0.90:
                row += bytes([0, 0, 0])           # black bar
            else:
                row += bytes([255, 255, 255])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def main():
    key = os.environ.get("NEBIUS_API_KEY", "").strip()
    if not key:
        env = pathlib.Path(__file__).resolve().parents[1] / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("NEBIUS_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        print("NEBIUS_API_KEY not set. Put it in .env or export it. Nothing else can run.")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=180.0, headers={"Authorization": f"Bearer {key}"})

    # --- Catalog preflight. Fails loudly if a manifest id vanished. -----------
    try:
        cat = httpx.get(CATALOG, timeout=60).json()
        live = set()
        for m in cat:
            for f in m.get("flavors", []):
                if f.get("model_id"):
                    live.add(f["model_id"])
        (OUT / "catalog_snapshot.json").write_text(json.dumps(cat, indent=2))
        missing = [f"{r}={v['id']}" for r, v in MANIFEST.items() if v["id"] not in live]
        record("catalog_preflight", not missing,
               f"{len(live)} live ids; missing from catalog: {missing or 'none'}",
               missing=missing)
    except Exception as e:
        record("catalog_preflight", False, f"catalog fetch failed: {e!r}")

    # --- X-0a. The provenance record. This is what licenses the NVIDIA claim. -
    mid = MANIFEST["reasoning_cheap"]["id"]
    try:
        t0 = time.time()
        r = client.post(f"{BASE}/chat/completions", json={
            "model": mid,
            "messages": [{"role": "user",
                          "content": "Reply with exactly the word: EXULANICA"}],
            "max_tokens": 800, "temperature": 0,
        })
        dt = time.time() - t0
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
        archive = {
            "request_model": mid, "status": r.status_code,
            "latency_s": round(dt, 3),
            "response_headers": dict(r.headers),
            "response_body": body,
        }
        (OUT / "x0a_nvidia_provenance.json").write_text(json.dumps(archive, indent=2))
        echoed = body.get("model") if isinstance(body, dict) else None
        record("x0a_nvidia_runtime_call", r.status_code == 200,
               f"HTTP {r.status_code}, echoed model={echoed!r}, {dt:.2f}s. Archived.",
               echoed_model=echoed)
    except Exception as e:
        record("x0a_nvidia_runtime_call", False, f"{e!r}")

    # --- Structured output. Decides whether canonical state can be schema-safe.
    try:
        r = client.post(f"{BASE}/chat/completions", json={
            "model": mid,
            "messages": [{"role": "user", "content": "Return the colours of the French flag."}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "colours", "strict": True,
                    "schema": {"type": "object", "additionalProperties": False,
                               "required": ["colours"],
                               "properties": {"colours": {"type": "array",
                                                          "items": {"type": "string"}}}},
                },
            },
            "max_tokens": 2000, "temperature": 0,
        })
        ok = r.status_code == 200
        parsed = None
        if ok:
            try:
                parsed = json.loads(r.json()["choices"][0]["message"]["content"])
            except Exception:
                ok = False
        (OUT / "structured_output.json").write_text(
            json.dumps({"status": r.status_code, "body": r.json() if ok else r.text}, indent=2))
        rt = None
        if r.status_code == 200:
            rt = (r.json().get("usage", {}).get("completion_tokens_details") or {}).get("reasoning_tokens")
        record("structured_output_json_schema", ok,
               f"HTTP {r.status_code}, parsed={parsed}, reasoning_tokens={rt}",
               reasoning_tokens=rt)
    except Exception as e:
        record("structured_output_json_schema", False, f"{e!r}")

    # --- X-0d. Does the vision model accept images, and what do they cost? ----
    # The catalog types MiniMax-M3 as text2text but declares image/video in
    # use_cases. This settles it, and measures tokens per image at two sizes so
    # the ingestion cost model stops being an estimate.
    vid = MANIFEST["vision"]["id"]
    per_image = {}
    for side in (256, 768):
        try:
            b64 = base64.b64encode(png(side, side)).decode()
            r = client.post(f"{BASE}/chat/completions", json={
                "model": vid,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Describe the shapes and their colours."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]}],
                "max_tokens": 800, "temperature": 0,
            })
            ok = r.status_code == 200
            usage, text = None, None
            if ok:
                b = r.json()
                usage = b.get("usage")
                text = b["choices"][0]["message"]["content"][:200]
                per_image[side] = usage.get("prompt_tokens") if usage else None
            (OUT / f"x0d_vision_{side}.json").write_text(
                json.dumps({"model": vid, "status": r.status_code,
                            "body": r.json() if ok else r.text}, indent=2))
            record(f"x0d_vision_image_{side}px", ok,
                   f"HTTP {r.status_code}, prompt_tokens={per_image.get(side)}, saw: {text!r}")
        except Exception as e:
            record(f"x0d_vision_image_{side}px", False, f"{e!r}")

    if len(per_image) == 2 and all(per_image.values()):
        lo, hi = per_image[256], per_image[768]
        cost_1000 = (hi * 0.30 + 500 * 1.20) / 1e6 * 1000
        record("cost_model", True,
               f"prompt_tokens 256px={lo}, 768px={hi}. At 768px, 1000 photos "
               f"is about ${cost_1000:.2f} on {vid}.", tokens=per_image)

    # --- Embeddings. The role with no possible fallback. ---------------------
    try:
        r = client.post(f"{BASE}/embeddings", json={
            "model": MANIFEST["embedding"]["id"], "input": "exulanica evidence span"})
        ok = r.status_code == 200
        dim = len(r.json()["data"][0]["embedding"]) if ok else None
        record("embeddings", ok, f"HTTP {r.status_code}, dim={dim}")
    except Exception as e:
        record("embeddings", False, f"{e!r}")

    results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    passed = sum(1 for c in results["checks"] if c["ok"] is True)
    results["summary"] = f"{passed}/{len(results['checks'])} passed"
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\n{results['summary']}. Artifacts in {OUT}")
    return 0 if passed == len(results["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
