"""The depth checkpoint is stated in the model manifest, and stating it there re-keyed nothing.

Until 2026-09-16 the worker chose MoGe from two environment variables with defaults in Python, so
the manifest named no depth model and a personal model right could not name depth by role. The pin
now lives in ``local_roles.depth``. The move is safe only if every artifact identity it can reach
is unchanged, so the values below were recorded on main at 42f296bf, before the move, by the same
computation this module repeats, and are compared byte for byte.

The two whole-registry digests were recorded again on main at e76503fd, still before the move, when
the tile bake stage ``baked_tile`` joined the registry. That stage moves only those two values:
every stage recorded at 42f296bf kept its own parameter digest, and every other value is unchanged.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import types

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.evidence.blob import BlobId
from exulanica.ingest import worker_command
from exulanica.ingest.personal_admission import role_handoff
from exulanica.ingest.stages import STAGES, idempotency_key, input_digest_of, pipeline_digest, stage
from exulanica.ingest.stages import depth as depth_stage
from exulanica.ingest.stages.segmentation import (
    DEPTH_ROLE,
    DETECTION_ROLE,
    SEGMENTATION_ROLE,
    local_model_role,
    local_model_roles,
)
from exulanica.models.handoff import ModelHandoff, ModelIdentity
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest
from exulanica.reconstruction import moge

#: Recorded with the depth pin still in worker defaults: on main 42f296bf, and the two
#: whole-registry digests again on main e76503fd.
GOLDEN = {
    "depth_model_id": "Ruicheng/moge-2-vitl@39c4d5e957afe587e04eec59dc2bcc3be5ecd968",
    "depth_key": "b61967020fae53eedf34d3ca0b9e67a5365e743b41b265de99ef1c0bc97c3e4f",
    "pipeline_digest": "05becde891860583",
    "pipeline_version": 3,
    "stages_digest": "1ece64d3241453c4dee81b4b5661a16beb30e88e29a27051f1003ca3c0a51817",
    "local_roles_digest": "1ec7d3a7f36817d12a975c5b0a48461d96cf27db1ad7d37cee29a699be7837a5",
    "blob": "e4f90aa67ee4c3c76b62f706472fe2e6d8072ed92ac8151e048492d490a60fee",
    "inputs": "fd2b925e8379846ee7ea096f62a44a127d70deb6baba9e9d3339869ec0f9e0fe",
}

#: The README at the pinned revision, retrieved 2026-09-16: its frontmatter, with CRLF endings.
MOGE_README = b"---\r\nlicense: mit\r\n---\r\n"


class _Loaded:
    """What ``MoGeModel.from_pretrained`` returns, with no scale head and no weights."""

    def to(self, device):
        return self

    def eval(self):
        return self


@pytest.fixture
def loaded(monkeypatch):
    """Build a real ``MoGeDepthModel`` with torch and MoGe replaced, recording what it loads.

    In-process torch is not safe in this suite, and nothing here needs a forward pass: only what
    the constructor asks for and what it calls itself.
    """
    requested = []

    class MoGeModel:
        @staticmethod
        def from_pretrained(repo_id, **kwargs):
            requested.append((repo_id, kwargs))
            return _Loaded()

    torch = types.ModuleType("torch")
    torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.device = lambda name: name
    v2 = types.ModuleType("moge.model.v2")
    v2.MoGeModel = MoGeModel
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "moge", types.ModuleType("moge"))
    monkeypatch.setitem(sys.modules, "moge.model", types.ModuleType("moge.model"))
    monkeypatch.setitem(sys.modules, "moge.model.v2", v2)
    return requested


def test_the_manifest_pins_the_depth_checkpoint_it_always_ran():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    role = local_model_role(DEPTH_ROLE, document)
    assert role.fallback is None
    assert role.primary.ref == GOLDEN["depth_model_id"]
    assert role.primary.license == "mit"
    entry = document["local_models"][role.primary.repo_id]
    assert entry["readme_sha256"] == hashlib.sha256(MOGE_README).hexdigest()
    assert stage("depth").model_role == DEPTH_ROLE
    # Depth is not a segmentation role, so nothing that reads those two sees it.
    assert set(local_model_roles(document)) == {SEGMENTATION_ROLE, DETECTION_ROLE}


def test_moving_the_depth_pin_into_the_manifest_re_keys_no_artifact(loaded):
    """Every identity the pin can reach, computed now and compared with main before the move."""
    pin = local_model_role(DEPTH_ROLE).primary
    built = moge.MoGeDepthModel(model_id=pin.repo_id, revision=pin.revision)
    assert loaded == [(pin.repo_id, {"revision": pin.revision})]
    depth_binding = {"model_id": built.model_id}
    assert depth_binding["model_id"] == GOLDEN["depth_model_id"]

    blob = BlobId.of_bytes(b"model right golden key fixture")
    inputs = input_digest_of(
        [hashlib.sha256(b"intake").digest(), hashlib.sha256(b"receipt").digest()]
    )
    assert blob.hex == GOLDEN["blob"]
    assert inputs.hex() == GOLDEN["inputs"]
    key = idempotency_key(blob, STAGES["depth"], inputs, binding=depth_binding)
    assert key == GOLDEN["depth_key"]

    manifest = load_manifest()
    bindings = {
        "vision": {"model_id": manifest[Role.VISION].primary.model_id},
        "depth": depth_binding,
    }
    assert pipeline_digest(bindings) == GOLDEN["pipeline_digest"]
    assert manifest.pipeline_version == GOLDEN["pipeline_version"]
    params = {key: [spec.version, spec.params_digest.hex()] for key, spec in sorted(STAGES.items())}
    assert sha256_of_canonical(params).hex() == GOLDEN["stages_digest"]
    pins = {
        name: [role.primary.as_identity(), role.fallback.as_identity() if role.fallback else None]
        for name, role in sorted(local_model_roles().items())
    }
    assert sha256_of_canonical(pins).hex() == GOLDEN["local_roles_digest"]


def test_the_worker_loads_moge_from_the_manifest_pin_alone(monkeypatch, loaded):
    built = worker_command._build_depth({worker_command.DEPTH_MODEL_ENV: "moge"})
    pin = local_model_role(DEPTH_ROLE).primary
    assert isinstance(built, moge.MoGeDepthModel)
    assert built.model_id == pin.ref
    assert loaded == [(pin.repo_id, {"revision": pin.revision})]


@pytest.mark.parametrize("retired", worker_command.RETIRED_DEPTH_ENVS)
def test_a_worker_still_configured_the_old_way_refuses_to_start(loaded, retired):
    """A deployment that pinned another checkpoint stops rather than quietly running this one."""
    with pytest.raises(ValueError, match="no longer read"):
        worker_command._build_depth(
            {worker_command.DEPTH_MODEL_ENV: "moge", retired: "example/other-checkpoint"}
        )
    assert loaded == []


def test_moge_takes_its_checkpoint_only_from_the_caller(loaded):
    with pytest.raises(TypeError):
        moge.MoGeDepthModel()
    pin = local_model_role(DEPTH_ROLE).primary
    for revision in (None, "main", pin.revision.upper()):
        with pytest.raises(ValueError, match="full lowercase Git commit"):
            moge.MoGeDepthModel(model_id=pin.repo_id, revision=revision)
    with pytest.raises(ValueError, match="repository identifier"):
        moge.MoGeDepthModel(model_id="", revision=pin.revision)
    assert loaded == []


def test_a_depth_right_granted_by_role_names_what_the_depth_stage_asks_for(loaded):
    pin = local_model_role(DEPTH_ROLE).primary
    built = moge.MoGeDepthModel(model_id=pin.repo_id, revision=pin.revision)
    granted = role_handoff(DEPTH_ROLE)
    assert granted == ModelHandoff.local(ModelIdentity.local(DEPTH_ROLE, pin.repo_id, pin.revision))
    assert depth_stage.model_handoff(built) == granted


def test_a_depth_role_that_is_not_pinned_is_refused():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    unpinned = copy.deepcopy(document)
    unpinned["local_models"][unpinned["local_roles"][DEPTH_ROLE]["primary"]]["revision"] = "main"
    with pytest.raises(ValueError, match="full lowercase revision"):
        local_model_role(DEPTH_ROLE, unpinned)
    missing = copy.deepcopy(document)
    del missing["local_roles"][DEPTH_ROLE]
    with pytest.raises(ValueError, match="does not bind the local role 'depth'"):
        local_model_role(DEPTH_ROLE, missing)
