# World API

Connect tools to personal world state through authenticated read and write interfaces.

The platform design allows creation tools to read a named world version and submit supported
changes. Edits carry their source version and pass the same permission and acceptance rules as
changes from the interface.

## Current routes

| Method and path | Current responsibility |
| --- | --- |
| `GET /world-read/scenes/{scene_id}` | Read an authorized scene bundle |
| `GET /world-read/places/{place_id}` | Read a place, optionally resolved at a requested time |
| `POST /world-write/scenes/{scene_id}/generated` | Record a generated-scene receipt tied to its conditioning sources |

These are current backend routes, not a general object-editing API. World Write records provenance;
it does not deliver generated assets or execute behavior. Editable objects, alternate-world reads,
and supported runtime changes require the [roadmap extensions](../product-direction.md).

Definitions: [World Read](../../exulanica/api/routes/world_read.py) and
[World Write](../../exulanica/api/routes/world_write.py).
See [development setup](../development-setup.md) for authentication and server configuration.
