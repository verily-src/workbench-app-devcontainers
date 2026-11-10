package org.broadinstitute.variantinterpretation.datasource;

import com.google.cloud.bigquery.JobStatistics;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import org.broadinstitute.variantinterpretation.model.QueryJob;
import org.broadinstitute.variantinterpretation.model.QueryUsage;
import org.broadinstitute.variantinterpretation.model.SearchUsage;
import org.springframework.stereotype.Component;

/**
 * This instance's BigQuery usage: running totals from each job's statistics, plus a log of the
 * last few requests (searches and type-ahead lookups) with the jobs each ran. One per process,
 * which in a Workbench app is one user's session.
 *
 * <p>Jobs are attributed to a request by thread: the controller brackets its work with {@link
 * #beginSearch} or {@link #beginConditionLookup} and {@link #endSearch}. A request that ran no job
 * is dropped from the log.
 *
 */
@Component
public class QueryUsageMeter {

  /** BigQuery on-demand analysis pricing, US dollars per TiB billed (as of Oct 16 2026) */
  static final double USD_PER_TIB = 6.25;

  /** How many searches are kept for the log; older ones are dropped. */
  static final int SEARCHES_KEPT = 20;

  private static final double BYTES_PER_TIB = 1024.0 * 1024 * 1024 * 1024;

  /** One request's jobs, filled in while it runs. Guarded by the meter's monitor. */
  private static final class SearchRecord {
    final int id;
    final SearchUsage.KindEnum kind;
    final OffsetDateTime at;
    final List<String> variants;
    final String term;
    List<String> phenotypes = List.of();
    final List<QueryJob> jobs = new ArrayList<>();

    SearchRecord(int id, SearchUsage.KindEnum kind, OffsetDateTime at, List<String> variants, String term) {
      this.id = id;
      this.kind = kind;
      this.at = at;
      this.variants = List.copyOf(variants);
      this.term = term;
    }

    SearchUsage snapshot() {
      long billed = jobs.stream().mapToLong(QueryJob::getBytesBilled).sum();
      return new SearchUsage()
          .id(id)
          .kind(kind)
          .at(at)
          .variants(variants)
          .phenotypes(phenotypes)
          .term(term)
          .queries(List.copyOf(jobs))
          .cacheHits((int) jobs.stream().filter(QueryJob::getCacheHit).count())
          .bytesProcessed(jobs.stream().mapToLong(QueryJob::getBytesProcessed).sum())
          .bytesBilled(billed)
          .estimatedCostUsd(cost(billed));
    }
  }

  private final Clock clock;
  private final OffsetDateTime since;
  private int queries;
  private int cacheHits;
  private long bytesProcessed;
  private long bytesBilled;
  private long slotMilliseconds;
  private int searchIds;
  /** Newest first. */
  private final Deque<SearchRecord> searches = new ArrayDeque<>();
  /** The request this thread is in; per-thread, so unguarded. */
  private final ThreadLocal<SearchRecord> current = new ThreadLocal<>();

  public QueryUsageMeter() {
    this(Clock.systemUTC());
  }

  QueryUsageMeter(Clock clock) {
    this.clock = clock;
    this.since = OffsetDateTime.now(clock);
  }

  /** Starts attributing this thread's jobs to a new search, the newest in the log. */
  public synchronized void beginSearch(List<String> variants) {
    begin(new SearchRecord(++searchIds, SearchUsage.KindEnum.SEARCH, OffsetDateTime.now(clock), variants, null));
  }

  /** Starts attributing this thread's jobs to a condition lookup for the type-ahead. */
  public synchronized void beginConditionLookup(String term) {
    begin(new SearchRecord(++searchIds, SearchUsage.KindEnum.CONDITION, OffsetDateTime.now(clock), List.of(), term));
  }

  private void begin(SearchRecord record) {
    searches.addFirst(record);
    while (searches.size() > SEARCHES_KEPT) {
      searches.removeLast();
    }
    current.set(record);
  }

  /**
   * Names the current search's conditions, once it has resolved them; the UI words the list, so
   * it reads the same as everywhere else. No-op outside a search.
   */
  public synchronized void describeSearchPhenotypes(List<String> phenotypes) {
    SearchRecord search = current.get();
    if (search != null) {
      search.phenotypes = List.copyOf(phenotypes);
    }
  }

  /**
   * Stops attributing this thread's jobs. Always called, so a failed request can't leak into the
   * next. A request that ran no job is taken out of the log: nothing to account for.
   */
  public synchronized void endSearch() {
    SearchRecord record = current.get();
    current.remove();
    if (record != null && record.jobs.isEmpty()) {
      searches.remove(record);
    }
  }

  /** Adds one finished query's statistics. Any figure BigQuery left out counts as zero. */
  public synchronized void record(String name, JobStatistics.QueryStatistics statistics) {
    boolean cacheHit = Boolean.TRUE.equals(statistics.getCacheHit());
    long processed = zeroIfNull(statistics.getTotalBytesProcessed());
    long billed = zeroIfNull(statistics.getTotalBytesBilled());
    long slotMs = zeroIfNull(statistics.getTotalSlotMs());
    queries++;
    if (cacheHit) {
      cacheHits++;
    }
    bytesProcessed += processed;
    bytesBilled += billed;
    slotMilliseconds += slotMs;
    attach(
        new QueryJob()
            .name(name)
            .at(OffsetDateTime.now(clock))
            .cacheHit(cacheHit)
            .bytesProcessed(processed)
            .bytesBilled(billed)
            .slotMilliseconds(slotMs));
  }

  /** A query that ran but whose statistics couldn't be fetched: counted, with nothing to add. */
  public synchronized void recordUnknown(String name) {
    queries++;
    attach(
        new QueryJob().name(name).at(OffsetDateTime.now(clock)).cacheHit(false).bytesProcessed(0L).bytesBilled(0L).slotMilliseconds(0L));
  }

  private void attach(QueryJob job) {
    SearchRecord search = current.get();
    if (search != null) {
      search.jobs.add(job);
    }
  }

  public synchronized QueryUsage snapshot() {
    return new QueryUsage()
        .queries(queries)
        .cacheHits(cacheHits)
        .bytesProcessed(bytesProcessed)
        .bytesBilled(bytesBilled)
        .slotMilliseconds(slotMilliseconds)
        .estimatedCostUsd(cost(bytesBilled))
        .since(since)
        .searches(searches.stream().map(SearchRecord::snapshot).toList());
  }

  private static double cost(long bytesBilled) {
    return bytesBilled / BYTES_PER_TIB * USD_PER_TIB;
  }

  private static long zeroIfNull(Long value) {
    return value == null ? 0 : value;
  }
}
