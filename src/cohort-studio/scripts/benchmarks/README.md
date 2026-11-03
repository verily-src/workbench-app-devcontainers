# Cohort transform benchmark

Run in an isolated Python environment containing DuckDB and Polars. This creates
2 million synthetic rows in a Parquet file under the temporary directory.

```sh
python cohort_polars.py generate
python compare_polars.py
```

Set `STUDIO_BENCHMARK_PARQUET` to choose the local file. The comparison checks
nulls, identifiers, groups and means, then reports elapsed time and peak RSS.
Results depend on hardware, cache and data compression; this is not a general
engine comparison.
