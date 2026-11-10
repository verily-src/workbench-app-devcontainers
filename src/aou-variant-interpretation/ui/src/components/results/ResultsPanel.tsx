import type { CSSProperties, ReactNode } from "react";
import * as Style from "../../libs/style";

const styles = {
  panel: {
    ...Style.elements.panel,
    display: "flex",
    flexDirection: "column",
    boxShadow: Style.shadows.panel,
  },
  header: {
    ...Style.elements.panelHeader,
    justifyContent: "space-between",
    gap: 12,
    minHeight: 53,
  },
  title: {
    ...Style.elements.panelTitle,
    flexShrink: 0,
  },
} as const satisfies Record<string, CSSProperties>;

interface ResultsPanelProps {
  title: ReactNode;
  /** Actions and counts at the header's right end, e.g. the table's Export TSV. */
  headerRight?: ReactNode;
  children: ReactNode;
  style?: CSSProperties;
}

/** The bordered card the results page's views sit in: a title strip, then the content. */
export default function ResultsPanel({ title, headerRight, children, style }: ResultsPanelProps) {
  return (
    <div style={{ ...styles.panel, ...style }}>
      <div style={styles.header}>
        <h2 style={styles.title}>{title}</h2>
        {headerRight}
      </div>
      {children}
    </div>
  );
}
