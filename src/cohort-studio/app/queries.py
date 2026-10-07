"""SQL data layer.

Every datasource is a table in Aurora: native tables, views, and
aurora_analytics foreign tables that read Parquet/Iceberg directly from S3.
They all appear in information_schema, so one code path covers all three.
"""

import logging
import re

import pandas as pd
from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

ROW_CAP = 100_000
CATEGORICAL_THRESHOLD = 50

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TABLE_TYPE_LABELS = {
    "BASE TABLE": "table",
    "VIEW": "view",
    "FOREIGN": "s3",
    "FOREIGN TABLE": "s3",
}


def _quote(identifier: str) -> str:
    if not _IDENTIFIER.match(identifier):
        raise ValueError(f"Invalid identifier: {identifier!r}")
    return f'"{identifier}"'


def list_tables(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)).fetchall()
    return [
        {"name": name, "kind": TABLE_TYPE_LABELS.get(ttype, "table")}
        for name, ttype in rows
    ]


def fetch_table(engine: Engine, table: str, cap: int = ROW_CAP) -> pd.DataFrame:
    query = f"SELECT * FROM {_quote(table)} LIMIT {int(cap)}"
    return pd.read_sql_query(query, engine)


def has_analytics_extension(engine: Engine) -> bool:
    with engine.connect() as conn:
        available = conn.execute(text(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'aurora_analytics'"
        )).fetchone()
    return available is not None


def ensure_analytics_extension(engine: Engine):
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS aurora_analytics"))
        conn.commit()


def create_s3_foreign_table(engine: Engine, name: str, location: str,
                            file_format: str, region: str):
    """Register S3 data as a foreign table. Schema is inferred by Aurora."""
    if not location.startswith("s3://"):
        raise ValueError("Location must start with s3://")
    if file_format not in ("parquet", "iceberg"):
        raise ValueError(f"Unsupported format: {file_format}")
    if not _IDENTIFIER.match(region.replace("-", "_")):
        raise ValueError(f"Invalid region: {region!r}")
    safe_location = location.replace("'", "''")
    ensure_analytics_extension(engine)
    with engine.connect() as conn:
        conn.execute(text(f"""
            CREATE FOREIGN TABLE {_quote(name)} ()
            SERVER aurora_analytics_server
            OPTIONS (
                location '{safe_location}',
                format '{file_format}',
                region '{region}'
            )
        """))
        conn.commit()
    logger.info("Created foreign table %s -> %s", name, location)


GTEX_SAMPLES_URL = (
    "https://storage.googleapis.com/adult-gtex/annotations/v8/metadata-files/"
    "GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt")


def load_gtex_samples(engine: Engine, name: str = "gtex_samples") -> int:
    """Load the open-access GTEx V8 sample attributes into an Aurora table."""
    df = pd.read_csv(GTEX_SAMPLES_URL, sep="\t", low_memory=False)
    df.columns = [c.lower() for c in df.columns]
    # Default executemany, not method="multi": 63 columns x a large chunk
    # exceeds PostgreSQL's 65535 bind-parameter limit per statement.
    # if_exists="replace" lets a failed load be retried cleanly.
    df.to_sql(name, engine, if_exists="replace", index=False, chunksize=1000)
    logger.info("Loaded %d GTEx samples into %s", len(df), name)
    return len(df)


def create_demo_table(engine: Engine, name: str = "demo_samples",
                      rows: int = 500):
    """Seed a small sample table so a fresh database has data to explore."""
    import random
    rng = random.Random(7)
    tissues = ["liver", "lung", "heart", "skin", "kidney"]
    df = pd.DataFrame({
        "sample_id": [f"SAMP-{i:05d}" for i in range(rows)],
        "tissue": [tissues[rng.randrange(len(tissues))] for _ in range(rows)],
        "rin_score": [round(5 + rng.random() * 5, 1) for _ in range(rows)],
        "age": [20 + rng.randrange(60) for _ in range(rows)],
        "case_control": [rng.choice(["case", "control"]) for _ in range(rows)],
    })
    df.to_sql(name, engine, if_exists="replace", index=False)
    logger.info("Created demo table %s with %d rows", name, rows)
    return name


def infer_filter_kinds(df: pd.DataFrame) -> dict[str, str]:
    """Decide which filter control each column gets: categorical, range, or none."""
    kinds = {}
    for col in df.columns:
        series = df[col].dropna()
        unique = series.nunique()
        if unique == 0:
            kinds[col] = "none"
        elif pd.api.types.is_bool_dtype(series):
            kinds[col] = "categorical"
        elif pd.api.types.is_float_dtype(series):
            # Floats are measurements: checkboxes over 50 distinct readings
            # help nobody, so they go to a range slider much sooner.
            kinds[col] = "categorical" if unique <= 10 else "range"
        elif pd.api.types.is_numeric_dtype(series):
            kinds[col] = "categorical" if unique <= CATEGORICAL_THRESHOLD else "range"
        elif unique <= CATEGORICAL_THRESHOLD:
            kinds[col] = "categorical"
        else:
            kinds[col] = "none"
    return kinds
