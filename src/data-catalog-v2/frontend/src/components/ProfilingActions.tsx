import { useState } from "react";
import { triggerSemantic, triggerTechnical } from "../hooks/useProfiles";
import { Button, Stack } from "./rds";

export function ProfilingActions(props: {
  project: string;
  dataset: string;
  table: string;
  status: { technical: string; semantic: string } | null;
  onTriggered: () => void;
  kind: "technical" | "semantic";
}) {
  const [msg, setMsg] = useState<string | null>(null);
  const tech = props.status?.technical ?? "none";
  const sem = props.status?.semantic ?? "none";

  if (props.kind === "technical") {
    return (
      <div style={{ marginBottom: 16 }}>
        <Stack gap={8}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <Button
              variant="primary"
              size="sm"
              disabled={tech === "running"}
              onClick={async () => {
                setMsg(null);
                try {
                  await triggerTechnical(props.project, props.dataset, props.table);
                  props.onTriggered();
                  setMsg("Technical profiling started.");
                } catch (e) {
                  setMsg(String(e));
                }
              }}
            >
              {tech === "running" ? "Running…" : tech === "available" ? "Re-run technical profiling" : "Run technical profiling"}
            </Button>
            {tech === "running" ? (
              <span style={{ fontSize: 13, color: "var(--wb-primary)" }}>Profiling in progress…</span>
            ) : null}
            {msg ? <span style={{ fontSize: 13 }}>{msg}</span> : null}
          </div>
        </Stack>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <Stack gap={8}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <Button
            variant="primary"
            size="sm"
            disabled={sem === "running" || tech !== "available"}
            onClick={async () => {
              setMsg(null);
              try {
                await triggerSemantic(props.project, props.dataset, props.table);
                props.onTriggered();
                setMsg("Semantic profiling started.");
              } catch (e) {
                setMsg(String(e));
              }
            }}
          >
            {sem === "running" ? "Running…" : sem === "available" ? "Re-run semantic profiling" : "Run semantic profiling"}
          </Button>
          {tech !== "available" ? (
            <span style={{ fontSize: 13, color: "var(--wb-warning)" }}>Run technical profiling first</span>
          ) : null}
          {sem === "running" ? (
            <span style={{ fontSize: 13, color: "var(--wb-primary)" }}>Profiling in progress…</span>
          ) : null}
          {msg ? <span style={{ fontSize: 13 }}>{msg}</span> : null}
        </div>
      </Stack>
    </div>
  );
}
