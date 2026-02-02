# pgweb

Custom Workbench application for querying PostgreSQL databases using pgweb - a lightweight, web-based database browser.

## Configuration

- **Image**: sosedoff/pgweb
- **Port**: 8081
- **User**: root
- **Home Directory**: /root
- **Sessions Mode**: Enabled (allows interactive login via web UI)

## Access

Once deployed in Workbench, access the pgweb UI at the app URL (port 8081).

You'll see an interactive login form where you can enter your database connection details:
- **Host**: Your Aurora cluster endpoint (e.g., `mycluster.cluster-xxx.us-east-1.rds.amazonaws.com`)
- **Port**: `5432` (default PostgreSQL port)
- **Username**: Your database username
- **Password**: Your database password (works with IAM temporary passwords)
- **Database**: Your database name
- **SSL Mode**: `require` (recommended for Aurora)

## Aurora PostgreSQL with IAM Authentication

This app works well with Aurora PostgreSQL IAM authentication. The sessions mode allows you to enter temporary IAM passwords directly in the web form, avoiding URL encoding issues.

For local testing:
1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:8081`

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration (change the `command` to customize pgweb options)
- `devcontainer-template.json` - Template options and metadata

## Testing

To test this app template:

```bash
cd test
./test.sh pgweb
```

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (pgweb)
