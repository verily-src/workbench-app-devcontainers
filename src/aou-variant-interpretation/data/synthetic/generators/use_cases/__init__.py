"""
The curated demo use cases, in the order the entry page's example menu lists them.

To add one: write a module here with a CASE (see common.py for the spec types, and any existing
use case for the pattern), add it below, and rerun both generators.
"""

from . import familial_hypercholesterolemia, hypertrophic_cardiomyopathy, long_qt_syndrome, tetralogy_of_fallot
from .common import validate

USE_CASES = [
    tetralogy_of_fallot.CASE,
    hypertrophic_cardiomyopathy.CASE,
    familial_hypercholesterolemia.CASE,
    long_qt_syndrome.CASE,
]

for _case in USE_CASES:
    validate(_case)
