"""Where a model credential comes from: the environment, or a ``.env`` file named explicitly.

A process holds a key it was given and no other. A ``.env`` file in or above the working directory
gives it nothing: a search up from there would hand the key to every process started beneath a
checkout that holds one, a worktree or a child given a cleaned environment among them. Every key
written here is made up, and its variable is the manifest's, never spelled here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role

from model_fakes import FakeTransport, RecordingPolicy

PLANTED = "made-up-for-this-test"


@pytest.fixture
def variable(manifest, monkeypatch) -> str:
    """The variable the cheap reasoning role's provider reads its key from, unset for the test."""
    name = manifest.provider(manifest[Role.REASONING_CHEAP].provider).api_key_env
    monkeypatch.delenv(name, raising=False)
    return name


@pytest.fixture
def worktree(tmp_path, monkeypatch):
    """A working directory below another, as a worktree sits below the checkout holding it."""
    here = tmp_path / "worktree"
    here.mkdir()
    monkeypatch.chdir(here)
    return here


def built(manifest, transport: FakeTransport, **given) -> ModelClient:
    return ModelClient(
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
        **given,
    )


@pytest.mark.parametrize("in_parent", [True, False], ids=["parent", "working-directory"])
def test_a_client_gets_no_key_from_a_dotenv_nobody_named(manifest, variable, worktree, in_parent):
    holder = worktree.parent if in_parent else worktree
    (holder / ".env").write_text(f"{variable}={PLANTED}\n", encoding="utf-8")

    with pytest.raises(ModelError, match=f"no credential: set {variable} "):
        built(manifest, FakeTransport())


def test_a_client_reads_the_dotenv_it_is_given(manifest, variable, worktree):
    dotenv = worktree.parent / ".env"
    dotenv.write_text(f"# made up\n{variable}={PLANTED}\n", encoding="utf-8")
    transport = FakeTransport()

    client = built(manifest, transport, dotenv=dotenv)
    client.chat(Role.REASONING_CHEAP, [{"role": "user", "content": "x"}], prompt_version="t")

    assert transport.requests[-1]["headers"]["Authorization"] == f"Bearer {PLANTED}"
