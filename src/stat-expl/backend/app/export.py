"""
Export module for Dataset Explorer.
Handles sub-cohort export to GCS buckets with risk tiering and governance bundling.
"""
import csv
import json
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel
from google.cloud import bigquery, storage
from .config import AppConfig, WorkbenchResource
from .governance import (
    ComplianceValidator,
    EvidenceCollector,
    CohortEvidence,
    GovernanceReport
)


class ExportRequest(BaseModel):
    """Request to export a cohort"""
    cohort_type: str
    patient_ids: List[str]
    selection_criteria: Dict[str, Any]
    sql_query: str
    data_sources: List[str]
    risk_tier: str = "standard"  # 'standard', 'sensitive', 'highly_sensitive'
    require_validation: bool = True
    validated_by: Optional[str] = None


class ExportResult(BaseModel):
    """Result of an export operation"""
    success: bool
    export_path: Optional[str] = None
    governance_report_path: Optional[str] = None
    message: str
    validation_status: str = "pending"  # 'pending', 'approved', 'rejected'
    compliance_passed: bool = False
    errors: List[str] = []


class CohortExporter:
    """Exports cohorts to GCS buckets with governance controls"""

    def __init__(
        self,
        config: AppConfig,
        bq_client: bigquery.Client,
        data_project: str
    ):
        self.config = config
        self.bq_client = bq_client
        self.data_project = data_project
        self.storage_client = storage.Client(project=config.app_project)

        # Initialize governance components
        evidence_dir = Path.home() / ".claude" / "evidence"
        self.evidence_collector = EvidenceCollector(evidence_dir)
        self.compliance_validator = ComplianceValidator(bq_client, data_project)

    def get_export_bucket(self, risk_tier: str) -> Optional[WorkbenchResource]:
        """Get appropriate export bucket based on risk tier"""
        bucket = self.config.discovery.get_export_bucket(risk_tier)

        if not bucket:
            # Fall back to any controlled bucket
            controlled = self.config.discovery.get_controlled_buckets()
            if controlled:
                return controlled[0]

        return bucket

    def validate_export_request(
        self,
        request: ExportRequest
    ) -> tuple[bool, List[str]]:
        """
        Validate export request meets requirements.
        Returns (is_valid, error_messages).
        """
        errors = []

        # Check patient IDs
        if not request.patient_ids:
            errors.append("Empty cohort - no patients to export")

        # Check risk tier is valid
        valid_tiers = ["standard", "sensitive", "highly_sensitive"]
        if request.risk_tier not in valid_tiers:
            errors.append(f"Invalid risk tier: {request.risk_tier}")

        # Check validation requirement
        if self.config.require_validation and not request.validated_by:
            errors.append("Export requires validator approval but validated_by is not set")

        # Check export destination exists
        bucket = self.get_export_bucket(request.risk_tier)
        if not bucket:
            errors.append(f"No export bucket configured for risk tier: {request.risk_tier}")

        return (len(errors) == 0, errors)

    def run_compliance_checks(
        self,
        request: ExportRequest
    ) -> tuple[bool, List[Any]]:
        """
        Run all compliance checks on the cohort.
        Returns (all_passed, check_results).
        """
        if not self.config.run_compliance_checks:
            return (True, [])

        check_results = self.compliance_validator.run_all_checks(
            patient_ids=request.patient_ids,
            cohort_type=request.cohort_type,
            enabled_checks=self.config.compliance_checks
        )

        # Check if any critical checks failed
        all_passed = all(
            result.passed or result.severity != "error"
            for result in check_results
        )

        return (all_passed, check_results)

    def export_cohort_csv(
        self,
        request: ExportRequest
    ) -> ExportResult:
        """
        Export cohort to CSV with governance report.

        Workflow:
        1. Validate export request
        2. Run compliance checks
        3. Build cohort evidence trail
        4. Query and export patient data
        5. Generate governance report
        6. Upload to appropriate GCS bucket
        7. Bundle governance report with export
        """

        # Step 1: Validate request
        is_valid, validation_errors = self.validate_export_request(request)
        if not is_valid:
            return ExportResult(
                success=False,
                message="Export validation failed",
                errors=validation_errors
            )

        # Step 2: Run compliance checks
        if self.config.run_compliance_checks:
            compliance_passed, check_results = self.run_compliance_checks(request)

            if not compliance_passed:
                error_checks = [c for c in check_results if c.severity == "error" and not c.passed]
                errors = [f"{c.check_name}: {c.message}" for c in error_checks]

                return ExportResult(
                    success=False,
                    message="Compliance checks failed",
                    compliance_passed=False,
                    errors=errors
                )
        else:
            check_results = []
            compliance_passed = True

        # Step 3: Build evidence trail
        cohort_evidence = self.evidence_collector.create_cohort_evidence(
            cohort_type=request.cohort_type,
            patient_ids=request.patient_ids,
            selection_criteria=request.selection_criteria,
            sql_query=request.sql_query,
            data_sources=request.data_sources,
            compliance_checks=check_results,
            created_by=request.validated_by or "system"
        )

        # Step 4: Get export bucket
        export_bucket = self.get_export_bucket(request.risk_tier)
        if not export_bucket:
            return ExportResult(
                success=False,
                message=f"No export bucket available for risk tier: {request.risk_tier}",
                errors=["Export bucket not configured"]
            )

        # Extract bucket name from path (gs://bucket-name -> bucket-name)
        bucket_name = export_bucket.path.replace("gs://", "").split('/')[0]

        # Step 5: Query patient data
        patient_list = ','.join([f"'{p}'" for p in request.patient_ids])

        demo_query = f"""
        SELECT
            d.SUBJID,
            d.SEX,
            d.RACE,
            d.age_at_enrollment,
            e.enrollment_date
        FROM `{self.data_project}.screener.DM` d
        LEFT JOIN `{self.data_project}.analysis.ENRDT` e ON d.SUBJID = e.SUBJID
        WHERE d.SUBJID IN ({patient_list})
        ORDER BY d.SUBJID
        """

        try:
            results = list(self.bq_client.query(demo_query).result())
        except Exception as e:
            return ExportResult(
                success=False,
                message=f"Failed to query cohort data: {str(e)}",
                errors=[str(e)]
            )

        # Step 6: Generate CSV
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'SUBJID',
            'Sex',
            'Race',
            'Age',
            'Enrollment_Date',
            'Cohort_Type',
            'Export_Timestamp',
            'Validated_By'
        ])

        export_timestamp = datetime.utcnow().isoformat()

        for row in results:
            writer.writerow([
                row.SUBJID,
                row.SEX or '',
                row.RACE or '',
                row.age_at_enrollment or '',
                row.enrollment_date.isoformat() if row.enrollment_date else '',
                request.cohort_type,
                export_timestamp,
                request.validated_by or 'system'
            ])

        csv_content = output.getvalue()

        # Step 7: Upload to GCS
        timestamp_str = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        cohort_filename = f"cohort_{request.cohort_type}_{timestamp_str}.csv"
        blob_path = f"exports/{request.cohort_type}/{cohort_filename}"

        try:
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            blob.upload_from_string(csv_content, content_type='text/csv')
            export_path = f"gs://{bucket_name}/{blob_path}"
        except Exception as e:
            return ExportResult(
                success=False,
                message=f"Failed to upload to GCS: {str(e)}",
                errors=[str(e)]
            )

        # Step 8: Generate and upload governance report
        dataset_metadata = {
            "data_project": self.data_project,
            "risk_tier": request.risk_tier,
            "export_timestamp": export_timestamp,
            "app_project": self.config.app_project
        }

        governance_report = self.evidence_collector.generate_governance_report(
            cohort_evidence=cohort_evidence,
            dataset_metadata=dataset_metadata,
            export_destination=export_path
        )

        # Save report locally
        local_report_path = self.evidence_collector.save_report(governance_report)

        # Upload report to GCS alongside cohort data
        report_filename = f"governance_report_{request.cohort_type}_{timestamp_str}.json"
        report_blob_path = f"exports/{request.cohort_type}/{report_filename}"

        try:
            report_blob = bucket.blob(report_blob_path)
            report_blob.upload_from_filename(str(local_report_path), content_type='application/json')
            governance_report_path = f"gs://{bucket_name}/{report_blob_path}"
        except Exception as e:
            # Non-critical - export succeeded but report upload failed
            governance_report_path = str(local_report_path)

        # Step 9: Return success
        validation_status = "approved" if request.validated_by else "pending"

        return ExportResult(
            success=True,
            export_path=export_path,
            governance_report_path=governance_report_path,
            message=f"Cohort exported successfully to {export_path}",
            validation_status=validation_status,
            compliance_passed=compliance_passed
        )

    def list_exports(
        self,
        cohort_type: Optional[str] = None,
        risk_tier: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all exports, optionally filtered by cohort type or risk tier"""
        exports = []

        # Get all controlled buckets
        buckets = self.config.discovery.get_controlled_buckets()

        for bucket_resource in buckets:
            bucket_name = bucket_resource.path.replace("gs://", "").split('/')[0]

            try:
                bucket = self.storage_client.bucket(bucket_name)
                blobs = bucket.list_blobs(prefix="exports/")

                for blob in blobs:
                    if blob.name.endswith('.csv'):
                        # Parse metadata from blob
                        parts = blob.name.split('/')
                        if len(parts) >= 3:
                            export_cohort_type = parts[1]

                            # Filter by cohort type if specified
                            if cohort_type and export_cohort_type != cohort_type:
                                continue

                            exports.append({
                                "cohort_type": export_cohort_type,
                                "path": f"gs://{bucket_name}/{blob.name}",
                                "size_bytes": blob.size,
                                "created_at": blob.time_created.isoformat() if blob.time_created else None,
                                "bucket": bucket_name
                            })
            except Exception:
                # Skip buckets we can't access
                continue

        return sorted(exports, key=lambda x: x.get('created_at', ''), reverse=True)
