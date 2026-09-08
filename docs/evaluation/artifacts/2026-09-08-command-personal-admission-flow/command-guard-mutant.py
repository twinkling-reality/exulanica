import inspect

import exulanica.ingest.privacy as privacy
import pytest

lines = inspect.getsource(privacy).splitlines(keepends=True)
needle = "    if not capture_mask_is_current(repository, capture_id):\n"
assert lines.count(needle) == 1
start = lines.index(needle)
assert "privacy screening is stale:" in lines[start + 2]
assert lines[start + 4].strip() == "return screening"
source = "".join(lines[:start] + lines[start + 4:])
exec(compile(source, privacy.__file__, "exec"), privacy.__dict__)
selector = (
    "tests/test_personal_admission_flow.py::"
    "test_changed_region_requires_current_mask_before_geometry"
)
raise SystemExit(pytest.main([selector, "-q"]))
