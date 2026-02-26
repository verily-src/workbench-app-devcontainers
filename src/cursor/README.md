# Cursor IDE

Web-based Cursor IDE with AI-powered coding assistant for Verily Workbench.

## Configuration

- **Build**: Custom Verily-controlled Dockerfile
- **Base**: LinuxServer.io KasmVNC (Debian Bookworm)
- **Cursor Version**: 1.7.52 (downloaded from official cursor.com)
- **Port**: 8080
- **User**: root
- **Home Directory**: /config

## Access

Once deployed in Workbench, access Cursor IDE at the app URL (port 8080).

**Login:**
- Username: `cursor`
- Password: `changeme`

After logging in to the container, sign in with your Cursor account to activate AI features.

## Local Testing

```bash
# Build the image
cd src/cursor
docker build --build-arg CURSOR_VERSION=1.7.52 -t cursor-verily .

# Create network and run
docker network create app-network
docker run -d --name cursor-test --network app-network \
  -p 8080:8080 -e CUSTOM_USER=cursor -e PASSWORD=changeme \
  cursor-verily
```

Access at: http://localhost:8080

## Customization

Edit `docker-compose.yaml` to change authentication credentials:

```yaml
environment:
  CUSTOM_USER: "your-username"
  PASSWORD: "your-password"
```

## Security Notes

✅ **This setup uses a Verily-controlled Dockerfile that:**

- Downloads Cursor from official source (downloads.cursor.com)
- Uses verified LinuxServer.io KasmVNC base image
- Follows the same pattern as VSCode-Docker template
- Provides full build transparency and audit trail

## Production Readiness

**Current Status: Production-Ready Build**

Before deploying to Workbench:
1. Security scan the built image (`trivy image ...`)
2. Verify Cursor enterprise licensing terms
3. Optional: Push to Verily's GCR for faster deployment
4. See `BUILD_GUIDE.md` for detailed instructions

## Files

- `Dockerfile.verily` - Production Dockerfile matching VSCode pattern
- `docker-compose.yaml` - Workbench deployment configuration
- `BUILD_GUIDE.md` - Detailed build and deployment guide
- `DOCKERFILE_COMPARISON.md` - Comparison with VSCode template
