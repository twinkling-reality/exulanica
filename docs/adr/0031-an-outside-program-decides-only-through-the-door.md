# ADR-0031: An outside program decides for a world's things only through the door

- Status: Accepted
- Date: 2026-10-06
- Related: [door contract](../door-contract.md), [decision roles contract](../decision-roles-contract.md),
  [world memory model, simulation adapter boundary](../world-memory-model.md#simulation-adapter-boundary)

## Context

A world's things are decided for by the world's own routine, by an open model its owner chose, or
by its owner's direct request. Outside programs, such as a game's adapter or an agent another person
runs, could not decide for anything: the decision records named only models, there was no per-world
credential an outside program could hold, no route to read the options a thing has or to answer
them, and nothing to replay such an answer from. Connecting a game is the first such program, and a
second game should need nothing new in the product.

## Decision

- **One door for every outside program, in its own package** (`exulanica/door`), reached only
  through the HTTP surface. The product holds no game's name and imports nothing of an adapter; a
  game is an adapter outside the product plus a mapping file, which is data.
- **Bridges are declared by the deployment** (`EXULANICA_DOOR_BRIDGES`), with who runs the program
  (a shared game server, or each world's owner on their own machine), whether its choices are an
  AI's, a server's credential digest, the mapping digests and adapter versions they may present,
  their own hold and answer deadline, and whether they are offered to every workspace. A program is
  admitted as a model is: by deployment configuration, never by a route. Who runs it decides how its
  grants open: a server by invites its own credential redeems, a program the owner runs by a
  credential handed to that owner.
- **A world's owner issues grants**: one bridge, one world, a bounded scope, an end, revocable, kept as
  appended revisions. A revocation is a withdrawal of permission, carried by a restore from an older
  backup like any other. A grant opens through a single-use invite of 80 bits that a bridge redeems
  with its own deployment credential, or through a channel credential of 256 bits; both are stored as
  digests in the one door table outside every workspace, read before any workspace is known, and
  no backup carries them, so a restore voids every credential and owners open their grants again.
- **A bridge dials out and reads by long-poll over HTTPS.** It receives the same request a model is
  shown and answers with one of the labels offered; the decision host writes the receipt, so replay
  needs no bridge. The world keeps its clock: a late or missing answer falls to the routine.
- **An answer is tied, in the database, to its ask, a standing grant and whoever gave it**: the
  adapter version, mapping and declaration its own hello named. A grant answers to one program at a
  time: it has one live channel credential, and only a hello said under that credential counts, so
  a receipt never names an adapter that did not answer and no answer outlives a revocation.
- **Door credentials and account credentials never overlap**, by a route declaration kind of their
  own (`Channel`), and the owner permission that issues grants (`door.grant`) is isolated by name.

## Rejected alternatives

- **WebSocket transport.** At least one target game engine gives its scripts HTTP requests and no
  socket, short of lifting its sandbox, so a WebSocket door would need a sidecar beside every game
  server. Long-poll serves every adapter with one protocol and fits the API's credentials, route
  declarations, probes and admission classes. A WebSocket transport can be added over the same frames
  if many visitors per server is measured to need it.
- **Bridges registered through a route.** A registration surface would be a surface for registering
  anything, across workspaces; the deployment already decides which programs and models it admits.
- **Channel credentials kept by the authentication role.** That role exists only where browser
  accounts are configured and reaches only the account tables, so the door would be unavailable in
  token-only deployments and tests. The door's table holds only digests and identifiers instead, and
  the runtime role may change only when a secret was used or revoked.
- **An outside program writing world state.** Every effect stays an offered option the engine checks
  again in its minute; a program proposes and the engine decides, as for a model.
- **Game data in decision records.** Receipts and requests carry no free-form data from a program,
  only the fixed fields the external record states. A program's declared name, maker and mind are
  kept beside the door's answers for a card, never in a society record or a model's context.
- **A redemption lockout per bridge.** One player typing wrong codes at a shared server would lock
  every other player out, across workspaces. The lockout is per requester, a digest the bridge
  derives for whoever typed the code; 80 random bits are not guessed either way.

## Consequences

- A game is connected by writing an adapter and a mapping file and declaring a bridge; the product's
  code does not change, and a source guard and the import contracts hold that.
- An outside decider's history replays from receipts alone, and comparisons run an externally decided
  thing by its routine in every arm, since a program cannot be asked again for another arm.
- The door's tables outside every workspace are read on a connection that declares no workspace, and
  are limited to digests, identifiers and the two timestamps the runtime may set; they are pruned
  past their retention by one function with its owner's rights, since the runtime deletes nothing.
