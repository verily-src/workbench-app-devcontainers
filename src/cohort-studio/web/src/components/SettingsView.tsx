import { useEffect, useState } from "react";
import { api, AppConfig, MCPConnection } from "../api";

export function SettingsView() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.config().then((c) => {
      setCfg(c);
      setModel(c.llm.model);
      setConnections(c.mcp_connections);
    }).catch(() => undefined);
  }, []);

  const save = async () => {
    setStatus("Saving…");
    try {
      const updated = await api.updateConfig({
        model,
        ...(apiKey ? { api_key: apiKey } : {}),
        mcp_connections: connections,
      });
      setCfg(updated);
      setConnections(updated.mcp_connections);
      setApiKey("");
      setStatus("Saved.");
    } catch (e) {
      setStatus(`Save failed: ${(e as Error).message}`);
    }
  };

  const testLlm = async () => {
    setStatus("Testing connection…");
    try {
      const out = await api.testLlm();
      setStatus(`Connected: ${out.display_name} (${out.model})`);
    } catch (e) {
      setStatus(`Test failed: ${(e as Error).message}`);
    }
  };

  const updateConnection = (i: number, changes: Partial<MCPConnection>) =>
    setConnections((prev) =>
      prev.map((c, j) => (j === i ? { ...c, ...changes } : c)));

  if (!cfg) return <div className="activity"><span className="pulse" />Loading settings…</div>;

  return (
    <div style={{ maxWidth: 680 }}>
      <div className="section-label">AI model</div>
      <div className="settings-card">
        <p className="settings-caption">
          Powers "Ask AI" natural-language filtering on datasets. The API
          key is stored server-side and never shown again.
        </p>
        <div className="field-label">Model</div>
        <select value={model} onChange={(e) => setModel(e.target.value)}>
          {["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
            .concat(model && !["claude-opus-5", "claude-sonnet-5",
              "claude-haiku-4-5"].includes(model) ? [model] : [])
            .map((m) => <option key={m}>{m}</option>)}
        </select>
        <div className="field-label">
          Anthropic API key
          {cfg.llm.api_key_set && (
            <span className="settings-hint">
              {" "}· configured ({cfg.llm.api_key_hint}, via {cfg.llm.api_key_source})
            </span>
          )}
        </div>
        <input
          type="password"
          placeholder={cfg.llm.api_key_set ? "Enter a new key to replace" : "sk-ant-…"}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button className="primary" onClick={save}>Save</button>
          <button onClick={testLlm} disabled={!cfg.llm.api_key_set && !apiKey}>
            Test connection
          </button>
        </div>
      </div>

      <div className="section-label">MCP server (this app)</div>
      <div className="settings-card">
        <p className="settings-caption">
          Agents can drive this cohort builder over MCP (streamable HTTP):
          list datasources, open tables, and run cross-filtered queries.
        </p>
        <code className="settings-code">
          {cfg.mcp.available
            ? `${window.location.origin}${cfg.mcp.path}`
            : "MCP package not installed in this build"}
        </code>
        <p className="settings-caption">
          Note: through the Workbench proxy this URL requires browser
          cookies — agents typically connect from inside the workspace
          (localhost:8080{cfg.mcp.path} on the VM).
        </p>
      </div>

      <div className="section-label">MCP connections</div>
      <div className="settings-card">
        <p className="settings-caption">
          External MCP servers this app (and its AI features) may use.
          Verily Workbench and common research sources are pre-seeded —
          fill in a URL and enable to activate.
        </p>
        {connections.map((c, i) => (
          <div key={c.name} className="mcp-row">
            <label className="mcp-toggle">
              <input
                type="checkbox"
                checked={c.enabled}
                disabled={!c.url}
                onChange={(e) => updateConnection(i, { enabled: e.target.checked })}
              />
              <span>{c.label || c.name}</span>
            </label>
            <input
              type="text"
              placeholder="https://…/mcp"
              value={c.url}
              onChange={(e) => updateConnection(i, {
                url: e.target.value,
                ...(e.target.value ? {} : { enabled: false }),
              })}
            />
            <input
              type="password"
              placeholder={c.token_set ? "token set — replace?" : "auth token (optional)"}
              value={c.authorization_token ?? ""}
              onChange={(e) => updateConnection(i, {
                authorization_token: e.target.value || undefined })}
            />
            <button className="quiet" title="Remove"
                    onClick={() => setConnections(connections.filter((_, j) => j !== i))}>
              ✕
            </button>
            {c.note && <div className="settings-hint mcp-note">{c.note}</div>}
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => setConnections([...connections, {
            name: `server-${connections.length + 1}`, label: "", url: "",
            enabled: false, note: "", token_set: false }])}>
            Add connection
          </button>
          <button className="primary" onClick={save}>Save</button>
        </div>
      </div>

      {status && <div className="settings-status">{status}</div>}
    </div>
  );
}
