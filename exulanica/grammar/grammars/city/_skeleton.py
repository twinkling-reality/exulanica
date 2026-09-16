"""How a city stage with no generator is declared. One sentence, the same for every stage."""

from __future__ import annotations

from collections.abc import Callable

from exulanica.grammar.contract import UnimplementedStage


def skeleton(
    stage_id: str, stage_version: int, *validators: tuple[type, Callable[[object], None]]
) -> UnimplementedStage:
    return UnimplementedStage(
        stage_id=stage_id,
        stage_version=stage_version,
        reason=(
            f"the {stage_id} stage has a record shape and a validator and no generator; "
            "it emits nothing rather than plausible output"
        ),
        validators=tuple(validators),
    )
