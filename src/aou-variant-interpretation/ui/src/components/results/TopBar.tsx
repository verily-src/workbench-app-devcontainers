import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";
import { fetchQueryUsage, type QueryUsage } from "../../api/usage";
import colors, { alpha } from "../../libs/colors";
import { useHover, useMediaQuery } from "../../libs/hooks";
import * as Style from "../../libs/style";
import Clickable from "../common/Clickable";
import { GaugeIcon, PencilIcon, SearchIcon, UserIcon } from "../icons";
import AppMenu from "../shell/AppMenu";
import { formatBytes, formatUsd } from "../../utils/format";
import { describeAlternatives } from "../../utils/phenotypes";
import { usePreference } from "../../utils/preferences";

/** Exported for what has to sit just below the bar, e.g. the edit-search popover's backdrop. */
export const TOP_BAR_HEIGHT = 41;

// Below this width the bar's contents are compressed to fit
const COMPACT_QUERY = "(max-width: 860px)";

/** How often the usage meter re-reads the backend's total (if it's shown). */
export const USAGE_REFRESH_MS = 60_000;

const styles = {
  topbar: {
    position: "sticky",
    top: 0,
    zIndex: 50,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    height: TOP_BAR_HEIGHT,
    padding: "0 20px",
    background: colors.surface2,
    borderBottom: `1px solid ${colors.border}`,
    color: colors.textSecondary,
    fontSize: 12,
  },
  // The hamburger, the mark and name, then (on the results page) the search box.
  leading: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    flex: 1,
    minWidth: 0,
    marginRight: 20,
  },
  brand: {
    display: "inline-flex",
    alignItems: "center",
    flexShrink: 0,
    gap: 7,
    margin: "-4px -6px",
    padding: "4px 6px",
    borderRadius: 6,
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: 800,
    letterSpacing: 0.3,
    textDecoration: "none",
  },
  /** Matches the menu button's (Style.buttons.iconHover). */
  brandHover: {
    ...Style.buttons.iconHover,
  },
  /**
   * On the results page, the rule between the brand and the search box. Its own element, not a
   * border on the brand, so the brand's hover fill doesn't run up against it.
   */
  brandDivider: {
    flexShrink: 0,
    width: 1,
    height: 22,
    background: colors.border,
  },
  brandMark: {
    display: "block",
  },
  // The current terms as a row of labelled cells; clicking anywhere in it opens the drawer.
  // Positioning context for the edit-search popover, which hangs from the box's left edge.
  searchAnchor: {
    position: "relative",
    display: "flex",
    flex: 1,
    minWidth: 0,
    maxWidth: 575,
  },
  /**
   * A box squared to the inputs' radius, only as wide as its cells, which hairlines divide. The
   * cells stretch to its height so the edit cell's fill runs edge to edge. Page-coloured against
   * the white bar, so it reads as a field; goes white while the drawer is open, via inputs.focused.
   */
  searchBox: {
    ...Style.inputs.text,
    display: "inline-flex",
    alignItems: "stretch",
    width: "auto",
    minWidth: 0,
    height: 29,
    padding: 0,
    overflow: "hidden",
    background: colors.surface0,
    color: colors.textSecondary,
    textAlign: "left",
    cursor: "pointer",
  },
  searchBoxHover: {
    borderColor: colors.borderHover,
  },
  searchTerms: {
    display: "flex",
    alignItems: "stretch",
    minWidth: 0,
    overflow: "hidden",
  },
  /** A label and its value: "VARIANTS 3", "PHENOTYPE Seizure". */
  cell: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    minWidth: 0,
    padding: "0 11px",
    whiteSpace: "nowrap",
  },
  /** The variant count is short and always worth showing whole; the phenotype name gives way. */
  cellFixed: {
    flexShrink: 0,
  },
  /** Every cell after the first is set off by a hairline. */
  cellRuled: {
    borderLeft: `1px solid ${colors.border}`,
  },
  searchIcon: {
    flexShrink: 0,
    color: colors.textMuted,
  },
  cellLabel: {
    ...Style.elements.eyebrow,
    letterSpacing: 0.6,
  },
  cellValue: {
    maxWidth: 240,
    overflow: "hidden",
    textOverflow: "ellipsis",
    color: colors.textAccent,
    fontSize: 12,
    fontWeight: 600,
  },
  skeletonBadge: {
    display: "inline-block",
    width: 72,
    height: 14,
    borderRadius: 4,
    background: colors.border,
  },
  /** The pencil in its own cell at the end, tinted a step past the box so it reads as the control it is. */
  editCell: {
    display: "inline-flex",
    alignItems: "center",
    flexShrink: 0,
    padding: "0 9px",
    background: alpha(colors.textAccent, 0.07),
    color: colors.textAccent,
  },
  editCellHover: {
    background: colors.bgAccent,
  },
  user: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginLeft: "auto",
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: 500,
  },
  userIcon: {
    flexShrink: 0,
    color: colors.textAccent,
  },
  meter: {
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
    padding: "3px 8px",
    borderRadius: 999,
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: 600,
    fontVariantNumeric: "tabular-nums",
    textDecoration: "none",
    whiteSpace: "nowrap",
  },
  meterHover: {
    background: colors.bgAccent,
    color: colors.textAccent,
  },
  meterIcon: {
    flexShrink: 0,
    color: colors.textAccent,
  },
  meterDot: {
    color: colors.textMuted,
    fontWeight: 400,
  },
  /** Same rule as the brand divider, between the meter and the email. */
  userDivider: {
    width: 1,
    height: 16,
    margin: "0 8px",
    background: colors.border,
  },
} as const satisfies Record<string, CSSProperties>;

/**
 * The phenotype badge is 240px wide at most. Up to about this many characters of 12px text fit
 * in it, so a short list is shown whole and a long one as its first name and how many more.
 */
const BADGE_CHARS = 34;

/** What the badge says for the picked conditions, and the full list for its tooltip. */
export function describePhenotypeBadge(phenotypes: string[]): { label: string; title: string | undefined } {
  if (phenotypes.length === 0) return { label: "None entered", title: undefined };
  const full = describeAlternatives(phenotypes);
  if (phenotypes.length === 1 || full.length <= BADGE_CHARS) return { label: full, title: full };
  return { label: `${phenotypes[0]} +${phenotypes.length - 1} more`, title: full };
}

const compactStyles = {
  topbar: { padding: "0 12px" },
  leading: { gap: 10, marginRight: 10 },
  cell: { padding: "0 9px" },
  userDivider: { margin: "0 4px" },
} as const satisfies Record<string, CSSProperties>;

interface TopBarProps {
  loading?: boolean;
  variantsEnteredCount?: number;
  /** The picked conditions' names, in the order they were picked. */
  phenotypes?: string[];
  userEmail: string;
  onModifySearch?: () => void;
  /** Whether the edit-search popover is open, which the search box shows as focused. */
  modifyOpen?: boolean;
  /** The edit-search popover (SearchPopover), anchored under the search box. */
  editSearchPanel?: ReactNode;
}

export default function TopBar({
  loading,
  variantsEnteredCount,
  phenotypes = [],
  userEmail,
  onModifySearch,
  modifyOpen = false,
  editSearchPanel,
}: TopBarProps) {
  const [usage, setUsage] = useState<QueryUsage | null>(null);
  const { hovered: brandHovered, hoverProps: brandHoverProps } = useHover();
  const { hovered: meterHovered, hoverProps: meterHoverProps } = useHover();
  const { hovered: searchHovered, hoverProps: searchHoverProps } = useHover();
  const termsId = useId();
  const compact = useMediaQuery(COMPACT_QUERY);
  const compactStyle = (key: keyof typeof compactStyles) => (compact ? compactStyles[key] : undefined);
  const fieldLabel = compact ? Style.elements.visuallyHidden : styles.cellLabel;
  const hidePhenotype = compact && !loading && phenotypes.length === 0;
  const badge = describePhenotypeBadge(phenotypes);
  const searchBoxRef = useRef<HTMLButtonElement>(null);

  // When the edit-search popover closes, hand focus back to the box that opened it; otherwise it
  // stays on a field that's now hidden.
  const wasModifyOpen = useRef(modifyOpen);
  useEffect(() => {
    if (wasModifyOpen.current && !modifyOpen) searchBoxRef.current?.focus();
    wasModifyOpen.current = modifyOpen;
  }, [modifyOpen]);

  // The meter is opt-in, from the Usage page. While it's on it reads the backend's running total
  // when switched on or mounted, each time a search finishes loading (a search is what moves it),
  // and otherwise every minute. Reads can overlap, so only the newest one's reply is kept. If it
  // can't be read the meter stays off the bar; the Usage page is where that failure is explained.
  const [showMeter] = usePreference("showUsageMeter");
  const usageRead = useRef(0);
  const readUsage = useCallback(() => {
    const read = ++usageRead.current;
    fetchQueryUsage()
      .then((next) => {
        if (read === usageRead.current) setUsage(next);
      })
      .catch(() => {
        // Stale figures would look authoritative exactly when the backend is unreachable.
        if (read === usageRead.current) setUsage(null);
      });
  }, []);
  useEffect(() => {
    if (!showMeter || loading) return;
    readUsage();
    const timer = window.setInterval(readUsage, USAGE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [showMeter, loading, readUsage]);

  const meter =
    showMeter && usage
      ? {
          scanned: formatBytes(usage.bytesProcessed),
          billed: formatBytes(usage.bytesBilled),
          cost: formatUsd(usage.estimatedCostUsd),
        }
      : null;

  return (
    <div style={{ ...styles.topbar, ...compactStyle("topbar") }}>
      <div style={{ ...styles.leading, ...compactStyle("leading") }}>
        <AppMenu />
        <Link
          to="/"
          style={{
            ...styles.brand,
            ...(brandHovered ? styles.brandHover : undefined),
          }}
          aria-label="VIA home, new search"
          {...brandHoverProps}
        >
          <img src="/favicon.svg" alt="" width={22} height={22} style={styles.brandMark} />
          VIA
        </Link>
        {onModifySearch && <span style={styles.brandDivider} aria-hidden="true" />}
        {onModifySearch && (
          <div style={styles.searchAnchor}>
            <Clickable
              ref={searchBoxRef}
              style={{
                ...styles.searchBox,
                ...(searchHovered && !loading ? styles.searchBoxHover : undefined),
                ...(modifyOpen ? Style.inputs.focused : undefined),
              }}
              disabledStyle={{ cursor: "default" }}
              onClick={onModifySearch}
              disabled={loading}
              aria-label="Edit search"
              aria-describedby={termsId}
              aria-expanded={modifyOpen}
              {...searchHoverProps}
            >
              <span id={termsId} style={styles.searchTerms}>
                <span style={{ ...styles.cell, ...compactStyle("cell"), ...styles.cellFixed }}>
                  <SearchIcon size={14} style={styles.searchIcon} aria-hidden="true" />
                  <span style={fieldLabel}>Variants</span>
                  {loading ? (
                    <span className="animate-skeleton-pulse" style={styles.skeletonBadge} />
                  ) : (
                    <span style={styles.cellValue}>
                      {/* The label says what the number counts; without it (compact) the value has to. */}
                      {compact
                        ? `${variantsEnteredCount} variant${variantsEnteredCount === 1 ? "" : "s"}`
                        : variantsEnteredCount}
                    </span>
                  )}
                </span>
                <span
                  style={
                    hidePhenotype
                      ? Style.elements.visuallyHidden
                      : { ...styles.cell, ...compactStyle("cell"), ...styles.cellRuled }
                  }
                >
                  <span style={fieldLabel}>Phenotype</span>
                  {loading ? (
                    <span className="animate-skeleton-pulse" style={styles.skeletonBadge} />
                  ) : (
                    <span style={styles.cellValue} title={badge.title}>
                      {badge.label}
                    </span>
                  )}
                </span>
              </span>
              {!loading && (
                <span
                  style={{
                    ...styles.editCell,
                    ...styles.cellRuled,
                    ...(searchHovered ? styles.editCellHover : undefined),
                  }}
                  aria-hidden="true"
                >
                  <PencilIcon size={12} />
                </span>
              )}
            </Clickable>
            {editSearchPanel}
          </div>
        )}
      </div>
      <div style={styles.user}>
        {meter && (
          <>
            <Link
              to="/usage"
              style={{ ...styles.meter, ...(meterHovered ? styles.meterHover : undefined) }}
              aria-label={`BigQuery usage this session: ${meter.scanned} scanned, ${meter.billed} billed, ${meter.cost} estimated. Open usage details`}
              title={`BigQuery this session: ${meter.scanned} scanned · ${meter.billed} billed · ${meter.cost} estimated`}
              {...meterHoverProps}
            >
              <GaugeIcon size={14} style={styles.meterIcon} aria-hidden="true" />
              {compact ? (
                <span>{meter.cost}</span>
              ) : (
                <>
                  <span>{meter.scanned}</span>
                  <span style={styles.meterDot} aria-hidden="true">·</span>
                  <span>{meter.billed}</span>
                  <span style={styles.meterDot} aria-hidden="true">·</span>
                  <span>{meter.cost}</span>
                </>
              )}
            </Link>
            <span style={{ ...styles.userDivider, ...compactStyle("userDivider") }} aria-hidden="true" />
          </>
        )}
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }} title={compact ? userEmail : undefined}>
          <UserIcon size={16} style={styles.userIcon} />
          <span style={compact ? Style.elements.visuallyHidden : undefined}>{userEmail}</span>
        </span>
      </div>
    </div>
  );
}
