#!/bin/bash

mkdir -p ~/.claude && cat <<EOF > ~/.claude/settings.json
{
  "env": {
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLOUD_ML_REGION": "us-east5",
    "VERTEX_REGION_CLAUDE_4_7_OPUS": "us",
    "VERTEX_REGION_CLAUDE_4_8_OPUS": "us",
    "ANTHROPIC_VERTEX_PROJECT_ID": "wb-agile-aubergine-8187",
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "DISABLE_TELEMETRY": "1",
    "OTEL_LOG_USER_PROMPTS": "0",
    "OTEL_LOG_TOOL_DETAILS": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://claude-otel-collector-usage-events-64mw6qm9.uc.gateway.dev",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "https://claude-otel-collector-usage-events-64mw6qm9.uc.gateway.dev/v1/traces",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://claude-otel-collector-usage-events-64mw6qm9.uc.gateway.dev/v1/metrics",
    "OTEL_EXPORTER_OTLP_HEADERS": "x-api-key=AIzaSyAY8kCGXpV3XHEDc3J5CoMk7XeCkb6HVuQ",
    "OTEL_RESOURCE_ATTRIBUTES": "environment=workbench,username=\${WORKBENCH_USER_EMAIL%@*}"
  },
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "deny": [
      "Read(.env)",
      "Read(.env.*)"
    ]
  },
  "allowedMcpServers": [
    {"serverUrl": "https://mcp.atlassian.com/v1/mcp"},
    {"serverUrl": "https://mcp.figma.com/mcp"},
    {"serverUrl": "https://mcp.cypress.io/mcp"},
    {"serverUrl": "https://mcp.heymarvin.com"},
    {"serverCommand": ["xcrun", "mcpbridge"]},
    {
      "serverCommand": [
        "npx",
        "-y",
        "@playwright/mcp@latest",
        "--allowed-origins",
        "https://dev.*.verily.com;https://test.*.verily.com;https://dev.*.verilyme.com;https://test.*.verilyme.com;https://localhost:*",
        "--save-session",
        "--extension"
      ]
    }
  ],
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["git"],
    "allowUnsandboxedCommands": false
  }
}
EOF

mkdir -p /config/data/User
echo '{"workbench.colorTheme":"Default Dark Modern"}' > /config/data/User/settings.json
