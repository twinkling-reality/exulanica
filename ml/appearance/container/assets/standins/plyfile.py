"""Stand-in for plyfile (GPL-3.0-or-later): the job never reads or writes PLY files."""


class _Refuse:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "plyfile is not installed in the generated asset job; nothing may write PLY"
        )


PlyData = _Refuse
PlyElement = _Refuse
