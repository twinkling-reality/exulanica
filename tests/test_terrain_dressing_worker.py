"""Terrain coverage keeps worker erasure fencing without treating cached geometry as authority."""

from exulanica.world.kinds import worker as worker_module

from test_kind_worker import _PoolWithItsOwnLock


def test_erasure_drops_workspace_coverage_and_fences_a_late_result(monkeypatch):
    pool = _PoolWithItsOwnLock()
    worker = worker_module.KindWorker(lambda: pool)
    monkeypatch.setattr(worker_module, "_worker", worker)
    own = "terrain-coverage:v1:ours:" + "a" * 64
    foreign = "terrain-coverage:v1:theirs:" + "a" * 64
    late = "terrain-coverage:v1:ours:" + "b" * 64
    worker.checks.put(own, {"coverage": "old"})
    worker.checks.put(foreign, {"coverage": "foreign"})
    assert (
        worker.run(late, 0.001, lambda: {}, workspace="ours", kept=worker.checks).status
        == "overran"
    )
    worker.forget_receipts("ours", frozenset({"c" * 64}))
    pool.futures[0].set_result({"coverage": "late"})
    assert worker.checks.get(own) is None
    assert worker.checks.get(late) is None
    assert worker.checks.get(foreign) == {"coverage": "foreign"}
    worker.close()
