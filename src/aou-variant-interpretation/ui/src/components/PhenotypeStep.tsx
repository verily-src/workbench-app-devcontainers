import { useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { ConditionConcept, HpoTerm } from "../api/conditions";
import colors, { alpha } from "../libs/colors";
import { useElementWidth } from "../libs/hooks";
import * as Style from "../libs/style";
import { hpoTermUrl } from "../utils/externalLinks";
import { describeHpo } from "../utils/hpo";
import { PHENOTYPES_LIMIT } from "../utils/phenotypes";
import AllOfUs from "./common/AllOfUs";
import Clickable from "./common/Clickable";
import ConditionSearchField, { describeEstimate } from "./ConditionSearchField";
import FieldHint from "./FieldHint";
import { CloseIcon, ExternalLinkIcon, UserIcon } from "./icons";
import StepPanel, { type StepPanelAppearance, type StepTag } from "./StepPanel";

/** What the step does for the search; the folded row says the same, so the step reads alike open or closed. */
export const PHENOTYPE_STEP_DESCRIPTION =
  <>
    See how often each variant shows up among <AllOfUs /> participants recorded with any of up to three conditions.
  </>;

/** The step's tags, the same on the folded row and the open step: optional, then the limit. */
export function phenotypeTags(limit: number = PHENOTYPES_LIMIT): StepTag[] {
  return [
    { label: "Optional", variant: "optional" },
    { label: `limit ${limit}`, variant: "limit", title: `A search takes up to ${limit} phenotype${limit === 1 ? "" : "s"}.` },
  ];
}

/**
 * Narrower than this, the list stacks each row's figures under its name instead of beside it.
 * The entry card's list is about 820px wide and the edit popover's about 350px; the figures
 * take about 200px, so below this a name of ordinary length would be left a thin column.
 */
const STACKED_LIST_WIDTH = 480;

const styles = {
  /**
   * The picks as a bordered list, one condition per row. Condition names run long ("Malignant
   * neoplasm of upper-outer quadrant of female breast"), so a row gives the name the width it needs
   * and lets it wrap, while the figures sit in a column at the right edge, aligned down the list.
   * In a narrow list every row stacks the figures under the name instead; one layout for the whole
   * list, rather than each row wrapping or not by its own name's length.
   */
  picked: {
    margin: "0 0 8px",
    padding: 0,
    listStyle: "none",
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    background: colors.surface2,
    overflow: "hidden",
  },
  pick: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "8px 6px 8px 12px",
  },
  /** The remove button stays level with the name's first line, not the middle of the stack. */
  pickStacked: {
    alignItems: "flex-start",
  },
  pickRuled: {
    borderTop: `1px solid ${colors.border}`,
  },
  /** "or" as a small label sitting on the rule above every row but the first. */
  or: {
    position: "absolute",
    top: -7,
    left: 9,
    padding: "0 4px",
    background: colors.surface2,
    ...Style.elements.eyebrow,
    lineHeight: 1.3,
  },
  /** The name, and in the stacked layout the figures beneath it. Takes the row's spare width. */
  nameBlock: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    flex: 1,
    minWidth: 0,
  },
  name: {
    color: colors.textBody,
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 1.35,
  },
  /** The estimate and HPO id; never wraps, so the name gives way instead. */
  figures: {
    display: "inline-flex",
    alignItems: "center",
    gap: 10,
    flexShrink: 0,
  },
  chipDivider: {
    flexShrink: 0,
    width: 1,
    height: 14,
    background: colors.border,
  },
  chipEstimate: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    ...Style.elements.mono,
    fontSize: 11.5,
    fontWeight: 500,
    color: colors.textSecondary,
    whiteSpace: "nowrap",
  },
  chipEstimateIcon: {
    display: "block",
    flexShrink: 0,
  },
  chipHpo: {
    display: "inline-flex",
    alignItems: "center",
    gap: 3,
    ...Style.elements.mono,
    fontSize: 11,
    fontWeight: 600,
    color: colors.textAccent,
    textDecoration: "underline",
    textDecorationColor: alpha(colors.textAccent, 0.35),
    textUnderlineOffset: 2,
    whiteSpace: "nowrap",
  },
  remove: {
    ...Style.buttons.icon,
    flexShrink: 0,
    width: 20,
    height: 20,
    borderRadius: "50%",
    color: colors.textSecondary,
  },
  /** Centred on the name's 17.5px first line. */
  removeStacked: {
    marginTop: -1,
  },
  removeHover: {
    background: colors.surface0,
    color: colors.textDanger,
  },
  atLimit: {
    ...Style.elements.fieldHint,
    marginTop: 0,
  },
} as const satisfies Record<string, CSSProperties>;

interface PhenotypeStepProps {
  id: string;
  /** The phenotypes picked so far, in the order they were picked. */
  picked: ConditionConcept[];
  onPick: (concept: ConditionConcept) => void;
  onRemove: (conceptId: number) => void;
  /** How many the search can take; the field hides once they're all picked. */
  limit?: number;
  /** See StepPanel. */
  appearance?: StepPanelAppearance;
  numbered?: boolean;
  description?: ReactNode;
  /** Extra content below the hint. */
  children?: ReactNode;
}

function ChipEstimate({ estimate }: { estimate: number | null }) {
  const { label, tooltip, spoken } = describeEstimate(estimate);
  return (
    <span style={styles.chipEstimate} title={tooltip} aria-label={spoken}>
      <UserIcon size={11} strokeWidth={2.5} style={styles.chipEstimateIcon} aria-hidden="true" />
      {label}
    </span>
  );
}

/** The pick's HPO id as the link out to the term; "≈" ahead of it marks a nearest match. */
function ChipHpo({ hpo }: { hpo: HpoTerm }) {
  const { label, tooltip, spoken } = describeHpo(hpo, { link: true });
  return (
    <a href={hpoTermUrl(hpo.id)} target="_blank" rel="noopener noreferrer" style={styles.chipHpo} title={tooltip} aria-label={spoken}>
      {label}
      <ExternalLinkIcon size={11} aria-hidden="true" />
    </a>
  );
}

export default function PhenotypeStep({
  id,
  picked,
  onPick,
  onRemove,
  limit = PHENOTYPES_LIMIT,
  appearance,
  numbered,
  description,
  children,
}: PhenotypeStepProps) {
  // What's typed in the field: transient, cleared by a pick. Only picked concepts filter a search,
  // so text left here without picking is ignored, the same as leaving the field empty.
  const [text, setText] = useState("");
  const listRef = useRef<HTMLUListElement>(null);
  const listWidth = useElementWidth(listRef);
  const stacked = listWidth !== undefined && listWidth < STACKED_LIST_WIDTH;
  const atLimit = picked.length >= limit;
  const tags = phenotypeTags(limit);

  return (
    <StepPanel
      stepNumber={2}
      title="Phenotype"
      tags={tags}
      appearance={appearance}
      numbered={numbered}
      description={description}
    >
      {picked.length > 0 && (
        <ul ref={listRef} style={styles.picked} aria-label="Picked phenotypes">
          {picked.map((concept, index) => {
            const figures = (
              <span style={styles.figures}>
                <ChipEstimate estimate={concept.estimatedParticipantCount} />
                {concept.hpo && (
                  <>
                    <span style={styles.chipDivider} aria-hidden="true" />
                    <ChipHpo hpo={concept.hpo} />
                  </>
                )}
              </span>
            );
            return (
              <li
                key={concept.conceptId}
                style={{
                  ...styles.pick,
                  ...(index > 0 ? styles.pickRuled : undefined),
                  ...(stacked ? styles.pickStacked : undefined),
                }}
              >
                {index > 0 && <span style={styles.or}>or</span>}
                <span style={styles.nameBlock}>
                  <span style={styles.name}>{concept.name}</span>
                  {stacked && figures}
                </span>
                {!stacked && figures}
                <Clickable
                  style={{ ...styles.remove, ...(stacked ? styles.removeStacked : undefined) }}
                  hoverStyle={styles.removeHover}
                  aria-label={`Remove ${concept.name}`}
                  onClick={() => onRemove(concept.conceptId)}
                >
                  <CloseIcon size={11} aria-hidden="true" />
                </Clickable>
              </li>
            );
          })}
        </ul>
      )}
      {atLimit ? (
        <p style={styles.atLimit}>
          {limit === 1
            ? "You have reached the maximum of one phenotype. Remove it to pick another."
            : `You have reached the maximum of ${limit} phenotypes. Remove one to pick another.`}
        </p>
      ) : (
        <>
          <ConditionSearchField
            id={id}
            value={text}
            onChange={setText}
            onSelect={(concept) => {
              setText("");
              if (!picked.some((other) => other.conceptId === concept.conceptId)) onPick(concept);
            }}
            // A concept already picked is left out of the list, rather than picked again to no effect.
            excludeConceptIds={picked.map((concept) => concept.conceptId)}
            placeholder={picked.length === 0 ? "e.g. tetralogy of fallot" : "Add another condition"}
          />
          <FieldHint>
            {picked.length === 0 ? (
              <>
                Start typing a condition and pick one from the list. Matched
                against the <AllOfUs /> condition vocabulary.
              </>
            ) : (
              `Add up to ${limit - picked.length} more. A participant recorded with any of these conditions is matched.`
            )}
          </FieldHint>
        </>
      )}
      {children}
    </StepPanel>
  );
}
