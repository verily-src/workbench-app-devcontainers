# Deploying stat-expl as a Workbench Custom App

## Prerequisites

1. Push this code to a GitHub repository
2. Have access to Workbench workspace

## Step 1: Push to GitHub

```bash
cd /home/jupyter/temp-devcontainers
git add src/stat-expl/
git commit -m "Add stat-expl deployment files"
git push origin stat-expl-v1
```

## Step 2: Create Custom App in Workbench UI

1. Navigate to your Workbench workspace
2. Click **Apps** → **Create Custom App**
3. Fill in the details:
   - **Name**: `Dataset Statistical Explorer`
   - **Repository URL**: `https://github.com/YOUR-ORG/workbench-app-devcontainers.git`
   - **Branch**: `stat-expl-v1`
   - **Folder path**: `src/stat-expl`
   - **Machine type**: `n1-standard-2` (recommended)
   - **Disk size**: 50 GB

4. Click **Create**

## Step 3: Wait for Build

First build takes ~5-10 minutes:
- Node.js stage builds React app
- Python stage creates runtime container
- Workbench deploys as custom app

## Step 4: Access the App

Once running, get your app URL:

```bash
wb app list --format=json | jq -r '.[] | select(.displayName == "Dataset Statistical Explorer") | .id'
```

Then access at:
```
https://workbench.verily.com/app/<APP_UUID>/proxy/8080/dashboard/
```

## Available Routes

- `/dashboard/` → Redirects to Passport page
- `/dashboard/passport` → Passport page
- `/dashboard/population` → Population page
- `/dashboard/variables` → Variables page
- `/dashboard/quality` → Quality page
- `/dashboard/hypotheses` → Hypotheses page
- `/dashboard/test` → Test page (verify deployment)
- `/dashboard/health` → Health check endpoint

## Troubleshooting

### App won't start
- Check Workbench app logs: `wb app logs <app-name>`
- Verify branch and folder path are correct
- Ensure `.devcontainer.json` is in the folder root

### White page / no content
- Check browser console for errors
- Verify URL format: `workbench.verily.com/app/UUID/proxy/8080/dashboard/`
- Try the `/dashboard/health` endpoint to verify server is running

### Build fails
- Check that all required files are present:
  - `.devcontainer.json`
  - `docker-compose.yaml`
  - `Dockerfile`
  - `server.py`
  - `package.json`
  - `public/docs/schema.json`

## Architecture

```
Workbench Proxy
      ↓
Flask (port 8080)
      ↓
Serves /dashboard/* routes
      ├── /dashboard/health → Health check
      ├── /dashboard/docs/schema.json → Static schema file
      └── /dashboard/* → React SPA (client-side routing)
```

## Local Testing (if Docker available)

```bash
cd src/stat-expl

# Create network
docker network create app-network

# Build and run
docker compose build
docker compose up

# Access at http://localhost:8080/dashboard/
```

## File Structure

```
src/stat-expl/
├── .devcontainer.json         ← Workbench config (MUST be at root!)
├── docker-compose.yaml         ← Container orchestration
├── Dockerfile                  ← Multi-stage: Node build + Python runtime
├── devcontainer-template.json  ← App metadata
├── server.py                   ← Flask server for static files
├── package.json                ← Node dependencies
├── vite.config.ts              ← Vite build config (base: '/dashboard/')
├── public/docs/schema.json     ← Dataset schema (292KB)
└── src/                        ← React app source
```

## Support

- Workbench docs: https://support.workbench.verily.com
- Custom apps guide: https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps/
- Example apps: https://github.com/verily-src/workbench-app-devcontainers
