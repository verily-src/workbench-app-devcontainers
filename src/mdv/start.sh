#!/bin/bash
# Starts MDV's own gunicorn on a loopback-only port, then runs nginx in front
# of it on the port Workbench actually proxies (5055). nginx adds
# Document-Isolation-Policy on every response so SharedArrayBuffer/WASM
# threads work from the first request — no SDK, no client-side
# service-worker double-load. See BENCH-9901.
set -euo pipefail

MDV_API_ROOT="${MDV_API_ROOT:-/}"
export MDV_API_ROOT

envsubst '${MDV_API_ROOT}' \
    < /opt/mdv-nginx/nginx.conf.template \
    > /tmp/mdv-nginx.conf

# Same command as the published mdvadmin/mdv:stable image's own CMD, just
# bound to loopback instead of 0.0.0.0:5055 so only nginx is reachable.
poetry run gunicorn -k gevent -t 0 -w 1 -b 127.0.0.1:5056 \
    --reload --capture-output --log-level info \
    mdvtools.dbutils.safe_mdv_app:app &
gunicorn_pid=$!

nginx -c /tmp/mdv-nginx.conf -g 'daemon off;' &
nginx_pid=$!

cleanup() {
    kill -TERM "$gunicorn_pid" "$nginx_pid" 2>/dev/null || true
}
trap cleanup TERM INT

wait -n "$gunicorn_pid" "$nginx_pid"
cleanup
wait
