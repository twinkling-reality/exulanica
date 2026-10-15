"""The code that runs the product without serving an HTTP request: operator commands and the parts
of hosts and workers that need no web framework.

It sits directly below :mod:`exulanica.api` in the layers contract (``pyproject.toml``): the web
layer imports it, and nothing here imports the web layer. The decision host, the society runtime,
the workers and the comparison runners are code of this kind that sits in :mod:`exulanica.api`.
"""
