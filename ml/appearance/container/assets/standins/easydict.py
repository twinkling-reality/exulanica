"""Stand-in for easydict (LGPL-3.0): a dict whose keys read and write as attributes."""

from typing import Any


class EasyDict(dict):
    def __init__(self, value: Any = None, **kwargs: Any) -> None:
        super().__init__()
        for key, item in dict(value or {}, **kwargs).items():
            self[key] = item

    def __setitem__(self, key: str, item: Any) -> None:
        if isinstance(item, dict) and not isinstance(item, EasyDict):
            item = EasyDict(item)
        elif isinstance(item, list):
            item = [EasyDict(x) if isinstance(x, dict) else x for x in item]
        super().__setitem__(key, item)

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error

    def __setattr__(self, key: str, item: Any) -> None:
        self[key] = item


edict = EasyDict
