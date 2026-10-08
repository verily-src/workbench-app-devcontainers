import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

export function LineageView() {
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<unknown[][]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    api.lineage()
      .then((out) => { setColumns(out.columns); setRows(out.data); })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  useEffect(refresh, [refresh]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div className="hero">
          <span className="count">{rows.length}</span>
          <span className="detail">lineage events</span>
        </div>
        <div style={{ flex: 1 }} />
        {loading && <div className="activity"><span className="pulse" />Loading…</div>}
        <button onClick={refresh}>Refresh</button>
      </div>
      <p className="settings-caption" style={{ margin: "6px 0 12px" }}>
        Loads, uploads, exports, and AI queries are recorded with actor and
        payload — in the workspace Aurora database when connected, or a
        local store otherwise.
      </p>
      {rows.length === 0 ? (
        <div className="empty">
          <div className="title">No lineage events yet</div>
          <div className="caption">Load a table or export a cohort and it will appear here.</div>
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell === null ? "–" : String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
