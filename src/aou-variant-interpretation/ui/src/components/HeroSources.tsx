import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { fetchDataSourceVersions, type DataSourceVersion } from "../api/dataSourceVersions";
import colors, { alpha } from "../libs/colors";
import * as Style from "../libs/style";
import AllOfUs from "./common/AllOfUs";

// The hero's last line: what every answer is read from -- the dataset release and the versions
// of gnomAD, ClinVar and the annotations. The same facts the settings dialog's Data sources
// panel lists, fetched here too, so a version bump shows where a search starts rather than only
// behind the gear. If they can't be fetched the line is left empty: they're context, not
// something the search needs, and the settings panel is where the failure is explained.

/** As many placeholder bars as there are sources, so the line is the same length while they load. */
const SKELETON_COUNT = 5;

const styles = {
  line: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "4px 14px",
    // Held whether the versions are loading, loaded or missing, so the card beneath never moves.
    minHeight: 16,
    margin: "8px 0 0",
    padding: 0,
    listStyle: "none",
    fontSize: 11.5,
    lineHeight: 1.3,
    color: alpha(colors.white, 0.72),
  },
  name: {
    marginRight: 2,
    color: colors.white,
    fontWeight: 600,
  },
  version: {
    ...Style.elements.mono,
    fontSize: 11,
  },
  skeleton: {
    ...Style.elements.skeleton,
    width: 84,
    height: 11,
    background: alpha(colors.white, 0.18),
  },
} as const satisfies Record<string, CSSProperties>;

export default function HeroSources() {
  const [versions, setVersions] = useState<DataSourceVersion[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchDataSourceVersions()
      .then(setVersions)
      .catch((err: unknown) => {
        console.error("Failed to load data source versions", err);
        setFailed(true);
      });
  }, []);

  if (failed) return <div style={styles.line} />;

  if (!versions) {
    return (
      <div style={styles.line} aria-busy="true">
        {Array.from({ length: SKELETON_COUNT }, (_, index) => (
          <span key={index} className="animate-skeleton-pulse" style={styles.skeleton} />
        ))}
      </div>
    );
  }

  return (
    <ul style={styles.line} aria-label="Data sources">
      {versions.map((source) => (
        <li key={source.name}>
          <span style={styles.name}>{source.name === "All of Us" ? <AllOfUs /> : source.name}</span>{" "}
          <span style={styles.version}>{source.version}</span>
        </li>
      ))}
    </ul>
  );
}
