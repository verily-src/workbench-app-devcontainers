import type { CSSProperties, ReactNode } from "react";
import colors from "../libs/colors";
import * as Style from "../libs/style";
import Footer from "../components/results/Footer";
import TopBar from "../components/results/TopBar";
import { useUserEmail } from "../utils/useUserEmail";

// The frame for the app menu's workspace pages: the bar, a title on the page, one panel of
// facts, and the footer at the bottom of the window. The panel sits in the search page's column
// unless the page asks for the wide one, which a table of requests needs.
const styles = {
  page: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
  },
  main: {
    flex: 1,
    width: "100%",
    margin: "0 auto",
    padding: "28px 20px 40px",
  },
  title: {
    margin: "0 0 14px",
    color: colors.textPrimary,
    fontSize: 22,
    fontWeight: 800,
    letterSpacing: -0.3,
    lineHeight: 1.2,
  },
  panel: {
    ...Style.elements.panel,
    padding: "16px 20px 20px",
    boxShadow: Style.shadows.panel,
  },
} as const satisfies Record<string, CSSProperties>;

/** The panel's column: the search card's width, or the wide one for pages with tables. */
const COLUMN_WIDTH = { column: 860, wide: 1240 } as const;

interface SettingsPageProps {
  title: string;
  width?: keyof typeof COLUMN_WIDTH;
  children: ReactNode;
}

export default function SettingsPage({ title, width = "column", children }: SettingsPageProps) {
  const userEmail = useUserEmail();
  return (
    <div style={styles.page}>
      <TopBar userEmail={userEmail} />
      <main style={{ ...styles.main, maxWidth: COLUMN_WIDTH[width] + 40 }}>
        <h1 style={styles.title}>{title}</h1>
        <section style={styles.panel} aria-label={title}>
          {children}
        </section>
      </main>
      <Footer />
    </div>
  );
}
