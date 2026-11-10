import type { CSSProperties } from "react";
import colors from "../../libs/colors";
import AppVersion from "../elements/AppVersion";

export const FOOTER_HEIGHT = 60;

const styles = {
  footer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 16,
    minHeight: FOOTER_HEIGHT,
    padding: "10px 20px",
    background: colors.surface2,
    borderTop: `1px solid ${colors.border}`,
  },
  logo: {
    height: 32,
    width: "auto",
  },
} as const satisfies Record<string, CSSProperties>;

interface FooterProps {
  style?: CSSProperties;
}

export default function Footer({ style }: FooterProps) {
  return (
    <footer style={{ ...styles.footer, ...style }}>
      <AppVersion />
      <img style={styles.logo} src="/broad-logo.svg" alt="Broad Institute" />
    </footer>
  );
}
