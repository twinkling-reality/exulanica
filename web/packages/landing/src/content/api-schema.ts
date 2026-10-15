// Generated from tests/snapshots/api-openapi.json. Run scripts/sync-api-reference.mjs.
import type { ApiSpec } from "./api-types.js";
export const API_SCHEMA: ApiSpec = {
  "paths": {
    "/worlds": {
      "get": {
        "tags": [
          "world"
        ],
        "summary": "Every world this workspace holds, with its kind, and how many of each it may hold.",
        "operationId": "worlds_worlds_get",
        "parameters": [
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorldsView"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/worlds/recipes": {
      "get": {
        "tags": [
          "world"
        ],
        "summary": "The recipes a world can be generated from.",
        "description": "Every recipe this server generates worlds from, in catalog order.",
        "operationId": "recipes_worlds_recipes_get",
        "parameters": [
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "$ref": "#/components/schemas/WorldRecipeView"
                  },
                  "title": "Response Recipes Worlds Recipes Get"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/worlds/generated": {
      "post": {
        "tags": [
          "world"
        ],
        "summary": "Generate a world from a recipe and save it as yours.",
        "description": "Generate the preset's world with the values asked for, for a new identity, save it and its\nentry, and queue its bakes.\n\nAn unknown preset, a value its schema does not offer (422, naming the key, the value and the\nrange), a title that is empty once trimmed (422), a preset its composer does not generate, a\nspecification that generates no world from any of its seed candidates, a style pack that is\nnot a pack of the host's library at exactly that version and manifest digest (422\n`invalid_style_data`), and a workspace that already holds as many generated worlds as the\ncount policy allows are each refused by name, and nothing is written. A deployment whose\ndatabase role cannot register a world is refused 403 `worlds_read_only` before anything is\ngenerated.\n\nThe world is made, then its look named in its appearance's next version, the entry's resume\npointer moved with it. When that write is refused as busy, the world stays as made, naming no\npack, which a page draws in the default look.",
        "operationId": "create_generated_world_worlds_generated_post",
        "parameters": [
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/CreateGeneratedWorldBody"
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/SavedWorldEntryView"
                }
              }
            }
          },
          "409": {
            "description": "Refused by name; nothing was written."
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/world/versions/{version_id}/models": {
      "get": {
        "tags": [
          "world"
        ],
        "summary": "World Models",
        "operationId": "world_models_world_versions__version_id__models_get",
        "parameters": [
          {
            "name": "version_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Version Id"
            }
          },
          {
            "name": "world_id",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "minLength": 1,
              "maxLength": 200,
              "title": "World Id"
            }
          },
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "title": "Response World Models World Versions  Version Id  Models Get"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/world/versions/{version_id}/society": {
      "get": {
        "tags": [
          "society"
        ],
        "summary": "Society",
        "description": "The current state. ``places`` adds where inhabitants can go, as its consumed input says.",
        "operationId": "society_world_versions__version_id__society_get",
        "parameters": [
          {
            "name": "version_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Version Id"
            }
          },
          {
            "name": "world_id",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "minLength": 1,
              "maxLength": 200,
              "title": "World Id"
            }
          },
          {
            "name": "places",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false,
              "title": "Places"
            }
          },
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "title": "Response Society World Versions  Version Id  Society Get"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/world/versions/{version_id}/society/replay": {
      "get": {
        "tags": [
          "society"
        ],
        "summary": "Replay Society",
        "operationId": "replay_society_world_versions__version_id__society_replay_get",
        "parameters": [
          {
            "name": "version_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Version Id"
            }
          },
          {
            "name": "world_id",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "minLength": 1,
              "maxLength": 200,
              "title": "World Id"
            }
          },
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "title": "Response Replay Society World Versions  Version Id  Society Replay Get"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/world-entries": {
      "get": {
        "tags": [
          "world-entries"
        ],
        "summary": "Entries",
        "operationId": "entries_world_entries_get",
        "parameters": [
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "$ref": "#/components/schemas/SavedWorldEntryView"
                  },
                  "title": "Response Entries World Entries Get"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/world/versions/{version_id}": {
      "get": {
        "tags": [
          "world"
        ],
        "summary": "One alternate version with its objects, overrides and edit history.",
        "operationId": "alternate_version_world_versions__version_id__get",
        "parameters": [
          {
            "name": "version_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Version Id"
            }
          },
          {
            "name": "world_id",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "minLength": 1,
              "maxLength": 200,
              "title": "World Id"
            }
          },
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/AlternateVersionView"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/world/versions/{version_id}/capabilities": {
      "get": {
        "tags": [
          "world"
        ],
        "summary": "What can be done with this version of the world now: its regions, its society and each supported operation with its state.",
        "operationId": "version_capabilities_world_versions__version_id__capabilities_get",
        "parameters": [
          {
            "name": "version_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Version Id"
            }
          },
          {
            "name": "world_id",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "minLength": 1,
              "maxLength": 200,
              "title": "World Id"
            }
          },
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "additionalProperties": true,
                  "title": "Response Version Capabilities World Versions  Version Id  Capabilities Get"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/world/versions/{version_id}/objects": {
      "post": {
        "tags": [
          "world"
        ],
        "summary": "Add one authored object against an explicit base version state.",
        "operationId": "add_authored_object_world_versions__version_id__objects_post",
        "parameters": [
          {
            "name": "version_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Version Id"
            }
          },
          {
            "name": "world_id",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "minLength": 1,
              "maxLength": 200,
              "title": "World Id"
            }
          },
          {
            "name": "authorization",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Authorization"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/AddObjectBody"
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/AlternateVersionView"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    }
  },
  "schemas": {
    "WorldsView": {
      "properties": {
        "policy": {
          "$ref": "#/components/schemas/WorldCountPolicyView"
        },
        "worlds": {
          "items": {
            "$ref": "#/components/schemas/WorldView"
          },
          "type": "array",
          "title": "Worlds"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "policy",
        "worlds"
      ],
      "title": "WorldsView"
    },
    "WorldCountPolicyView": {
      "properties": {
        "policy_id": {
          "type": "string",
          "title": "Policy Id"
        },
        "version": {
          "type": "integer",
          "title": "Version"
        },
        "sha256": {
          "type": "string",
          "title": "Sha256"
        },
        "limits": {
          "additionalProperties": {
            "anyOf": [
              {
                "type": "integer"
              },
              {
                "type": "null"
              }
            ]
          },
          "type": "object",
          "title": "Limits"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "policy_id",
        "version",
        "sha256",
        "limits"
      ],
      "title": "WorldCountPolicyView"
    },
    "WorldView": {
      "properties": {
        "world_id": {
          "type": "string",
          "title": "World Id"
        },
        "kind": {
          "type": "string",
          "title": "Kind"
        },
        "created_at": {
          "type": "string",
          "format": "date-time",
          "title": "Created At"
        },
        "created_by": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Created By"
        },
        "provenance": {
          "additionalProperties": {
            "$ref": "#/components/schemas/JsonValue"
          },
          "type": "object",
          "title": "Provenance"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "world_id",
        "kind",
        "created_at",
        "created_by",
        "provenance"
      ],
      "title": "WorldView"
    },
    "JsonValue": {},
    "HTTPValidationError": {
      "properties": {
        "detail": {
          "items": {
            "$ref": "#/components/schemas/ValidationError"
          },
          "type": "array",
          "title": "Detail"
        }
      },
      "type": "object",
      "title": "HTTPValidationError"
    },
    "ValidationError": {
      "properties": {
        "loc": {
          "items": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "integer"
              }
            ]
          },
          "type": "array",
          "title": "Location"
        },
        "msg": {
          "type": "string",
          "title": "Message"
        },
        "type": {
          "type": "string",
          "title": "Error Type"
        },
        "input": {
          "title": "Input"
        },
        "ctx": {
          "type": "object",
          "title": "Context"
        }
      },
      "type": "object",
      "required": [
        "loc",
        "msg",
        "type"
      ],
      "title": "ValidationError"
    },
    "WorldRecipeView": {
      "properties": {
        "key": {
          "type": "string",
          "title": "Key"
        },
        "label": {
          "type": "string",
          "title": "Label"
        },
        "tiles": {
          "type": "integer",
          "title": "Tiles"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "key",
        "label",
        "tiles"
      ],
      "title": "WorldRecipeView"
    },
    "CreateGeneratedWorldBody": {
      "properties": {
        "recipe": {
          "type": "string",
          "maxLength": 100,
          "minLength": 1,
          "title": "Recipe"
        },
        "title": {
          "type": "string",
          "maxLength": 200,
          "minLength": 1,
          "title": "Title"
        },
        "values": {
          "anyOf": [
            {
              "additionalProperties": true,
              "type": "object",
              "maxProperties": 64
            },
            {
              "type": "null"
            }
          ],
          "title": "Values"
        },
        "style_pack": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/StylePackBody"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "recipe",
        "title"
      ],
      "title": "CreateGeneratedWorldBody"
    },
    "StylePackBody": {
      "properties": {
        "pack_id": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9-]{0,31}(\\.[a-z][a-z0-9-]{0,31}){1,3}$",
          "title": "Pack Id"
        },
        "version": {
          "type": "integer",
          "maximum": 1000000,
          "minimum": 1,
          "title": "Version"
        },
        "manifest_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Manifest Sha256"
        },
        "setting": {
          "anyOf": [
            {
              "additionalProperties": {
                "$ref": "#/components/schemas/JsonValue"
              },
              "type": "object"
            },
            {
              "type": "null"
            }
          ],
          "title": "Setting"
        },
        "setting_parts": {
          "anyOf": [
            {
              "additionalProperties": {
                "type": "string"
              },
              "type": "object",
              "maxProperties": 8
            },
            {
              "type": "null"
            }
          ],
          "title": "Setting Parts"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "pack_id",
        "version",
        "manifest_sha256"
      ],
      "title": "StylePackBody",
      "description": "A style pack named exactly: id, version and manifest digest.\n\nAppearance previews resolve the library and current workspace; world creation uses the library."
    },
    "SavedWorldEntryView": {
      "properties": {
        "entry_id": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
        },
        "world_id": {
          "type": "string",
          "title": "World Id"
        },
        "title": {
          "type": "string",
          "title": "Title"
        },
        "source_kind": {
          "type": "string",
          "enum": [
            "personal",
            "authored",
            "generated"
          ],
          "title": "Source Kind"
        },
        "source_snapshot_id": {
          "type": "string",
          "format": "uuid",
          "title": "Source Snapshot Id"
        },
        "source_snapshot_sha256": {
          "type": "string",
          "title": "Source Snapshot Sha256"
        },
        "authored_scene": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/AuthoredStarterSceneView"
            },
            {
              "type": "null"
            }
          ]
        },
        "declared_floor": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/DeclaredFloorView"
            },
            {
              "type": "null"
            }
          ]
        },
        "generated_ground": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/GeneratedGroundView"
            },
            {
              "type": "null"
            }
          ]
        },
        "generated_site": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/GeneratedSiteView"
            },
            {
              "type": "null"
            }
          ]
        },
        "generated_terrain": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/GeneratedTerrainView"
            },
            {
              "type": "null"
            }
          ]
        },
        "society_engine": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Engine"
        },
        "authored_version_id": {
          "type": "string",
          "format": "uuid",
          "title": "Authored Version Id"
        },
        "authored_state_sha256": {
          "type": "string",
          "title": "Authored State Sha256"
        },
        "authored_edit_seq": {
          "type": "integer",
          "title": "Authored Edit Seq"
        },
        "current_authored_state_sha256": {
          "type": "string",
          "title": "Current Authored State Sha256"
        },
        "current_authored_edit_seq": {
          "type": "integer",
          "title": "Current Authored Edit Seq"
        },
        "style_version_id": {
          "type": "string",
          "format": "uuid",
          "title": "Style Version Id"
        },
        "revision": {
          "type": "integer",
          "title": "Revision"
        },
        "availability": {
          "type": "string",
          "enum": [
            "available",
            "unavailable"
          ],
          "title": "Availability"
        },
        "unavailable_reason": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Unavailable Reason"
        },
        "source_attachments": {
          "items": {
            "$ref": "#/components/schemas/SavedWorldSourceAttachmentView"
          },
          "type": "array",
          "title": "Source Attachments"
        },
        "previous_source_attachments": {
          "items": {
            "$ref": "#/components/schemas/SavedWorldPreviousSourceAttachmentView"
          },
          "type": "array",
          "title": "Previous Source Attachments"
        },
        "created_by": {
          "type": "string",
          "format": "uuid",
          "title": "Created By"
        },
        "created_at": {
          "type": "string",
          "format": "date-time",
          "title": "Created At"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time",
          "title": "Updated At"
        },
        "takes_photographs": {
          "type": "boolean",
          "title": "Takes Photographs"
        },
        "arrival": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/ArrivalDescriptor"
            },
            {
              "type": "null"
            }
          ]
        },
        "arrival_unavailable_reason": {
          "anyOf": [
            {
              "type": "string",
              "const": "arrival_source_unavailable"
            },
            {
              "type": "null"
            }
          ],
          "title": "Arrival Unavailable Reason"
        },
        "arrival_scene": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/ReconstructionSceneRow"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "entry_id",
        "world_id",
        "title",
        "source_kind",
        "source_snapshot_id",
        "source_snapshot_sha256",
        "authored_scene",
        "declared_floor",
        "authored_version_id",
        "authored_state_sha256",
        "authored_edit_seq",
        "current_authored_state_sha256",
        "current_authored_edit_seq",
        "style_version_id",
        "revision",
        "availability",
        "unavailable_reason",
        "source_attachments",
        "previous_source_attachments",
        "created_by",
        "created_at",
        "updated_at",
        "takes_photographs"
      ],
      "title": "SavedWorldEntryView"
    },
    "AuthoredStarterSceneView": {
      "properties": {
        "schema_version": {
          "type": "integer",
          "const": 1,
          "title": "Schema Version"
        },
        "kind": {
          "type": "string",
          "const": "authored-starter",
          "title": "Kind"
        },
        "region": {
          "$ref": "#/components/schemas/AuthoredRegionView"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "schema_version",
        "kind",
        "region"
      ],
      "title": "AuthoredStarterSceneView"
    },
    "AuthoredRegionView": {
      "properties": {
        "region_id": {
          "type": "string",
          "title": "Region Id"
        },
        "origin": {
          "type": "string",
          "const": "authored",
          "title": "Origin"
        },
        "module": {
          "$ref": "#/components/schemas/AuthoredModuleView"
        },
        "ground": {
          "oneOf": [
            {
              "$ref": "#/components/schemas/BoundedAuthoredGroundView"
            },
            {
              "$ref": "#/components/schemas/EndlessAuthoredGroundView"
            }
          ],
          "title": "Ground",
          "discriminator": {
            "propertyName": "kind",
            "mapping": {
              "endless": "#/components/schemas/EndlessAuthoredGroundView",
              "flat": "#/components/schemas/BoundedAuthoredGroundView"
            }
          }
        },
        "spawn": {
          "$ref": "#/components/schemas/AuthoredSpawnView"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "region_id",
        "origin",
        "module",
        "ground",
        "spawn"
      ],
      "title": "AuthoredRegionView"
    },
    "AuthoredModuleView": {
      "properties": {
        "key": {
          "type": "string",
          "title": "Key"
        },
        "version": {
          "type": "integer",
          "title": "Version"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "key",
        "version"
      ],
      "title": "AuthoredModuleView"
    },
    "BoundedAuthoredGroundView": {
      "properties": {
        "kind": {
          "type": "string",
          "const": "flat",
          "title": "Kind"
        },
        "half_width_mm": {
          "type": "integer",
          "title": "Half Width Mm"
        },
        "half_depth_mm": {
          "type": "integer",
          "title": "Half Depth Mm"
        },
        "elevation_mm": {
          "type": "integer",
          "title": "Elevation Mm"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "kind",
        "half_width_mm",
        "half_depth_mm",
        "elevation_mm"
      ],
      "title": "BoundedAuthoredGroundView"
    },
    "EndlessAuthoredGroundView": {
      "properties": {
        "kind": {
          "type": "string",
          "const": "endless",
          "title": "Kind"
        },
        "elevation_mm": {
          "type": "integer",
          "title": "Elevation Mm"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "kind",
        "elevation_mm"
      ],
      "title": "EndlessAuthoredGroundView"
    },
    "AuthoredSpawnView": {
      "properties": {
        "x_mm": {
          "type": "integer",
          "title": "X Mm"
        },
        "y_mm": {
          "type": "integer",
          "title": "Y Mm"
        },
        "z_mm": {
          "type": "integer",
          "title": "Z Mm"
        },
        "yaw_microradians": {
          "type": "integer",
          "title": "Yaw Microradians"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "x_mm",
        "y_mm",
        "z_mm",
        "yaw_microradians"
      ],
      "title": "AuthoredSpawnView"
    },
    "DeclaredFloorView": {
      "properties": {
        "half_extent_mm": {
          "type": "integer",
          "title": "Half Extent Mm"
        },
        "elevation_mm": {
          "type": "integer",
          "title": "Elevation Mm"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "half_extent_mm",
        "elevation_mm"
      ],
      "title": "DeclaredFloorView",
      "description": "The floor every region of a world that states no ground has: a square of this half extent\nabout the region origin, at this height in the region's frame, in millimetres."
    },
    "GeneratedGroundView": {
      "properties": {
        "recipe_key": {
          "type": "string",
          "title": "Recipe Key"
        },
        "recipe_label": {
          "type": "string",
          "title": "Recipe Label"
        },
        "region_id": {
          "type": "string",
          "title": "Region Id"
        },
        "arrival_mm": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 3,
          "minItems": 3,
          "title": "Arrival Mm"
        },
        "arrival_facing_mm": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 2,
          "minItems": 2,
          "title": "Arrival Facing Mm"
        },
        "tiles": {
          "items": {
            "$ref": "#/components/schemas/GeneratedTileView"
          },
          "type": "array",
          "title": "Tiles"
        },
        "specification": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Specification"
        },
        "values": {
          "anyOf": [
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "type": "integer"
                  },
                  {
                    "type": "string"
                  }
                ]
              },
              "type": "object"
            },
            {
              "type": "null"
            }
          ],
          "title": "Values"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "recipe_key",
        "recipe_label",
        "region_id",
        "arrival_mm",
        "arrival_facing_mm",
        "tiles"
      ],
      "title": "GeneratedGroundView",
      "description": "What the page draws of a world generated from a recipe: its tiles, the one region its\npeople live in and where a person arrives, in that region's frame (east, height, south); and\nwhat the world was made with, read-only. Nothing changes an existing world's values: a new\nworld made from them is ``POST /worlds/generated`` with ``recipe_key`` as its ``recipe`` and\nthese ``values``, and this world keeps its own receipt."
    },
    "GeneratedTileView": {
      "properties": {
        "tile_x": {
          "type": "integer",
          "title": "Tile X"
        },
        "tile_y": {
          "type": "integer",
          "title": "Tile Y"
        },
        "tile_inputs_digest": {
          "type": "string",
          "title": "Tile Inputs Digest"
        },
        "baked_tile_id": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Baked Tile Id"
        },
        "state": {
          "type": "string",
          "enum": [
            "baked",
            "baking",
            "failed"
          ],
          "title": "State"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "tile_x",
        "tile_y",
        "tile_inputs_digest",
        "baked_tile_id",
        "state"
      ],
      "title": "GeneratedTileView"
    },
    "GeneratedSiteView": {
      "properties": {
        "kind": {
          "type": "string",
          "title": "Kind"
        },
        "kind_version": {
          "type": "integer",
          "title": "Kind Version"
        },
        "kind_label": {
          "type": "string",
          "title": "Kind Label"
        },
        "region_id": {
          "type": "string",
          "title": "Region Id"
        },
        "arrival_mm": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 3,
          "minItems": 3,
          "title": "Arrival Mm"
        },
        "arrival_facing_mm": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 2,
          "minItems": 2,
          "title": "Arrival Facing Mm"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "kind",
        "kind_version",
        "kind_label",
        "region_id",
        "arrival_mm",
        "arrival_facing_mm"
      ],
      "title": "GeneratedSiteView",
      "description": "What the page draws of a world made from a world kind: its kind, the one region its people\nlive in and where a person arrives, in that region's frame (east, height, south). The drawing\nitself is read through the world's version (``GET /world/versions/{version_id}/site``)."
    },
    "GeneratedTerrainView": {
      "properties": {
        "region_id": {
          "type": "string",
          "title": "Region Id"
        },
        "arrival_mm": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 3,
          "minItems": 3,
          "title": "Arrival Mm"
        },
        "arrival_facing_mm": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 2,
          "minItems": 2,
          "title": "Arrival Facing Mm"
        },
        "geometry_sha256": {
          "type": "string",
          "title": "Geometry Sha256"
        },
        "contact_sha256": {
          "type": "string",
          "title": "Contact Sha256"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "region_id",
        "arrival_mm",
        "arrival_facing_mm",
        "geometry_sha256",
        "contact_sha256"
      ],
      "title": "GeneratedTerrainView",
      "description": "An exact terrain source and arrival, without a world-kind or society projection."
    },
    "SavedWorldSourceAttachmentView": {
      "properties": {
        "attachment_id": {
          "type": "string",
          "format": "uuid",
          "title": "Attachment Id"
        },
        "operation_id": {
          "type": "string",
          "format": "uuid",
          "title": "Operation Id"
        },
        "capture_id": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
        },
        "evidence_span_id": {
          "type": "string",
          "format": "uuid",
          "title": "Evidence Span Id"
        },
        "source_sha256": {
          "type": "string",
          "title": "Source Sha256"
        },
        "authorization_id": {
          "type": "string",
          "format": "uuid",
          "title": "Authorization Id"
        },
        "screening_id": {
          "type": "string",
          "format": "uuid",
          "title": "Screening Id"
        },
        "role": {
          "type": "string",
          "const": "reference",
          "title": "Role"
        },
        "attached_entry_revision": {
          "type": "integer",
          "title": "Attached Entry Revision"
        },
        "attached_by": {
          "type": "string",
          "format": "uuid",
          "title": "Attached By"
        },
        "attached_at": {
          "type": "string",
          "format": "date-time",
          "title": "Attached At"
        },
        "availability": {
          "type": "string",
          "enum": [
            "available",
            "unavailable"
          ],
          "title": "Availability"
        },
        "unavailable_reason": {
          "anyOf": [
            {
              "type": "string",
              "enum": [
                "source_unavailable",
                "authorization_expired",
                "screening_expired",
                "viewer_unavailable"
              ]
            },
            {
              "type": "null"
            }
          ],
          "title": "Unavailable Reason"
        },
        "viewer_sha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Viewer Sha256"
        },
        "evidence_path": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Evidence Path"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "attachment_id",
        "operation_id",
        "capture_id",
        "evidence_span_id",
        "source_sha256",
        "authorization_id",
        "screening_id",
        "role",
        "attached_entry_revision",
        "attached_by",
        "attached_at",
        "availability",
        "unavailable_reason",
        "viewer_sha256",
        "evidence_path"
      ],
      "title": "SavedWorldSourceAttachmentView"
    },
    "SavedWorldPreviousSourceAttachmentView": {
      "properties": {
        "attachment_id": {
          "type": "string",
          "format": "uuid",
          "title": "Attachment Id"
        },
        "operation_id": {
          "type": "string",
          "format": "uuid",
          "title": "Operation Id"
        },
        "capture_id": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
        },
        "evidence_span_id": {
          "type": "string",
          "format": "uuid",
          "title": "Evidence Span Id"
        },
        "source_sha256": {
          "type": "string",
          "title": "Source Sha256"
        },
        "authorization_id": {
          "type": "string",
          "format": "uuid",
          "title": "Authorization Id"
        },
        "screening_id": {
          "type": "string",
          "format": "uuid",
          "title": "Screening Id"
        },
        "attached_entry_revision": {
          "type": "integer",
          "title": "Attached Entry Revision"
        },
        "attached_at": {
          "type": "string",
          "format": "date-time",
          "title": "Attached At"
        },
        "detach_operation_id": {
          "type": "string",
          "format": "uuid",
          "title": "Detach Operation Id"
        },
        "detached_entry_revision": {
          "type": "integer",
          "title": "Detached Entry Revision"
        },
        "detached_by": {
          "type": "string",
          "format": "uuid",
          "title": "Detached By"
        },
        "detached_at": {
          "type": "string",
          "format": "date-time",
          "title": "Detached At"
        },
        "availability": {
          "type": "string",
          "enum": [
            "available",
            "unavailable"
          ],
          "title": "Availability"
        },
        "unavailable_reason": {
          "anyOf": [
            {
              "type": "string",
              "const": "source_unavailable"
            },
            {
              "type": "null"
            }
          ],
          "title": "Unavailable Reason"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "attachment_id",
        "operation_id",
        "capture_id",
        "evidence_span_id",
        "source_sha256",
        "authorization_id",
        "screening_id",
        "attached_entry_revision",
        "attached_at",
        "detach_operation_id",
        "detached_entry_revision",
        "detached_by",
        "detached_at",
        "availability",
        "unavailable_reason"
      ],
      "title": "SavedWorldPreviousSourceAttachmentView"
    },
    "ArrivalDescriptor": {
      "properties": {
        "profile": {
          "type": "string",
          "const": "exulanica.arrival-descriptor/v1",
          "title": "Profile"
        },
        "presentation_policy": {
          "type": "string",
          "const": "exulanica.arrival-presentation/v1",
          "title": "Presentation Policy"
        },
        "region_id": {
          "type": "string",
          "minLength": 1,
          "title": "Region Id"
        },
        "position_local_mm": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 3,
          "minItems": 3,
          "title": "Position Local Mm"
        },
        "forward_local_millionths": {
          "prefixItems": [
            {
              "type": "integer"
            },
            {
              "type": "integer"
            },
            {
              "type": "integer"
            }
          ],
          "type": "array",
          "maxItems": 3,
          "minItems": 3,
          "title": "Forward Local Millionths"
        },
        "source": {
          "oneOf": [
            {
              "$ref": "#/components/schemas/RetainedScenePin"
            },
            {
              "$ref": "#/components/schemas/PointMapArrivalPin"
            },
            {
              "$ref": "#/components/schemas/PhotographArrivalPin"
            }
          ],
          "title": "Source",
          "discriminator": {
            "propertyName": "profile",
            "mapping": {
              "exulanica.arrival-photograph-pin/v1": "#/components/schemas/PhotographArrivalPin",
              "exulanica.arrival-point-map-pin/v1": "#/components/schemas/PointMapArrivalPin",
              "exulanica.arrival-scene-pin/v1": "#/components/schemas/RetainedScenePin"
            }
          }
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "profile",
        "presentation_policy",
        "region_id",
        "position_local_mm",
        "forward_local_millionths",
        "source"
      ],
      "title": "ArrivalDescriptor",
      "description": "Region-local opening pose and exact source under the versioned display policy."
    },
    "RetainedScenePin": {
      "properties": {
        "profile": {
          "type": "string",
          "const": "exulanica.arrival-scene-pin/v1",
          "title": "Profile"
        },
        "world_id": {
          "type": "string",
          "minLength": 1,
          "title": "World Id"
        },
        "version_id": {
          "type": "string",
          "format": "uuid",
          "title": "Version Id"
        },
        "source_snapshot_id": {
          "type": "string",
          "format": "uuid",
          "title": "Source Snapshot Id"
        },
        "region_id": {
          "type": "string",
          "minLength": 1,
          "title": "Region Id"
        },
        "scene_id": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
        },
        "job_id": {
          "type": "string",
          "format": "uuid",
          "title": "Job Id"
        },
        "pose_receipt_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Pose Receipt Sha256"
        },
        "placement_receipt_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Placement Receipt Sha256"
        },
        "gate_receipt_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Gate Receipt Sha256"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "profile",
        "world_id",
        "version_id",
        "source_snapshot_id",
        "region_id",
        "scene_id",
        "job_id",
        "pose_receipt_sha256",
        "placement_receipt_sha256",
        "gate_receipt_sha256"
      ],
      "title": "RetainedScenePin",
      "description": "The exact scene build a v4 society and its entry share."
    },
    "PointMapArrivalPin": {
      "properties": {
        "profile": {
          "type": "string",
          "const": "exulanica.arrival-point-map-pin/v1",
          "title": "Profile"
        },
        "world_id": {
          "type": "string",
          "minLength": 1,
          "title": "World Id"
        },
        "version_id": {
          "type": "string",
          "format": "uuid",
          "title": "Version Id"
        },
        "source_snapshot_id": {
          "type": "string",
          "format": "uuid",
          "title": "Source Snapshot Id"
        },
        "region_id": {
          "type": "string",
          "minLength": 1,
          "title": "Region Id"
        },
        "capture_id": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
        },
        "artifact_id": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
        },
        "content_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Content Sha256"
        },
        "byte_size": {
          "type": "integer",
          "exclusiveMinimum": 0,
          "title": "Byte Size"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "profile",
        "world_id",
        "version_id",
        "source_snapshot_id",
        "region_id",
        "capture_id",
        "artifact_id",
        "content_sha256",
        "byte_size"
      ],
      "title": "PointMapArrivalPin",
      "description": "One exact standalone estimate of an owned photograph."
    },
    "PhotographArrivalPin": {
      "properties": {
        "profile": {
          "type": "string",
          "const": "exulanica.arrival-photograph-pin/v1",
          "title": "Profile"
        },
        "world_id": {
          "type": "string",
          "minLength": 1,
          "title": "World Id"
        },
        "version_id": {
          "type": "string",
          "format": "uuid",
          "title": "Version Id"
        },
        "source_snapshot_id": {
          "type": "string",
          "format": "uuid",
          "title": "Source Snapshot Id"
        },
        "region_id": {
          "type": "string",
          "minLength": 1,
          "title": "Region Id"
        },
        "capture_id": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "profile",
        "world_id",
        "version_id",
        "source_snapshot_id",
        "region_id",
        "capture_id"
      ],
      "title": "PhotographArrivalPin",
      "description": "The source-photograph fallback when an owned region has no authorized geometry."
    },
    "ReconstructionSceneRow": {
      "properties": {
        "scene_id": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
        },
        "member_digest": {
          "type": "string",
          "title": "Member Digest"
        },
        "pose_receipt_sha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Pose Receipt Sha256"
        },
        "placement_receipt_sha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Placement Receipt Sha256"
        },
        "gate_digest": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Gate Digest"
        },
        "recorded_rung": {
          "anyOf": [
            {
              "type": "integer",
              "enum": [
                1,
                2,
                3,
                4
              ]
            },
            {
              "type": "null"
            }
          ],
          "title": "Recorded Rung"
        },
        "recorded_reasons": {
          "items": {
            "type": "string"
          },
          "type": "array",
          "title": "Recorded Reasons"
        },
        "displayed_rung": {
          "type": "integer",
          "enum": [
            1,
            2,
            3,
            4
          ],
          "title": "Displayed Rung"
        },
        "display_reasons": {
          "items": {
            "type": "string"
          },
          "type": "array",
          "title": "Display Reasons"
        },
        "member_count": {
          "type": "integer",
          "title": "Member Count"
        },
        "registered_member_count": {
          "type": "integer",
          "title": "Registered Member Count"
        },
        "receipt_state": {
          "type": "string",
          "enum": [
            "available",
            "missing",
            "invalid"
          ],
          "title": "Receipt State"
        },
        "placement_state": {
          "type": "string",
          "enum": [
            "available",
            "partial",
            "none_placed",
            "bytes_missing",
            "unavailable",
            "invalid"
          ],
          "title": "Placement State"
        },
        "rendering_substrate": {
          "type": "string",
          "enum": [
            "posed_point_maps",
            "unposed_point_maps",
            "source_photographs",
            "gaussian_splats"
          ],
          "title": "Rendering Substrate"
        },
        "hidden_person_count": {
          "type": "integer",
          "title": "Hidden Person Count"
        },
        "masked_member_count": {
          "type": "integer",
          "title": "Masked Member Count"
        },
        "trained_geometry": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneTrainedGeometryRow"
            },
            {
              "type": "null"
            }
          ]
        },
        "members": {
          "items": {
            "$ref": "#/components/schemas/ReconstructionSceneMemberRow"
          },
          "type": "array",
          "title": "Members"
        },
        "generated_geometry": {
          "items": {
            "$ref": "#/components/schemas/SceneGeneratedGeometryRow"
          },
          "type": "array",
          "title": "Generated Geometry"
        },
        "standpoint": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneStandpointRow"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "scene_id",
        "member_digest",
        "pose_receipt_sha256",
        "placement_receipt_sha256",
        "gate_digest",
        "recorded_rung",
        "recorded_reasons",
        "displayed_rung",
        "display_reasons",
        "member_count",
        "registered_member_count",
        "receipt_state",
        "placement_state",
        "rendering_substrate",
        "hidden_person_count",
        "masked_member_count",
        "members",
        "generated_geometry",
        "standpoint"
      ],
      "title": "ReconstructionSceneRow",
      "description": "A durable multi-photograph scene with recorded and deliverable state kept separate."
    },
    "SceneTrainedGeometryRow": {
      "properties": {
        "artifact_id": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "container": {
          "type": "string",
          "const": "sog/1",
          "title": "Container"
        },
        "scene_from_asset_row_major": {
          "items": {
            "type": "number"
          },
          "type": "array",
          "title": "Scene From Asset Row Major"
        },
        "bounds": {
          "additionalProperties": {
            "items": {
              "type": "number"
            },
            "type": "array"
          },
          "type": "object",
          "title": "Bounds"
        },
        "state": {
          "type": "string",
          "enum": [
            "available",
            "bytes_missing",
            "invalid"
          ],
          "title": "State"
        },
        "reference": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneGeometryReferenceRow"
            },
            {
              "type": "null"
            }
          ]
        },
        "quality": {
          "$ref": "#/components/schemas/SceneTrainingQualityRow"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "artifact_id",
        "content_sha256",
        "container",
        "scene_from_asset_row_major",
        "bounds",
        "state",
        "reference",
        "quality"
      ],
      "title": "SceneTrainedGeometryRow",
      "description": "A trained representation with its own bytes; it never carries a rung assertion."
    },
    "SceneGeometryReferenceRow": {
      "properties": {
        "href": {
          "type": "string",
          "title": "Href"
        },
        "authorization": {
          "type": "string",
          "const": "workspace-bearer",
          "title": "Authorization"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "byte_size": {
          "type": "integer",
          "title": "Byte Size"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "href",
        "authorization",
        "content_sha256",
        "byte_size"
      ],
      "title": "SceneGeometryReferenceRow",
      "description": "Authenticated, digest-declared bytes for one exact point-map artifact."
    },
    "SceneTrainingQualityRow": {
      "properties": {
        "heldout_views": {
          "type": "integer",
          "title": "Heldout Views"
        },
        "psnr": {
          "type": "number",
          "title": "Psnr"
        },
        "ssim": {
          "type": "number",
          "title": "Ssim"
        },
        "lpips": {
          "type": "number",
          "title": "Lpips"
        },
        "coverage_fraction": {
          "type": "number",
          "title": "Coverage Fraction"
        },
        "floaters_fraction": {
          "type": "number",
          "title": "Floaters Fraction"
        },
        "iterations_completed": {
          "type": "integer",
          "title": "Iterations Completed"
        },
        "duration_seconds": {
          "type": "number",
          "title": "Duration Seconds"
        },
        "usd_cost": {
          "type": "number",
          "title": "Usd Cost"
        },
        "gpu": {
          "type": "string",
          "title": "Gpu"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "heldout_views",
        "psnr",
        "ssim",
        "lpips",
        "coverage_fraction",
        "floaters_fraction",
        "iterations_completed",
        "duration_seconds",
        "usd_cost",
        "gpu"
      ],
      "title": "SceneTrainingQualityRow",
      "description": "The measured held-out appearance and accounting behind an accepted trained scene.\n\nAppearance-held-out numbers with pose conditioning, exactly as the trainer's quality receipt\nrecorded them; a summary for the status line, never a rung or a physical-scale claim."
    },
    "ReconstructionSceneMemberRow": {
      "properties": {
        "capture_id": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
        },
        "ordinal": {
          "type": "integer",
          "title": "Ordinal"
        },
        "registered": {
          "type": "boolean",
          "title": "Registered"
        },
        "placement": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/ScenePointMapPlacementRow"
            },
            {
              "type": "null"
            }
          ]
        },
        "unposed_point_map": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneUnposedPointMapRow"
            },
            {
              "type": "null"
            }
          ]
        },
        "exclusion_reason": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Exclusion Reason"
        },
        "person_regions": {
          "items": {
            "$ref": "#/components/schemas/MemberPersonRegionRow"
          },
          "type": "array",
          "title": "Person Regions"
        },
        "person_review_state": {
          "type": "string",
          "enum": [
            "unscreened",
            "screened",
            "stale"
          ],
          "title": "Person Review State"
        },
        "recovered_camera": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneRecoveredCameraRow"
            },
            {
              "type": "null"
            }
          ]
        },
        "standpoint_placement": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneStandpointPlacementRow"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "capture_id",
        "ordinal",
        "registered",
        "placement",
        "unposed_point_map",
        "exclusion_reason",
        "person_regions",
        "person_review_state",
        "standpoint_placement"
      ],
      "title": "ReconstructionSceneMemberRow",
      "description": "One immutable member and its exact placement or explicit exclusion."
    },
    "ScenePointMapPlacementRow": {
      "properties": {
        "artifact_id": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "container": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Container"
        },
        "scene_from_opm_row_major": {
          "items": {
            "type": "number"
          },
          "type": "array",
          "title": "Scene From Opm Row Major"
        },
        "local_units_to_scene_units": {
          "type": "number",
          "title": "Local Units To Scene Units"
        },
        "scale_status": {
          "type": "string",
          "const": "colmap-correspondence-fit",
          "title": "Scale Status"
        },
        "state": {
          "type": "string",
          "enum": [
            "available",
            "bytes_missing",
            "unavailable"
          ],
          "title": "State"
        },
        "reference": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneGeometryReferenceRow"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "artifact_id",
        "content_sha256",
        "container",
        "scene_from_opm_row_major",
        "local_units_to_scene_units",
        "scale_status",
        "state",
        "reference"
      ],
      "title": "ScenePointMapPlacementRow",
      "description": "A verified scene transform and the exact immutable point map it places."
    },
    "SceneUnposedPointMapRow": {
      "properties": {
        "artifact_id": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "container": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Container"
        },
        "state": {
          "type": "string",
          "enum": [
            "available",
            "bytes_missing",
            "unavailable"
          ],
          "title": "State"
        },
        "reference": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneGeometryReferenceRow"
            },
            {
              "type": "null"
            }
          ]
        },
        "photograph": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneUnposedPhotographRow"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "artifact_id",
        "content_sha256",
        "container",
        "state",
        "reference",
        "photograph"
      ],
      "title": "SceneUnposedPointMapRow",
      "description": "A member's own point map, offered because its scene's pose recovered no photograph.\n\nNo transform, on purpose. Pose recovery found no position for any member, so there is no\nmeasured relation between one photograph's depth and another's, and saying where each one\nstands would be a claim nothing recorded. The client lays these out in an arrangement it\nlabels as unmeasured. The bytes are the ones the scene's own placement record names by digest,\nread under the same live checks as a placed member's, so the lineage is the scene's and not a\nloose derivative's. Offered only when no member registered: a scene that placed some members\nkeeps its excluded members as photographs, because mixing measured and unmeasured panels in\none frame would let the unmeasured ones borrow the measured ones' authority, and a pose that\nregistered members but was refused keeps its recorded meaning until that is decided."
    },
    "SceneUnposedPhotographRow": {
      "properties": {
        "href": {
          "type": "string",
          "title": "Href"
        },
        "authorization": {
          "type": "string",
          "const": "workspace-bearer",
          "title": "Authorization"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "byte_size": {
          "type": "integer",
          "title": "Byte Size"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "href",
        "authorization",
        "content_sha256",
        "byte_size"
      ],
      "title": "SceneUnposedPhotographRow",
      "description": "The image a viewer may see of one member, for drawing its unplaced depth in full detail.\n\nThe route is the viewer route, ``/evidence/{span_id}/masked``, which serves the original when\nnobody in the photograph needs hiding and a current masked derivative when somebody does. The\ndigest is the one that route resolved to when the graph was read, so a client that receives\nother bytes, because a consent changed in between, refuses them and draws the depth's own\ncolours instead. It is never a way to reach an original the viewer route would not serve."
    },
    "MemberPersonRegionRow": {
      "properties": {
        "region_id": {
          "type": "string",
          "title": "Region Id"
        },
        "state": {
          "type": "string",
          "enum": [
            "unknown",
            "present",
            "shown",
            "hidden",
            "withdrawn"
          ],
          "title": "State"
        },
        "silhouette_ppm": {
          "items": {
            "items": {
              "type": "integer"
            },
            "type": "array"
          },
          "type": "array",
          "title": "Silhouette Ppm"
        },
        "display_name": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Display Name"
        },
        "subject_id": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Subject Id"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "region_id",
        "state",
        "silhouette_ppm",
        "display_name",
        "subject_id"
      ],
      "title": "MemberPersonRegionRow",
      "description": "One person in one photograph: their state, their outline, and never their pixels.\n\nThe outline is here and the pixels are not, which is the whole presentation rule in one\nmodel. A masked region is drawn as a silhouette; the bytes behind it were replaced with\nneutral fill before reconstruction ever read them, so there is nothing here for a client bug\nto reveal.\n\n``display_name`` is null unless naming was consented, somebody has actually been named, and\nthat person has not withdrawn. Three separate conditions. The first two are separate because a\nperson may consent to being named before anybody names them, and a name that appeared without\nthe first would be the exact failure the three-consent split exists to prevent. The third is\nseparate because a withdrawal is not a fourth consent and cannot be expressed by revoking one:\n``person_consent_is_granted`` has no withdrawal term, so a subject who withdrew still holds\ntheir old naming receipt and the name has to be taken back above it."
    },
    "SceneRecoveredCameraRow": {
      "properties": {
        "scene_from_camera_row_major": {
          "items": {
            "type": "number"
          },
          "type": "array",
          "title": "Scene From Camera Row Major"
        },
        "calibration": {
          "$ref": "#/components/schemas/SceneRecoveredCalibrationRow"
        },
        "projection": {
          "type": "string",
          "enum": [
            "pinhole",
            "pinhole-approximation"
          ],
          "title": "Projection"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "scene_from_camera_row_major",
        "calibration",
        "projection"
      ],
      "title": "SceneRecoveredCameraRow"
    },
    "SceneRecoveredCalibrationRow": {
      "properties": {
        "model": {
          "type": "string",
          "title": "Model"
        },
        "width": {
          "type": "integer",
          "title": "Width"
        },
        "height": {
          "type": "integer",
          "title": "Height"
        },
        "fx": {
          "type": "number",
          "title": "Fx"
        },
        "fy": {
          "type": "number",
          "title": "Fy"
        },
        "cx": {
          "type": "number",
          "title": "Cx"
        },
        "cy": {
          "type": "number",
          "title": "Cy"
        },
        "parameters": {
          "items": {
            "type": "number"
          },
          "type": "array",
          "title": "Parameters"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "model",
        "width",
        "height",
        "fx",
        "fy",
        "cx",
        "cy",
        "parameters"
      ],
      "title": "SceneRecoveredCalibrationRow"
    },
    "SceneStandpointPlacementRow": {
      "properties": {
        "scene_from_opm_row_major": {
          "items": {
            "type": "number"
          },
          "type": "array",
          "title": "Scene From Opm Row Major"
        },
        "depth_scale": {
          "type": "number",
          "title": "Depth Scale"
        },
        "lateral_scale": {
          "type": "number",
          "title": "Lateral Scale"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "scene_from_opm_row_major",
        "depth_scale",
        "lateral_scale"
      ],
      "title": "SceneStandpointPlacementRow",
      "description": "Where one member stands in its scene's standpoint arrangement: measured, not derived.\n\nOnly for a scene whose pose recovered no photograph and whose standpoint record joined this\nmember (``exulanica/reconstruction/standpoint_record.py``). The matrix acts on raw OPM positions\nand is ``R diag(s l, s l, s)``: the photograph turned to face the way it faced, its depth at the\nscene's scale ``s``, and its sideways extent re-projected onto the photograph's own rays by\n``l``. Every member's camera stands at the scene origin, which is the standpoint. Not a\nsimilarity when ``l`` is not 1, so a reader applies the matrix as it is and nothing else."
    },
    "SceneGeneratedGeometryRow": {
      "properties": {
        "artifact_id": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
        },
        "receipt_sha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Receipt Sha256"
        },
        "tier": {
          "type": "string",
          "const": "generated",
          "title": "Tier"
        },
        "state": {
          "type": "string",
          "enum": [
            "available",
            "invalid"
          ],
          "title": "State"
        },
        "state_reason": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "State Reason"
        },
        "model": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SceneGenerationModelRow"
            },
            {
              "type": "null"
            }
          ]
        },
        "prompt_sha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Prompt Sha256"
        },
        "conditioning": {
          "items": {
            "additionalProperties": {
              "type": "string"
            },
            "type": "object"
          },
          "type": "array",
          "title": "Conditioning"
        },
        "world_read_bundle_sha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "World Read Bundle Sha256"
        },
        "container": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Container"
        },
        "content_sha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Content Sha256"
        },
        "byte_size": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "Byte Size"
        },
        "seam": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Seam"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "artifact_id",
        "receipt_sha256",
        "tier",
        "state",
        "state_reason",
        "model",
        "prompt_sha256",
        "conditioning",
        "world_read_bundle_sha256",
        "container",
        "content_sha256",
        "byte_size",
        "seam"
      ],
      "title": "SceneGeneratedGeometryRow",
      "description": "Content a world model imagined, in its own tier below every recorded rung.\n\nA separate model from :class:`SceneTrainedGeometryRow` rather than a flag on it, because a\nclient that ignored a flag would draw imagination as record. To draw one of these a client has\nto have read a field whose name says what it is.\n\n``seam`` is where the record stops, in words, and it is required of every valid generation.\n``conditioning`` is what the model was actually shown, digest by digest, which is what makes\n\"conditioned on the real place\" checkable rather than asserted."
    },
    "SceneGenerationModelRow": {
      "properties": {
        "provider": {
          "type": "string",
          "title": "Provider"
        },
        "model_id": {
          "type": "string",
          "title": "Model Id"
        },
        "model_version": {
          "type": "string",
          "title": "Model Version"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "provider",
        "model_id",
        "model_version"
      ],
      "title": "SceneGenerationModelRow",
      "description": "Which model produced a generated surface, at which version."
    },
    "SceneStandpointRow": {
      "properties": {
        "artifact_id": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "state": {
          "type": "string",
          "enum": [
            "joined",
            "nothing_joined",
            "withdrawn",
            "stale",
            "invalid",
            "bytes_missing"
          ],
          "title": "State"
        },
        "member_count": {
          "type": "integer",
          "title": "Member Count"
        },
        "joined_member_count": {
          "type": "integer",
          "title": "Joined Member Count"
        },
        "reference_capture_id": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Reference Capture Id"
        },
        "rotation_residual_max_millidegrees": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "Rotation Residual Max Millidegrees"
        },
        "scale_residual_max_ppm": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "Scale Residual Max Ppm"
        },
        "up_method": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Up Method"
        },
        "implied_roll_max_millidegrees": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "Implied Roll Max Millidegrees"
        },
        "excluded": {
          "items": {
            "$ref": "#/components/schemas/SceneStandpointExclusionRow"
          },
          "type": "array",
          "title": "Excluded"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "artifact_id",
        "content_sha256",
        "state",
        "member_count",
        "joined_member_count",
        "reference_capture_id",
        "rotation_residual_max_millidegrees",
        "scale_residual_max_ppm",
        "up_method",
        "implied_roll_max_millidegrees",
        "excluded"
      ],
      "title": "SceneStandpointRow",
      "description": "The scene's standpoint record as it can be used now.\n\n``joined`` means the arrangement is drawn and its members carry placements. Every other state\ndraws nothing from it, and the scene's photographs keep the unmeasured arrangement:\n``nothing_joined`` is a record that found no two photographs to join, ``withdrawn`` is a record\none of whose read members may no longer be used (every rotation in it was measured with that\nmember's pixels), ``stale`` is a record of an earlier build or point map, and ``invalid`` and\n``bytes_missing`` are what they say. The residuals are the record's own, for the status line."
    },
    "SceneStandpointExclusionRow": {
      "properties": {
        "capture_id": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
        },
        "reason": {
          "type": "string",
          "enum": [
            "insufficient_overlap",
            "moved_between_photographs",
            "scene_changed",
            "inconsistent_with_set",
            "not_permitted",
            "point_map_unreadable",
            "focal_length_unstated"
          ],
          "title": "Reason"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "capture_id",
        "reason"
      ],
      "title": "SceneStandpointExclusionRow",
      "description": "A member photograph the arrangement does not hold, and why, in a stable code."
    },
    "AlternateVersionView": {
      "properties": {
        "schema_version": {
          "type": "integer",
          "title": "Schema Version"
        },
        "version_id": {
          "type": "string",
          "format": "uuid",
          "title": "Version Id"
        },
        "world_id": {
          "type": "string",
          "title": "World Id"
        },
        "source_snapshot_id": {
          "type": "string",
          "format": "uuid",
          "title": "Source Snapshot Id"
        },
        "parent_version_id": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Parent Version Id"
        },
        "title": {
          "type": "string",
          "title": "Title"
        },
        "origin": {
          "type": "string",
          "title": "Origin"
        },
        "style_version_id": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Style Version Id"
        },
        "state_sha256": {
          "type": "string",
          "title": "State Sha256"
        },
        "edit_seq": {
          "type": "integer",
          "title": "Edit Seq"
        },
        "source_invalidated": {
          "type": "boolean",
          "title": "Source Invalidated"
        },
        "created_by": {
          "type": "string",
          "format": "uuid",
          "title": "Created By"
        },
        "created_at": {
          "type": "string",
          "title": "Created At"
        },
        "objects": {
          "items": {
            "$ref": "#/components/schemas/AuthoredObjectView"
          },
          "type": "array",
          "title": "Objects"
        },
        "element_overrides": {
          "items": {
            "$ref": "#/components/schemas/ElementOverrideView"
          },
          "type": "array",
          "title": "Element Overrides"
        },
        "environment_instances": {
          "items": {
            "additionalProperties": {
              "$ref": "#/components/schemas/JsonValue"
            },
            "type": "object"
          },
          "type": "array",
          "title": "Environment Instances"
        },
        "point_map_instances": {
          "items": {
            "additionalProperties": {
              "$ref": "#/components/schemas/JsonValue"
            },
            "type": "object"
          },
          "type": "array",
          "title": "Point Map Instances"
        },
        "things": {
          "items": {
            "additionalProperties": {
              "$ref": "#/components/schemas/JsonValue"
            },
            "type": "object"
          },
          "type": "array",
          "title": "Things"
        },
        "edits": {
          "items": {
            "$ref": "#/components/schemas/VersionEditView"
          },
          "type": "array",
          "title": "Edits"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "schema_version",
        "version_id",
        "world_id",
        "source_snapshot_id",
        "parent_version_id",
        "title",
        "origin",
        "style_version_id",
        "state_sha256",
        "edit_seq",
        "source_invalidated",
        "created_by",
        "created_at",
        "objects",
        "element_overrides",
        "environment_instances",
        "point_map_instances",
        "things",
        "edits"
      ],
      "title": "AlternateVersionView"
    },
    "AuthoredObjectView": {
      "properties": {
        "object_id": {
          "type": "string",
          "title": "Object Id"
        },
        "asset": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/ReviewedAssetView"
            },
            {
              "type": "null"
            }
          ]
        },
        "workspace_asset": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/WorkspaceAssetObjectView"
            },
            {
              "type": "null"
            }
          ]
        },
        "region_id": {
          "type": "string",
          "title": "Region Id"
        },
        "transform": {
          "$ref": "#/components/schemas/TransformView"
        },
        "origin": {
          "$ref": "#/components/schemas/ObjectOriginView"
        },
        "behaviour": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/ObjectBehaviourView"
            },
            {
              "type": "null"
            }
          ]
        },
        "removed": {
          "type": "boolean",
          "title": "Removed"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "object_id",
        "asset",
        "region_id",
        "transform",
        "origin",
        "behaviour",
        "removed"
      ],
      "title": "AuthoredObjectView"
    },
    "ReviewedAssetView": {
      "properties": {
        "asset_key": {
          "type": "string",
          "title": "Asset Key"
        },
        "title": {
          "type": "string",
          "title": "Title"
        },
        "summary": {
          "type": "string",
          "title": "Summary"
        },
        "media_type": {
          "type": "string",
          "title": "Media Type"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "byte_size": {
          "type": "integer",
          "title": "Byte Size"
        },
        "licence_id": {
          "type": "string",
          "title": "Licence Id"
        },
        "licence_sha256": {
          "type": "string",
          "title": "Licence Sha256"
        },
        "availability": {
          "type": "string",
          "title": "Availability"
        },
        "placeable": {
          "type": "boolean",
          "title": "Placeable"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "asset_key",
        "title",
        "summary",
        "media_type",
        "content_sha256",
        "byte_size",
        "licence_id",
        "licence_sha256",
        "availability",
        "placeable"
      ],
      "title": "ReviewedAssetView"
    },
    "WorkspaceAssetObjectView": {
      "properties": {
        "asset_id": {
          "type": "string",
          "format": "uuid",
          "title": "Asset Id"
        },
        "preparation_id": {
          "type": "string",
          "format": "uuid",
          "title": "Preparation Id"
        },
        "title": {
          "type": "string",
          "title": "Title"
        },
        "content_sha256": {
          "type": "string",
          "title": "Content Sha256"
        },
        "byte_size": {
          "type": "integer",
          "title": "Byte Size"
        },
        "media_type": {
          "type": "string",
          "title": "Media Type"
        },
        "licence_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Licence Id"
        },
        "attribution": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Attribution"
        },
        "availability": {
          "type": "string",
          "title": "Availability"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "asset_id",
        "preparation_id",
        "title",
        "content_sha256",
        "byte_size",
        "media_type",
        "licence_id",
        "attribution",
        "availability"
      ],
      "title": "WorkspaceAssetObjectView",
      "description": "What a placed object draws when it is a person's own admitted asset (migration 0126).\n\n``availability`` is resolved when the version is read and is not part of ``state_sha256``:\n``available``, ``withdrawn`` (the admission was withdrawn or its workspace erased; the object\nstays in the version and is not drawn), ``unavailable_bytes``, or ``unknown`` when this\ninstance keeps no workspace asset store. The bytes are\n``GET /workspace-assets/{asset_id}/prepared/bytes``, checked against ``content_sha256``."
    },
    "TransformView": {
      "properties": {
        "coordinate_space": {
          "type": "string",
          "title": "Coordinate Space"
        },
        "coordinate_unit": {
          "type": "string",
          "title": "Coordinate Unit"
        },
        "x_mm": {
          "type": "integer",
          "title": "X Mm"
        },
        "y_mm": {
          "type": "integer",
          "title": "Y Mm"
        },
        "z_mm": {
          "type": "integer",
          "title": "Z Mm"
        },
        "yaw_microradians": {
          "type": "integer",
          "title": "Yaw Microradians"
        },
        "scale_milli": {
          "type": "integer",
          "title": "Scale Milli"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "coordinate_space",
        "coordinate_unit",
        "x_mm",
        "y_mm",
        "z_mm",
        "yaw_microradians",
        "scale_milli"
      ],
      "title": "TransformView"
    },
    "ObjectOriginView": {
      "properties": {
        "kind": {
          "type": "string",
          "title": "Kind"
        },
        "role": {
          "type": "string",
          "title": "Role"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "kind",
        "role"
      ],
      "title": "ObjectOriginView"
    },
    "ObjectBehaviourView": {
      "properties": {
        "behaviour_key": {
          "type": "string",
          "title": "Behaviour Key"
        },
        "behaviour_version": {
          "type": "integer",
          "title": "Behaviour Version"
        },
        "parameters": {
          "additionalProperties": {
            "$ref": "#/components/schemas/JsonValue"
          },
          "type": "object",
          "title": "Parameters"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "behaviour_key",
        "behaviour_version",
        "parameters"
      ],
      "title": "ObjectBehaviourView"
    },
    "ElementOverrideView": {
      "properties": {
        "element_id": {
          "type": "string",
          "title": "Element Id"
        },
        "suppressed": {
          "type": "boolean",
          "title": "Suppressed"
        },
        "transform": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/TransformView"
            },
            {
              "type": "null"
            }
          ]
        },
        "storeys": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "Storeys"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "element_id",
        "suppressed",
        "transform"
      ],
      "title": "ElementOverrideView"
    },
    "VersionEditView": {
      "properties": {
        "edit_id": {
          "type": "string",
          "format": "uuid",
          "title": "Edit Id"
        },
        "edit_seq": {
          "type": "integer",
          "title": "Edit Seq"
        },
        "kind": {
          "type": "string",
          "title": "Kind"
        },
        "object_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Object Id"
        },
        "element_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Element Id"
        },
        "environment_instance_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Environment Instance Id"
        },
        "point_map_instance_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Point Map Instance Id"
        },
        "thing_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Thing Id"
        },
        "undone_edit_id": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Undone Edit Id"
        },
        "base_state_sha256": {
          "type": "string",
          "title": "Base State Sha256"
        },
        "result_state_sha256": {
          "type": "string",
          "title": "Result State Sha256"
        },
        "actor": {
          "type": "string",
          "format": "uuid",
          "title": "Actor"
        },
        "recorded_at": {
          "type": "string",
          "title": "Recorded At"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "edit_id",
        "edit_seq",
        "kind",
        "object_id",
        "element_id",
        "environment_instance_id",
        "point_map_instance_id",
        "thing_id",
        "undone_edit_id",
        "base_state_sha256",
        "result_state_sha256",
        "actor",
        "recorded_at"
      ],
      "title": "VersionEditView"
    },
    "AddObjectBody": {
      "properties": {
        "base_state_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Base State Sha256"
        },
        "saved_entry": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/SavedEntryAdvanceBody"
            },
            {
              "type": "null"
            }
          ]
        },
        "object_id": {
          "type": "string",
          "maxLength": 200,
          "minLength": 1,
          "title": "Object Id"
        },
        "asset_sha256": {
          "type": "string",
          "maxLength": 64,
          "minLength": 64,
          "title": "Asset Sha256"
        },
        "region_id": {
          "type": "string",
          "maxLength": 500,
          "minLength": 1,
          "title": "Region Id"
        },
        "transform": {
          "$ref": "#/components/schemas/TransformBody"
        },
        "origin_role": {
          "type": "string",
          "enum": [
            "fictional",
            "personal"
          ],
          "title": "Origin Role"
        },
        "behaviour": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/BehaviourBody"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "base_state_sha256",
        "object_id",
        "asset_sha256",
        "region_id",
        "transform",
        "origin_role"
      ],
      "title": "AddObjectBody"
    },
    "SavedEntryAdvanceBody": {
      "properties": {
        "entry_id": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
        },
        "base_revision": {
          "type": "integer",
          "minimum": 1,
          "title": "Base Revision"
        },
        "authored_state_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Authored State Sha256"
        },
        "authored_edit_seq": {
          "type": "integer",
          "minimum": 0,
          "title": "Authored Edit Seq"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "entry_id",
        "base_revision",
        "authored_state_sha256",
        "authored_edit_seq"
      ],
      "title": "SavedEntryAdvanceBody"
    },
    "TransformBody": {
      "properties": {
        "x_mm": {
          "type": "integer",
          "title": "X Mm"
        },
        "y_mm": {
          "type": "integer",
          "title": "Y Mm"
        },
        "z_mm": {
          "type": "integer",
          "title": "Z Mm"
        },
        "yaw_microradians": {
          "type": "integer",
          "maximum": 6283185,
          "minimum": 0,
          "title": "Yaw Microradians"
        },
        "scale_milli": {
          "type": "integer",
          "maximum": 1000000,
          "minimum": 1,
          "title": "Scale Milli"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "x_mm",
        "y_mm",
        "z_mm",
        "yaw_microradians",
        "scale_milli"
      ],
      "title": "TransformBody"
    },
    "BehaviourBody": {
      "properties": {
        "behaviour_key": {
          "type": "string",
          "maxLength": 200,
          "title": "Behaviour Key"
        },
        "behaviour_version": {
          "type": "integer",
          "minimum": 1,
          "title": "Behaviour Version"
        },
        "parameters": {
          "additionalProperties": {
            "$ref": "#/components/schemas/JsonValue"
          },
          "type": "object",
          "title": "Parameters"
        }
      },
      "additionalProperties": false,
      "type": "object",
      "required": [
        "behaviour_key",
        "behaviour_version",
        "parameters"
      ],
      "title": "BehaviourBody"
    }
  }
};
