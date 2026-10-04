"""Stand-in for rembg: the cut-out comes from BiRefNet, so any call here is a mistake."""


def new_session(*args: object, **kwargs: object) -> object:
    raise RuntimeError("rembg is not installed in the generated asset job; pass an RGBA cut-out")


def remove(*args: object, **kwargs: object) -> object:
    raise RuntimeError("rembg is not installed in the generated asset job; pass an RGBA cut-out")
