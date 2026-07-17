"""Tests for schema.py type-inference helpers."""
from schema import _is_integer


def test_is_integer_accepts_90_percent_numeric():
    """9 valid integers + 1 junk value = 90% → should still classify as integer.
    Real-world data has noise; requiring 100% would misinfer nearly any column."""
    values = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "junk"]
    assert _is_integer(values) is True


def test_is_integer_rejects_below_90_percent():
    """8 valid + 2 junk = 80% → not integer.
    Guards against someone loosening the threshold below the 90% intent."""
    values = ["1", "2", "3", "4", "5", "6", "7", "8", "junk", "oops"]
    assert _is_integer(values) is False
