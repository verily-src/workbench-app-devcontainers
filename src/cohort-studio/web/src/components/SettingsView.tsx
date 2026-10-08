import { useEffect, useState } from "react";
import { api, AppConfig, MCPConnection, Provider } from "../api";
import { PALETTE_NAMES, getPalette } from "../palette";

const PROVIDERS: { id: Provider; label: string; keyLabel: string;
                   placeholder: string; models: string[] }[] = [
  { id: "anthropic", label: "Anthropic (Claude)", keyLabel: "Anthropic API key",
    placeholder: "sk-ant-…",
    models: ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"] },
  { id: "openai", label: "OpenAI", keyLabel: "OpenAI API key",
    placeholder: "sk-…", models: [] },
  { id: "gemini", label: "Google Gemini", keyLabel: "Gemini API key",
    placeholder: "AIza…", models: [] },
];

export function SettingsView(
    { onPaletteChange }: { onPaletteChange?: (p: string) => void }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [palette, setPalette] = useState("verily");
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.config().then((c) => {
      setCfg(c);
      setProvider(c.llm.provider);
      setModel(c.llm.model);
      setConnections(c.mcp_connections);
      setPalette(c.chart_palette);
    }).catch(() => undefined);
  }, []);

  // Switching provider in the dropdown recalls that provider's saved
  // model and clears the (per-provider) key entry box.
  const pickProvider = (p: Provider) => {
    setProvider(p);
    setModel(cfg?.llm.providers[p]?.model ?? "");
    setApiKey("");
  };

  const meta = PROVIDERS.find((p) => p.id === provider) ?? PROVIDERS[0];
  const providerState = cfg?.llm.providers[provider];

  const save = async () => {
    setStatus("Saving…");
    try {
      const updated = await api.updateConfig({
        provider,
        model,
        ...(apiKey ? { api_key: apiKey } : {}),
        mcp_connections: connections,
        chart_palette: palette,
      });
      setCfg(updated);
      setConnections(updated.mcp_connections);
      setPalette(updated.chart_palette);
      onPaletteChange?.(updated.chart_palette);
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
          Powers "Ask AI" filtering and the chat assistant. Pick a provider;
          each keeps its own key and model. Keys are stored server-side and
          never shown again.
        </p>
        <div className="field-label">Provider</div>
        <select value={provider}
                onChange={(e) => pickProvider(e.target.value as Provider)}>
          {PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
        <div className="field-label">Model</div>
        <input
          type="text"
          list="model-suggestions"
          placeholder={provider === "anthropic"
            ? "claude-opus-5" : "enter the provider's model id"}
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
        {meta.models.length > 0 && (
          <datalist id="model-suggestions">
            {meta.models.map((m) => <option key={m} value={m} />)}
          </datalist>
        )}
        <div className="field-label">
          {meta.keyLabel}
          {providerState?.api_key_set && (
            <span className="settings-hint">
              {" "}· configured ({providerState.api_key_hint}, via{" "}
              {providerState.api_key_source})
            </span>
          )}
        </div>
        <input
          type="password"
          placeholder={providerState?.api_key_set
            ? "Enter a new key to replace" : meta.placeholder}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button className="primary" onClick={save}>Save</button>
          <button onClick={testLlm}
                  disabled={!providerState?.api_key_set && !apiKey}>
            Test connection
          </button>
        </div>
      </div>

      <div className="section-label">Chart palette</div>
      <div className="settings-card">
        <p className="settings-caption">
          The colour charts use — the full cohort renders muted and the
          filtered cohort in the accent.
        </p>
        <div className="palette-grid">
          {PALETTE_NAMES.map((name) => {
            const p = getPalette(name);
            return (
              <button key={name}
                      className={`palette-swatch${palette === name ? " active" : ""}`}
                      onClick={() => setPalette(name)}>
                <span className="palette-dots">
                  <span style={{ background: p.muted }} />
                  <span style={{ background: p.accent }} />
                  <span style={{ background: p.ramp[3] }} />
                </span>
                {name}
              </button>
            );
          })}
        </div>
        <button className="primary" style={{ marginTop: 10 }} onClick={save}>
          Save
        </button>
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
