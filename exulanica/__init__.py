"""Exulanica: Worlds for AI Agents, built on an evidence-addressed spine.

Two things in this package are load bearing and everything else is downstream of them:

*   ``exulanica.evidence`` holds the address type. Every factual claim in the product resolves to
    original media through it. Reconstruction is a navigation substrate, never evidence.
*   ``exulanica.store`` holds the content-addressed object store. Its normal interface has no
    delete; erasure is a separate, explicitly authorised operation, so an injected or
    accidental deletion is not expressible from the request path.

Storage is append-only **by policy**, which is exactly as strong as the bucket policy behind it.
It is not immutable, not WORM, and not tamper-proof, and the platform provides no mechanism that
would make those words true.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
