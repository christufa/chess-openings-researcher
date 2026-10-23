import pytest

from openings_research.storage import identifier


@pytest.mark.parametrize("value", ["x; DROP TABLE y", "a.b", "x`", "a-b", ""])
def test_rejects_unsafe_sql_identifiers(value):
    with pytest.raises(ValueError):
        identifier(value)
