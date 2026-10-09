"""The generation worker against a migrated database, the S3 double and a session the test plays.

The worker runs as the runtime role with durable spending (the workspace's nebius_ai_cloud_gpu grant
issued by the spending operator). The session is played by writing what a warm session writes into
the bucket: a heartbeat, then for the worker's entry a claim, a receipt and a piece per item and a
done marker naming the receipts. The receipts are warm session 1's own well receipts
(``ml/appearance/evidence/generated-assets-session-1``) restated for the worker's request, job and
seed, with piece bytes of the size each measured; amounts are worked from the compute catalog's
rate (USD 1.80 an hour) by hand in each test. The worker's clock is the test's: ``later`` moves it.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.generation import batches, store
from exulanica.generation.bucket import SignedGenerationBucket
from exulanica.generation.requests import (
    GPU_PROVIDER,
    LookReference,
    generation_catalogs,
    plan_requests,
)
from exulanica.generation.worker import PieceGenerationWorker
from exulanica.ingest.repository import IngestRepository
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.object import ObjectRequests, ObjectStoreCredentials, ObjectStoreLocation
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.worlds import GENERATED
from exulanica_pieces.budgets import read_budgets
from exulanica_pieces.canonical import canonical_bytes, sha256_hex
from exulanica_pieces.queue import BEAT_PROFILE, build_claim, build_done
from exulanica_pieces.records import build_receipt, read_job, read_request, seed_for
from psycopg.rows import dict_row

from object_store_double import S3Double
from spending_support import bench as spending_bench  # noqa: F401
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
SESSION_1 = ROOT / "ml/appearance/evidence/generated-assets-session-1"
LIBRARY = style_pack_library()
COMPUTE_KEY = "nebius-ai-cloud-rtx-pro-6000"


@pytest.fixture(name="bench")
def _bench_alias(request):
    return request.getfixturevalue("spending_bench")


def _stamp(at: dt.datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


class Played:
    """The worker, its bucket and the session the test plays."""

    def __init__(self, repository, bench, tmp_path, granted: str | None) -> None:
        self.repository, self.bench = repository, bench
        self.workspace_id = repository.workspace_id
        registered_world(repository.connection, self.workspace_id)
        self.session_raw = (SESSION_1 / "session.json").read_bytes()
        self.session_sha256 = sha256_hex(self.session_raw)
        job = read_job(min((SESSION_1 / "jobs").glob("*.json")).read_bytes())
        self.components = job["components_sha256"]
        self.code = job["code_sha256"]
        self.container = job["container"]
        repository.connection.execute(
            "insert into generation_session (session_canonical, session_sha256, route, "
            "code_sha256, components_sha256, container, compute_key, provider_job_id, opened_by, "
            "window_ends_at) values (%s, %s, 'A', %s, %s, %s, %s, 'aijob-test', 'test operator', "
            "now() + interval '1 hour')",
            (
                self.session_raw.decode(),
                self.session_sha256,
                self.code,
                self.components,
                self.container,
                COMPUTE_KEY,
            ),
        )
        repository.connection.commit()
        # The session's one instant, read when the test runs (never at import), after the session
        # was registered so the worker finds it open.
        self.now = dt.datetime.now(dt.UTC).replace(microsecond=0) + dt.timedelta(seconds=1)
        if granted is not None:
            now = dt.datetime.now(dt.UTC)
            authority = bench.operator.issue(
                provider=GPU_PROVIDER,
                ceiling_usd=Decimal("1.00"),
                max_calls=1000,
                valid_until=now + dt.timedelta(days=30),
                operator="test-operator",
                reason="the operator's GPU time, for a test",
            )
            bench.operator.grant(
                authority,
                self.workspace_id,
                ceiling_usd=Decimal(granted),
                max_calls=1000,
                valid_until=now + dt.timedelta(days=29),
                operator="test-operator",
                reason="a test grant",
            )
        double = S3Double(bucket="exulanica-gen", region="uk-south2", clock=lambda: self.now)
        self.bucket = SignedGenerationBucket(
            ObjectRequests(
                ObjectStoreLocation(
                    endpoint="http://127.0.0.1:19477", bucket="exulanica-gen", region="uk-south2"
                ),
                ObjectStoreCredentials("runtime-key", "runtime-secret"),
                transport=double.transport(),
                now=lambda: self.now,
            )
        )
        self.pieces = LocalContentAddressedStore(tmp_path / "generated-pieces")
        self.worker = PieceGenerationWorker(
            database=bench.runtime,
            bucket=self.bucket,
            pieces_store=self.pieces,
            spending=bench.durable(),
            catalogs=generation_catalogs(),
            library=LIBRARY,
            shipped=shipped_thing_kinds(),
            workspaces=lambda: [self.workspace_id],
            store_bound=1 << 30,
            now=lambda: self.now + self.offset,
        )
        self.offset = dt.timedelta(0)

    def later(self, **delta: float) -> None:
        """Move the worker's clock on by ``delta`` from the session's instant."""
        self.offset = dt.timedelta(**delta)

    def ask(
        self, kinds=(("well", 1),), world_id: str = FIXTURE_WORLD_ID
    ) -> list[store.PieceRequestRecord]:
        pack = LIBRARY.default_pack
        look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
        planned = plan_requests(list(kinds), look, library=LIBRARY)
        compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
        with self.bench.runtime.session(self.workspace_id) as connection:
            made, _ = store.create_piece_requests(
                connection,
                self.workspace_id,
                requested_by=uuid.uuid4(),
                world_id=world_id,
                look=look,
                planned=planned,
                worst_cases=[compute.worst_case_usd(plan.variants) for plan in planned],
            )
        return made

    def beat(
        self,
        state: str = "idle",
        at: dt.datetime | None = None,
        started: dt.timedelta = dt.timedelta(minutes=5),
    ) -> None:
        at = self.now if at is None else at
        self.bucket.put(
            f"session/{self.session_sha256}/beat-{at.strftime('%Y%m%dT%H%M%SZ')}.json",
            canonical_bytes(
                {
                    "at": _stamp(at),
                    "job_sha256": None,
                    "profile": BEAT_PROFILE,
                    "served": 0,
                    "session_sha256": self.session_sha256,
                    "started_at": _stamp(at - started),
                    "state": state,
                }
            ),
        )

    def entries(self) -> list[str]:
        return sorted(
            key.split("/")[1] for key in self.bucket.keys("queue/") if key.endswith("/ready.json")
        )

    def entry(self, entry: str | None = None) -> tuple[str, dict, dict, dict[str, dict]]:
        entry = entry or self.entries()[-1]
        ready = json.loads(self.bucket.get(f"queue/{entry}/ready.json"))
        job = read_job(self.bucket.get(f"queue/{entry}/job.json"))
        budgets = generation_catalogs().budgets
        requests = {
            item["request_sha256"]: read_request(
                self.bucket.get(f"queue/{entry}/requests/{item['request_sha256']}.json"), budgets
            )
            for item in job["items"]
        }
        return entry, ready, job, requests

    def claim_the_entry(self, entry: str | None = None, session: str | None = None) -> str:
        entry, ready, _, _ = self.entry(entry)
        self.bucket.put(
            f"claimed/{entry}.json",
            build_claim(
                entry_id=entry,
                job_sha256=ready["job_sha256"],
                session_sha256=session or self.session_sha256,
                at=self.now,
            ),
        )
        return entry

    def run_the_entry(
        self,
        *,
        components: str | None = None,
        milliseconds: int = 40743,
        session: str | None = None,
        entry: str | None = None,
    ) -> str:
        """Publish what a session publishes for the entry, from session 1's well receipts."""
        entry, ready, job, requests = self.entry(entry)
        templates = sorted(
            (
                json.loads(path.read_bytes())
                for path in (SESSION_1 / "receipts").glob("*.json")
                if json.loads(path.read_bytes())["request_sha256"].startswith("4743c0a6")
            ),
            key=lambda receipt: receipt["variant"],
        )
        receipts = []
        for item in job["items"]:
            request = requests[item["request_sha256"]]
            template = templates[item["variant"]]
            piece = bytes([item["variant"] + 1]) * template["measured"]["glb_bytes"]
            document = {
                **template,
                "components_sha256": components or self.components,
                "job_sha256": ready["job_sha256"],
                "output": {"bytes": len(piece), "sha256": sha256_hex(piece)},
                "request_sha256": item["request_sha256"],
                "seed": seed_for(item["request_sha256"], item["variant"]),
                "variant": item["variant"],
            }
            raw = build_receipt(document, request)
            self.bucket.put(f"out/receipts/{sha256_hex(raw)}.json", raw)
            self.bucket.put(f"out/pieces/{sha256_hex(piece)}.glb", piece)
            receipts.append(sha256_hex(raw))
        self._done(
            entry,
            ready["job_sha256"],
            session=session,
            ran={
                "items": {"made": len(job["items"]), "total": len(job["items"]), "within": 4},
                "receipts": receipts,
                "request_milliseconds": {sha: milliseconds for sha in requests},
                "results_ended_at": _stamp(self.now),
            },
        )
        return entry

    def _done(self, entry: str, job_sha256: str, *, session: str | None = None, **outcome) -> None:
        self.bucket.put(
            f"done/{entry}.json",
            build_done(
                entry_id=entry,
                job_sha256=job_sha256,
                session_sha256=session or self.session_sha256,
                claimed_at=_stamp(self.now),
                ended_at=_stamp(self.now),
                **outcome,
            ),
        )

    def refuse_the_entry(self) -> None:
        entry, ready, _, _ = self.entry()
        self._done(entry, ready["job_sha256"], refused="queue entry: a request it does not name")

    def tombstone(self) -> None:
        with self.bench.runtime.session(self.workspace_id) as connection:
            IngestRepository(connection, self.workspace_id).insert_tombstone(
                scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
            )

    def rows(self, sql: str, *params) -> list[dict]:
        with self.bench.runtime.session(self.workspace_id) as connection:
            return connection.cursor(row_factory=dict_row).execute(sql, params).fetchall()

    def reservations(self) -> list[dict]:
        return self.bench.reservations(self.workspace_id)


@pytest.fixture
def played(repository, bench, tmp_path):
    return lambda granted="0.50": Played(repository, bench, tmp_path, granted)


def _queued(p: Played) -> str:
    p.ask()
    p.beat("idle")
    p.worker.run_once()
    [entry] = p.entries()
    return entry


def test_a_warm_session_takes_a_request_and_the_worker_keeps_and_settles_what_it_made(
    played,
) -> None:
    p = played()
    p.ask()
    p.beat("idle")
    report = p.worker.run_once()
    assert report["session"] == "warm"
    [row] = p.rows("select state, piece_batch_id, reservation_id from piece_request")
    assert row["state"] == "queued" and row["piece_batch_id"] is not None
    # The entry is named by the batch's own id and may be taken until the session's own stop:
    # its heartbeat started 5 minutes before now and its record stops at 1800 s.
    entry, ready, job, _ = p.entry()
    assert entry == row["piece_batch_id"].hex
    assert ready["not_after"] == _stamp(
        p.now - dt.timedelta(minutes=5) + dt.timedelta(seconds=1800)
    )
    assert len(job["items"]) == 4
    [reservation] = p.reservations()
    assert reservation["state"] == "dispatched"
    # The worst case admitted: 4 variants at 30 s and USD 1.80 an hour.
    assert Decimal(reservation["reserved_usd"]) == Decimal("0.06")
    p.run_the_entry(milliseconds=40743)
    p.worker.run_once()
    [row] = p.rows("select state, failure, request_sha256 from piece_request")
    assert (row["state"], row["failure"]) == ("made", None)
    outputs = p.rows(
        "select variant, within, piece_sha256, cache_key from piece_output order by variant"
    )
    assert [o["variant"] for o in outputs] == [0, 1, 2, 3]
    assert all(o["within"] for o in outputs)
    # Kept under its cache key: the request, the session's models and the post-process version.
    key = sha256_hex(
        canonical_bytes(
            {
                "components_sha256": p.components,
                "postprocess": "exulanica.generated-asset-postprocess/v2",
                "request_sha256": row["request_sha256"],
            }
        )
    )
    assert {o["cache_key"] for o in outputs} == {key}
    assert len(p.rows("select variant from generated_piece where cache_key = %s", key)) == 4
    for output in outputs:
        assert p.pieces.exists(BlobId.from_hex(output["piece_sha256"]))
    [batch] = p.rows("select state, claimed_at from piece_batch")
    assert batch["state"] == "done" and batch["claimed_at"] is not None
    [reservation] = p.reservations()
    # Settled at the measured milliseconds: 40,743 ms at USD 1.80 an hour is USD 0.020372.
    assert reservation["state"] == "settled"
    assert Decimal(reservation["settled_usd"]) == Decimal("0.020372")
    [settlement] = p.rows("select basis, usd, settled_at from piece_settlement")
    assert (settlement["basis"], settlement["usd"]) == ("reported", Decimal("0.020372"))
    assert settlement["settled_at"] is not None


def test_a_refused_entry_fails_its_requests_and_releases_their_reservations(played) -> None:
    p = played()
    _queued(p)
    p.refuse_the_entry()
    p.worker.run_once()
    [row] = p.rows("select state, failure from piece_request")
    assert (row["state"], row["failure"]) == ("failed", "entry_refused")
    [batch] = p.rows("select state, refusal from piece_batch")
    assert (batch["state"], batch["refusal"]) == ("refused", "entry_refused")
    [reservation] = p.reservations()
    assert reservation["state"] == "released"


def test_an_entry_no_session_took_expires_only_after_its_not_after(played) -> None:
    p = played()
    _queued(p)
    _, ready, _, _ = p.entry()
    not_after = dt.datetime.strptime(ready["not_after"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.UTC
    )
    # Heartbeats that stop without saying the session ended are not enough: it could still be
    # taking the entry until then.
    p.later(seconds=300)
    p.worker.run_once()
    [row] = p.rows("select state from piece_request")
    assert row["state"] == "queued"
    # Past not_after, but within the clocks' two-minute allowance: still queued.
    p.later(seconds=(not_after - p.now).total_seconds() + 119)
    p.worker.run_once()
    assert p.rows("select state from piece_request")[0]["state"] == "queued"
    p.later(seconds=(not_after - p.now).total_seconds() + 121)
    p.worker.run_once()
    [row] = p.rows("select state, failure from piece_request")
    assert (row["state"], row["failure"]) == ("failed", "session_ended")
    [reservation] = p.reservations()
    assert reservation["state"] == "released"
    [settlement] = p.rows("select basis from piece_settlement")
    assert settlement["basis"] == "not_sent"


def test_an_entry_its_ended_session_never_took_is_released_at_once(played) -> None:
    p = played()
    _queued(p)
    # The entry names this session, and no other takes it; once its last heartbeat says it ended,
    # nothing will, long before not_after.
    _, ready, _, _ = p.entry()
    assert ready["session_sha256"] == p.session_sha256
    p.beat("ended: idle", p.now + dt.timedelta(seconds=1))
    p.later(seconds=2)
    p.worker.run_once()
    [row] = p.rows("select state, failure from piece_request")
    assert (row["state"], row["failure"]) == ("failed", "session_ended")
    [reservation] = p.reservations()
    assert reservation["state"] == "released"


def test_a_catalog_change_ends_a_waiting_and_an_in_flight_request_instead_of_stalling(
    played, tmp_path
) -> None:
    p = played()
    _queued(p)
    p.ask(kinds=(("lantern", 1),))
    p.run_the_entry(milliseconds=40743)
    # The piece budgets file changes under both: every request names the digest it was asked under.
    text = (ROOT / "assets/style-packs/piece-budgets.v1.json").read_text()
    about = json.loads(text)["about"]
    changed = tmp_path / "changed" / "assets/style-packs/piece-budgets.v1.json"
    changed.parent.mkdir(parents=True)
    changed.write_text(text.replace(json.dumps(about), json.dumps(about + " Changed."), 1))
    p.worker.catalogs = dataclasses.replace(
        p.worker.catalogs, budgets=read_budgets(tmp_path / "changed")
    )
    p.worker.run_once()
    rows = p.rows(
        "select r.state, r.failure, b.state as batch, b.refusal from piece_request r "
        "left join piece_batch b on b.piece_batch_id = r.piece_batch_id order by r.requested_at"
    )
    # The batch in flight ends refused, its measured time still settled; the waiting request
    # ends failed and never reaches the allowance.
    assert [(r["state"], r["failure"], r["batch"], r["refusal"]) for r in rows] == [
        ("failed", "request_unreadable", "refused", "request_unreadable"),
        ("failed", "request_unreadable", None, None),
    ]
    [reservation] = p.reservations()
    assert reservation["state"] == "settled"
    assert Decimal(reservation["settled_usd"]) == Decimal("0.020372")


def test_a_claimed_entry_is_waited_for_until_its_stop_and_then_settled_unknown(played) -> None:
    p = played()
    _queued(p)
    p.claim_the_entry()
    # The job's stop: 4 items at 30 s is 120 s, and its stop is 150 per cent of that, 180 s.
    p.later(seconds=180 + 119)
    p.worker.run_once()
    [batch] = p.rows("select state, claimed_at from piece_batch")
    assert batch["state"] == "queued" and batch["claimed_at"] is not None
    p.later(seconds=180 + 121)
    p.worker.run_once()
    [row] = p.rows("select state, failure from piece_request")
    assert (row["state"], row["failure"]) == ("failed", "session_ended")
    [reservation] = p.reservations()
    # A session took it and never said it ended: its whole liability stays, never not_sent.
    assert reservation["state"] == "unknown"
    assert Decimal(reservation["settled_usd"]) == Decimal("0.06")


def test_a_request_asked_again_is_answered_from_the_kept_pieces_with_no_run(played) -> None:
    p = played()
    _queued(p)
    p.run_the_entry()
    p.worker.run_once()
    [first] = p.reservations()
    p.ask()
    report = p.worker.run_once()
    [answered] = report["workspaces"][str(p.workspace_id)]["answered"]
    rows = p.rows("select piece_request_id, state from piece_request order by requested_at")
    assert [row["state"] for row in rows] == ["made", "made"]
    assert str(rows[1]["piece_request_id"]) == answered
    outputs = p.rows(
        "select piece_batch_id from piece_output where piece_request_id = %s",
        rows[1]["piece_request_id"],
    )
    assert len(outputs) == 4 and all(o["piece_batch_id"] is None for o in outputs)
    # No new entry, batch or reservation: the second ask cost nothing.
    assert len(p.entries()) == 1 and len(p.rows("select state from piece_batch")) == 1
    assert p.reservations() == [first]


def test_a_request_asked_again_after_its_batch_expired_is_queued_again(played) -> None:
    p = played()
    first = _queued(p)
    # not_after is 25 minutes on (the session started 5 minutes ago and stops at 1800 s); 28 is
    # past it and its two-minute allowance.
    p.later(minutes=28)
    p.worker.run_once()
    assert p.rows("select state from piece_request")[0]["state"] == "failed"
    # The same kind asked again makes the same job: it is a new entry, never a stalled one.
    p.ask()
    p.beat("idle", at=p.now + dt.timedelta(minutes=28))
    p.worker.run_once()
    entries = p.entries()
    assert len(entries) == 2 and first in entries
    _, first_ready, _, _ = p.entry(first)
    _, second_ready, _, _ = p.entry(next(e for e in entries if e != first))
    assert first_ready["job_sha256"] == second_ready["job_sha256"]
    states = [
        row["state"] for row in p.rows("select state from piece_request order by requested_at")
    ]
    assert states == ["failed", "queued"]


def test_a_done_marker_that_is_not_this_entry_s_ends_it_without_stopping_the_worker(played) -> None:
    p = played()
    _queued(p)
    # Another session's marker filed under this entry's name (same code and models, other stops).
    p.run_the_entry(session="0" * 64)
    report = p.worker.run_once()
    assert report["session"] == "warm"
    [batch] = p.rows("select state, refusal from piece_batch")
    assert (batch["state"], batch["refusal"]) == ("refused", "marker_not_this_entry")
    assert p.rows("select variant from piece_output") == []
    [reservation] = p.reservations()
    assert reservation["state"] == "unknown"


def test_two_worlds_asking_one_kind_share_one_run_and_one_charge(played) -> None:
    p = played()
    with p.bench.runtime.session(p.workspace_id) as connection:
        registered_world(connection, p.workspace_id, "w-second", kind=GENERATED)
    p.ask()
    p.ask(world_id="w-second")
    p.beat("idle")
    p.worker.run_once()
    _, _, job, requests = p.entry()
    # One item set for the one request digest both requests hold.
    assert len(requests) == 1 and len(job["items"]) == 4
    p.run_the_entry(milliseconds=40743)
    p.worker.run_once()
    rows = p.rows("select piece_request_id, state from piece_request order by requested_at")
    assert [row["state"] for row in rows] == ["made", "made"]
    assert len(p.rows("select variant from piece_output")) == 8
    settled = sorted(Decimal(r["settled_usd"]) for r in p.reservations())
    # The measured time is charged once, to the oldest request: USD 0.020372 and 0.
    assert settled == [Decimal("0"), Decimal("0.020372")]


def test_a_settlement_the_authority_did_not_take_is_retried_on_the_next_pass(
    played, monkeypatch
) -> None:
    p = played()
    _queued(p)
    p.run_the_entry()
    failing = {"left": 1}
    from exulanica.spending import ledger

    real_settle = ledger.WorkspaceSpending.settle

    def settle_once_failing(self, ticket, usage):
        if failing["left"]:
            failing["left"] -= 1
            raise ledger.SettlementNotRecorded("the lock timed out")
        return real_settle(self, ticket, usage)

    monkeypatch.setattr(ledger.WorkspaceSpending, "settle", settle_once_failing)
    p.worker.run_once()
    assert p.rows("select state from piece_request")[0]["state"] == "made"
    assert p.reservations()[0]["state"] == "dispatched"
    assert p.rows("select settled_at from piece_settlement")[0]["settled_at"] is None
    p.worker.run_once()
    assert p.reservations()[0]["state"] == "settled"
    assert p.rows("select settled_at from piece_settlement")[0]["settled_at"] is not None


def test_one_workspace_s_fault_does_not_stop_another_s_pass(played, monkeypatch) -> None:
    p = played()
    p.ask()
    p.beat("idle")
    broken = uuid.uuid4()
    real = batches.decide_cancelled

    def decide(connection, workspace_id):
        if workspace_id == broken:
            raise RuntimeError("a fault in one workspace")
        return real(connection, workspace_id)

    monkeypatch.setattr(batches, "decide_cancelled", decide)
    p.worker.workspaces = lambda: [broken, p.workspace_id]
    report = p.worker.run_once()
    assert str(broken) not in report["workspaces"]
    assert report["workspaces"][str(p.workspace_id)]["queued"]


def test_a_malformed_output_ends_the_batch_refused_and_still_settles_its_time(played) -> None:
    p = played()
    _queued(p)
    p.run_the_entry(milliseconds=40743)
    entry, ready, _, _ = p.entry()
    marker = json.loads(p.bucket.get(f"done/{entry}.json"))
    p.bucket.put(f"out/pieces/{'0' * 64}.glb", b"x")
    p.bucket.put(
        f"done/{entry}.json",
        build_done(
            entry_id=entry,
            job_sha256=ready["job_sha256"],
            session_sha256=p.session_sha256,
            claimed_at=marker["claimed_at"],
            ended_at=marker["ended_at"],
            ran={
                **{k: marker[k] for k in ("items", "request_milliseconds", "results_ended_at")},
                "receipts": [*marker["receipts"], "0" * 64],
            },
        ),
    )
    p.worker.run_once()
    [batch] = p.rows("select state, refusal from piece_batch")
    assert (batch["state"], batch["refusal"]) == ("refused", "outputs_unreadable")
    [reservation] = p.reservations()
    assert reservation["state"] == "settled"
    assert Decimal(reservation["settled_usd"]) == Decimal("0.020372")


@pytest.mark.parametrize("error", [OSError, RuntimeError])
def test_an_entry_that_never_reached_the_bucket_is_refused_and_its_reservations_released(
    played, error
) -> None:
    # Whatever fails before ready.json (a refused write, or any other error), no session can have
    # taken the entry, so nothing of it was sent.
    p = played()
    p.ask()
    p.beat("idle")
    put = p.bucket.put

    def refusing(key, data):
        if key.endswith("/job.json"):
            raise error("the bucket refused the write")
        return put(key, data)

    p.bucket.put = refusing  # type: ignore[method-assign]
    p.worker.run_once()
    assert p.entries() == []
    [batch] = p.rows("select state, refusal from piece_batch")
    assert (batch["state"], batch["refusal"]) == ("refused", "not_sent")
    [row] = p.rows("select state, failure from piece_request")
    assert (row["state"], row["failure"]) == ("failed", "not_sent")
    [reservation] = p.reservations()
    assert reservation["state"] == "released"


def test_a_request_cancelled_before_its_batch_is_recorded_leaves_nothing_sent(
    played, monkeypatch
) -> None:
    p = played()
    [made] = p.ask()
    p.beat("idle")
    real = batches.waiting_requests

    def stale(connection, workspace_id):
        rows = real(connection, workspace_id)
        # The person cancels between the worker's read and its record.
        store.cancel_piece_request(connection, workspace_id, made.piece_request_id)
        return rows

    monkeypatch.setattr(batches, "waiting_requests", stale)
    p.worker.run_once()
    assert p.entries() == [] and p.rows("select state from piece_batch") == []
    assert p.rows("select state from piece_request")[0]["state"] == "cancelled"
    [reservation] = p.reservations()
    assert reservation["state"] == "released"


def test_a_settlement_is_held_to_its_reservation_and_its_job_s_stop(played) -> None:
    p = played()
    _queued(p)
    # 150,000 ms is inside the job's 180 s stop but costs USD 0.075: settled at the USD 0.06
    # reservation.
    p.run_the_entry(milliseconds=150_000)
    p.worker.run_once()
    [reservation] = p.reservations()
    assert Decimal(reservation["settled_usd"]) == Decimal("0.06")


def test_a_done_marker_stating_more_than_its_stop_is_settled_unknown(played) -> None:
    p = played()
    _queued(p)
    # The job's stop is 180 s; a marker stating one millisecond more is not a measurement the
    # session could have made, so its whole reservation stays until an administrator reconciles it.
    p.run_the_entry(milliseconds=180_001)
    p.worker.run_once()
    [reservation] = p.reservations()
    assert reservation["state"] == "unknown"
    assert Decimal(reservation["settled_usd"]) == Decimal("0.06")


def test_nothing_is_queued_that_the_session_could_not_finish(played) -> None:
    p = played()
    p.ask()
    # Started 1,560 s ago with an 1,800 s stop: 240 s left, less the 120 s allowance, is 120 s,
    # short of the job's 180 s stop.
    p.beat("idle", started=dt.timedelta(seconds=1560))
    p.worker.run_once()
    assert p.entries() == [] and p.reservations() == []
    assert p.rows("select state from piece_request")[0]["state"] == "requested"


def test_a_queued_request_its_workspace_s_deletion_cancelled_is_settled_unknown(played) -> None:
    p = played()
    entry = _queued(p)
    p.tombstone()
    p.worker.run_once()
    # The entry is withdrawn before the settlement is decided, so a session that has not claimed it
    # never does.
    withdrawn = json.loads(p.bucket.get(f"withdrawn/{entry}.json"))
    assert (withdrawn["entry_id"], withdrawn["profile"]) == (
        entry,
        "exulanica.generated-asset-queue-withdrawn/v1",
    )
    [row] = p.rows("select state, failure from piece_request")
    assert (row["state"], row["failure"]) == ("cancelled", "workspace_deleted")
    [settlement] = p.rows("select basis, settled_at from piece_settlement")
    assert settlement["basis"] == "unknown" and settlement["settled_at"] is not None
    [reservation] = p.reservations()
    assert reservation["state"] == "unknown"


def test_a_request_the_allowance_refuses_stays_waiting(played) -> None:
    p = played(granted="0.05")
    p.ask()
    p.beat("idle")
    p.worker.run_once()
    [row] = p.rows("select state from piece_request")
    assert row["state"] == "requested"
    assert p.bucket.keys("queue/") == [] and p.reservations() == []


def test_nothing_is_queued_while_the_session_is_not_warm(played) -> None:
    p = played()
    p.ask()
    assert p.worker.run_once()["session"] == "starting"
    p.beat("loading")
    assert p.worker.run_once()["session"] == "starting"
    assert p.bucket.keys("queue/") == []
    [row] = p.rows("select state from piece_request")
    assert row["state"] == "requested"


def test_a_piece_made_by_other_models_is_not_kept(played) -> None:
    p = played()
    _queued(p)
    p.run_the_entry(components="0" * 64)
    p.worker.run_once()
    [row] = p.rows("select state from piece_request")
    assert row["state"] == "refused"
    assert p.rows("select variant from piece_output") == []
    assert list(p.pieces.iter_blob_ids()) == []


def test_a_heartbeat_that_does_not_read_stops_queueing_and_nothing_else(played) -> None:
    p = played()
    _queued(p)
    p.run_the_entry(milliseconds=40743)
    p.ask(kinds=(("lantern", 1),))
    # The latest heartbeat is not one: the session is not warm, and the batch is still followed.
    p.bucket.put(f"session/{p.session_sha256}/beat-29991231T000000Z.json", b"{}")
    report = p.worker.run_once()
    assert report["session"] == "starting"
    states = [r["state"] for r in p.rows("select state from piece_request order by requested_at")]
    assert states == ["made", "requested"]
    [reservation] = p.reservations()
    assert Decimal(reservation["settled_usd"]) == Decimal("0.020372")


def test_a_deletion_between_a_batch_s_record_and_its_offer_sends_nothing(
    played, monkeypatch
) -> None:
    from exulanica.generation import entries

    p = played()
    p.ask()
    p.beat("idle")
    real = entries.write_files

    def then_deleted(*arguments, **keywords):
        real(*arguments, **keywords)
        p.tombstone()

    monkeypatch.setattr(entries, "write_files", then_deleted)
    p.worker.run_once()
    # The batch was erased before its ready.json: no session can take what was never offered.
    assert p.entries() == []
    p.worker.run_once()
    [settlement] = p.rows("select basis from piece_settlement")
    assert settlement["basis"] == "not_sent"
    [reservation] = p.reservations()
    assert reservation["state"] == "released"


def test_a_deleted_request_whose_reservation_was_only_admitted_is_released(
    played, monkeypatch
) -> None:
    from exulanica.spending import ledger

    p = played()
    p.ask()
    p.beat("idle")

    def deleted_then_refused(self, ticket):
        p.tombstone()
        raise RuntimeError("the dispatch did not happen")

    monkeypatch.setattr(ledger.WorkspaceSpending, "dispatch", deleted_then_refused)
    p.worker.run_once()
    monkeypatch.undo()
    p.worker.run_once()
    [settlement] = p.rows("select basis, usd from piece_settlement")
    assert (settlement["basis"], settlement["usd"]) == ("not_sent", Decimal(0))
    [reservation] = p.reservations()
    assert reservation["state"] == "released"


def test_a_gpu_the_compute_catalog_no_longer_prices_is_given_nothing_and_settled_unknown(
    played,
) -> None:
    p = played()
    _queued(p)
    p.run_the_entry(milliseconds=40743)
    p.ask(kinds=(("lantern", 1),))
    compute = p.worker.catalogs.compute
    p.worker.catalogs = dataclasses.replace(
        p.worker.catalogs,
        compute=dataclasses.replace(
            compute, entries={k: v for k, v in compute.entries.items() if k != COMPUTE_KEY}
        ),
    )
    p.worker.run_once()
    rows = p.rows("select state from piece_request order by requested_at")
    # The made batch cannot be priced, so its whole reservation stays until reconciled; the
    # waiting request is admitted against nothing.
    assert [r["state"] for r in rows] == ["made", "requested"]
    [reservation] = p.reservations()
    assert reservation["state"] == "unknown"
    assert Decimal(reservation["settled_usd"]) == Decimal("0.06")
