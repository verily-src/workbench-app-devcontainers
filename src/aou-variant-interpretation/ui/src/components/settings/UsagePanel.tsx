import { Fragment, useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { describeError } from "../../api/client";
import { fetchQueryUsage, type QueryUsage, type SearchUsage } from "../../api/usage";
import colors from "../../libs/colors";
import { useHoveredKey } from "../../libs/hooks";
import * as Style from "../../libs/style";
import { formatBytes, formatInt, formatUsd } from "../../utils/format";
import { describeAlternatives } from "../../utils/phenotypes";
import Clickable from "../common/Clickable";
import { ArrowLeftIcon, ArrowRightIcon, ChevronDownIcon, ChevronRightIcon, UserIcon } from "../icons";

const styles = {
  heading: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    marginBottom: 14,
  },
  strip: {
    display: "flex",
    flexWrap: "wrap",
    rowGap: 12,
    margin: "2px 0 0",
    padding: 0,
  },
  stat: {
    display: "flex",
    flexDirection: "column-reverse",
    gap: 3,
    minWidth: 0,
    padding: "2px 28px",
    borderLeft: `1px solid ${colors.border}`,
  },
  statFirst: {
    paddingLeft: 0,
    borderLeft: "none",
  },
  statLabel: {
    fontSize: 11.5,
    lineHeight: 1.2,
    color: colors.textSecondary,
  },
  statValue: {
    fontSize: 22,
    fontWeight: 700,
    lineHeight: 1.1,
    letterSpacing: -0.3,
    color: colors.textPrimary,
    fontVariantNumeric: "tabular-nums",
  },
  statFigure: {
    display: "flex",
    alignItems: "baseline",
    gap: 7,
    margin: 0,
  },
  statSub: {
    fontSize: 11.5,
    color: colors.textMuted,
    whiteSpace: "nowrap",
  },
  caption: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    gap: 12,
    margin: "16px 0 6px",
    fontSize: 11.5,
    color: colors.textSecondary,
  },
  captionTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: colors.textBody,
  },
  frame: {
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    overflow: "hidden",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
  },
  head: {
    padding: "7px 10px",
    background: colors.surface0,
    borderBottom: `1px solid ${colors.border}`,
    textAlign: "left",
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.3,
    textTransform: "uppercase",
    color: colors.textSecondary,
    whiteSpace: "nowrap",
  },
  cell: {
    padding: "8px 10px",
    borderTop: `1px solid ${colors.border}`,
    verticalAlign: "middle",
    whiteSpace: "nowrap",
    fontSize: 12.5,
    color: colors.textBody,
  },
  cellRight: {
    textAlign: "right",
    fontVariantNumeric: "tabular-nums",
  },
  request: {
    cursor: "pointer",
  },
  requestHovered: {
    background: colors.surface1,
  },
  toggle: {
    ...Style.buttons.icon,
    padding: 2,
    color: colors.textMuted,
  },
  toggleCell: {
    width: 16,
    paddingRight: 0,
  },
  time: {
    width: 72,
    fontSize: 11.5,
    color: colors.textSecondary,
    fontVariantNumeric: "tabular-nums",
  },
  variants: {
    ...Style.elements.mono,
    display: "block",
    overflow: "hidden",
    maxWidth: 340,
    fontSize: 11.5,
    color: colors.textBody,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  lookup: {
    fontSize: 12.5,
    color: colors.textBody,
  },
  lookupTerm: {
    fontWeight: 700,
  },
  phenotype: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    maxWidth: 240,
    padding: "1px 8px",
    borderRadius: 999,
    background: colors.bgAccent,
    color: colors.textAccent,
    fontSize: 11,
    fontWeight: 600,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    verticalAlign: "middle",
  },
  phenotypeNext: {
    marginLeft: 4,
  },
  none: {
    color: colors.textMuted,
  },
  cost: {
    fontWeight: 600,
    color: colors.textPrimary,
  },
  queryCell: {
    padding: "6px 10px",
    borderTop: `1px solid ${colors.border}`,
    background: colors.surface1,
    verticalAlign: "middle",
    whiteSpace: "nowrap",
    fontSize: 12,
    color: colors.textSecondary,
  },
  queryName: {
    paddingLeft: 34,
    color: colors.textBody,
  },
  tag: {
    display: "inline-block",
    padding: "1px 7px",
    borderRadius: 999,
    fontSize: 10.5,
    fontWeight: 600,
    lineHeight: 1.5,
  },
  tagCached: {
    background: colors.bgSuccess,
    color: colors.textSuccess,
  },
  tagBilled: {
    background: colors.bgAccent,
    color: colors.textAccent,
  },
  skeletonRow: {
    padding: "11px 10px",
    borderTop: `1px solid ${colors.border}`,
  },
  empty: {
    padding: "14px 12px",
    fontSize: 12.5,
    color: colors.textSecondary,
  },
  pager: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 4,
    marginTop: 8,
    fontSize: 11.5,
    color: colors.textSecondary,
    fontVariantNumeric: "tabular-nums",
  },
  pagerRange: {
    marginRight: 6,
  },
} as const satisfies Record<string, CSSProperties>;

const SKELETON_ROWS = 3;
const STATS = 4;

function Stat({ label, value, sub, first }: { label: string; value: string; sub?: string; first?: boolean }) {
  return (
    <div style={{ ...styles.stat, ...(first ? styles.statFirst : undefined) }}>
      <dt style={styles.statLabel}>{label}</dt>
      <dd style={styles.statFigure}>
        <span style={styles.statValue}>{value}</span>
        {sub && <span style={styles.statSub}>{sub}</span>}
      </dd>
    </div>
  );
}
/** Searches shown at once; the pager steps through any remaining rows */
export const SEARCHES_PER_PAGE = 10;
/** Variant IDs shown in a search's row before the rest are summarized as "+N more". */
const PREVIEW_VARIANTS = 2;

/** "since 3:12 PM" today, or "since Oct 14, 3:12 PM" on another day. */
export function describeSince(iso: string, now = new Date()): string {
  const since = new Date(iso);
  const sameDay =
    since.getFullYear() === now.getFullYear() && since.getMonth() === now.getMonth() && since.getDate() === now.getDate();
  const time = since.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return sameDay ? `since ${time}` : `since ${since.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
}

/** Slot time as the console shows it: milliseconds below a second, then seconds or minutes. */
export function formatSlotTime(milliseconds: number): string {
  if (milliseconds < 1000) return `${formatInt(milliseconds)} ms`;
  const seconds = milliseconds / 1000;
  if (seconds < 60) return `${seconds.toLocaleString("en-US", { maximumFractionDigits: 1 })} s`;
  return `${(seconds / 60).toLocaleString("en-US", { maximumFractionDigits: 1 })} min`;
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
/**
 * A query's time, to the second, without the AM or PM its request's row already says: "11:14:13"
 * is no wider than "11:14 AM", so opening a request doesn't widen the column.
 */
const clockSeconds = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" }).replace(/\s?[AP]M$/, "");

function previewVariants(variants: string[]): string {
  const shown = variants.slice(0, PREVIEW_VARIANTS).join(", ");
  const rest = variants.length - PREVIEW_VARIANTS;
  return rest > 0 ? `${shown} +${rest} more` : shown;
}

/** A request's slot time: the sum over its queries, which the API doesn't total itself. */
const slotTime = (search: SearchUsage) => search.queries.reduce((total, job) => total + job.slotMilliseconds, 0);

/** "cached" when every query came from the cache, else "billed". */
function CostTag({ search }: { search: SearchUsage }) {
  const cached = search.queries.length > 0 && search.cacheHits === search.queries.length;
  return (
    <span style={{ ...styles.tag, ...(cached ? styles.tagCached : styles.tagBilled) }}>{cached ? "cached" : "billed"}</span>
  );
}

export default function UsagePanel() {
  const [usage, setUsage] = useState<QueryUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Which searches are open, by id. All start closed.
  const [open, setOpen] = useState<Set<number>>(new Set());
  // Zero-based; clamped below so a refresh that shortens the log can't leave it past the end.
  const [page, setPage] = useState(0);
  const { hoveredKey, hoverProps } = useHoveredKey<number>();

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchQueryUsage()
      .then(setUsage)
      .catch((err: unknown) => setError(`Couldn't reach the backend: ${describeError(err)}`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const pageCount = usage ? Math.max(1, Math.ceil(usage.searches.length / SEARCHES_PER_PAGE)) : 1;
  const currentPage = Math.min(page, pageCount - 1);
  const first = currentPage * SEARCHES_PER_PAGE;
  const shown = usage ? usage.searches.slice(first, first + SEARCHES_PER_PAGE) : [];

  function toggle(id: number) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <>
      <div style={styles.heading}>
        <p style={{ ...Style.elements.panelIntro, margin: 0 }}>
          What this VIA instance has spent on BigQuery since it started.
        </p>
        <Clickable
          style={{ ...Style.buttons.accent, flexShrink: 0 }}
          hoverStyle={Style.buttons.accentHover}
          disabledStyle={Style.buttons.disabled}
          onClick={load}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </Clickable>
      </div>

      {error ? (
        <div role="alert" style={Style.elements.errorNote}>
          {error}
        </div>
      ) : loading || !usage ? (
        <>
          <div style={styles.strip} aria-busy="true">
            {Array.from({ length: STATS }, (_, index) => (
              <div key={index} style={{ ...styles.stat, ...(index === 0 ? styles.statFirst : undefined) }}>
                <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: 72, height: 22 }} />
                <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: 48, height: 10 }} />
              </div>
            ))}
          </div>
          <div style={styles.caption}>
            <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: 120, height: 10 }} />
          </div>
          <div style={styles.frame} aria-busy="true">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
              <div key={index} style={{ ...styles.skeletonRow, ...(index === 0 ? { borderTop: "none" } : undefined) }}>
                <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: `${70 - index * 8}%` }} />
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          <dl role="group" style={styles.strip} aria-label="This session's totals">
            <Stat first label="Billed" value={formatBytes(usage.bytesBilled)} />
            <Stat label="Est. cost" value={formatUsd(usage.estimatedCostUsd)} sub="on-demand" />
            <Stat label="Queries" value={formatInt(usage.queries)} sub={`${formatInt(usage.cacheHits)} from cache`} />
            <Stat label="Slot time" value={formatSlotTime(usage.slotMilliseconds)} />
          </dl>
          <div style={styles.caption}>
            <span style={styles.captionTitle}>Recent requests</span>
            <span>Searches and phenotype lookups {describeSince(usage.since)}, newest first</span>
          </div>
          {usage.searches.length === 0 ? (
            <div style={{ ...styles.frame, ...styles.empty }}>Nothing has queried BigQuery yet this session.</div>
          ) : (
            <div style={styles.frame}>
              <table style={styles.table} aria-label="Requests this session, newest first">
                <thead>
                  <tr>
                    <th style={{ ...styles.head, ...styles.toggleCell }} />
                    <th style={styles.head}>Time</th>
                    <th style={styles.head}>Request</th>
                    <th style={styles.head}>Phenotype</th>
                    <th style={{ ...styles.head, ...styles.cellRight }}>Queries</th>
                    <th style={{ ...styles.head, ...styles.cellRight }}>Read</th>
                    <th style={{ ...styles.head, ...styles.cellRight }}>Billed</th>
                    <th style={{ ...styles.head, ...styles.cellRight }}>Slot time</th>
                    <th style={{ ...styles.head, ...styles.cellRight }}>Cost</th>
                    <th style={styles.head} />
                  </tr>
                </thead>
                {shown.map((search, index) => {
                  const expanded = open.has(search.id);
                  const jobsId = `usage-search-${search.id}-queries`;
                  const cell = (extra?: CSSProperties): CSSProperties => ({
                    ...styles.cell,
                    ...(index === 0 ? { borderTop: "none" } : undefined),
                    ...extra,
                  });
                  const right = { ...styles.cellRight };
                  return (
                    <Fragment key={search.id}>
                      <tbody>
                        <tr
                          onClick={() => toggle(search.id)}
                          {...hoverProps(search.id)}
                          style={{ ...styles.request, ...(hoveredKey === search.id ? styles.requestHovered : undefined) }}
                        >
                          <td style={cell(styles.toggleCell)}>
                            <button
                              type="button"
                              style={styles.toggle}
                              aria-expanded={expanded}
                              aria-controls={expanded ? jobsId : undefined}
                              aria-label={`${expanded ? "Hide" : "Show"} queries for request ${search.id}`}
                            >
                              {expanded ? (
                                <ChevronDownIcon size={12} aria-hidden="true" />
                              ) : (
                                <ChevronRightIcon size={12} aria-hidden="true" />
                              )}
                            </button>
                          </td>
                          <td style={cell(styles.time)}>{clock(search.at)}</td>
                          <td style={cell()}>
                            {search.kind === "condition" ? (
                              <span style={styles.lookup}>
                                Condition lookup <span style={styles.lookupTerm}>“{search.term}”</span>
                              </span>
                            ) : (
                              <span style={styles.variants} title={search.variants.join("\n")}>
                                {previewVariants(search.variants)}
                              </span>
                            )}
                          </td>
                          <td style={cell()}>
                            {search.phenotypes.length > 0 ? (
                              search.phenotypes.map((phenotype, phenotypeIndex) => (
                                <span
                                  key={phenotype}
                                  style={{ ...styles.phenotype, ...(phenotypeIndex > 0 ? styles.phenotypeNext : undefined) }}
                                  title={describeAlternatives(search.phenotypes)}
                                >
                                  <UserIcon size={11} aria-hidden="true" />
                                  {phenotype}
                                </span>
                              ))
                            ) : (
                              <span style={styles.none} aria-label={search.kind === "condition" ? "Not a search" : "No phenotype"}>
                                —
                              </span>
                            )}
                          </td>
                          <td style={cell(right)}>{formatInt(search.queries.length)}</td>
                          <td style={cell(right)}>{formatBytes(search.bytesProcessed)}</td>
                          <td style={cell(right)}>{formatBytes(search.bytesBilled)}</td>
                          <td style={cell(right)}>{formatSlotTime(slotTime(search))}</td>
                          <td style={cell({ ...right, ...styles.cost })}>{formatUsd(search.estimatedCostUsd)}</td>
                          <td style={cell()}>
                            <CostTag search={search} />
                          </td>
                        </tr>
                      </tbody>
                      {expanded && (
                        <tbody id={jobsId} aria-label={`Queries run by request ${search.id}`}>
                          {search.queries.map((job, jobIndex) => (
                            <tr key={jobIndex}>
                              <td style={{ ...styles.queryCell, ...styles.toggleCell }} />
                              <td style={{ ...styles.queryCell, ...styles.time }}>{clockSeconds(job.at)}</td>
                              <td style={{ ...styles.queryCell, ...styles.queryName }}>{job.name}</td>
                              <td style={styles.queryCell} />
                              <td style={styles.queryCell} />
                              <td style={{ ...styles.queryCell, ...right }}>{formatBytes(job.bytesProcessed)}</td>
                              <td style={{ ...styles.queryCell, ...right }}>{formatBytes(job.bytesBilled)}</td>
                              <td style={{ ...styles.queryCell, ...right }}>{formatSlotTime(job.slotMilliseconds)}</td>
                              <td style={styles.queryCell} />
                              <td style={styles.queryCell}>
                                <span style={{ ...styles.tag, ...(job.cacheHit ? styles.tagCached : styles.tagBilled) }}>
                                  {job.cacheHit ? "cache" : "billed"}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      )}
                    </Fragment>
                  );
                })}
              </table>
            </div>
          )}
          {usage.searches.length > SEARCHES_PER_PAGE && (
            <nav style={styles.pager} aria-label="Requests, by page">
              <span style={styles.pagerRange}>
                {first + 1}–{first + shown.length} of {usage.searches.length}
              </span>
              <Clickable
                style={Style.buttons.icon}
                hoverStyle={Style.buttons.iconHover}
                disabledStyle={Style.buttons.disabled}
                onClick={() => setPage(currentPage - 1)}
                disabled={currentPage === 0}
                aria-label="Newer requests"
                title="Newer requests"
              >
                <ArrowLeftIcon size={14} aria-hidden="true" />
              </Clickable>
              <Clickable
                style={Style.buttons.icon}
                hoverStyle={Style.buttons.iconHover}
                disabledStyle={Style.buttons.disabled}
                onClick={() => setPage(currentPage + 1)}
                disabled={currentPage >= pageCount - 1}
                aria-label="Older requests"
                title="Older requests"
              >
                <ArrowRightIcon size={14} aria-hidden="true" />
              </Clickable>
            </nav>
          )}
        </>
      )}
    </>
  );
}
