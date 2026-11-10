package org.broadinstitute.variantinterpretation.datasource;

import com.google.cloud.bigquery.TableId;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Where VIA's BigQuery data lives, and which project pays for querying it.
 *
 * @param billingProjectId project query jobs run in and are billed to: the workspace's own
 *     project ({@code GOOGLE_PROJECT}) on a Workbench VM
 * @param vatProjectId project owning the VAT dataset
 * @param vatDatasetId dataset holding the VAT table
 * @param vatTableId the VAT table backing variant search
 * @param cdr the workspace's CDR dataset as {@code project.dataset} ({@code WORKSPACE_CDR} on a
 *     Workbench VM), holding the condition lookup tables
 */
@ConfigurationProperties(prefix = "bigquery")
public record BigQueryProperties(
    String billingProjectId,
    String vatProjectId,
    String vatDatasetId,
    String vatTableId,
    String cdr) {

  /**
   * Fails startup on a missing or malformed CDR, rather than letting it surface later as broken
   * SQL. application.properties supplies a default, so "missing" means it was set to blank.
   */
  public BigQueryProperties {
    if (cdr == null || cdr.isBlank()) {
      throw new IllegalArgumentException(
          "WORKSPACE_CDR is not set. Set it to the CDR dataset as \"project.dataset\".");
    }
    if (cdr.split("\\.").length != 2) {
      throw new IllegalArgumentException(
          "WORKSPACE_CDR must be the CDR dataset as \"project.dataset\", got: " + cdr);
    }
  }

  /** The configured VAT table, as the id type the BigQuery client expects. */
  public TableId vatTable() {
    return TableId.of(vatProjectId, vatDatasetId, vatTableId);
  }

  /**
   * A table in the CDR. The condition lookup tables aren't configurable the way the VAT table
   * is: `cb_criteria`, `concept_ancestor` and `condition_occurrence` are fixed names in every All
   * of Us CDR, so only the dataset varies.
   */
  public TableId cdrTable(String table) {
    String[] parts = cdr.split("\\.");
    return TableId.of(parts[0], parts[1], table);
  }

  /** Fully-qualified, backtick-quotable reference to the configured VAT table, for use in SQL. */
  public String vatTableRef() {
    return sqlRef(vatTable());
  }

  /** Same, for a table in the CDR. */
  public String cdrTableRef(String table) {
    return sqlRef(cdrTable(table));
  }

  private static String sqlRef(TableId table) {
    return "`%s.%s.%s`".formatted(table.getProject(), table.getDataset(), table.getTable());
  }
}
