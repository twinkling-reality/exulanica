# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Verify the Tavily credential with one real runtime call, and record the request.

Doubles as the first exercise of Exulanica's past-to-present boundary: the query
carries ONLY public-entity context. No private media, no person, no private
location, no transcript. That constraint is the point of the test, not an
incidental detail.

Nothing of the response is kept or printed beyond its status, latency, result
count, credits and request id: Tavily's terms give no right to keep or show a
result (THIRD_PARTY_NOTICES.md section 3.4).
"""
import json, pathlib, sys, time
import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / ".exulanica" / "experiments" / "web-lookup"

# A well-known public landmark, standing in for the class of public entity a
# corpus photograph can contain. Nothing private is sent.
PUBLIC_ENTITY_QUERY = "Eiffel Tower Paris visitor access and conditions"


def main():
    key = ""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("TAVILY_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        print("TAVILY_API_KEY not set in .env")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "query": PUBLIC_ENTITY_QUERY,
        "max_results": 3,
        "search_depth": "basic",
        "include_answer": False,
        "include_usage": True,
    }
    t0 = time.time()
    r = httpx.post("https://api.tavily.com/search", timeout=60,
                   headers={"Authorization": f"Bearer {key}",
                            "Content-Type": "application/json"},
                   json=payload)
    dt = time.time() - t0
    ok = r.status_code == 200
    body = r.json() if ok else {}

    results = body.get("results", []) if ok else []
    credits = (body.get("usage") or {}).get("credits") if ok else None
    request_id = body.get("request_id") if ok else None

    # Record the request, never the response: the request is the evidence that
    # no private payload was sent.
    (OUT / "tavily_runtime_call.json").write_text(json.dumps({
        "request": payload, "status": r.status_code,
        "latency_s": round(dt, 3), "result_count": len(results),
        "credits": credits, "request_id": request_id,
    }, indent=2))

    if ok:
        print(f"[PASS] Tavily HTTP 200 in {dt:.2f}s, {len(results)} results, "
              f"{credits} credits")
        print(f"       Recorded the request to {OUT / 'tavily_runtime_call.json'}")
        print("       Payload contained public-entity text only. No private data sent.")
    else:
        # An error body is Tavily's own message about the request, not a result.
        print(f"[FAIL] HTTP {r.status_code}: {r.text[:300]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
