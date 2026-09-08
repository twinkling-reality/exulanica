import pytest
from exulanica.api.routes import evidence


def bypass(*args: object, **kwargs: object) -> None:
    pass


evidence._authorize_original = bypass
SELECTOR = "tests/test_asset_read_currency.py::test_final_check_sees_edit_during_buffer_read"
raise SystemExit(pytest.main([SELECTOR, "-q", "-ra"]))
