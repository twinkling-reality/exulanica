"""Stand-in for pymeshlab (GPL-3.0): the post-process simplifies; nothing here may reduce faces."""


def __getattr__(name: str) -> object:
    raise RuntimeError(f"pymeshlab.{name} is not installed in the generated asset job")
