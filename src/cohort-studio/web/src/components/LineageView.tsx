import { useCallback, useEffect, useState } from "react";
import { api, AgentTurn } from "../api";

export function LineageView() {
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<unknown[][]>([]);
  const [turns, setTurns] = useState<AgentTurn[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.lineage()
        .then((out) => { setColumns(out.columns); setRows(out.data); })
        .catch(() => undefined),
      api.agentTurns().then((out) => setTurns(out.turns)).catch(() => undefined),
    ]).finally(() => setLoading(false));
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

      <div className="section-label" style={{ marginTop: 20 }}>
        Agent activity
      </div>
      <p className="settings-caption" style={{ margin: "6px 0 12px" }}>
        Each chat-assistant turn is stored with OpenTelemetry-shaped fields
        (trace, provider, model, latency, token usage, tool calls) in the
        same Aurora database — exportable to a collector later.
      </p>
      {turns.length === 0 ? (
        <div className="settings-hint">No agent turns recorded yet.</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>when</th><th>provider</th><th>model</th><th>latency</th>
              <th>tokens</th><th>tools</th><th>status</th>
            </tr>
          </thead>
          <tbody>
            {turns.map((t) => (
              <tr key={t.trace_id}>
                <td>{String(t.ts).replace("T", " ").slice(0, 19)}</td>
                <td>{t.provider}</td>
                <td>{t.model}</td>
                <td>{Math.round(t.latency_ms)} ms</td>
                <td>{t.total_tokens}</td>
                <td>{(() => {
                  try { return (JSON.parse(t.tool_calls) as string[]).join(", "); }
                  catch { return ""; }
                })()}</td>
                <td>{t.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
