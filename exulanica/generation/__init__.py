"""Generated pieces: asking a GPU for new pieces of a look, and keeping what was asked.

A person or the Companion asks for pieces of a world's look for some thing kinds. This package
turns the ask into piece requests (:mod:`exulanica.generation.requests`), states what they will
cost and how long they will take, and keeps each request in the workspace's store
(:mod:`exulanica.generation.store`). The GPU work itself runs elsewhere (``ml/appearance``) on a
session the operator starts; nothing here creates a cloud resource or spends.
"""
