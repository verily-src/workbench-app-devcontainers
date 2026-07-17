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


def test_infer_sees_columns_empty_in_first_N_rows(tmp_path):
    """Inference must sample enough rows to correctly classify columns
    that are blank at the top of the file.

    Regression: the GTEx v10 SMATSSCR column is blank for its first
    ~2700 rows and integer-valued after. With the old sample_size=1000,
    inference saw only blanks and defaulted to text. Fix bumped the
    default to 5000. This test proves that fix is still in place.
    """
    from schema import infer_from_csv

    # BLANK_ROWS is chosen > old sample_size (1000) so any regression
    # that lowers the default back would fail this test.
    BLANK_ROWS = 1200
    TOTAL_ROWS = 1400

    csv = tmp_path / "sparse.tsv"
    lines = ["always_int\tlate_populated"]
    for i in range(BLANK_ROWS):
        lines.append(f"{i}\t")                # late_populated is empty
    for i in range(BLANK_ROWS, TOTAL_ROWS):
        lines.append(f"{i}\t{i}")             # late_populated has values
    csv.write_text("\n".join(lines))

    mappings = infer_from_csv(str(csv))
    by_name = {m.column: m for m in mappings}

    # Sanity: an always-populated integer column must classify correctly.
    # If this fails, _is_integer is broken and the next assertion isn't
    # meaningful.
    assert by_name["always_int"].type == "integer"

    assert by_name["late_populated"].type == "integer", (
        f"expected integer, got {by_name['late_populated'].type} — "
        f"did someone lower the sample_size back below {BLANK_ROWS}?"
    )
