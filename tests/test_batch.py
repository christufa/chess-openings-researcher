import pytest

from openings_research.batch import plan


@pytest.mark.parametrize("names", [[], [" "], ["Italian", " italian "], [None], "Italian", ["x"] * 51])
def test_invalid_batch(names):
    with pytest.raises(ValueError):
        plan(names)


def test_names_are_trimmed_in_order():
    assert plan([" Italian Game", "French Defense "]) == {
        "runs": [{"opening": "Italian Game"}, {"opening": "French Defense"}]
    }
