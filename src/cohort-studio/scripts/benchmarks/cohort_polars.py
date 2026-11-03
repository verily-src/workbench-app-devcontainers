import json, os, resource, sys, tempfile, time
from pathlib import Path

DATA = Path(os.environ.get('STUDIO_BENCHMARK_PARQUET', str(Path(tempfile.gettempdir()) / 'cohort-polars-benchmark.parquet')))
if sys.argv[1] == 'generate':
    import duckdb
    conn = duckdb.connect()
    conn.execute("SET threads=4")
    conn.execute(f"""COPY (
      SELECT (9007199254740993::BIGINT + i) AS person_id,
        CASE WHEN i % 13 = 0 THEN NULL ELSE 1930 + i % 70 END::INTEGER AS year_of_birth,
        CASE WHEN i % 11 = 0 THEN NULL WHEN i % 2 = 0 THEN 'female' ELSE 'male' END AS gender,
        CASE WHEN i % 7 = 0 THEN NULL ELSE (i % 3)::INTEGER END AS dosage,
        (i % 10)::INTEGER AS condition_count,
        CASE WHEN i % 17 = 0 THEN NULL ELSE (i % 1000)::DOUBLE / 10 END AS measurement,
        DATE '2000-01-01' + (i % 3650)::INTEGER AS index_date
      FROM range(2000000) AS r(i)) TO '{DATA}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    print(json.dumps({'file': str(DATA), 'bytes': DATA.stat().st_size, 'rows': 2000000}))
    raise SystemExit

engine = sys.argv[1]
os.environ['POLARS_MAX_THREADS'] = '4'
t0 = time.perf_counter()
if engine == 'duckdb':
    import duckdb
    conn=duckdb.connect()
    conn.execute('SET threads=4')
    version=duckdb.__version__
    query=f"""SELECT coalesce(gender, 'unknown') AS gender,
      CASE WHEN dosage = 0 THEN 'noncarrier' WHEN dosage > 0 THEN 'carrier' ELSE 'unknown' END AS carrier_status,
      count(*) AS rows, count(distinct person_id) AS people, count(measurement) AS observed,
      avg(measurement) AS mean_measurement, min(person_id) AS min_id, max(person_id) AS max_id
      FROM read_parquet('{DATA}')
      WHERE year_of_birth BETWEEN 1940 AND 1970 AND condition_count >= 2
      GROUP BY ALL ORDER BY gender, carrier_status"""
    out=conn.execute(query)
    cols=[x[0] for x in out.description]; groups=[dict(zip(cols,r)) for r in out.fetchall()]
    source_schema=[(r[0],r[1]) for r in conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{DATA}')").fetchall()]
    sample=conn.execute(f"SELECT person_id,year_of_birth,gender,dosage,measurement,CAST(index_date AS VARCHAR) FROM read_parquet('{DATA}') WHERE person_id >= 9007199254740993 AND person_id < 9007199254741015 ORDER BY person_id").fetchall()
else:
    import polars as pl
    version=pl.__version__
    lf=pl.scan_parquet(DATA)
    source_schema=[(name,str(dtype)) for name,dtype in lf.collect_schema().items()]
    transformed=(lf.filter(pl.col('year_of_birth').is_between(1940,1970) & (pl.col('condition_count') >= 2))
      .with_columns(pl.col('gender').fill_null('unknown'),
       pl.when(pl.col('dosage') == 0).then(pl.lit('noncarrier')).when(pl.col('dosage') > 0).then(pl.lit('carrier')).otherwise(pl.lit('unknown')).alias('carrier_status'))
      .group_by(['gender','carrier_status'])
      .agg(pl.len().alias('rows'),pl.col('person_id').n_unique().alias('people'),pl.col('measurement').count().alias('observed'),
       pl.col('measurement').mean().alias('mean_measurement'),pl.col('person_id').min().alias('min_id'),pl.col('person_id').max().alias('max_id'))
      .sort(['gender','carrier_status']))
    groups=transformed.collect(engine='streaming').to_dicts()
    sample=(lf.filter((pl.col('person_id') >= 9007199254740993) & (pl.col('person_id') < 9007199254741015))
      .select('person_id','year_of_birth','gender','dosage','measurement',pl.col('index_date').cast(pl.String)).sort('person_id').collect(engine='streaming').rows())
print(json.dumps({'engine':engine,'version':version,'elapsed_s':round(time.perf_counter()-t0,3),'max_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),'groups':groups,'schema':source_schema,'sample':sample}))
