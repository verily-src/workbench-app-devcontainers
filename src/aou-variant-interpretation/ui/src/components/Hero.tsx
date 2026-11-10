import type { CSSProperties, ReactNode } from "react";
import colors, { alpha } from "../libs/colors";
import { IS_BETA } from "../libs/version";

// A band under the top bar in the brand's navy. A line for each job:
// the app's name (identity), a sentence on what it gives you (purpose), and optionally a line of
// facts such as the data it reads from (provenance). What to do is the form's job, and the form
// starts right beneath.
const styles = {
  hero: {
    padding: "20px 20px 22px",
    // The favicon's navy, flat: the one brand surface in the app, so it doesn't need decorating.
    // Dark enough for white text without a scrim.
    background: colors.brandNavy,
  },
  // The same width as the search card beneath, so the title and the card share a left edge.
  inner: {
    maxWidth: 860,
    margin: "0 auto",
  },
  // The name and the Beta chip on one line; the chip beside the heading, not in it, so the
  // heading's name is the app's.
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 4,
  },
  title: {
    margin: 0,
    color: colors.white,
    fontSize: 22,
    fontWeight: 800,
    letterSpacing: -0.3,
    lineHeight: 1.2,
  },
  // The footer's Beta chip, on navy: a label for the product's stage beside its name.
  beta: {
    padding: "2px 7px",
    borderRadius: 999,
    background: alpha(colors.white, 0.16),
    color: colors.white,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  subtitle: {
    margin: 0,
    color: alpha(colors.white, 0.85),
    fontSize: 13.5,
    lineHeight: 1.5,
  },
} as const satisfies Record<string, CSSProperties>;

interface HeroProps {
  title: ReactNode;
  subtitle: ReactNode;
  /** A line of facts under the subtitle, e.g. the data sources. */
  facts?: ReactNode;
}

export default function Hero({ title, subtitle, facts }: HeroProps) {
  return (
    <div style={styles.hero}>
      <div style={styles.inner}>
        <div style={styles.titleRow}>
          <h1 style={styles.title}>{title}</h1>
          {IS_BETA && (
            <span style={styles.beta} title="VIA is in beta: features are subject to change.">
              Beta
            </span>
          )}
        </div>
        <p style={styles.subtitle}>{subtitle}</p>
        {facts}
      </div>
    </div>
  );
}
