"""Declared synthetic graph inputs for social mechanics, not admitted scene evidence."""

import uuid
from copy import deepcopy

from exulanica.world.society import society_state_sha256
from exulanica.world.society_decisions import REQUEST_PROFILE, receipt_for
from exulanica.world.society_decisions import seal as seal_request
from exulanica.world.society_social import decision_context

from society_fixtures import VERSION, edited, seal, society_input


def social_input(version_id=VERSION):
    document = society_input(version_id)
    document["navigation"]["nodes"] = [
        {"node_id": key, "subject_id": "walk:" + key, "position_mm": [i * 6000, 0]}
        for i, key in enumerate(("a", "b", "c"))
    ]
    document["navigation"]["edges"] = [
        {
            "edge_id": a + b,
            "from_node_id": a,
            "to_node_id": b,
            "length_mm": 6000,
            "subject_id": "walk:" + a + b,
        }
        for a, b in (("a", "b"), ("b", "c"))
    ]
    document["targets"] = [
        {
            "target_id": f"district:{node}:rest",
            "subject_id": f"district:{node}",
            "node_id": node,
            "affordance": "rest",
            "duration_ticks": 3,
            "origin": "district",
            "object_id": None,
            "version_id": str(version_id),
            "enabled": True,
        }
        for node in ("a", "b", "c")
    ]
    document["navigation"]["destinations"] = [
        {
            "destination_id": t["target_id"],
            **{key: t[key] for key in ("subject_id", "node_id", "affordance", "duration_ticks")},
        }
        for t in document["targets"]
    ]
    return seal(document)


def add_social_marker(document):
    result = edited(document)
    result["targets"].append(
        {
            "target_id": "authored:new-marker:visit",
            "subject_id": "authored:new-marker",
            "node_id": "a",
            "affordance": "visit",
            "duration_ticks": 1,
            "origin": "authored",
            "object_id": "object:new-marker",
            "version_id": document["version_id"],
            "enabled": True,
        }
    )
    result["targets"].sort(key=lambda t: t["target_id"])
    return seal(result)


def recorded_choice(state, document, subject, sequence=1, proposal=None):
    context = decision_context(state, document, subject)
    request = seal_request(
        {
            "profile": REQUEST_PROFILE,
            "request_id": str(uuid.uuid5(uuid.UUID(subject), str(state["tick"]))),
            "subject_id": subject,
            "branch_id": state["branch_id"],
            "base_tick": state["tick"],
            "base_state_sha256": society_state_sha256(state),
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "context": context,
            "context_sha256": society_state_sha256(context),
            "provider_config": {
                "role": "offline-fixture",
                "model_id": "offline-proposal-fixture",
                "manifest_sha256": "a" * 64,
            },
        }
    )
    return receipt_for(
        request,
        sequence,
        {
            "status": "accepted",
            "reason": "validated_known_affordance_choice",
            "proposal": deepcopy(
                proposal or {"kind": "choose_goal", "target_id": "authored:new-marker:visit"}
            ),
            "provider": {"evidence": "offline typed proposal fixture, not a model execution"},
        },
    )
