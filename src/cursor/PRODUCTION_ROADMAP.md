# Cursor Production Roadmap

## Current State (Spike)
- Using: `arfodublo/cursor-in-browser:1.7.52-x64` (pinned version)
- Status: TESTING ONLY - not approved for production
- Risk: Unvetted third-party image

## Path to Production

### Phase 1: Security Assessment (1-2 weeks)
- [ ] Scan pinned image for vulnerabilities (`trivy`, `docker scout`)
- [ ] Review Dockerfile source (if available from arfodublo)
- [ ] Document findings and risks
- [ ] Get InfoSec preliminary review

### Phase 2: Custom Build (2-3 weeks)
- [ ] Research official Cursor distribution options
- [ ] Create custom Dockerfile from verified sources
- [ ] Build and test custom image
- [ ] Compare functionality with community image

### Phase 3: Verification (1-2 weeks)
- [ ] Security scan custom image
- [ ] Penetration testing
- [ ] Compliance review (HIPAA, SOC2, etc.)
- [ ] Performance testing
- [ ] User acceptance testing

### Phase 4: Production Deployment (1 week)
- [ ] Push to Verily container registry (GCR)
- [ ] Update docker-compose.yaml to use verified image
- [ ] InfoSec sign-off
- [ ] Deploy to production Workbench
- [ ] Monitor and validate

## Current Blockers

### Blocker 1: Cursor Distribution
**Problem:** Cursor may not have official server/headless version

**Options:**
1. Wait for official Cursor server release
2. Reverse-engineer community solution (legal/ethical concerns)
3. Build similar IDE with verified components (VS Code + Copilot)
4. Request enterprise version from Cursor support

**Recommendation:** Contact Cursor support about enterprise server deployment

### Blocker 2: Image Provenance
**Problem:** Cannot verify community image contents

**Options:**
1. Audit community Dockerfile source
2. Build from scratch with verified components
3. Request official Docker image from Cursor

**Recommendation:** Build custom image from verified sources

## Alternative Solutions

### Option A: VS Code Server + GitHub Copilot
- **Pro:** Fully verified, Microsoft-backed
- **Pro:** Already approved/used at many enterprises
- **Con:** Not "Cursor" specifically
- **Con:** Separate Copilot subscription needed

### Option B: Desktop Cursor + Remote Development
- **Pro:** Official Cursor desktop app (verified)
- **Pro:** Users install on their machines
- **Con:** Not containerized
- **Con:** Less isolation/security

### Option C: Wait for Official Cursor Server
- **Pro:** Official support and verification
- **Pro:** Proper licensing and compliance
- **Con:** Timeline unknown
- **Con:** May never be released

## Recommendation

**For Spike (Now):**
✅ Use pinned community image for technical validation

**For Production (Next):**
1. Contact Cursor about official enterprise image
2. If available: Use official Cursor image
3. If not available: Build custom VS Code + Copilot solution
4. Document security trade-offs for decision makers

## Security Requirements Checklist

Before production deployment:
- [ ] Image source verified (official or audited)
- [ ] All dependencies pinned to specific versions
- [ ] Security scan passed (no critical vulnerabilities)
- [ ] Image signed and stored in Verily registry
- [ ] InfoSec approval documented
- [ ] Compliance review completed (HIPAA, etc.)
- [ ] Incident response plan documented
- [ ] Regular update/patching process defined

## Timeline Estimate

| Phase | Duration | Depends On |
|-------|----------|------------|
| Spike (current) | 1 week | Technical validation |
| Security assessment | 1-2 weeks | InfoSec availability |
| Custom build | 2-3 weeks | Cursor support response |
| Verification | 1-2 weeks | Testing resources |
| Production | 1 week | All approvals |
| **Total** | **6-9 weeks** | All blockers resolved |

## Next Steps

1. **Complete spike** with pinned image
2. **Email Cursor support** about enterprise options
3. **Contact Verily InfoSec** about requirements
4. **Document findings** in spike report
5. **Decision meeting** on path forward
