"""Track A generation, outside the product: stage inputs on the Mac, run them on a rented GPU, check what comes back.

Nothing in this package imports torch at module level. The GPU backends import it lazily, inside the
container, and the stub backend lets the whole pipeline run on the Mac with no torch and no weights.
"""
