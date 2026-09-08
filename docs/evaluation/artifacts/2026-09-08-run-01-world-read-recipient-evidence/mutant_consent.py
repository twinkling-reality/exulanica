"""Executed negative control: disable one exact recipient check."""
def pytest_sessionstart(session: object) -> None:
    import exulanica.graph.world_read_verification as verifier
    original = verifier.require
    def broken(condition: bool, reason: str) -> None:
        if reason != 'consent_digest_mismatch':
            original(condition, reason)
    verifier.require = broken
