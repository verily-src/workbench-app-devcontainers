package org.broadinstitute.variantinterpretation.datasource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.cloud.bigquery.BigQuery;
import com.google.cloud.bigquery.Job;
import com.google.cloud.bigquery.JobId;
import com.google.cloud.bigquery.JobStatistics;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.TableResult;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/** The accounting around a query: what the job is sent with, and what comes back into the meter. */
class BigQueryServiceTest {

  private final BigQuery bigQuery = mock(BigQuery.class);
  private final QueryUsageMeter meter = new QueryUsageMeter();
  private final BigQueryService service = new BigQueryService(bigQuery, meter);

  private TableResult resultWithJob(String jobName) throws InterruptedException {
    TableResult result = mock(TableResult.class);
    when(result.getJobId()).thenReturn(jobName == null ? null : JobId.of(jobName));
    when(result.iterateAll()).thenReturn(List.of());
    when(bigQuery.query(any(QueryJobConfiguration.class))).thenReturn(result);
    return result;
  }

  @Test
  void query_capsBytesBilledAndLabelsTheJob() throws InterruptedException {
    resultWithJob(null);

    service.query(QueryJobConfiguration.newBuilder("SELECT 1"), "VAT lookup");

    ArgumentCaptor<QueryJobConfiguration> sent = ArgumentCaptor.forClass(QueryJobConfiguration.class);
    org.mockito.Mockito.verify(bigQuery).query(sent.capture());
    assertThat(sent.getValue().getMaximumBytesBilled()).isEqualTo(100L * 1024 * 1024);
    assertThat(sent.getValue().getLabels()).containsEntry("app", "via");
  }

  @Test
  void query_metersTheFinishedJobsStatistics() throws InterruptedException {
    resultWithJob("job-1");
    JobStatistics.QueryStatistics statistics = mock(JobStatistics.QueryStatistics.class);
    when(statistics.getTotalBytesProcessed()).thenReturn(2_000_000L);
    when(statistics.getTotalBytesBilled()).thenReturn(10_485_760L);
    when(statistics.getCacheHit()).thenReturn(false);
    when(statistics.getTotalSlotMs()).thenReturn(120L);
    Job job = mock(Job.class);
    when(job.getStatistics()).thenReturn(statistics);
    when(bigQuery.getJob(JobId.of("job-1"))).thenReturn(job);

    meter.beginSearch(List.of("1-1-A-G"));
    service.query(QueryJobConfiguration.newBuilder("SELECT 1"), "VAT lookup");
    meter.endSearch();

    assertThat(meter.snapshot().getQueries()).isEqualTo(1);
    assertThat(meter.snapshot().getBytesBilled()).isEqualTo(10_485_760L);
    assertThat(meter.snapshot().getSlotMilliseconds()).isEqualTo(120L);
    // Named, and logged under the search that was running.
    assertThat(meter.snapshot().getSearches().get(0).getQueries()).extracting(q -> q.getName()).containsExactly("VAT lookup");
  }

  /** Accounting never fails a search: a job that can't be looked up still counts as one query. */
  @Test
  void query_countsAQueryWhoseStatisticsCantBeRead() throws InterruptedException {
    resultWithJob("job-2");
    when(bigQuery.getJob(JobId.of("job-2"))).thenThrow(new RuntimeException("gone"));

    Iterable<?> rows = service.query(QueryJobConfiguration.newBuilder("SELECT 1"), "VAT lookup");

    assertThat(rows).isEmpty();
    assertThat(meter.snapshot().getQueries()).isEqualTo(1);
    assertThat(meter.snapshot().getBytesBilled()).isZero();
  }
}
