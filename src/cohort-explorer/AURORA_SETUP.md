# Loading GTEx Public Data into Aurora

Step-by-step runbook for creating a data collection workspace with an Aurora database and loading the public GTEx V8 sample annotations. Follows the same pattern as the [aurora-demo README](https://github.com/verily-src/mc-terra-aws-demo-notebooks/blob/master/aurora-demo/README.md).

## What was loaded

**Source file:** [GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt](https://storage.googleapis.com/adult-gtex/annotations/v8/metadata-files/GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt)
from the [GTEx Portal datasets page](https://gtexportal.org/home/datasets) (public, no dbGaP authorization required).

**Data collection:** `gtex-v8-cohort-data` on `verily-aws` pod
**Aurora resource:** `gtex-public-cohort-db` (database name: `gtex_public_cohort_db`)
**Table:** `gtex_sample_attributes` — 22,951 rows, 63 columns, 31 tissue types
**Region:** us-east-1

This is de-identified sample-level metadata. It does NOT contain subject identifiers, FASTQ paths, or anything requiring dbGaP authorization.

## Prerequisites

- Workbench CLI (`wb`) installed and authenticated
- `psql` available (`sudo apt-get install -y postgresql-client`)
- Must run from an app (JupyterLab, etc.) in the same AWS region/VPC as the Aurora cluster — you cannot connect from your local machine

## Step 1: Create a data collection workspace

```bash
wb workspace create \
    --id=gtex-v8-cohort-data \
    --name="GTEx V8 Cohort Data (Public)" \
    --description="Public GTEx V8 sample annotations for the cohort explorer POC. Source: https://storage.googleapis.com/adult-gtex/annotations/v8/metadata-files/GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt" \
    --pod=verily-aws \
    --properties=terra-type=data-collection
```

Note: `--properties=terra-type=data-collection` must be set at creation time (cannot be changed after).

```bash
wb folder create --name=version1
```

## Step 2: Create an Aurora PostgreSQL database

```bash
wb resource create aurora-database \
    --id gtex-public-cohort-db \
    --database-name gtex_public_cohort_db
```

Note: Aurora database names are **globally unique** across the entire AWS account, not per-workspace. If the name is taken, choose a different one.

Wait ~2-3 minutes for provisioning, then verify:

```bash
wb resource describe --id gtex-public-cohort-db
```

You should see `rwEndpoint`, `roEndpoint`, `rwUser`, `roUser`, `port: 5432`.

## Step 3: Download the public GTEx sample attributes file

```bash
curl -fSL "https://storage.googleapis.com/adult-gtex/annotations/v8/metadata-files/GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt" -o /tmp/gtex_samples.txt
echo "Downloaded $(wc -l < /tmp/gtex_samples.txt) lines"
```

Expected: 22,952 lines (22,951 data + 1 header).

## Step 4: Get a write-read connection string

```bash
CONNECTION_STRING="$(wb resource resolve \
    --id=gtex-public-cohort-db \
    --access-mode=WRITE_READ \
    --include-password)"
```

The token expires after 15 minutes. If subsequent steps take longer, re-run this command.

## Step 5: Create the table

```bash
psql "${CONNECTION_STRING}" <<'SQL'
CREATE TABLE IF NOT EXISTS gtex_sample_attributes (
    sampid TEXT PRIMARY KEY,
    smatsscr TEXT, smcenter TEXT, smpthnts TEXT, smrin TEXT,
    smts TEXT, smtsd TEXT, smubrid TEXT, smtsisch TEXT, smtspax TEXT,
    smnabtch TEXT, smnabtcht TEXT, smnabtchd TEXT,
    smgebtch TEXT, smgebtchd TEXT, smgebtcht TEXT,
    smafrze TEXT, smgtc TEXT,
    sme2mprt TEXT, smchmprs TEXT, smntrart TEXT, smnumgps TEXT,
    smmaprt TEXT, smexncrt TEXT, sm550nrm TEXT, smgnsdtc TEXT,
    smunmprt TEXT, sm350nrm TEXT, smrdlgth TEXT, smmncpb TEXT,
    sme1mmrt TEXT, smsflgth TEXT, smestlbs TEXT, smmppd TEXT,
    smnterrt TEXT, smrrnanm TEXT, smrdttl TEXT, smvqcfl TEXT,
    smmncv TEXT, smtrscpt TEXT, smmppdpr TEXT, smcglgth TEXT,
    smgappct TEXT, smunpdrd TEXT, smntrnrt TEXT, smmpunrt TEXT,
    smexpeff TEXT, smmppdun TEXT, sme2mmrt TEXT, sme2anti TEXT,
    smaltalg TEXT, sme2snse TEXT, smmflgth TEXT, sme1anti TEXT,
    smspltrd TEXT, smbsmmrt TEXT, sme1snse TEXT, sme1pcts TEXT,
    smrrnart TEXT, sme1mprt TEXT, smnum5cd TEXT, smdpmprt TEXT,
    sme2pcts TEXT
);
SQL
```

All 63 columns loaded as TEXT, matching the source file schema exactly. Column names match the GTEx data dictionary (e.g., SMTS = tissue type, SMTSD = tissue type detail, SMRIN = RIN number).

## Step 6: Load the data

```bash
psql "${CONNECTION_STRING}" -c "\copy gtex_sample_attributes FROM '/tmp/gtex_samples.txt' WITH (FORMAT csv, DELIMITER E'\t', HEADER true, QUOTE E'\b')"
```

## Step 7: Verify the load

```bash
psql "${CONNECTION_STRING}" -c "
SELECT
    COUNT(*) AS total_samples,
    COUNT(DISTINCT smts) AS tissue_types,
    COUNT(DISTINCT smtsd) AS tissue_details
FROM gtex_sample_attributes;
"
```

Expected:

```
 total_samples | tissue_types | tissue_details
---------------+--------------+----------------
         22951 |           31 |             54
```

## Step 8: Spot check

```bash
psql "${CONNECTION_STRING}" -c "
SELECT smts, COUNT(*) AS samples
FROM gtex_sample_attributes
GROUP BY smts
ORDER BY samples DESC
LIMIT 5;
"
```

## Notes

- The `\copy` command runs client-side (reads the file from your machine, not the Aurora server). The file must be accessible from wherever you run `psql`.
- Aurora is only reachable from within the workspace's VPC. Run these commands from a JupyterLab or other cloud app in the same pod/region, not from your local machine.
- If the IAM token expires mid-load, re-run Step 4 to get a fresh connection string.
- All columns are stored as TEXT to match the source file exactly. Type casting (e.g., SMRIN to NUMERIC) can be done at query time or in the cohort explorer app.
