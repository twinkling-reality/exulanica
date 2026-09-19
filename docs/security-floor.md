# Security floor

- Status: mixed, labelled per claim. See [README.md](README.md) for the status convention.
- Date: 2026-09-16.
- Relationship to other documents: this is what the code enforces for four controls that
  [privacy-consent-threat-model.md](privacy-consent-threat-model.md) and
  [evaluation-methodology.md](evaluation-methodology.md) already name. Where either document
  describes a control more strongly than this one, this one describes the code.

Four controls, and one rule about them. **No on-demand tile route and no lens may ship until all
four exist**, because each of those is the first thing in the system that turns one request into
unbounded compute or into traffic leaving the process. Before them, a bearer token reached every
router, nothing limited egress, and row-level security was the only thing standing where a route
permission should have been: a second boundary carrying a first boundary's load.

Each section says what the control enforces, where, what it does not cover, and how it is
configured. None of the four has a default. A setting that is absent refuses; it is never read as
permission.

## 1. Route permissions

**What it enforces.** CLOSED. Every mounted route requires a declared set of permissions, or is
declared public with the reason it needs no credential, or is declared part of the sign-in surface
(`/auth/google/start`, `/auth/google/callback`, `/auth/session`, `/auth/logout`), which needs no
prior credential because it is where a browser credential is issued, reported and ended, and which
checks its own login cookie, provider state, origin and CSRF token. A request whose token does not hold every
required permission is refused before the route runs, before path, query and body validation, and
before a database connection is opened for the route.

- Declared in `exulanica/api/permissions.py`, `ROUTE_RULES`. The vocabulary is the closed enum
  `Permission`: `library.read`, `library.write`, `model.invoke`, `intake.write`, `deletion.write`,
  `consent.read`, `consent.write`, `admission.read`, `admission.write`, `world.read`,
  `world.write`, `operations.read`, `operations.write`, `tiles.materialise`. There is no wildcard.
- Enforced in `exulanica/api/dependencies.py`, `authorise_route`, installed on the application by
  `exulanica/api/app.py` as an application-level dependency, so no route can leave it out.
  `current_session`, which every authenticated route depends on, applies the same check again for
  an application built some other way.
- Build-time check: `create_app` refuses to build when a mounted route has no declaration or a
  declaration names a route that is not mounted. The comparison is against
  `exulanica.api.routes.routable_paths`, the one walk of the router tree. A route any lane adds under
  `exulanica/api/routes/` therefore needs one line in `ROUTE_RULES` before any test that builds the
  application passes.
- Enforced by `tests/test_route_permissions.py`, which sweeps every route from the router with a
  real request and reads the status.

**Who holds what.** DECISION. A bearer token holds exactly the permissions its grant names. A
browser session holds `ACCOUNT_OWNER_PERMISSIONS`: `admission.read`, `admission.write`,
`consent.read`, `consent.write`, `deletion.write`, `intake.write`, `library.read`,
`library.write`, `model.invoke`, `operations.read`, `operations.write`, `world.read` and
`world.write`, which is every permission except `tiles.materialise`. That grant is keyed on the
membership role, not assumed: a browser session exists only for an account membership, migration
0058 allows one role, `owner`, and `AccountRepository.session` requires it.
`tests/test_route_permissions.py` reads 0058's check and fails when a second role appears, until
that role is given a grant of its own. `tiles.materialise` is withheld from a browser session, and
that is now an open decision rather than a pending event: three routes require it, so a browser
session cannot ask for a generated world or read a tile's bytes until somebody grants it here
deliberately. An explicit Authorization header never falls back to the
cookie. Rejected alternative: letting a browser session inherit whatever a bearer token would hold,
which has no source to inherit from.

**Routes that reach a model** require `model.invoke` beside their read or write permission:
`/selection/plan`, `/selection/ask`, `/selection/appearance`, `/selection/environment` and
`POST /world/versions/{version_id}/society/decisions`, which reaches the society decision provider
through `request_decision` without the endpoint naming a model client. The test that finds them
reads each endpoint's source for all three markers.

**The status a refusal carries.** DECISION. On a route addressed by an id (a `{parameter}` in its
path), a missing permission answers `404 unknown_reference` with one fixed detail, identical for a
real id, a foreign id and an invented one, because M10 scores any 403 on such a route as an
existence leak. Everywhere else it answers `403 not_authorised` naming the missing permission,
because there is no other tenant to leak. Rejected alternative: 403 everywhere. It is not an oracle
when decided before lookup, but M10 cannot tell why a 403 was issued, and the rule in
`exulanica/api/app.py` already says 404 on an id.

**Consent withdrawal.** DECISION. `consent.write` covers granting, revoking and withdrawing a
person's consent and linking and unlinking subject regions, so a credential that may grant consent
may always withdraw it. `deletion.write` covers deleting a companion memory and revoking a
confirmed identity or place decision. Rejected alternative: all withdrawals under
`deletion.write`, which would let a token grant a consent it could not withdraw.

**The record of a refusal.** CLOSED. Each refusal is counted in `route_permission_refusal`
(migration `0061_route_permissions.sql`), one row per workspace, actor, method and route template,
under `enable` and `force row level security` with `ws_isolation`. Only the route template is
stored, never the requested URL. The trigger calls `assert_workspace_context` first and owns both
timestamps. The runtime role holds no DELETE on it.

**Configuration.** Every grant in `EXULANICA_API_TOKENS` must carry `permissions`:

```json
{"<token>": {"workspace_id": "<uuid>", "actor": "<uuid>",
             "permissions": ["library.read", "world.read"]}}
```

A grant with no `permissions`, an empty list, a duplicate, a non-string or a name outside the
vocabulary does not load, and the API does not start.

**What it does not cover.** OPEN, each item.

- It is bearer-token authorisation against an operator-configured table. It is not an account
  system and adds no expiry, rotation or revocation beyond editing the configuration.
- A route mounted as a plain Starlette route or an ASGI mount rather than a FastAPI route does not
  receive application-level dependencies. Today only the documentation routes are of that kind,
  and all are declared public. A `Mount` of a non-router application is also invisible to
  `routable_paths`, so the build-time check would not see it.
- Permissions are per route, not per body. A route that does two things with one body grants both
  with one permission.
- Row-level security still decides which rows a permitted route can see; a permission never widens
  that.

## 2. Per-workspace tile quotas

**What it enforces.** CLOSED. A workspace may have at most `tiles_limit` tiles materialised on
demand. A request to a route whose declaration requires `tiles.materialise` is charged before the
route runs, and refused with `429 tile_quota_exceeded` when the charge would cross the ceiling. A
workspace with no declared quota is refused with `429 tile_quota_undeclared`.

HOW MANY TILES ONE REQUEST COSTS IS THE ROUTE'S DECLARATION, NOT A CONSTANT. `authorise_route`
charges `TILES_PER_REQUEST`, which is 1, for every such route except those listed in
`SELF_CHARGING_TILE_ROUTES`, which charge their own and say why. `POST /world-generation/worlds`
charges one tile per tile the specification covers, counted from the resolved extents before a
record is made, because one request there can cover up to the 16 by 16 tiles the declared extent
range allows and a flat charge of one would be wrong by the size of the world.

- Declared per workspace in `workspace_tile_quota` (migration `0062_workspace_tile_quotas.sql`),
  under `enable` and `force row level security` with `ws_isolation`. `tiles_used` only rises; a
  check constraint keeps it at or under `tiles_limit` even for a write that bypasses the code.
- Enforced in `exulanica/api/dependencies.py`, `authorise_route`, through
  `exulanica/api/quotas.py`, `charge_tiles`, as the runtime role on a workspace-scoped connection.
  The permission check runs first, so a refused request charges nothing.
- Enforced by `tests/test_workspace_tile_quotas.py` through a real request against a probe route
  mounted for that test only. No tile route ships.

**Configuration.** An operator declares a ceiling with `declare_tile_quota`. There is no default
ceiling, and raising one is deliberate.

**What it does not cover.** OPEN.

- It is a ceiling, not a rate. A window needs a clock and is the tile route's policy to declare.
- The charge is one tile per request. A route that materialises several tiles per request must
  declare that before it ships.
- The charge is not refunded when materialisation fails. That is pessimistic on purpose.

## 3. Egress allowlist

**What it enforces.** CLOSED. The model transport and Google sign-in reach only declared origins. Each origin is a
scheme, a lowercase DNS host name and a port. Matching is exact: a subdomain, a different port, a
userinfo prefix, a trailing-dot host, an IP literal in any spelling a resolver accepts, a
backslash, whitespace or a non-ASCII character is refused. Plain `http` is accepted only for
`localhost`. A refusal is `EgressRefused` from `exulanica/models/egress.py`, logged as a warning,
never retried and never failed over, and the API answers it with `502 egress_refused`.

- Declared in `EXULANICA_EGRESS_ALLOWLIST`, a JSON array of origins, for example
  `["https://api.tokenfactory.nebius.com"]`. Absent, empty or malformed refuses at load time.
  A deployment that runs the catalog preflight also needs the catalog's origin,
  `https://tokenfactory.nebius.com`, which is a different host from the endpoint.
- Enforced in `exulanica/models/transport.py`. `HttpxTransport` will not build its network client
  without an allowlist. It checks each URL before the client is called, and a transport mounted
  inside the client checks each request again immediately before a connection is opened, which is
  the check a redirect hop would pass through. Redirects are not followed. Environment proxy
  variables are ignored by the client it builds.
- Enforced at startup in `exulanica/models/client.py`: `ModelClient` refuses to construct when the
  manifest's `base_url` is not declared.
- Enforced for Google sign-in in `exulanica/api/account_runtime.py`. When sign-in is configured,
  `load_account_runtime` stops startup unless the list includes `https://accounts.google.com`
  (discovery), `https://oauth2.googleapis.com` (token) and `https://www.googleapis.com` (JWKS),
  alongside whatever else it declares. The provider is handed only those three, through the same
  mounted check (`allowlisted_transport`, which serves `httpx2` as well as `httpx`), so sign-in
  cannot reach the model endpoint and the model client cannot be pointed at Google by accident. A
  provider with no allowlist and no test transport refuses at its first network call. A refusal is
  logged with the origin it refused, and sign-in fails closed as `503 account_unavailable`.
- Operational consequence, OPEN by nature: if Google moves its token endpoint or JWKS to another
  host, sign-in fails closed before any request to the new host, because
  `GoogleOIDCProvider.metadata` compares the discovery document with its pinned URLs. The fix is
  to update those pinned URLs and add the new origin to `EXULANICA_EGRESS_ALLOWLIST`; the
  allowlist entry alone is not enough. [deployment.md](deployment.md) says the same for an
  operator.
- Enforced by `tests/test_egress_allowlist.py`, which proves an unlisted host is refused with no
  socket opened, and proves the socket patch is live by letting a listed host reach it.

**What it does not cover.** VERIFIED against the tree on 2026-09-16 by
`tests/test_egress_allowlist.py::test_the_list_of_uncovered_network_modules_is_complete`, which
fails when the list below changes.

This is a development and deployment safety rail, described as one, and it is not a substitute for
the network's own limit. **A process-level allowlist is not a network-level one.** The sentence in
the threat model that egress "is allowlisted" is true of the model transport and Google sign-in and
of nothing else:

- `exulanica/environment/nyc_open_data.py`, `exulanica/environment/owned_district.py` and
  `exulanica/evaluation/benchmark.py` open URLs with `urllib` and do not pass through it.
- The test that keeps this list true matches `urlopen`, `httpx` and `httpx2` clients,
  `OAuth2Client`, `requests`, `aiohttp`, `urllib3` and `socket.create_connection`. It first
  matched `httpx` alone and missed the sign-in path, which used `httpx2`; a client library outside
  that pattern would be missed the same way.
- Any code that builds its own HTTP client or socket does not pass through it.
- It checks the host name, not the address the name resolves to. A declared host whose DNS answer
  changes is reached wherever the answer points.
- A compromised process can simply not call it.
- A test double passed as the transport's client reaches no network and is not policed. A real
  `httpx.Client` passed that way is refused without an allowlist, and
  `tests/test_egress_allowlist.py` fails if package code passes a client at all.

Threat F1 in [evaluation-methodology.md](evaluation-methodology.md) expects "egress blocked by
allowlist; URL inert; alert". The first and last parts now hold for the model transport. Whether a
URL in model output is rendered inert is a rendering property this control does not touch.
An egress control at the network, which a deployment should add, is OPEN.

## 4. Per-lens budgets

**What it enforces.** CLOSED. A lens runs under four ceilings: `max_tokens`, `max_calls`,
`max_wall_clock_ms` and `max_cost_usd`. Every request is reserved against all four before it is
sent, pessimistically: the caller's `max_tokens` plus an over-estimate of the prompt, the worst-case
price, one call, and the full per-call timeout. A request that could cross any ceiling is refused
with `LensBudgetExceeded`, which is a `BudgetExceededError`: the chain does not retry it, its message
says never to retry it, and the API answers it with 429. A reported call replaces its reservation
with what it cost; a request that failed without a report stays charged at its worst case.

- Declared in `EXULANICA_LENS_BUDGETS`, a JSON object mapping a lens name to exactly those four
  fields. Ceilings are integers; the cost is a decimal string. A JSON float anywhere in the document
  is refused. A lens with no declared budget is refused by `budget_for`.
- Enforced in `exulanica/models/lens_budget.py`, `LensBudgetGuard`, which has the shape of
  `exulanica/models/budget.py`, `BudgetGuard`, and plugs into `ModelClient(budget=...)`. Use
  `LensBudgetGuard.model_client`, which sets the client's timeout to the guard's per-call timeout
  and one attempt, so the wall-clock reservation describes the client.
- A lens record references its budget by `LensBudget.digest()`, sha256 over canonical JSON with the
  cost as a quantised decimal string. No clock reading enters that digest, the usage document or a
  refusal record.
- Enforced by `tests/test_lens_budgets.py`, one refusal per axis with the other three shown inside
  their ceilings, each through a real `ModelClient` whose transport is shown not to have been called.

**What it does not cover.** OPEN.

- The wall clock bounds when a call may start, not how long a started call runs: httpx has no
  total-request timeout, so a response that arrives slowly inside each per-operation timeout is not
  cut off.
- The guard is in memory. A durable ledger of lens spend and refusals belongs to the lens lane.
- A process-wide guard can be passed as `process=` so a lens cannot exceed it; nothing forces a
  caller to pass one.

## What still waits on another lane

- OPEN. **The SELECT-only `exulanica_ro` role for lenses** waits on `exulanica/db/roles.py`, which
  is being changed in another worktree. **No lens may run without it.** A lens that reads through
  the write role is a lens that can write, and none of the four controls above prevents that.
- OPEN. A process-level sandbox exists only for the gsplat container. Nothing here adds one.
