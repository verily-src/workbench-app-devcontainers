import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { fetchStatus, type BigQueryStatus } from "../../api/status";
import { describeError } from "../../api/client";
import colors from "../../libs/colors";
import * as Style from "../../libs/style";
import Clickable from "../common/Clickable";

const styles = {
  heading: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    marginBottom: 14,
  },
  summary: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 12,
    padding: "4px 10px",
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
  },
  list: {
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    overflow: "hidden",
  },
  row: {
    display: "flex",
    alignItems: "flex-start",
    gap: 10,
    padding: "9px 12px",
  },
  tableName: {
    ...Style.elements.mono,
    color: colors.textBody,
    wordBreak: "break-all",
  },
  detail: {
    marginTop: 3,
    fontSize: 11.5,
    lineHeight: 1.4,
    color: colors.textDanger,
    wordBreak: "break-word",
  },
  state: {
    marginLeft: "auto",
    flexShrink: 0,
    fontSize: 11,
    fontWeight: 600,
  },
} as const satisfies Record<string, CSSProperties>;

const SKELETON_ROWS = 4;

export default function SystemStatusPanel() {
  const [status, setStatus] = useState<BigQueryStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const check = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchStatus()
      .then(setStatus)
      .catch((err: unknown) => setError(`Couldn't reach the backend: ${describeError(err)}`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(check, [check]);

  const unavailable = status?.tables.filter((table) => !table.accessible).length ?? 0;

  return (
    <>
      <div style={styles.heading}>
        <p style={{ ...Style.elements.panelIntro, margin: 0 }}>
          The BigQuery tables VIA queries, and whether this workspace's credentials can read them.
        </p>
        <Clickable
          style={{ ...Style.buttons.accent, flexShrink: 0 }}
          hoverStyle={Style.buttons.accentHover}
          disabledStyle={Style.buttons.disabled}
          onClick={check}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </Clickable>
      </div>

      {error ? (
        <div role="alert" style={Style.elements.errorNote}>
          {error}
        </div>
      ) : loading || !status ? (
        <div style={styles.list} aria-busy="true">
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
            <div
              key={index}
              style={{ ...styles.row, borderTop: index > 0 ? `1px solid ${colors.border}` : undefined }}
            >
              <span className="animate-skeleton-pulse" style={{ ...Style.elements.skeleton, width: `${60 - index * 6}%` }} />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div
            style={{
              ...styles.summary,
              background: status.accessible ? colors.bgSuccess : colors.bgDanger,
              color: status.accessible ? colors.textSuccess : colors.textDanger,
            }}
          >
            {status.accessible
              ? "All tables accessible"
              : `${unavailable} of ${status.tables.length} tables unavailable`}
          </div>
          <ul style={{ ...styles.list, listStyle: "none", margin: 0, padding: 0 }}>
            {status.tables.map((table, index) => (
              <li
                key={table.table}
                style={{ ...styles.row, borderTop: index > 0 ? `1px solid ${colors.border}` : undefined }}
              >
                <span
                  style={{
                    ...Style.colorDot(table.accessible ? colors.textSuccess : colors.textDanger, 8),
                    marginTop: 4,
                  }}
                />
                <div style={{ minWidth: 0 }}>
                  <div style={styles.tableName}>{table.table}</div>
                  {table.detail && <div style={styles.detail}>{table.detail}</div>}
                </div>
                <span style={{ ...styles.state, color: table.accessible ? colors.textSuccess : colors.textDanger }}>
                  {table.accessible ? "Accessible" : "Unavailable"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
