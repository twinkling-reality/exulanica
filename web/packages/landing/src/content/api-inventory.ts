// Generated from the pinned API and route contracts. Run scripts/sync-api-reference.mjs.
import type { InventoryOperation } from "./api-types.js";
export const API_INVENTORY: readonly InventoryOperation[] = [
  {
    "path": "/healthz",
    "method": "get",
    "id": "healthz_healthz_get",
    "title": "Liveness. Touches no dependency.",
    "description": "",
    "group": "health",
    "permission": {
      "public": "a liveness probe that needed a credential would go red when the credential rotated"
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "additionalProperties": {
                "type": "string"
              },
              "type": "object",
              "title": "Response Healthz Healthz Get"
            }
          }
        }
      }
    }
  },
  {
    "path": "/readyz",
    "method": "get",
    "id": "readyz_readyz_get",
    "title": "Readiness. One query, one object-store call, no model call.",
    "description": "Report each check separately, and return 503 when any of them fails.\n\nSeparately, because a single boolean tells an operator at 3am that something is wrong and\nnothing about which thing. The checks are the ones section 6.2 lists, and each one's entry says\nwhat it proves rather than only whether it passed. ``checked_at`` and ``age_ms`` say when the\nchecks ran; ``capacity`` gives the declared limits, and ``GET /operations/capacity`` the counts.",
    "group": "health",
    "permission": {
      "public": "the same, and it reports no workspace content"
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "additionalProperties": true,
              "type": "object",
              "title": "Response Readyz Readyz Get"
            }
          }
        }
      }
    }
  },
  {
    "path": "/auth/google/start",
    "method": "get",
    "id": "google_start_auth_google_start_get",
    "title": "Google Start",
    "description": "",
    "group": "accounts",
    "permission": {
      "authentication": "begins Google sign-in; there is no credential yet, and it sets only a login cookie"
    },
    "parameters": [
      {
        "name": "return_uri",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "maxLength": 2048
            },
            {
              "type": "null"
            }
          ],
          "title": "Return Uri"
        }
      }
    ],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/auth/google/callback",
    "method": "get",
    "id": "google_callback_auth_google_callback_get",
    "title": "Google Callback",
    "description": "",
    "group": "accounts",
    "permission": {
      "authentication": "completes sign-in against its own login cookie, provider state and origin check"
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          }
        }
      }
    }
  },
  {
    "path": "/auth/session",
    "method": "get",
    "id": "account_session_auth_session_get",
    "title": "Account Session",
    "description": "The browser's session: its account, workspace, role and CSRF token.\n\nA signed-out browser is answered 401 (``authentication_failed``), and a server with no browser\naccounts 503 (``account_unavailable``); both answers also carry ``sign_in``, how a browser may\ncome in here: ``google`` (true or false) and ``guest`` (``code`` when ``POST /auth/guest``\ntakes the entry code, ``open`` when it takes none, ``off`` when it admits nobody new). An\nanswer without ``sign_in`` is one whose server could not read its own configuration.",
    "group": "accounts",
    "permission": {
      "authentication": "reports the browser session its own cookie names, and refuses without one"
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          }
        }
      }
    }
  },
  {
    "path": "/auth/guest",
    "method": "post",
    "id": "guest_entry_auth_guest_post",
    "title": "Guest Entry",
    "description": "Enter as a guest: an account with no identity, a workspace of its own and a session.\n\nAfter the account's transaction commits, the workspace is given its allowance by the spending\nauthority's guest policy and its first world from the installation's arrival list, dressed\nwith the scene the list names for it, if any. Any of these can fail without undoing the entry,\nso once the account exists the answer is always 201 with the session cookie, and\n``incomplete`` names each step that failed (``allowance`` with the refusal's code,\n``arrival``, or ``scene`` with its code and, for one being's mind, its ``thing_id``). A visitor\nwhose allowance is missing is granted it on their next session read (``GET /auth/session``).",
    "group": "accounts",
    "permission": {
      "authentication": "makes a guest's account, workspace and session; there is no credential yet, and it checks its own origin, entry code and day's limit"
    },
    "parameters": [],
    "request": {
      "content": {
        "application/json": {
          "schema": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/GuestEntryBody"
              },
              {
                "type": "null"
              }
            ],
            "title": "Body"
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/auth/logout",
    "method": "post",
    "id": "logout_auth_logout_post",
    "title": "Logout",
    "description": "",
    "group": "accounts",
    "permission": {
      "authentication": "ends the browser session its own cookie names, and must work for any holder of it"
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          }
        }
      }
    }
  },
  {
    "path": "/graph",
    "method": "get",
    "id": "snapshot_graph_get",
    "title": "The entity graph, as one snapshot at one state version.",
    "description": "",
    "group": "graph",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/GraphPayload"
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
  },
  {
    "path": "/graph/sources",
    "method": "get",
    "id": "sources_graph_sources_get",
    "title": "Live admitted photographs for review before reconstruction.",
    "description": "",
    "group": "graph",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/ReviewSourceRow"
              },
              "title": "Response Sources Graph Sources Get"
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
  },
  {
    "path": "/geometry",
    "method": "get",
    "id": "geometry_geometry_get",
    "title": "Which captures have reconstructed geometry, and the digest of each.",
    "description": "The descriptor list, in the presentation order :func:`point_map_descriptors` documents.\n\nKeyed by capture. An island is a client decision (ADR-0005) and the graph payload ships no\nisland id, so this ships none either: the client puts capture ids through the same\n``islandOf`` its occurrences went through, and geometry lands in the same regions the anchors\ndid. A server that grouped them here would be answering a question it was deliberately kept\nout of.",
    "group": "geometry",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/GeometryView"
              },
              "title": "Response Geometry Geometry Get"
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
  },
  {
    "path": "/geometry/{artifact_id}",
    "method": "get",
    "id": "point_map_geometry__artifact_id__get",
    "title": "The bytes of one reconstructed point map. Never a citation target.",
    "description": "",
    "group": "geometry",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "artifact_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          },
          "application/vnd.exulanica.point-map": {}
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
  },
  {
    "path": "/scene-geometry/{artifact_id}",
    "method": "get",
    "id": "trained_scene_scene_geometry__artifact_id__get",
    "title": "Exact trained scene bytes, never a citation target.",
    "description": "",
    "group": "geometry",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "artifact_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/scene-segments/{scene_id}",
    "method": "get",
    "id": "scene_segments_scene_segments__scene_id__get",
    "title": "The entities lifted into one scene, as voxels, under the geometry read policy.",
    "description": "",
    "group": "geometry",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "scene_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SceneSegmentsView"
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
  },
  {
    "path": "/selection",
    "method": "post",
    "id": "resolve_selection_selection_post",
    "title": "Resolve a Selection to captures, entities and evidence.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SelectionPlan"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SelectionView"
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
  },
  {
    "path": "/selection/place-bridges",
    "method": "get",
    "id": "place_bridges_selection_place_bridges_get",
    "title": "List confirmed canonical-to-memory place bridges.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/PlaceBridgeView"
              },
              "title": "Response Place Bridges Selection Place Bridges Get"
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
  },
  {
    "path": "/selection/place-bridges",
    "method": "post",
    "id": "confirm_place_bridge_selection_place_bridges_post",
    "title": "Confirm a canonical-to-memory place bridge.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PlaceBridgeRequest"
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
              "$ref": "#/components/schemas/PlaceBridgeView"
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
  },
  {
    "path": "/selection/place-bridges/{decision_id}/revoke",
    "method": "post",
    "id": "revoke_place_bridge_selection_place_bridges__decision_id__revoke_post",
    "title": "Revoke a confirmed canonical-to-memory place bridge.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "deletion.write"
      ]
    },
    "parameters": [
      {
        "name": "decision_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Decision Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PlaceBridgeRevocationRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/PlaceBridgeView"
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
  },
  {
    "path": "/selection/catalogue",
    "method": "get",
    "id": "catalogue_selection_catalogue_get",
    "title": "The named entities this session may filter by.",
    "description": "What the interface offers as filter chips, and what the planner is allowed to reference.\n\nNamed entities only. An entity with no name is one the user has not identified, and offering\nit as a filter would be offering to filter by somebody they have never met by name.",
    "group": "selection",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/EntityView"
              },
              "title": "Response Catalogue Selection Catalogue Get"
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
  },
  {
    "path": "/selection/plan",
    "method": "post",
    "id": "plan_from_question_selection_plan_post",
    "title": "Propose a Selection from a question. Does not run it.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "library.read",
        "model.invoke"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/QuestionRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SelectionPlan"
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
  },
  {
    "path": "/selection/ask",
    "method": "post",
    "id": "ask_selection_ask_post",
    "title": "Answer a question, citing evidence, or decline to answer.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "library.read",
        "model.invoke"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/QuestionRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/exulanica__api__routes__selection__AnswerView"
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
  },
  {
    "path": "/selection/packet",
    "method": "post",
    "id": "packet_selection_packet_post",
    "title": "The evidence a Selection would offer, without composing text.",
    "description": "The deterministic half of the answer path, exposed on its own.\n\nUseful to the interface, which can show what a question found without spending a model call,\nand useful to an evaluation run, which needs the retrieval measured separately from the\ncomposition.",
    "group": "selection",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SelectionPlan"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Packet Selection Packet Post"
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
  },
  {
    "path": "/selection/appearance",
    "method": "post",
    "id": "appearance_selection_appearance_post",
    "title": "Read one utterance as a bounded appearance proposal, or decline to.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "model.invoke",
        "world.read"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/AppearanceRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/AppearanceView"
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
  },
  {
    "path": "/selection/actions",
    "method": "post",
    "id": "plan_actions_selection_actions_post",
    "title": "Read one utterance as a plan of exact world requests, or decline to. Changes nothing.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "model.invoke",
        "world.read"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ActionRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ActionPlanView"
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
  },
  {
    "path": "/selection/actions/prepare",
    "method": "post",
    "id": "prepare_actions_selection_actions_prepare_post",
    "title": "Prepare typed actions as a plan, with no model. Changes nothing.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PrepareRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ActionPlanView"
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
  },
  {
    "path": "/selection/actions/outcome",
    "method": "post",
    "id": "action_outcomes_selection_actions_outcome_post",
    "title": "What the authorities recorded for a plan's steps, read back. Changes nothing.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/OutcomeRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ActionOutcomeView"
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
  },
  {
    "path": "/selection/environment",
    "method": "post",
    "id": "environment_proposal_selection_environment_post",
    "title": "Propose one typed NYC environment edit without changing world state.",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "model.invoke",
        "world.read"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/EnvironmentProposalRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/EnvironmentProposalResponse"
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
  },
  {
    "path": "/world/versions/{version_id}/society",
    "method": "post",
    "id": "create_society_world_versions__version_id__society_post",
    "title": "Create Society",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CreateSocietyBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Create Society World Versions  Version Id  Society Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society",
    "method": "get",
    "id": "society_world_versions__version_id__society_get",
    "title": "Society",
    "description": "The current state. ``places`` adds where inhabitants can go, as its consumed input says.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/world/versions/{version_id}/society",
    "method": "delete",
    "id": "erase_society_records_world_versions__version_id__society_delete",
    "title": "Erase Society Records",
    "description": "Erase this world version's society whole, under a society tombstone: every row that records\nit (what its people said among them), its clock, its asks to outside programs and its\ncrossings, and the comparisons and experiments started from it; the Companion's answers that\ncited the version are withdrawn. Refused ``society_unavailable`` (404) where the version holds\nno society, and ``restore_sealed`` (409) while the installation is sealed for a restore.",
    "group": "society",
    "permission": {
      "requires": [
        "deletion.write",
        "world.write"
      ]
    },
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/world/versions/{version_id}/society/decisions",
    "method": "post",
    "id": "propose_decision_world_versions__version_id__society_decisions_post",
    "title": "Propose Decision",
    "description": "Refused by name for every society: explicitly requested model proposals are retired.\n\nThey were the retired ``exulanica-society/v3`` engine's, and no host was ever configured to\nanswer them. A model decides for a person only as the world's owner chose, at the planner's\nown choice point. The world and its society are resolved first, so a stranger learns nothing\nfrom the refusal that an unknown version would not tell them; a stored request still reads.",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DecisionBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Propose Decision World Versions  Version Id  Society Decisions Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/decisions/{request_id}",
    "method": "get",
    "id": "read_decision_world_versions__version_id__society_decisions__request_id__get",
    "title": "Read Decision",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "request_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Request Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Read Decision World Versions  Version Id  Society Decisions  Request Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/take-in",
    "method": "post",
    "id": "take_newcomers_in_society_world_versions__version_id__society_take_in_post",
    "title": "Take Newcomers In Society",
    "description": "A living town's people take in what was placed in their world after they came: this\nversion's living society is ended and a society of things made on the same version, in one\ntransaction, and answered as a creation answers. They are the same people, with their\nidentities, homes, jobs, roles and shifts; their day so far is not kept: the erasure is the\none ``DELETE .../society`` makes (a society tombstone, every row that records the society,\nits clock, its asks and crossings, the comparisons and experiments started from it, and the\nCompanion's answers that cited the version withdrawn). Refused ``society_unavailable`` (404)\nwhere the version holds no society, ``society_takes_in_already`` (409) where its society is\nnot a living one, ``nothing_to_take_in`` (409) where the engine table gives the version no\nsociety of things, and ``restore_sealed`` (409) while the installation is sealed for a\nrestore; a refusal of the making is answered as a creation's and leaves the living society\nas it was.",
    "group": "society",
    "permission": {
      "requires": [
        "deletion.write",
        "world.write"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Take Newcomers In Society World Versions  Version Id  Society Take In Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/steps",
    "method": "post",
    "id": "advance_society_world_versions__version_id__society_steps_post",
    "title": "Advance Society",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/StepSocietyBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Advance Society World Versions  Version Id  Society Steps Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/presence",
    "method": "post",
    "id": "change_society_presence_world_versions__version_id__society_presence_post",
    "title": "Change Society Presence",
    "description": "One recorded minute in which everyone leaves, or the same people arrive again.\n\nThe request names only what the person wants and the state they saw; the server resolves the\nworld, the society, the rights and the minute. A refusal names what stands in the way.",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PresenceBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Change Society Presence World Versions  Version Id  Society Presence Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/events",
    "method": "get",
    "id": "society_events_world_versions__version_id__society_events_get",
    "title": "Society Events",
    "description": "The society's events, newest first, a page at a time (``before`` reads on). Naming a window\nof minutes (``from_tick``, ``to_tick``, inclusive) reads it oldest first instead, a page at a\ntime (``after`` reads on), so a page can show what was said in the minutes it draws, in order;\n``kinds`` keeps those kinds alone (``said`` for lines). A window that ends before it begins,\n``before`` with a window, ``after`` without one or a malformed kind is refused\n``invalid_events_window``.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 256,
          "minimum": 1,
          "default": 256,
          "title": "Limit"
        }
      },
      {
        "name": "before",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 120
            },
            {
              "type": "null"
            }
          ],
          "title": "Before"
        }
      },
      {
        "name": "after",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 120
            },
            {
              "type": "null"
            }
          ],
          "title": "After"
        }
      },
      {
        "name": "kinds",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "array",
              "items": {
                "type": "string"
              },
              "minItems": 1,
              "maxItems": 16
            },
            {
              "type": "null"
            }
          ],
          "title": "Kinds"
        }
      },
      {
        "name": "from_tick",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "maximum": 2147483647,
              "minimum": 0
            },
            {
              "type": "null"
            }
          ],
          "title": "From Tick"
        }
      },
      {
        "name": "to_tick",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "maximum": 2147483647,
              "minimum": 0
            },
            {
              "type": "null"
            }
          ],
          "title": "To Tick"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Society Events World Versions  Version Id  Society Events Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/inputs/{input_seq}",
    "method": "get",
    "id": "society_input_provenance_world_versions__version_id__society_inputs__input_seq__get",
    "title": "Society Input Provenance",
    "description": "One stored input of the version's society: its identity and the authored state it was\ncomposed after, the version's ``edit_seq`` and state digest as the input records them, never\nthe input itself. An event names its input by ``input_seq``, so this read joins an event to the\nedit in the version's history that it followed. Its rights are asked as the events read asks\nthem.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "input_seq",
        "in": "path",
        "required": true,
        "schema": {
          "type": "integer",
          "maximum": 2147483647,
          "minimum": 1,
          "title": "Input Seq"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Society Input Provenance World Versions  Version Id  Society Inputs  Input Seq  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/replay",
    "method": "get",
    "id": "replay_society_world_versions__version_id__society_replay_get",
    "title": "Replay Society",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/world/versions/{version_id}/society/actions",
    "method": "post",
    "id": "record_action_world_versions__version_id__society_actions_post",
    "title": "Record Action",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SocietyActionBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Record Action World Versions  Version Id  Society Actions Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/actions",
    "method": "get",
    "id": "action_events_world_versions__version_id__society_actions_get",
    "title": "Action Events",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 128,
          "minimum": 1,
          "default": 64,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Action Events World Versions  Version Id  Society Actions Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/actions/{request_id}",
    "method": "get",
    "id": "read_action_world_versions__version_id__society_actions__request_id__get",
    "title": "Read Action",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "request_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Request Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Read Action World Versions  Version Id  Society Actions  Request Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control",
    "method": "get",
    "id": "read_control_world_versions__version_id__society_control_get",
    "title": "Read Control",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ControlRead"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control",
    "method": "put",
    "id": "configure_control_world_versions__version_id__society_control_put",
    "title": "Configure Control",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ConfigureBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ControlRead"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control/steps",
    "method": "post",
    "id": "manual_step_world_versions__version_id__society_control_steps_post",
    "title": "Manual Step",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/StepBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Manual Step World Versions  Version Id  Society Control Steps Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control/events",
    "method": "get",
    "id": "control_events_world_versions__version_id__society_control_events_get",
    "title": "Control Events",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 128,
          "minimum": 1,
          "default": 64,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Control Events World Versions  Version Id  Society Control Events Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control/sessions",
    "method": "post",
    "id": "open_living_session_world_versions__version_id__society_control_sessions_post",
    "title": "Open Living Session",
    "description": "Open a living session on a paused society and play it: one bounded stretch of playback,\nstated by its limits, from the tick and state digest the caller read. Refused 409\n``session_already_open`` while one is open, ``society_not_paused`` for a society playing without\none, ``session_request_reused`` for a key that opened a session with other limits, and\n``stale_society_state`` for another revision, tick or digest; 422 for limits beyond the\ninstallation's. The same key answers the session it opened.",
    "group": "society",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/OpenSessionBody"
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
              "title": "Response Open Living Session World Versions  Version Id  Society Control Sessions Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control/sessions",
    "method": "get",
    "id": "list_living_sessions_world_versions__version_id__society_control_sessions_get",
    "title": "List Living Sessions",
    "description": "Every living session of the society, newest first, each open until it closed.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response List Living Sessions World Versions  Version Id  Society Control Sessions Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control/sessions/{session_id}",
    "method": "get",
    "id": "read_living_session_world_versions__version_id__society_control_sessions__session_id__get",
    "title": "Read Living Session",
    "description": "One living session; 404 ``session_unknown`` where the society has none by that id.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "session_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Session Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Read Living Session World Versions  Version Id  Society Control Sessions  Session Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/control/sessions/{session_id}/stop",
    "method": "post",
    "id": "stop_living_session_world_versions__version_id__society_control_sessions__session_id__stop_post",
    "title": "Stop Living Session",
    "description": "Stop a living session: pause the society and close the session, ``stopped_by_person``. A\nsession that already closed is answered as it closed.",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "session_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Session Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Stop Living Session World Versions  Version Id  Society Control Sessions  Session Id  Stop Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/comparisons",
    "method": "get",
    "id": "society_comparisons_world_versions__version_id__society_comparisons_get",
    "title": "Society Comparisons",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Society Comparisons World Versions  Version Id  Society Comparisons Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/comparisons",
    "method": "post",
    "id": "start_society_comparison_world_versions__version_id__society_comparisons_post",
    "title": "Start Society Comparison",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ComparisonStartBody"
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
              "title": "Response Start Society Comparison World Versions  Version Id  Society Comparisons Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/comparisons/plan",
    "method": "get",
    "id": "plan_society_comparison_world_versions__version_id__society_comparisons_plan_get",
    "title": "Plan Society Comparison",
    "description": "What a start would do, writing nothing: the roles, groups, models and development seeds\nthis server offers a comparison of the version's society, the windows it may run over (an\nhour, or a day where the society's engine keeps one and a reading line was measured for its\nday), and, for the selection the query names (``model`` as ``<provider>/<model id>``, once or\ntwice; ``person`` for a named group; ``input_seq`` for an earlier stored input to freeze;\n``bound_usd`` for the bound a start would state; ``window`` for the window, an hour unless\nnamed), the runs it plans, the input it freezes, the most it can cost and what one like it\ntypically cost, with the most one decided person's run can ask and call, each model's\nreservation for one ask and the most its asking can take, or the refusal a start of it would\nmeet, by the same predicates a start's allowance and grant checks read\n(``Services.allowance_refusal``, ``Services.bound_room_refusal``). Without a bound, the grant\nis judged on the calls the selection can make alone.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "role",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 63
            },
            {
              "type": "null"
            }
          ],
          "title": "Role"
        }
      },
      {
        "name": "group",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "enum": [
                "everyone",
                "owner_choice",
                "named"
              ],
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Group"
        }
      },
      {
        "name": "choice_seq",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "minimum": 1
            },
            {
              "type": "null"
            }
          ],
          "title": "Choice Seq"
        }
      },
      {
        "name": "person",
        "in": "query",
        "required": false,
        "schema": {
          "type": "array",
          "items": {
            "type": "string",
            "format": "uuid"
          },
          "maxItems": 512,
          "default": [],
          "title": "Person"
        }
      },
      {
        "name": "model",
        "in": "query",
        "required": false,
        "schema": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "maxItems": 2,
          "default": [],
          "title": "Model"
        }
      },
      {
        "name": "control",
        "in": "query",
        "required": false,
        "schema": {
          "type": "boolean",
          "default": false,
          "title": "Control"
        }
      },
      {
        "name": "seeds",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 64,
          "minimum": 1,
          "default": 1,
          "title": "Seeds"
        }
      },
      {
        "name": "input_seq",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "minimum": 1
            },
            {
              "type": "null"
            }
          ],
          "title": "Input Seq"
        }
      },
      {
        "name": "bound_usd",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[0-9]{1,6}(\\.[0-9]{1,8})?$"
            },
            {
              "type": "null"
            }
          ],
          "title": "Bound Usd"
        }
      },
      {
        "name": "window",
        "in": "query",
        "required": false,
        "schema": {
          "enum": [
            "hour",
            "day"
          ],
          "type": "string",
          "default": "hour",
          "title": "Window"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Plan Society Comparison World Versions  Version Id  Society Comparisons Plan Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/comparisons/{comparison_id}",
    "method": "get",
    "id": "society_comparison_world_versions__version_id__society_comparisons__comparison_id__get",
    "title": "Society Comparison",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Society Comparison World Versions  Version Id  Society Comparisons  Comparison Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}",
    "method": "get",
    "id": "society_comparison_run_world_versions__version_id__society_comparisons__comparison_id__runs__run_id__get",
    "title": "Society Comparison Run",
    "description": "One run as the page draws it. A day's run is read one hour at a time (``hour``, its first\nwhere none is named): the hour replayed from the state the hour before it sealed, its genesis\nfor the first, from the receipts the hour recorded, held to the hour's record, and drawn as an\nhour's run is, with where the hour lies in the day. An hour the window does not hold is\nrefused (``hour_not_in_window``), and one the run has not sealed is ``run_not_completed``.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
        }
      },
      {
        "name": "run_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Run Id"
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
        "name": "hour",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "minimum": 0
            },
            {
              "type": "null"
            }
          ],
          "title": "Hour"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Society Comparison Run World Versions  Version Id  Society Comparisons  Comparison Id  Runs  Run Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}/day",
    "method": "get",
    "id": "society_comparison_run_day_world_versions__version_id__society_comparisons__comparison_id__runs__run_id__day_get",
    "title": "Society Comparison Run Day",
    "description": "A day's run over every hour it sealed, from its sealed hours alone, with no replay: each\nhour's terms for the group and what its asking took, and every person's minutes, coded as the\nrun's drawing classifies a minute, with the activities and places the codes name, so two runs'\ndays can be set side by side minute by minute without drawing every hour. Answered for a run\nstill playing or one that failed too, over the hours it sealed; the inputs' rights are asked\nbefore anything drawn from them is answered. A comparison whose window is an hour is\n``comparison_not_a_day``.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
        }
      },
      {
        "name": "run_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Run Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Society Comparison Run Day World Versions  Version Id  Society Comparisons  Comparison Id  Runs  Run Id  Day Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/comparisons/{comparison_id}/cancel",
    "method": "post",
    "id": "cancel_society_comparison_world_versions__version_id__society_comparisons__comparison_id__cancel_post",
    "title": "Cancel Society Comparison",
    "description": "Cancel a comparison started from the application, once. A start no host holds closes now:\nevery run left open fails as ``comparison_cancelled``, asking nothing, and what a host whose\nlease ran out may have spent is presumed as a takeover presumes it. A start a host is playing\nis closed by that host before its next dispatch. Its durable bounds, where it spends under\nthem, are closed once the cancellation is recorded, so the authority refuses an ask a host\nsends after it. A repeated cancel changes nothing, and a finished start keeps its own\nclosing. Answers the comparison as the listing states it.",
    "group": "society",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Cancel Society Comparison World Versions  Version Id  Society Comparisons  Comparison Id  Cancel Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/models",
    "method": "get",
    "id": "society_models_world_versions__version_id__society_models_get",
    "title": "Society Models",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Society Models World Versions  Version Id  Society Models Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/models",
    "method": "post",
    "id": "choose_society_model_world_versions__version_id__society_models_post",
    "title": "Choose Society Model",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelChoiceBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Choose Society Model World Versions  Version Id  Society Models Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/play",
    "method": "post",
    "id": "start_playing_world_versions__version_id__society_play_post",
    "title": "Start Playing",
    "description": "Start playing one being: a choice naming it with the person who plays, the session's\naccount. Refused by name where the society is not a society of things\n(``engine_takes_no_play``), another person plays it (``being_played``), its own program\ndecides for it (``decided_from_outside``) or its kind lets no person decide for it\n(``decider_not_allowed``).",
    "group": "society",
    "permission": {
      "requires": [
        "being.act",
        "world.read"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PlayBody"
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
              "title": "Response Start Playing World Versions  Version Id  Society Play Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/play/{subject_id}/give-back",
    "method": "post",
    "id": "give_back_world_versions__version_id__society_play__subject_id__give_back_post",
    "title": "Give Back",
    "description": "Give the being back: it is decided for again as it was before the play began. Refused\n``not_played`` where the reader does not play it.",
    "group": "society",
    "permission": {
      "requires": [
        "being.act",
        "world.read"
      ]
    },
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
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/GiveBackBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Give Back World Versions  Version Id  Society Play  Subject Id  Give Back Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/play/{subject_id}/turn",
    "method": "get",
    "id": "turn_world_versions__version_id__society_play__subject_id__turn_get",
    "title": "Turn",
    "description": "What the being is offered in the minute to come, read from the society's stored state as\nits request will offer it: each option's label, kind, the place or being it names and whether\nit takes a line; the line's bound; whether the reader plays it; how many quiet minutes are\nleft before the being is given back; and when the minute is due.",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Turn World Versions  Version Id  Society Play  Subject Id  Turn Get"
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
  },
  {
    "path": "/world/versions/{version_id}/society/play/{subject_id}/answer",
    "method": "post",
    "id": "answer_world_versions__version_id__society_play__subject_id__answer_post",
    "title": "Answer",
    "description": "The reader's answer for the being they play, for the minute ``base_tick``: one option the\nminute offers, by its label, and its line where it says something or the spot it walks to\n(``point``) where it walks to one the reader chooses. Checked as any decider's answer is, its\nline read in Unicode normal form C and trimmed first, and kept as the latest for that minute;\nthe minute takes the latest. Refused ``minute_passed`` (409, with the current minute) where\nthat minute has been played or has taken the being's answer already, ``not_played`` where the\nreader does not play the being, ``too_many_answers`` (429, with ``Retry-After`` where the\nsociety plays) past twelve answers a minute, and by the check that fails.",
    "group": "society",
    "permission": {
      "requires": [
        "being.act",
        "world.read"
      ]
    },
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
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PlayAnswerBody"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Answer World Versions  Version Id  Society Play  Subject Id  Answer Post"
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
  },
  {
    "path": "/world/versions/{version_id}/society/district",
    "method": "get",
    "id": "society_district_world_versions__version_id__society_district_get",
    "title": "Society District",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SocietyDistrictView"
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
  },
  {
    "path": "/world/versions/{version_id}/society/experiments",
    "method": "post",
    "id": "prepare_experiment_world_versions__version_id__society_experiments_post",
    "title": "Prepare Experiment",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PrepareExperimentBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ExperimentDefinitionResponse"
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
  },
  {
    "path": "/world/versions/{version_id}/society/experiments/{experiment_id}",
    "method": "get",
    "id": "read_experiment_world_versions__version_id__society_experiments__experiment_id__get",
    "title": "Read Experiment",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "experiment_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Experiment Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ExperimentDefinitionResponse"
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
  },
  {
    "path": "/world/versions/{version_id}/society/experiments/{experiment_id}/attempts",
    "method": "post",
    "id": "reserve_attempt_world_versions__version_id__society_experiments__experiment_id__attempts_post",
    "title": "Reserve Attempt",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "experiment_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Experiment Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ReserveAttemptBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/AttemptResponse"
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
  },
  {
    "path": "/world/versions/{version_id}/society/experiments/{experiment_id}/attempts/{attempt_id}",
    "method": "get",
    "id": "read_attempt_world_versions__version_id__society_experiments__experiment_id__attempts__attempt_id__get",
    "title": "Read Attempt",
    "description": "",
    "group": "society",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "experiment_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Experiment Id"
        }
      },
      {
        "name": "attempt_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Attempt Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/AttemptResponse"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance",
    "method": "get",
    "id": "read_world_versions__version_id__characters__subject_kind___subject_id__appearance_get",
    "title": "Read",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Read World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Get"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance",
    "method": "put",
    "id": "save_world_versions__version_id__characters__subject_kind___subject_id__appearance_put",
    "title": "Save",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SaveBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Save World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Put"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/reset",
    "method": "post",
    "id": "reset_world_versions__version_id__characters__subject_kind___subject_id__appearance_reset_post",
    "title": "Reset",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ResetBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Reset World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Reset Post"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/history",
    "method": "get",
    "id": "history_world_versions__version_id__characters__subject_kind___subject_id__appearance_history_get",
    "title": "History",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
        }
      },
      {
        "name": "before_revision",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "minimum": 1
            },
            {
              "type": "null"
            }
          ],
          "title": "Before Revision"
        }
      },
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 100,
          "minimum": 1,
          "default": 50,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response History World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance History Get"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/families",
    "method": "get",
    "id": "families_world_versions__version_id__characters__subject_kind___subject_id__appearance_families_get",
    "title": "Families",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Families World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Families Get"
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
  },
  {
    "path": "/world/character-catalogs",
    "method": "get",
    "id": "character_catalogs_world_character_catalogs_get",
    "title": "The character catalogs this host serves: each publication's identity and state.",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Character Catalogs World Character Catalogs Get"
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
  },
  {
    "path": "/world/character-catalogs/{catalog_sha256}",
    "method": "get",
    "id": "character_catalog_world_character_catalogs__catalog_sha256__get",
    "title": "One published character catalog, as the canonical document its digest names.",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "catalog_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Catalog Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Character Catalog World Character Catalogs  Catalog Sha256  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/preparations",
    "method": "post",
    "id": "request_preparation_world_versions__version_id__characters__subject_kind___subject_id__appearance_preparations_post",
    "title": "Prepare a body for a recipe over a parametric family, or answer the one prepared.",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PreparationBody"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Request Preparation World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Preparations Post"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/preparations/{preparation_id}",
    "method": "get",
    "id": "read_preparation_world_versions__version_id__characters__subject_kind___subject_id__appearance_preparations__preparation_id__get",
    "title": "One character body preparation: its state, its body once prepared, or its failure.",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
        }
      },
      {
        "name": "preparation_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Preparation Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Read Preparation World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Preparations  Preparation Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/preparations/{preparation_id}/cancel",
    "method": "post",
    "id": "cancel_preparation_world_versions__version_id__characters__subject_kind___subject_id__appearance_preparations__preparation_id__cancel_post",
    "title": "Stop a character body preparation that has not finished.",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
        }
      },
      {
        "name": "preparation_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Preparation Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Cancel Preparation World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Preparations  Preparation Id  Cancel Post"
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
  },
  {
    "path": "/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance/preparations/{preparation_id}/bytes",
    "method": "get",
    "id": "read_preparation_bytes_world_versions__version_id__characters__subject_kind___subject_id__appearance_preparations__preparation_id__bytes_get",
    "title": "A prepared character body's bytes, while the family it was prepared over is served.",
    "description": "",
    "group": "character-appearance",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "subject_kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "avatar",
            "synthetic-inhabitant"
          ],
          "type": "string",
          "title": "Subject Kind"
        }
      },
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
        }
      },
      {
        "name": "preparation_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Preparation Id"
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
        "name": "society_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Society Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Read Preparation Bytes World Versions  Version Id  Characters  Subject Kind   Subject Id  Appearance Preparations  Preparation Id  Bytes Get"
            }
          },
          "model/gltf-binary": {}
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
  },
  {
    "path": "/materials/makers",
    "method": "get",
    "id": "makers_materials_makers_get",
    "title": "Makers",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/library",
    "method": "get",
    "id": "library_materials_library_get",
    "title": "Library",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/recipes",
    "method": "get",
    "id": "list_recipes_materials_recipes_get",
    "title": "List Recipes",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/recipes",
    "method": "post",
    "id": "create_recipe_materials_recipes_post",
    "title": "Create Recipe",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RecipeBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/recipes/{recipe_id}",
    "method": "get",
    "id": "read_recipe_materials_recipes__recipe_id__get",
    "title": "Read Recipe",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "recipe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Recipe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/recipes/{recipe_id}/withdraw",
    "method": "post",
    "id": "withdraw_recipe_materials_recipes__recipe_id__withdraw_post",
    "title": "Withdraw Recipe",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "recipe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Recipe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/recipes/{recipe_id}/bake",
    "method": "post",
    "id": "request_bake_materials_recipes__recipe_id__bake_post",
    "title": "Request Bake",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "recipe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Recipe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/recipes/{recipe_id}/bake",
    "method": "get",
    "id": "read_bake_materials_recipes__recipe_id__bake_get",
    "title": "Read Bake",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "recipe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Recipe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/materials/recipes/{recipe_id}/bake/bytes",
    "method": "get",
    "id": "read_bake_bytes_materials_recipes__recipe_id__bake_bytes_get",
    "title": "Read Bake Bytes",
    "description": "",
    "group": "materials",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "recipe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Recipe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models",
    "method": "post",
    "id": "admit_model_models_post",
    "title": "Admit Model",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelRecordBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models",
    "method": "get",
    "id": "discover_models_models_get",
    "title": "Discover Models",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Discover Models Models Get"
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
  },
  {
    "path": "/models/remove",
    "method": "post",
    "id": "remove_admitted_model_models_remove_post",
    "title": "Remove Admitted Model",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelRecordBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models/probes/prepare",
    "method": "post",
    "id": "prepare_model_probe_models_probes_prepare_post",
    "title": "Prepare Model Probe",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelRecordBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models/probes/{probe_id}/start",
    "method": "post",
    "id": "start_model_probe_models_probes__probe_id__start_post",
    "title": "Start Model Probe",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "probe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Probe Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProbeStartBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models/probes/{probe_id}",
    "method": "get",
    "id": "read_model_probe_models_probes__probe_id__get",
    "title": "Read Model Probe",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "probe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Probe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models/probes/{probe_id}/replay",
    "method": "post",
    "id": "replay_model_probe_models_probes__probe_id__replay_post",
    "title": "Replay Model Probe",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "probe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Probe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models/probes/{probe_id}/cancel",
    "method": "post",
    "id": "cancel_model_probe_models_probes__probe_id__cancel_post",
    "title": "Cancel Model Probe",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "probe_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Probe Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/models/preflight",
    "method": "post",
    "id": "preflight_model_models_preflight_post",
    "title": "Preflight Model",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelPreflightBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Preflight Model Models Preflight Post"
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
  },
  {
    "path": "/models/bindings/{binding_sha256}",
    "method": "get",
    "id": "read_model_binding_models_bindings__binding_sha256__get",
    "title": "Read Model Binding",
    "description": "",
    "group": "models",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "binding_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Binding Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-assets",
    "method": "post",
    "id": "admit_workspace_asset_workspace_assets_post",
    "title": "Admit Workspace Asset",
    "description": "",
    "group": "workspace-assets",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "multipart/form-data": {
          "schema": {
            "type": "object",
            "required": [
              "declaration",
              "content"
            ],
            "properties": {
              "declaration": {
                "type": "string",
                "maxLength": 65536,
                "title": "Declaration"
              },
              "content": {
                "type": "string",
                "contentMediaType": "application/octet-stream",
                "title": "Content"
              }
            }
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-assets",
    "method": "get",
    "id": "list_workspace_assets_workspace_assets_get",
    "title": "List Workspace Assets",
    "description": "",
    "group": "workspace-assets",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-assets/{asset_id}",
    "method": "get",
    "id": "read_workspace_asset_workspace_assets__asset_id__get",
    "title": "Read Workspace Asset",
    "description": "",
    "group": "workspace-assets",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "asset_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Asset Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-assets/{asset_id}/preparation",
    "method": "post",
    "id": "request_workspace_preparation_workspace_assets__asset_id__preparation_post",
    "title": "Request Workspace Preparation",
    "description": "",
    "group": "workspace-assets",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
    "parameters": [
      {
        "name": "asset_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Asset Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-assets/{asset_id}/preparation/cancel",
    "method": "post",
    "id": "cancel_workspace_preparation_workspace_assets__asset_id__preparation_cancel_post",
    "title": "Cancel Workspace Preparation",
    "description": "",
    "group": "workspace-assets",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
    "parameters": [
      {
        "name": "asset_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Asset Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-assets/{asset_id}/withdraw",
    "method": "post",
    "id": "withdraw_workspace_asset_workspace_assets__asset_id__withdraw_post",
    "title": "Withdraw Workspace Asset",
    "description": "",
    "group": "workspace-assets",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
    "parameters": [
      {
        "name": "asset_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Asset Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-assets/{asset_id}/prepared/bytes",
    "method": "get",
    "id": "read_workspace_asset_prepared_bytes_workspace_assets__asset_id__prepared_bytes_get",
    "title": "Read Workspace Asset Prepared Bytes",
    "description": "",
    "group": "workspace-assets",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "asset_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Asset Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          },
          "model/gltf-binary": {}
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
  },
  {
    "path": "/workspace-style-packs",
    "method": "post",
    "id": "admit_workspace_style_pack_workspace_style_packs_post",
    "title": "Admit Workspace Style Pack",
    "description": "",
    "group": "workspace-style-packs",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "multipart/form-data": {
          "schema": {
            "type": "object",
            "required": [
              "declaration",
              "manifest"
            ],
            "properties": {
              "declaration": {
                "type": "string",
                "maxLength": 65536
              },
              "manifest": {
                "type": "string",
                "maxLength": 262144
              }
            },
            "additionalProperties": {
              "type": "string",
              "contentMediaType": "application/octet-stream"
            }
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-style-packs",
    "method": "get",
    "id": "list_workspace_style_packs_workspace_style_packs_get",
    "title": "This workspace's own style pack versions and their checks.",
    "description": "",
    "group": "workspace-style-packs",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-style-packs/{manifest_sha256}",
    "method": "get",
    "id": "read_workspace_style_pack_workspace_style_packs__manifest_sha256__get",
    "title": "One version of a workspace style pack, and its check.",
    "description": "",
    "group": "workspace-style-packs",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "manifest_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Manifest Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-style-packs/{manifest_sha256}/files/{content_sha256}",
    "method": "get",
    "id": "read_workspace_style_pack_file_workspace_style_packs__manifest_sha256__files__content_sha256__get",
    "title": "One file of a ready workspace style pack version, after the final read check.",
    "description": "",
    "group": "workspace-style-packs",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "manifest_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Manifest Sha256"
        }
      },
      {
        "name": "content_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Content Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          },
          "model/gltf-binary": {},
          "image/png": {}
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
  },
  {
    "path": "/workspace-style-packs/{manifest_sha256}/withdraw",
    "method": "post",
    "id": "withdraw_workspace_style_pack_workspace_style_packs__manifest_sha256__withdraw_post",
    "title": "Withdraw a version of a workspace style pack for good.",
    "description": "",
    "group": "workspace-style-packs",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
    "parameters": [
      {
        "name": "manifest_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Manifest Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/workspace-style-packs/{manifest_sha256}/archive",
    "method": "get",
    "id": "read_workspace_style_pack_archive_workspace_style_packs__manifest_sha256__archive_get",
    "title": "A ready workspace style pack version as one uncompressed tar archive.",
    "description": "",
    "group": "workspace-style-packs",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "manifest_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Manifest Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          },
          "application/x-tar": {}
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
  },
  {
    "path": "/workspace-style-packs/{manifest_sha256}/publish-request",
    "method": "post",
    "id": "request_workspace_style_pack_publication_workspace_style_packs__manifest_sha256__publish_request_post",
    "title": "Ask for a ready version of your own style pack to join the shared library.",
    "description": "",
    "group": "workspace-style-packs",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
    "parameters": [
      {
        "name": "manifest_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Manifest Sha256"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PublishRequest"
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/tiles",
    "method": "get",
    "id": "list_tiles_tiles_get",
    "title": "List Tiles",
    "description": "",
    "group": "tiles",
    "permission": {
      "requires": [
        "tiles.materialise"
      ]
    },
    "parameters": [
      {
        "name": "city_seed",
        "in": "query",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "City Seed"
        }
      },
      {
        "name": "lod",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "maximum": 64,
              "minimum": 0
            },
            {
              "type": "null"
            }
          ],
          "title": "Lod"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/tiles/traffic",
    "method": "get",
    "id": "tile_traffic_tiles_traffic_get",
    "title": "The vehicles driving a stored generated city's streets, second by second, to draw.",
    "description": "",
    "group": "tiles",
    "permission": {
      "requires": [
        "tiles.materialise"
      ]
    },
    "parameters": [
      {
        "name": "world_seed",
        "in": "query",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "World Seed"
        }
      },
      {
        "name": "from_second",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "From Second"
        }
      },
      {
        "name": "seconds",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "default": 60,
          "title": "Seconds"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/tiles/{baked_tile_id}/bytes",
    "method": "get",
    "id": "read_tile_bytes_tiles__baked_tile_id__bytes_get",
    "title": "Read Tile Bytes",
    "description": "",
    "group": "tiles",
    "permission": {
      "requires": [
        "tiles.materialise"
      ]
    },
    "parameters": [
      {
        "name": "baked_tile_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Baked Tile Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/companion/memory/recent",
    "method": "get",
    "id": "recent_companion_memory_recent_get",
    "title": "What this Companion asked you, what it answered, and what you told it to leave alone.",
    "description": "",
    "group": "companion",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 200,
          "minimum": 1,
          "default": 50,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/MemoryView"
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
  },
  {
    "path": "/companion/memory/answers",
    "method": "post",
    "id": "record_answer_companion_memory_answers_post",
    "title": "Keep an answer that has already been shown, so a reload does not ask again.",
    "description": "",
    "group": "companion",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/AnswerBody"
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
              "$ref": "#/components/schemas/exulanica__api__routes__companion__AnswerView"
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
  },
  {
    "path": "/companion/memory/escapes",
    "method": "post",
    "id": "record_escape_companion_memory_escapes_post",
    "title": "Keep an escape, so its cooldown outlives the page it was taken on.",
    "description": "",
    "group": "companion",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/EscapeBody"
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
              "$ref": "#/components/schemas/EscapeView"
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
  },
  {
    "path": "/companion/memory/answers/{answer_id}/corrections",
    "method": "post",
    "id": "correct_answer_companion_memory_answers__answer_id__corrections_post",
    "title": "Say what the answer should have been. The old one is superseded, never rewritten.",
    "description": "",
    "group": "companion",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
    "parameters": [
      {
        "name": "answer_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Answer Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CorrectionBody"
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
              "$ref": "#/components/schemas/exulanica__api__routes__companion__AnswerView"
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
  },
  {
    "path": "/companion/memory/answers/{answer_id}",
    "method": "delete",
    "id": "delete_answer_companion_memory_answers__answer_id__delete",
    "title": "Delete one memory, and every correction of it, for good.",
    "description": "",
    "group": "companion",
    "permission": {
      "requires": [
        "deletion.write"
      ]
    },
    "parameters": [
      {
        "name": "answer_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Answer Id"
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/environment-resources/places",
    "method": "post",
    "id": "declare_place_environment_resources_places_post",
    "title": "Declare Place",
    "description": "Create a place whose frame a provider documented, so a source can be admitted to it.\n\nThe frame this records is **declared, never measured**: the response says so in\n``frame_authority`` and the receipt repeats it, because a reader that could not tell a\ndeclaration from a recovered frame would be told a measurement had been made where none was.\nCreating a place grants no right to any source; rights are resolved per admission.",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DeclaredPlaceFrame"
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/environment-resources/places/{place_id}",
    "method": "get",
    "id": "declared_place_environment_resources_places__place_id__get",
    "title": "Declared Place",
    "description": "What a place declared about its frame, for a reader holding only its identifier.\n\nRegistered before the ``{kind}/{resource_id}`` reads below, so ``places`` resolves here\nrather than as a resource kind. A caller that reached a place through a Selection row or a\ncomposed instance can ask this what kind of frame it has, which is the only way the\ndeclared-never-measured distinction survives past the request that created the place.",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "place_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Place Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/environment-resources/sources",
    "method": "post",
    "id": "admit_source_environment_resources_sources_post",
    "title": "Admit Source",
    "description": "",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SourceAdmission"
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/environment-resources/assets",
    "method": "post",
    "id": "register_derived_asset_environment_resources_assets_post",
    "title": "Register Derived Asset",
    "description": "Register derived bytes against an admitted source, so a feature index can name them.\n\nThe admission stays authoritative. A withdrawn source, or one whose rights do not permit\nwhat the derivation declares, refuses here exactly as it refuses everywhere else, and the\nderived row can never widen its source's rights.",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DerivedEnvironmentAsset"
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/environment-resources/sources/{admission_id}/feature-indexes",
    "method": "post",
    "id": "publish_feature_index_environment_resources_sources__admission_id__feature_indexes_post",
    "title": "Publish Feature Index",
    "description": "",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
    "parameters": [
      {
        "name": "admission_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Admission Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/FeatureIndexPublication"
          }
        }
      }
    },
    "responses": {
      "201": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/environment-resources/sources/{admission_id}/features",
    "method": "get",
    "id": "features_environment_resources_sources__admission_id__features_get",
    "title": "Features",
    "description": "",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "admission_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Admission Id"
        }
      },
      {
        "name": "feature_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            {
              "type": "null"
            }
          ],
          "title": "Feature Id"
        }
      },
      {
        "name": "kind",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "$ref": "#/components/schemas/EnvironmentFeatureKind"
            },
            {
              "type": "null"
            }
          ],
          "title": "Kind"
        }
      },
      {
        "name": "bbox",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "array",
              "items": {
                "type": "integer"
              },
              "minItems": 4,
              "maxItems": 6
            },
            {
              "type": "null"
            }
          ],
          "title": "Bbox"
        }
      },
      {
        "name": "label",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 512
            },
            {
              "type": "null"
            }
          ],
          "title": "Label"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/environment-resources/{kind}/{resource_id}",
    "method": "get",
    "id": "metadata_environment_resources__kind___resource_id__get",
    "title": "Metadata",
    "description": "",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "source",
            "asset"
          ],
          "type": "string",
          "title": "Kind"
        }
      },
      {
        "name": "resource_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Resource Id"
        }
      },
      {
        "name": "operation",
        "in": "query",
        "required": true,
        "schema": {
          "$ref": "#/components/schemas/EnvironmentOperation"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/environment-resources/{kind}/{resource_id}/bytes",
    "method": "get",
    "id": "resource_bytes_environment_resources__kind___resource_id__bytes_get",
    "title": "Resource Bytes",
    "description": "",
    "group": "environment-resources",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "kind",
        "in": "path",
        "required": true,
        "schema": {
          "enum": [
            "source",
            "asset"
          ],
          "type": "string",
          "title": "Kind"
        }
      },
      {
        "name": "resource_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Resource Id"
        }
      },
      {
        "name": "operation",
        "in": "query",
        "required": true,
        "schema": {
          "$ref": "#/components/schemas/EnvironmentOperation"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/identity/name",
    "method": "post",
    "id": "name_identity_name_post",
    "title": "The account holder says who somebody is.",
    "description": "",
    "group": "identity",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/NameRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/NamedView"
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
  },
  {
    "path": "/identity/rename",
    "method": "post",
    "id": "rename_identity_rename_post",
    "title": "The account holder corrects a name they gave.",
    "description": "One transaction, two writes, and the second one is not optional.\n\nMigration 0006 makes ``name_is`` supersede, so the new claim retires the old one inside the\ninsert, and 0002's cache trigger nulls ``entity.display_name`` on that retirement because the\nreplacement row does not exist yet. ``rename_entity`` writes the cache back in the same\ntransaction; a caller that wrote only the assertion would leave the person unnamed.",
    "group": "identity",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RenameRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": {
                "type": "string"
              },
              "title": "Response Rename Identity Rename Post"
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
  },
  {
    "path": "/identity/confirm",
    "method": "post",
    "id": "confirm_identity_confirm_post",
    "title": "This occurrence is that person.",
    "description": "",
    "group": "identity",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/LinkRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": {
                "type": "string"
              },
              "title": "Response Confirm Identity Confirm Post"
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
  },
  {
    "path": "/identity/reject",
    "method": "post",
    "id": "reject_identity_reject_post",
    "title": "No, that is not them. Remembered against the evidence.",
    "description": "",
    "group": "identity",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/LinkRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": {
                "type": "string"
              },
              "title": "Response Reject Identity Reject Post"
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
  },
  {
    "path": "/identity/revoke",
    "method": "post",
    "id": "revoke_identity_revoke_post",
    "title": "Withdraw a confirmed link.",
    "description": "",
    "group": "identity",
    "permission": {
      "requires": [
        "deletion.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RevokeRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/EventView"
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
  },
  {
    "path": "/identity/merge",
    "method": "post",
    "id": "merge_identity_merge_post",
    "title": "Two records of one person become one.",
    "description": "",
    "group": "identity",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/MergeRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/EventView"
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
  },
  {
    "path": "/identity/split",
    "method": "post",
    "id": "split_identity_split_post",
    "title": "These occurrences are somebody else.",
    "description": "",
    "group": "identity",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SplitRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/EventView"
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
  },
  {
    "path": "/identity/undo",
    "method": "post",
    "id": "undo_decision_identity_undo_post",
    "title": "Reverse one identity decision, from what its event recorded.",
    "description": "",
    "group": "identity",
    "permission": {
      "requires": [
        "library.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UndoRequest"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/EventView"
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
  },
  {
    "path": "/identity/events",
    "method": "get",
    "id": "events_identity_events_get",
    "title": "What has been decided, most recent first.",
    "description": "The identity ledger, which is what makes undo exact rather than approximate.",
    "group": "identity",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "default": 50,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "type": "object",
                "additionalProperties": true
              },
              "title": "Response Events Identity Events Get"
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
  },
  {
    "path": "/evidence/{span_id}",
    "method": "get",
    "id": "original_evidence__span_id__get",
    "title": "The original media a citation resolves to.",
    "description": "",
    "group": "evidence",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "span_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Span Id"
        }
      },
      {
        "name": "range",
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
          "title": "Range"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/evidence/{span_id}/masked",
    "method": "get",
    "id": "masked_evidence__span_id__masked_get",
    "title": "The photograph with every unconsented person filled neutral.",
    "description": "The derivative a viewer may see, never the original bytes behind it.\n\nA sibling of the route above rather than a change to it, and the distinction is not cosmetic.\n``GET /evidence/{span_id}`` resolves the exact bytes a citation names, and those bytes are\ninside the span digest: serving something else there would break every archived citation that\nverifies against it. So the original endpoint keeps its meaning and this one exists for the\nworld, which shows photographs to people rather than resolving citations.\n\n**Refuses rather than falling back.** When the photograph contains somebody who has not\nconsented and no masked derivative exists, this returns 409 and no bytes. Serving the original\nwould show exactly the person the derivative exists to hide, on the one path a viewer actually\nlooks at, and it would do it precisely when something upstream had already gone wrong.",
    "group": "evidence",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "span_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Span Id"
        }
      },
      {
        "name": "view_scene",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "View Scene"
        }
      },
      {
        "name": "view_capture",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "View Capture"
        }
      },
      {
        "name": "view_binding",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[0-9a-f]{64}$"
            },
            {
              "type": "null"
            }
          ],
          "title": "View Binding"
        }
      },
      {
        "name": "range",
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
          "title": "Range"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/evidence/{span_id}/region",
    "method": "get",
    "id": "region_evidence__span_id__region_get",
    "title": "The region of the original this span names, as PNG.",
    "description": "A crop, for showing what a citation points at inside a photograph.\n\nNot what the citation resolves to. The address names the original bytes and a region within\nthem; this renders that region so an interface can draw it, and a caller wanting the\nevidence itself asks for the endpoint above.",
    "group": "evidence",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "span_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Span Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/evidence",
    "method": "get",
    "id": "by_uri_evidence_get",
    "title": "The same, addressed by permalink rather than by row id.",
    "description": "Resolve an ``exulanica://`` permalink.\n\nThe permalink is designed to stay valid forever and to parse back to an address with the\nsame digest, which is what lets an archived answer's citation still open. It names a blob\ndirectly, so the workspace check cannot come from the row id and has to be made explicitly:\na span with this digest must exist in the caller's workspace. Without that, a permalink\nwould be a way to read any blob in the database by naming its hash.",
    "group": "evidence",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "uri",
        "in": "query",
        "required": true,
        "schema": {
          "type": "string",
          "title": "Uri"
        }
      },
      {
        "name": "range",
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
          "title": "Range"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/formation",
    "method": "get",
    "id": "batches_formation_get",
    "title": "Watched intakes in this workspace, newest first.",
    "description": "What there is to watch.\n\nFinished batches are listed as well as running ones, because a client that arrived after an\ningest finished should still be able to read what happened rather than find nothing and\nconclude the upload was lost. The stream of a finished batch replays its history and ends,\nwhich is the same code path a live subscriber takes.",
    "group": "formation",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "default": 20,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/BatchRow"
              },
              "title": "Response Batches Formation Get"
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
  },
  {
    "path": "/formation/{batch_id}",
    "method": "get",
    "id": "stream_formation__batch_id__get",
    "title": "Formation progress for one intake batch, as it happens.",
    "description": "Subscribe to a batch.\n\nTwo ways to resume, and both exist for a reason. ``Last-Event-ID`` is what a browser's own\n``EventSource`` sends on an automatic reconnect and the client never has to think about it.\n``since`` is for a client that reconnects deliberately, having held its own token across a\nview change or a reload, which an ``EventSource`` cannot do because it is a new object with\nno memory.\n\nThe header wins when both are present. A browser sends it only when it genuinely has an event\nto resume from, so it is the more recent of the two by construction.",
    "group": "formation",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "batch_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Batch Id"
        }
      },
      {
        "name": "since",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "maxLength": 200
            },
            {
              "type": "null"
            }
          ],
          "title": "Since"
        }
      },
      {
        "name": "last-event-id",
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
          "title": "Last-Event-Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/intake",
    "method": "post",
    "id": "intake_intake_post",
    "title": "Upload photographs. Intake runs now; the model stages are queued.",
    "description": "Read the upload's body, then admit its photographs.\n\nThe route declares no form parameter, so the framework reads none of the body before the app's\ndependencies have authenticated the caller and claimed the workspace's upload share; and it\nopens its connection only once the body is in, so none is held while it arrives.",
    "group": "intake",
    "permission": {
      "requires": [
        "intake.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "multipart/form-data": {
          "schema": {
            "type": "object",
            "required": [
              "files"
            ],
            "properties": {
              "files": {
                "type": "array",
                "items": {
                  "type": "string",
                  "contentMediaType": "application/octet-stream"
                },
                "title": "Files",
                "description": "The photographs to ingest."
              }
            }
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/IntakeAccepted"
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
  },
  {
    "path": "/operations/capacity",
    "method": "get",
    "id": "capacity_operations_capacity_get",
    "title": "How much of each capacity class this API process holds now.",
    "description": "This process's admission limits and counts, and the decode bound's.\n\nCounts for the whole process, never another workspace's id; ``workspace_in_flight`` is the\ncaller's own. This read is itself a request, so the requests class's ``in_flight`` includes it.\nAnother API process keeps counts of its own (``docs/deployment.md`` section 5.4).",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Capacity Operations Capacity Get"
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
  },
  {
    "path": "/operations/installation",
    "method": "get",
    "id": "installation_operations_installation_get",
    "title": "What this installation runs, its identity, and what each component can do now.",
    "description": "The installation facts document, ``exulanica.installation-facts/v1``.\n\nInstallation-wide rather than one workspace's: code revision, image digests, the configuration\nfingerprint, component states and recovery times. None of it is workspace content, and none\nof it is a setting's value. Unauthenticated readiness carries only the component states.",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Installation Operations Installation Get"
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
  },
  {
    "path": "/operations/derivative-jobs",
    "method": "get",
    "id": "jobs_operations_derivative_jobs_get",
    "title": "Measured derivative queue health for this workspace.",
    "description": "",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Jobs Operations Derivative Jobs Get"
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
  },
  {
    "path": "/operations/derivative-jobs/{job_id}",
    "method": "get",
    "id": "job_operations_derivative_jobs__job_id__get",
    "title": "One derivative job's state and progress.",
    "description": "Whether the job is queued, running or finished, and how far it got.\n\n404 ``unknown_reference`` for a job this workspace cannot see, identically to one that never\nexisted. The events route beside this one answers an empty replay for both; this is the read\nthat tells an unknown job from one that has not reported yet.",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
    "parameters": [
      {
        "name": "job_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Job Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Job Operations Derivative Jobs  Job Id  Get"
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
  },
  {
    "path": "/operations/derivative-jobs/{job_id}/events",
    "method": "get",
    "id": "job_events_operations_derivative_jobs__job_id__events_get",
    "title": "Durable delivery replay for one derivative job.",
    "description": "",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
    "parameters": [
      {
        "name": "job_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Job Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "type": "object",
                "additionalProperties": true
              },
              "title": "Response Job Events Operations Derivative Jobs  Job Id  Events Get"
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
  },
  {
    "path": "/operations/reconstruction-scenes",
    "method": "get",
    "id": "reconstruction_scenes_operations_reconstruction_scenes_get",
    "title": "Measured reconstruction dependency and queue health for this workspace.",
    "description": "",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Reconstruction Scenes Operations Reconstruction Scenes Get"
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
  },
  {
    "path": "/operations/reconstruction-scenes/{job_id}",
    "method": "get",
    "id": "reconstruction_scene_detail_operations_reconstruction_scenes__job_id__get",
    "title": "Exact inputs, state and outputs for one reconstruction build.",
    "description": "",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
    "parameters": [
      {
        "name": "job_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Job Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Reconstruction Scene Detail Operations Reconstruction Scenes  Job Id  Get"
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
  },
  {
    "path": "/operations/reconstruction-scenes/{job_id}/retry",
    "method": "post",
    "id": "retry_reconstruction_scene_operations_reconstruction_scenes__job_id__retry_post",
    "title": "Make one retryable failed reconstruction build immediately eligible.",
    "description": "",
    "group": "operations",
    "permission": {
      "requires": [
        "operations.write"
      ]
    },
    "parameters": [
      {
        "name": "job_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Job Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": {
                "type": "string"
              },
              "title": "Response Retry Reconstruction Scene Operations Reconstruction Scenes  Job Id  Retry Post"
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
  },
  {
    "path": "/spending",
    "method": "get",
    "id": "spending_spending_get",
    "title": "What this workspace may still spend on hosted models, by provider.",
    "description": "",
    "group": "spending",
    "permission": {
      "requires": [
        "operations.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Spending Spending Get"
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
  },
  {
    "path": "/person-regions/{capture_id}",
    "method": "get",
    "id": "regions_person_regions__capture_id__get",
    "title": "Who is in this photograph, and their state.",
    "description": "",
    "group": "person-regions",
    "permission": {
      "requires": [
        "consent.read"
      ]
    },
    "parameters": [
      {
        "name": "capture_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Regions Person Regions  Capture Id  Get"
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
  },
  {
    "path": "/person-regions/{capture_id}/edits",
    "method": "post",
    "id": "edit_regions_person_regions__capture_id__edits_post",
    "title": "Edit Regions",
    "description": "Confirm, correct or delete proposed regions. Each edit is its own receipt.",
    "group": "person-regions",
    "permission": {
      "requires": [
        "consent.write"
      ]
    },
    "parameters": [
      {
        "name": "capture_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Capture Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RegionEdits"
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
              "type": "object",
              "additionalProperties": true,
              "title": "Response Edit Regions Person Regions  Capture Id  Edits Post"
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
  },
  {
    "path": "/person-subjects",
    "method": "post",
    "id": "new_subject_person_subjects_post",
    "title": "New Subject",
    "description": "Create somebody a decision can be about, named or not.",
    "group": "person-regions",
    "permission": {
      "requires": [
        "consent.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/NewSubject"
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
              "type": "object",
              "additionalProperties": true,
              "title": "Response New Subject Person Subjects Post"
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
  },
  {
    "path": "/person-subjects/{subject_id}/consents",
    "method": "post",
    "id": "add_consent_person_subjects__subject_id__consents_post",
    "title": "Add Consent",
    "description": "Record one consent transition, as the account holder and never as the subject.",
    "group": "person-regions",
    "permission": {
      "requires": [
        "consent.write"
      ]
    },
    "parameters": [
      {
        "name": "subject_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Subject Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ConsentDecision"
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
              "type": "object",
              "additionalProperties": true,
              "title": "Response Add Consent Person Subjects  Subject Id  Consents Post"
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
  },
  {
    "path": "/identity/subjects/link",
    "method": "post",
    "id": "link_subject_regions_identity_subjects_link_post",
    "title": "Link Subject Regions",
    "description": "Confirm that regions across photographs show one person, creating one subject if needed.",
    "group": "person-regions",
    "permission": {
      "requires": [
        "consent.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/LinkSubject"
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
              "type": "object",
              "additionalProperties": true,
              "title": "Response Link Subject Regions Identity Subjects Link Post"
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
  },
  {
    "path": "/identity/subjects/unlink",
    "method": "post",
    "id": "unlink_subject_regions_identity_subjects_unlink_post",
    "title": "Unlink Subject Regions",
    "description": "Withdraw region-to-subject links, retaining every earlier edit and consent receipt.",
    "group": "person-regions",
    "permission": {
      "requires": [
        "consent.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UnlinkSubject"
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
              "type": "object",
              "additionalProperties": true,
              "title": "Response Unlink Subject Regions Identity Subjects Unlink Post"
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
  },
  {
    "path": "/personal-admission",
    "method": "post",
    "id": "admit_personal_personal_admission_post",
    "title": "Admit Personal",
    "description": "Record receipts for the exact captures returned by upload, then queue observation.",
    "group": "personal-admission",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PersonalBatch"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Admit Personal Personal Admission Post"
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
  },
  {
    "path": "/personal-admission",
    "method": "get",
    "id": "personal_status_personal_admission_get",
    "title": "Personal Status",
    "description": "",
    "group": "personal-admission",
    "permission": {
      "requires": [
        "admission.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Personal Status Personal Admission Get"
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
  },
  {
    "path": "/personal-admission/model-rights/{right_id}/withdraw",
    "method": "post",
    "id": "withdraw_right_personal_admission_model_rights__right_id__withdraw_post",
    "title": "Withdraw Right",
    "description": "End a model right now, and answer with that right. Final, and idempotent: a second\nwithdrawal of the same right changes nothing.\n\nAnother workspace's right is answered exactly as an id nobody granted. A picture's reading\nright is stopped only by the person who granted it or an owner of the workspace; anyone else\nis answered as for an id nobody granted. Stopping it ends, in this one transaction, every\nreading right not yet withdrawn that its grantor holds on that picture, so nothing more of it\nis sent whichever of them a request would have used; stopping it again ends only those granted\nat or before its own stop, never a consent given since.",
    "group": "personal-admission",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
    "parameters": [
      {
        "name": "right_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Right Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Withdraw Right Personal Admission Model Rights  Right Id  Withdraw Post"
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
  },
  {
    "path": "/place-name-rights",
    "method": "get",
    "id": "every_place_place_name_rights_get",
    "title": "Every place whose name has a decision, and each use.",
    "description": "",
    "group": "place-name-rights",
    "permission": {
      "requires": [
        "consent.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Every Place Place Name Rights Get"
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
  },
  {
    "path": "/place-name-rights/{entity_id}",
    "method": "get",
    "id": "one_place_place_name_rights__entity_id__get",
    "title": "Where one place's name may go, and why not.",
    "description": "",
    "group": "place-name-rights",
    "permission": {
      "requires": [
        "consent.read"
      ]
    },
    "parameters": [
      {
        "name": "entity_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entity Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response One Place Place Name Rights  Entity Id  Get"
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
  },
  {
    "path": "/place-name-rights/{entity_id}/grants",
    "method": "post",
    "id": "allow_place_name_rights__entity_id__grants_post",
    "title": "Allow",
    "description": "Allow this place's name to go to every model of one use, against the notice shown.",
    "group": "place-name-rights",
    "permission": {
      "requires": [
        "consent.write"
      ]
    },
    "parameters": [
      {
        "name": "entity_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entity Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PlaceNameAllowRequest"
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
              "title": "Response Allow Place Name Rights  Entity Id  Grants Post"
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
  },
  {
    "path": "/place-name-rights/{entity_id}/withdrawals",
    "method": "post",
    "id": "stop_place_name_rights__entity_id__withdrawals_post",
    "title": "Stop",
    "description": "Stop this place's name going to any model of one use, from the next request on.",
    "group": "place-name-rights",
    "permission": {
      "requires": [
        "consent.write"
      ]
    },
    "parameters": [
      {
        "name": "entity_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entity Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PlaceNameStopRequest"
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
              "title": "Response Stop Place Name Rights  Entity Id  Withdrawals Post"
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
  },
  {
    "path": "/operations/reconstruction-admission",
    "method": "post",
    "id": "admit_benchmark_operations_reconstruction_admission_post",
    "title": "Admit Benchmark",
    "description": "",
    "group": "operations",
    "permission": {
      "requires": [
        "admission.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BenchmarkReview"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Admit Benchmark Operations Reconstruction Admission Post"
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
  },
  {
    "path": "/world/styles/catalog",
    "method": "get",
    "id": "catalog_world_styles_catalog_get",
    "title": "Reviewed world profiles and capability-backed controls.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Catalog World Styles Catalog Get"
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
  },
  {
    "path": "/world/styles/current",
    "method": "get",
    "id": "current_world_styles_current_get",
    "title": "The current immutable style version and protected topology digest.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/StyleStateView"
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
  },
  {
    "path": "/world/styles/versions",
    "method": "get",
    "id": "versions_world_styles_versions_get",
    "title": "Immutable style history, including rollback versions.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/StyleVersionView"
              },
              "title": "Response Versions World Styles Versions Get"
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
  },
  {
    "path": "/world/styles/previews",
    "method": "post",
    "id": "preview_world_styles_previews_post",
    "title": "Validate an isolated appearance preview without changing current state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PreviewBody"
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
              "$ref": "#/components/schemas/PreviewView"
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
  },
  {
    "path": "/world/styles/previews",
    "method": "get",
    "id": "open_previews_world_styles_previews_get",
    "title": "The open appearance previews a page may take up when it opens this world, newest first, each with its proposal.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/OpenPreviewsView"
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
  },
  {
    "path": "/world/styles/proposals/{proposal_id}",
    "method": "get",
    "id": "proposal_world_styles_proposals__proposal_id__get",
    "title": "Inspect one authorised style proposal, provenance, and lifecycle state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "proposal_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Proposal Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/StyleProposalView"
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
  },
  {
    "path": "/world/styles/previews/{preview_id}/apply",
    "method": "post",
    "id": "apply_world_styles_previews__preview_id__apply_post",
    "title": "Atomically apply one still-current preview as a new immutable version.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "preview_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Preview Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ApplyBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/StyleVersionView"
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
  },
  {
    "path": "/world/styles/previews/{preview_id}",
    "method": "delete",
    "id": "discard_world_styles_previews__preview_id__delete",
    "title": "Discard an isolated preview without changing style state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "preview_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Preview Id"
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/world/styles/rollback",
    "method": "post",
    "id": "rollback_world_styles_rollback_post",
    "title": "Restore historical style values by creating a new immutable version.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RollbackBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/StyleVersionView"
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
  },
  {
    "path": "/world/source-media",
    "method": "get",
    "id": "source_media_world_source_media_get",
    "title": "Protected topology source slots with honest availability states.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "topology_digest",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 256
            },
            {
              "type": "null"
            }
          ],
          "title": "Topology Digest"
        }
      },
      {
        "name": "source_snapshot_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Source Snapshot Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/SourceMediaView"
              },
              "title": "Response Source Media World Source Media Get"
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
  },
  {
    "path": "/world/source-media/{source_id}",
    "method": "get",
    "id": "require_source_media_world_source_media__source_id__get",
    "title": "Require one authorised source slot to have available local evidence bytes.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "source_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Source Id"
        }
      },
      {
        "name": "topology_digest",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "minLength": 1,
              "maxLength": 256
            },
            {
              "type": "null"
            }
          ],
          "title": "Topology Digest"
        }
      },
      {
        "name": "source_snapshot_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Source Snapshot Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SourceMediaView"
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
  },
  {
    "path": "/world/assets",
    "method": "get",
    "id": "reviewed_asset_catalog_world_assets_get",
    "title": "The reviewed assets a person may place as objects, with real byte availability and what inhabitants do with each.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/PlaceableAssetView"
              },
              "title": "Response Reviewed Asset Catalog World Assets Get"
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
  },
  {
    "path": "/world/assets/{asset_key}",
    "method": "get",
    "id": "reviewed_asset_world_assets__asset_key__get",
    "title": "One reviewed asset of any kind, whether it may be placed and whether its bytes exist.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "asset_key",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Asset Key"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/PlaceableAssetView"
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
  },
  {
    "path": "/world/assets/{asset_key}/bytes",
    "method": "get",
    "id": "reviewed_asset_bytes_world_assets__asset_key__bytes_get",
    "title": "The reviewed geometry itself. Never a citation target and never evidence.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "asset_key",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Asset Key"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          },
          "model/gltf-binary": {}
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
  },
  {
    "path": "/world/assets/{asset_key}/licence",
    "method": "get",
    "id": "reviewed_asset_licence_world_assets__asset_key__licence_get",
    "title": "The licence text the reviewed bytes are published under.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "asset_key",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Asset Key"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
          },
          "text/plain": {}
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
  },
  {
    "path": "/world/style-packs",
    "method": "get",
    "id": "style_packs_world_style_packs_get",
    "title": "The committed style packs this host serves: each pack's identity, licence and origin.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Style Packs World Style Packs Get"
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
  },
  {
    "path": "/world/style-packs/{content_sha256}",
    "method": "get",
    "id": "style_pack_content_world_style_packs__content_sha256__get",
    "title": "One style pack manifest or listed file, as the bytes its SHA-256 names.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "content_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Content Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Style Pack Content World Style Packs  Content Sha256  Get"
            }
          },
          "model/gltf-binary": {}
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
  },
  {
    "path": "/things/library",
    "method": "get",
    "id": "thing_library_listing_things_library_get",
    "title": "The shipped thing library: every kind, look and look container, by digest.",
    "description": "",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Thing Library Listing Things Library Get"
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
  },
  {
    "path": "/things/library/{content_sha256}",
    "method": "get",
    "id": "thing_library_content_things_library__content_sha256__get",
    "title": "One thing kind, look, the body plans catalog or a look's container, by its SHA-256.",
    "description": "",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "content_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Content Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Thing Library Content Things Library  Content Sha256  Get"
            }
          },
          "model/gltf-binary": {}
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
  },
  {
    "path": "/things/looks/{look_sha256}",
    "method": "get",
    "id": "held_look_things_looks__look_sha256__get",
    "title": "A look this workspace holds, by the SHA-256 of its document.",
    "description": "",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "look_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Look Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Held Look Things Looks  Look Sha256  Get"
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
  },
  {
    "path": "/things/looks/{look_sha256}/container",
    "method": "get",
    "id": "held_look_container_things_looks__look_sha256__container_get",
    "title": "The container of a look this workspace holds, by the SHA-256 of the look.",
    "description": "",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "look_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Look Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Held Look Container Things Looks  Look Sha256  Container Get"
            }
          },
          "model/gltf-binary": {}
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
  },
  {
    "path": "/things/kinds/{kind_sha256}",
    "method": "get",
    "id": "held_kind_things_kinds__kind_sha256__get",
    "title": "A thing kind this workspace holds, by the SHA-256 of its document.",
    "description": "",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "kind_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Kind Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Held Kind Things Kinds  Kind Sha256  Get"
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
  },
  {
    "path": "/things/kinds/{kind_sha256}",
    "method": "delete",
    "id": "erase_kind_things_kinds__kind_sha256__delete",
    "title": "Erase a creature this workspace drafted, whole, by the SHA-256 of its kind.",
    "description": "",
    "group": "things",
    "permission": {
      "requires": [
        "deletion.write",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "kind_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Kind Sha256"
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/things/plans/{plan_sha256}",
    "method": "get",
    "id": "held_plan_things_plans__plan_sha256__get",
    "title": "A body plan this workspace holds, by the SHA-256 of its document.",
    "description": "",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "plan_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Plan Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Held Plan Things Plans  Plan Sha256  Get"
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
  },
  {
    "path": "/things/creatures/offered",
    "method": "get",
    "id": "creature_offer_things_creatures_offered_get",
    "title": "Creature Offer",
    "description": "Whether this workspace may ask for a creature here, why not by code, how long a draft\nusually takes by the creature drafter's measured calls, and every code a draft may end with.",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/things/creatures/drafts",
    "method": "get",
    "id": "list_creature_drafts_things_creatures_drafts_get",
    "title": "List Creature Drafts",
    "description": "The requester's own drafts, newest first: a reload or a second tab finds one still\nrunning.",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/things/creatures",
    "method": "post",
    "id": "draft_creature_things_creatures_post",
    "title": "Draft Creature",
    "description": "Ask for a creature from the person's words; answers 202 with its draft at once.",
    "group": "things",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CreatureBody"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/things/creatures/drafts/{draft_id}",
    "method": "get",
    "id": "read_creature_draft_things_creatures_drafts__draft_id__get",
    "title": "Read Creature Draft",
    "description": "One creature draft: queued, running, kept with its kind and look, erased since, refused with\nthe check's code and its fixed sentence, or failed with why.",
    "group": "things",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "draft_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Draft Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/behaviours",
    "method": "get",
    "id": "reviewed_behaviours_world_behaviours_get",
    "title": "The reviewed behaviours an object may be given, with each parameter's bounds.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/ReviewedBehaviourView"
              },
              "title": "Response Reviewed Behaviours World Behaviours Get"
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
  },
  {
    "path": "/world/versions",
    "method": "get",
    "id": "alternate_versions_world_versions_get",
    "title": "Every alternate world version in this workspace, newest first.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/AlternateVersionView"
              },
              "title": "Response Alternate Versions World Versions Get"
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
  },
  {
    "path": "/world/versions",
    "method": "post",
    "id": "create_alternate_version_world_versions_post",
    "title": "Create an alternate version from a source snapshot or from another version.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CreateVersionBody"
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
              "$ref": "#/components/schemas/BranchedVersionView"
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
  },
  {
    "path": "/world/versions/bootstrap",
    "method": "post",
    "id": "bootstrap_alternate_version_world_versions_bootstrap_post",
    "title": "Open the first snapshot and alternate from the current composed sources.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BootstrapWorldBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/BootstrapWorldView"
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
  },
  {
    "path": "/world/versions/{version_id}",
    "method": "get",
    "id": "alternate_version_world_versions__version_id__get",
    "title": "One alternate version with its objects, overrides and edit history.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/world/versions/{version_id}/inventory",
    "method": "get",
    "id": "world_inventory_world_versions__version_id__inventory_get",
    "title": "World Inventory",
    "description": "Enumerate saved identities; role membership does not grant model assignment or execution.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response World Inventory World Versions  Version Id  Inventory Get"
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
  },
  {
    "path": "/world/versions/{version_id}/inventory/query",
    "method": "post",
    "id": "query_world_entities_world_versions__version_id__inventory_query_post",
    "title": "Query World Entities",
    "description": "Match actual constant base factors; reading performs no edit, worker or model call.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/WorldEntityQueryBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/environment-instances",
    "method": "post",
    "id": "add_environment_instance_world_versions__version_id__environment_instances_post",
    "title": "Place one exact environment asset or feature against the current version state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/AddEnvironmentBody"
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
  },
  {
    "path": "/world/versions/{version_id}/environment-instances/{instance_id}/move",
    "method": "post",
    "id": "move_environment_instance_world_versions__version_id__environment_instances__instance_id__move_post",
    "title": "Move an available, still-authorized environment instance without changing its source.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "instance_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Instance Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/MoveObjectBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/environment-instances/{instance_id}/remove",
    "method": "post",
    "id": "remove_environment_instance_world_versions__version_id__environment_instances__instance_id__remove_post",
    "title": "Store a removal, including when the pinned source has since been withdrawn.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "instance_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Instance Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BaseStateBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/environment-instances/undo",
    "method": "post",
    "id": "undo_environment_edit_world_versions__version_id__environment_instances_undo_post",
    "title": "Undo the newest authored edit from stored history, even after source withdrawal.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BaseStateBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/things",
    "method": "post",
    "id": "add_thing_world_versions__version_id__things_post",
    "title": "Place a thing by its kind, shipped or its workspace's own, against the current state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/AddThingBody"
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
  },
  {
    "path": "/world/versions/{version_id}/things/{thing_id}/move",
    "method": "post",
    "id": "move_thing_world_versions__version_id__things__thing_id__move_post",
    "title": "Move a placed thing to another pose in its region, its kind unchanged.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "thing_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Thing Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/MoveThingBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/things/{thing_id}/remove",
    "method": "post",
    "id": "remove_thing_world_versions__version_id__things__thing_id__remove_post",
    "title": "Store the removal of a placed thing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "thing_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Thing Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BaseStateBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/things/undo",
    "method": "post",
    "id": "undo_thing_edit_world_versions__version_id__things_undo_post",
    "title": "Undo the newest authored edit from stored history.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BaseStateBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/thing-looks",
    "method": "get",
    "id": "thing_looks_world_versions__version_id__thing_looks_get",
    "title": "The look each thing of a version wears: the latest choice per thing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/society/things/{thing_id}",
    "method": "get",
    "id": "thing_card_read_world_versions__version_id__society_things__thing_id__get",
    "title": "One thing or being of the version's society of things, as its card shows it.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "thing_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Thing Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/society/things/{thing_id}/look",
    "method": "post",
    "id": "thing_look_choose_world_versions__version_id__society_things__thing_id__look_post",
    "title": "The world's owner chooses a shipped look for a thing; answers its card.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "thing_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Thing Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ThingLookBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/things/{thing_id}/character",
    "method": "post",
    "id": "thing_character_write_world_versions__version_id__things__thing_id__character_post",
    "title": "The world's owner writes or clears who a placed being is; answers the record.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "thing_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$",
          "title": "Thing Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ThingCharacterBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/things/on-support/preview",
    "method": "post",
    "id": "preview_supported_thing_world_versions__version_id__things_on_support_preview_post",
    "title": "Check passive rigid thing placement against an exact source support and state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SupportedThingBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/things/on-support",
    "method": "post",
    "id": "place_supported_thing_world_versions__version_id__things_on_support_post",
    "title": "Save a passive rigid thing with explicit admitted support affinity.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SupportedThingBody"
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
  },
  {
    "path": "/world/versions/{version_id}/things/{thing_id}/support",
    "method": "get",
    "id": "read_thing_support_world_versions__version_id__things__thing_id__support_get",
    "title": "Read a placed thing's support affinity and current bounded clearance availability.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "thing_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Thing Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/objects",
    "method": "post",
    "id": "add_authored_object_world_versions__version_id__objects_post",
    "title": "Add one authored object against an explicit base version state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
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
  },
  {
    "path": "/world/versions/{version_id}/objects/{object_id}/move",
    "method": "post",
    "id": "move_authored_object_world_versions__version_id__objects__object_id__move_post",
    "title": "Replace one authored object's region-local transform.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "object_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Object Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/MoveObjectBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/objects/{object_id}/remove",
    "method": "post",
    "id": "remove_authored_object_world_versions__version_id__objects__object_id__remove_post",
    "title": "Store a removal. POST rather than DELETE: this appends history, it destroys nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "object_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Object Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BaseStateBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/objects/{object_id}/behaviour",
    "method": "post",
    "id": "set_authored_object_behaviour_world_versions__version_id__objects__object_id__behaviour_post",
    "title": "Give one authored object a reviewed behaviour, replace it, or take it away with null.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "object_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Object Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SetObjectBehaviourBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/objects/undo",
    "method": "post",
    "id": "undo_authored_edit_world_versions__version_id__objects_undo_post",
    "title": "Reverse the newest object edit, from the document that edit stored.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/BaseStateBody"
          }
        }
      }
    },
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
  },
  {
    "path": "/world/versions/{version_id}/objects/{object_id}/move/preview",
    "method": "post",
    "id": "move_authored_object_preview_world_versions__version_id__objects__object_id__move_preview_post",
    "title": "What moving one authored object would record. Writes nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "object_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Object Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/MovePreviewBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Move Authored Object Preview World Versions  Version Id  Objects  Object Id  Move Preview Post"
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
  },
  {
    "path": "/world/versions/{version_id}/objects/{object_id}/remove/preview",
    "method": "post",
    "id": "remove_authored_object_preview_world_versions__version_id__objects__object_id__remove_preview_post",
    "title": "What removing one authored object would record. Writes nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
        "name": "object_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "maxLength": 200,
          "title": "Object Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/EditPreviewBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Remove Authored Object Preview World Versions  Version Id  Objects  Object Id  Remove Preview Post"
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
  },
  {
    "path": "/world/versions/{version_id}/objects/undo/preview",
    "method": "post",
    "id": "undo_authored_edit_preview_world_versions__version_id__objects_undo_preview_post",
    "title": "Which edit an undo would reverse, and what it would restore. Writes nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/EditPreviewBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Undo Authored Edit Preview World Versions  Version Id  Objects Undo Preview Post"
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
  },
  {
    "path": "/world/versions/{version_id}/compositions/preview",
    "method": "post",
    "id": "composition_preview_route_world_versions__version_id__compositions_preview_post",
    "title": "The server's verdict on one composition into one authored version. Writes nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CompositionPreviewBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Composition Preview Route World Versions  Version Id  Compositions Preview Post"
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
  },
  {
    "path": "/world/versions/{version_id}/compositions/apply",
    "method": "post",
    "id": "composition_apply_route_world_versions__version_id__compositions_apply_post",
    "title": "Perform exactly the resolved composition, or refuse with its blocked reason.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CompositionApplyBody"
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
  },
  {
    "path": "/world/versions/{version_id}/compositions/photo-point-maps/preview",
    "method": "post",
    "id": "photo_point_map_preview_route_world_versions__version_id__compositions_photo_point_maps_preview_post",
    "title": "The server's verdict on placing a 3D estimate from a photograph. Writes nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "admission.read",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PhotoPointMapPreviewBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Photo Point Map Preview Route World Versions  Version Id  Compositions Photo Point Maps Preview Post"
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
  },
  {
    "path": "/world/versions/{version_id}/compositions/photo-point-maps/apply",
    "method": "post",
    "id": "photo_point_map_apply_route_world_versions__version_id__compositions_photo_point_maps_apply_post",
    "title": "Place exactly the resolved estimate, or refuse with its blocked reason.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "admission.read",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PhotoPointMapApplyBody"
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
  },
  {
    "path": "/world/arrangements",
    "method": "get",
    "id": "arrangement_catalog_route_world_arrangements_get",
    "title": "The published arrangements a preview or apply may name, with their words.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ArrangementCatalogView"
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
  },
  {
    "path": "/world/versions/{version_id}/arrangements/preview",
    "method": "post",
    "id": "arrangement_preview_route_world_versions__version_id__arrangements_preview_post",
    "title": "Where an arrangement's objects would stand in one authored version. Writes nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ArrangementPreviewBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Arrangement Preview Route World Versions  Version Id  Arrangements Preview Post"
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
  },
  {
    "path": "/world/versions/{version_id}/arrangements/apply",
    "method": "post",
    "id": "arrangement_apply_route_world_versions__version_id__arrangements_apply_post",
    "title": "Add exactly the resolved objects as ordinary edits, or refuse with the reason.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ArrangementApplyBody"
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
              "$ref": "#/components/schemas/ArrangementApplyView"
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
  },
  {
    "path": "/world-entries",
    "method": "get",
    "id": "entries_world_entries_get",
    "title": "Entries",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/world-entries",
    "method": "post",
    "id": "create_entry_world_entries_post",
    "title": "Create Entry",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CreateSavedWorldEntryBody"
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
  },
  {
    "path": "/world-entries/candidates",
    "method": "get",
    "id": "candidates_world_entries_candidates_get",
    "title": "Candidates",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/SavedWorldCandidateView"
              },
              "title": "Response Candidates World Entries Candidates Get"
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
  },
  {
    "path": "/world-entries/starter",
    "method": "post",
    "id": "create_starter_entry_world_entries_starter_post",
    "title": "Create Starter Entry",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CreateStarterWorldBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SavedWorldEntryView"
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
  },
  {
    "path": "/world-entries/{entry_id}",
    "method": "get",
    "id": "entry_world_entries__entry_id__get",
    "title": "Entry",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "entry_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SavedWorldEntryView"
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
  },
  {
    "path": "/world-entries/{entry_id}",
    "method": "put",
    "id": "update_entry_world_entries__entry_id__put",
    "title": "Update Entry",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "entry_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UpdateSavedWorldEntryBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SavedWorldEntryView"
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
  },
  {
    "path": "/world-entries/{entry_id}/arrival/scene-geometry/{artifact_id}",
    "method": "get",
    "id": "arrival_scene_geometry_world_entries__entry_id__arrival_scene_geometry__artifact_id__get",
    "title": "Arrival Scene Geometry",
    "description": "Serve only the trained artifact of this entry's currently authorized v4 build.",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "entry_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
        }
      },
      {
        "name": "artifact_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Artifact Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world-entries/{entry_id}/source-attachments",
    "method": "post",
    "id": "attach_sources_world_entries__entry_id__source_attachments_post",
    "title": "Attach Sources",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "admission.read",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "entry_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/AttachSavedWorldSourcesBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SavedWorldEntryView"
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
  },
  {
    "path": "/world-entries/{entry_id}/source-detachments",
    "method": "post",
    "id": "detach_sources_world_entries__entry_id__source_detachments_post",
    "title": "Detach Sources",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "entry_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DetachSavedWorldSourcesBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SavedWorldEntryView"
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
  },
  {
    "path": "/world-entries/{entry_id}/source-rebinds",
    "method": "post",
    "id": "rebind_sources_world_entries__entry_id__source_rebinds_post",
    "title": "Rebind Sources",
    "description": "",
    "group": "world-entries",
    "permission": {
      "requires": [
        "admission.read",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "entry_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Entry Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RebindSavedWorldSourcesBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/SavedWorldEntryView"
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
  },
  {
    "path": "/world/versions/{version_id}/clock",
    "method": "get",
    "id": "read_clock_world_versions__version_id__clock_get",
    "title": "Which timeline each of a world version's systems runs on, and where it is.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Read Clock World Versions  Version Id  Clock Get"
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
  },
  {
    "path": "/world/versions/{version_id}/clock",
    "method": "put",
    "id": "transition_clock_world_versions__version_id__clock_put",
    "title": "Couple a world version's clock: one timeline for its people, traffic and birds.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/TransitionBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Transition Clock World Versions  Version Id  Clock Put"
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
  },
  {
    "path": "/world/versions/{version_id}/clock/events",
    "method": "get",
    "id": "clock_events_world_versions__version_id__clock_events_get",
    "title": "A world version's clock receipts, newest first.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 128,
          "minimum": 1,
          "default": 64,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Clock Events World Versions  Version Id  Clock Events Get"
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
  },
  {
    "path": "/world/versions/{version_id}/clock/verify",
    "method": "get",
    "id": "verify_clock_world_versions__version_id__clock_verify_get",
    "title": "Replay a coupled world's minutes from what was stored and check them.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "from_tick",
        "in": "query",
        "required": true,
        "schema": {
          "type": "integer",
          "minimum": 1,
          "title": "From Tick"
        }
      },
      {
        "name": "to_tick",
        "in": "query",
        "required": true,
        "schema": {
          "type": "integer",
          "minimum": 1,
          "title": "To Tick"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Verify Clock World Versions  Version Id  Clock Verify Get"
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
  },
  {
    "path": "/world/versions/{version_id}/flight",
    "method": "get",
    "id": "world_flight_world_versions__version_id__flight_get",
    "title": "The flyers a saved world's objects host, as steps of its flight for a page to draw.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "from_step",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "From Step"
        }
      },
      {
        "name": "steps",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "default": 600,
          "title": "Steps"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response World Flight World Versions  Version Id  Flight Get"
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
  },
  {
    "path": "/world/versions/{version_id}/traffic",
    "method": "get",
    "id": "world_traffic_world_versions__version_id__traffic_get",
    "title": "The vehicles a saved world's roads hold, second by second, for a page to draw.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "from_second",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "title": "From Second"
        }
      },
      {
        "name": "seconds",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "default": 60,
          "title": "Seconds"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/traffic/comparisons",
    "method": "get",
    "id": "signal_comparisons_world_versions__version_id__traffic_comparisons_get",
    "title": "Signal Comparisons",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Signal Comparisons World Versions  Version Id  Traffic Comparisons Get"
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
  },
  {
    "path": "/world/versions/{version_id}/traffic/comparisons",
    "method": "post",
    "id": "start_signal_comparison_world_versions__version_id__traffic_comparisons_post",
    "title": "Start Signal Comparison",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SignalComparisonStartBody"
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
              "title": "Response Start Signal Comparison World Versions  Version Id  Traffic Comparisons Post"
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
  },
  {
    "path": "/world/versions/{version_id}/traffic/comparisons/plan",
    "method": "get",
    "id": "plan_signal_comparison_world_versions__version_id__traffic_comparisons_plan_get",
    "title": "Plan Signal Comparison",
    "description": "What a start would do, writing nothing and playing no episode: the town's signals, the\nmodels offered for a signal's decisions, the development seeds this server holds and, for the\nselection the query names (``model`` as ``<provider>/<model id>``, once or twice; ``signal``\nfor a named group, every signal where none is named; ``bound_usd`` for the bound a start\nwould state), the runs it plans and the most it can cost, or the refusal a start of it would\nmeet, by the same predicates a start's allowance and grant checks read\n(``Services.allowance_refusal``, ``Services.bound_room_refusal``). Without a bound, the grant\nis judged on the calls the selection can make alone.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "model",
        "in": "query",
        "required": false,
        "schema": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "maxItems": 2,
          "default": [],
          "title": "Model"
        }
      },
      {
        "name": "control",
        "in": "query",
        "required": false,
        "schema": {
          "type": "boolean",
          "default": false,
          "title": "Control"
        }
      },
      {
        "name": "seeds",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 64,
          "minimum": 1,
          "default": 1,
          "title": "Seeds"
        }
      },
      {
        "name": "signal",
        "in": "query",
        "required": false,
        "schema": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "maxItems": 64,
          "default": [],
          "title": "Signal"
        }
      },
      {
        "name": "bound_usd",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[0-9]{1,6}(\\.[0-9]{1,8})?$"
            },
            {
              "type": "null"
            }
          ],
          "title": "Bound Usd"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Plan Signal Comparison World Versions  Version Id  Traffic Comparisons Plan Get"
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
  },
  {
    "path": "/world/versions/{version_id}/traffic/comparisons/{comparison_id}",
    "method": "get",
    "id": "signal_comparison_world_versions__version_id__traffic_comparisons__comparison_id__get",
    "title": "Signal Comparison",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Signal Comparison World Versions  Version Id  Traffic Comparisons  Comparison Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/traffic/comparisons/{comparison_id}/runs/{run_id}",
    "method": "get",
    "id": "signal_comparison_run_world_versions__version_id__traffic_comparisons__comparison_id__runs__run_id__get",
    "title": "Signal Comparison Run",
    "description": "One run's outcome and every choice point's receipt, as recorded; no replay.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
        }
      },
      {
        "name": "run_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Run Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Signal Comparison Run World Versions  Version Id  Traffic Comparisons  Comparison Id  Runs  Run Id  Get"
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
  },
  {
    "path": "/world/versions/{version_id}/traffic/comparisons/{comparison_id}/runs/{run_id}/replay",
    "method": "get",
    "id": "replay_signal_comparison_run_world_versions__version_id__traffic_comparisons__comparison_id__runs__run_id__replay_get",
    "title": "Replay Signal Comparison Run",
    "description": "A completed run played again from what it stored, asking no model, held to its record.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
        }
      },
      {
        "name": "run_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Run Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Replay Signal Comparison Run World Versions  Version Id  Traffic Comparisons  Comparison Id  Runs  Run Id  Replay Get"
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
  },
  {
    "path": "/world/versions/{version_id}/traffic/comparisons/{comparison_id}/cancel",
    "method": "post",
    "id": "cancel_signal_comparison_world_versions__version_id__traffic_comparisons__comparison_id__cancel_post",
    "title": "Cancel Signal Comparison",
    "description": "Cancel a signal comparison started from the application, once, as a comparison of people\nis cancelled: a start no host holds closes now, its open runs failed as\n``comparison_cancelled`` asking nothing, with what a host whose lease ran out may have spent\npresumed; a host playing it stops before its next ask. Its durable bounds, where it spends\nunder them, are closed once the cancellation is recorded. A repeated cancel changes nothing,\nand a finished start keeps its own closing. Answers the comparison as the listing states it.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
        "name": "comparison_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Comparison Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Cancel Signal Comparison World Versions  Version Id  Traffic Comparisons  Comparison Id  Cancel Post"
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
  },
  {
    "path": "/world/versions/{version_id}/models",
    "method": "get",
    "id": "world_models_world_versions__version_id__models_get",
    "title": "World Models",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/world/versions/{version_id}/models/{role_key}",
    "method": "post",
    "id": "choose_world_model_world_versions__version_id__models__role_key__post",
    "title": "Choose World Model",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "role_key",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "title": "Role Key"
        }
      },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RoleChoiceBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Choose World Model World Versions  Version Id  Models  Role Key  Post"
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
  },
  {
    "path": "/world/versions/{version_id}/models/{role_key}/budget",
    "method": "post",
    "id": "set_world_minds_budget_world_versions__version_id__models__role_key__budget_post",
    "title": "Set World Minds Budget",
    "description": "Set what this world may spend on the model minds of its beings, in any hour of real time.\n\nOne appended record of the world, naming who set it; the newest is the budget, and the same\nrequest asked again answers the record it made (``budget`` is that record, also when a later\nrequest has set another since). A request that names the budget it was prepared against\n(``after_budget_seq``) is refused where another has been set since (``budget_changed``).\nIt asks no model and spends nothing. The process's own\nbudget and its reserve, a deployment's allowance and the workspace's grant still bound every\ncall: a budget is never above them, whatever it reads.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "role_key",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "title": "Role Key"
        }
      },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/MindsBudgetBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Set World Minds Budget World Versions  Version Id  Models  Role Key  Budget Post"
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
  },
  {
    "path": "/world/versions/{version_id}/subjects/{ref}",
    "method": "get",
    "id": "read_subject_world_versions__version_id__subjects__ref__get",
    "title": "A world, being or thing's properties and catalog actions, without performing them.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "ref",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "title": "Ref"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/capabilities",
    "method": "get",
    "id": "world_creation_worlds_capabilities_get",
    "title": "Whether each kind of world can be made in this workspace now, and how.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response World Creation Worlds Capabilities Get"
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
  },
  {
    "path": "/world/versions/{version_id}/capabilities",
    "method": "get",
    "id": "version_capabilities_world_versions__version_id__capabilities_get",
    "title": "What can be done with this version of the world now: its regions, its society and each supported operation with its state.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/world/interactions/catalog",
    "method": "get",
    "id": "catalog_world_interactions_catalog_get",
    "title": "Reviewed comfort, navigation, disclosure, and initiative controls.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Catalog World Interactions Catalog Get"
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
  },
  {
    "path": "/world/interactions/current",
    "method": "get",
    "id": "current_world_interactions_current_get",
    "title": "Current",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/InteractionStateView"
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
  },
  {
    "path": "/world/interactions/versions",
    "method": "get",
    "id": "versions_world_interactions_versions_get",
    "title": "Versions",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/InteractionVersionView"
              },
              "title": "Response Versions World Interactions Versions Get"
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
  },
  {
    "path": "/world/interactions/proposals/{proposal_id}",
    "method": "get",
    "id": "proposal_record_world_interactions_proposals__proposal_id__get",
    "title": "Proposal Record",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "proposal_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Proposal Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/InteractionProposalView"
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
  },
  {
    "path": "/world/interactions/recommendations",
    "method": "get",
    "id": "recommendations_world_interactions_recommendations_get",
    "title": "Recommendations",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/InteractionRecommendationView"
              },
              "title": "Response Recommendations World Interactions Recommendations Get"
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
  },
  {
    "path": "/world/interactions/previews",
    "method": "post",
    "id": "preview_world_interactions_previews_post",
    "title": "Preview",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/InteractionPreviewBody"
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
              "$ref": "#/components/schemas/InteractionPreviewView"
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
  },
  {
    "path": "/world/interactions/previews/{preview_id}/apply",
    "method": "post",
    "id": "apply_world_interactions_previews__preview_id__apply_post",
    "title": "Apply",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "preview_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Preview Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/InteractionApplyBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/InteractionVersionView"
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
  },
  {
    "path": "/world/interactions/previews/{preview_id}",
    "method": "delete",
    "id": "discard_world_interactions_previews__preview_id__delete",
    "title": "Discard",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "preview_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Preview Id"
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/world/interactions/rollback",
    "method": "post",
    "id": "rollback_world_interactions_rollback_post",
    "title": "Rollback",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/InteractionRollbackBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/InteractionVersionView"
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
  },
  {
    "path": "/world/projects",
    "method": "get",
    "id": "list_projects_world_projects_get",
    "title": "This world's projects the caller owns or that are shared with them.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 100,
          "minimum": 1,
          "default": 50,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/ProjectView"
              },
              "title": "Response List Projects World Projects Get"
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
  },
  {
    "path": "/world/projects",
    "method": "post",
    "id": "create_project_world_projects_post",
    "title": "Start a project bound to a version of this world. An exact retry of a key is 200.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProjectBody"
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
              "$ref": "#/components/schemas/ProjectView"
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
  },
  {
    "path": "/world/projects/{project_id}",
    "method": "get",
    "id": "read_project_world_projects__project_id__get",
    "title": "One project: its binding as the version reads now, and what the caller may see.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectView"
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
  },
  {
    "path": "/world/projects/{project_id}",
    "method": "put",
    "id": "update_project_world_projects__project_id__put",
    "title": "Rename the project, or bind it to another version of this world.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProjectUpdateBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectView"
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
  },
  {
    "path": "/world/projects/{project_id}",
    "method": "delete",
    "id": "delete_project_world_projects__project_id__delete",
    "title": "Delete the project, every item's words and every share, for good.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "deletion.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/world/projects/{project_id}/audit",
    "method": "get",
    "id": "project_audit_world_projects__project_id__audit_get",
    "title": "The owner's non-content record of a project, kept after its words are deleted.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectAuditView"
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
  },
  {
    "path": "/world/projects/{project_id}/items",
    "method": "get",
    "id": "list_items_world_projects__project_id__items_get",
    "title": "The items the caller may see, with what each names as its authority reads now.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "status",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "array",
              "items": {
                "enum": [
                  "proposed",
                  "active",
                  "resolved"
                ],
                "type": "string"
              }
            },
            {
              "type": "null"
            }
          ],
          "title": "Status"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/ProjectItemView"
              },
              "title": "Response List Items World Projects  Project Id  Items Get"
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
  },
  {
    "path": "/world/projects/{project_id}/items",
    "method": "post",
    "id": "add_item_world_projects__project_id__items_post",
    "title": "Keep an item, or copy one of the caller's own. An exact retry of a key is 200.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProjectItemBody"
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
              "$ref": "#/components/schemas/ProjectItemView"
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
  },
  {
    "path": "/world/projects/{project_id}/items/{item_id}/history",
    "method": "get",
    "id": "item_history_world_projects__project_id__items__item_id__history_get",
    "title": "Every revision of one of the owner's items, with its words: its correction history.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "item_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Item Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/ProjectItemRevisionView"
              },
              "title": "Response Item History World Projects  Project Id  Items  Item Id  History Get"
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
  },
  {
    "path": "/world/projects/{project_id}/items/{item_id}/corrections",
    "method": "post",
    "id": "correct_item_world_projects__project_id__items__item_id__corrections_post",
    "title": "Correct an item. The earlier words stay in its history until it is deleted.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "item_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Item Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProjectItemCorrectionBody"
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
              "$ref": "#/components/schemas/ProjectItemView"
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
  },
  {
    "path": "/world/projects/{project_id}/items/{item_id}/review",
    "method": "post",
    "id": "review_item_world_projects__project_id__items__item_id__review_post",
    "title": "Accept a suggestion into the context, or reject it and erase its words.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "item_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Item Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProjectItemReviewBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectItemReviewView"
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
  },
  {
    "path": "/world/projects/{project_id}/items/{item_id}/resolve",
    "method": "post",
    "id": "resolve_item_world_projects__project_id__items__item_id__resolve_post",
    "title": "Close a goal, question or task that is done. It leaves the context.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "item_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Item Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProjectItemResolveBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectItemView"
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
  },
  {
    "path": "/world/projects/{project_id}/items/{item_id}",
    "method": "delete",
    "id": "delete_item_world_projects__project_id__items__item_id__delete",
    "title": "Delete one item and every copy of it, erasing their words.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "deletion.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "item_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Item Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectRevisionView"
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
  },
  {
    "path": "/world/projects/{project_id}/shares",
    "method": "post",
    "id": "share_world_projects__project_id__shares_post",
    "title": "Share the project, or listed items of it, with the other people of this workspace.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ProjectShareBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectSharesView"
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
  },
  {
    "path": "/world/projects/{project_id}/shares/{share_id}",
    "method": "delete",
    "id": "stop_share_world_projects__project_id__shares__share_id__delete",
    "title": "Stop one share. The next read by anyone else no longer shows what it opened.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "share_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Share Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectRevisionView"
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
  },
  {
    "path": "/world/projects/{project_id}/context",
    "method": "get",
    "id": "project_context_world_projects__project_id__context_get",
    "title": "The bounded context the caller may hand onward, assembled now; nothing is stored.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "project_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Project Id"
        }
      },
      {
        "name": "max_entries",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 64,
          "minimum": 1,
          "default": 24,
          "title": "Max Entries"
        }
      },
      {
        "name": "max_bytes",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 32768,
          "minimum": 1024,
          "default": 8192,
          "title": "Max Bytes"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ProjectContextView"
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
  },
  {
    "path": "/world-read/scenes/{scene_id}",
    "method": "get",
    "id": "scene_bundle_world_read_scenes__scene_id__get",
    "title": "What a generative world model may condition on for one scene, digest-bound.",
    "description": "",
    "group": "world-read",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "scene_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world-read/places/{place_id}",
    "method": "get",
    "id": "place_bundle_world_read_places__place_id__get",
    "title": "What a generative world model may condition on for one place at one time.",
    "description": "A place and a time, resolved to the version in force then.\n\nFour answers, and the reason they are four rather than two is that a caller can act on each.\n\n*   **404** for a place that does not exist and for another workspace's, indistinguishable,\n    for the same M10 reason the scene address gives.\n*   **424** for a place with no anchor. The place row exists and has no shared frame yet,\n    which is the window between creating it and its first accepted alignment. Answering 404\n    would deny a place the caller can see, and 410 would say somebody deleted it.\n*   **410** for a place whose anchor was withdrawn. Every version's frame is the anchor's, so\n    withdrawing the anchor's photographs takes the shared frame with it, and the caller\n    holding an earlier bundle is entitled to learn that rather than to be told 404.\n*   **200** for a readable place, INCLUDING one with no version at or before ``at``. That is\n    an answer, not an absence: the bundle carries the place, its versions and their times, no\n    scene at all, and says which of those it is. Turning it into a 404 would report a place\n    that exists as missing.\n\n``at`` is optional and a missing one means the latest dated version rather than \"now\". A read\nwhose answer depends on the clock has a digest that moves with no write behind it, which\n``exulanica/graph/world_read.py`` records the cost of. A naive timestamp is refused rather\nthan assumed to be UTC: the column is UTC and guessing is how an hour goes missing.",
    "group": "world-read",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "place_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Place Id"
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
        "name": "at",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "date-time"
            },
            {
              "type": "null"
            }
          ],
          "description": "Resolve the version of this place in force at this instant.",
          "title": "At"
        },
        "description": "Resolve the version of this place in force at this instant."
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world-read/scenes/{scene_id}/observations",
    "method": "get",
    "id": "scene_observation_graph_world_read_scenes__scene_id__observations_get",
    "title": "Which photographs actually observed each retained sparse point.",
    "description": "Click-to-evidence's recorded half.\n\nA scene with no accepted pose receipt answers 404 alongside a missing and a foreign one. That\nis deliberate: \"this scene exists but its pose was refused\" is a fact about somebody's library,\nand the read surface does not distinguish reasons a caller may not have.\n\n``limit`` and ``after_point_id`` page the answer, and no limit means the whole graph, which is\nwhat this route returns and what a client reading it expects. The response\nsays which one it got: MEASURED 2026-09-07 against the retained reference instance, the bowl\nscene's graph is 97,633,587 canonical bytes and the volcanic scene's is 1,179,240,157, so a\ncaller who wants a page has to be able to ask for one, and a caller who gets a page has to be\ntold so.\n\nThe inspector resolves one click at a time through ``/resolve`` below, because the volcanic\nscene's whole graph is more than a browser can hold as one string.",
    "group": "world-read",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "scene_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
        }
      },
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer",
              "minimum": 1
            },
            {
              "type": "null"
            }
          ],
          "description": "Return at most this many points, in point-id order.",
          "title": "Limit"
        },
        "description": "Return at most this many points, in point-id order."
      },
      {
        "name": "after_point_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "description": "Continue after this point id, from a previous page's next_point_id.",
          "title": "After Point Id"
        },
        "description": "Continue after this point id, from a previous page's next_point_id."
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world-read/scenes/{scene_id}/observations/summary",
    "method": "get",
    "id": "scene_observation_counts_world_read_scenes__scene_id__observations_summary_get",
    "title": "How many recorded points and observations a click in this scene resolves against.",
    "description": "Counts only, for the inspector to show before anyone clicks. Hundreds of bytes.",
    "group": "world-read",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "scene_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world-read/scenes/{scene_id}/observations/resolve",
    "method": "get",
    "id": "scene_observation_resolve_world_read_scenes__scene_id__observations_resolve_get",
    "title": "The one recorded point a cursor selects in one photograph, and who observed it.",
    "description": "Click-to-evidence, resolved here rather than by downloading the graph to the browser.\n\nThe answer holds at most one point and that point's retained observations, so it is bounded\nby the scene's member count and not by its point count. MEASURED 2026-09-11 on the volcanic\nscene: the inspector's own centre-of-view click is 11,277 bytes, and the heaviest point any\nclick can select there, 78 retained photographs, is 92,547. The whole graph is\n1,015,016,928.\nA miss is a 200 whose ``state`` says so, because nothing recorded near a click is an answer.\n``exulanica/graph/observations.py`` holds the rest of the argument.",
    "group": "world-read",
    "permission": {
      "requires": [
        "library.read"
      ]
    },
    "parameters": [
      {
        "name": "scene_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
        }
      },
      {
        "name": "capture_id",
        "in": "query",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "description": "The photograph whose recovered camera the cursor is in.",
          "title": "Capture Id"
        },
        "description": "The photograph whose recovered camera the cursor is in."
      },
      {
        "name": "u",
        "in": "query",
        "required": true,
        "schema": {
          "type": "number",
          "maximum": 1000000000,
          "minimum": -1000000000,
          "description": "Cursor, in that photograph's pixels, +u right.",
          "title": "U"
        },
        "description": "Cursor, in that photograph's pixels, +u right."
      },
      {
        "name": "v",
        "in": "query",
        "required": true,
        "schema": {
          "type": "number",
          "maximum": 1000000000,
          "minimum": -1000000000,
          "description": "Cursor, in that photograph's pixels, +v down.",
          "title": "V"
        },
        "description": "Cursor, in that photograph's pixels, +v down."
      },
      {
        "name": "tolerance_px",
        "in": "query",
        "required": false,
        "schema": {
          "type": "number",
          "maximum": 1024,
          "exclusiveMinimum": 0,
          "description": "How far a point may project from it.",
          "default": 24,
          "title": "Tolerance Px"
        },
        "description": "How far a point may project from it."
      },
      {
        "name": "occlusion_band_px",
        "in": "query",
        "required": false,
        "schema": {
          "type": "number",
          "maximum": 1024,
          "minimum": 0,
          "description": "Within this of the nearest, nearer wins.",
          "default": 4,
          "title": "Occlusion Band Px"
        },
        "description": "Within this of the nearest, nearer wins."
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world-write/scenes/{scene_id}/generated",
    "method": "post",
    "id": "record_generation_world_write_scenes__scene_id__generated_post",
    "title": "File what a world model imagined, in the tier below every recorded rung.",
    "description": "",
    "group": "world-write",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "scene_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Scene Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/GeneratedSceneBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world-generation/grammars",
    "method": "get",
    "id": "grammars_world_generation_grammars_get",
    "title": "Every parameter a world can be asked for by, as its grammar declares it.",
    "description": "The catalog. Nobody can tune a parameter they cannot enumerate.\n\nEvery declared parameter, with its unit, the cascade level it belongs to, the one stage that\nreads it, what happens when nothing sets it, its range or its options, and the stated basis of\nthat range. All of it read off the registered grammar rather than restated here, so this\ncannot drift from what the cascade will actually enforce.",
    "group": "world-generation",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "array",
              "items": {
                "$ref": "#/components/schemas/GrammarView"
              },
              "title": "Response Grammars World Generation Grammars Get"
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
  },
  {
    "path": "/world-generation/worlds",
    "method": "post",
    "id": "ask_for_a_world_world_generation_worlds_post",
    "title": "State a specification; get the world it makes, or a refusal naming the parameter.",
    "description": "Resolve, charge, generate.\n\nIn that order, and the order is the point. The charge is taken from the tile count the\nRESOLVED specification covers, before any record is made, so a request the workspace cannot\nafford costs nothing but the resolution. That mirrors ``exulanica.models.budget``, which\nreserves before a call for the same reason ``exulanica.api.quotas`` gives: charging less than\na request can cost lets the last request cross the ceiling, which is the one thing a ceiling\nexists to prevent.\n\nNothing is stored. A specification needs no row, because the seed is derived from it: the\nrequest body and this route are together enough to make the same world again, and a table\nwould be a second copy of a fact that is already reproducible.",
    "group": "world-generation",
    "permission": {
      "requires": [
        "tiles.materialise"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SpecificationBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/GeneratedWorldView"
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
  },
  {
    "path": "/worlds",
    "method": "get",
    "id": "worlds_worlds_get",
    "title": "Every world this workspace holds, with its kind, and how many of each it may hold.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/worlds/personal-source",
    "method": "get",
    "id": "personal_source_world_worlds_personal_source_get",
    "title": "Whether a world can be made, or photographs added to it, from your reviewed photographs now; writes nothing.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "admission.read",
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/PersonalWorldView"
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
  },
  {
    "path": "/worlds/personal-source",
    "method": "post",
    "id": "compose_personal_source_world_worlds_personal_source_post",
    "title": "Compose your reviewed photographs into your personal-source world, or add them to it, as last read.",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "admission.read",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ComposePersonalWorldBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/ComposedPersonalWorldView"
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
  },
  {
    "path": "/worlds/{world_id}/removal",
    "method": "get",
    "id": "preview_world_removal_worlds__world_id__removal_get",
    "title": "Preview World Removal",
    "description": "Read removal consequences. Only its creator or workspace owner can remove a world.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "world_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/WorldRemovalView"
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
  },
  {
    "path": "/worlds/{world_id}",
    "method": "delete",
    "id": "remove_world_worlds__world_id__delete",
    "title": "Remove World",
    "description": "Permanently remove a generated world; a backup restore honors the removal again.",
    "group": "world",
    "permission": {
      "requires": [
        "deletion.write",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "world_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/worlds/recipes",
    "method": "get",
    "id": "recipes_worlds_recipes_get",
    "title": "The recipes a world can be generated from.",
    "description": "Every recipe this server generates worlds from, in catalog order.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
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
  },
  {
    "path": "/worlds/specification",
    "method": "get",
    "id": "specification_worlds_specification_get",
    "title": "What a generated world may be made from: every value, its range, presets, refusals.",
    "description": "The specification schema this server offers, with its presets and every refusal by name.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Specification Worlds Specification Get"
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
  },
  {
    "path": "/worlds/generated",
    "method": "post",
    "id": "create_generated_world_worlds_generated_post",
    "title": "Generate a world from a recipe and save it as yours.",
    "description": "Generate the preset's world with the values asked for, for a new identity, save it and its\nentry, and queue its bakes.\n\nAn unknown preset, a value its schema does not offer (422, naming the key, the value and the\nrange), a title that is empty once trimmed (422), a preset its composer does not generate, a\nspecification that generates no world from any of its seed candidates, a style pack that is\nnot a pack of the host's library at exactly that version and manifest digest (422\n`invalid_style_data`), and a workspace that already holds as many generated worlds as the\ncount policy allows are each refused by name, and nothing is written. A deployment whose\ndatabase role cannot register a world is refused 403 `worlds_read_only` before anything is\ngenerated.\n\nThe world is made, then its look named in its appearance's next version, the entry's resume\npointer moved with it. When that write is refused as busy, the world stays as made, naming no\npack, which a page draws in the default look.",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
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
  },
  {
    "path": "/worlds/generated/terrain",
    "method": "post",
    "id": "create_terrain_world_worlds_generated_terrain_post",
    "title": "Save an admitted terrain realization as a world.",
    "description": "Retain exact authored terrain and a valid entry through saved-world authority.\n\nThe source declares bounded person contact and passive flat-patch geometry. It has no\nsociety projection; creating it does not fulfill a world kind's activity requirements.",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CreateTerrainWorldBody"
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
      "422": {
        "description": "Invalid terrain or entry; nothing was written."
      }
    }
  },
  {
    "path": "/world/versions/{version_id}/terrain-contact",
    "method": "get",
    "id": "read_terrain_contact_world_versions__version_id__terrain_contact_get",
    "title": "Read Terrain Contact",
    "description": "Bind static terrain contact to an authorized version with no unreconciled authored delta.\n\nAny authored occupancy without a complete terrain proxy adapter is unavailable. A source\ngeometry digest alone is never a claim that the current edited world is clear.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "expected_state_sha256",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[0-9a-f]{64}$"
            },
            {
              "type": "null"
            }
          ],
          "title": "Expected State Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/versions/{version_id}/tiles/{baked_tile_id}/bytes",
    "method": "get",
    "id": "read_world_tile_bytes_world_versions__version_id__tiles__baked_tile_id__bytes_get",
    "title": "One baked tile of a generated world, for the world that names it.",
    "description": "A baked tile's bytes, served only when the version's own snapshot names the tile.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
        "name": "baked_tile_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Baked Tile Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/kinds",
    "method": "get",
    "id": "library_worlds_kinds_get",
    "title": "The kinds of world a person can make worlds of.",
    "description": "The town, the shipped kinds and the workspace's own kinds, each in plain words, and whether\nthis caller may draft a new kind of place here.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/KindLibraryView"
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
  },
  {
    "path": "/worlds/kinds",
    "method": "post",
    "id": "upload_kind_worlds_kinds_post",
    "title": "Keep a creator's world kind in this workspace once its checks pass.",
    "description": "Read the kind, build its sample worlds and keep it when every one passes.\n\nA server whose deployment has not turned kinds from people on\n(``EXULANICA_KINDS_FROM_PEOPLE``) answers 403 ``kinds_from_people_not_offered`` for a document\nit would otherwise keep, before any sample world is built and before anything is written: a\nkept kind is a person's own document, and no removal reaches its row. A body that is no kind\nis refused 422 for itself first, as on any server.\nA body over :data:`UPLOAD_BODY_MAXIMUM` is refused 413 before it is read; a document larger\nthan :data:`UPLOAD_BYTES_MAXIMUM`, one whose origin is not ``uploaded``, and any refusal of\neither stage answer 422 with the refusal's code, where and why (stage B's with its report so\nfar); a version or a document the workspace already holds, and a workspace already keeping as\nmany kind versions as it may, answer 409, before any sample world is built. Stage B runs in the\nkind worker (:mod:`exulanica.world.kinds.worker`), never on the request's thread: checks the\nworker does not finish within its limit, or cannot take, answer 503 ``kind_work_overran``,\n``kind_work_busy`` or ``kind_work_unavailable`` with a ``Retry-After``, and finished checks\nare kept, so sending the same kind again reads them.",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UploadKindBody"
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
              "$ref": "#/components/schemas/UploadedKindView"
            }
          }
        }
      },
      "422": {
        "description": "Refused by name; nothing was written."
      }
    }
  },
  {
    "path": "/worlds/kinds/drafts",
    "method": "post",
    "id": "start_kind_draft_worlds_kinds_drafts_post",
    "title": "Draft a kind of world from a description, as a job the page polls.",
    "description": "Admit the words and start the draft; answer at once, never waiting on the model.\n\n403 ``kinds_from_people_not_offered`` on a server whose deployment has not turned kinds from\npeople on (``EXULANICA_KINDS_FROM_PEOPLE``), before anything is read;\n503 without a model credential; 429 ``budget_exceeded`` with its ``spending`` member when the\nworkspace's allowance for the drafting model admits no attempt (spent, or below what one\nreserves); 409 ``kind_cap_reached`` when the\nworkspace keeps as many kinds as it may, each before anything is spent; 409\n``kind_draft_busy`` while a draft runs in this workspace, with its ``draft_id`` when the caller\nstarted it; 429 ``kind_draft_limit`` with a ``Retry-After`` when the caller has started as many\ndrafts this hour as one person may; 503 ``kind_draft_capacity`` with a ``Retry-After`` when\nthe server runs as many drafts as it may. Saved names are replaced before the job starts, and\nthe workspace's rules, releasing no place's name, are applied again as each request leaves.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DraftKindBody"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/KindDraftView"
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
  },
  {
    "path": "/worlds/kinds/drafts",
    "method": "get",
    "id": "list_kind_drafts_worlds_kinds_drafts_get",
    "title": "The kinds of place this caller is drafting or drafted lately, newest first.",
    "description": "The caller's drafts this server still holds in this workspace, newest first, so a reload,\na second tab or a return finds a draft still running without starting another.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/KindDraftListView"
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
  },
  {
    "path": "/worlds/kinds/drafts/{draft_id}",
    "method": "get",
    "id": "read_kind_draft_worlds_kinds_drafts__draft_id__get",
    "title": "A kind's draft: drafting, ready with the kept kind, or refused by name.",
    "description": "The requester's retained draft, including after another process takes over.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "draft_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Draft Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/KindDraftView"
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
  },
  {
    "path": "/worlds/kinds/versions/{document_sha256}/removal",
    "method": "get",
    "id": "kind_removal_preview_worlds_kinds_versions__document_sha256__removal_get",
    "title": "Kind Removal Preview",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "document_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Document Sha256"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/kinds/versions/{document_sha256}",
    "method": "delete",
    "id": "remove_kept_kind_worlds_kinds_versions__document_sha256__delete",
    "title": "Remove Kept Kind",
    "description": "",
    "group": "world",
    "permission": {
      "requires": [
        "deletion.write",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "document_sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Document Sha256"
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
  },
  {
    "path": "/worlds/kinds/{kind}/worlds",
    "method": "post",
    "id": "create_kind_world_worlds_kinds__kind__worlds_post",
    "title": "Make a world of a kind and save it as yours.",
    "description": "Make a world of ``kind`` with a preset and values, for a new identity, and save its entry.\n\nThe town is made as ``POST /worlds/generated`` makes it, from its preset through the same gate\nand composer, so it is the same world. Every other kind is made by the site grammar from the\nkind the workspace holds or the product ships (the latest version unless one is named). An\nunknown kind or preset answers 404; a value the kind does not offer 422, naming the key, the\nvalue and the range; a title empty once trimmed 422; a kind none of whose candidates makes a\nworld people can live in, for any identity drawn, 409 with every refusal; a workspace already\nholding as many generated worlds as the count policy allows 409; a deployment whose database\nrole cannot register a world 403 ``worlds_read_only``. Nothing is written when any is refused.\n\nA world's receipt carries its kind's whole document, so a world of a kind the workspace keeps\ncopies a person's document once more. A server whose deployment has not turned kinds from\npeople on (``EXULANICA_KINDS_FROM_PEOPLE``) makes worlds of shipped kinds and the town only,\nand answers 403 ``kinds_from_people_not_offered`` for a kind the workspace keeps.",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "kind",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "title": "Kind"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CreateKindWorldBody"
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
  },
  {
    "path": "/world/versions/{version_id}/site",
    "method": "get",
    "id": "read_site_drawing_world_versions__version_id__site_get",
    "title": "A site world's drawing, for the world whose snapshot names its receipt.",
    "description": "Serve the version's exact drawing after worker/cache and final current-source checks.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/drafts",
    "method": "post",
    "id": "start_world_draft_worlds_drafts_post",
    "title": "Make a world from a description, as a job the page polls.",
    "description": "Admit the words and start the draft; answer at once, never waiting on a model.\n\n403 ``kinds_from_people_not_offered`` on a server whose deployment has not turned kinds from\npeople on; 503 without a model credential; 429 ``budget_exceeded`` with its ``spending``\nmember when the workspace's allowance admits no attempt; 409 ``world_limit_reached`` when the\nworkspace holds as many generated worlds as it may; 403 ``worlds_read_only`` where the\ndatabase role cannot register a world: each before anything is spent, and each said by\n``GET /worlds/drafts`` before anything is typed. 409 ``kind_draft_busy`` while a draft runs in\nthis workspace, with its ``draft_id`` when the caller started it as a world's draft; 429\n``kind_draft_limit`` with a ``Retry-After`` when the caller has started as many drafts this\nhour as one person may. A server already running as many drafts as it may still answers 202:\nthe draft waits queued until its worker has a slot, and ends refused ``kind_draft_capacity``\nonly where no thread could be started for it. The three figures are the world draft policy's\nbudgets. A body over 131,072 bytes, including quote metadata, is refused 413 before it is read.\nSaved names are replaced in the words before the job starts.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DraftWorldBody"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/MadeWorldDraftView"
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
  },
  {
    "path": "/worlds/drafts",
    "method": "get",
    "id": "read_world_draft_offer_worlds_drafts_get",
    "title": "Whether a draft of a world would be taken now, and what one may spend.",
    "description": "What starting a draft would meet, for this person in this workspace, before a word is\ntyped: ``offered`` or the first refusal a start would give, by code and sentence, in the\norder the start asks them; the most times one draft asks a model (``calls_at_most``); this\nperson's starts this hour, how many are left and when the next frees; and their own draft of\na world still running here, by id. Nothing is said of anybody else: another person's running\ndraft is ``kind_draft_busy`` with no id. The server's own capacity changes from moment to\nmoment and is answered when a draft starts.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/WorldDraftOfferView"
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
  },
  {
    "path": "/worlds/drafts/{draft_id}",
    "method": "get",
    "id": "read_world_draft_worlds_drafts__draft_id__get",
    "title": "Where a draft of a world has got to, for the person who started it.",
    "description": "The draft's state: choosing, drafting, making, ready with the saved world, or refused by\nname. 404 ``world_draft_unknown`` for an id the server holds for nobody here to read:\nanother person's, another workspace's, a kind's draft, one a restart lost, or none.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "draft_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Draft Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/MadeWorldDraftView"
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
  },
  {
    "path": "/selection/world-drafts/prepare",
    "method": "post",
    "id": "prepare_selection_world_drafts_prepare_post",
    "title": "Prepare",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PrepareBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Prepare Selection World Drafts Prepare Post"
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
  },
  {
    "path": "/selection/world-drafts/outcome",
    "method": "post",
    "id": "outcome_selection_world_drafts_outcome_post",
    "title": "Outcome",
    "description": "",
    "group": "selection",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/OutcomeBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/references",
    "method": "get",
    "id": "list_references_worlds_references_get",
    "title": "List References",
    "description": "The caller's most recent reference requests, newest first, and whether one may be made.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/references",
    "method": "post",
    "id": "request_reference_worlds_references_post",
    "title": "Request Reference",
    "description": "Ask for notes on what the things in a description and the person's own pictures look like,\nfor one draft. Answers 202 with the request at once; an idempotency key answers 200 with the\nrequest it first made.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "references.request",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ReferenceBody"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/references/{reference_id}",
    "method": "get",
    "id": "read_reference_worlds_references__reference_id__get",
    "title": "Read Reference",
    "description": "One reference request: its steps as they happen, then its notes, or why it stopped.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "reference_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Reference Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/references/{reference_id}/cancel",
    "method": "post",
    "id": "cancel_reference_worlds_references__reference_id__cancel_post",
    "title": "Cancel Reference",
    "description": "Stop a request: a queued one at once, a running one at its next step. A finished one is\nanswered as it stands.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "references.request",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "reference_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Reference Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/piece-requests",
    "method": "post",
    "id": "ask_for_pieces_world_piece_requests_post",
    "title": "Ask For Pieces",
    "description": "Ask for new pieces of a world's look for some thing kinds. Answers 202 with the requests and\ntheir estimate; an idempotency key, or an ask already waiting, answers 200.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.write"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PieceAskBody"
          }
        }
      }
    },
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/piece-requests",
    "method": "get",
    "id": "list_piece_requests_world_piece_requests_get",
    "title": "List Piece Requests",
    "description": "A world's piece requests, newest first, and whether the piece maker is running.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/piece-requests/{piece_request_id}",
    "method": "get",
    "id": "read_piece_request_world_piece_requests__piece_request_id__get",
    "title": "Read Piece Request",
    "description": "One piece request and where it stands.",
    "group": "world",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "piece_request_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Piece Request Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/piece-requests/{piece_request_id}",
    "method": "delete",
    "id": "cancel_piece_request_world_piece_requests__piece_request_id__delete",
    "title": "Cancel Piece Request",
    "description": "Cancel a request no session has taken. One taken or ended is answered 409 with its state.",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "piece_request_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Piece Request Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/world/piece-requests/{piece_request_id}/take-back",
    "method": "post",
    "id": "take_back_pieces_world_piece_requests__piece_request_id__take_back_post",
    "title": "Take Back Pieces",
    "description": "Ask for a request's pieces to leave its world's look. Answers 202 with the request; one\nwhose pieces its world never took in is answered 409 with where it stands.",
    "group": "world",
    "permission": {
      "requires": [
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "piece_request_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Piece Request Id"
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
    "request": null,
    "responses": {
      "202": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/worlds/specification/drafts",
    "method": "post",
    "id": "draft_world_worlds_specification_drafts_post",
    "title": "Draft a world's specification from a description; nothing is made.",
    "description": "Ask the specification drafter for a proposal of ``body.description``, validate it as a\nperson's own values are validated, and sample one town of it when it is valid; make nothing.\n\nAnswered 503 where the instance has no model credential, before the specification is read.",
    "group": "world",
    "permission": {
      "requires": [
        "model.invoke",
        "world.read"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DraftBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "$ref": "#/components/schemas/WorldDraftView"
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
  },
  {
    "path": "/door/bridges",
    "method": "get",
    "id": "bridges_door_bridges_get",
    "title": "Bridges",
    "description": "The bridges this deployment offers this workspace, in words, and who runs each.",
    "group": "door",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Bridges Door Bridges Get"
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
  },
  {
    "path": "/door/grants",
    "method": "post",
    "id": "issue_grant_door_grants_post",
    "title": "Issue Grant",
    "description": "Issue a grant in one world for one bridge, or answer with the one this key issued.",
    "group": "door",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/exulanica__api__routes__door__IssueBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Issue Grant Door Grants Post"
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
  },
  {
    "path": "/door/grants",
    "method": "get",
    "id": "world_grants_door_grants_get",
    "title": "World Grants",
    "description": "The grants issued in one world, newest first, at most ``limit``, each as it stands now,\nand ``next``, the ``before`` that reads the page after them (null after the last): the first\npage holds every grant that may still stand. Reading a page settles the first of its grants\nthat ran out with something left to settle.",
    "group": "door",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 100,
          "minimum": 1,
          "default": 100,
          "title": "Limit"
        }
      },
      {
        "name": "before",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "maxLength": 200
            },
            {
              "type": "null"
            }
          ],
          "title": "Before"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response World Grants Door Grants Get"
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
  },
  {
    "path": "/door/grants/{grant_id}",
    "method": "get",
    "id": "one_grant_door_grants__grant_id__get",
    "title": "One Grant",
    "description": "",
    "group": "door",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response One Grant Door Grants  Grant Id  Get"
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
  },
  {
    "path": "/door/crossings/{arrival_id}/manifest",
    "method": "get",
    "id": "crossing_manifest_door_crossings__arrival_id__manifest_get",
    "title": "Crossing Manifest",
    "description": "What came across with one visitor and what stayed behind: the translation manifest its\narrival into this world (into the society ``version_id`` holds, when it is named) named, as\nthe door kept it, with its digest, and the bridge it came through in the words the\ndeployment declares for it (null for a bridge it no longer declares). One answer for an id\nthat names no arrival there.",
    "group": "door",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "arrival_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Arrival Id"
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
        "name": "version_id",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "Version Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Crossing Manifest Door Crossings  Arrival Id  Manifest Get"
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
  },
  {
    "path": "/door/grants/{grant_id}/revoke",
    "method": "post",
    "id": "revoke_grant_door_grants__grant_id__revoke_post",
    "title": "Revoke Grant",
    "description": "End a grant now. Revoking twice changes nothing.",
    "group": "door",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Revoke Grant Door Grants  Grant Id  Revoke Post"
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
  },
  {
    "path": "/door/grants/{grant_id}/credentials/revoke",
    "method": "post",
    "id": "revoke_credentials_door_grants__grant_id__credentials_revoke_post",
    "title": "Revoke Credentials",
    "description": "End every live invite and channel credential of a grant now, without ending the grant: after\na credential leaked, the owner ends them all and gives the bridge a new one.",
    "group": "door",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Revoke Credentials Door Grants  Grant Id  Credentials Revoke Post"
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
  },
  {
    "path": "/door/grants/{grant_id}/invites",
    "method": "post",
    "id": "invite_door_grants__grant_id__invites_post",
    "title": "Invite",
    "description": "A one-use invite to a standing grant of a server bridge, shown once, for a player of its\nbridge to use.",
    "group": "door",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Invite Door Grants  Grant Id  Invites Post"
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
  },
  {
    "path": "/door/grants/{grant_id}/channel-credentials",
    "method": "post",
    "id": "channel_credential_door_grants__grant_id__channel_credentials_post",
    "title": "Channel Credential",
    "description": "A channel credential for a standing grant, shown once: for a program its owner runs, or a\nserver bridge declared for this workspace alone.",
    "group": "door",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Channel Credential Door Grants  Grant Id  Channel Credentials Post"
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
  },
  {
    "path": "/door/grants/{grant_id}/send-away",
    "method": "post",
    "id": "send_away_door_grants__grant_id__send_away_post",
    "title": "Send Away",
    "description": "Send one of a grant's visitors home at the world's next minute, as its owner.",
    "group": "door",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SendAwayBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Send Away Door Grants  Grant Id  Send Away Post"
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
  },
  {
    "path": "/door/invites/redeem",
    "method": "post",
    "id": "redeem_door_invites_redeem_post",
    "title": "Redeem",
    "description": "Redeem one invite, as the bridge whose credential is presented, for a channel credential.",
    "group": "door",
    "permission": {
      "channel": "bridge"
    },
    "parameters": [],
    "request": {
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/exulanica__api__routes__door__RedeemBody"
          }
        }
      },
      "required": true
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Redeem Door Invites Redeem Post"
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
  },
  {
    "path": "/door/channel/hello",
    "method": "post",
    "id": "hello_door_channel_hello_post",
    "title": "Hello",
    "description": "Present the adapter, its mapping and the program's own words for this grant.",
    "group": "door",
    "permission": {
      "channel": "grant"
    },
    "parameters": [],
    "request": {
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/HelloBody"
          }
        }
      },
      "required": true
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Hello Door Channel Hello Post"
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
  },
  {
    "path": "/door/channel/answers",
    "method": "post",
    "id": "answer_door_channel_answers_post",
    "title": "Answer",
    "description": "Answer one open ask of this grant with one of the labels it offered.",
    "group": "door",
    "permission": {
      "channel": "grant"
    },
    "parameters": [],
    "request": {
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ChannelAnswerBody"
          }
        }
      },
      "required": true
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Answer Door Channel Answers Post"
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
  },
  {
    "path": "/door/channel/arrivals",
    "method": "post",
    "id": "arrive_door_channel_arrivals_post",
    "title": "Arrive",
    "description": "Send a visitor into the grant's world version: it arrives at the world's next minute.",
    "group": "door",
    "permission": {
      "channel": "grant"
    },
    "parameters": [],
    "request": {
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ArrivalBody"
          }
        }
      },
      "required": true
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Arrive Door Channel Arrivals Post"
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
  },
  {
    "path": "/door/channel/departures/{departure_id}/delivered",
    "method": "post",
    "id": "delivered_door_channel_departures__departure_id__delivered_post",
    "title": "Delivered",
    "description": "Report what the game delivered of what a departed visitor carried home.",
    "group": "door",
    "permission": {
      "channel": "grant"
    },
    "parameters": [
      {
        "name": "departure_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Departure Id"
        }
      }
    ],
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DeliveryBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Delivered Door Channel Departures  Departure Id  Delivered Post"
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
  },
  {
    "path": "/door/channel/gone",
    "method": "post",
    "id": "gone_door_channel_gone_post",
    "title": "Gone",
    "description": "Say the person behind one of the grant's visitors left the game.",
    "group": "door",
    "permission": {
      "channel": "grant"
    },
    "parameters": [],
    "request": {
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/GoneBody"
          }
        }
      },
      "required": true
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Gone Door Channel Gone Post"
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
  },
  {
    "path": "/door/channel/home",
    "method": "post",
    "id": "home_door_channel_home_post",
    "title": "Home",
    "description": "Call one of the grant's visitors home at the world's next minute, as its player asked.",
    "group": "door",
    "permission": {
      "channel": "grant"
    },
    "parameters": [],
    "request": {
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/HomeBody"
          }
        }
      },
      "required": true
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Home Door Channel Home Post"
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
  },
  {
    "path": "/door/channel/frames",
    "method": "get",
    "id": "frames_door_channel_frames_get",
    "title": "Frames",
    "description": "What was sent to this grant after the cursor, held up to the bridge's hold for something.",
    "group": "door",
    "permission": {
      "channel": "grant"
    },
    "parameters": [
      {
        "name": "after",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "maxLength": 200
            },
            {
              "type": "null"
            }
          ],
          "title": "After"
        }
      }
    ],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "title": "Response Frames Door Channel Frames Get"
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
  },
  {
    "path": "/world/invitations",
    "method": "post",
    "id": "issue_world_invitations_post",
    "title": "Issue",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/exulanica__api__routes__participation__IssueBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Issue World Invitations Post"
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
  },
  {
    "path": "/world/invitations",
    "method": "get",
    "id": "invitations_world_invitations_get",
    "title": "Invitations",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
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
        "name": "after",
        "in": "query",
        "required": false,
        "schema": {
          "anyOf": [
            {
              "type": "string",
              "format": "uuid"
            },
            {
              "type": "null"
            }
          ],
          "title": "After"
        }
      },
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "schema": {
          "type": "integer",
          "maximum": 100,
          "minimum": 1,
          "default": 50,
          "title": "Limit"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Invitations World Invitations Get"
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
  },
  {
    "path": "/world/invitations/{grant_id}",
    "method": "get",
    "id": "invitation_world_invitations__grant_id__get",
    "title": "Invitation",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.read"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Invitation World Invitations  Grant Id  Get"
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
  },
  {
    "path": "/world/invitations/{grant_id}/revoke",
    "method": "post",
    "id": "revoke_world_invitations__grant_id__revoke_post",
    "title": "Revoke",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "door.grant",
        "world.write"
      ]
    },
    "parameters": [
      {
        "name": "grant_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Grant Id"
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
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Revoke World Invitations  Grant Id  Revoke Post"
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
  },
  {
    "path": "/participation/notice",
    "method": "get",
    "id": "notice_participation_notice_get",
    "title": "Notice",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "additionalProperties": true,
              "type": "object",
              "title": "Response Notice Participation Notice Get"
            }
          }
        }
      }
    }
  },
  {
    "path": "/participation/redeem",
    "method": "post",
    "id": "redeem_participation_redeem_post",
    "title": "Redeem",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
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
    "request": {
      "required": true,
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/exulanica__api__routes__participation__RedeemBody"
          }
        }
      }
    },
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "type": "object",
              "additionalProperties": true,
              "title": "Response Redeem Participation Redeem Post"
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
  },
  {
    "path": "/participation/{grant_id}",
    "method": "get",
    "id": "grant_participation__grant_id__get",
    "title": "Grant",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "additionalProperties": true,
              "type": "object",
              "title": "Response Grant Participation  Grant Id  Get"
            }
          }
        }
      }
    }
  },
  {
    "path": "/participation/{grant_id}/world",
    "method": "get",
    "id": "world_participation__grant_id__world_get",
    "title": "World",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "additionalProperties": true,
              "type": "object",
              "title": "Response World Participation  Grant Id  World Get"
            }
          }
        }
      }
    }
  },
  {
    "path": "/participation/{grant_id}/society",
    "method": "get",
    "id": "society_participation__grant_id__society_get",
    "title": "Society",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
    "parameters": [],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {
              "additionalProperties": true,
              "type": "object",
              "title": "Response Society Participation  Grant Id  Society Get"
            }
          }
        }
      }
    }
  },
  {
    "path": "/participation/{grant_id}/world/tiles/{baked_tile_id}/bytes",
    "method": "get",
    "id": "tile_participation__grant_id__world_tiles__baked_tile_id__bytes_get",
    "title": "Tile",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
    "parameters": [
      {
        "name": "baked_tile_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "format": "uuid",
          "title": "Baked Tile Id"
        }
      }
    ],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/participation/{grant_id}/world/files/{sha256}",
    "method": "get",
    "id": "file_participation__grant_id__world_files__sha256__get",
    "title": "File",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
    "parameters": [
      {
        "name": "sha256",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "title": "Sha256"
        }
      }
    ],
    "request": null,
    "responses": {
      "200": {
        "description": "Successful Response",
        "content": {
          "application/json": {
            "schema": {}
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
  },
  {
    "path": "/participation/{grant_id}/leave",
    "method": "post",
    "id": "leave_participation__grant_id__leave_post",
    "title": "Leave",
    "description": "",
    "group": "participation",
    "permission": {
      "requires": [
        "world.enter"
      ]
    },
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
    "request": null,
    "responses": {
      "204": {
        "description": "Successful Response"
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
];
