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
2. **Access-Based Credentials**: For each database, attempts to get credentials based on your workspace permissions:
   - **Read-Only**: Always attempted first - if successful, creates a read-only bookmark
   - **Write-Read**: Only attempted if you have write access - creates a write-read bookmark if successful
3. **IAM Token Generation**: Generates fresh IAM authentication tokens for each access level you have
4. **Bookmark Creation**: Creates pgweb bookmarks only for the access levels you're granted
5. **Always Fresh**: Tokens refresh every 10 minutes (they expire after 15), so connections never expire

**Note**: You'll only see bookmarks for databases you have access to. If you only have read-only access to a database, you'll only see the read-only bookmark. If a database is removed from the workspace or your access is revoked, its bookmarks will disappear on the next refresh.

### Using Bookmarks

When you open pgweb, you'll see bookmarks for databases you have access to. Examples:

- `aurora-demo-db-20260115 (Read-Only)` - Read-only connection
- `aurora-demo-db-20260115 (Write-Read)` - Read-write connection (only if you have write access)
- `dc-database (Read-Only)` - Read-only connection to referenced database
- `dc-database (Write-Read)` - Read-write connection (only if you have write access)

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

## Local Testing

For local testing of the bookmark refresh script:

```bash
# Test with custom paths (useful for local development)
WB_EXE="$(which wb)" PGWEB_BASE=/tmp/pgweb ./src/pgweb/refresh-bookmarks.sh
```

Environment variables:

- `WB_EXE` - Path to wb executable (default: `/usr/bin/wb`)
- `PGWEB_BASE` - Base directory for pgweb config (default: `/root/.pgweb`)

For full devcontainer testing:

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
