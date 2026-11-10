import { useId, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { ConditionSearch, HpoTerm } from "../../api/conditions";
import colors, { alpha } from "../../libs/colors";
import { useHover } from "../../libs/hooks";
import * as Style from "../../libs/style";
import type { BreakdownSegment } from "../../types/results";
import { conditionBreakdown } from "../../utils/conditionBreakdown";
import { hpoTermUrl } from "../../utils/externalLinks";
import { formatInt } from "../../utils/format";
import { describeHpo } from "../../utils/hpo";
import Clickable from "../common/Clickable";
import InfoTooltip from "../common/InfoTooltip";
import { useTooltip } from "../common/useTooltip";
import { ExternalLinkIcon, PlusIcon } from "../icons";
import BreakdownBar from "./BreakdownBar";
import CopyButton from "./CopyButton";
import ViewSwitcher, { type ResultsView } from "./ViewSwitcher";

const NO_TERM_NOTE = "No term in the Human Phenotype Ontology has this condition's name, or a name its words contain.";

/**
 * The chip that says a condition has no HPO term, explained by the app's tooltip on hover, focus
 * or tap. Focusable, so the keyboard reaches the explanation, and described by it for screen
 * readers without hovering.
 */
function NoHpoTermChip() {
  const ref = useRef<HTMLSpanElement>(null);
  const descriptionId = useId();
  const tooltip = useTooltip(ref, NO_TERM_NOTE);
  return (
    <span
      ref={ref}
      tabIndex={0}
      aria-describedby={descriptionId}
      style={{
        ...styles.hpoNone,
        ...(tooltip.keyboardFocused ? Style.elements.tooltipIconFocusRing : undefined),
      }}
      {...tooltip.anchorProps}
    >
      no matching term
      <span id={descriptionId} style={Style.elements.visuallyHidden}>
        {NO_TERM_NOTE}
      </span>
      {tooltip.bubble}
    </span>
  );
}

/**
 * The line under a condition's name that names its HPO term: an "HPO" eyebrow, then the term's
 * own name (always, even when it is the condition's name too, so what was matched is never left
 * to inference), then its id as the link out, styled as the picked chip's id is on the search
 * page, with a copy button. A nearest match carries "≈" ahead of its id, as the chip does, and
 * explains itself on hover; a condition with no term says so in a dashed chip.
 */
function HpoLine({ hpo }: { hpo: HpoTerm | null | undefined }) {
  const { hovered, hoverProps } = useHover();
  if (!hpo) {
    return (
      <span style={styles.hpoLine}>
        <span style={styles.hpoEyebrow} aria-hidden="true">
          HPO
        </span>
        <NoHpoTermChip />
      </span>
    );
  }
  const words = describeHpo(hpo, { link: true });
  return (
    <span style={styles.hpoLine}>
      <span style={styles.hpoEyebrow} aria-hidden="true">
        HPO
      </span>
      <span style={styles.hpoName} title={hpo.name}>
        {hpo.name}
      </span>
      <a
        href={hpoTermUrl(hpo.id)}
        target="_blank"
        rel="noopener noreferrer"
        title={words.tooltip}
        aria-label={words.spoken}
        style={{ ...styles.hpoId, ...(hovered ? styles.hpoIdHover : undefined) }}
        {...hoverProps}
      >
        {words.label}
        <ExternalLinkIcon size={11} aria-hidden="true" />
      </a>
      <CopyButton getText={() => hpo.id} label="Copy HPO term ID" />
    </span>
  );
}

const BLOCK_GAP = 20;

const styles = {
  strip: {
    ...Style.elements.panel,
    display: "grid",
    gridTemplateColumns: "auto auto minmax(0, 1fr) auto",
    alignItems: "stretch",
    padding: "10px 18px",
    boxShadow: Style.shadows.panel,
  },
  block: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    minWidth: 0,
    paddingRight: BLOCK_GAP,
  },
  blockDivided: {
    paddingLeft: BLOCK_GAP,
    borderLeft: `1px solid ${colors.border}`,
  },
  // The label row: the eyebrow, and for the breakdown its toggle, kept to one height so the
  // content rows beneath start level.
  blockLabel: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    height: 20,
  },
  eyebrow: {
    ...Style.elements.eyebrow,
    display: "inline-flex",
    alignItems: "center",
  },
  blockContent: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    minHeight: 30,
    minWidth: 0,
  },
  conditionName: {
    fontSize: 13.5,
    fontWeight: 600,
    lineHeight: 1.2,
    color: colors.textPrimary,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    maxWidth: 320,
  },
  // One condition: its name over its HPO term.
  conditionText: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    minWidth: 0,
  },
  // Several: a two-column list, each condition (its name over its HPO line) and that condition's
  // own matched count, centred against the two lines.
  conditionList: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "8px 16px",
    margin: 0,
    padding: 0,
    listStyle: "none",
    minWidth: 0,
  },
  conditionRow: {
    display: "contents",
  },
  // A condition in the list: its name, then its HPO line, stacked like the one-condition layout.
  conditionRowText: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    minWidth: 0,
    maxWidth: 360,
  },
  conditionRowName: {
    overflow: "hidden",
    color: colors.textPrimary,
    fontSize: 12.5,
    fontWeight: 600,
    lineHeight: 1.3,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  conditionCount: {
    fontSize: 12.5,
    fontWeight: 600,
    color: colors.textPrimary,
    fontVariantNumeric: "tabular-nums",
    textAlign: "right",
  },
  // Qualifiers in the label row: "any of" after the eyebrow, "participants" over the count column.
  labelQualifier: {
    fontWeight: 500,
    letterSpacing: 0,
    textTransform: "none",
    color: colors.textMuted,
  },
  labelRowSplit: {
    justifyContent: "space-between",
  },
  // Under a condition's name: "HPO", the term's name, its id as the link, a copy button.
  hpoLine: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 6,
    minWidth: 0,
  },
  hpoEyebrow: {
    ...Style.elements.eyebrow,
    flexShrink: 0,
    color: colors.textSecondary,
  },
  hpoName: {
    overflow: "hidden",
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: 500,
    lineHeight: 1.3,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  // The picked chip's id link: navy mono, faintly underlined, the external mark inline.
  hpoId: {
    display: "inline-flex",
    alignItems: "center",
    flexShrink: 0,
    gap: 3,
    color: colors.textAccent,
    fontFamily: Style.monoFamily,
    fontSize: 11.5,
    fontWeight: 600,
    textDecoration: "underline",
    textDecorationColor: alpha(colors.textAccent, 0.35),
    textUnderlineOffset: 2,
    whiteSpace: "nowrap",
  },
  hpoIdHover: {
    textDecorationColor: colors.textAccent,
  },
  hpoNone: {
    flexShrink: 0,
    padding: "1px 7px",
    border: `1px dashed ${colors.borderStrong}`,
    borderRadius: 6,
    color: colors.textSecondary,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.3,
    lineHeight: 1.4,
    textTransform: "uppercase",
    whiteSpace: "nowrap",
    cursor: "default",
  },
  count: {
    fontSize: 20,
    fontWeight: 700,
    lineHeight: 1,
    color: colors.textPrimary,
    fontVariantNumeric: "tabular-nums",
  },
  countUnit: {
    fontSize: 12,
    color: colors.textSecondary,
  },
  // The Ancestry/Age toggle in the label row, the same pill as the view switcher one size down.
  tabs: {
    display: "inline-flex",
    gap: 2,
    padding: 2,
    background: colors.surface1,
    border: `1px solid ${colors.border}`,
    borderRadius: 999,
  },
  tab: {
    padding: "1px 8px",
    border: "none",
    borderRadius: 999,
    background: "none",
    color: colors.textSecondary,
    fontSize: 10.5,
    fontWeight: 600,
    cursor: "pointer",
  },
  tabActive: {
    background: colors.surface2,
    color: colors.textAccent,
    boxShadow: Style.shadows.pill,
  },
  emptyTitle: {
    fontSize: 14,
    fontWeight: 600,
    color: colors.textPrimary,
  },
  emptyMessage: {
    fontSize: 12,
    color: colors.textSecondary,
  },
  noMatch: {
    fontSize: 12.5,
    color: colors.textSecondary,
  },
} as const satisfies Record<string, CSSProperties>;

type BreakdownTab = "ancestry" | "age" | "condition";

const TABS: { id: BreakdownTab; label: string }[] = [
  { id: "ancestry", label: "Ancestry" },
  { id: "age", label: "Age" },
  { id: "condition", label: "Condition" },
];

interface PhenotypeSummaryStripProps {
  /** Null while results are loading: the strip shows a skeleton. */
  conditionSearch: ConditionSearch | null | undefined;
  ancestryBreakdown: BreakdownSegment[];
  ageBreakdown: BreakdownSegment[];
  onAddPhenotypeFilter: () => void;
  view: ResultsView;
  onViewChange: (view: ResultsView) => void;
  /** Whether Review has anything to compare: a phenotype filter that matched participants. */
  canReview: boolean;
  loading?: boolean;
}

export default function PhenotypeSummaryStrip({
  conditionSearch,
  ancestryBreakdown,
  ageBreakdown,
  onAddPhenotypeFilter,
  view,
  onViewChange,
  canReview,
  loading = false,
}: PhenotypeSummaryStripProps) {
  const [activeTab, setActiveTab] = useState<BreakdownTab>("ancestry");
  const switcher = (
    <ViewSwitcher
      value={view}
      onChange={onViewChange}
      reviewUnavailableReason={
        canReview ? undefined : "Review compares matched participants with the cohort. Add a phenotype filter to enable it."
      }
    />
  );
  const viewBlock = (
    <div style={{ ...styles.block, ...styles.blockDivided, paddingRight: 0 }}>
      <div style={styles.blockLabel}>
        <span style={styles.eyebrow}>View</span>
      </div>
      <div style={styles.blockContent}>{switcher}</div>
    </div>
  );

  if (loading) {
    return (
      <div style={styles.strip} aria-busy="true">
        {[220, 90, 320].map((width, index) => (
          <div key={index} style={{ ...styles.block, ...(index > 0 ? styles.blockDivided : undefined) }}>
            <div style={styles.blockLabel}>
              <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: 60, height: 8 }} />
            </div>
            <div style={styles.blockContent}>
              <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width, height: 18 }} />
            </div>
          </div>
        ))}
        <div style={{ ...styles.block, ...styles.blockDivided, paddingRight: 0 }}>
          <div style={styles.blockLabel}>
            <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: 30, height: 8 }} />
          </div>
          <div style={styles.blockContent}>
            <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: 150, height: 28, borderRadius: 999 }} />
          </div>
        </div>
      </div>
    );
  }

  if (!conditionSearch) {
    return (
      <div style={{ ...styles.strip, gridTemplateColumns: "minmax(0, 1fr) auto" }}>
        <div style={styles.block}>
          <div style={styles.blockLabel}>
            <span style={styles.eyebrow}>Phenotype</span>
          </div>
          <div style={{ ...styles.blockContent, gap: 16 }}>
            <span style={styles.emptyTitle}>No phenotype filter</span>
            <span style={styles.emptyMessage}>Add a phenotype filter to see participant breakdowns and Review.</span>
            <Clickable style={Style.buttons.accent} hoverStyle={Style.buttons.accentHover} onClick={onAddPhenotypeFilter}>
              <PlusIcon size={12} />
              Add phenotype filter
            </Clickable>
          </div>
        </div>
        {viewBlock}
      </div>
    );
  }

  const concepts = conditionSearch.concepts;
  const participantCount = conditionSearch.participantCount ?? 0;
  const hasBreakdown = ancestryBreakdown.length > 0;
  // One condition has nothing to split, so its tab stays away; a re-run that drops to one
  // condition while the tab is active falls back to ancestry.
  const hasConditionTab = concepts.length > 1;
  const tabs = TABS.filter((tab) => tab.id !== "condition" || hasConditionTab);
  const tab = activeTab === "condition" && !hasConditionTab ? "ancestry" : activeTab;
  const breakdowns: Record<BreakdownTab, { segments: BreakdownSegment[]; label: string }> = {
    ancestry: { segments: ancestryBreakdown, label: "Ancestry" },
    age: { segments: ageBreakdown, label: "Age" },
    condition: {
      segments: conditionBreakdown(concepts, conditionSearch.conditionOverlap, participantCount),
      label: "Condition",
    },
  };
  // The union counts a participant once however many of the conditions they have, so the
  // per-condition counts beside the names can sum to more than it.
  const countTooltip =
    concepts.length > 1
      ? participantCount
        ? "Participants recorded with any of these conditions, or a more specific form of one. " +
          "A participant with more than one is counted once here, so the counts beside the conditions may add up to more than this total."
        : "No participants are recorded with any of these conditions or a more specific form of one."
      : participantCount
        ? "Participant counts include anyone recorded with this condition or any more specific form of it."
        : "No participants are recorded with this condition or any more specific form of it.";

  return (
    <div style={styles.strip}>
      <div style={styles.block}>
        <div style={{ ...styles.blockLabel, ...(concepts.length > 1 ? styles.labelRowSplit : undefined) }}>
          <span style={styles.eyebrow}>
            Phenotype
            {concepts.length > 1 && <span style={styles.labelQualifier}>&nbsp;· any of</span>}
          </span>
          {concepts.length > 1 && (
            <span style={{ ...styles.eyebrow, ...styles.labelQualifier }} aria-hidden="true">
              participants
            </span>
          )}
        </div>
        <div style={styles.blockContent}>
          {concepts.length > 1 ? (
            <ul style={styles.conditionList} aria-label="Conditions, any of, with participants matched by each">
              {concepts.map((concept) => (
                <li key={concept.conceptId} style={styles.conditionRow}>
                  <span style={styles.conditionRowText}>
                    <span style={styles.conditionRowName} title={concept.name}>
                      {concept.name}
                    </span>
                    <HpoLine hpo={concept.hpo} />
                  </span>
                  <span style={styles.conditionCount} aria-label={`${formatInt(concept.participantCount)} participants`}>
                    {formatInt(concept.participantCount)}
                  </span>
                </li>
              ))}
            </ul>
          ) : concepts.length === 1 ? (
            <div style={styles.conditionText}>
              <span style={styles.conditionName} title={concepts[0].name}>
                {concepts[0].name}
              </span>
              <HpoLine hpo={concepts[0].hpo} />
            </div>
          ) : (
            <span style={styles.noMatch}>
              Condition concept{conditionSearch.conceptIds.length === 1 ? "" : "s"}{" "}
              {conditionSearch.conceptIds.join(", ")} {conditionSearch.conceptIds.length === 1 ? "wasn’t" : "weren’t"}{" "}
              found in this CDR.
            </span>
          )}
        </div>
      </div>

      <div style={{ ...styles.block, ...styles.blockDivided }}>
        <div style={styles.blockLabel}>
          <span style={styles.eyebrow}>
            Participants
            <InfoTooltip text={countTooltip} style={{ marginTop: -4, marginBottom: -4 }} />
          </span>
        </div>
        <div style={styles.blockContent}>
          <span style={styles.count}>{formatInt(participantCount)}</span>
          <span style={styles.countUnit}>matched</span>
        </div>
      </div>

      <div style={{ ...styles.block, ...styles.blockDivided }}>
        <div style={styles.blockLabel}>
          <span style={styles.eyebrow}>Breakdown</span>
          {hasBreakdown && (
            <div style={styles.tabs} role="group" aria-label="Participant breakdown">
              {tabs.map((candidate) => (
                <Clickable
                  key={candidate.id}
                  aria-pressed={tab === candidate.id}
                  style={{ ...styles.tab, ...(tab === candidate.id ? styles.tabActive : undefined) }}
                  hoverStyle={{ color: colors.textAccent }}
                  onClick={() => setActiveTab(candidate.id)}
                >
                  {candidate.label}
                </Clickable>
              ))}
            </div>
          )}
        </div>
        <div style={{ ...styles.blockContent, alignItems: "stretch" }}>
          {hasBreakdown ? (
            // Keyed by tab so switching remounts the bar, replaying its entrance.
            <BreakdownBar key={tab} segments={breakdowns[tab].segments} label={breakdowns[tab].label} />
          ) : (
            <span style={styles.emptyMessage}>No participants to break down.</span>
          )}
        </div>
      </div>

      {viewBlock}
    </div>
  );
}
