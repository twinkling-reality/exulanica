"""Stand-in for pymeshlab (GPL-3.0): the post-process simplifies; nothing here may reduce faces.

Step1X-3D names pymeshlab.MeshSet in a type annotation, which Python evaluates when the module
loads (measured on Nebius, 2026-10-06), so every public name is a class that may be named,
annotated and tested against, and refuses only when made or called.
"""


class _Refuse:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(
            f"pymeshlab.{type(self).__name__} is not installed in the generated asset job"
        )


_NAMES: dict[str, type] = {}


def __getattr__(name: str) -> type:
    if name.startswith("__"):
        raise AttributeError(name)
    if name not in _NAMES:
        _NAMES[name] = type(name, (_Refuse,), {"__module__": __name__})
    return _NAMES[name]
