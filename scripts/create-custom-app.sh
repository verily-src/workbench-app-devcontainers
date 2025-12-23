#!/bin/bash
# Script to create a custom Workbench app devcontainer structure
# Usage: ./create-custom-app.sh <app-name> <docker-image> <port> [username] [home-dir]

set -o errexit -o nounset -o pipefail -o xtrace

# Parse arguments
if [ $# -lt 3 ]; then
  echo "Usage: $0 <app-name> <docker-image> <port> [username] [home-dir]"
  echo ""
  echo "Arguments:"
  echo "  app-name      - Name of your custom app (e.g., my-jupyter-app)"
  echo "  docker-image  - Docker image to use (e.g., jupyter/base-notebook)"
  echo "  port          - Port your app exposes (e.g., 8888)"
  echo "  username      - (Optional) User inside container (default: root)"
  echo "  home-dir      - (Optional) Home directory (default: /root or /home/<username>)"
  echo ""
  echo "Example:"
  echo "  $0 my-jupyter jupyter/base-notebook 8888 jovyan /home/jovyan"
  exit 1
fi

readonly APP_NAME="$1"
readonly DOCKER_IMAGE="$2"
readonly PORT="$3"
readonly USERNAME="${4:-root}"

# Calculate home directory if not provided
if [ $# -ge 5 ]; then
  readonly HOME_DIR="$5"
else
  if [ "$USERNAME" = "root" ]; then
    readonly HOME_DIR="/root"
  else
    readonly HOME_DIR="/home/$USERNAME"
  fi
fi
readonly -f

readonly APP_DIR="src/${APP_NAME}"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Create app directory
echo "Creating app directory: ${APP_DIR}"
mkdir -p "${REPO_ROOT}/${APP_DIR}"

# Generate .devcontainer.json
echo "Generating .devcontainer.json"
cat > "${REPO_ROOT}/${APP_DIR}/.devcontainer.json" <<EOF
{
  "name": "${APP_NAME}",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "postCreateCommand": [
    "./startupscript/post-startup.sh",
    "\${templateOption:username}",
    "\${templateOption:homeDir}",
    "\${templateOption:cloud}"
  ],
  "postStartCommand": [
    "./startupscript/remount-on-restart.sh",
    "\${templateOption:username}",
    "\${templateOption:homeDir}",
    "\${templateOption:cloud}"
  ],
  "features": {
    "ghcr.io/devcontainers/features/java:1": {
      "version": "17"
    },
    "ghcr.io/devcontainers/features/aws-cli:1": {},
    "ghcr.io/dhoeric/features/google-cloud-cli:1": {}
  },
  "remoteUser": "root"
}
EOF

# Generate docker-compose.yaml
echo "Generating docker-compose.yaml"
cat > "${REPO_ROOT}/${APP_DIR}/docker-compose.yaml" <<EOF
services:
  app:
    # The container name must be "application-server"
    container_name: "application-server"
    # This can be either a pre-existing image or built from a Dockerfile
    image: "\${templateOption:image}"
    # build:
    #   context: .
    restart: always
    volumes:
      - .:/workspace:cached
      - work:\${templateOption:homeDir}/work
    # The port specified here will be forwarded and accessible from the
    # Workbench UI.
    ports:
      - \${templateOption:port}:\${templateOption:port}
    # The service must be connected to the "app-network" Docker network
    networks:
      - app-network
    # SYS_ADMIN and fuse are required to mount workspace resources into the
    # container.
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined

volumes:
  work:

networks:
  # The Docker network must be named "app-network". This is an external network
  # that is created outside of this docker-compose file.
  app-network:
    external: true
EOF

# Generate devcontainer-template.json
echo "Generating devcontainer-template.json"
cat > "${REPO_ROOT}/${APP_DIR}/devcontainer-template.json" <<EOF
{
  "id": "${APP_NAME}",
  "version": "1.0.0",
  "name": "${APP_NAME}",
  "description": "Custom Workbench app: ${APP_NAME}",
  "options": {
    "image": {
      "type": "string",
      "default": "${DOCKER_IMAGE}",
      "description": "Docker image to use for the application"
    },
    "port": {
      "type": "string",
      "default": "${PORT}",
      "description": "Port the application exposes"
    },
    "username": {
      "type": "string",
      "default": "${USERNAME}",
      "description": "Default user inside the container"
    },
    "homeDir": {
      "type": "string",
      "default": "${HOME_DIR}",
      "description": "Home directory for the user"
    },
    "cloud": {
      "type": "string",
      "enum": ["gcp", "aws"],
      "default": "gcp",
      "description": "Cloud provider (gcp or aws)"
    }
  }
}
EOF

# Generate README
echo "Generating README.md"
cat > "${REPO_ROOT}/${APP_DIR}/README.md" <<EOF
# ${APP_NAME}

Custom Workbench application based on ${DOCKER_IMAGE}.

## Configuration

- **Image**: ${DOCKER_IMAGE}
- **Port**: ${PORT}
- **User**: ${USERNAME}
- **Home Directory**: ${HOME_DIR}

## Customization

Edit the following files to customize your app:

- \`.devcontainer.json\` - Devcontainer configuration
- \`docker-compose.yaml\` - Docker Compose configuration
- \`devcontainer-template.json\` - Template options and metadata

## Testing

To test this app template:

\`\`\`bash
cd test
./test.sh ${APP_NAME}
\`\`\`

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (${APP_NAME})
EOF

echo ""
echo "✓ Custom app created successfully at: ${APP_DIR}"
echo ""
echo "Next steps:"
echo "  1. Review and customize the generated files in ${APP_DIR}"
echo "  2. Test your app: cd test && ./test.sh ${APP_NAME}"
echo "  3. Commit and push to your forked repository"
echo "  4. Create a custom app in Workbench UI using your repository"
