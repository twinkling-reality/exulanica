"""Check a running judge stack from outside it, the way a judge's browser reaches it.

    uv run python scripts/judge_smoke.py --origin https://<host> --token-file <judge token file> \\
        [--cafile <root certificate>] [--http-origin http://<host>] [--rate-limit] \\
        [--ask "<question>"] [--out <record.json>]

Every request goes through the public origin, so each check covers the edge, the web proxy and
the API together. The checks, in order:

* the client is served at the origin root, and its hashed assets are cached as immutable;
* liveness and readiness answer through ``/api``, and readiness reports every check passing;
* a read without a credential is refused with 401, and with the judge's token it answers;
* with ``--http-origin``, plain HTTP redirects to HTTPS;
* with ``--ask``, one Companion question is asked in the seeded world. This is the only check that
  can call a hosted model and spend;
* with ``--rate-limit``, last, because it spends this address's burst: a burst of writes meets 429
  after the burst the web proxy allows. The writes carry no credential, so the API refuses each
  one it sees, and nothing is written or spent.

The token is read from a token directory file (``exulanica-seed token`` writes one) and is never
printed or written. The standard library only, so it runs on a host with Python and nothing else.
Exits 0 when every check that ran passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final

#: Longer than a graph read's cold start on the rehearsal laptop (docs/judge-access.md section 6)
#: and shorter than a person would wait. The ask has its own, longer bound.
READ_TIMEOUT_S: Final = 60.0
#: The web proxy and the edge both allow 300 s for a question, so the smoke waits as long.
ASK_TIMEOUT_S: Final = 300.0
#: More writes than the web proxy's burst of 20 (deploy/judge/web.Dockerfile), so a working limit
#: must refuse some of them.
RATE_LIMIT_PROBES: Final = 40


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Smoke:
    def __init__(self, origin: str, context: ssl.SSLContext, read_timeout: float) -> None:
        self.origin = origin.rstrip("/")
        self.read_timeout = read_timeout
        self.last_error: str | None = None
        self.context = context
        self.checks: list[dict[str, Any]] = []
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context), _NoRedirect()
        )

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        token: str | None = None,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict[str, str], bytes, float]:
        """Status, headers, body and seconds. A header sent twice is joined with ", ".

        A connection that fails or times out answers status 0 with the error as the body, so it
        is a failed check in the record rather than a traceback that ends the run.
        """
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request((origin or self.origin) + path, data=data, method=method)
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        started = time.monotonic()
        try:
            with self.opener.open(request, timeout=timeout or self.read_timeout) as response:
                payload = response.read()
                status, message = response.status, response.headers
        except urllib.error.HTTPError as error:
            payload = error.read()
            status, message = error.code, error.headers
        except (urllib.error.URLError, OSError) as error:
            self.last_error = repr(error)
            return 0, {}, b"", round(time.monotonic() - started, 3)
        headers = {name: ", ".join(message.get_all(name) or []) for name in set(message.keys())}
        return status, headers, payload, round(time.monotonic() - started, 3)

    def record(self, name: str, passed: bool, **detail: Any) -> bool:
        if detail.get("status") == 0:
            detail["error"], self.last_error = self.last_error, None
        self.checks.append({"check": name, "passed": passed, **detail})
        print(f"{'pass' if passed else 'FAIL'}  {name}  {json.dumps(detail, sort_keys=True)}")
        return passed


def _token_from(path: Path) -> str:
    """The one token in a judge's token directory file. Refuses a file holding several."""
    directory = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(directory, dict) or len(directory) != 1:
        raise SystemExit(f"{path} must hold exactly one token; give one judge's file")
    return next(iter(directory))


def run(arguments: argparse.Namespace) -> int:
    context = ssl.create_default_context(cafile=arguments.cafile)
    smoke = Smoke(arguments.origin, context, arguments.read_timeout)
    token = _token_from(Path(arguments.token_file))

    status, headers, body, seconds = smoke.request("/")
    page = body.decode("utf-8", "replace")
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page)
    smoke.record(
        "client served at the origin root",
        status == 200 and "text/html" in headers.get("Content-Type", "") and bool(assets),
        status=status,
        assets=len(assets),
        seconds=seconds,
    )
    if assets:
        status, headers, body, seconds = smoke.request(assets[0])
        smoke.record(
            "hashed asset cached as immutable",
            status == 200 and "immutable" in headers.get("Cache-Control", ""),
            status=status,
            cache_control=headers.get("Cache-Control"),
            bytes=len(body),
        )

    status, _, _, seconds = smoke.request("/api/healthz")
    smoke.record("liveness through the edge", status == 200, status=status, seconds=seconds)

    status, _, body, seconds = smoke.request("/api/readyz")
    try:
        readiness = json.loads(body)
    except ValueError:
        readiness = {}
    checks = readiness.get("checks", {})
    smoke.record(
        "readiness through the edge",
        status == 200 and readiness.get("ready") is True,
        status=status,
        failing=sorted(name for name, check in checks.items() if not check.get("ok")),
        warnings=len(readiness.get("warnings", [])),
        seconds=seconds,
    )

    status, _, _, _ = smoke.request("/api/graph")
    smoke.record("a read without a credential is refused", status == 401, status=status)

    status, _, body, seconds = smoke.request("/api/graph", token=token)
    smoke.record(
        "the judge reads the graph", status == 200, status=status, bytes=len(body), seconds=seconds
    )

    status, _, body, seconds = smoke.request("/api/worlds", token=token)
    worlds = json.loads(body).get("worlds", []) if status == 200 else []
    smoke.record(
        "the judge lists the seeded worlds",
        status == 200 and bool(worlds),
        status=status,
        worlds=[world.get("kind") for world in worlds],
        seconds=seconds,
    )

    if arguments.http_origin:
        status, headers, _, _ = smoke.request("/", origin=arguments.http_origin.rstrip("/"))
        location = headers.get("Location", "")
        smoke.record(
            "plain HTTP redirects to HTTPS",
            status in (301, 302, 307, 308) and location.startswith("https://"),
            status=status,
            location=location,
        )

    if arguments.ask:
        world = next((w["world_id"] for w in worlds), None)
        if world is None:
            smoke.record("the Companion answers", False, reason="no world to ask in")
        else:
            status, _, body, seconds = smoke.request(
                f"/api/selection/ask?world_id={urllib.parse.quote(world)}",
                method="POST",
                token=token,
                body={"question": arguments.ask},
                timeout=ASK_TIMEOUT_S,
            )
            answer = json.loads(body) if body.startswith(b"{") else {}
            calls = (answer.get("execution") or {}).get("calls") or []
            smoke.record(
                "the Companion answers",
                status == 200,
                status=status,
                seconds=seconds,
                deterministic=answer.get("deterministic"),
                abstained=answer.get("abstained"),
                # What each attempt cost and which model served it; never the answer's text.
                calls=[
                    {
                        key: call.get(key)
                        for key in ("role", "served_model", "outcome", "cost_basis", "usd")
                    }
                    for call in calls
                ],
                refusal=answer.get("code") or answer.get("detail") if status != 200 else None,
            )

    if arguments.rate_limit:
        statuses: list[int] = []
        for _ in range(RATE_LIMIT_PROBES):
            status, _, _, _ = smoke.request(
                "/api/selection/ask?world_id=probe", method="POST", body={"question": "probe"}
            )
            statuses.append(status)
        counted = {str(code): statuses.count(code) for code in sorted(set(statuses))}
        smoke.record(
            "writes from one address meet the per-address limit",
            429 in statuses and set(statuses) <= {401, 429} and statuses[0] == 401,
            statuses=counted,
        )

    passed = all(check["passed"] for check in smoke.checks)
    if arguments.out:
        record = {
            "schema": "exulanica.judge-smoke/v1",
            "origin": smoke.origin,
            "ran_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "passed": passed,
            "checks": smoke.checks,
        }
        Path(arguments.out).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"{'passed' if passed else 'FAILED'}: {len(smoke.checks)} checks")
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="judge_smoke.py", description=__doc__.split("\n")[0])
    parser.add_argument("--origin", required=True, help="the HTTPS origin judges open")
    parser.add_argument("--token-file", required=True, help="one judge's token directory file")
    parser.add_argument("--cafile", help="a root certificate to trust, for a rehearsal's edge")
    parser.add_argument("--http-origin", help="the plain HTTP origin, to check the redirect")
    parser.add_argument("--rate-limit", action="store_true", help="probe the per-address limit")
    parser.add_argument("--ask", help="ask the Companion one question; may spend")
    parser.add_argument("--out", help="write the checks as a JSON record here")
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=READ_TIMEOUT_S,
        help="seconds to wait for each read; raise it for an emulated rehearsal",
    )
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
