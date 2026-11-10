import { useRef, type CSSProperties } from "react";
import colors from "../../libs/colors";
import { useCenterAboveFold } from "../../libs/hooks";
import * as Style from "../../libs/style";
import Clickable from "../common/Clickable";
import { describeAlternatives } from "../../utils/phenotypes";
import { PlusIcon } from "../icons";
import PhenotypeFilterIllustration from "./PhenotypeFilterIllustration";
import { TOP_BAR_HEIGHT } from "./TopBar";

// What the phenotype-matched columns hold when there's nothing matched to show: the picture, one
// line saying what the columns would show, and the button that fills them. It sits on a white card
// so the picture's colours and the navy button aren't read against the column's blue tint, and
// the card starts centred in whatever part of the column is on screen. Two layouts, so a short
// table doesn't stretch its rows to fit the full one.

const styles = {
  // The gutter between the card and the tinted cell around it. Part of the measured box, so
  // centring accounts for it.
  frame: {
    padding: 12,
  },
  frameCompact: {
    padding: 6,
  },
  card: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 8,
    padding: "18px 16px 16px",
    background: colors.surface2,
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    boxShadow: Style.shadows.panel,
    textAlign: "center",
  },
  cardCompact: {
    flexDirection: "row",
    gap: 12,
    padding: "4px 8px",
    textAlign: "left",
  },
  title: {
    fontSize: 13,
    fontWeight: 700,
    color: colors.textPrimary,
  },
  message: {
    maxWidth: 260,
    fontSize: 12,
    lineHeight: 1.45,
    color: colors.textSecondary,
  },
  compactText: {
    display: "flex",
    flexDirection: "column",
    gap: 1,
    minWidth: 0,
  },
  // Accent, not primary: Export TSV is the table's one call to action, and this reveals the search
  // editor rather than completing anything.
  button: {
    ...Style.buttons.accent,
    flexShrink: 0,
  },
} as const satisfies Record<string, CSSProperties>;

interface PhenotypeFilterPromptProps {
  /** The picked conditions' names when some were picked but matched nobody; empty when none was picked. */
  phenotypes: string[];
  /** Absent where there's nothing to open, which leaves the button out. */
  onAddPhenotypeFilter?: () => void;
  /** The one-line layout, for a table too short for the full one. */
  compact?: boolean;
}

export default function PhenotypeFilterPrompt({ phenotypes, onAddPhenotypeFilter, compact = false }: PhenotypeFilterPromptProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  useCenterAboveFold(frameRef, TOP_BAR_HEIGHT);

  const condition = describeAlternatives(phenotypes);
  const title = condition ? "No matched participants" : "Compare with a phenotype";
  const message = condition
    ? `Nobody is recorded with ${condition}. Try a broader or different phenotype.`
    : "Add a phenotype to see how often its participants carry each variant.";
  const button = onAddPhenotypeFilter && (
    <Clickable
      style={styles.button}
      hoverStyle={Style.buttons.accentHover}
      onClick={(event) => {
        // The row underneath toggles expansion on click.
        event.stopPropagation();
        onAddPhenotypeFilter();
      }}
    >
      <PlusIcon size={12} aria-hidden="true" />
      {condition ? "Change phenotype" : "Add phenotype filter"}
    </Clickable>
  );

  return (
    <div ref={frameRef} style={{ ...styles.frame, ...(compact ? styles.frameCompact : undefined) }}>
      {compact ? (
        <div style={{ ...styles.card, ...styles.cardCompact }}>
          <PhenotypeFilterIllustration width={52} />
          <div style={styles.compactText}>
            <span style={{ ...styles.title, fontSize: 12 }}>{title}</span>
            <span style={{ ...styles.message, fontSize: 11 }}>{message}</span>
          </div>
          {button}
        </div>
      ) : (
        <div style={styles.card}>
          <PhenotypeFilterIllustration width={150} />
          <span style={styles.title}>{title}</span>
          <span style={styles.message}>{message}</span>
          {button}
        </div>
      )}
    </div>
  );
}
