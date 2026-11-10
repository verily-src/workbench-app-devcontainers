package org.broadinstitute.variantinterpretation.controller;

import com.google.cloud.bigquery.TableId;
import java.util.ArrayList;
import java.util.List;

import org.broadinstitute.variantinterpretation.datasource.BigQueryProperties;
import org.broadinstitute.variantinterpretation.datasource.BigQueryService;
import org.broadinstitute.variantinterpretation.datasource.ConditionLookupService;
import org.broadinstitute.variantinterpretation.datasource.QueryUsageMeter;
import org.broadinstitute.variantinterpretation.api.SystemApi;
import org.broadinstitute.variantinterpretation.model.BigQueryStatus;
import org.broadinstitute.variantinterpretation.model.DataSourceVersion;
import org.broadinstitute.variantinterpretation.model.QueryUsage;
import org.broadinstitute.variantinterpretation.model.TableStatus;
import org.broadinstitute.variantinterpretation.ontology.HpoLookupService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SystemController implements SystemApi {

  private final BigQueryService bigQuery;
  private final BigQueryProperties properties;
  private final QueryUsageMeter usage;
  private final HpoLookupService hpo;

  public SystemController(BigQueryService bigQuery, BigQueryProperties properties, QueryUsageMeter usage, HpoLookupService hpo) {
    this.bigQuery = bigQuery;
    this.properties = properties;
    this.usage = usage;
    this.hpo = hpo;
  }

  /** What this instance has spent on BigQuery since it started; see QueryUsageMeter. */
  @Override
  public ResponseEntity<QueryUsage> queryUsage() {
    return ResponseEntity.ok(usage.snapshot());
  }

  /**
   * Checks that VIA can access all BigQuery tables.
   */
  @Override
  public ResponseEntity<BigQueryStatus> bigQueryStatus() {
    List<TableId> tables = new ArrayList<>();
    tables.add(properties.vatTable());
    ConditionLookupService.CDR_TABLES.forEach(t -> tables.add(properties.cdrTable(t)));

    List<TableStatus> statuses = tables.stream().map(bigQuery::checkAccess).toList();
    return ResponseEntity.ok(
        new BigQueryStatus()
            .tables(statuses)
            .accessible(statuses.stream().allMatch(TableStatus::getAccessible)));
  }

  // TODO VIA-47: right now these data source versions are hardcoded (and not entirely accurate)
  @Override
  public ResponseEntity<List<DataSourceVersion>> dataSourceVersions() {
    return ResponseEntity.ok(
        List.of(
            source(
                "All of Us",
                "CDRv9",
                "Whole-genome sequences and health records of the research cohort",
                "https://researchallofus.org/"),
            source(
                "gnomAD",
                "v3.1.2",
                "Allele frequencies across the wider population, for comparison",
                "https://gnomad.broadinstitute.org/"),
            source(
                "ClinVar",
                "2025-06-01",
                "Reported clinical classifications and the conditions they cite",
                "https://ncbi.nlm.nih.gov/clinvar/"),
            source("SpliceAI", "v1.3", "Predicted gain or loss of splice sites", "https://github.com/Illumina/SpliceAI"),
            source(
                "LOFTEE",
                "v1.0.3",
                "Confidence in each predicted loss-of-function variant",
                "https://github.com/konradjk/loftee"),
            // The one source that ships inside VIA, so its version is read from the file itself.
            source("HPO", hpo.release(), "Phenotype terms that picked conditions are matched to", "https://hpo.jax.org/")));
  }

  private static DataSourceVersion source(String name, String version, String description, String url) {
    return new DataSourceVersion().name(name).version(version).description(description).url(url);
  }
}
