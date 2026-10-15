# World project evidence format

This contract describes the evidence file of a world project, profile
`exulanica.world-project-evidence/v1`, field by field, for Exulanica and for outside programs that
read it, such as session report and agent performance tools. The project workflow that writes and
publishes these files is described in
[the world memory package's checkpoint section](world-memory-package.md#editable-repository-checkpoints).

An evidence file records what happened while models decided for beings in one session of a world:
the decisions a society recorded, the model assignments they were made under and, when the owner
asked for it, readable text. It is evidence, not part of the world definition. A project keeps one
file per session at `evidence/<session>.json`, beside `world-project.json`.

The JSON Schema of the profile is committed at
`exulanica/world_package/projects/schemas/world-project-evidence.v1.json` and is regenerated from
the code by a test that fails on any difference. `python -m exulanica.world_package.projects
evidence-schema` prints the same schema.

## Encoding

A file is one JSON object in UTF-8, written with sorted keys and two-space indentation. Integers
only: no floats, no `NaN`, no duplicate keys. Money is a decimal string in US dollars. Durations
are integer milliseconds. Identifiers match `[a-zA-Z0-9:._/-]`, at most 200 characters. Digests are
lowercase hex SHA-256. A file is at most 2 MiB and holds at most 1024 decisions; a longer session
continues in files named `<session>-2.json`, `<session>-3.json` and so on, whose `session_id` ends
in `:2`, `:3`.

The file's digest is the SHA-256 of its canonical form: Exulanica canonical JSON of the object
with `models` sorted by thing and model (two assignments of one thing to one model, which differ
only in what they record, by their canonical bytes), `decisions` sorted by `tick` then
`record_id`, and absent optional fields left out rather than written as null.

## The file

| Field | Type | Meaning |
| --- | --- | --- |
| `profile` | string | Always `exulanica.world-project-evidence/v1`. |
| `project_id` | identifier | The project the file belongs to; equals the project's `world-project.json`. |
| `session_id` | identifier | The session, unique within the project. |
| `source` | object | The world version the decisions were recorded in (below). |
| `models` | array, 1 to 256 | The model assignments the decisions were made under (below). |
| `decisions` | array, 1 to 1024 | The recorded decisions (below). |
| `coverage` | object, optional | Which of the session's decisions the file holds (below). Absent in files written before it existed: treat as unknown. |
| `captured_at` | string, optional | When the session's first file was written, UTC, `YYYY-MM-DDTHH:MM:SSZ`. Later captures of the same session keep it. |
| `living_session` | object, optional | The living session the file is the evidence of (below). The file's `session_id` is then `session:<its session_id>`, with `:2`, `:3` for continuations. |

### `coverage`

| Field | Type | Meaning |
| --- | --- | --- |
| `decisions` | `consumed` or `all` | `consumed`: only decisions a minute of the world took up are present. A request that never got a usable answer and was never taken up (an unavailable answer, a timed-out call) is absent, so counts of those, the acceptance denominator and timeout streaks cannot be computed from the file. `all`: every request of the session is present. |

### `living_session`

A living session is one bounded stretch of a society's playback, opened and closed by two receipts
of its playback history ([synthetic society contract](synthetic-society-contract.md#living-sessions)).
The block carries those receipts and the spending authority's figures as read when the file was
captured. It carries no account, actor, request or bound identity.

| Field | Type | Meaning |
| --- | --- | --- |
| `session_id` | UUID string | The society's session identity. |
| `state` | `open` or `closed` | The session's state when captured. |
| `opened` | object | `tick` (the minute it started from), `at` (UTC instant), `state_sha256` (the state it started from) and `limits`. |
| `at` | string | A receipt's UTC instant, `YYYY-MM-DDTHH:MM:SSZ`. |
| `limits` | object | As recorded when it opened: `wall_seconds`, `minutes`, `decisions`, `usd` and `calls`. |
| `wall_seconds` | integer | Wall-clock seconds: the limit, or what was used. |
| `minutes` | integer | World minutes: the limit, or what was played. |
| `usd` | decimal string | US dollars: the limit, or what the bounds committed. |
| `calls` | integer | Model calls: the limit, or what the bounds committed. |
| `closed` | object or null | Null while open. Otherwise `tick` (the minute it ended at), `at`, `state_sha256`, `reason` and `by`. |
| `reason` | code | Why it closed, as the society records it, for example `session_minutes`, `session_spending_limit`, `session_liability_unknown`, `stopped_by_person`. The words for a code belong to the society's own table. |
| `by` | `system` or `person` | `person` for `stopped_by_person` and `paused_by_person`, `system` for every other code. |
| `spending` | object | `used` and `bounds`, below: spending as found, never a bill. |
| `used` | object | What the session used of each limit: `wall_seconds`, `minutes`, `decisions`, `usd`, `calls`, and `unresolved_count` and `unresolved_usd`, calls whose cost is not known until an operator reconciles them, counted at their reservation, the most they can have cost. |
| `bounds` | array | One entry per provider the session could ask. |
| `provider` | identifier | The model provider the bound is for. |
| `ceiling_usd` | decimal string | The bound's ceiling. |
| `committed_usd` | decimal string | What the bound committed. |
| `committed_calls` | integer | The calls it committed. |
| `known_usage_usd` | decimal string | The part computed from reported tokens at the listed price. |
| `unresolved_count` | integer | Calls whose cost is unknown until an operator reconciles them. |
| `unresolved_usd` | decimal string | Reservations of calls whose cost is unknown, at most what they cost. |
| `reconciled_usd` | decimal string | What reconciliation had settled when captured. |

A bound's `state` is `open` or `closed`. An open session's block may later
become closed, and its spending may change while it is open; a closed block never changes, even
when a later reconciliation settles an unknown cost, which is recorded as a new entry naming the
session and the provider rather than as an edit. When the session read lists every decision asked
in the session's minutes (its `decisions_read.counted` equals its `decisions_read.total`), the
file's `coverage` is `all` and requests no minute took up are present with their receipts;
otherwise capture enumerates the decisions minutes took up and the file's `coverage` is
`consumed`. Each listed request's full record is still read one by one: the session list names
each request and its status, but a decision in this format also needs what only the receipt holds
(its source record digest, offered options, choice, latency, tokens and cost).

### `source`

| Field | Type | Meaning |
| --- | --- | --- |
| `world_id` | identifier | The world. |
| `version_id` | identifier | The world version the session ran in. |
| `snapshot_id` | identifier | The version's source snapshot. |
| `state_sha256` | digest | The version's state when it was captured. |
| `snapshot_sha256` | digest | The source snapshot's digest. |

### `models[]`: a model assignment

| Field | Type | Meaning |
| --- | --- | --- |
| `thing_id` | identifier | The placed being the model decided for. |
| `role` | identifier | The decision role (for example `society_decision`). |
| `contract_sha256` | digest | The decision contract the requests were asked under. |
| `model_manifest_sha256` | digest | Digest of `{provider, model_id, revision}`. |
| `provider` | identifier | The model provider. |
| `model_id` | identifier | The model asked. |
| `revision` | identifier | The model the provider reported serving, or `unrecorded`. |

A decision binds to its assignment by `binding_sha256`, the digest of the assignment object. A
living session's file holds the assignment chosen for each thing when it was captured and, for a
decision asked under an earlier model, an assignment to the model it was asked under (its
request's provider and model, its revision what the provider reported serving for those
decisions), so one thing may have several assignments in one file and every decision of the
session keeps the model that made it.

### `decisions[]`: one recorded decision

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | identifier | `request:<request id>`. Unique within a file only: a later run from the same starting state reuses request identities for different decisions. Across files, `source_record_sha256` identifies a record. |
| `thing_id` | identifier | The placed being that decided. |
| `tick` | integer | The world minute the request was asked in. |
| `binding_sha256` | digest | The model assignment in `models` it was made under. |
| `source_record_sha256` | digest | Digest of the source receipt document. |
| `observation_sha256` | digest | Digest of the context the model was shown. |
| `options` | array | The offered options, in the order offered (below). |
| `chosen_option_id` | identifier or null | The option answered, or null when the answer named none. |
| `outcome` | `applied`, `refused` or `not-applied` | A summary: `applied` when a minute applied the answer, `refused` when the minute's check rejected it, `not-applied` otherwise (superseded or stale). `receipt` holds the detail. |
| `reason_code` | identifier | The receipt's reason when applied; the minute's reason otherwise. |
| `elapsed_ms` | integer or null | The model call's latency. |
| `input_tokens` | integer or null | Prompt tokens the provider reported. |
| `output_tokens` | integer or null | Completion tokens the provider reported. |
| `receipt` | object, optional | The receipt and its minute as codes and numbers (below). |
| `readable` | object, optional | Readable text, present only when the owner captured it (below). |

### `options[]`

| Field | Type | Meaning |
| --- | --- | --- |
| `option_id` | identifier | `option:<n>`, its position in the offered order, from 1. |
| `action` | identifier | What the option does (for example `go`, `wait`, `stand`). |
| `target_id` | identifier or null | The place or being it is about. |

### `receipt`: codes and numbers, no words

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | `accepted`, `rejected`, `unavailable` or `stale` | Whether the model gave a usable answer the engine accepted. |
| `reason` | code | The receipt's reason (for example `validated_choice`, `model_timed_out`). |
| `disposition` | `applied`, `rejected`, `superseded`, `stale` or null | What a minute did with the answer; null when no minute has. |
| `disposition_reason` | code or null | The minute's reason. |
| `consumed_tick` | integer or null | The minute that took the answer up. |
| `served_model_id` | identifier or null | The model the provider reported serving. |
| `cost_usd` | decimal string or null | The call's cost: computed from reported tokens at the listed price when `cost_known`, otherwise the reservation charged, the most it can have cost. Never a provider's bill. |
| `cost_known` | boolean | Whether `cost_usd` was computed from reported tokens. |

### `readable`: opt-in text

Present only when the owner captured with readable text. It is what the source record itself
stores, made readable, and it may contain names and lines from the owner's world.

| Field | Type | Meaning |
| --- | --- | --- |
| `situation` | string | The situation text the model was shown, rebuilt from the record's own context. |
| `options` | array of strings | The offered options' labels, in the offered order. |
| `choice` | string or null | The label answered. |
| `line` | string or null | The line the answer proposed to say. |
| `status` | as in `receipt` | The receipt status. |
| `reason` | code | The receipt reason. |
| `consumed_tick` | integer | The minute that took the answer up. |
| `disposition` | code | What that minute did. |
| `served_model_id` | identifier or null | The model the provider reported serving. |
| `cost_usd` | decimal string or null | As in `receipt`. |
| `cost_known` | boolean | As in `receipt`. |

## Versioning

Within `v1`, fields are only ever added, and only as optional fields; no field changes meaning,
type or unit. An outside reader of `v1` may ignore a field it does not know. Exulanica's own reader
is closed: it refuses a file with a field it does not know, so an older Exulanica names the file as
newer instead of dropping data. A change that is not an optional addition is a new profile, `v2`.

## Privacy boundary

A file never carries credentials, tokens, local file paths, the system instruction text of a
prompt, raw provider responses, hidden model reasoning or model weights. Every string is scanned
for local paths and credential shapes when the file is written or read, and a match is refused. A
file without `readable` carries identifiers, codes, numbers and digests only. A digest of a short
text is not anonymous: anyone who can guess the text can confirm it. Publishing a file is the
owner's act; the project workflow publishes readable text only to private repositories.

## What the format does not establish

A file is evidence a world recorded, not a verified replay: an edited file cannot prove its source
receipts were authentic, and the format carries no signature. It describes decisions and their
outcomes; it does not say why a model chose, and it does not measure a model's quality on its own.
