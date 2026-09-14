"""The preview adapter accepts only catalog-supported recipes, never file paths or commands."""

import importlib.util
from pathlib import Path

import pytest
from exulanica.env import resolve_briefs_path

spec = importlib.util.spec_from_file_location(
    "parametric_preview",
    Path(__file__).parents[1] / "scripts/parametric_character/preview_server.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def recipe():
    return {
        field["key"]: field["default"]
        for field in module.FAMILY["controls"] + module.FAMILY["choices"]
    }


def test_recipe_accepts_declared_extremes():
    for bound in ("min", "max"):
        value = recipe()
        value.update({c["key"]: c[bound] for c in module.FAMILY["controls"]})
        assert module.validate_recipe(value) == value


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -100, 10000, "175"])
def test_invalid_dimensions_are_rejected(value):
    r = recipe()
    r["heightCm"] = value
    with pytest.raises(ValueError):
        module.validate_recipe(r)


def test_catalog_does_not_accept_arbitrary_asset_paths():
    r = recipe()
    r["hair"] = "../../secret"
    with pytest.raises(ValueError):
        module.validate_recipe(r)
    r = recipe()
    r["command"] = "anything"
    with pytest.raises(ValueError):
        module.validate_recipe(r)


def test_declared_target_pairs_exist_in_pinned_source():
    source = (
        resolve_briefs_path("parametric-human", root=Path(__file__).parents[1])
        / "mpfb2/src/mpfb/data/targets"
    )
    if not source.exists():
        pytest.skip("Optional pinned preparation environment is not installed")
    for c in module.FAMILY["controls"]:
        for target in c.get("targets", []):
            for direction in ("incr", "decr"):
                assert (source / f"{target}-{direction}.target.gz").is_file()
