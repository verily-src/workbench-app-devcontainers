import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import colors, { alpha } from "../../libs/colors";
import { useHoveredKey } from "../../libs/hooks";
import * as Style from "../../libs/style";
import type { BreakdownSegment, CohortVariantRow, FilteredVariantRow } from "../../types/results";
import { buildComparisonRows, sortByEnrichment } from "../../utils/comparison";
import { formatRatio } from "../../utils/format";
import type { Enrichment } from "../../utils/statistics";
import Clickable from "../common/Clickable";
import { ArrowLeftIcon, ArrowRightIcon } from "../icons";
import ResultsPanel from "./ResultsPanel";
import ReviewDetail from "./ReviewDetail";
import VerdictGlyph from "./VerdictGlyph";
import { verdictTone } from "./verdictTone";

// The rail's height follows the detail's: it's absolutely positioned inside its grid cell, so a
// long candidate list scrolls within the rail instead of stretching the page.
const RAIL_WIDTH = 260;

const styles = {
  stepper: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  position: {
    ...Style.elements.mono,
    minWidth: 52,
    textAlign: "center",
    fontSize: 12,
    color: colors.textSecondary,
  },
  body: {
    display: "grid",
    gridTemplateColumns: `${RAIL_WIDTH}px minmax(0, 1fr)`,
    minHeight: 520,
  },
  railCell: {
    position: "relative",
    background: colors.surface1,
    borderRight: `1px solid ${colors.border}`,
  },
  rail: {
    position: "absolute",
    inset: 0,
    display: "flex",
    flexDirection: "column",
  },
  railList: {
    flex: 1,
    margin: 0,
    padding: "6px 8px 10px",
    listStyle: "none",
    overflowY: "auto",
    scrollbarWidth: "thin",
  },
  // A group's label: what its verdicts have in common, and how many there are.
  railGroup: {
    ...Style.elements.eyebrow,
    display: "flex",
    justifyContent: "space-between",
    padding: "12px 8px 6px",
  },
  railGroupCount: {
    fontVariantNumeric: "tabular-nums",
  },
  railItem: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    width: "100%",
    padding: "7px 8px",
    // Longhands, so the selected entry's borderColor is restored rather than dropped when the
    // selection moves on (see stateBorder).
    ...Style.stateBorder("transparent"),
    borderRadius: Style.radius,
    background: "none",
    textAlign: "left",
    cursor: "pointer",
  },
  railItemHovered: {
    background: colors.surface0,
  },
  // The open variant lifts off the rail as a white card outlined in the accent, the way a focused
  // field is; its glyph goes solid too (see VerdictGlyph's `solid`). Its halo spills a few pixels
  // into the entries either side, so it's raised above them: otherwise a hovered neighbour's
  // background, painted later, covers the halo.
  railItemSelected: {
    position: "relative",
    zIndex: 1,
    background: colors.surface2,
    borderColor: alpha(colors.textAccent, 0.55),
    boxShadow: `0 0 0 3px ${alpha(colors.textAccent, 0.12)}, ${Style.shadows.pill}`,
  },
  railText: {
    display: "flex",
    flexDirection: "column",
    gap: 1,
    flex: 1,
    minWidth: 0,
  },
  railGene: {
    fontSize: 12.5,
    fontWeight: 600,
    color: colors.textPrimary,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  railVariant: {
    ...Style.elements.mono,
    fontSize: 10.5,
    color: colors.textMuted,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  // Quiet, in body ink: the glyph already carries the direction and its colour.
  railRatio: {
    flexShrink: 0,
    fontSize: 12,
    fontWeight: 600,
    fontVariantNumeric: "tabular-nums",
    color: colors.textSecondary,
  },
  detail: {
    minWidth: 0,
    padding: "22px 28px 26px",
  },
} as const satisfies Record<string, CSSProperties>;

/**
 * The rail's groups, in the order sortByEnrichment already puts them: supported departures (either
 * direction) first, then similar, then too few alleles, then nothing to compare. The glyph on each
 * entry gives its direction, so the groups replace a legend.
 */
function railGroup(enrichment: Enrichment | null): string {
  if (!enrichment) return "No comparison";
  if (enrichment.verdict === "similar") return "Similar frequency";
  if (enrichment.verdict === "inconclusive") return "Too few alleles";
  return "Departs from cohort-wide";
}

/** Marks the rail and the stepper: the arrow-key shortcut applies to their buttons too. */
const SHORTCUT_SCOPE_ATTRIBUTE = "data-review-shortcuts";
/** Anything with its own keyboard behaviour, which the shortcut must not override. */
const INTERACTIVE_SELECTOR =
  'input, textarea, select, button, a[href], [contenteditable], [role="button"], [role="listbox"], [role="option"], [role="menu"], [role="menuitem"], [role="dialog"], [tabindex]';

interface ReviewViewProps {
  cohortVariants: CohortVariantRow[];
  filteredVariants: FilteredVariantRow[];
  /** The picked conditions' names; the matched participants have any of them. */
  phenotypes: string[];
  participantCount: number;
  ancestryBreakdown: BreakdownSegment[];
  /** Which variant to open on; the best-supported signal when omitted or unknown. */
  initialVariant?: string;
}

/**
 * Review: the two cohorts head to head, one variant at a time, shown in place of the table when
 * the summary strip's switcher is on Review. A rail on the left ranks the candidates by how well
 * the interval supports a departure from cohort-wide; the detail on the right states the verdict,
 * the evidence behind it, and how the matched cohort's ancestry makeup bears on it. Arrow keys
 * step through the rail.
 */
export default function ReviewView({
  cohortVariants,
  filteredVariants,
  phenotypes,
  participantCount,
  ancestryBreakdown,
  initialVariant,
}: ReviewViewProps) {
  const rows = useMemo(
    () => sortByEnrichment(buildComparisonRows(cohortVariants, filteredVariants, ancestryBreakdown)),
    [cohortVariants, filteredVariants, ancestryBreakdown],
  );
  const [index, setIndex] = useState(() => Math.max(0, rows.findIndex((row) => row.variant === initialVariant)));
  const { hoveredKey, hoverProps } = useHoveredKey<string>();
  const railRef = useRef<HTMLOListElement>(null);
  const selected = rows[index] ?? null;
  // Bonferroni divides by the tests actually run. A variant not in All of Us, or one without
  // matched statistics, has no comparison and so no test; it doesn't count against the others.
  const testedCount = rows.filter((row) => row.enrichment !== null).length;

  // Arrow keys step through the rail. The listener is on the document so the keys work with
  // nothing focused, but it leaves other controls alone: a key pressed on a field, a link, a
  // button outside the rail and stepper, or editable text means what it normally means there.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowDown" && event.key !== "ArrowLeft" && event.key !== "ArrowUp") return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target && !target.closest(`[${SHORTCUT_SCOPE_ATTRIBUTE}]`) && (target.isContentEditable || target.closest(INTERACTIVE_SELECTOR))) {
        return;
      }
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        setIndex((i) => Math.min(rows.length - 1, i + 1));
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        setIndex((i) => Math.max(0, i - 1));
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [rows.length]);

  // Keep the selected rail entry in view as the arrow keys move through a long list. If focus is
  // already in the rail (an entry was clicked), it follows the selection, so the focus ring
  // doesn't stay behind on an entry that's no longer open.
  useEffect(() => {
    const entry = railRef.current?.querySelector<HTMLElement>(`[data-rail-index="${index}"]`);
    if (!entry) return;
    if (railRef.current!.contains(document.activeElement) && document.activeElement !== entry) {
      entry.focus({ preventScroll: true });
    }
    entry.scrollIntoView?.({ block: "nearest" });
  }, [index]);

  const stepper = (
    <div style={styles.stepper} {...{ [SHORTCUT_SCOPE_ATTRIBUTE]: "" }}>
      <Clickable
        style={Style.buttons.icon}
        hoverStyle={Style.buttons.iconHover}
        disabledStyle={Style.buttons.disabled}
        onClick={() => setIndex((i) => Math.max(0, i - 1))}
        disabled={index <= 0}
        aria-label="Previous variant"
        title="Previous variant (←)"
      >
        <ArrowLeftIcon size={14} aria-hidden="true" />
      </Clickable>
      <span style={styles.position} aria-live="polite">
        {rows.length === 0 ? "0 of 0" : `${index + 1} of ${rows.length}`}
      </span>
      <Clickable
        style={Style.buttons.icon}
        hoverStyle={Style.buttons.iconHover}
        disabledStyle={Style.buttons.disabled}
        onClick={() => setIndex((i) => Math.min(rows.length - 1, i + 1))}
        disabled={index >= rows.length - 1}
        aria-label="Next variant"
        title="Next variant (→)"
      >
        <ArrowRightIcon size={14} aria-hidden="true" />
      </Clickable>
    </div>
  );

  return (
    <ResultsPanel
      title="Review"
      headerRight={stepper}
    >
      <div style={styles.body}>
        <div style={styles.railCell}>
          <nav style={styles.rail} aria-label="Candidate variants, best-supported first" {...{ [SHORTCUT_SCOPE_ATTRIBUTE]: "" }}>
            <ol ref={railRef} style={styles.railList}>
              {rows.map((row, i) => {
                const tone = verdictTone(row.enrichment);
                const group = railGroup(row.enrichment);
                const startsGroup = i === 0 || railGroup(rows[i - 1].enrichment) !== group;
                // An inconclusive point estimate isn't a finding, so it isn't shown as one.
                const showRatio = row.enrichment && row.enrichment.verdict !== "inconclusive";
                return (
                  <li key={row.variant}>
                    {startsGroup && (
                      <div style={styles.railGroup} aria-hidden="true">
                        <span>{group}</span>
                        <span style={styles.railGroupCount}>
                          {rows.filter((other) => railGroup(other.enrichment) === group).length}
                        </span>
                      </div>
                    )}
                    <button
                      type="button"
                      data-rail-index={i}
                      aria-current={i === index ? "true" : undefined}
                      title={tone.rule ? `${tone.word}: ${tone.rule}` : tone.word}
                      onClick={() => setIndex(i)}
                      {...hoverProps(row.variant)}
                      style={{
                        ...styles.railItem,
                        ...(hoveredKey === row.variant && i !== index ? styles.railItemHovered : undefined),
                        ...(i === index ? styles.railItemSelected : undefined),
                      }}
                    >
                      <VerdictGlyph tone={tone} size={20} solid={i === index} />
                      <span style={styles.railText}>
                        {row.cohort && <span style={styles.railGene}>{row.cohort.gene}</span>}
                        <span style={styles.railVariant}>{row.variant}</span>
                      </span>
                      {showRatio && <span style={styles.railRatio}>{formatRatio(row.enrichment!.ratio)}</span>}
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        </div>

        <section style={styles.detail}>
          {selected ? (
            <ReviewDetail
              key={selected.variant}
              row={selected}
              phenotypes={phenotypes}
              participantCount={participantCount}
              ancestryBreakdown={ancestryBreakdown}
              candidateCount={testedCount}
            />
          ) : (
            <p style={{ color: colors.textSecondary }}>No candidate variants to review.</p>
          )}
        </section>
      </div>
    </ResultsPanel>
  );
}
