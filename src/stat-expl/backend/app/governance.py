"""
Governance and compliance module for Dataset Explorer.
Implements evidence collection, audit trails, and compliance validation.
"""
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from pydantic import BaseModel
from google.cloud import bigquery


class ComplianceCheckResult(BaseModel):
    """Result of a single compliance check"""
    check_name: str
    passed: bool
    severity: str  # 'error', 'warning', 'info'
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime


class CohortEvidence(BaseModel):
    """Evidence trail for a cohort export"""
    cohort_id: str
    cohort_type: str
    cohort_size: int
    selection_criteria: Dict[str, Any]
    data_sources: List[str]  # BigQuery table references
    created_at: datetime
    created_by: str
    compliance_checks: List[ComplianceCheckResult]
    query_hash: str  # SHA256 of the SQL query used to build cohort


class GovernanceReport(BaseModel):
    """Comprehensive governance report bundled with exports"""
    report_id: str
    cohort_evidence: CohortEvidence
    dataset_metadata: Dict[str, Any]
    compliance_summary: Dict[str, Any]
    attestations: List[str]
    generated_at: datetime
    export_destination: Optional[str] = None


class ComplianceValidator:
    """Runs compliance checks on cohorts before export"""

    def __init__(self, bq_client: bigquery.Client, data_project: str):
        self.bq_client = bq_client
        self.data_project = data_project

    def check_data_completeness(
        self,
        patient_ids: List[str],
        required_domains: List[str]
    ) -> ComplianceCheckResult:
        """
        Validate that cohort has minimum data completeness across required domains.
        Requirement: At least 80% of patients must have data in each required domain.
        """
        if not patient_ids:
            return ComplianceCheckResult(
                check_name="data_completeness",
                passed=False,
                severity="error",
                message="Empty cohort - no patients to validate",
                timestamp=datetime.utcnow()
            )

        patient_list = ','.join([f"'{p}'" for p in patient_ids[:1000]])  # Limit for performance
        domain_map = {
            "vitals": f"`{self.data_project}.crf.VS`",
            "labs": f"`{self.data_project}.externallab.CLABS`",
            "medications": f"`{self.data_project}.crf.CM`",
            "diagnoses": f"`{self.data_project}.crf.MH`",
            "sensor": f"`{self.data_project}.sensordata.STEP`",
            "pro": f"`{self.data_project}.appsurveys.PHQ9A`"
        }

        completeness = {}
        cohort_size = len(patient_ids)

        for domain in required_domains:
            if domain not in domain_map:
                continue

            query = f"""
            SELECT COUNT(DISTINCT SUBJID) as count
            FROM {domain_map[domain]}
            WHERE SUBJID IN ({patient_list})
            """
            try:
                result = list(self.bq_client.query(query).result())[0]
                coverage_pct = round(100.0 * result.count / cohort_size, 1)
                completeness[domain] = coverage_pct
            except Exception as e:
                completeness[domain] = 0.0

        # Check if all required domains meet 80% threshold
        min_threshold = 80.0
        failing_domains = [d for d, pct in completeness.items() if pct < min_threshold]

        if failing_domains:
            return ComplianceCheckResult(
                check_name="data_completeness",
                passed=False,
                severity="warning",
                message=f"Domains below {min_threshold}% completeness: {', '.join(failing_domains)}",
                details={"completeness": completeness, "threshold": min_threshold},
                timestamp=datetime.utcnow()
            )

        return ComplianceCheckResult(
            check_name="data_completeness",
            passed=True,
            severity="info",
            message=f"All required domains meet {min_threshold}% completeness threshold",
            details={"completeness": completeness},
            timestamp=datetime.utcnow()
        )

    def check_sample_size_minimum(
        self,
        cohort_size: int,
        minimum_required: int = 30
    ) -> ComplianceCheckResult:
        """
        Validate minimum cohort size for statistical power.
        Default: At least 30 participants (basic statistical minimum).
        """
        if cohort_size < minimum_required:
            return ComplianceCheckResult(
                check_name="sample_size_minimum",
                passed=False,
                severity="error",
                message=f"Cohort size ({cohort_size}) below minimum required ({minimum_required})",
                details={"cohort_size": cohort_size, "minimum_required": minimum_required},
                timestamp=datetime.utcnow()
            )

        return ComplianceCheckResult(
            check_name="sample_size_minimum",
            passed=True,
            severity="info",
            message=f"Cohort size ({cohort_size}) meets minimum requirement ({minimum_required})",
            details={"cohort_size": cohort_size, "minimum_required": minimum_required},
            timestamp=datetime.utcnow()
        )

    def check_demographic_representation(
        self,
        patient_ids: List[str]
    ) -> ComplianceCheckResult:
        """
        Validate demographic representation in cohort.
        Requirement: Both sexes represented, age range >= 10 years.
        """
        if not patient_ids:
            return ComplianceCheckResult(
                check_name="demographic_representation",
                passed=False,
                severity="error",
                message="Empty cohort",
                timestamp=datetime.utcnow()
            )

        patient_list = ','.join([f"'{p}'" for p in patient_ids[:1000]])

        query = f"""
        SELECT
            COUNT(DISTINCT SEX) as sex_count,
            MAX(age_at_enrollment) - MIN(age_at_enrollment) as age_range,
            COUNTIF(SEX = 'Male') as male_count,
            COUNTIF(SEX = 'Female') as female_count,
            COUNT(*) as total
        FROM `{self.data_project}.screener.DM`
        WHERE SUBJID IN ({patient_list})
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            issues = []
            if result.sex_count < 2:
                issues.append("Only one sex represented")
            if result.age_range < 10:
                issues.append(f"Age range too narrow ({result.age_range} years)")

            # Check for extreme imbalance (>90% one sex)
            if result.male_count > 0 and result.female_count > 0:
                male_pct = round(100.0 * result.male_count / result.total, 1)
                if male_pct > 90 or male_pct < 10:
                    issues.append(f"Severe sex imbalance ({male_pct}% male)")

            if issues:
                return ComplianceCheckResult(
                    check_name="demographic_representation",
                    passed=False,
                    severity="warning",
                    message="Demographic representation issues: " + "; ".join(issues),
                    details={
                        "sex_count": result.sex_count,
                        "age_range": result.age_range,
                        "male_pct": round(100.0 * result.male_count / result.total, 1) if result.total > 0 else 0
                    },
                    timestamp=datetime.utcnow()
                )

            return ComplianceCheckResult(
                check_name="demographic_representation",
                passed=True,
                severity="info",
                message="Adequate demographic representation",
                details={
                    "sex_count": result.sex_count,
                    "age_range": result.age_range,
                    "male_pct": round(100.0 * result.male_count / result.total, 1) if result.total > 0 else 0
                },
                timestamp=datetime.utcnow()
            )
        except Exception as e:
            return ComplianceCheckResult(
                check_name="demographic_representation",
                passed=False,
                severity="error",
                message=f"Failed to validate demographics: {str(e)}",
                timestamp=datetime.utcnow()
            )

    def run_all_checks(
        self,
        patient_ids: List[str],
        cohort_type: str,
        enabled_checks: List[str]
    ) -> List[ComplianceCheckResult]:
        """Run all enabled compliance checks"""
        results = []

        if "sample_size_minimum" in enabled_checks:
            results.append(self.check_sample_size_minimum(len(patient_ids)))

        if "demographic_representation" in enabled_checks:
            results.append(self.check_demographic_representation(patient_ids))

        if "data_completeness" in enabled_checks:
            # Determine required domains based on cohort type
            required_domains = ["vitals", "diagnoses"]
            if cohort_type in ["hypertension", "cardiovascular", "diabetes"]:
                required_domains.extend(["medications", "sensor"])
            elif cohort_type == "baseline":
                required_domains.extend(["sensor"])

            results.append(self.check_data_completeness(patient_ids, required_domains))

        return results


class EvidenceCollector:
    """Collects and persists evidence trails for cohort exports"""

    def __init__(self, evidence_dir: Path):
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def create_cohort_evidence(
        self,
        cohort_type: str,
        patient_ids: List[str],
        selection_criteria: Dict[str, Any],
        sql_query: str,
        data_sources: List[str],
        compliance_checks: List[ComplianceCheckResult],
        created_by: str = "claude-explorer-app"
    ) -> CohortEvidence:
        """Create evidence record for a cohort"""
        query_hash = hashlib.sha256(sql_query.encode()).hexdigest()
        cohort_id = f"{cohort_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{query_hash[:8]}"

        return CohortEvidence(
            cohort_id=cohort_id,
            cohort_type=cohort_type,
            cohort_size=len(patient_ids),
            selection_criteria=selection_criteria,
            data_sources=data_sources,
            created_at=datetime.utcnow(),
            created_by=created_by,
            compliance_checks=compliance_checks,
            query_hash=query_hash
        )

    def generate_governance_report(
        self,
        cohort_evidence: CohortEvidence,
        dataset_metadata: Dict[str, Any],
        export_destination: Optional[str] = None
    ) -> GovernanceReport:
        """Generate comprehensive governance report"""
        report_id = f"report_{cohort_evidence.cohort_id}"

        # Summarize compliance results
        compliance_summary = {
            "total_checks": len(cohort_evidence.compliance_checks),
            "passed": len([c for c in cohort_evidence.compliance_checks if c.passed]),
            "failed": len([c for c in cohort_evidence.compliance_checks if not c.passed]),
            "errors": len([c for c in cohort_evidence.compliance_checks if c.severity == "error"]),
            "warnings": len([c for c in cohort_evidence.compliance_checks if c.severity == "warning"])
        }

        # Standard attestations
        attestations = [
            "Data exported from Verily Workbench controlled environment",
            "Cohort selection criteria documented and auditable",
            "Compliance checks executed prior to export",
            f"Export approved for risk tier: {dataset_metadata.get('risk_tier', 'standard')}"
        ]

        return GovernanceReport(
            report_id=report_id,
            cohort_evidence=cohort_evidence,
            dataset_metadata=dataset_metadata,
            compliance_summary=compliance_summary,
            attestations=attestations,
            generated_at=datetime.utcnow(),
            export_destination=export_destination
        )

    def save_report(self, report: GovernanceReport) -> Path:
        """Save governance report to disk as JSON"""
        report_path = self.evidence_dir / f"{report.report_id}.json"

        with open(report_path, 'w') as f:
            json.dump(report.model_dump(mode='json'), f, indent=2, default=str)

        return report_path

    def get_report(self, report_id: str) -> Optional[GovernanceReport]:
        """Retrieve a saved governance report"""
        report_path = self.evidence_dir / f"{report_id}.json"

        if not report_path.exists():
            return None

        with open(report_path, 'r') as f:
            data = json.load(f)

        return GovernanceReport(**data)

    def list_reports(self, cohort_type: Optional[str] = None) -> List[str]:
        """List all governance reports, optionally filtered by cohort type"""
        reports = []
        for report_file in self.evidence_dir.glob("report_*.json"):
            report_id = report_file.stem

            if cohort_type:
                # Filter by cohort type in filename
                if cohort_type not in report_id:
                    continue

            reports.append(report_id)

        return sorted(reports, reverse=True)  # Most recent first
