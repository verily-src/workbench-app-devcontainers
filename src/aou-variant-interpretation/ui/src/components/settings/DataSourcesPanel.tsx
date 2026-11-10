import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { fetchDataSourceVersions, type DataSourceVersion } from "../../api/dataSourceVersions";
import { describeError } from "../../api/client";
import colors from "../../libs/colors";
import { useHoveredKey } from "../../libs/hooks";
import * as Style from "../../libs/style";
import { ExternalLinkIcon } from "../icons";

const styles = {
  frame: {
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    overflow: "hidden",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
  },
  headerCell: {
    ...Style.elements.eyebrow,
    padding: "7px 12px",
    background: colors.surface0,
    borderBottom: `1px solid ${colors.border}`,
    textAlign: "left",
  },
  cell: {
    padding: "10px 12px",
    verticalAlign: "top",
    lineHeight: "18px",
  },
  name: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: 600,
  },
  description: {
    marginTop: 1,
    color: colors.textSecondary,
    fontSize: 11.5,
    lineHeight: 1.4,
  },
  version: {
    ...Style.elements.mono,
    whiteSpace: "nowrap",
    color: colors.textBody,
    fontSize: 12,
    fontWeight: 600,
  },
  link: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    whiteSpace: "nowrap",
    color: colors.textSecondary,
    fontSize: 11.5,
    textDecoration: "none",
  },
  linkHovered: {
    color: colors.textAccent,
    textDecoration: "underline",
    textUnderlineOffset: 2,
  },
} as const satisfies Record<string, CSSProperties>;

const SKELETON_ROWS = 5;

/** The link text: just the site, since the full URL is in the href. */
function hostname(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export default function DataSourcesPanel() {
  const [versions, setVersions] = useState<DataSourceVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { hoveredKey: hoveredLink, hoverProps: linkHoverProps } = useHoveredKey<string>();

  useEffect(() => {
    fetchDataSourceVersions()
      .then(setVersions)
      .catch((err: unknown) => setError(`Couldn't reach the backend: ${describeError(err)}`));
  }, []);

  const cell = (index: number, extra?: CSSProperties): CSSProperties => ({
    ...styles.cell,
    borderTop: index > 0 ? `1px solid ${colors.border}` : undefined,
    ...extra,
  });

  if (error) {
    return (
      <>
        <p style={Style.elements.panelIntro}>The datasets and annotation releases behind VIA's results.</p>
        <div role="alert" style={Style.elements.errorNote}>
          {error}
        </div>
      </>
    );
  }

  return (
    <>
      <p style={Style.elements.panelIntro}>The datasets and annotation releases behind VIA's results.</p>
      <div style={styles.frame} aria-busy={!versions}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th scope="col" style={styles.headerCell}>
                Source
              </th>
              <th scope="col" style={styles.headerCell}>
                Version
              </th>
              <th scope="col" style={{ ...styles.headerCell, textAlign: "right" }}>
                Website
              </th>
            </tr>
          </thead>
          <tbody>
            {versions
              ? versions.map((source, index) => (
                  <tr key={source.name}>
                    <td style={cell(index, { width: "100%" })}>
                      <div style={styles.name}>{source.name}</div>
                      {source.description && <div style={styles.description}>{source.description}</div>}
                    </td>
                    <td style={cell(index, styles.version)}>{source.version}</td>
                    <td style={cell(index, { textAlign: "right" })}>
                      {source.url && (
                        <a
                          style={{
                            ...styles.link,
                            ...(hoveredLink === source.name ? styles.linkHovered : undefined),
                          }}
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`Open ${source.name}`}
                          {...linkHoverProps(source.name)}
                        >
                          {hostname(source.url)}
                          <ExternalLinkIcon size={11} aria-hidden="true" />
                        </a>
                      )}
                    </td>
                  </tr>
                ))
              : Array.from({ length: SKELETON_ROWS }, (_, index) => (
                  <tr key={index}>
                    <td style={cell(index)} colSpan={3}>
                      <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: `${50 - index * 5}%` }} />
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
