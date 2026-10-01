"""The object store's request signer, held to AWS's published Signature Version 4 cases.

``tests/vectors/aws-sigv4-test-suite/`` holds the cases of the AWS Signature Version 4 Test Suite
that apply to S3, copied unchanged with the suite's LICENSE and NOTICE (THIRD_PARTY_NOTICES.md names
the source and the file set). Every case directory found there runs; each compares the canonical
request, the string to sign and the Authorization header byte for byte.

Left out, because S3 does not do what they test: ``normalize-path/*`` and ``get-utf8`` (the
generic suite resolves ``.`` segments and encodes the path twice; S3 does neither),
``get-header-value-multiline`` (a folded header value, which no S3 request here sends),
``get-vanilla-with-session-token`` and ``post-sts-token/*`` (temporary credentials, which this
store does not accept).

The S3 rules the generic suite does not cover are held by the four worked examples in the Amazon S3
API Reference's Signature Version 4 header authentication page: a path encoded once, and the payload
digest carried in ``x-amz-content-sha256``.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from exulanica.store.sigv4 import (
    EMPTY_PAYLOAD_SHA256,
    RequestSigner,
    s3_canonical_uri,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "tests" / "vectors" / "aws-sigv4-test-suite"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
CASES = sorted(path.name for path in SUITE.iterdir() if path.is_dir())

#: The suite's own example credentials and signing time.
SUITE_KEY_ID = "AKIDEXAMPLE"
SUITE_SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
SUITE_TIME = datetime(2015, 8, 30, 12, 36, tzinfo=UTC)


def _parse(raw: str) -> tuple[str, str, list[tuple[str, str]], list[tuple[str, str]], bytes]:
    """A suite ``.req`` file: request line, ``Name:value`` headers, a blank line, the body."""
    head, _, body = raw.partition("\n\n")
    first, *lines = head.split("\n")
    method, target, _version = first.split(" ")
    headers = [tuple(line.split(":", 1)) for line in lines if line]
    path, _, query_string = target.partition("?")
    query = [
        (urllib.parse.unquote(name), urllib.parse.unquote(value))
        for name, _, value in (part.partition("=") for part in query_string.split("&") if part)
    ]
    return method, path, query, headers, body.encode("utf-8")  # type: ignore[return-value]


def test_the_suite_holds_every_case_this_module_names():
    assert len(CASES) == 21, CASES
    for case in CASES:
        assert sorted(p.suffix for p in (SUITE / case).iterdir()) == [
            ".authz",
            ".creq",
            ".req",
            ".sts",
        ]


@pytest.mark.parametrize("case", CASES)
def test_the_signer_reproduces_the_published_case(case):
    directory = SUITE / case
    method, path, query, headers, body = _parse(
        (directory / f"{case}.req").read_text(encoding="utf-8")
    )
    signer = RequestSigner(SUITE_KEY_ID, SUITE_SECRET, region="us-east-1", service="service")
    signed = signer.sign(method, path, query, headers, hashlib.sha256(body).hexdigest(), SUITE_TIME)
    assert signed.canonical_request == (directory / f"{case}.creq").read_text(encoding="utf-8")
    assert signed.string_to_sign == (directory / f"{case}.sts").read_text(encoding="utf-8")
    assert signed.authorization == (directory / f"{case}.authz").read_text(encoding="utf-8")


# The Amazon S3 API Reference's worked examples: bucket ``examplebucket``, 2013-05-24, us-east-1.
S3_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
S3_HOST = "examplebucket.s3.amazonaws.com"
S3_TIME = datetime(2013, 5, 24, tzinfo=UTC)
WELCOME = hashlib.sha256(b"Welcome to Amazon S3.").hexdigest()
S3_EXAMPLES = {
    "get-object": (
        "GET",
        "/test.txt",
        [],
        [
            ("Host", S3_HOST),
            ("Range", "bytes=0-9"),
            ("x-amz-content-sha256", EMPTY_PAYLOAD_SHA256),
            ("x-amz-date", "20130524T000000Z"),
        ],
        EMPTY_PAYLOAD_SHA256,
        "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
    ),
    "put-object": (
        "PUT",
        "/test$file.text",
        [],
        [
            ("Host", S3_HOST),
            ("Date", "Fri, 24 May 2013 00:00:00 GMT"),
            ("x-amz-date", "20130524T000000Z"),
            ("x-amz-storage-class", "REDUCED_REDUNDANCY"),
            ("x-amz-content-sha256", WELCOME),
        ],
        WELCOME,
        "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd",
    ),
    "get-bucket-lifecycle": (
        "GET",
        "/",
        [("lifecycle", "")],
        [
            ("Host", S3_HOST),
            ("x-amz-date", "20130524T000000Z"),
            ("x-amz-content-sha256", EMPTY_PAYLOAD_SHA256),
        ],
        EMPTY_PAYLOAD_SHA256,
        "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543",
    ),
    "list-objects": (
        "GET",
        "/",
        [("max-keys", "2"), ("prefix", "J")],
        [
            ("Host", S3_HOST),
            ("x-amz-date", "20130524T000000Z"),
            ("x-amz-content-sha256", EMPTY_PAYLOAD_SHA256),
        ],
        EMPTY_PAYLOAD_SHA256,
        "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7",
    ),
}


@pytest.mark.parametrize("example", sorted(S3_EXAMPLES))
def test_the_signer_reproduces_the_s3_worked_example(example):
    method, path, query, headers, payload, signature = S3_EXAMPLES[example]
    signer = RequestSigner("EXAMPLEKEYID", S3_SECRET, region="us-east-1", service="s3")
    signed = signer.sign(method, s3_canonical_uri(path), query, headers, payload, S3_TIME)
    assert signed.authorization.endswith(f"Signature={signature}")


def test_an_s3_path_is_encoded_once_and_never_normalised():
    assert s3_canonical_uri("/test$file.text") == "/test%24file.text"
    assert s3_canonical_uri("/a/./b/../c") == "/a/./b/../c"
    assert s3_canonical_uri("/key with space") == "/key%20with%20space"
    assert s3_canonical_uri("/ሴ") == "/%E1%88%B4"
    with pytest.raises(ValueError):
        s3_canonical_uri("relative")


def test_the_secret_never_appears_in_what_a_signer_prints():
    signer = RequestSigner("EXAMPLEKEYID", S3_SECRET, region="us-east-1")
    signed = signer.sign(
        "GET",
        "/",
        [],
        [("host", S3_HOST), ("x-amz-date", "20130524T000000Z")],
        EMPTY_PAYLOAD_SHA256,
        S3_TIME,
    )
    for text in (repr(signer), str(signer)):
        assert S3_SECRET not in text and "EXAMPLEKEYID" not in text
    for text in (str(signed), repr(signed)):
        assert S3_SECRET not in text
    assert not hasattr(signer, "__dict__"), "no attribute outside the declared slots"


def test_a_signing_time_the_headers_do_not_state_is_refused():
    signer = RequestSigner("EXAMPLEKEYID", S3_SECRET, region="us-east-1")
    headers = [("host", S3_HOST), ("x-amz-date", "20130524T000000Z")]
    with pytest.raises(ValueError, match="x-amz-date"):
        signer.sign("GET", "/", [], headers, EMPTY_PAYLOAD_SHA256, S3_TIME + timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone"):
        signer.sign("GET", "/", [], headers, EMPTY_PAYLOAD_SHA256, datetime(2013, 5, 24))
    # The same instant in another zone is the same signing time.
    eastern = S3_TIME.astimezone(timezone(timedelta(hours=-4)))
    assert signer.sign("GET", "/", [], headers, EMPTY_PAYLOAD_SHA256, eastern).amz_date == (
        "20130524T000000Z"
    )


def test_the_notices_row_names_exactly_these_suite_files():
    """The copied files and the row that discloses them cannot drift apart silently."""
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(SUITE).as_posix()}"
        for path in sorted(p for p in SUITE.rglob("*") if p.is_file())
    ]
    manifest = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
    row = next(
        line
        for line in NOTICES.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `tests/vectors/aws-sigv4-test-suite/`")
    )
    assert f"{len(lines)} files" in row
    assert re.search(rf"manifest SHA-256 `{manifest}`", row), row
