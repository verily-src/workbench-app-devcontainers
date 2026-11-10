package org.broadinstitute.variantinterpretation.datasource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.tuple;
import static org.assertj.core.api.Assertions.within;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.cloud.bigquery.JobStatistics;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.broadinstitute.variantinterpretation.model.QueryJob;
import org.broadinstitute.variantinterpretation.model.QueryUsage;
import org.broadinstitute.variantinterpretation.model.SearchUsage;
import org.junit.jupiter.api.Test;

class QueryUsageMeterTest {

  private static final Instant START = Instant.parse("2026-10-14T15:00:00Z");

  private static JobStatistics.QueryStatistics stats(Long processed, Long billed, Boolean cacheHit, Long slotMs) {
    JobStatistics.QueryStatistics statistics = mock(JobStatistics.QueryStatistics.class);
    when(statistics.getTotalBytesProcessed()).thenReturn(processed);
    when(statistics.getTotalBytesBilled()).thenReturn(billed);
    when(statistics.getCacheHit()).thenReturn(cacheHit);
    when(statistics.getTotalSlotMs()).thenReturn(slotMs);
    return statistics;
  }

  @Test
  void startsAtZeroFromWhenItWasMade() {
    QueryUsage usage = new QueryUsageMeter(Clock.fixed(START, ZoneOffset.UTC)).snapshot();

    assertThat(usage.getQueries()).isZero();
    assertThat(usage.getBytesBilled()).isZero();
    assertThat(usage.getEstimatedCostUsd()).isZero();
    assertThat(usage.getSince().toInstant()).isEqualTo(START);
  }

  /** Bytes, slot time and cache hits add up across queries; cost follows bytes billed at the on-demand rate. */
  @Test
  void addsUpEveryQuery() {
    QueryUsageMeter meter = new QueryUsageMeter(Clock.fixed(START, ZoneOffset.UTC));
    long gib = 1024L * 1024 * 1024;

    meter.record("VAT lookup", stats(3 * gib, 3 * gib, false, 40_000L));
    meter.record("VAT lookup", stats(3 * gib, 0L, true, 0L));
    meter.record("Cohort count", stats(2 * 1024 * 1024L, 10 * 1024 * 1024L, false, 150L));

    QueryUsage usage = meter.snapshot();
    assertThat(usage.getQueries()).isEqualTo(3);
    assertThat(usage.getCacheHits()).isEqualTo(1);
    assertThat(usage.getBytesProcessed()).isEqualTo(6 * gib + 2 * 1024 * 1024L);
    assertThat(usage.getBytesBilled()).isEqualTo(3 * gib + 10 * 1024 * 1024L);
    assertThat(usage.getSlotMilliseconds()).isEqualTo(40_150L);
    // 3 GiB + 10 MiB at $6.25 per TiB.
    assertThat(usage.getEstimatedCostUsd()).isCloseTo((3.0 + 10.0 / 1024) / 1024 * 6.25, within(1e-9));
  }

  /** Jobs metered between beginSearch and endSearch belong to that search; others only to the totals. */
  @Test
  void logsEachSearchWithTheJobsItRan() {
    QueryUsageMeter meter = new QueryUsageMeter(Clock.fixed(START, ZoneOffset.UTC));
    long mib = 1024L * 1024;

    // The type-ahead, outside any search.
    meter.record("Condition candidates", stats(4096L, 10 * mib, false, 20L));
    meter.beginSearch(List.of("1-1-A-G", "2-2-C-T"));
    meter.record("VAT lookup", stats(26_000L, 10 * mib, false, 30L));
    meter.record("Resolve concept", stats(4_000L, 0L, true, 0L));
    meter.describeSearchPhenotypes(List.of("Tetralogy of Fallot", "Long QT syndrome"));
    meter.recordUnknown("Cohort count");
    meter.endSearch();
    // After the search ends, a job is in the totals but belongs to nothing.
    meter.record("Condition candidates", stats(4096L, 10 * mib, false, 20L));

    QueryUsage usage = meter.snapshot();
    assertThat(usage.getQueries()).isEqualTo(5);
    assertThat(usage.getSearches()).hasSize(1);
    SearchUsage search = usage.getSearches().get(0);
    assertThat(search.getId()).isEqualTo(1);
    assertThat(search.getKind()).isEqualTo(SearchUsage.KindEnum.SEARCH);
    assertThat(search.getTerm().orElse(null)).isNull();
    assertThat(search.getAt().toInstant()).isEqualTo(START);
    assertThat(search.getVariants()).containsExactly("1-1-A-G", "2-2-C-T");
    assertThat(search.getPhenotypes()).containsExactly("Tetralogy of Fallot", "Long QT syndrome");
    assertThat(search.getQueries())
        .extracting(QueryJob::getName, QueryJob::getBytesBilled, QueryJob::getCacheHit)
        .containsExactly(
            tuple("VAT lookup", 10 * mib, false), tuple("Resolve concept", 0L, true), tuple("Cohort count", 0L, false));
    assertThat(search.getCacheHits()).isEqualTo(1);
    assertThat(search.getBytesBilled()).isEqualTo(10 * mib);
    assertThat(search.getBytesProcessed()).isEqualTo(30_000L);
    assertThat(search.getEstimatedCostUsd()).isCloseTo(10.0 / 1024 / 1024 * 6.25, within(1e-12));
  }

  /** A type-ahead lookup is logged like a search, with its term; one that ran no query is dropped. */
  @Test
  void logsConditionLookupsThatQueried() {
    QueryUsageMeter meter = new QueryUsageMeter(Clock.fixed(START, ZoneOffset.UTC));

    meter.beginConditionLookup("long qt");
    meter.record("Condition candidates", stats(4096L, 10L * 1024 * 1024, false, 20L));
    meter.endSearch();
    // A blank term never reaches BigQuery; nothing to account for.
    meter.beginConditionLookup("");
    meter.endSearch();

    QueryUsage usage = meter.snapshot();
    assertThat(usage.getSearches()).hasSize(1);
    SearchUsage lookup = usage.getSearches().get(0);
    assertThat(lookup.getKind()).isEqualTo(SearchUsage.KindEnum.CONDITION);
    assertThat(lookup.getTerm().orElse(null)).isEqualTo("long qt");
    assertThat(lookup.getVariants()).isEmpty();
    assertThat(lookup.getPhenotypes()).isEmpty();
    assertThat(lookup.getQueries()).extracting(QueryJob::getName).containsExactly("Condition candidates");
    assertThat(lookup.getBytesBilled()).isEqualTo(10L * 1024 * 1024);
  }

  /** The log keeps the newest twenty, newest first; the totals keep everything. */
  @Test
  void keepsTheNewestTwentySearches() {
    QueryUsageMeter meter = new QueryUsageMeter();

    for (int i = 1; i <= 23; i++) {
      meter.beginSearch(List.of("1-" + i + "-A-G"));
      meter.record("VAT lookup", stats(1L, 1L, false, 1L));
      meter.endSearch();
    }

    QueryUsage usage = meter.snapshot();
    assertThat(usage.getQueries()).isEqualTo(23);
    assertThat(usage.getSearches()).hasSize(20);
    assertThat(usage.getSearches().get(0).getId()).isEqualTo(23);
    assertThat(usage.getSearches().get(19).getId()).isEqualTo(4);
  }

  /** A search without a condition, or whose condition wasn't found, has no phenotype. */
  @Test
  void leavesThePhenotypeNullWhenNoneWasNamed() {
    QueryUsageMeter meter = new QueryUsageMeter();
    meter.beginSearch(List.of("1-1-A-G"));
    meter.record("VAT lookup", stats(1L, 1L, false, 1L));
    meter.endSearch();
    // Naming outside a search does nothing.
    meter.describeSearchPhenotypes(List.of("Ignored"));

    assertThat(meter.snapshot().getSearches().get(0).getPhenotypes()).isEmpty();
  }

  /** BigQuery leaves figures null on some jobs (a dry run, a failed one); they count as nothing. */
  @Test
  void treatsMissingFiguresAsZero() {
    QueryUsageMeter meter = new QueryUsageMeter();

    meter.record("Query", stats(null, null, null, null));
    meter.recordUnknown("Query");

    QueryUsage usage = meter.snapshot();
    assertThat(usage.getQueries()).isEqualTo(2);
    assertThat(usage.getCacheHits()).isZero();
    assertThat(usage.getBytesBilled()).isZero();
  }

  /**
   * A snapshot taken while searches are being recorded on other threads describes one state: its
   * totals are the sums of its log, never a job ahead of or behind it. Several threads each run a
   * stream of one-job searches while this one snapshots as fast as it can.
   */
  @Test
  void snapshotsAreConsistentUnderConcurrentRecording() throws Exception {
    QueryUsageMeter meter = new QueryUsageMeter(Clock.fixed(START, ZoneOffset.UTC));
    long mib = 1024L * 1024;
    int writers = 4;
    int searchesEach = 500;
    CountDownLatch go = new CountDownLatch(1);
    ExecutorService pool = Executors.newFixedThreadPool(writers);
    try {
      List<Future<?>> done = new java.util.ArrayList<>();
      for (int w = 0; w < writers; w++) {
        done.add(
            pool.submit(
                () -> {
                  go.await();
                  for (int i = 0; i < searchesEach; i++) {
                    meter.beginSearch(List.of("1-1-A-C"));
                    meter.record("VAT lookup", stats(mib, 10 * mib, false, 7L));
                    meter.endSearch();
                  }
                  return null;
                }));
      }
      go.countDown();
      int snapshots = 0;
      while (done.stream().anyMatch(f -> !f.isDone())) {
        QueryUsage usage = meter.snapshot();
        snapshots++;
        // Each query bills 10 MiB, so the totals must agree with the count exactly. A search in the
        // log has either recorded its one job or not begun it yet; never a job half-recorded.
        assertThat(usage.getBytesBilled()).isEqualTo(10 * mib * usage.getQueries());
        assertThat(usage.getBytesProcessed()).isEqualTo(mib * usage.getQueries());
        assertThat(usage.getSlotMilliseconds()).isEqualTo(7L * usage.getQueries());
        assertThat(usage.getSearches())
            .allSatisfy(search -> assertThat(search.getBytesBilled()).isEqualTo(10 * mib * search.getQueries().size()));
      }
      for (Future<?> f : done) {
        f.get(10, TimeUnit.SECONDS);
      }
      assertThat(snapshots).isPositive();
      assertThat(meter.snapshot().getQueries()).isEqualTo(writers * searchesEach);
    } finally {
      pool.shutdownNow();
    }
  }
}
