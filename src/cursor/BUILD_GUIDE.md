# Building Verily-Verified Cursor Image

## Overview

This Dockerfile creates a production-ready Cursor IDE container by:
1. Using verified LinuxServer.io KasmVNC base
2. Downloading Cursor from official source (downloads.cursor.com)
3. Adding Verily-specific security controls
4. Providing audit trail and reproducibility

## Legal/Licensing Status

### ✅ ALLOWED

**Why this approach is legally sound:**

1. **Base Image (KasmVNC):**
   - Source: LinuxServer.io (reputable open-source org)
   - License: GPL v3 (allows modification and redistribution)
   - Well-maintained, security-focused

2. **Cursor AppImage:**
   - Downloaded from official Cursor servers
   - Same binary users would download for desktop
   - No modification or redistribution of Cursor itself
   - Similar to how Docker images download Chrome, VS Code, etc.

3. **Our Dockerfile:**
   - Original work by Verily
   - Automates setup, doesn't redistribute Cursor
   - Follows same pattern as obsidian-remote (established practice)

**Precedent:** Many organizations containerize desktop apps this way:
- sytone/obsidian-remote (Obsidian)
- linuxserver/code-server (VS Code)
- selenium images (Chrome/Firefox)

### What We're NOT Doing

❌ NOT redistributing Cursor binaries
❌ NOT modifying Cursor code
❌ NOT bypassing Cursor licensing
❌ NOT violating Cursor ToS (users still need accounts/licenses)

### What We ARE Doing

✅ Automating download from official source
✅ Providing container runtime environment
✅ Adding security and compliance controls
✅ Following industry-standard patterns

## Differences from Community Version

| Aspect | Community (arfodublo) | Verily Version |
|--------|----------------------|----------------|
| **Base** | Same (KasmVNC) | Same (but will pin to digest) |
| **Source** | Official Cursor | Same |
| **Versions** | Latest tag | Explicit versions pinned |
| **Security** | Basic | Hardened + audited |
| **Registry** | Docker Hub | GCR (Verily) |
| **Signing** | None | Will add cosign |
| **Scanning** | None | CI/CD security scans |
| **Support** | Community | Verily Platform Team |

## Building the Image

### Prerequisites

```bash
# Install Docker
docker --version  # Should be 20.x or higher

# GCP authentication (for pushing to GCR)
gcloud auth configure-docker gcr.io
```

### Build Command

```bash
cd /Users/michaelx/workbench-app-devcontainers/src/cursor

# Build for x64 (GCE)
docker build \
  --file Dockerfile.verily \
  --build-arg CURSOR_VERSION=1.7.52 \
  --tag gcr.io/verily-project/cursor-ide:1.7.52 \
  --tag gcr.io/verily-project/cursor-ide:latest \
  .

# Build for ARM64 (local Mac testing)  
docker build \
  --file Dockerfile.verily \
  --build-arg CURSOR_VERSION=1.7.52 \
  --platform linux/arm64 \
  --tag gcr.io/verily-project/cursor-ide:1.7.52-arm64 \
  .
```

### Test Locally

```bash
# Run the image
docker run -d \
  --name cursor-test \
  -p 8080:8080 \
  -e CUSTOM_USER=cursor \
  -e PASSWORD=test123 \
  gcr.io/verily-project/cursor-ide:1.7.52

# Check logs
docker logs cursor-test

# Access: http://localhost:8080
# Login: cursor / test123

# Stop
docker stop cursor-test && docker rm cursor-test
```

### Security Scan

```bash
# Install trivy
brew install aquasecurity/trivy/trivy

# Scan the image
trivy image gcr.io/verily-project/cursor-ide:1.7.52

# Generate report
trivy image --format json --output report.json gcr.io/verily-project/cursor-ide:1.7.52
```

### Push to GCR

```bash
# Push to Verily's registry
docker push gcr.io/verily-project/cursor-ide:1.7.52
docker push gcr.io/verily-project/cursor-ide:latest
```

## Update Workbench Configuration

Edit `docker-compose.yaml`:

```yaml
services:
  app:
    # Replace community image:
    # image: "arfodublo/cursor-in-browser:1.7.52-x64"
    
    # With Verily's verified image:
    image: "gcr.io/verily-project/cursor-ide:1.7.52"
```

## Version Updates

When new Cursor versions are released:

1. **Test new version:**
   ```bash
   # Update version in Dockerfile.verily
   # ARG CURSOR_VERSION=1.7.53
   
   # Build and test locally
   docker build -t cursor-test:1.7.53 .
   docker run -d -p 8080:8080 cursor-test:1.7.53
   # Test thoroughly
   ```

2. **Security scan:**
   ```bash
   trivy image cursor-test:1.7.53
   ```

3. **If approved, tag and push:**
   ```bash
   docker tag cursor-test:1.7.53 gcr.io/verily-project/cursor-ide:1.7.53
   docker push gcr.io/verily-project/cursor-ide:1.7.53
   ```

4. **Update Workbench config** to use new version

## Production Hardening Checklist

Before production deployment:

- [ ] Pin base image to specific digest (not just tag)
- [ ] Add SHA256 checksum verification of Cursor AppImage
- [ ] Run full security scan (trivy, grype)
- [ ] Sign image with cosign
- [ ] Set up automated scanning in CI/CD
- [ ] Document approval process for new versions
- [ ] Create incident response plan
- [ ] Set up monitoring and alerts
- [ ] Implement image signing verification in Workbench
- [ ] Add secrets management (not env vars)
- [ ] Configure audit logging
- [ ] Test backup/restore procedures

## CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Build and Scan Cursor Image

on:
  push:
    paths:
      - 'src/cursor/Dockerfile.verily'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build image
        run: |
          docker build -f src/cursor/Dockerfile.verily \
            -t cursor-test:${{ github.sha }} .
      
      - name: Scan for vulnerabilities
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: cursor-test:${{ github.sha }}
          severity: 'CRITICAL,HIGH'
          exit-code: '1'
      
      - name: Push to GCR (if scan passes)
        run: |
          gcloud auth configure-docker gcr.io
          docker tag cursor-test:${{ github.sha }} gcr.io/verily-project/cursor-ide:${{ github.sha }}
          docker push gcr.io/verily-project/cursor-ide:${{ github.sha }}
```

## Cost Comparison

### Current (Community Image)
- **Cost**: Free (uses Docker Hub)
- **Trust**: Community-maintained
- **Control**: None
- **Support**: None
- **Updates**: When community updates

### Verily-Built Image
- **Cost**: ~$5/month storage in GCR
- **Trust**: Audited by Verily
- **Control**: Full
- **Support**: Verily Platform Team
- **Updates**: When Verily approves

## Support

**Issues with build:** Verily Platform Team
**Cursor functionality:** Cursor support
**Security concerns:** Verily InfoSec
**Licensing questions:** Verily Legal

## References

- Original community Dockerfile: https://github.com/Arfo-du-blo/cursor-in-browser
- KasmVNC base: https://github.com/linuxserver/docker-baseimage-kasmvnc
- Obsidian pattern: https://github.com/sytone/obsidian-remote
- Cursor official: https://cursor.com
