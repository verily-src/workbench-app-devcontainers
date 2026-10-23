import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

import db

RESOURCE_ID = os.environ.get("LOCAL_RESOURCE_ID", "local-postgres")
DATABASE_URL = os.environ["LOCAL_DB_URL"]
database_url = make_url(DATABASE_URL)
if database_url.drivername == "postgresql":
    database_url = database_url.set(drivername="postgresql+psycopg")
engine = create_engine(database_url, pool_pre_ping=True)
database_name = database_url.database or "cohort_local"

db.warm_resource_cache = lambda: None
db.resources_ready = lambda: True
db.retry_if_empty = lambda: None
db.list_aurora_resources = lambda wait=False: [{
    "id": RESOURCE_ID, "database": database_name, "region": "local",
}]
db.list_s3_folders = lambda wait=False: []
db.list_bq_datasets = lambda wait=False: []


def get_engine(resource_id):
    if resource_id != RESOURCE_ID:
        raise KeyError(f"Unknown local resource: {resource_id}")
    return engine


db.get_engine_for_resource = get_engine

import uvicorn
import main

if __name__ == "__main__":
    uvicorn.run(main.app, host="0.0.0.0", port=8080)
