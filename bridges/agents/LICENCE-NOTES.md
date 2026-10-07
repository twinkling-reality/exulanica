# Licence notes: the agents' side of the door

- Everything in this folder is ours, under the repository's licence (Apache-2.0).
- The library (`exulanica_agent`, everything but `mcp_server.py`'s serving functions) needs the
  Python standard library only. Nothing is vendored.
- The MCP facade needs the MCP Python SDK, an optional dependency installed by whoever runs the
  facade (`exulanica-agent[mcp]`): `mcp` 2.3.0, MIT, its licence read on 2026-10-06 at the
  release's tag (Copyright (c) 2024 Anthropic, PBC). Its resolved dependencies on 2026-10-06, as
  each installed package states its licence: MIT (`mcp-types`, `anyio`, `attrs`,
  `annotated-types`, `h11`, `jsonschema`, `jsonschema-specifications`, `pydantic`,
  `pydantic_core`, `PyJWT`, `referencing`, `rpds-py`, `truststore`, `typing-inspection`), MIT-0
  (`cffi`), BSD-3-Clause (`click`, `httpcore2`, `httpx2`, `idna`, `pycparser`, `sse-starlette`,
  `starlette`, `uvicorn`), Apache-2.0 (`opentelemetry-api`, `python-multipart`), Apache-2.0 or
  BSD-3-Clause (`cryptography`) and PSF-2.0 (`typing_extensions`). None of them is in the
  product's lock file.
- The agents' mapping file names one look for an agent's own body, `people-catalog` version 1 from
  the product's thing catalogs, CC0-1.0.
- The quickstart's mind is a model the developer calls with their own Nebius Token Factory account,
  under that service's terms and the model's licence (Qwen3 235B Instruct: Apache-2.0; Nemotron 3
  Nano: the NVIDIA Open Model License).
