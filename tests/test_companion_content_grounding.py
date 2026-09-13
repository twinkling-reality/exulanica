from __future__ import annotations

import uuid

from exulanica.selection.executor import SelectedContent, SelectionResult
from exulanica.selection.packet import build_content_packet
from exulanica.selection.plan import Intent
from exulanica.selection.question import render_content_answer

PLACE = uuid.UUID("bc9a2107-cd67-4fe5-be70-570158cffdfa")
VERSION = uuid.UUID("1b39b2b3-9534-441d-88e6-0b62623ef22a")


def _content(kind: str, label: str, *, visit: bool = False) -> SelectedContent:
    return SelectedContent(
        result_kind=kind,
        origin_kind={
            "memory_capture": "personal",
            "authored_environment_instance": "authored",
        }.get(
            kind,
            "simulated" if kind.startswith("sim") or kind.startswith("synthetic") else "imported",
        ),
        content_kind="content",
        authored_role="fictional" if kind == "authored_environment_instance" else None,
        place_relationship="simulated_at" if kind.startswith("sim") else "admitted_for",
        match_reason="fixture",
        memory_place_entity_id=PLACE,
        canonical_place_id=PLACE,
        world_id="atlas" if kind != "memory_capture" else None,
        version_id=VERSION if kind != "memory_capture" else None,
        source_id=f"source:{kind}",
        lineage_ids=(f"lineage:{kind}",),
        label=label,
        availability="available",
        personal_visit_evidence=visit,
    )


def test_content_answer_keeps_source_memory_authored_and_simulated_truth_separate():
    answer = render_content_answer(
        (
            _content("memory_capture", "photograph", visit=True),
            _content("admitted_environment_source", "NYC Open Data"),
            _content("authored_environment_instance", "illuminated Flatiron"),
            _content("synthetic_inhabitant", "Ari Ash · synthetic baker"),
            _content("simulation_event", "Ari departed on schedule"),
        )
    )
    text = " ".join(clause.text for clause in answer.clauses)

    assert "Authorized memory evidence" in text
    assert "Admitted source record" in text
    assert "modifies a version, not its source record" in text
    assert "not a real resident" in text
    assert "not a real-world visit" in text
    assert text.endswith("Imported, authored, and simulated records cannot.")


def test_content_answer_is_bounded_and_does_not_invent_real_residents():
    answer = render_content_answer(
        tuple(_content("synthetic_inhabitant", f"Synthetic {index}") for index in range(20))
    )

    assert len(answer.clauses) == 9
    assert all("real resident" in clause.text for clause in answer.clauses[:-1])


def test_content_packet_uses_unforgeable_handles_and_keeps_truth_classes_separate():
    content = (
        _content("memory_capture", "photograph", visit=True),
        _content("admitted_environment_source", "NYC Open Data"),
        _content("authored_environment_instance", "fantasy addition"),
        _content("simulation_event", "scheduled departure"),
    )
    packet = build_content_packet(
        SelectionResult(
            intent=Intent.CONTENT,
            captures=(),
            entities=(),
            total_matched=len(content),
            includes_proposals=False,
            content=content,
        )
    )

    assert {item.truth_class for item in packet.items} == {
        "authorized_memory",
        "admitted_source",
        "authored_version",
        "simulation",
    }
    assert len({item.token for item in packet.items}) == len(content)
    assert packet.resolve(packet.items[0].token) == packet.items[0]
    assert packet.resolve("INVENTED") is None
    assert [item.personal_visit_evidence for item in packet.items] == [True, False, False, False]
