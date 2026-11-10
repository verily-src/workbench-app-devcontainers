# The event bridge behind the app's front door (bridge.py; the app's README, "Web UI"): relays the
# OpenCode web UI's event stream over a websocket, which Workbench's proxy carries, and puts
# the script that uses it into the UI's page. Runs in the app container's network namespace.
FROM python:3.12-alpine

RUN pip install --no-cache-dir websockets==17.4

COPY event-bridge/bridge.py event-bridge/event-shim.js /opt/event-bridge/

USER nobody
CMD ["python3", "-u", "/opt/event-bridge/bridge.py"]
