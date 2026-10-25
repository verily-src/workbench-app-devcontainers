import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ANALYSIS = Path(__file__).parents[1] / "analysis.py"
SPEC = importlib.util.spec_from_file_location("genetics_analysis", ANALYSIS)
analysis = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analysis
SPEC.loader.exec_module(analysis)
SAMPLE = ANALYSIS.with_name("input.csv")
DICTIONARY = ANALYSIS.with_name("variant_dictionary.csv")


def _run(source: Path, output: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(ANALYSIS), "--input", str(source),
         "--variant-dictionary", str(DICTIONARY),
         "--output-dir", str(output), *args],
        text=True, capture_output=True, check=False,
    )


def _csv(path: Path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_cli_writes_stratified_summary_and_trace_manifest(tmp_path):
    output = tmp_path / "result"
    run = _run(SAMPLE, output, "--cohort-size", "8", "--input-uri",
               "s3://input/cohort.csv", "--variant-dictionary-uri",
               "s3://input/variant_dictionary.csv", "--output-uri-prefix",
               "s3://results/run-1", "--source-resource", "demo-db",
               "--source-table", "cms_synpuf_100k.person",
               "--workflow-id", "workflow-7", "--run-id", "run-9")
    assert run.returncode == 0, run.stderr
    summary = _csv(output / "carrier_summary.csv")
    dictionary = _csv(output / "variant_dictionary.csv")
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert set(summary[0]) == set(analysis.OUTPUT_COLUMNS)
    assert {row["carrier_status"] for row in summary} == {"carrier", "noncarrier"}
    assert sum(int(row["people"]) for row in summary) == 6
    assert manifest["input"]["row_count"] == 6
    assert manifest["input"]["sha256"] == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    assert manifest["variant_dictionary"]["row_count"] == 1
    assert manifest["variant_dictionary"]["sha256"] == hashlib.sha256(
        DICTIONARY.read_bytes()).hexdigest()
    assert manifest["variant_dictionary"]["uri"] == "s3://input/variant_dictionary.csv"
    assert manifest["variant_dictionary"]["annotations_used_for_carrier_status"] is False
    assert manifest["cohort"] == {
        "cohort_size": 8, "matched_people": 6, "unmatched_cohort_members": 2,
    }
    assert manifest["analysis"]["status_counts"] == {"carrier": 3, "noncarrier": 3}
    assert manifest["analysis"]["summary_people_total"] == 6
    assert manifest["outputs"]["carrier_summary_csv"] == "s3://results/run-1/carrier_summary.csv"
    assert manifest["outputs"]["variant_dictionary_csv"] == \
        "s3://results/run-1/variant_dictionary.csv"
    assert dictionary == _csv(DICTIONARY)
    assert manifest["execution"]["workflow_id"] == "workflow-7"
    assert manifest["execution"]["run_id"] == "run-9"
    assert manifest["source"]["tables"] == ["cms_synpuf_100k.person"]
    assert "SYN_SAMPLE" not in (output / "carrier_summary.csv").read_text()
    assert "1001" not in (output / "carrier_summary.csv").read_text()
    assert all(row["synthetic_notice"] == analysis.SYNTHETIC_NOTICE for row in summary)
    carriers = [row for row in summary if row["carrier_status"] == "carrier"]
    assert sum(float(row["share_within_status"]) for row in carriers) == pytest.approx(1)
    assert any(row["gender_concept_id"] == "unknown" and
               row["birth_year_band"] == "unknown" for row in summary)


@pytest.mark.parametrize("bad_rows, message", [
    (["1,S1,SYN_VAR_0021,0,8507,1970", "1,S2,SYN_VAR_0021,1,8507,1970"],
     "Duplicate person_id"),
    (["1,S1,SYN_VAR_0021,0,8507,1970", "2,S1,SYN_VAR_0021,1,8507,1970"],
     "Duplicate sample_id"),
    (["1,S1,SYN_VAR_0021,0,8507,1970", "2,S2,SYN_VAR_9999,1,8507,1970"],
     "expected 'SYN_VAR_0021'"),
    (["1,S1,SYN_VAR_0021,2.1,8507,1970"], "dosage"),
])
def test_rejects_invalid_or_duplicate_rows_without_outputs(tmp_path, bad_rows, message):
    source = tmp_path / "bad.csv"
    source.write_text(",".join(analysis.INPUT_COLUMNS) + "\n" + "\n".join(bad_rows) + "\n")
    output = tmp_path / "out"
    run = _run(source, output)
    assert run.returncode == 2
    assert message in run.stderr
    assert not (output / "carrier_summary.csv").exists()
    assert not (output / "run_manifest.json").exists()


def test_rejects_cohort_smaller_than_matched_input_and_existing_outputs(tmp_path):
    output = tmp_path / "out"
    too_small = _run(SAMPLE, output, "--cohort-size", "5")
    assert too_small.returncode == 2
    assert "cannot exceed cohort_size" in too_small.stderr
    assert not output.exists()

    output.mkdir()
    (output / "carrier_summary.csv").write_text("keep")
    existing = _run(SAMPLE, output)
    assert existing.returncode == 2
    assert (output / "carrier_summary.csv").read_text() == "keep"


def test_missing_cohort_size_does_not_claim_unmatched_count(tmp_path):
    manifest = analysis.analyze(SAMPLE, tmp_path / "out")
    assert manifest["cohort"]["matched_people"] == 6
    assert manifest["cohort"]["unmatched_cohort_members"] is None
    assert manifest["source"]["tables"] == []


def test_dictionary_requires_unique_key_and_selected_variant(tmp_path):
    source = tmp_path / "dictionary.csv"
    header = ",".join(analysis.DICTIONARY_COLUMNS)
    row = "SYN_VAR_0021,SYN_GENE_011,splice," + analysis.SYNTHETIC_NOTICE
    source.write_text(header + "\n" + row + "\n" + row + "\n")
    with pytest.raises(ValueError, match="Duplicate variant_id"):
        analysis.analyze(SAMPLE, tmp_path / "duplicate", variant_dictionary_path=source)

    source.write_text(header + "\n" +
                      "SYN_VAR_0022,SYN_GENE_011,splice," + analysis.SYNTHETIC_NOTICE + "\n")
    with pytest.raises(ValueError, match="does not contain 'SYN_VAR_0021'"):
        analysis.analyze(SAMPLE, tmp_path / "missing", variant_dictionary_path=source)
