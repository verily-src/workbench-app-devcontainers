import { apiFetch } from "./client";

/** One BigQuery job, as the backend names its query shapes ("VAT lookup", "Cohort count"). */
export interface QueryJob {
  name: string;
  at: string;
  /** Answered from BigQuery's result cache, which bills nothing. */
  cacheHit: boolean;
  bytesProcessed: number;
  bytesBilled: number;
  slotMilliseconds: number;
}

/** One request that queried BigQuery this session, and the jobs it ran. */
export interface SearchUsage {
  /** Counts up from 1 within the session. */
  id: number;
  /** A search, or a condition lookup for the phenotype type-ahead. */
  kind: "search" | "condition";
  at: string;
  /** For a search, the variant IDs searched; empty for a condition lookup. */
  variants: string[];
  /**
   * For a search, the names of the conditions it resolved, in request order; a participant is
   * matched by any of them. Empty when none was picked or found, and for a condition lookup.
   */
  phenotypes: string[];
  /** For a condition lookup, the text looked up; null for a search. */
  term: string | null;
  /** In the order they ran. */
  queries: QueryJob[];
  cacheHits: number;
  bytesProcessed: number;
  bytesBilled: number;
  estimatedCostUsd: number;
}

/** This VIA instance's BigQuery usage since it started; see /api/usage. */
export interface QueryUsage {
  queries: number;
  /** Queries BigQuery answered from its cache, which bill nothing. */
  cacheHits: number;
  bytesProcessed: number;
  /** What on-demand pricing charges for: rounded up to 10 MB a query, zero for a cache hit. */
  bytesBilled: number;
  slotMilliseconds: number;
  /** bytesBilled at on-demand pricing. An estimate; a reservation bills by slot time instead. */
  estimatedCostUsd: number;
  /** When the backend started counting, as an ISO date-time. */
  since: string;
  /**
   * The last 20 requests that queried BigQuery, newest first: searches and the condition
   * type-ahead's lookups. A request that ran no query isn't logged.
   */
  searches: SearchUsage[];
}

export const fetchQueryUsage = () => apiFetch<QueryUsage>("/usage");
