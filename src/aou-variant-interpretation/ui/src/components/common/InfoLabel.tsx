import type { CSSProperties, ReactNode } from "react";
import * as Style from "../../libs/style";
import InfoTooltip from "./InfoTooltip";

const styles = {
  // The gap stands in for the space character that used to separate label and icon.
  wrap: {
    display: "inline-flex",
    alignItems: "center",
    gap: 3,
  },
  // Trimmed to cap height, so the icon centers on the capitals rather than on a box that also
  // holds descender space the label doesn't use.
  label: Style.elements.trimmedText,
  // The icon's 20px hit area would otherwise make the line taller than a plain label's, pushing
  // this label up out of line with its neighbours (e.g. the other headers in a row). The negative
  // margins shrink only its footprint in the layout, not the area that takes the pointer.
  icon: {
    marginTop: -4,
    marginBottom: -4,
  },
} as const satisfies Record<string, CSSProperties>;

interface InfoLabelProps {
  children: ReactNode;
  /** See InfoTooltip. */
  tooltip: ReactNode;
}

/** A label with an InfoTooltip beside it, the icon centered on the label's text. */
export default function InfoLabel({ children, tooltip }: InfoLabelProps) {
  return (
    <span style={styles.wrap}>
      <span style={styles.label}>{children}</span>
      <InfoTooltip text={tooltip} style={styles.icon} />
    </span>
  );
}
