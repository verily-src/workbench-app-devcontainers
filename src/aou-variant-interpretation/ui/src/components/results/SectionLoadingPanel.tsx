import type { CSSProperties } from "react";
import colors from "../../libs/colors";
import LensSpinner from "../common/LensSpinner";
import ResultsPanel from "./ResultsPanel";

const styles = {
  body: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    padding: "56px 20px",
    color: colors.textSecondary,
    fontSize: 12.5,
    textAlign: "center",
  },
} as const satisfies Record<string, CSSProperties>;

interface SectionLoadingPanelProps {
  title: string;
  message?: string;
  minHeight?: number;
}

export default function SectionLoadingPanel({
  title,
  message = "Loading…",
  minHeight,
}: SectionLoadingPanelProps) {
  return (
    <ResultsPanel title={title}>
      <div
        // minHeight comes from the caller so this placeholder occupies roughly the same
        // footprint as the panel it stands in for.
        style={{ ...styles.body, minHeight }}
      >
        <LensSpinner size={56} />
        <span>{message}</span>
      </div>
    </ResultsPanel>
  );
}
