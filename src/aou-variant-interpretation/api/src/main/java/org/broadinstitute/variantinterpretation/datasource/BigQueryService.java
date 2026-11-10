package org.broadinstitute.variantinterpretation.datasource;

import com.google.cloud.bigquery.BigQuery;
import com.google.cloud.bigquery.FieldValueList;
import com.google.cloud.bigquery.Job;
import com.google.cloud.bigquery.JobId;
import com.google.cloud.bigquery.JobStatistics;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.TableId;
import com.google.cloud.bigquery.TableResult;
import java.util.Map;
import org.broadinstitute.variantinterpretation.model.TableStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * All of VIA's calls to BigQuery go through here, so query cost caps, logging, error
 * handling and usage tracking are applied in one place.
 */
@Service
public class BigQueryService {

  private static final Logger log = LoggerFactory.getLogger(BigQueryService.class);

  // Right now this is a small limit to keep development costs low and prevent accidental
  // full-table scan. When using the real VAT we'll need to use a more realistic value. See VIA-50
  private static final long MAXIMUM_BYTES_BILLED = 100L * 1024 * 1024;

  /**
   * Add these to every job VIA submits, so usage can be told apart from the workspace's other queries
   * in INFORMATION_SCHEMA.JOBS.
   */
  static final Map<String, String> JOB_LABELS = Map.of("app", "via");

  private final BigQuery bigQuery;
  private final QueryUsageMeter usage;

  public BigQueryService(BigQuery bigQuery, QueryUsageMeter usage) {
    this.bigQuery = bigQuery;
    this.usage = usage;
  }

  /**
   * Takes the builder rather than a built configuration so the cost cap and the labels can't be
   * skipped. Each query's statistics go to the usage meter once it has run, under {@code name},
   * which is how the usage log describes it to the user ("Cohort count", "VAT lookup").
   */
  public Iterable<FieldValueList> query(QueryJobConfiguration.Builder builder, String name) {
    QueryJobConfiguration configuration =
        builder.setMaximumBytesBilled(MAXIMUM_BYTES_BILLED).setLabels(JOB_LABELS).build();
    log.info("Running BigQuery query: {}", configuration.getQuery());
    try {
      TableResult result = bigQuery.query(configuration);
      meter(name, result.getJobId());
      return result.iterateAll();
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("Interrupted while querying BigQuery", e);
    }
  }

  /**
   * Reads the finished job's statistics into the meter. A job we can't look up (no id, or a
   * lookup failure) is still counted as a query; the figures BigQuery would have given are
   * accounting, not results, so they should never fail a search.
   */
  private void meter(String name, JobId jobId) {
    try {
      Job job = jobId == null ? null : bigQuery.getJob(jobId);
      JobStatistics.QueryStatistics statistics = job == null ? null : job.getStatistics();
      if (statistics == null) {
        usage.recordUnknown(name);
        return;
      }
      usage.record(name, statistics);
      log.info(
          "BigQuery job {}: {} bytes billed, cache hit {}",
          jobId.getJob(),
          statistics.getTotalBytesBilled(),
          statistics.getCacheHit());
    } catch (RuntimeException e) {
      log.warn("Couldn't read statistics for BigQuery job {}", jobId, e);
      usage.recordUnknown(name);
    }
  }

  /** Whether the current credentials can see this table, with the reason when they can't. */
  public TableStatus checkAccess(TableId table) {
    var status = new TableStatus().table("%s.%s.%s".formatted(table.getProject(), table.getDataset(), table.getTable()));
    try {
      if (bigQuery.getTable(table) == null) {
        return status.accessible(false).detail("Table does not exist, or is not visible to user.");
      }
      return status.accessible(true);
    } catch (RuntimeException e) {
      log.warn("BigQuery access check failed for table {}", status.getTable(), e);
      return status.accessible(false).detail(e.getMessage());
    }
  }
}
