"""The authorisation sweep's requests, derived from the one declaration of what each route requires.

``tests/test_api.py`` sweeps every authenticated route three ways: an anonymous caller, a bad
token, and a stranger holding a real session for another workspace, who must never be answered
403 (M10: "404, never 403, so the surface is not an existence oracle"). The requests it sends used
to be a second hand-kept list of the same routes beside
:data:`exulanica.api.permissions.ROUTE_RULES`, and a route missing from that list was noticed only
by a test that needs PostgreSQL.

Here the probed set IS the authenticated part of ROUTE_RULES, so a route is swept the moment it is
declared, and each probe's default request is read from the route's own OpenAPI operation: sent
bare when it takes no body, with an empty JSON object when it takes one, and in the fixture world
when it requires a world, as every override of such a route is too. :data:`PROBE_OVERRIDES`
gives a realistic request where the default would stop at validation before the route's own
lookup, because that lookup is where a stranger's answer is decided: without one, "never 403"
would hold for the route by never reaching it. A route taking a body of any other kind has no
default and must have an override, which :func:`derive_probes` says by name.

``tests/test_route_probes.py`` checks, without a database, that every declared authenticated route
is probed and that every override still names one.

The second half serves ``tests/test_existence_oracle.py``, which asks every route whose path takes
an id whether a stranger can tell another workspace's id from an invented one. It needs a real
object of each kind to ask about: :data:`EXISTENCE_BUILDERS` says how each is made, keyed by the
id's address (the route template up to its placeholder), :data:`BUILDER_OVERRIDES` names a
narrower kind for a route that asks about one, and :data:`EXISTENCE_REQUESTS` gives a request made
from the owner's own objects where a static probe could not show that the owner's id is real.
:data:`CHOSEN_IDS` names the create routes whose body carries an id the caller chooses, which the
same file asks whether naming another workspace's id is answered as a fresh id is.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.api.permissions import ROUTE_RULES, Authentication, Public, Requires, route_key
from exulanica.api.surface import routing_only_application
from exulanica.consent.place_names import load_place_name_uses
from exulanica.models.manifest import load_manifest
from exulanica.world.society_experiments import DEVELOPMENT_SEEDS

import existence_builders as build
from world_support import FIXTURE_WORLD_ID

__all__ = [
    "ACCOUNT_ROUTES",
    "BUILDER_OVERRIDES",
    "CHOSEN_IDS",
    "EXISTENCE_BUILDERS",
    "EXISTENCE_REQUESTS",
    "PROBE_OVERRIDES",
    "PUBLIC_ROUTES",
    "ROUTE_PROBES",
    "Chosen",
    "IdAddress",
    "Owned",
    "Shared",
    "authenticated_routes",
    "default_probe",
    "derive_probes",
    "fill",
    "id_addresses",
    "id_routes",
    "requires_world",
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


def _place_name_notice(role: str) -> str:
    """The words the product states for a place-name use now, which a grant must quote exactly.

    A grant naming any other words is refused before the place is looked up, so a probe sending
    made-up words would never reach the lookup a stranger's answer is decided by.
    """
    uses = load_place_name_uses()
    use = uses.use(role)
    assert use is not None, f"a place's name is not offered to the {role} role"
    return uses.notice(use, uses.handoff(use, load_manifest()))


#: A saved world's cursor as every edit of it names one, pointing at nothing in particular.
_ENTRY_CURSOR: Final = {
    "base_revision": 1,
    "authored_version_id": str(uuid.uuid4()),
    "authored_state_sha256": _ZERO_DIGEST,
    "authored_edit_seq": 0,
    "style_version_id": str(uuid.uuid4()),
}
_PLACEMENT: Final = {
    "subject_id": "object:probe",
    "region_id": "region-a",
    "transform": _TRANSFORM,
    "origin_role": "fictional",
}
#: The world a probe of a route that requires one is sent in. The sweeps' owners hold it, and so
#: does the existence sweep's stranger, so a stranger's request reaches the route's own lookup.
_IN_WORLD: Final = {"params": {"world_id": FIXTURE_WORLD_ID}}
_PHOTO_POINT_MAP: Final = {
    "kind": "photo_point_map",
    "entry_id": str(uuid.uuid4()),
    "attachment_id": str(uuid.uuid4()),
}
_REVIEWED_ASSET: Final = {"kind": "reviewed_asset", "asset_key": "cc0.marker-cube"}

#: A realistic request for each route whose default would stop at validation, sorted by path and
#: then method. What a route does with a body it accepts belongs to that route's own tests; these
#: bodies only have to get a stranger past validation to the route's own answer.
#: An arrangement request the routes accept: the small square, asked for from the region's origin
#: against a base nobody holds, so the route reaches its own lookup of the version.
_ARRANGEMENT: Final = {
    "base_state_sha256": _ZERO_DIGEST,
    "arrangement_key": "small_square",
    "arrangement_version": 1,
    "viewer": {"x_mm": 0, "z_mm": 0, "yaw_microradians": 0},
    "origin_role": "fictional",
}
PROBE_OVERRIDES: Final[dict[str, dict[str, Any]]] = {
    "POST /companion/memory/answers": {
        "json": {
            "question": "when were these taken?",
            "answer_text": "on 2026-02-01",
            "prompt_version": "selection-3",
            "latency_ms": 1,
            "composed": "none",
            "used_fallback": False,
            "unanswered_attempts": 0,
            "unanswered_cost_unknown": False,
        }
    },
    "POST /companion/memory/answers/{answer_id}/corrections": {
        "json": {"answer_text": "no, it was 2026-03-04"}
    },
    "POST /companion/memory/escapes": {
        "json": {"escape": "skip", "intent": "confirm_continuity", "turn_id": "turn-1"}
    },
    "POST /environment-resources/sources/{admission_id}/feature-indexes": {
        "json": {
            "render_asset_id": str(uuid.uuid4()),
            "features": [
                {"provider_feature_id": "feature", "kind": "terrain", "bbox": [0, 0, 10, 10]}
            ],
        }
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
    "POST /place-name-rights/{entity_id}/grants": {
        "json": {"use": "embedding", "notice": _place_name_notice("embedding")}
    },
    "POST /place-name-rights/{entity_id}/withdrawals": {"json": {"use": "embedding"}},
    "POST /selection": {**_IN_WORLD, "json": {"intent": "captures"}},
    "POST /selection/appearance": {
        **_IN_WORLD,
        "json": {"utterance": "could it be softer in here?"},
    },
    "POST /selection/ask": {**_IN_WORLD, "json": {"question": "where was I?"}},
    "POST /selection/packet": {**_IN_WORLD, "json": {"intent": "captures"}},
    "POST /selection/plan": {"json": {"question": "where was I?"}},
    "GET /tiles": {"params": {"city_seed": _ZERO_DIGEST}},
    # Enough of a specification to reach the permission floor, which is all this sweep asks of it.
    # What the route does with a body it accepts is tests/test_world_generation_route.py.
    "PUT /world-entries/{entry_id}": {
        "json": {
            "base_revision": 1,
            "authored_version_id": str(uuid.uuid4()),
            "expected_authored_state_sha256": _ZERO_DIGEST,
            "expected_authored_edit_seq": 0,
            "style_version_id": str(uuid.uuid4()),
        }
    },
    "POST /world-entries/{entry_id}/source-attachments": {
        "json": {
            "operation_id": str(uuid.uuid4()),
            **_ENTRY_CURSOR,
            "sources": [{"capture_id": str(uuid.uuid4()), "evidence_span_id": str(uuid.uuid4())}],
        }
    },
    "POST /world-entries/{entry_id}/source-detachments": {
        "json": {
            "operation_id": str(uuid.uuid4()),
            **_ENTRY_CURSOR,
            "selections": [{"attachment_id": str(uuid.uuid4())}],
        }
    },
    "POST /world-entries/{entry_id}/source-rebinds": {
        "json": {
            "operation_id": str(uuid.uuid4()),
            **_ENTRY_CURSOR,
            "sources": [{"capture_id": str(uuid.uuid4()), "evidence_span_id": str(uuid.uuid4())}],
        }
    },
    "POST /world-generation/worlds": {
        "json": {"grammar_id": "city", "grammar_version": 3, "bindings": []}
    },
    "GET /world-read/scenes/{scene_id}/observations/resolve": {
        "params": {"capture_id": str(uuid.uuid4()), "u": "10", "v": "20"}
    },
    "POST /world-write/scenes/{scene_id}/generated": {
        **_IN_WORLD,
        "json": {
            "model": {"provider": "p", "model_id": "m", "model_version": "v"},
            "prompt_sha256": _ZERO_DIGEST,
            "conditioning": [{"role": "world-read-bundle", "sha256": "1" * 64}],
            "container": "sog/1",
            "content_sha256": "2" * 64,
            "byte_size": 1,
            "seam": "where the record stops and the imagining begins",
        },
    },
    "POST /world/interactions/previews": {
        **_IN_WORLD,
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
        },
    },
    "POST /world/interactions/previews/{preview_id}/apply": {
        **_IN_WORLD,
        "json": {
            "base_policy_version_id": None,
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
        },
    },
    "POST /world/interactions/rollback": {
        **_IN_WORLD,
        "json": {
            "target_version_id": str(uuid.uuid4()),
            "origin": "settings",
            "base_policy_version_id": str(uuid.uuid4()),
            "base_structure_snapshot_id": None,
            "base_topology_sha256": None,
        },
    },
    "POST /world/styles/previews": {
        **_IN_WORLD,
        "json": {
            "proposal_id": str(uuid.uuid4()),
            "origin": "user",
            "scope": {"kind": "global"},
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
            "profile": {"profile_id": "origin-landscape", "profile_version": 1},
        },
    },
    "POST /world/styles/previews/{preview_id}/apply": {
        **_IN_WORLD,
        "json": {
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
        },
    },
    "POST /world/styles/rollback": {
        **_IN_WORLD,
        "json": {
            "target_version_id": str(uuid.uuid4()),
            "base_style_version_id": str(uuid.uuid4()),
            "base_topology_digest": "probe-topology",
            "origin": "user",
        },
    },
    "POST /world/versions": {
        **_IN_WORLD,
        "json": {"title": "probe", "source_snapshot_id": str(uuid.uuid4())},
    },
    "POST /world/versions/bootstrap": {**_IN_WORLD, "json": {"base_topology_digest": _ZERO_DIGEST}},
    "POST /world/versions/{version_id}/arrangements/apply": {**_IN_WORLD, "json": _ARRANGEMENT},
    "POST /world/versions/{version_id}/arrangements/preview": {**_IN_WORLD, "json": _ARRANGEMENT},
    "PUT /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance": {
        **_IN_WORLD,
        "json": {
            "base_revision": 0,
            "recipe": {
                "family_id": "probe-family/v1",
                "family_sha256": _ZERO_DIGEST,
                "parameters": {"height": 175},
                "seed": 0,
            },
        },
    },
    "POST /world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/reset": {
        **_IN_WORLD,
        "json": {"base_revision": 0},
    },
    "POST /world/versions/{version_id}/compositions/apply": {
        **_IN_WORLD,
        "json": {
            "base_state_sha256": _ZERO_DIGEST,
            "source": _REVIEWED_ASSET,
            "placement": _PLACEMENT,
        },
    },
    "POST /world/versions/{version_id}/compositions/photo-point-maps/apply": {
        **_IN_WORLD,
        "json": {
            "base_state_sha256": _ZERO_DIGEST,
            "source": _PHOTO_POINT_MAP,
            "placement": _PLACEMENT,
        },
    },
    "POST /world/versions/{version_id}/compositions/photo-point-maps/preview": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST, "source": _PHOTO_POINT_MAP},
    },
    "POST /world/versions/{version_id}/compositions/preview": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST, "source": _REVIEWED_ASSET},
    },
    "POST /world/versions/{version_id}/environment-instances": {
        **_IN_WORLD,
        "json": {
            "base_state_sha256": _ZERO_DIGEST,
            "instance_id": "environment:probe",
            "admission_id": str(uuid.uuid4()),
            "render_asset_id": str(uuid.uuid4()),
            "selection": {"kind": "whole_asset"},
            "source_anchor": {
                "frame_name": "nyc-grid",
                "coordinate_scale": 1000,
                "coordinates": [10, 20, 0],
            },
            "region_id": "region-a",
            "transform": _TRANSFORM,
            "origin_role": "fictional",
        },
    },
    "POST /world/versions/{version_id}/environment-instances/undo": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST},
    },
    "POST /world/versions/{version_id}/environment-instances/{instance_id}/move": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST, "transform": _TRANSFORM},
    },
    "POST /world/versions/{version_id}/environment-instances/{instance_id}/remove": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST},
    },
    "POST /world/versions/{version_id}/objects": {
        **_IN_WORLD,
        "json": {
            "base_state_sha256": _ZERO_DIGEST,
            "object_id": "object:probe",
            "asset_sha256": "1" * 64,
            "region_id": "region-a",
            "transform": _TRANSFORM,
            "origin_role": "fictional",
        },
    },
    "POST /world/versions/{version_id}/objects/undo": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST},
    },
    "POST /world/versions/{version_id}/objects/{object_id}/behaviour": {
        **_IN_WORLD,
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
        },
    },
    "POST /world/versions/{version_id}/objects/{object_id}/move": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST, "transform": _TRANSFORM},
    },
    "POST /world/versions/{version_id}/objects/{object_id}/remove": {
        **_IN_WORLD,
        "json": {"base_state_sha256": _ZERO_DIGEST},
    },
    "POST /world/versions/{version_id}/society": {
        **_IN_WORLD,
        "json": {"place_id": str(uuid.uuid4()), "region_id": "region-a", "seed": "7a" * 32},
    },
    "POST /world/versions/{version_id}/society/actions": {
        **_IN_WORLD,
        "json": {
            "idempotency_key": str(uuid.uuid4()),
            "base_tick": 0,
            "base_state_sha256": _ZERO_DIGEST,
            "subject_id": str(uuid.uuid4()),
            "intent": {"kind": "go_to", "target_id": "fixture:target"},
        },
    },
    "PUT /world/versions/{version_id}/society/control": {
        **_IN_WORLD,
        "json": {"base_revision": 0, "mode": "paused", "speed": 1},
    },
    "POST /world/versions/{version_id}/society/control/steps": {
        **_IN_WORLD,
        "json": {"base_revision": 0, "base_tick": 0, "base_state_sha256": _ZERO_DIGEST},
    },
    "POST /world/versions/{version_id}/society/decisions": {
        **_IN_WORLD,
        "json": {
            "idempotency_key": str(uuid.uuid4()),
            "subject_id": str(uuid.uuid4()),
            "base_tick": 0,
            "base_state_sha256": _ZERO_DIGEST,
        },
    },
    "POST /world/versions/{version_id}/society/experiments": {
        **_IN_WORLD,
        "json": {
            "experiment_id": str(uuid.uuid4()),
            "baseline_input_seq": 1,
            "treatment_input_seq": 1,
            "intervention": {"kind": "noop"},
            "population": 3,
            "warmup_ticks": 2,
            "followup_ticks": 3,
        },
    },
    "POST /world/versions/{version_id}/society/experiments/{experiment_id}/attempts": {
        **_IN_WORLD,
        "json": {"attempt_id": str(uuid.uuid4()), "seed_sha256": DEVELOPMENT_SEEDS[0]},
    },
    "POST /world/versions/{version_id}/society/models": {
        **_IN_WORLD,
        "json": {
            "idempotency_key": str(uuid.uuid4()),
            "people": [str(uuid.uuid4())],
            "model": None,
        },
    },
    "POST /world/versions/{version_id}/society/presence": {
        **_IN_WORLD,
        "json": {
            "idempotency_key": str(uuid.uuid4()),
            "presence": "away",
            "base_tick": 0,
            "base_state_sha256": _ZERO_DIGEST,
        },
    },
    "POST /world/versions/{version_id}/society/steps": {
        **_IN_WORLD,
        "json": {"base_tick": 0, "base_state_sha256": _ZERO_DIGEST},
    },
    "POST /worlds/personal-source": {"json": {"topology_digest": _ZERO_DIGEST}},
}


def authenticated_routes() -> list[tuple[str, str]]:
    """Every declared route that needs a credential: neither public nor the sign-in surface."""
    return sorted(
        key for key, rule in ROUTE_RULES.items() if not isinstance(rule, Public | Authentication)
    )


def requires_world(operation: Mapping[str, Any]) -> bool:
    """Whether a route's OpenAPI operation requires the ``world_id`` query parameter."""
    return any(
        parameter.get("in") == "query"
        and parameter.get("name") == "world_id"
        and parameter.get("required", False)
        for parameter in operation.get("parameters", ())
    )


def default_probe(operation: Mapping[str, Any]) -> dict[str, Any] | None:
    """The request a route takes when nothing about it is special, or None when there is none.

    A route that requires a world is asked in the fixture world, so its probe is answered by the
    route rather than by the validator refusing a request that names no world.
    """
    body = operation.get("requestBody")
    if body is None:
        probe: dict[str, Any] = {}
    elif "application/json" in body.get("content", {}):
        probe = {"json": {}}
    else:
        return None
    return {**probe, **_IN_WORLD} if requires_world(operation) else probe


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


# -- The existence sweep's objects --------------------------------------------------------------
#
# tests/test_existence_oracle.py asks every route whose path takes an id whether a stranger can
# tell somebody else's id from an invented one. It needs a real object of each kind in the owner's
# workspace to ask about, and EXISTENCE_BUILDERS says how each is made. A kind is named by its
# ADDRESS, the route template up to and including its placeholder, because a placeholder's name
# alone does not name a kind: {artifact_id} is a point map under /geometry and a trained scene
# under /scene-geometry, and six more names are shared across kinds the same way.


@dataclass(frozen=True)
class IdAddress:
    """One identifier in a route template: its placeholder, and the address that names its kind."""

    placeholder: str
    address: str


def id_addresses(path: str) -> tuple[IdAddress, ...]:
    """Every identifier a route template takes, outermost first, each with its address."""
    return tuple(
        IdAddress(match.group(1), path[: match.end()])
        for match in _PLACEHOLDER.finditer(path)
        if match.group(1) not in _NON_IDENTIFIER_PARAMETERS
    )


def id_routes(
    rules: Mapping[tuple[str, str], Public | Authentication | Requires] = ROUTE_RULES,
) -> list[tuple[str, str]]:
    """Every declared route that needs a credential and takes an identifier in its path."""
    return sorted(
        key for key, rule in rules.items() if isinstance(rule, Requires) and id_addresses(key[1])
    )


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class Owned:
    """A kind a workspace owns: how to make one in the owner's workspace, and how to invent one.

    ``build`` takes the sweep's owner context and returns the id. ``invent`` returns an id of the
    same shape that nobody allocated, so a route cannot tell the two apart by their form and
    answer the invented one from its validator.
    """

    build: Callable[[Any], object]
    invent: Callable[[], str] = _uuid


@dataclass(frozen=True)
class Shared:
    """A kind every workspace reads alike, so no workspace's id of it is foreign to another's.

    ``build`` makes or names one. The sweep holds the declaration to its word: a stranger must get
    exactly the owner's answer for it. A kind that became workspace-owned would fail there, and
    would need to become :class:`Owned`.
    """

    build: Callable[[Any], object]
    reason: str
    invent: Callable[[], str] = _uuid


#: How each id kind is made, keyed by its address. A route whose path takes an id with no entry
#: here fails the sweep by name. Sorted by address.
EXISTENCE_BUILDERS: Final[Mapping[str, Owned | Shared]] = {
    "/companion/memory/answers/{answer_id}": Owned(build.companion_answer),
    "/environment-resources/places/{place_id}": Owned(build.declared_place),
    "/environment-resources/sources/{admission_id}": Owned(build.environment_source),
    # The sweep fills {kind} with "source", so the resource is an admitted source.
    "/environment-resources/{kind}/{resource_id}": Owned(build.environment_source),
    "/evidence/{span_id}": Owned(build.evidence_span),
    "/formation/{batch_id}": Owned(build.intake_batch),
    "/geometry/{artifact_id}": Owned(build.point_map),
    "/materials/recipes/{recipe_id}": Owned(build.material_recipe),
    "/operations/derivative-jobs/{job_id}": Owned(build.derivative_job),
    "/operations/reconstruction-scenes/{job_id}": Owned(build.reconstruction_job),
    "/person-regions/{capture_id}": Owned(build.capture),
    "/person-subjects/{subject_id}": Owned(build.person_subject),
    "/personal-admission/model-rights/{right_id}": Owned(build.model_right),
    "/place-name-rights/{entity_id}": Owned(build.named_place),
    "/scene-geometry/{artifact_id}": Owned(build.trained_scene),
    "/scene-segments/{scene_id}": Owned(build.reconstruction_scene),
    "/selection/place-bridges/{decision_id}": Owned(build.place_bridge),
    "/tiles/{baked_tile_id}": Shared(
        build.baked_tile,
        "migration 0072 keeps baked tiles outside every workspace: an offline bake of a city seed "
        "is the same bytes for everyone, and what a workspace spends is its own delivery ledger",
    ),
    "/world-entries/{entry_id}": Owned(build.world_entry),
    "/world-read/places/{place_id}": Owned(build.world_read_place),
    "/world-read/scenes/{scene_id}": Owned(build.reconstruction_scene),
    "/world-write/scenes/{scene_id}": Owned(build.reconstruction_scene),
    "/world/assets/{asset_key}": Shared(
        build.reviewed_asset,
        "migration 0042 registers the reviewed assets once for every workspace, with no "
        "workspace column, and the application seeds their bytes at startup",
    ),
    "/world/interactions/previews/{preview_id}": Owned(build.interaction_preview),
    "/world/interactions/proposals/{proposal_id}": Owned(build.interaction_proposal),
    "/world/source-media/{source_id}": Owned(build.source_media),
    "/world/styles/previews/{preview_id}": Owned(build.style_preview),
    "/world/styles/proposals/{proposal_id}": Owned(build.style_proposal),
    "/world/versions/{version_id}": Owned(build.world_version),
    # The sweep fills {subject_kind} with "avatar", whose subject is the actor it belongs to.
    "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}": Owned(build.avatar),
    "/world/versions/{version_id}/environment-instances/{instance_id}": Owned(
        build.environment_instance, build.invented_environment_instance
    ),
    "/world/versions/{version_id}/objects/{object_id}": Owned(
        build.world_object, build.invented_object
    ),
    "/world/versions/{version_id}/society/actions/{request_id}": Owned(build.action_request),
    "/world/versions/{version_id}/society/decisions/{request_id}": Owned(build.decision_request),
    "/world/versions/{version_id}/society/experiments/{experiment_id}": Owned(build.experiment),
    "/world/versions/{version_id}/society/experiments/{experiment_id}/attempts/{attempt_id}": (
        Owned(build.experiment_attempt)
    ),
}

#: Routes that ask about a narrower kind than their address names, each with the builder that makes
#: it, sorted by path and then method. The district read asks about a version, and only a version
#: whose district the host registered can be answered for its owner.
BUILDER_OVERRIDES: Final[Mapping[str, Mapping[str, Owned | Shared]]] = {
    "GET /world/versions/{version_id}/society/district": {
        "/world/versions/{version_id}": Owned(build.district_version)
    },
}

#: Requests made from the owner's own objects, for routes whose static probe names objects in its
#: body that only the owner's own could stand for: sent that way, the owner's answer turns on the
#: id in the path, which is what shows that the route looked it up. Sorted by path, then method.
EXISTENCE_REQUESTS: Final[Mapping[str, Callable[[Any], dict[str, Any]]]] = {
    "POST /environment-resources/sources/{admission_id}/feature-indexes": (
        build.feature_index_request
    ),
    "PUT /world-entries/{entry_id}": build.entry_update_request,
    "POST /world/styles/previews/{preview_id}/apply": build.style_apply_request,
}


@dataclass(frozen=True)
class Chosen:
    """A create route whose body names an id the caller chooses, and how to ask it about one.

    ``owned`` makes the owner's own object of the kind and returns the id the owner chose for it.
    ``request`` makes a request naming a given id, for a given caller, from that caller's own
    state, so each caller's request is one its route accepts whoever sends it.
    """

    field: str
    owned: Callable[[Any], object]
    request: Callable[[Any, str], dict[str, Any]]


#: Create routes whose body carries an id the caller chooses rather than the server, sorted by path
#: and then method. Each id's table keys it by workspace (migration 0102 for these three), so an id
#: another workspace chose names a new object of the caller's own and must be answered as a fresh
#: id is. The other ids a caller chooses, such as experiment, attempt, operation and idempotency
#: ids, were keyed by workspace from their first migration and are not asked about here.
CHOSEN_IDS: Final[Mapping[str, Chosen]] = {
    "POST /environment-resources/places": Chosen(
        "place_id", build.declared_place, build.place_declaration
    ),
    "POST /world/interactions/previews": Chosen(
        "proposal_id", build.interaction_proposal, build.interaction_preview_request
    ),
    "POST /world/styles/previews": Chosen(
        "proposal_id", build.style_proposal, build.style_preview_request
    ),
}
