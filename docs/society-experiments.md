# Society experiments

The society experiment surface records controlled comparisons over an existing
`exulanica-society/v4` society. It freezes the exact immutable input rows used by both arms and
reserves development attempts. Preparing or reserving a record does not run a simulation.

## HTTP surface

All routes are scoped by the authenticated session's workspace and by the authored version in the
path.

| Method and path | Permission | Result |
| --- | --- | --- |
| `POST /world/versions/{version_id}/society/experiments` | `world.write` | Records one immutable definition |
| `GET /world/versions/{version_id}/society/experiments/{experiment_id}` | `world.read` | Reads the compact definition |
| `POST /world/versions/{version_id}/society/experiments/{experiment_id}/attempts` | `world.write` | Reserves one development attempt |
| `GET /world/versions/{version_id}/society/experiments/{experiment_id}/attempts/{attempt_id}` | `world.read` | Reads compact attempt status and a terminal result or failure |

The client supplies idempotency UUIDs, immutable input sequence numbers, explicit workload bounds,
and a supported intervention identity. The server resolves the society and full input documents.
It verifies those documents through the configured `SocietyRuntime` authority before recording or
reading an experiment. The request cannot supply an input document, definition document,
checkpoint, execution evidence, result, or failure record.

An experiment or attempt under the wrong workspace, version, or parent experiment is an unknown
reference. A withdrawn source makes its historical experiment unavailable rather than preserving
access to stale geometry or rights.

## Definitions

The supported definitions are:

| Intervention | Input rule |
| --- | --- |
| `noop` | Baseline and treatment name the same genesis input |
| `add_rest_amenity` | The treatment is the next input and adds exactly one enabled authored rest target backed by the reviewed marker-plate asset |

The stored definition binds the source society, world and authored version, the treatment's
authored cursor, both immutable input sequence and digest pairs, the deterministic routine, the
development and held-out seed commitments, and the predeclared metrics. Public reservation accepts
only a seed from the committed development split. The held-out split cannot be reserved through
this HTTP surface.

Work is bounded to a population from 1 through 256, warm-up and follow-up lengths from 1 through
1,440 ticks each, and at most 500,000 person-ticks under the definition's paired-run accounting.
Definition records are limited to 256 KiB.

## Attempt lifecycle

An attempt reservation is an append-only fact. Its initial status is `incomplete`, which means no
terminal outcome has been recorded. Internal bounded execution may add one sealed checkpoint and
then exactly one `completed` or `failed` outcome. Reusing an experiment or attempt UUID with the
same canonical content is idempotent; reusing it with different content is a conflict.

The HTTP request path does not prepare checkpoints, advance either arm, call a worker or model, or
finalize outcomes. Those operations remain internal repository and deterministic-core work.

## Compact reads

Attempt reads return the definition, seed, checkpoint, evidence, result and failure digests that
exist for the record. A completed result includes each arm's raw metric numerators and denominators,
safety counts, evidence counts and digests, and exact signed comparisons. A failed result includes
the bounded server-defined failure code and detail. The response never includes checkpoint state or
full execution evidence.

There is no evidence download or portable experiment package endpoint. A digest in the compact
response identifies a persisted artifact but does not by itself provide an export surface.

## Independent read-only consumer

[`scripts/society_experiment_result_client.py`](../scripts/society_experiment_result_client.py)
is a small consumer of the two GET routes. It imports no Exulanica implementation. Its caller
provides an HTTP client that already owns base URL, authentication, timeout and transport policy,
then supplies the three explicit resource identifiers:

```python
outcome = read_experiment_result(
    http,
    version_id=version_id,
    experiment_id=experiment_id,
    attempt_id=attempt_id,
)
```

The consumer requests the definition projection first and the nested attempt second. It validates
the path identities, lifecycle combination, digest syntax and cross-response bindings before
exposing metrics. For a completed result it independently checks the supported result profile and
canonical result digest. The compact definition digest is only an identity binding because the GET
response does not contain the full canonical definition document.

The consumer requests `Accept-Encoding: identity` and refuses a response carrying a nonidentity
`Content-Encoding` before reading its body. Identity-encoded response bodies are read in bounded
chunks through byte ceilings before JSON buffering. An over-limit or compressed lazy response is
closed without consuming the remainder. The ceiling governs work performed through the supplied
lazy streaming transport; it cannot undo buffering a caller or upstream transport completed before
the response context was returned. The consumer uses only GET, rejects duplicate JSON fields and
does not request checkpoint state or execution evidence.

The outcome status is one of `valid`, `invalid_pair`, `incomplete`, `failed` or `unavailable`.
Metric numerators and denominators remain integers exactly as served. A missing or zero denominator
marks that metric unavailable; it is not interpreted as zero effect. `left_minus_right` means the
stored treatment arm minus baseline comparison. The consumer makes no significance, held-out,
external replay, production authentication or real-human-effect claim.

## Browser result view

An authenticated saved world exposes **Recorded comparison** from the World menu. The view fixes
the authored version to the active saved-world entry and asks for the experiment and attempt UUIDs
printed on an existing record receipt. It then uses the two GET routes above to verify and present
that one compact result. The browser does not offer a record list, preparation, reservation,
execution or finalization control.

The view presents stored baseline and treatment fractions, signed server-recorded deltas, safety
summaries, exact record bindings, unsupported metrics, lifecycle failures and unavailable records
without reinterpreting them. Closing the view cancels its active read. Opening another identity
supersedes the prior read, so a late response cannot replace the current result.

## Local reserved-attempt execution

The local experiment runner accepts a current server session and one exact already-reserved
development attempt identity. It rejects held-out phases and seeds before checkpoint preparation,
arm computation or explicit abort; a held-out reservation remains incomplete. Trusted host
composition must supply current permission to execute the development reservation. The
reservation's `created_by` field remains attribution and does not grant execution. The runner also
applies the configured society runtime's current input authorization, including workspace/version
registration, immutable stored-input equality, current environment-source operation rights and
withdrawal state, required byte integrity, authored-source validity, frame and affordance registry
bindings, and reviewed-asset availability.

Checkpoint preparation and paired-arm computation run outside database transactions. Checkpoint
and result replay use an open idle autocommit connection before each short append transaction, as
required by the repository. Each phase reloads the reservation and rechecks execution and source
authorization. Checkpoint, completion and failure appends recheck execution permission again after
taking the attempt lock, including after result replay. A crash, missing authorization or other
exception before a terminal append leaves the attempt incomplete and retryable. A retry reuses the
exact sealed checkpoint. An explicit operator abort records a bounded development failure.
Competing runners may duplicate deterministic computation, but attempt locking and the append-only
outcome allow only one terminal record.

Only a pair with canonical arm evidence is recorded as completed. A core `invalid_pair` refusal has
no arm evidence, so this runner records it as a failed `execution_refused` outcome with the bounded
core refusal code and detail. The compact read schema can represent `invalid_pair`, but this runner
does not fabricate evidence or persist that state as a completed result. Execution remains a local
composition capability; there is no HTTP execution route, queue discovery or browser launch control.
