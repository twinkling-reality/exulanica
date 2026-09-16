"""Exulanica's training code: learned models that propose material recipes, and nothing else.

This package is not part of the product. It has its own environment (``ml/pyproject.toml``), runs
in its own container (``ml/container``), and nothing under ``exulanica/`` may import it, which the
import contract in the root ``pyproject.toml`` and ``tests/test_training_boundary.py`` hold. What
crosses back into the product is data: a model's weights by digest, and the receipt of the run
that made them. A proposal from a model is a recipe like any other, checked against the published
maker before anything stores it, and one read from a person's photographs waits for the personal
model right.
"""
