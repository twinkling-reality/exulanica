"""Erasing a kept kind scrubs copies and cannot be undone by late local callbacks."""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from exulanica.api.kind_drafts import KindDraft, KindDrafts
from exulanica.api.routes.world_kinds import _draft_view
from exulanica.world.kinds import repository
from exulanica.world.kinds import worker as worker_module
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.worker import KindWorker, check_key

from test_kind_worker import _PoolWithItsOwnLock
from test_world_kinds_postgres import _uploaded


def test_kind_eviction_discards_late_checks_and_composition_but_keeps_other_worlds(monkeypatch):
    pool = _PoolWithItsOwnLock()
    worker = KindWorker(lambda: pool)
    monkeypatch.setattr(worker_module, "_worker", worker)
    composer = worker_module.WorkerComposer("ours")
    digest = "a" * 64
    key = check_key("ours", digest)
    other = check_key("theirs", digest)
    worker.checks.put(other, {"report": "other workspace"})
    worker.drawings.put("other world", {"body": "retained"})
    composer.drawn = ("stale world", {"body": "private"})
    assert (
        worker.run(key, 0.001, lambda: {}, workspace="ours", kept=worker.checks).status == "overran"
    )
    worker.forget_kind("ours", digest)
    pool.futures[0].set_result({"report": "erased late content"})
    composer.keep()
    assert worker.checks.get(key) is None
    assert worker.drawings.get("stale world") is None
    assert worker.checks.get(other) == {"report": "other workspace"}
    assert worker.drawings.get("other world") == {"body": "retained"}
    worker.close()


def test_parsed_kind_eviction_cannot_be_undone_by_a_reader_already_parsing(monkeypatch):
    kind = read_kind(_uploaded("farm"))
    repository.forget_kind(kind.sha256)
    original = repository.read_kind

    def read_and_erase(document):
        read = original(document)
        repository.forget_kind(kind.sha256)
        return read

    monkeypatch.setattr(repository, "read_kind", read_and_erase)
    assert repository._read_stored(dict(kind.document), kind.sha256).sha256 == kind.sha256
    assert not any(key[0] == kind.sha256 for key in repository._read)


def test_draft_erasure_covers_pre_finish_identity_and_separate_read_copy(monkeypatch):
    holder = KindDrafts()
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    draft = KindDraft(
        uuid.uuid4(), workspace, actor, "private sentence", dt.datetime.now(dt.UTC), holder.clock()
    )
    holder._drafts[draft.draft_id] = draft
    holder.advance(draft, kind="private_label", version=1)
    holder.erase_kind(workspace, "private_label", 1)
    holder.finish(draft, state="ready", kind="private_label", version=1)
    assert draft.erased and draft.description == "" and draft.kind is None
    assert holder.read(workspace, actor, draft.draft_id) is None
    # Another process already holds a ready draft; its route receives a dataclass copy.
    ready = KindDraft(
        uuid.uuid4(),
        workspace,
        actor,
        "",
        dt.datetime.now(dt.UTC),
        holder.clock(),
        state="ready",
        kind="private_label",
        version=1,
        left_out=("private omitted phrase",),
    )
    holder._drafts[ready.draft_id] = ready
    copied = dataclasses.replace(ready)
    monkeypatch.setattr(repository.WorkspaceKinds, "version", lambda *_: None)
    view = _draft_view(copied, None, workspace, holder.clock(), holder)
    assert ready.erased and copied.erased
    assert view.kind is None and view.execution is None and view.refusal is None
    assert not holder.listing(workspace, actor)
