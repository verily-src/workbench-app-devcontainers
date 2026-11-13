import { useState } from "react";
import type { ApiConfig } from "../types/catalog";
import { Badge, Button, Card, Input, Stack } from "./rds";
import { useWorkspaces, useWorkspaceDatasets } from "../hooks/useWorkspaces";

interface SaveResult extends ApiConfig {
  bucket_status?: { bucket: string; action: string; error?: string };
}

const selectStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: "var(--wb-radius)",
  border: "1px solid var(--wb-border)",
  fontSize: 14,
  fontFamily: "var(--wb-font)",
  background: "#fff",
  width: "100%",
  cursor: "pointer",
};

export function SettingsPanel(props: {
  config: ApiConfig | null;
  onSave: (patch: { billing_project?: string; data_project?: string; gemini_model?: string }) => Promise<SaveResult>;
  onSaved: () => void;
}) {
  const c = props.config;

  const { workspaces, loading: wsLoading } = useWorkspaces();

  const [useManual, setUseManual] = useState(false);
  const [billingProject, setBillingProject] = useState(c?.billing_project ?? "");
  const [manualData, setManualData] = useState(c?.data_project ?? "");

  const [selectedWsId, setSelectedWsId] = useState("");
  const selectedWs = workspaces.find((w) => w.id === selectedWsId);

  const { datasets, loading: dsLoading } = useWorkspaceDatasets(selectedWsId);

  const [selectedDataProject, setSelectedDataProject] = useState(c?.data_project ?? "");
  const [model, setModel] = useState(c?.gemini_model ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [bucketMsg, setBucketMsg] = useState<string | null>(null);

  const dataProject = useManual ? (manualData.trim() || billingProject) : (selectedDataProject || billingProject);

  const handleSelectWorkspace = (wsId: string) => {
    setSelectedWsId(wsId);
    const ws = workspaces.find((w) => w.id === wsId);
    if (ws) {
      setSelectedDataProject(ws.gcp_project);
    }
    setMsg(null);
    setBucketMsg(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setMsg(null);
    setBucketMsg(null);
    try {
      const result = await props.onSave({
        billing_project: billingProject,
        data_project: dataProject,
        gemini_model: model.trim(),
      });
      const bs = result.bucket_status;
      if (bs) {
        if (bs.action === "exists") {
          setBucketMsg(`Bucket "${bs.bucket}" verified.`);
        } else if (bs.action === "error") {
          setBucketMsg(`Bucket warning: ${bs.error}`);
        }
      }
      setMsg("Settings saved. Reloading catalog...");
      props.onSaved();
    } catch (e) {
      setMsg(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap={20}>
      <Card title="Settings" style={{ marginTop: 20 }}>
        <Stack gap={16}>
          {/* Billing project — always shown */}
          <label style={{ fontSize: 14 }}>
            <strong>Billing Project</strong>
            <span style={{ color: "var(--wb-muted)", fontWeight: 400 }}> — GCP project for compute costs and ADC</span>
            <Input
              value={billingProject}
              onChange={setBillingProject}
              placeholder="e.g. wb-fleeting-lemon-7624"
            />
            {billingProject && (
              <div style={{ fontSize: 12, color: "var(--wb-muted)", marginTop: 4 }}>
                Profile bucket: metadata-json-{billingProject}
              </div>
            )}
          </label>

          {/* Data source toggle */}
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>Data Source</div>
            <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, cursor: "pointer" }}>
                <input type="radio" checked={!useManual} onChange={() => setUseManual(false)} />
                Workbench workspace
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, cursor: "pointer" }}>
                <input type="radio" checked={useManual} onChange={() => setUseManual(true)} />
                Custom GCP project
              </label>
            </div>
          </div>

          {/* Manual data project input */}
          {useManual && (
            <label style={{ fontSize: 14 }}>
              <strong>Data Project ID</strong>
              <span style={{ color: "var(--wb-muted)", fontWeight: 400 }}> — project whose datasets to browse</span>
              <Input
                value={manualData}
                onChange={setManualData}
                placeholder="e.g. wb-beamish-acorn-6393"
              />
            </label>
          )}

          {/* Workspace picker */}
          {!useManual && <>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Workspace</div>
            <select
              value={selectedWsId}
              onChange={(e) => handleSelectWorkspace(e.target.value)}
              style={selectStyle}
            >
              <option value="">
                {wsLoading ? "Loading workspaces..." : "Select a workspace..."}
              </option>
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name} ({ws.role})
                </option>
              ))}
            </select>
          </div>

          {selectedWs && (
            <div style={{
              display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
              padding: "10px 14px", background: "#f8f9fa", borderRadius: "var(--wb-radius)",
            }}>
              <Badge tone="info">{selectedWs.role}</Badge>
              <span style={{ fontSize: 13, color: "var(--wb-muted)", fontFamily: "monospace" }}>
                {selectedWs.gcp_project}
              </span>
            </div>
          )}

          {selectedWs && (
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Data Project</div>
              {dsLoading ? (
                <div style={{ fontSize: 13, color: "var(--wb-muted)", padding: 8 }}>Loading datasets...</div>
              ) : datasets.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {/* Default: workspace's own project */}
                  <label style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
                    border: "1px solid var(--wb-border)", borderRadius: "var(--wb-radius)",
                    cursor: "pointer",
                    background: selectedDataProject === selectedWs.gcp_project ? "#e3f2fd" : "#fff",
                  }}>
                    <input
                      type="radio"
                      name="dataProject"
                      checked={selectedDataProject === selectedWs.gcp_project}
                      onChange={() => setSelectedDataProject(selectedWs.gcp_project)}
                    />
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 500 }}>Workspace project</div>
                      <div style={{ fontSize: 12, color: "var(--wb-muted)" }}>{selectedWs.gcp_project}</div>
                    </div>
                  </label>

                  {/* Cross-project datasets */}
                  {datasets
                    .filter((d) => d.project_id !== selectedWs.gcp_project)
                    .map((d) => (
                      <label key={d.id} style={{
                        display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
                        border: "1px solid var(--wb-border)", borderRadius: "var(--wb-radius)",
                        cursor: "pointer",
                        background: selectedDataProject === d.project_id ? "#e3f2fd" : "#fff",
                      }}>
                        <input
                          type="radio"
                          name="dataProject"
                          checked={selectedDataProject === d.project_id}
                          onChange={() => setSelectedDataProject(d.project_id)}
                        />
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 14, fontWeight: 500 }}>
                            {d.dataset_id}
                            <Badge tone="neutral" >{d.type}</Badge>
                          </div>
                          <div style={{ fontSize: 12, color: "var(--wb-muted)" }}>
                            {d.project_id}
                            {d.num_tables != null && ` · ${d.num_tables} tables`}
                            {d.location && ` · ${d.location}`}
                          </div>
                        </div>
                      </label>
                    ))}
                </div>
              ) : (
                <div style={{ fontSize: 13, color: "var(--wb-muted)", padding: 8 }}>
                  No BQ datasets found. Using workspace project: {selectedWs.gcp_project}
                </div>
              )}
            </div>
          )}
          </>}

          {/* Gemini model */}
          <label style={{ fontSize: 14 }}>
            <strong>Gemini Model</strong> (leave blank for auto-detect)
            <Input
              value={model}
              onChange={setModel}
              placeholder="e.g. gemini-2.5-flash"
            />
          </label>

          {/* Save */}
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <Button variant="primary" onClick={handleSave} disabled={saving || !billingProject}>
              {saving ? "Saving..." : "Save & reload"}
            </Button>
            {msg && <span style={{ fontSize: 14 }}>{msg}</span>}
          </div>
          {bucketMsg && (
            <div
              style={{
                fontSize: 14,
                padding: "8px 12px",
                borderRadius: "var(--wb-radius)",
                background: bucketMsg.includes("warning") ? "#ffebe9" : "#dafbe1",
                color: bucketMsg.includes("warning") ? "var(--wb-danger)" : "var(--wb-success)",
              }}
            >
              {bucketMsg}
            </div>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}
