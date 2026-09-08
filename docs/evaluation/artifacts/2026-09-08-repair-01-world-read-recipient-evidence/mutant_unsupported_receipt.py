"""Executed control: restore unchecked receipt projection."""
def pytest_sessionstart(session: object) -> None:
    import exulanica.graph.world_read_evidence as evidence
    def unchecked(value: object, expected_profile: str) -> None:
        return None
    evidence.receipt_problem = unchecked
