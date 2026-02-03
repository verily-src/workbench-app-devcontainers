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

## Automatic Database Discovery

The app automatically discovers all Aurora databases in your Workbench workspace and creates pre-configured connection bookmarks with fresh IAM authentication tokens.

### How It Works

1. **Auto-Discovery**: Every 10 minutes, the app queries `wb resource list` to find all Aurora databases
2. **IAM Token Generation**: For each database, generates fresh IAM authentication tokens for both read-write (RW) and read-only (RO) users
3. **Bookmark Creation**: Creates pgweb bookmarks for each database connection
4. **Always Fresh**: Tokens refresh every 10 minutes (they expire after 15), so connections never expire

### Using Bookmarks

When you open pgweb, you'll see bookmarks for each database in your workspace:
- `aurora-demo-db-20260115 (Write-Read)` - Read-write connection
- `aurora-demo-db-20260115 (Read-Only)` - Read-only connection
- `dc-database (Write-Read)` - Read-write connection (referenced database)
- `dc-database (Read-Only)` - Read-only connection (referenced database)

Click any bookmark to connect instantly - no need to enter credentials!

### Manual Connections

You can also use the interactive login form to enter connection details manually:
- **Host**: Your Aurora cluster endpoint
- **Port**: `5432`
- **Username**: Your database username
- **Password**: Your database password (works with IAM temporary passwords)
- **Database**: Your database name
- **SSL Mode**: `require`

## Aurora PostgreSQL with IAM Authentication

This app is optimized for Aurora PostgreSQL with IAM authentication. The automatic bookmark system handles token refresh transparently, and manual connections support entering temporary IAM passwords directly without URL encoding issues.

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
