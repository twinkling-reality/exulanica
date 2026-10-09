"""A kept generated piece as the worker records it, for tests that need one without a session.

The receipt holds exactly what the installation's index checks against it (``generated_piece``'s
constraints): its request, variant, components, post-process version, output and verdict. The cache
key is computed from those parts as :func:`exulanica_pieces.records.cache_key` computes it.
"""

from __future__ import annotations

from exulanica.generation.batches import KeptOutput
from exulanica.generation.entries import Output
from exulanica_pieces.canonical import canonical_bytes, sha256_hex
from exulanica_pieces.records import POSTPROCESS_VERSION, cache_key

COMPONENTS = "c0" * 32


def kept_output(request_sha256: str, variant: int = 0, *, within: bool = True) -> KeptOutput:
    piece = f"a piece for {request_sha256[:12]} variant {variant}".encode()
    verdict = {"over": [] if within else ["triangles"], "within": within}
    receipt = canonical_bytes(
        {
            "components_sha256": COMPONENTS,
            "output": {"bytes": len(piece), "sha256": sha256_hex(piece)},
            "postprocess": {"version": POSTPROCESS_VERSION},
            "request_sha256": request_sha256,
            "variant": variant,
            "verdict": verdict,
        }
    )
    output = Output(
        receipt_sha256=sha256_hex(receipt),
        receipt=receipt,
        document={"request_sha256": request_sha256, "variant": variant, "verdict": verdict},
        piece_sha256=sha256_hex(piece),
        piece=piece,
    )
    return KeptOutput(
        output=output,
        cache_key=cache_key(request_sha256, COMPONENTS, POSTPROCESS_VERSION),
        components_sha256=COMPONENTS,
        postprocess_version=POSTPROCESS_VERSION,
    )
