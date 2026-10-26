import { useEffect, useState } from "react";
import { api, MCPConnection } from "../api";
import "./AgentIntegrations.css";

const literature = [
  { name: "arxiv", label: "arXiv" },
];

export function AgentIntegrations({ onOpenSettings }: { onOpenSettings: () => void }) {
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    let cancelled = false;
    api.config().then((config) => {
      if (cancelled) return;
      setConnections(config.mcp_connections ?? []);
      setStatus("ready");
    }).catch(() => { if (!cancelled) setStatus("error"); });
    return () => { cancelled = true; };
  }, []);
  const items = [...literature, ...connections.filter((item) =>
    !(["pubmed", "biorxiv"].includes(item.name)) && !literature.some((known) => known.name === item.name))];
  return <details className="agent-integrations">
    <summary>Integrations</summary>
    <div className="agent-integrations-body">
      <div className="agent-integration"><strong>Studio data & workflows</strong><span>Built in</span></div>
      <div className="agent-integration"><strong>PubMed</strong><span>Built in · optional NCBI key</span></div>
      <div className="agent-integration"><strong>bioRxiv</strong><span>Built in · date-window search</span></div>
      <p>Other MCP connections are setup-only.</p>
      {status === "loading" ? <span role="status">Loading connections…</span>
        : status === "error" ? <span role="alert">Could not load integrations.</span>
        : <ul>{items.map((item) => {
          const saved = connections.find((connection) => connection.name === item.name);
          const label = !saved?.url ? "Not configured" : saved.enabled ? "Configured · setup only" : "Disabled";
          return <li className="agent-integration" key={item.name}>
            <span>{item.label}</span><span>{label}</span>
          </li>;
        })}</ul>}
      <button type="button" className="quiet" onClick={onOpenSettings}>Manage integrations</button>
    </div>
  </details>;
}
