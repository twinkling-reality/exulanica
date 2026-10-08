# The door for outside programs

An outside program, such as a game's adapter or an AI agent someone runs, may decide for things in a
world only through the door: a deployment admits the program as a **bridge**, a world's owner issues
it a **grant**, and the bridge receives the same options a model is shown and answers with one of
them. The decision host turns every answer into a receipt, so a world with an outside decider
replays with no program running. This contract owns bridges, grants and their secrets, the channel
a bridge reads and answers on, the external asker the decision host is given, mapping files, and the
door's limits. What a decider is, and how a receipt is checked and applied, is the
[decision roles contract](decision-roles-contract.md)'s.

<details>
<summary>Sections</summary>

- [Bridges](#bridges)
- [Grants](#grants)
- [Opening a grant](#opening-a-grant)
- [The channel](#the-channel)
- [Deciding through the door](#deciding-through-the-door)
- [Mapping files](#mapping-files)
- [Security and limits](#security-and-limits)
- [Crossings](#crossings)
- [Implementation and evidence](#implementation-and-evidence)

</details>

## Bridges

A deployment declares the bridges it admits in `EXULANICA_DOOR_BRIDGES`, a JSON array read once at
startup (`exulanica/door/bridges.py`). There is no route that registers a bridge: admitting a
program that will act in people's worlds is the deployment's decision, as admitting a model is. Each
entry states:

| Field | What it states |
| --- | --- |
| `bridge` | The key every grant, request and receipt names it by: lowercase, 1 to 32 letters, digits, hyphens or underscores, beginning with a letter |
| `label`, `game` | What an owner reads when choosing it, as words; the product's code names no game |
| `run_by` | Who runs the program: `server`, a game server other people join; or `owner`, a program the world's owner runs on their own machine, such as an agent or a single-player game |
| `ai` | Whether the program's choices are an AI's, always stated: a card marks the things and lines of every grant of an AI bridge as AI's |
| `credential_sha256` | For a server bridge only: the SHA-256 of the bridge's own credential, which only redeems invites; the deployment never holds the secret |
| `mapping_sha256` | The digests of the mapping files the bridge may present, one to eight |
| `adapter_versions` | The adapter versions admitted, each one to four whole numbers joined by dots, so no name can ride in one |
| `listed`, `workspaces` | A listed bridge is offered to every workspace; an unlisted one only to the workspaces named |
| `hold_seconds`, `deadline_ms` | Optional: how long its polls are held (1 to 25 seconds, 15 unless stated) and how long the decision host waits for its answer to one ask (1 ms to the person role contract's `decision_deadline_ms`, 3,000 unless stated); a game's scripts and an agent that takes a model call to choose need different figures, and the figures are data |

A missing or empty setting admits no bridge. A malformed one is refused at startup by name, never
with the secret in the message, and two bridges may share neither a key nor a credential. A bridge
credential is matched in constant time against every declared digest. Removing a bridge from the
setting, or no longer offering it to a workspace, closes its channels there: every credential of it
then opens nothing, and the decision host no longer asks it. Unpinning a mapping or an adapter
version closes every channel that said hello with it: until the bridge says hello again with one the
deployment admits, its polls and answers are 409 `hello_first` and the host does not ask it
(`decider_disconnected`).

Listing an owner bridge is how a deployment offers one program to every owner, as an agents' client
is offered: any owner may give it a channel credential for their own grant, each owner's copy holds
only that owner's credentials, which open only that owner's grants, and the bridge's held polls are
shared evenly among the workspaces using it (see Frames). A deployment that offers it to some owners
only declares it unlisted, naming their workspaces.

## Grants

A grant is a world owner's permission for one bridge in one world (`exulanica/door/grants.py`,
migration 0149). Its scope states how many visitors the bridge may bring in (0 to 4) and which
kinds, which of the world's own things it decides for (none by default, at most 8), whether things
may be carried in or out, whether its visitors may speak, the words the bridge may show its players
for the world (`world_words`, at most 80 characters, chosen by the owner; the door never reads the
world's own title), and when it ends: 120 minutes unless the owner says otherwise, at most 1,440. A
grant names at least one visitor or one thing.

| Route | Requires | Does |
| --- | --- | --- |
| `GET /door/bridges` | `world.read` | The bridges this deployment offers the workspace, in words, with who runs each and whether it is an AI |
| `POST /door/grants?world_id=` | `world.write`, `door.grant` | Issue a grant: 201 with it, or 200 with the grant an earlier issue under the same `idempotency_key` made, for the same world, bridge and scope (its kinds and things in any order); a key reused for another grant is 409 `idempotency_key_reused`; with `channel_credential` true, also its channel credential, shown once, so an issue answered 200 carries none and the first stays live; a grant for visitors only in a version holding a society of things (409 `world_not_open_to_visitors`, see Crossings) |
| `GET /door/grants?world_id=` | `world.read` | Every grant in a world, newest first, each with its bridge's label, who runs it, whether it is an AI, whether it is connected and what its program declared itself to be |
| `GET /door/grants/{grant_id}` | `world.read` | One grant as it stands, in the same view |
| `POST /door/grants/{grant_id}/revoke` | `world.write`, `door.grant` | End it now; revoking twice changes nothing |
| `POST /door/grants/{grant_id}/credentials/revoke` | `world.write`, `door.grant` | End every live invite and channel credential of the grant now, without ending the grant, as after a credential leaked |
| `POST /door/grants/{grant_id}/invites` | `world.write`, `door.grant` | An invite, shown once: for a server bridge only |
| `POST /door/grants/{grant_id}/channel-credentials` | `world.write`, `door.grant` | A channel credential, shown once: for a program the owner runs, or a server bridge declared for this workspace alone |

Who runs a bridge decides how its grants open. A server bridge's grants open by invites its own
credential redeems; an owner is given a server bridge's channel credential directly only when the
bridge is unlisted and names the owner's workspace, because a listed server serves people who are
not that owner. A program its owner runs has no bridge credential and takes no invites: any owner it
is offered to is given its channel credential directly. A request for a credential the bridge cannot
be given is refused before anything is issued (422 `direct_credential_not_offered`, or
`invites_not_offered`). Per grant, at most eight unexpired invites wait unused (409
`too_many_secrets`), and one channel credential is live: a grant answers to one program at a time,
so a channel credential issued or redeemed ends the grant's earlier one, whose program is refused at
its next request (401 `unauthenticated`). Issuing and revoking a grant, every write of its secrets,
and a hello and an answer on its channel take the grant's lock, so a credential being ended is never
issued again beside it, a cap is never passed by two requests at once, and an answer is never stored
under a hello its own credential did not say.

A grant is the newest of its revisions, each appended and never changed. Revoking records the
owner's revocation (`door_grant_revocation`), after which nothing is asked or answered under the
grant and nothing revises it. A revocation withdraws a permission, so a restore from an older backup
writes it again ([withdrawal catalog](../exulanica/deletion/withdrawals.v2.json), kind `door_grant`)
and a sealed restore checkpoint refuses one. Every request asked under a grant records the number of
the revision it was asked under. `door.grant` is held by a workspace's owner and isolated by name
because a grant hands some of a world's choices to a program its owner may not run.

**Named things.** A grant that names some of the world's own things also names the world version
they live in (`version_id`), because each version's society is its own. Issuing binds them to the
bridge through the choice record (`record_external_choice`, decider `{kind: external, bridge,
grant_id}`) in the grant's own transaction, so no thing is ever decided for under a grant that does
not exist. When the version has no society, or the choice record refuses the binding, the whole
grant is refused with the answer the choices route gives (404 `unknown_reference` for a version with
no society; 409 for `engine_takes_no_model_choice`, `choice_key_reused` and `decided_from_outside`;
422 for the rest, such as `person_not_in_this_world`), and nothing is issued. Revoking hands every
thing the grant still decides for back to its routine in the revocation's transaction
(`release_external_choice`); a thing its owner gave another decider meanwhile keeps that decider. A
grant that runs out hands its things back the same way the first time the decision host meets one
of them, under the grant's lock and chosen by the grant's own actor: that turn is recorded
unavailable with `grant_expired`, and every later turn is the routine's, with no request.

Refusals: `bridge_not_offered` and `invalid_scope` (422), `unknown_world` (404), `grant_ended` (409)
for an invite or credential on a grant that has ended, and `unknown_reference` (404) for a grant id
this workspace does not hold, which is the same answer an invented id gets.

## Opening a grant

A grant opens through one of two secrets (`exulanica/door/credentials.py`, `secrets.py`), each
stored only as its SHA-256 in `door_secret`, the one door table outside every workspace besides the
redemption ledger: it is read before any workspace is known, and holds nothing but digests,
identifiers and times.

- **An invite** is 16 characters of Crockford's base32 alphabet, 80 random bits, written in four
  groups of four. It is single use and opens its grant for 15 minutes, or until the grant ends if
  that is sooner. A server bridge redeems it with the deployment's credential for that bridge
  (`POST /door/invites/redeem`, `{code, requester}`), and receives a channel credential, shown once.
  Typing ignores case, spaces and hyphens, and reads `O` as `0` and `I` and `L` as `1`.
- **A channel credential** is 32 random bytes, 43 characters of URL-safe base64. It opens one grant's
  channel until a day after the grant ends, so a bridge can read that its grant ended and what
  happened before it did; it answers nothing once the grant has ended. Anything not shaped as one is
  refused before the database is asked.

An invite that is malformed, unknown, used, revoked, expired, another bridge's, for a workspace the
bridge is no longer offered to, or for a grant that has ended gets one refusal, 404
`invite_not_redeemable`, with one sentence. A server bridge forwards codes many people type, so it
names who typed each one: `requester` is a SHA-256 digest the bridge derives for them, never a name.
Every failed redemption is recorded against its bridge and requester in `door_redemption_refusal`,
and a requester with ten failures in the last minute is refused before its code is read (429
`too_many_redemptions`, `retry_after_s` 60). Those refusals are not recorded, so the lockout ends a
minute after the requester's last real failure, and another requester of the same bridge is never
held up. Every use of a secret checks its grant: once the grant has ended an invite opens nothing
and a channel credential answers nothing, reading only, for the day after, what was sent. Where the
deployment has accounts, a secret opens its grant only while the workspace is open: its owner's
account and owner membership stand and the workspace is not disabled, read through the account role
on every request as a browser session is (an account database that cannot be read answers 503
`account_unavailable`), and a disabled workspace's societies stop playing, so its programs are not
asked either. A secret's time is stamped when it is stored, whatever the writer says (migration
0157), and a secret may only gain the time an invite was used and the time it was revoked, each
once: migration 0149 refuses every other change. A grant is given at most 48 secrets over its life,
invites and channel credentials together (409 `too_many_secrets`), and an invite is issued only
while two more fit, itself and the channel credential its redemption issues (an invite whose room
direct credentials took meanwhile is refused at redemption, 409 `too_many_secrets`, and its
requester is not counted). A workspace issues at most 50 grants in any 24 hours (429
`too_many_grants`, with `retry_after_s`). A revoked secret is a withdrawal written once and kept for
good: no prune removes it and its trigger refuses its delete, whoever asks, so a database that keeps
door rows never holds a revocation a later checkpoint lacks. Kept revocations grow by at most 50
grants a day times 48 secrets, 2,400 rows (about 0.6 MB) a day for a workspace at both bounds, and
every sealed checkpoint carries them all. Backup sets carry no door secret and no refused redemption
(`EPHEMERAL_TABLES` in `exulanica/orchestration/installation/backup_set.py`), so a restore voids
every invite and channel credential and each owner opens their grants again. A secret's revocation
is catalogued (kind `door_secret`) so that a sealed restore checkpoint refuses it, as it refuses a
sign-out. The runtime role may update those two columns and deletes nothing: `door_prune`, a
function with its owner's rights the runtime alone may execute, removes refused redemptions a day
old and secrets nobody revoked thirty days past their end, a bounded batch at a time, as the door
issues and redeems (`exulanica/door/retention.py`); the tables' triggers refuse every other delete,
whoever asks.

## The channel

A bridge acts on its grant's channel with its channel credential. No account's credential reaches a
channel route, and a channel credential reaches no other route: an account's token or browser
session presented there is refused exactly as an unknown credential is (401 `unauthenticated`), and
a door credential presented elsewhere meets the token directory, which does not know it
(`exulanica/api/permissions.py`, declaration kind `Channel`).

**Hello.** `POST /door/channel/hello` presents the adapter's version, its mapping file, the game
fields it reads, and optionally what the program declares itself to be: `declared {name, maker,
mind}`, name and maker 1 to 40 characters, mind (the model it says it thinks with) 1 to 60. The
grant must stand (else 410 `grant_ended`). The version must be one the deployment admits for the
bridge (else 422 `adapter_version_not_admitted`), the mapping one whose digest the deployment pins
(else 422 `mapping_not_admitted`), and the mapping must meet its profile and account for every field
read (else 422 `mapping_refused`, naming what, a fractional number included). Declared words are
allowed, never listed against: letters, marks and digits of any script and `. , ' & ( ) _ +` and `-`
(and `/` in a mind), on the line rule ([things contract](things-contract.md)), with no dotted host
name (else 422 `declared_refused`). The mapping and the declaration are kept in the workspace by
their digests (`door_mapping`, `door_declaration`), and the grant's presence records the version,
mapping and declaration that every later answer names. A presence counts only if its hello was said
since the grant's live channel credential was issued, so a hello an earlier program said never names
who answers now, and only while the deployment still admits its version and mapping. Declared words
are a program's own words for a person reading a card: they never enter a society record or any
model's context. A grant takes at most six hellos a minute in one process (429 `too_many_hellos`,
`retry_after_s` 60). The answer states the bridge's hold. A bridge polls only after its hello (409
`hello_first`), except once its grant has ended: then it reads what it was sent without one, so a
bridge whose version or mapping the deployment no longer admits still reads the end.

**Frames.** `GET /door/channel/frames?after=` answers with frames of `exulanica.door-frame/v1` after
an opaque cursor, and the cursor after them; a bridge reads only response bodies. One ask is written
for the bridge, by the decision host; every other frame is projected from records that exist anyway,
so a frame never disagrees with the history it reports:

| Frame | Carries |
| --- | --- |
| `grant` | The grant's scope, its world words and its end, first and again whenever its owner changes it |
| `asked` | One reserved request: its id and digest, the minute it was asked at, the deadline, the role's instruction and choice description, the request's context byte for byte as a model reads it, and the same request rendered as a model is sent it: the role's own `messages` and `act`, the one function a model is forced to call, whose `action` is one of the offered labels; and `idle_label`, the label of the offered option that changes nothing (the role's own, null where it offers none), which a bridge answers when nobody in its game acts for the thing |
| `outcome` | The status and reason the host recorded for an ask, in ask order |
| `arrived`, `arrival_refused`, `departed` | What became of the grant's visitors, in the order the society recorded it (see Crossings) |
| `grant_ended` | That the grant was revoked or ended, once, after everything else the bridge is told |

An ask whose turn was decided before the bridge read it is not sent; its outcome is. One poll's
answer stops adding asked frames once they pass 262,144 bytes (the first always goes), and the next
poll reads on, so an agent never renders a role's words itself and no answer grows past a bound.
Every poll checks its grant: under a standing grant it records the poll; once the grant has ended it
records nothing and sends the end as soon as every ask was read, every outcome reported or passed
over and nothing else is left to tell (see Crossings for a grant's visitors), and once the bridge
has read that end its polls and hellos are refused (410 `grant_ended`). Outcomes are reported in ask
order; an ask whose request no receipt can close any more, past its deadline and the minutes in
which the host closes a request a stopped process left (the unanswered window), is passed over with
no outcome, since none was recorded, so nothing after it waits for it. A poll is held for at most
its bridge's hold with nothing to send. While held it keeps no database connection or transaction:
its first read records the poll and reads the head on one short connection, later reads each open a
short connection from a limiter of four poller threads per process, and frames are built only when
the head says something is new. Within the process that wrote an ask the poll wakes at once;
otherwise the head is read once a second, and a poll whose client went away ends at its next read.
One poll is held per grant, a second ending the first with nothing to send; a process holds at most
64, a workspace at most four of them and a bridge at most half. When the process or a bridge is
full, a poll from a workspace holding fewer takes the place of the oldest poll of the workspace
holding the most there, if that one holds at least two more; the poll whose place is taken is
answered at once with nothing to send. So the places are shared evenly among the workspaces that
want them, and only a poll that would not be fairer is refused (503 `door_busy`, `retry_after_ms`
1,000). One process therefore serves the programs of at most 32 workspaces at a time through one
bridge: a listed bridge that more owners use at once needs more API processes, or some programs
wait, and one left out past its hold and ten quiet seconds is reported not connected and its things
fall to the routine ([deployment guide](deployment.md), 5.4, which says what several processes do
not share: a kind of place being drafted needs each person routed to one of them). The frames route
belongs to the streams admission class.

**Answers.** `POST /door/channel/answers` names one open ask of the grant (else 404
`unknown_reference`), its request digest and one of the labels the request offered (else 422
`answer_not_offered`). A line is accepted only with an option that says one, at most 200 code points
on the line rule (else 422 `line_not_offered`, `line_missing` or `line_refused`). The answer is
stored as sent, with the adapter version, mapping and declaration its own hello named, and nothing
else happens: the host makes the receipt. A second answer is 409 `answer_already_given`, an answer
after the turn was decided 409 `answer_too_late`, and an answer once the grant has ended 410
`grant_ended`; none changes anything. Migration 0149 ties a stored answer to its ask by all four of
the ask's names, and refuses one under a grant that has ended under the lock revoking takes, so a
revocation and an answer never both commit as if the other had not.

## Deciding through the door

A thing an outside program decides for has the decider `{kind: external, bridge, grant_id}`
([decision roles](decision-roles-contract.md)). The decision host asks it through the external
asker the application gives it whenever the deployment runs the door (`exulanica/door/asker.py`,
given in `exulanica/api/services.py`):

1. **Before reserving**, the asker states the request's `provider_config` as the grant stands:
   `{kind, bridge, grant_id, grant_seq, mapping_sha256, deadline_ms}`, the host adding the role's
   contract. `mapping_sha256` is the mapping of the bridge's last hello, or the grant's first pinned
   digest before any; `deadline_ms` is the bridge's. It also states whether to ask at all: a revoked
   or expired grant (`grant_revoked`, `grant_expired`), a thing the grant no longer names
   (`grant_revoked`), a bridge the deployment no longer declares or offers here, a workspace that is
   closed, or a program that has said no hello under the grant's live credential with a version and
   mapping the deployment admits, or has not polled within its hold and ten quiet seconds
   (`decider_disconnected`). With a refusal the host records an unavailable receipt at once and the
   world's routine decides that turn.
2. **Asking** writes the ask to the grant's outbox (`door_ask`), which wakes the bridge's held poll,
   and waits until the minute's deadline for the bridge's answer in the inbox (`door_answer`),
   holding no connection between reads. The default deadline is 3,000 ms: a frame reaches a held
   poll at once in the process that wrote it, crosses the network, is read at the game's next server
   step and is answered back, and three seconds leaves room for a public network while staying under
   half of a world minute at normal speed. A bridge whose program takes longer to choose, such as an
   agent making a model call, declares its own.
3. **The result** is what the receipt records. Before an answer counts, the asker reads the grant
   again: an answer stored before a revocation committed is not accepted after it (`grant_revoked`),
   and an answer given under another mapping than the request was reserved with is not accepted
   (`decider_disconnected`). Otherwise the result is the offered option the bridge named and, as the
   receipt's `provider`, `{kind: external, bridge, adapter_version, grant_id, grant_seq,
   mapping_sha256, answer_sha256, latency_ms, source_ref_sha256}`, naming the adapter version and
   mapping the stored answer records, with no cost, because an external answer spends nothing. With
   no answer by the deadline it is `unavailable` with `no_answer_in_time`, or the grant's end if it
   ended meanwhile.

The host is the one writer of receipts, and replay reads them: a world with an outside decider
replays with no bridge running and no channel reachable.

## Mapping files

A mapping file states how one game's things become things here and what never crosses
(`exulanica/door/mapping.py`). It is data, kept with its adapter outside the product and pinned by
digest in the deployment's bridge directory. Two profiles are read side by side, the same but for
how a visitor's look is named: `exulanica.bridge-mapping/v1` names it by its digest
(`sha256:<digest>`), which the door resolves against the thing library's shipped looks when a
visitor arrives, and `exulanica.bridge-mapping/v2` by the library's own reference, `{look, version,
sha256}`. A mapping pinned in either profile stays valid; a look the library holds only in a
workspace's store can be named only in the second.

| Part | States |
| --- | --- |
| `visitors` | Each kind of game character that may cross, the thing kind it arrives as, the words it is known by, and the looks it may arrive in, each with its licence; none for a program that brings no visitor and only decides for a world's own things, such as an agent |
| `items` | Each game item that may be carried, the thing kind it becomes, which ways it travels, and whether the correspondence is exact or approximated; at most one item of each kind travels out, so a thing leaving always becomes one known game item |
| `actions` | Which of the game's actions become which abilities |
| `never_crosses` | Every game field the adapter reads with no counterpart here; a player's name always among them |

Every entry says in plain words what it is and what it becomes (`words`), and every entry that is
not exact says why (`reason_words`; every `never_crosses` entry does): a crossing's translation
manifest copies them field by field, so a thing's card shows each game's own reasons and the product
holds no game's text. Words meet the line rule every thing's words meet
(`exulanica/things/lines.py`): one line in Unicode NFC of a bounded number of code points, with no
control, format, surrogate, private use or separator character. Its checks are deterministic and
authoritative: the closed schema, unique keys, strings, whole numbers and true or false only,
bounded sizes, nesting and words, a reason exactly where an entry is approximated, and completeness:
an adapter that reads a field its mapping neither maps nor lists as staying behind is refused, so a
crossing's manifest cannot leave out a loss by forgetting it. A game's own identifiers, actions
included, may carry capitals and colons. Whether each named kind exists is checked against the thing
kind library by the crossings that use it.

## Security and limits

- Two credential families that never overlap: an account's credential reaches owner routes, and a
  door credential reaches only the channel routes its declaration names.
- An id the caller does not hold is answered as a nonexistent one, on owner and channel routes alike.
- Bodies are bounded before they are read or parsed (`exulanica/api/routes/door.py`, `BODY_LIMITS`):
  a hello 65,536 bytes, an answer 4,096, an arrival and a delivery report 8,192 each, a redemption
  and a player's leaving 1,024 each and an owner's grant routes 4,096 (413 `body_too_large`). A hello's mapping is at most 49,152 canonical bytes and 64 fields read; at most
  32 frames a poll.
- Nothing from a program is executed: a mapping is closed data, every answer is one of the labels its
  request offered, checked again by the engine in its minute, and a line meets the line rule before
  it is stored and the workspace's rules when the host records it.
- What leaves through the door is the request as the host reserved it, which is what a model is
  shown: its context, the role's instruction and the description of the one choice, the same
  request rendered as a model is sent it (`messages` and the forced `act`) and the minute it was
  asked at; the grant as its owner issued it, its named things and the version they live in
  included; and what became of the grant's own visitors: the ids the door gave them and the things
  they carried, the reason a minute refused one, and each departure with the game item each thing
  carried home becomes. A hello's cursor tells every arrival's outcome again from the grant's first.
- `door_secret` and `door_redemption_refusal` belong to the deployment and never travel in a seed
  (`exulanica/orchestration/judge_seed.py`). Grants, asks, answers, mappings and declarations are
  kept with the world; the transport tables are kept as appended.

## Crossings

A grant that lets visitors in names the world version they arrive in (`version_id`), which must
hold a society whose engine holds things (`exulanica-society/v7`, as the engine table in
`exulanica/world/society_engines.py` says; else 409 `world_not_open_to_visitors`), and may name the
gate they come through (`gate`, the id a gate was placed with, only with visitors). Both are rules
of issuing: a stored revision is read as it was written, so a visitors grant whose revision names
no version is listed, opened and revoked like any other and takes no arrival (409
`world_not_open_to_visitors`). Its bridge sends visitors and reads what became of them on its
channel; the owner may send one home:

| Route | Credential | Does |
| --- | --- | --- |
| `POST /door/channel/arrivals` | channel | `{arrival_id, game_type, look_key, carried: [{game_item, count}]}`: one visitor of a type the grant admits, in a look its mapping offers, carrying game items its mapping lets travel in, under an `arrival_id` of the bridge's own that is a random version 4 UUID; 201 `{arrival_id, thing_id}`, or 200 with the same answer for the same arrival sent again |
| `POST /door/channel/departures/{departure_id}/delivered` | channel | `{delivered: [{thing_id, game_item}], not_delivered: [{thing_id, reason}]}`, naming each thing a departed visitor carried home once: 202 `{recorded}`, true the first time; a report may follow the grant's end |
| `POST /door/channel/gone` | channel | `{thing_id}`: the person behind a visitor left the game, so it is not asked again; 202 `{recorded}` |
| `POST /door/grants/{grant_id}/send-away` | `world.write`, `door.grant` | `{thing_id}`: a visitor of the grant goes home at the next minute; 202 |

An arrival is refused before anything is written: an arrival id that is not a random version 4
UUID (422), a grant that brings no visitors (403 `no_visitors_allowed`), a type it does not admit
(422 `kind_not_admitted`), a kind the mapping names that the thing library does not ship (422
`kind_not_shipped`), a look the mapping does not offer (422 `look_not_offered`) or the thing library
does not ship for the visitor's kind (422 `look_not_shipped`, `look_unfit` or
`thing_kind_not_shipped`, `exulanica/world/thing_looks.py`), carrying without `may_carry_in` (403
`carrying_not_allowed`), more than 16 things (422 `too_much_carried`), an item that does not travel
in (422 `item_not_mapped`), more than 60 arrivals of the grant in the last hour, refused ones
included (429 `too_many_arrivals`, with `retry_after_s`), as many visitors as the grant lets in
already present (409 `visitors_full`; both counted under the society's crossing lock), an arrival
id already naming another arrival (409 `crossing_id_reused`), or no hello under the live credential
(409 `hello_first`). An arrival is named by the bridge's random id and a departure by one the door
derives (version 5), so no arrival can take the id a departure will be written under; the
crossings' migration refuses an arrival named any other way. The visitor's id and each carried thing's are derived
from the grant and the arrival id, so an arrival sent again is the same arrival; one sent again
after a hello with another adapter version or mapping is another arrival's document, so 409
`crossing_id_reused`. The door writes an `exulanica.thing-arrival/v1` document ([things
contract](things-contract.md)): the visitor's kind by the library's digest, its origin (class
`crossed`: the bridge, its adapter version and mapping, the grant, with the licence and
distribution of the shipped look it wears, never a mapping's words about that look), and the digest
of its translation manifest (`exulanica.translation-manifest/v2`), which says for each game field
the mapping accounts for whether it came across exact, approximated or not at all, in the mapping's
own words, and is kept in the workspace by that digest (`door_manifest`).

The society's next minute takes at most 32 crossings no minute has taken, in the order the door
wrote them, and binds each once to the event it recorded (`door_crossing_binding`): an arrival
arrived or was refused (`no_arrival_place`, `visitor_limit`, `unknown_kind`, `already_here`,
`malformed_crossing`), a departure departed, found nobody of that id here (`not_here`) or was
refused. An arrival that arrived records its visitor's look in the same transaction
(`world_thing_look`, chosen by the crossing), never anything the society reads. A society with
visitors therefore replays from what it stored and bound, with no bridge running.

The bridge reads what became of its visitors as frames, in the order the society recorded it:
`arrived` `{arrival_id, thing_id, carried: [{thing_id, game_item}]}`, `arrival_refused`
`{arrival_id, reason}`, and `departed` `{departure_id, thing_id, why, carried: [{thing_id, kind,
game_item}]}` for every departure of one of its visitors, those the door wrote and those the society
decided by its own rules. `why` is the society's word for the departure: `sent_home` for the owner's
send-away, `grant_ended`, or the society's own reasons (`chose_to_leave`, `decider_lost`). A thing a
visitor brought in goes home as the game item it came in as; a thing of the world it holds becomes
the one item the mapping lets travel out for its kind only under a grant that lets things be carried
out (`may_carry_out`), else none. A visitor leaves when its owner sends it home (`sent_away`), when
its grant ends (revoking writes a `grant_ended` departure for each visitor in the revocation's
transaction, before the grant's named things are handed back, and a grant that ran out sends each
visitor home the next time the host would ask it), or when the society sends it home. Until the
minute that takes its departure a visitor is still in the world, and its program is still asked for
it while its grant stands. The `grant_ended` frame comes only once no crossing of the grant waits
for a minute, every visitor of it has departed and the bridge has read each departure, so a bridge
that stops at the end has read every one. A hello's cursor tells every arrival's outcome again from
the grant's first, and every departure from the first one carrying something whose delivery the
bridge has not reported.

Migration 0163 holds the crossings (`door_crossing`), their bindings, manifests, delivery reports
(`door_delivery`) and the word that a visitor's player left (`door_visitor_gone`), each appended and
never changed, kept to its workspace, and inserted by the runtime only, and indexes a society's
departures by the thing that left, which is how the door finds a visitor's. Not built yet: the
lines and events a visitor hears, as frames. Whether a grant's visitors may speak (`may_speak`) is
recorded and shown; no line crosses the door yet, so nothing reads it. A visitor whose kind has
hands may take hold of a thing of the world in a society running hands, but no arrival records its
grant's `may_carry_out`, so the society keeps every such thing behind: a visitor going home puts a
thing of the world down where it stood, and `may_carry_out` names no game item yet. It takes home
what it brought, from its hands or from where it lies in the world, unless a being still here holds
it. Such a thing leaves the world when that being puts it down, undelivered: its bringer gave it
away, a departure's frame names only what went home with that visitor, and no later frame tells the
bringer's program of it. A departure's `carried` lists what went home with the visitor. The adapters that send visitors live in the repository's
`bridges/` folder, outside the product, each with its own licence notes.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Bridges, secrets, the cursor, mappings, words and the process's own notices | `exulanica/door/bridges.py`, `credentials.py`, `protocol.py`, `mapping.py`, `notices.py` | `tests/test_door.py` |
| Grants, redemption, retention, the channel and the asker | `exulanica/door/grants.py`, `secrets.py`, `retention.py`, `channel.py`, `asker.py`, `exulanica/api/routes/door.py`, migration 0149 | `tests/test_door_postgres.py` |
| Kept revocations, a secret's stamped time, `door_prune` keeping its owner, a run-out grant's things handed back | migration 0157, `exulanica/door/grants.py`, `asker.py` | `tests/test_door_postgres.py`, `tests/test_installation_recovery.py` |
| A bridge deciding a person's turn end to end, what it is sent, replay with no bridge, a quiet bridge and revocation | `exulanica/api/services.py`, `exulanica/door/grants.py`, `exulanica/door/asker.py`, `exulanica/door/channel.py` | `tests/test_door_outside_decider_postgres.py` |
| The `Channel` declaration and `door.grant` | `exulanica/api/permissions.py`, `exulanica/api/dependencies.py` | `tests/test_route_permissions.py`, `tests/test_route_rule_layout.py`, `tests/test_api.py`, `tests/test_existence_oracle.py` |
| The product names no game and imports no adapter | `pyproject.toml` import contracts | `tests/test_door_names_no_game.py` |
| The reference client: HTTPS or loopback only, no redirects | `bridges/door_client/door_client.py` | `tests/test_door_reference_client.py` |
| Running a slot's API with bridges | `scripts/acceptance/launch.py` (`--door-bridges`) | `tests/test_acceptance_launcher.py` |
| Crossings: arrivals, looks, manifests, departures, deliveries, the end's order, replay | `exulanica/door/crossings.py`, `manifest.py`, `channel.py`, `exulanica/api/routes/door.py`, migration 0163 | `tests/test_door_crossings_postgres.py` |
| The crossing rules: arrival ids apart from departure ids, revisions read as written, arrivals an hour, the look's licence, refusals by name, two grants in one society, the end's wait | `exulanica/door/crossings.py`, `grants.py`, `asker.py`, `exulanica/api/routes/door.py`, the crossings' migration | `tests/test_door_crossing_rules_postgres.py` |

Decision record: [ADR-0031](adr/0031-an-outside-program-decides-only-through-the-door.md).
