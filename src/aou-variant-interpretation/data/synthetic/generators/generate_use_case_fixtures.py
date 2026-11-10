#!/usr/bin/env python3
"""
Writes the two fixtures the curated demo use cases (use_cases/) need outside BigQuery:

    api/src/main/resources/fixtures/phenotype_use_cases.json
        The phenotype-matched stats and ancestry/age breakdowns for each use case's condition.
        The backend has no genotype data to compute these from, so it serves them from here when
        a search matches a use case, and makes them up (MockPhenotypeData) otherwise.

    ui/src/data/useCases.json
        The entry page's "Try an example" menu.

The VAT rows and condition tables come from the other two generators, which read the same use
cases, so rerun all three after changing one.

Usage:
    python3 data/synthetic/generators/generate_use_case_fixtures.py

Defaults assume it's run from the repo root; both paths can be overridden.
"""

import argparse
import json
import os

from use_cases import USE_CASES
from use_cases.common import phenotype_fixture, ui_example


def write_json(path, value):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {len(value)} use cases to {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phenotype-out", default="api/src/main/resources/fixtures/phenotype_use_cases.json")
    ap.add_argument("--ui-out", default="ui/src/data/useCases.json")
    args = ap.parse_args()

    write_json(args.phenotype_out, [phenotype_fixture(case) for case in USE_CASES])
    write_json(args.ui_out, [ui_example(case) for case in USE_CASES])


if __name__ == "__main__":
    main()
