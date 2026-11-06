#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="pg-program-gen"
DB_USER="pguser"
DB_PASS="pgpass"
DB_NAME="program_generator"
DB_PORT="5432"

echo "=== Program Generator Local Dev ==="

# --- Postgres ---
if docker inspect "$CONTAINER_NAME" &>/dev/null; then
  state=$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")
  if [ "$state" = "true" ]; then
    echo "Postgres already running."
  else
    echo "Starting existing Postgres container..."
    docker start "$CONTAINER_NAME"
  fi
else
  echo "Creating Postgres container..."
  docker run -d --name "$CONTAINER_NAME" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASS" \
    -e POSTGRES_DB="$DB_NAME" \
    -p "$DB_PORT":5432 \
    postgres:18-alpine
fi

# Wait for Postgres to be ready
echo -n "Waiting for Postgres"
for i in $(seq 1 30); do
  if docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" &>/dev/null; then
    echo " ready."
    break
  fi
  echo -n "."
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo " timed out!"
    exit 1
  fi
done

# --- Go app ---
echo "Starting Go server on http://localhost:8080"
echo "(Ctrl+C to stop)"
echo ""

export DB_HOST=localhost
export DB_PORT="$DB_PORT"
export DB_USER="$DB_USER"
export DB_PASSWORD="$DB_PASS"
export DB_NAME="$DB_NAME"
export FHIR_STORE="${FHIR_STORE:-projects/prj-d-1v-ucd/locations/us-west1/datasets/operational-healthcare-dataset/fhirStores/operational-fhir-store}"
export GCS_BUCKET="${GCS_BUCKET:-econsent-pdf-pilot-dev-oneverily-prj-d-1v-ucd}"
export ENV_BASE_URL="${ENV_BASE_URL:-https://dev-stable.one.verily.com}"

cd "$(dirname "$0")/.."
exec go run .
