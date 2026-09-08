import pytest
from exulanica.api.routes import evidence


def bypass(*args: object, **kwargs: object) -> None:
    pass


evidence._authorize_original = bypass
SELECTOR = (
    "tests/test_asset_read_currency.py::test_original_saved_urls_refuse_required_mask_and_ranges"
)
raise SystemExit(pytest.main([SELECTOR, "-q", "-ra"]))
