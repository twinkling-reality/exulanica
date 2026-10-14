#!/usr/bin/env python3
"""Write the Ollama Modelfile a model on this computer is created from, read from its manifest
recipe, and print the command and server settings that serve it as measured.

    uv run python scripts/laptop_model_recipe.py MODEL_ID OUT.Modelfile

The recipe is data in ``exulanica/models/models.manifest.json`` (``ModelSpec.recipe``): the Ollama
library model the alias is created from, the parameters it is created with, the server's own chat
renderer and parser where named, and the server environment it was measured under. This writes
nothing else and runs nothing: it downloads no weight, and creating the alias (``ollama create``)
needs the library model already on this computer.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exulanica.models.manifest import load_manifest  # noqa: E402


def modelfile(recipe: dict) -> str:
    """The Modelfile the recipe states, one directive a line."""
    lines = [f"FROM {recipe['from']}"]
    lines += [f"PARAMETER {name} {value}" for name, value in recipe["parameters"].items()]
    for directive in ("renderer", "parser"):
        if directive in recipe:
            lines.append(f"{directive.upper()} {recipe[directive]}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    model_id, out = argv
    manifest = load_manifest()
    spec = manifest.spec(model_id)
    if not spec.recipe:
        print(f"{model_id} is not a model on this computer: it has no recipe", file=sys.stderr)
        return 1
    recipe = dict(spec.recipe)
    Path(out).write_text(modelfile(recipe), encoding="utf-8")
    environment = {k: v for k, v in (recipe.get("server_environment") or {}).items()}
    basis = environment.pop("basis", None)
    print(f"wrote {out}")
    print(f"create it:  ollama create {model_id} -f {out}")
    if environment:
        print("serve it as measured:  " + " ".join(f"{k}={v}" for k, v in environment.items()))
        print("  then: ollama serve")
    if basis:
        print(f"why: {basis}")
    origin = manifest.provider(spec.provider).origin
    print(f"and declare {origin} in EXULANICA_EGRESS_ALLOWLIST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
