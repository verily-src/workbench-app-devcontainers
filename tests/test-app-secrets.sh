#!/bin/bash
set -o errexit
export TEST_USER="root"

CONTAINER_NAME="application-server"

# Verify pipe exists with correct permissions
echo "Checking secret pipe..."
docker exec --user root "$CONTAINER_NAME" test -p /tmp/secrets
result="$(docker exec --user root "$CONTAINER_NAME" stat -c '%a' /tmp/secrets)"
if [ "$result" != "600" ]; then
  echo "ERROR: Expected pipe permissions 600, got ${result}"
  exit 1
fi

# Inject mock secrets to unblock the secret receiver
echo "Injecting mock secrets..."
echo '[
    {"type":"valueVar","value":"secret-value","target":"SECRET_VALUE"},
    {"type":"pathVar","value":"secret-value","target":"SECRET_PATH"}
    {"type":"pipeVar","value":"secret-value","target":"SECRET_PIPE"}
]' | timeout 30 docker exec --user root -i "$CONTAINER_NAME" sh -c 'cat > /tmp/secrets'

bats tests/test-app-secrets.bats
