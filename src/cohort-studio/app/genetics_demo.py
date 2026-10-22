"""Load a deterministic, fabricated genetics demo into a new Aurora schema."""

import argparse
import json
import random
import re
import sys
from pydantic import BaseModel, ConfigDict, Field
from pathlib import Path

TARGET_RESOURCE = "cohort-dash-db-20261005"
SOURCE_SCHEMA = "cms_synpuf_100k"
TARGET_SCHEMA = "genetics_demo"
SEED = 20261022
SAMPLE_COUNT = 5_000
VARIANT_COUNT = 200
SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class DemoOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    sample_count: int = Field(ge=1, le=SAMPLE_COUNT)
    variant_count: int = Field(ge=20, le=VARIANT_COUNT)
    seed: int = Field(ge=0, le=2_147_483_647)


def _q(name):
    if not SCHEMA_RE.fullmatch(name):
        raise ValueError(f"Invalid schema name: {name!r}.")
    return '"' + name + '"'


def load(conn, source_schema=SOURCE_SCHEMA, target_schema=TARGET_SCHEMA,
         sample_count=SAMPLE_COUNT, variant_count=VARIANT_COUNT, seed=SEED):
    options = DemoOptions(sample_count=sample_count, variant_count=variant_count, seed=seed)
    sample_count, variant_count, seed = (options.sample_count, options.variant_count,
                                         options.seed)
    source = _q(source_schema)
    target = _q(target_schema)
    if target_schema == source_schema:
        raise ValueError("Source and target schemas must differ.")
    if sample_count < 1 or variant_count < 20:
        raise ValueError("Use at least one sample and 20 variants.")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                        (target_schema,))
            if cur.fetchone():
                raise ValueError(f"Target schema {target_schema} already exists; refusing to replace it.")
            cur.execute("SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = %s AND table_name = 'person'",
                        (source_schema,))
            if not cur.fetchone()[0]:
                raise ValueError(f"Source {source_schema}.person does not exist.")
            cur.execute(f"SELECT person_id FROM {source}.person ORDER BY person_id LIMIT %s",
                        (sample_count,))
            people = [row[0] for row in cur.fetchall()]
            if len(people) != sample_count or len(set(people)) != sample_count:
                raise ValueError(f"Source must contain {sample_count:,} distinct people.")
            cur.execute(f"CREATE SCHEMA {target}")
            cur.execute(f"""CREATE TABLE {target}.samples (
                sample_id text PRIMARY KEY,
                person_id bigint NOT NULL UNIQUE,
                demo_group text NOT NULL
            )""")
            cur.execute(f"""CREATE TABLE {target}.variants (
                variant_id text PRIMARY KEY,
                chromosome smallint NOT NULL,
                position integer NOT NULL,
                reference_allele char(1) NOT NULL,
                alternate_allele char(1) NOT NULL,
                synthetic_gene text NOT NULL,
                synthetic_consequence text NOT NULL,
                demo_group text NOT NULL
            )""")
            cur.execute(f"""CREATE TABLE {target}.genotypes (
                sample_id text NOT NULL REFERENCES {target}.samples(sample_id),
                variant_id text NOT NULL REFERENCES {target}.variants(variant_id),
                dosage smallint NOT NULL CHECK (dosage BETWEEN 0 AND 2),
                read_depth smallint NOT NULL,
                quality_score numeric(5,2) NOT NULL,
                PRIMARY KEY (sample_id, variant_id)
            )""")
            cur.executemany(f"INSERT INTO {target}.samples VALUES (%s, %s, %s)",
                            [(f"SYN_SAMPLE_{i + 1:05d}", person_id,
                              "planted_demo_group" if i % 10 == 0 else "background")
                             for i, person_id in enumerate(people)])
            bases = "ACGT"
            variants = []
            for i in range(variant_count):
                ref = bases[(i * 3 + 1) % 4]
                alt = bases[(i * 3 + 2) % 4]
                variants.append((f"SYN_VAR_{i + 1:04d}", i % 22 + 1,
                                 100_000 + i * 101, ref, alt,
                                 f"SYN_GENE_{i // 2 + 1:03d}",
                                 ("missense", "synonymous", "splice")[i % 3],
                                 "planted_demo_pattern" if i < 20 else "background"))
            cur.executemany(f"INSERT INTO {target}.variants VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", variants)
            rng = random.Random(seed)
            rows = []
            for sample_index, _person_id in enumerate(people):
                sample_id = f"SYN_SAMPLE_{sample_index + 1:05d}"
                planted = sample_index % 10 == 0
                for variant_index in range(variant_count):
                    dosage = (2 if planted else 0) if variant_index < 20 else rng.choices(
                        (0, 1, 2), weights=(72, 25, 3))[0]
                    rows.append((sample_id, f"SYN_VAR_{variant_index + 1:04d}",
                                 dosage, rng.randint(12, 60), round(rng.uniform(20, 99), 2)))
                    if len(rows) == 10_000:
                        with cur.copy(f"COPY {target}.genotypes "
                                      "(sample_id, variant_id, dosage, read_depth, quality_score) "
                                      "FROM STDIN") as copy:
                            for row in rows:
                                copy.write_row(row)
                        rows.clear()
            if rows:
                with cur.copy(f"COPY {target}.genotypes "
                              "(sample_id, variant_id, dosage, read_depth, quality_score) "
                              "FROM STDIN") as copy:
                    for row in rows:
                        copy.write_row(row)
            cur.execute(f"CREATE INDEX ON {target}.genotypes (variant_id, dosage)")
            cur.execute(f"""CREATE VIEW {target}.demo_pattern_summary AS
                SELECT v.variant_id, v.demo_group, g.dosage,
                       count(*) AS sample_count
                FROM {target}.genotypes g
                JOIN {target}.variants v USING (variant_id)
                WHERE v.demo_group = 'planted_demo_pattern'
                GROUP BY v.variant_id, v.demo_group, g.dosage""")
            cur.execute(f"ANALYZE {target}.samples")
            cur.execute(f"ANALYZE {target}.variants")
            cur.execute(f"ANALYZE {target}.genotypes")
            counts = {table: cur.execute(f"SELECT count(*) FROM {target}.{table}").fetchone()[0]
                      for table in ("samples", "variants", "genotypes")}
            expected = {"samples": sample_count, "variants": variant_count,
                        "genotypes": sample_count * variant_count}
            if counts != expected:
                raise ValueError(f"Loaded counts {counts} do not match expected counts {expected}.")
            cur.execute(f"SELECT count(*) FROM {target}.samples s "
                        f"LEFT JOIN {source}.person p USING (person_id) "
                        "WHERE p.person_id IS NULL")
            if cur.fetchone()[0]:
                raise ValueError("One or more sample person IDs do not match source people.")
            cur.execute(f"""CREATE TABLE {target}.import_metadata (
                imported_at timestamptz NOT NULL DEFAULT now(),
                source_schema text NOT NULL,
                seed integer NOT NULL,
                sample_count integer NOT NULL,
                variant_count integer NOT NULL,
                counts jsonb NOT NULL,
                synthetic_notice text NOT NULL
            )""")
            cur.execute(f"INSERT INTO {target}.import_metadata "
                        "(source_schema, seed, sample_count, variant_count, counts, synthetic_notice) "
                        "VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                        (source_schema, seed, sample_count, variant_count,
                         json.dumps(counts),
                         "Fabricated genotypes and variant identifiers; no clinical claims."))
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise


def export_csv(conn, output_dir, schema=TARGET_SCHEMA):
    target = _q(schema)
    outdir = Path(output_dir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=False)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT source_schema, seed, sample_count, variant_count, counts, "
                        f"synthetic_notice FROM {target}.import_metadata ORDER BY imported_at DESC LIMIT 1")
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"{schema} has no import metadata.")
            source_schema, seed, sample_count, variant_count, _stored_counts, notice = row
            counts = {}
            for table in ("samples", "variants", "genotypes"):
                cur.execute(f"SELECT count(*) FROM {target}.{table}")
                counts[table] = cur.fetchone()[0]
                filename = outdir / f"{table}.csv"
                with filename.open("xb") as output:
                    with cur.copy(f"COPY {target}.{table} TO STDOUT WITH (FORMAT CSV, HEADER TRUE)") as copy:
                        while data := copy.read():
                            output.write(data)
        manifest = {"schema": schema, "source_schema": source_schema, "seed": seed,
                    "sample_count": sample_count, "variant_count": variant_count,
                    "counts": counts, "synthetic_notice": notice,
                    "files": ["samples.csv", "variants.csv", "genotypes.csv"]}
        manifest_path = outdir / "manifest.json"
        with manifest_path.open("x", encoding="utf-8") as output:
            json.dump(manifest, output, indent=2)
            output.write("\n")
        conn.commit()
        return manifest
    except Exception:
        conn.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-id", default=TARGET_RESOURCE, choices=[TARGET_RESOURCE])
    parser.add_argument("--source-schema", default=SOURCE_SCHEMA)
    parser.add_argument("--target-schema", default=TARGET_SCHEMA)
    parser.add_argument("--samples", type=int, default=SAMPLE_COUNT)
    parser.add_argument("--variants", type=int, default=VARIANT_COUNT)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--export-csv", help="write loaded tables and manifest into a new directory")
    parser.add_argument("--export-only", action="store_true",
                        help="export an existing schema without attempting another load")
    args = parser.parse_args(argv)
    if args.export_only and not args.export_csv:
        parser.error("--export-only requires --export-csv")
    try:
        import db
        conn = db.get_engine_for_resource(args.resource_id).raw_connection()
        try:
            if args.export_only:
                manifest = export_csv(conn, args.export_csv, args.target_schema)
                counts = manifest["counts"]
            else:
                options = DemoOptions(sample_count=args.samples, variant_count=args.variants,
                                      seed=args.seed)
                counts = load(conn, args.source_schema, args.target_schema,
                              options.sample_count, options.variant_count, options.seed)
                if args.export_csv:
                    manifest = export_csv(conn, args.export_csv, args.target_schema)
        finally:
            conn.close()
    except Exception as exc:
        parser.error(str(exc))
    if not args.export_only:
        print(f"Committed {counts} to schema {args.target_schema} (synthetic; seed {args.seed}).")
    if args.export_csv:
        print(f"Exported {manifest['counts']} to {args.export_csv}.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
