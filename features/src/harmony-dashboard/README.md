# Harmony Data Harmonization Dashboard

Installs and launches the Streamlit-based **Harmony Dashboard** (`port 8502` by default) for inspecting agentic clinical data harmonization runs (`mapping/` and `audit/` artifacts).

## Options

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `port` | string | `"8502"` | Port on which Streamlit listens. |
| `gcsBucket` | string | `"anschutz-pancreatic-cancer-ds-bucket-wb-golden-parsnip-6065"` | Default GCS bucket containing run artifacts. |
| `gcsRootPrefix` | string | `"experimental/run_artifacts"` | Default GCS prefix containing `mapping/` and `audit/`. |
| `datasetName` | string | `"WP1 Data"` | Dataset display name in the dashboard header. |
| `datasetSubtitle` | string | `"Pancreatic Cancer Dataset \| Agentic FHIR Harmonization"` | Subtitle shown below the dataset name. |
| `localPath` | string | `""` | Optional local or gcsfuse-mounted root path overriding GCS. |
