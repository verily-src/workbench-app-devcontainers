import json
import logging

logger = logging.getLogger(__name__)

try:
    from mcp.server.mcpserver import MCPServer
    AVAILABLE = True
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
        AVAILABLE = True
    except ImportError:
        AVAILABLE = False
        mcp = None

if AVAILABLE:
    mcp = MCPServer(
        name="cohort-studio",
        instructions=(
            "Cohort exploration over a Verily Workbench workspace. "
            "Flow: list_datasources -> list_tables -> open_dataset -> "
            "query_dataset with filters. For OMOP CDM databases: "
            "omop_search_concepts -> omop_count_cohort -> omop_open_cohort."),
    )

    def http_app():

        return mcp.streamable_http_app(stateless_http=True,
                                       streamable_http_path="/")

    @mcp.tool()
    def list_datasources() -> str:
        """List available datasources (Aurora databases, S3 folders,
        BigQuery datasets, views-only DuckDB catalogs) in the workspace."""
        import catalog
        import db
        folders = db.list_s3_folders()
        catalogs, pending = catalog.discover([r["id"] for r in folders])
        sources = ([{"kind": "aurora", "id": r["id"]}
                    for r in db.list_aurora_resources()]
                   + [{"kind": "s3", "id": r["id"]} for r in folders]
                   + [{"kind": "bq", "id": r["id"]}
                      for r in db.list_bq_datasets()]
                   + [{"kind": "catalog", "id": c["id"]} for c in catalogs])
        return json.dumps({"ready": db.resources_ready(), "sources": sources,
                           "catalogs_pending": pending})

    @mcp.tool()
    def list_tables(kind: str, resource_id: str) -> str:
        """List tables (Aurora/BigQuery), data files (S3), or views
        (catalog) in a datasource. kind is 'aurora', 's3', 'bq', or
        'catalog'."""
        import bq
        import catalog
        import db
        import duck
        if kind == "catalog":
            return json.dumps([{"name": o["name"], "sql": o["sql"]}
                               for o in catalog.list_catalog(resource_id)])
        if kind == "aurora":
            items = [t["name"] for t in db.list_aurora_tables(resource_id)]
        elif kind == "s3":
            items = duck.list_s3_files(resource_id)
        elif kind == "bq":
            for d in db.list_bq_datasets():
                if d["id"] == resource_id:
                    items = bq.list_tables(d["project"], d["dataset"])
                    break
            else:
                raise ValueError(f"Unknown BigQuery dataset: {resource_id}")
        else:
            raise ValueError(f"Unknown kind: {kind}")
        return json.dumps(items)

    @mcp.tool()
    def open_dataset(kind: str, resource_id: str, table: str) -> str:
        """Load a table into memory for querying. Returns a dataset_id
        and a column profile (names, filter kinds, categorical values,
        numeric ranges)."""
        import bq
        import catalog
        import datasets
        import db
        import duck
        import joins
        import queries
        if kind == "aurora":
            df = db.fetch_aurora_table(resource_id, table, queries.ROW_CAP)
        elif kind == "s3":
            df = duck.fetch_s3_file(resource_id, table, queries.ROW_CAP)
        elif kind == "catalog":
            df = catalog.fetch_catalog_view(resource_id, table,
                                            queries.ROW_CAP)
        elif kind == "bq":
            for d in db.list_bq_datasets():
                if d["id"] == resource_id:
                    df = bq.fetch_table(d["project"], d["dataset"], table,
                                        queries.ROW_CAP)
                    break
            else:
                raise ValueError(f"Unknown BigQuery dataset: {resource_id}")
        else:
            raise ValueError(f"Unknown kind: {kind}")
        return json.dumps(datasets.open_dataset(
            df, f"{resource_id} / {table}",
            origin=joins.aurora_origin(resource_id, table)
            if kind == "aurora" else None))

    @mcp.tool()
    def query_dataset(dataset_id: str, filters_json: str = "[]",
                      page: int = 0, page_size: int = 50) -> str:
        """Query an opened dataset with cross-filtering. filters_json is
        a JSON array of {column, kind: 'categorical'|'range',
        values?: [..], min?: n, max?: n}. Returns total/filtered counts
        and a page of rows."""
        import datasets
        filters = json.loads(filters_json)
        result = datasets.query(dataset_id, filters, [], page=page,
                                page_size=page_size)
        return json.dumps({k: result[k] for k in ("total", "filtered", "rows")})

    def _omop_cdm(resource_id: str):
        import db
        import omop
        known = {r["id"] for r in db.list_aurora_resources()}
        if resource_id not in known:
            raise ValueError("Unknown Aurora resource or workspace resources are not ready.")
        info = omop.detect_resource(resource_id)
        if info is None:
            raise ValueError(f"No OMOP CDM found in {resource_id}.")
        return db.get_engine_for_resource(resource_id), info

    @mcp.tool()
    def omop_search_concepts(resource_id: str, q: str, domain: str = "",
                             vocabulary: str = "",
                             standard_only: bool = True) -> str:
        """Search OMOP concepts in an Aurora CDM by name words, concept_id
        or concept_code. domain is condition, drug, procedure,
        measurement, observation, visit, device (or an OMOP domain_id).
        Returns concept_id, concept_name, domain_id, vocabulary_id,
        concept_class_id, concept_code, standard_concept, persons."""
        import omop
        engine, info = _omop_cdm(resource_id)
        return json.dumps(omop.search_concepts(
            engine, info, q, domain or None, vocabulary or None,
            standard_only=standard_only), default=str)

    @mcp.tool()
    def omop_count_cohort(resource_id: str, spec_json: str) -> str:
        """Count persons in an OMOP cohort. spec_json is
        {criteria: [{domain, concept_ids: [int], descendants?: bool,
        exclude?: bool, min_count?: int, value_min?, value_max?,
        start?: 'YYYY-MM-DD', end?, index_relation?: 'before'|'after'}],
        demographics?: {gender_concept_ids?, age_min?, age_max?,
        year_of_birth_min?, year_of_birth_max?},
        require_observation?: bool}. Criteria are AND-ed. Returns
        persons, total_persons and cumulative attrition."""
        import omop
        engine, info = _omop_cdm(resource_id)
        return json.dumps(omop.count(engine, info, json.loads(spec_json)))

    @mcp.tool()
    def omop_open_cohort(resource_id: str, spec_json: str,
                         name: str = "") -> str:
        """Open an OMOP cohort (same spec as omop_count_cohort) as a
        person-level dataset for query_dataset. Returns a dataset_id and
        a column profile."""
        import datasets
        import omop
        engine, info = _omop_cdm(resource_id)
        df = omop.open_cohort(engine, info, json.loads(spec_json))
        return json.dumps(datasets.open_dataset(
            df, f"{resource_id} / {name.strip() or 'OMOP cohort'}"), default=str)
