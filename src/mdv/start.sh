#!/bin/bash
# Starts MDV's own gunicorn on a loopback-only port, then runs nginx in front
# of it on the port Workbench actually proxies (5055). nginx adds
# Document-Isolation-Policy on every response so SharedArrayBuffer/WASM
# threads work from the first request — no SDK, no client-side
# service-worker double-load. See BENCH-9901.
set -euo pipefail

MDV_API_ROOT="${MDV_API_ROOT:-/}"
export MDV_API_ROOT

# Cross-origin isolation mode for MDV's document (BENCH-9901):
#   credentialless (default): public cross-origin files and images load without CORP headers,
#     sent without cookies. Data read by JavaScript (fetch/XHR) still needs CORS in either mode.
#   require-corp: cross-origin subresources load only if they send CORP or CORS headers.
case "${MDV_ISOLATION_MODE:-credentialless}" in
  credentialless | require-corp) MDV_COEP="${MDV_ISOLATION_MODE:-credentialless}" ;;
  *) echo "Invalid MDV_ISOLATION_MODE '${MDV_ISOLATION_MODE}'" >&2; exit 1 ;;
esac
export MDV_COEP

# shellcheck disable=SC2016 # envsubst takes literal variable names
envsubst '${MDV_API_ROOT} ${MDV_COEP}' \
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

# Workspace data browser backend on 127.0.0.1:5057 (nginx routes /_workspace/ to it).
# Restarted if it exits; MDV keeps working without it.
(
    while true; do
        python3 /opt/mdv-workbench/workspace_ui.py || true
        sleep 2
    done
) &
workspace_ui_pid=$!

cleanup() {
    kill -TERM "$gunicorn_pid" "$nginx_pid" "$workspace_ui_pid" 2>/dev/null || true
}
trap cleanup TERM INT

wait -n "$gunicorn_pid" "$nginx_pid"
cleanup
wait
