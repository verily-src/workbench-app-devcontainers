import os
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import genetics_demo
import omop_load


def main():
    url = os.environ["LOCAL_DB_URL"]
    for attempt in range(30):
        try:
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT schema_name FROM information_schema.schemata "
                                "WHERE schema_name IN ('cdm', 'genetics_demo')")
                    existing = {row[0] for row in cur.fetchall()}
                if "cdm" not in existing:
                    counts = omop_load.load(
                        conn, ROOT / "tests" / "fixtures" / "omop", "cdm",
                        log=lambda *_: None)
                    print(f"Seeded OMOP cdm: {len(counts)} tables")
                if "genetics_demo" not in existing:
                    genetics_counts = genetics_demo.load(
                        conn, "cdm", "genetics_demo", sample_count=100,
                        variant_count=20, seed=20261023)
                    print(f"Seeded synthetic genetics: {genetics_counts}")
            return
        except psycopg.OperationalError:
            if attempt == 29:
                raise
            time.sleep(2)


if __name__ == "__main__":
    main()
