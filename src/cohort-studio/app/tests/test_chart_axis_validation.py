import pytest
from pydantic import ValidationError
from main import ChartSpec


def test_chart_axis_validation_rejects_invalid_ranges_and_scales():
    for axis in ({'scale': 'log', 'min': 0}, {'min': 5, 'max': 5},
                 {'max': float('inf')}, {'scale': 'unsupported'}):
        with pytest.raises(ValidationError):
            ChartSpec.model_validate({'kind': 'bar', 'x': 'tissue', 'x_axis': axis})

