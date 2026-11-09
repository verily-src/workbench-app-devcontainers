# Cohort Browser architecture

```mermaid
flowchart LR
    User["User"] --> UI["Browser<br/>Explore + Data Builder"]
    UI -->|"HTTP API"| App["Workbench app<br/>FastAPI"]

    App --> OMOP["OMOP cohort filters<br/>validated SQL"]
    OMOP --> DB[("Aurora / PostgreSQL")]
    App -->|"Live queries and same-database joins"| DB

    App --> Duck["DuckDB<br/>file data + mixed-source joins"]
    Duck --> S3[("S3 files")]
    DB -->|"Stage rows for cross-source joins"| Duck
    Duck --> Local[("Local staged data")]

    App --> Results["Counts, charts and rows"]
    Results --> UI
```

Live Aurora queries run in the database. DuckDB handles supported file data and mixed-source joins inside the app. OMOP cohorts are built from validated criteria and queried against Aurora.

[Detailed architecture and code references](architecture.md#detailed-service-and-omop-diagrams)
