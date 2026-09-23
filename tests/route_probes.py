"""The authorisation sweep's requests, derived from the one declaration of what each route requires.

``tests/test_api.py`` sweeps every authenticated route three ways: an anonymous caller, a bad
token, and a stranger holding a real session for another workspace, who must never be answered
403 (M10: "404, never 403, so the surface is not an existence oracle"). The requests it sends used
to be a second hand-kept list of the same routes beside
:data:`exulanica.api.permissions.ROUTE_RULES`, and a route missing from that list was noticed only
by a test that needs PostgreSQL.

Here the probed set IS the authenticated part of ROUTE_RULES, so a route is swept the moment it is
declared, and each probe's default request is read from the route's own OpenAPI operation: sent
bare when it takes no body, with an empty JSON object when it takes one. :data:`PROBE_OVERRIDES`
gives a realistic request where the default would stop at validation before the route's own
lookup, because that lookup is where a stranger's answer is decided: without one, "never 403"
would hold for the route by never reaching it. A route taking a body of any other kind has no
default and must have an override, which :func:`derive_probes` says by name.

``tests/test_route_probes.py`` checks, without a database, that every declared authenticated route
is probed and that every override still names one.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any, Final

from exulanica.api.permissions import ROUTE_RULES, Authentication, Public, route_key
from exulanica.api.surface import routing_only_application

__all__ = [
    "ACCOUNT_ROUTES",
    "PROBE_OVERRIDES",
    "PUBLIC_ROUTES",
    "ROUTE_PROBES",
    "authenticated_routes",
    "default_probe",
    "derive_probes",
    "fill",
]

#: Routes that need no credential, by path, with the reason each gives. Derived, not restated.
PUBLIC_ROUTES: Final[dict[str, str]] = {
    path: rule.reason for (_method, path), rule in ROUTE_RULES.items() if isinstance(rule, Public)
}

#: The sign-in surface, which refuses for itself and has its own suite.
ACCOUNT_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    key for key, rule in ROUTE_RULES.items() if isinstance(rule, Authentication)
)

_ZERO_DIGEST: Final = "0" * 64
_REGION_KEY: Final = "aa" * 32
_TRANSFORM: Final = {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0, "scale_milli": 1000}

#: A realistic request for each route whose default would stop at validation, sorted by path and
#: then method. What a route does with a body it accepts belongs to that route's own tests; these
#: bodies only have to get a stranger past validation to the route's own answer.
PROBE_OVERRIDES: Final[dict[str, dict[str, Any]]] = {
    "POST /companion/memory/answers": {
        "json": {
            "question": "when were these taken?",
            "answer_text": "on 2026-02-01",
            "prompt_version": "selection-3",
            "latency_ms": 1,
        }
    },
    "POST /companion/memory/answers/{answer_id}/corrections": {
        "json": {"answer_text": "no, it was 2026-03-04"}
    },
    "POST /companion/memory/escapes": {
        "json": {"escape": "skip", "intent": "confirm_continuity", "turn_id": "turn-1"}
    },
    "GET /environment-resources/{kind}/{resource_id}": {"params": {"operation": "display"}},
    "GET /environment-resources/{kind}/{resource_id}/bytes": {"params": {"operation": "display"}},
    "GET /evidence": {"params": {"uri": "exulanica://blob/x/img#t=0,1"}},
    "POST /identity/confirm": {
        "json": {"occurrence_id": str(uuid.uuid4()), "entity_id": str(uuid.uuid4())}
    },
    "POST /identity/merge": {"json": {"sources": [str(uuid.uuid4())], "target": str(uuid.uuid4())}},
    "POST /identity/name": {"json": {"occurrence_id": str(uuid.uuid4()), "display_name": "X"}},
    "POST /identity/reject": {
        "json": {"occurrence_id": str(uuid.uuid4()), "entity_id": str(uuid.uuid4())}
    },
    "POST /identity/rename": {"json": {"entity_id": str(uuid.uuid4()), "display_name": "X"}},
    "POST /identity/revoke": {"json": {"occurrence_id": str(uuid.uuid4())}},
    "POST /identity/split": {
        "json": {"entity_id": str(uuid.uuid4()), "occurrence_ids": [str(uuid.uuid4())]}
    },
    "POST /identity/subjects/link": {
        "json": {"regions": [{"capture_id": str(uuid.uuid4()), "region_key": _REGION_KEY}]}
    },
    "POST /identity/subjects/unlink": {
        "json": {
            "regions": [{"capture_id": str(uuid.uuid4()), "region_key": _REGION_KEY}],
            "subject_id": str(uuid.uuid4()),
        }
    },
    "POST /identity/undo": {"json": {"event_id": str(uuid.uuid4())}},
    # Multipart, because that is what the route takes, and a part the route refuses on its name,
    # because the sweep asks only who may reach the endpoint. What it does with a photograph is
    # test_intake_upload.py, which has a store and a schema to check against.
    "POST /intake": {"files": {"files": ("probe.txt", b"probe", "text/plain")}},
    "POST /person-regions/{capture_id}/edits": {
        "json": {"edits": [{"region_key": _REGION_KEY, "action": "confirm"}]}
    },
    "POST /person-subjects/{subject_id}/consents": {
        "json": {"consent_scope": "likeness", "decision": "granted"}
    },
    "POST /place-name-rights/{entity_id}/grants": {"json": {"use": "embedding", "notice": "x"}},
    "POST /place-name-rights/{entity_id}/withdrawals": {"json": {"use": "embedding"}},
    "POST /selection": {"json": {"intent": "captures"}},
    "POST /selection/appearance": {"json": {"utterance": "could it be softer in here?"}},
    "POST /selection/ask": {"json": {"question": "where was I?"}},
    "POST /selection/packet": {"json": {"intent": "captures"}},
    "POST /selection/plan": {"json": {"question": "where was I?"}},
    "GET /tiles": {"params": {"city_seed": _ZERO_DIGEST}},
    # Enough of a specification to reach the permission floor, which is all this sweep asks of it.
    # What the route does with a body it accepts is tests/test_world_generation_route.py.
    "POST /world-generation/worlds": {
        "json": {"grammar_id": "city", "grammar_version": 3, "bindings": []}
    },
    "GET /world-read/scenes/{scene_id}/observations/resolve": {
        "params": {"capture_id": str(uuid.uuid4()), "u": "10", "v": "20"}
    },
    "POST /world-write/scenes/{scene_id}/generated": {
        "json": {
            "model": {"provider": "p", "model_id": "m", "model_version": "v"},
            "prompt_sha256": _ZERO_DIGEST,
            "conditioning": [{"role": "world-read-bundle", "sha256": "1" * 64}],
            "container": "sog/1",
            "content_sha256": "2" * 64,
            "byte_size": 1,
            "seam": "where the record stops and the imagining begins",
        }
    },
    "POST /world/interactions/previews": {
        "json": {
            "proposal_id": str(uuid.uuid4()),
            "origin": "settings",
            "origin_reference": "probe-panel",
            "base_policy_version_id": None,
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
            "capability_patch": {"initiative.mode": "minimal"},
            "proposal_input": {"control": "initiative"},
            "explanation": "The user selected less initiative.",
        }
    },
    "POST /world/interactions/previews/{preview_id}/apply": {
        "json": {
            "base_policy_version_id": None,
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
        }
    },
    "POST /world/interactions/rollback": {
        "json": {
            "target_version_id": str(uuid.uuid4()),
            "origin": "settings",
            "base_policy_version_id": str(uuid.uuid4()),
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
        }
    },
    "POST /world/styles/previews": {
        "json": {
            "proposal_id": str(uuid.uuid4()),
            "origin": "user",
            "scope": {"kind": "global"},
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
            "profile": {"profile_id": "origin-landscape", "profile_version": 1},
        }
    },
    "POST /world/styles/previews/{preview_id}/apply": {
        "json": {
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
        }
    },
    "POST /world/styles/rollback": {
        "json": {
            "target_version_id": str(uuid.uuid4()),
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
            "origin": "user",
        }
    },
    "POST /world/versions": {"json": {"title": "probe", "source_snapshot_id": str(uuid.uuid4())}},
    "POST /world/versions/bootstrap": {"json": {"base_topology_digest": _ZERO_DIGEST}},
    "POST /world/versions/{version_id}/objects": {
        "json": {
            "base_state_sha256": _ZERO_DIGEST,
            "object_id": "object:probe",
            "asset_sha256": "1" * 64,
            "region_id": "region-a",
            "transform": _TRANSFORM,
            "origin_role": "fictional",
        }
    },
    "POST /world/versions/{version_id}/objects/undo": {"json": {"base_state_sha256": _ZERO_DIGEST}},
    "POST /world/versions/{version_id}/objects/{object_id}/behaviour": {
        "json": {
            "base_state_sha256": _ZERO_DIGEST,
            "behaviour": {
                "behaviour_key": "motion.bounded-path",
                "behaviour_version": 1,
                "parameters": {
                    "travel_mm": 1000,
                    "period_milliseconds": 4000,
                    "axis": "x",
                    "easing": "smooth",
                },
            },
        }
    },
    "POST /world/versions/{version_id}/objects/{object_id}/move": {
        "json": {"base_state_sha256": _ZERO_DIGEST, "transform": _TRANSFORM}
    },
    "POST /world/versions/{version_id}/objects/{object_id}/remove": {
        "json": {"base_state_sha256": _ZERO_DIGEST}
    },
    "POST /world/versions/{version_id}/society/actions": {
        "json": {
            "idempotency_key": str(uuid.uuid4()),
            "base_tick": 0,
            "base_state_sha256": _ZERO_DIGEST,
            "subject_id": str(uuid.uuid4()),
            "intent": {"kind": "go_to", "target_id": "fixture:target"},
        }
    },
    "PUT /world/versions/{version_id}/society/control": {
        "json": {"base_revision": 0, "mode": "paused", "speed": 1}
    },
    "POST /world/versions/{version_id}/society/control/steps": {
        "json": {"base_revision": 0, "base_tick": 0, "base_state_sha256": _ZERO_DIGEST}
    },
    "POST /world/versions/{version_id}/society/presence": {
        "json": {
            "idempotency_key": str(uuid.uuid4()),
            "presence": "away",
            "base_tick": 0,
            "base_state_sha256": _ZERO_DIGEST,
        }
    },
}


def authenticated_routes() -> list[tuple[str, str]]:
    """Every declared route that needs a credential: neither public nor the sign-in surface."""
    return sorted(
        key for key, rule in ROUTE_RULES.items() if not isinstance(rule, Public | Authentication)
    )


def default_probe(operation: Mapping[str, Any]) -> dict[str, Any] | None:
    """The request a route takes when nothing about it is special, or None when there is none."""
    body = operation.get("requestBody")
    if body is None:
        return {}
    if "application/json" in body.get("content", {}):
        return {"json": {}}
    return None


def derive_probes(
    operations: Mapping[str, Mapping[str, Any]],
    overrides: Mapping[str, dict[str, Any]] = PROBE_OVERRIDES,
) -> dict[tuple[str, str], dict[str, Any]]:
    """One request per authenticated route: its override, else the default its operation implies.

    ``operations`` is the OpenAPI ``paths`` object. A route with neither an override nor a default
    is refused by name rather than probed with a request it would reject for its shape.
    """
    replaced = {route_key(route): probe for route, probe in overrides.items()}
    probes: dict[tuple[str, str], dict[str, Any]] = {}
    for method, path in authenticated_routes():
        if (method, path) in replaced:
            probes[(method, path)] = replaced[(method, path)]
            continue
        probe = default_probe(operations[path][method.lower()])
        if probe is None:
            raise LookupError(
                f"{method} {path} takes a body the sweep has no default for; give it a realistic "
                "request in PROBE_OVERRIDES"
            )
        probes[(method, path)] = probe
    return probes


#: What the sweep sends to every authenticated route, keyed exactly as ROUTE_RULES is.
ROUTE_PROBES: Final[dict[tuple[str, str], dict[str, Any]]] = derive_probes(
    routing_only_application().openapi()["paths"]
)

#: Path parameters that are not identifiers, with the value the sweep sends. Each route checks these
#: against a closed set before anything else, so an identifier there would be refused as malformed
#: and the sweep would be asking the validator about the session rather than the route.
_NON_IDENTIFIER_PARAMETERS: Final[Mapping[str, str]] = {"kind": "source", "subject_kind": "avatar"}
_PLACEHOLDER: Final = re.compile(r"\{([^}]+)\}")


def fill(path: str, known: Mapping[str, object] | None = None) -> str:
    """A concrete URL for a route template: every placeholder replaced, none left literal.

    ``known`` supplies real values, such as ids a fixture created, so a route can be asked about
    something that exists. Any other identifier is a fresh UUID nobody allocated, which answers
    who may reach the route without a matching row in the fixture. A placeholder left in the URL
    would be sent as the literal text and answered by the parameter validator instead.
    """
    known = known or {}

    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in known:
            return str(known[name])
        return _NON_IDENTIFIER_PARAMETERS.get(name) or str(uuid.uuid4())

    return _PLACEHOLDER.sub(value, path)
