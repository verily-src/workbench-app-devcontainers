import type { CSSProperties } from "react";
import colors from "../../libs/colors";
import * as Style from "../../libs/style";
import { APP_VERSION, IS_BETA } from "../../libs/version";

const styles = {
  wrapper: {
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
  version: {
    ...Style.elements.mono,
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: 600,
  },
  // A chip in the accent tint, like the search card's "0 entered" and "Optional": a label for the
  // product's stage, not a warning.
  betaBadge: {
    padding: "2px 7px",
    background: colors.bgAccent,
    borderRadius: 999,
    color: colors.textAccent,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
} as const satisfies Record<string, CSSProperties>;

interface AppVersionProps {
  style?: CSSProperties;
}

export default function AppVersion({ style }: AppVersionProps) {
  return (
    <div style={{ ...styles.wrapper, ...style }}>
      <span style={styles.version} title="VIA version">
        VIA v{APP_VERSION}
      </span>
      {IS_BETA && (
        <span style={styles.betaBadge} title="VIA is in beta: features are subject to change.">
          Beta
        </span>
      )}
    </div>
  );
}
