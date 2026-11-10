import { useRef } from "react";
import type { CSSProperties } from "react";
import colors, { alpha } from "../../libs/colors";
import type { ClinVarSignificance } from "../../types/results";
import { CLINVAR_BADGE_CONFIG, CLINVAR_MAX_STARS, clinvarReviewDescription } from "../../utils/clinvar";
import { useTooltip } from "../common/useTooltip";

/** Split badges share one width, so a column of them lines up. */
const SPLIT_WIDTH = 68;
/** The code's slot, wide enough for "VUS" with a little air, with the code centered in it. */
const SPLIT_CODE_WIDTH = 30;

const styles = {
  badge: {
    display: "inline-flex",
    alignItems: "center",
    padding: "2px 8px",
    borderRadius: 999,
    fontSize: 11,
    fontWeight: 600,
    lineHeight: 1.2,
    whiteSpace: "nowrap",
  },
  split: {
    boxSizing: "border-box",
    width: SPLIT_WIDTH,
    padding: "2px 7px 2px 4px",
  },
  splitCode: {
    width: SPLIT_CODE_WIDTH,
    flexShrink: 0,
    textAlign: "center",
  },
  stars: {
    paddingLeft: 6,
    fontWeight: 500,
    color: colors.textSecondary,
  },
  // As a link the pill keeps its look and gains a pointer; the border firms up under it.
  link: {
    textDecoration: "none",
    cursor: "pointer",
    transition: "border-color 0.12s ease",
  },
} as const satisfies Record<string, CSSProperties>;

interface ClinvarBadgeProps {
  significance: ClinVarSignificance;
  /** ClinVar's 0–4 review stars; omitted from the badge when null. */
  stars?: number | null;
  /** "split" shows the short code (P, LP, VUS…) for table cells; "tag" spells the classification out. */
  mode?: "split" | "tag";
  /** Whether ClinVar's submissions conflict, which changes what one review star means. */
  conflicts?: boolean;
  /**
   * The variant's ClinVar page. Given, the badge is a link to it, opening in a new tab, with the
   * app's tooltip explaining the classification and review status on hover or focus.
   */
  href?: string;
}

export default function ClinvarBadge({ significance, stars = null, mode = "split", conflicts = false, href }: ClinvarBadgeProps) {
  const config = CLINVAR_BADGE_CONFIG[significance];
  const label = mode === "tag" ? significance : config.shortLabel;
  const ref = useRef<HTMLAnchorElement>(null);
  const review = stars !== null ? `${stars} of ${CLINVAR_MAX_STARS} stars: ${clinvarReviewDescription(stars, conflicts)}` : null;
  const description = `ClinVar: ${significance}${review ? `, ${review}` : ""}`;

  const tooltip = useTooltip(
    ref,
    [significance, review, "Click to open ClinVar in a new tab."].filter((line) => line !== null).join("\n"),
    "right",
  );

  const style: CSSProperties = {
    ...styles.badge,
    ...(mode === "split" ? styles.split : undefined),
    background: config.fill,
    border: `1px solid ${alpha(config.ink, href && tooltip.hovered ? 0.7 : 0.35)}`,
    color: config.ink,
    ...(href ? styles.link : undefined),
  };
  const content = (
    <>
      <span style={mode === "split" ? styles.splitCode : undefined}>{label}</span>
      {stars !== null && (
        <span style={{ ...styles.stars, borderLeft: `1px solid ${alpha(config.ink, 0.3)}` }}>{`${stars}★`}</span>
      )}
    </>
  );

  if (!href) {
    return (
      <span style={style} title={description}>
        {content}
      </span>
    );
  }
  return (
    <a
      ref={ref}
      style={style}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      // An element with no title shows its nearest ancestor's (ReviewDetail's Fact has one), which
      // would sit on top of the app's tooltip; an empty title opts out.
      title=""
      // Names the context change for screen readers, since the visible bubble is aria-hidden.
      aria-label={`${description}. Open in ClinVar (opens in new tab)`}
      {...tooltip.anchorProps}
      // A click follows the link; it shouldn't also expand the table row underneath, or re-show
      // the tooltip the way the hook's own click handler would.
      onClick={(event) => event.stopPropagation()}
    >
      {content}
      {tooltip.bubble}
    </a>
  );
}
