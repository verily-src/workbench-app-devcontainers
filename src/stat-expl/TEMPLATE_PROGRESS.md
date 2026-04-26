# Dataset Explorer Template - Generalization Progress

## Overview
Refactoring stat-expl into a reusable, workspace-agnostic template with enterprise governance and Workbench integration.

## Completed (stat-expl-tmpl branch)

### 1. Workbench Resource Discovery ✅
**File:** `backend/app/config.py`

- `WorkbenchResource` model for discovered resources
- `DatasetDiscovery` class scans `WORKBENCH_*` environment variables
- Resource type inference (gcs-bucket, bq-dataset, git-repo)
- Automounted path detection in `$HOME/workspace/`
- Methods to get BigQuery datasets, controlled buckets, export buckets
- `AppConfig` with compliance and validation settings

### 2. Dynamic Dataset Integration ✅
**File:** `backend/app/main.py` (updated)

- Imports from config.py
- Replaces hardcoded `DATA_PROJECT` with discovered datasets
- Uses `config.discovery.get_bigquery_datasets()` to find data sources
- Initializes governance and export components

### 3. Governance & Compliance Module ✅
**File:** `backend/app/governance.py`

**Classes:**
- `ComplianceCheckResult` - Result of a compliance check
- `CohortEvidence` - Evidence trail for cohort exports
- `GovernanceReport` - Comprehensive report bundled with exports
- `ComplianceValidator` - Runs compliance checks
- `EvidenceCollector` - Collects and persists evidence trails

**Compliance Checks:**
- `check_data_completeness` - Validates ≥80% coverage across required domains
- `check_sample_size_minimum` - Validates cohort size ≥30 participants
- `check_demographic_representation` - Validates sex diversity and age range ≥10 years

**Features:**
- Audit trail generation with SHA256 query hashing
- Compliance report persistence to `~/.claude/evidence/`
- Attestation generation for exports

### 4. Export Module with Risk Tiering ✅
**File:** `backend/app/export.py`

**Classes:**
- `ExportRequest` - Request to export a cohort
- `ExportResult` - Result of export operation
- `CohortExporter` - Exports cohorts to GCS with governance

**Features:**
- Risk tier-based bucket routing (standard, sensitive, highly_sensitive)
- Validation requirement enforcement
- Compliance check integration
- CSV export to GCS buckets
- Governance report bundling with exports
- Evidence trail preservation

**Workflow:**
1. Validate export request
2. Run compliance checks
3. Build cohort evidence trail
4. Query patient data
5. Generate CSV
6. Upload to appropriate GCS bucket
7. Generate and upload governance report
8. Return success with GCS paths

### 5. New API Endpoints ✅
**File:** `backend/app/main.py` (endpoints added)

Governance Endpoints:
- `GET /dashboard/api/governance/config` - Get governance configuration
- `POST /dashboard/api/governance/validate-cohort` - Run compliance checks
- `GET /dashboard/api/governance/reports` - List governance reports
- `GET /dashboard/api/governance/report/{report_id}` - Get specific report

Export Endpoints:
- `POST /dashboard/api/export/cohort` - Export with governance trail
- `GET /dashboard/api/export/list` - List all exports

Resource Discovery:
- `GET /dashboard/api/resources` - List discovered Workbench resources

### 6. Validation Gate UI ✅
**File:** `frontend/src/pages/Hypotheses.tsx`

**Features:**
- Automatic compliance check execution when cohort is built
- Visual compliance check results with severity indicators
- Validator name input field
- Approval workflow before export
- Export with governance report integration
- Export result display with GCS paths

**Components:**
- `ComplianceCheckCard` - Displays individual check results
- Validation state management
- Approval gate before export button

## Remaining Work

### 7. Frontend Dataset Selection 🔲
**Not yet implemented**

Needs:
- Dropdown to select from discovered BigQuery datasets
- Update API calls to use selected dataset
- Store selection in context/state

### 8. Update CLAUDE.md and Documentation 🔲
**Not yet implemented**

Needs:
- Update CLAUDE.md with template usage instructions
- Document environment variable requirements
- Add deployment guide for new workspaces
- Document governance configuration options

### 9. Testing & Validation 🔲
**Not yet implemented**

Needs:
- Test with empty workspace (no WORKBENCH_* variables)
- Test with multiple datasets
- Test compliance checks with edge cases
- Test export to different risk tiers
- Verify governance report generation

### 10. Configuration Presets 🔲
**Not yet implemented**

Needs:
- Create configuration presets for different use cases
- Example: `configs/strict_validation.py`
- Example: `configs/permissive_export.py`

## Key Design Decisions

1. **Resource Discovery:** Uses environment variables (`WORKBENCH_*`) rather than MCP tools for better portability
2. **Evidence Storage:** Local filesystem (`~/.claude/evidence/`) with GCS upload for governance reports
3. **Compliance Framework:** Extensible check system with severity levels (error, warning, info)
4. **Risk Tiering:** Three-tier system matching typical data governance policies
5. **Validation Gate:** Required approval step before export, enforced at API level

## How to Use Template in New Workspace

### Prerequisites
1. Workspace with WORKBENCH_* environment variables set
2. At least one BigQuery dataset resource
3. At least one controlled GCS bucket for exports

### Setup Steps
1. Deploy app to workspace
2. App automatically discovers resources on startup
3. Configure governance settings in config.py if needed
4. Use Hypotheses page to build and export cohorts
5. Governance reports automatically bundled with exports

### Governance Configuration
Edit `backend/app/config.py`:

```python
class AppConfig(BaseModel):
    enable_exports: bool = True  # Enable/disable exports
    require_validation: bool = True  # Require validator approval
    run_compliance_checks: bool = True  # Run checks before export
    compliance_checks: List[str] = [
        "data_completeness",
        "sample_size_minimum",
        "demographic_representation"
    ]
```

## Files Modified/Created

**Created:**
- `backend/app/config.py`
- `backend/app/governance.py`
- `backend/app/export.py`
- `TEMPLATE_PROGRESS.md` (this file)

**Modified:**
- `backend/app/main.py` - Added imports, governance/export integration, new endpoints
- `frontend/src/pages/Hypotheses.tsx` - Added validation gate UI

## Next Steps

1. Test the implementation with actual Workbench resources
2. Add frontend dataset selector
3. Complete documentation
4. Create configuration presets
5. Add error handling for missing resources
6. Test edge cases (empty workspace, no buckets, etc.)
