import { useEffect, useState } from "react";
import { KnowledgeBase } from "./KnowledgeBase";
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
  { id: "openrouter", label: "OpenRouter", keyLabel: "OpenRouter API key",
    placeholder: "sk-or-…", models: [] },
  { id: "bedrock", label: "Amazon Bedrock", keyLabel: "",
    placeholder: "", models: [] },
  { id: "vertexai", label: "Google Vertex AI", keyLabel: "",
    placeholder: "", models: [] },
  { id: "openweight", label: "Openweight (self-hosted)", keyLabel: "Optional API key",
    placeholder: "Optional", models: [] },
];

function safeProviderError(error: unknown, secret: string) {
  const message = error instanceof Error ? error.message : "Unknown error";
  const withoutCurrentKey = secret
    ? message.split(secret).join("[redacted]") : message;
  return withoutCurrentKey
    .replace(/\b(?:sk-ant-[A-Za-z0-9_-]+|sk-or-v1-[A-Za-z0-9_-]+|sk-proj-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]{20,})\b/g,
      "[redacted]")
    .slice(0, 240);
}

export function SettingsView(
    { onPaletteChange }: { onPaletteChange?: (p: string) => void }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [jevToken, setJevToken] = useState("");
  const [jevModel, setJevModel] = useState("");
  const [jevBusy, setJevBusy] = useState(false);
  const [jevStatus, setJevStatus] = useState("");
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [palette, setPalette] = useState("verily");
  const [status, setStatus] = useState("");
  const [providerBusy, setProviderBusy] = useState("");
  const [providerStatus, setProviderStatus] = useState("");

  useEffect(() => {
    api.config().then((c) => {
      setCfg(c);
      setProvider(c.llm.provider);
      setModel(c.llm.model);
      setConnections(c.mcp_connections);
      setPalette(c.chart_palette);
      setJevModel(c.jev?.model ?? "");
    }).catch(() => undefined);
  }, []);

  const pickProvider = (p: Provider) => {
    setProvider(p);
    setModel(cfg?.llm.providers[p]?.model ?? "");
    setApiKey("");
  };

  const meta = PROVIDERS.find((p) => p.id === provider) ?? PROVIDERS[0];
  const providerState = cfg?.llm.providers[provider];
  const usesBedrockIam = provider === "bedrock";
  const usesVertexAdc = provider === "vertexai";
  const usesOpenweight = provider === "openweight";

  const save = async () => {
    setProviderBusy("save");
    setProviderStatus("Saving provider settings…");
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
      setProviderStatus("Provider settings saved securely.");
    } catch (error) {
      setProviderStatus(`Save failed: ${safeProviderError(error, apiKey)}`);
    } finally {
      setProviderBusy("");
    }
  };

  const saveJev = async () => {
    setJevBusy(true);
    setJevStatus("Saving Jev settings…");
    try {
      const updated = await api.updateConfig({
        jev_model: jevModel,
        ...(jevToken ? { jev_api_key: jevToken } : {}),
      });
      setCfg(updated);
      setJevModel(updated.jev.model);
      setJevToken("");
      setJevStatus("Settings saved. Connection not tested.");
    } catch (error) {
      setJevStatus(`Save failed: ${safeProviderError(error, jevToken)}`);
    } finally {
      setJevBusy(false);
    }
  };

  const removeJevToken = async () => {
    setJevBusy(true);
    setJevStatus("Removing saved token…");
    try {
      const updated = await api.updateConfig({ jev_api_key: "" });
      setCfg(updated);
      setJevToken("");
      setJevStatus("Saved token removed.");
    } catch (error) {
      setJevStatus(`Removal failed: ${safeProviderError(error, jevToken)}`);
    } finally {
      setJevBusy(false);
    }
  };

  const removeApiKey = async () => {
    setStatus("Removing API key…");
    try {
      const updated = await api.updateConfig({ provider, api_key: "" });
      setCfg(updated);
      setStatus("API key removed.");
    } catch (e) {
      setStatus(`Key removal failed: ${(e as Error).message}`);
    }
  };

  const testLlm = async () => {
    setProviderBusy("test");
    setProviderStatus("Saving settings before testing…");
    try {
      const updated = await api.updateConfig({
        provider, model, ...(apiKey ? { api_key: apiKey } : {}),
      });
      setCfg(updated);
      setProvider(updated.llm.provider);
      setModel(updated.llm.model);
      setApiKey("");
      setProviderStatus("Testing connection…");
      const out = await api.testLlm();
      setProviderStatus(`Connected: ${out.display_name} (${out.model}).`);
    } catch (error) {
      setProviderStatus(`Connection test failed: ${safeProviderError(error, apiKey)}`);
    } finally {
      setProviderBusy("");
    }
  };

  const updateConnection = (i: number, changes: Partial<MCPConnection>) =>
    setConnections((prev) =>
      prev.map((c, j) => (j === i ? { ...c, ...changes } : c)));

  if (!cfg) return <div className="activity"><span className="pulse" />Loading settings…</div>;

  const mcpLocalUrl = `http://localhost:8080${cfg.mcp.path}`;
  const mcpPageUrl = `${window.location.origin}${cfg.mcp.path}`;

  return (
    <div style={{ maxWidth: 680 }}>
      <div className="section-label">AI model</div>
      <div className="settings-card">
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
          placeholder={provider === "anthropic" ? "claude-opus-5"
            : usesOpenweight ? "Set in app environment"
              : "enter the provider's model id"}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          readOnly={usesOpenweight}
        />
        {meta.models.length > 0 && (
          <datalist id="model-suggestions">
            {meta.models.map((m) => <option key={m} value={m} />)}
          </datalist>
        )}
        {usesOpenweight ? (
          <>
            <dl className="settings-caption">
              <div><dt>Endpoint</dt><dd>{providerState?.endpoint_host || "Not configured"}</dd></div>
              <div><dt>Authentication</dt><dd>Optional server key</dd></div>
            </dl>
            {!providerState?.configured && <p className="settings-hint" role="status">
              Set STUDIO_OPENWEIGHT_BASE_URL and STUDIO_OPENWEIGHT_MODEL in the app environment.
            </p>}
            <div className="field-label">Optional API key</div>
            <input type="password" placeholder={providerState?.api_key_set
              ? "Enter a new key to replace" : "Optional"} value={apiKey}
              onChange={(e) => setApiKey(e.target.value)} />
          </>
        ) : usesVertexAdc ? (
          <>
            <dl className="settings-caption">
              <div><dt>Project</dt><dd>{providerState?.project || "Not configured"}</dd></div>
              <div><dt>Location</dt><dd>{providerState?.location || "Not configured"}</dd></div>
              <div><dt>Authentication</dt><dd>Application Default Credentials</dd></div>
            </dl>
            {!providerState?.configured && (
              <p className="settings-hint" role="status">
                Vertex AI is not configured.
              </p>
            )}
          </>
        ) : usesBedrockIam ? (
          <>
            <dl className="settings-caption">
              <div><dt>Region</dt><dd>{providerState?.region || "Not configured"}</dd></div>
              <div><dt>Authentication</dt><dd>AWS credential chain (IAM)</dd></div>
            </dl>
            {!providerState?.region && (
              <p className="settings-hint" role="status">AWS Region is not configured.</p>
            )}
          </>
        ) : (
          <>
            <div className="field-label">
              {meta.keyLabel}
              {providerState?.api_key_set && (
                <span className="settings-hint">
                  {" "}· configured ({providerState.api_key_source})
                </span>
              )}
            </div>
            <input
              type="password"
              aria-label={meta.keyLabel}
              placeholder={providerState?.api_key_set
                ? "Enter a new key to replace" : meta.placeholder}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </>
        )}
        {!usesBedrockIam && !usesVertexAdc && providerState?.api_key_set && (
          <button className="quiet" onClick={removeApiKey}>Remove API key</button>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button className="primary" onClick={save} disabled={!!providerBusy}>
            {providerBusy === "save" ? "Saving…" : "Save"}
          </button>
          <button onClick={testLlm} disabled={!!providerBusy || (
                  usesOpenweight
                    ? !providerState?.configured || provider !== cfg.llm.provider
                    : usesVertexAdc
                    ? !providerState?.configured || !providerState?.model
                      || provider !== cfg.llm.provider
                      || model !== providerState?.model
                    : usesBedrockIam
                    ? !providerState?.region || !providerState?.model
                    : (!providerState?.api_key_set && !apiKey) || !model)}>
            {providerBusy === "test" ? "Testing…" : "Test connection"}
          </button>
        </div>
        {providerStatus && <div className="settings-status" role="status">
          {providerStatus}
        </div>}
      </div>

      <div className="section-label">Jev join recommendations</div>
      <div className="settings-card">
        <p className="settings-caption">
          Optional TypeSafe token for join suggestions. It is not used for chat.
          Saving does not test the connection.
        </p>
        <div className="field-label">
          TypeSafe API token
          {cfg.jev.api_key_set && <span className="settings-hint">
            {` · configured (${cfg.jev.api_key_source || "server setting"})`}
          </span>}
        </div>
        <input type="password" aria-label="TypeSafe API token"
          autoComplete="new-password"
          disabled={cfg.jev.api_key_source === "environment" || jevBusy}
          placeholder={cfg.jev.api_key_source === "environment"
            ? "Configured by environment"
            : cfg.jev.api_key_set ? "Enter a new token to replace" : "Enter token"}
          value={jevToken} onChange={(e) => setJevToken(e.target.value)} />
        <div className="field-label">Jev model (optional)</div>
        <input type="text" aria-label="Jev model" value={jevModel}
          placeholder="Use server default" disabled={jevBusy}
          onChange={(e) => setJevModel(e.target.value)} />
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button className="primary" onClick={saveJev} disabled={jevBusy}>
            {jevBusy ? "Saving…" : "Save Jev settings"}
          </button>
          {cfg.jev.api_key_set && cfg.jev.api_key_source !== "environment" &&
            <button className="quiet" onClick={removeJevToken} disabled={jevBusy}>
              Remove saved token
            </button>}
        </div>
        {jevStatus && <div className="settings-status" role="status">{jevStatus}</div>}
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
            ? mcpLocalUrl
            : "MCP package not installed in this build"}
        </code>
        <p className="settings-caption">
          Agents connect from inside the workspace: this address works in
          the app container (terminal or docker exec), and on the VM when
          port 8080 is published.
          {cfg.mcp.available && mcpPageUrl !== mcpLocalUrl && (
            <span className="settings-hint">
              {" "}This page's address ({mcpPageUrl}) needs browser
              cookies, so agents usually can't use it.
            </span>
          )}
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

      <KnowledgeBase />
      {status && <div className="settings-status">{status}</div>}
    </div>
  );
}
