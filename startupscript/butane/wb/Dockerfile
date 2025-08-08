# Workbench CLI Container
#
# This lightweight container provides the Workbench CLI (wb) tool configured
# for a specific Workbench server environment. The container is designed to:
# - Install the appropriate wb CLI version for the target Workbench server
# - Provide a consistent execution environment across different hosts
# - Maintain persistent configuration and data through volume mounting
#
# Build Requirements:
# The WORKBENCH_SERVER build argument must be provided when building:
#   docker build --build-arg WORKBENCH_SERVER=<server-url> -t wb .
#
# Runtime Requirements:
# The container must be run with host networking to access cloud instance
# metadata services, and requires a context directory mounted read-write at
# /workbench_context for persistence across runs:
#   docker run --network host -v /local/context:/workbench_context:rw wb [command]
#
# The wb CLI will store its configuration, authentication tokens, and
# workspace context in the mounted directory to maintain state between
# container executions.

FROM eclipse-temurin:17-jre-jammy

# Install jq for JSON processing (used by wb CLI)
RUN apt-get update && apt-get install -y jq

# Build-time argument for Workbench server URL
ARG WORKBENCH_SERVER

# Validate that WORKBENCH_SERVER build argument was provided
RUN if [ -z "$WORKBENCH_SERVER" ]; then \
    echo "Error: The build-time argument 'WORKBENCH_SERVER' must be set using --build-arg." >&2; \
    exit 1; \
    fi

# Configure environment variables for wb CLI
ENV WORKBENCH_CLI_SERVER=${WORKBENCH_SERVER} \
    WORKBENCH_CONTEXT_PARENT_DIR=/workbench_context \
    SUPPRESS_GCLOUD_CREDS_WARNING=true

# Download and install the wb CLI tool
RUN curl -L https://storage.googleapis.com/bkt-workbench-artifacts/download-install.sh | /bin/bash && \
    mv wb /usr/local/bin

# Set wb as the container entrypoint
ENTRYPOINT [ "wb" ]
