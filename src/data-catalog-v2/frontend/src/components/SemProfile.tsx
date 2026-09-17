import { useCallback, useState } from "react";
import type { SemProfile, SemColumn } from "../types/profile";
import { Badge, Button, Card, Stack } from "./rds";

function sensTone(s: string): "neutral" | "info" | "success" | "warn" | "danger" {
  if (s === "PHI") return "danger";
  if (s === "PII") return "warn";
  if (s === "UID") return "info";
  return "neutral";
}

function confTone(c: string): "success" | "warn" | "danger" | "neutral" {
  if (c === "high") return "success";
  if (c === "medium") return "warn";
  if (c === "low") return "danger";
  return "neutral";
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 10px",
  borderBottom: "2px solid var(--wb-border)",
  fontSize: 12,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.03em",
  color: "var(--wb-muted)",
  whiteSpace: "nowrap",
};

const td: React.CSSProperties = {
  padding: "8px 10px",
  borderBottom: "1px solid var(--wb-border)",
  verticalAlign: "top",
  fontSize: 13,
};

function StatPair(props: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8, fontSize: 14 }}>
      <span style={{ color: "var(--wb-muted)", minWidth: 120 }}>{props.label}</span>
      <span style={{ fontWeight: 500 }}>{props.value}</span>
    </div>
  );
}

function ValidationBanner(props: { validation: SemProfile["validation"] }) {
  const v = props.validation;
  const hasIssues = (v.issues?.length ?? 0) > 0;
  const hasWarnings = (v.warnings?.length ?? 0) > 0;

  if (v.status === "pass" && !hasWarnings) {
    return (
      <div style={{
        padding: "8px 14px", borderRadius: "var(--wb-radius)",
        background: "#dafbe1", color: "#1a7f37", fontSize: 13,
      }}>
        Validation passed
      </div>
    );
  }

  if (v.status === "warning" || (!hasIssues && hasWarnings)) {
    return (
      <div style={{
        padding: "10px 14px", borderRadius: "var(--wb-radius)",
        background: "#fff8e1", border: "1px solid #ffe082", fontSize: 13,
      }}>
        <strong style={{ color: "#e65100" }}>Warnings</strong>
        <ul style={{ margin: "6px 0 0", paddingLeft: 20, color: "#795548" }}>
          {v.warnings?.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      </div>
    );
  }

  return (
    <div style={{
      padding: "10px 14px", borderRadius: "var(--wb-radius)",
      background: "#ffebe9", border: "1px solid #ffcdd2", fontSize: 13,
    }}>
      <strong style={{ color: "var(--wb-danger)" }}>Issues</strong>
      <ul style={{ margin: "6px 0 0", paddingLeft: 20 }}>
        {v.issues?.map((issue, i) => <li key={i}>{issue}</li>)}
      </ul>
      {hasWarnings ? (
        <>
          <strong style={{ color: "#e65100", display: "block", marginTop: 8 }}>Warnings</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 20, color: "#795548" }}>
            {v.warnings?.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </>
      ) : null}
    </div>
  );
}

function DomainBadge(props: { domain?: SemProfile["semantic_domain"] }) {
  const d = props.domain;
  if (!d || !d.primary) return <span style={{ color: "var(--wb-muted)" }}>—</span>;
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <Badge tone="info">{d.primary}</Badge>
      {d.sub_domain ? (
        <span style={{ fontSize: 13, color: "var(--wb-text)" }}>{d.sub_domain}</span>
      ) : null}
    </span>
  );
}

function PrimaryKeyDisplay(props: { pk?: SemProfile["primary_key"] }) {
  const pk = props.pk;
  if (!pk || !pk.columns?.length || pk.pk_type === "none" || pk.pk_type === "") {
    return <span style={{ color: "var(--wb-muted)" }}>Not identified</span>;
  }
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      {pk.columns.map((col) => (
        <Badge key={col} tone="neutral">{col}</Badge>
      ))}
      <span style={{ fontSize: 12, color: "var(--wb-muted)" }}>
        ({pk.pk_type}, {pk.confidence} confidence)
      </span>
    </span>
  );
}

// ── P3-2: Entity Anchor Display ────────────────────────────────────────────

function EntityDisplay(props: { anchor?: string; type?: string }) {
  if (!props.anchor) return <span style={{ color: "var(--wb-muted)" }}>—</span>;
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <Badge tone="info">{props.anchor}</Badge>
      {props.type && (
        <span style={{ fontSize: 12, color: "var(--wb-muted)" }}>({props.type})</span>
      )}
    </span>
  );
}

// ── P3-3: Concept Binding Badge ────────────────────────────────────────────

const cbStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: "2px 8px",
  borderRadius: 4,
  fontSize: 11,
  fontWeight: 500,
  lineHeight: "18px",
  marginBottom: 2,
};

function systemShortName(uri: string): string {
  if (uri.includes("loinc")) return "LOINC";
  if (uri.includes("snomed") || uri.includes("sct")) return "SNOMED";
  if (uri.includes("icd-10")) return "ICD-10";
  if (uri.includes("rxnorm")) return "RxNorm";
  if (uri.includes("ndc")) return "NDC";
  if (uri.includes("cpt")) return "CPT";
  if (uri.includes("verily:custom")) return "Custom";
  return uri.split("/").pop() || uri;
}

function ConceptBindingBadge(props: { col: SemColumn }) {
  const cb = props.col.concept_binding;
  const csb = props.col.code_system_binding;

  if (cb && cb.system && cb.code) {
    return (
      <div>
        <span style={{ ...cbStyle, background: "#e3f2fd", color: "#1565c0" }}>
          {systemShortName(cb.system)}:{cb.code}
        </span>
        {cb.display && (
          <div style={{ fontSize: 11, color: "var(--wb-muted)", marginTop: 1 }}>{cb.display}</div>
        )}
      </div>
    );
  }

  if (csb && csb.system) {
    return (
      <div>
        <span style={{ ...cbStyle, background: "#fff3e0", color: "#e65100" }}>
          {systemShortName(csb.system)}
        </span>
        {csb.display && (
          <div style={{ fontSize: 11, color: "var(--wb-muted)", marginTop: 1 }}>{csb.display}</div>
        )}
      </div>
    );
  }

  if (props.col.terminology_bindings?.length > 0) {
    return (
      <>
        {props.col.terminology_bindings.slice(0, 2).map((b) => (
          <div key={`${b.system}-${b.code}`} style={{ marginBottom: 2, fontSize: 12 }}>
            <strong>{b.display}</strong>{" "}
            <span style={{ color: "var(--wb-muted)" }}>
              ({systemShortName(b.system)}: {b.code})
            </span>
          </div>
        ))}
      </>
    );
  }

  return <span style={{ color: "var(--wb-muted)" }}>—</span>;
}

// ── P3-3: Measurement Method Badge ─────────────────────────────────────────

const methodColors: Record<string, { bg: string; fg: string }> = {
  "self-reported": { bg: "#f3e5f5", fg: "#7b1fa2" },
  "lab-measured": { bg: "#e8f5e9", fg: "#2e7d32" },
  "device-collected": { bg: "#e0f7fa", fg: "#00695c" },
  "calculated": { bg: "#fce4ec", fg: "#c62828" },
  "administrative": { bg: "#efebe9", fg: "#4e342e" },
};

function MeasurementMethodBadge(props: { method?: string }) {
  if (!props.method) return null;
  const style = methodColors[props.method] || { bg: "#f5f5f5", fg: "#616161" };
  return (
    <span style={{
      ...cbStyle,
      background: style.bg,
      color: style.fg,
    }}>
      {props.method}
    </span>
  );
}

// ── P3-4: Value Set Popover ────────────────────────────────────────────────

function ValueSetTag(props: { values: string[]; columnName: string }) {
  const [open, setOpen] = useState(false);
  if (!props.values || props.values.length === 0) return null;

  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <span
        onClick={() => setOpen(!open)}
        style={{
          ...cbStyle,
          background: "#e8eaf6",
          color: "#283593",
          cursor: "pointer",
          border: "1px solid #c5cae9",
        }}
      >
        Cohort Filter
        <span style={{ fontSize: 10, opacity: 0.7 }}>({props.values.length})</span>
      </span>
      {open && (
        <div style={{
          position: "absolute",
          top: "100%",
          left: 0,
          zIndex: 100,
          background: "#fff",
          border: "1px solid var(--wb-border)",
          borderRadius: 6,
          boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
          padding: "10px 14px",
          minWidth: 180,
          maxWidth: 300,
          marginTop: 4,
          fontSize: 12,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 6, color: "var(--wb-muted)" }}>
            Values for {props.columnName}
          </div>
          {props.values.slice(0, 15).map((v) => (
            <div key={v} style={{ padding: "2px 0" }}>{v}</div>
          ))}
          {props.values.length > 15 && (
            <div style={{ color: "var(--wb-muted)", marginTop: 4 }}>
              +{props.values.length - 15} more
            </div>
          )}
          <div
            onClick={() => setOpen(false)}
            style={{ marginTop: 8, color: "#283593", cursor: "pointer", fontSize: 11 }}
          >
            Close
          </div>
        </div>
      )}
    </span>
  );
}

// ── P3-5: Concepts Summary Panel ───────────────────────────────────────────

function ConceptsSummaryPanel(props: { data: SemProfile }) {
  const [expanded, setExpanded] = useState(false);
  const d = props.data;

  const fixedBindings: { col: string; system: string; code: string; display: string }[] = [];
  const codeSystemBindings: { col: string; system: string; display: string }[] = [];
  const cohortDims: { col: string; values: string[] }[] = [];

  for (const c of d.columns) {
    if (c.concept_binding?.system && c.concept_binding?.code) {
      fixedBindings.push({
        col: c.name,
        system: systemShortName(c.concept_binding.system),
        code: c.concept_binding.code,
        display: c.concept_binding.display,
      });
    }
    if (c.code_system_binding?.system) {
      codeSystemBindings.push({
        col: c.name,
        system: systemShortName(c.code_system_binding.system),
        display: c.code_system_binding.display,
      });
    }
  }

  if (d.cohort_dimensions) {
    for (const dim of d.cohort_dimensions) {
      const col = d.columns.find((c) => c.name === dim);
      cohortDims.push({ col: dim, values: col?.value_set_binding || [] });
    }
  }

  const total = fixedBindings.length + codeSystemBindings.length + cohortDims.length;
  if (total === 0) return null;

  return (
    <Card title="Terminology">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            background: "none",
            border: "1px solid var(--wb-border)",
            borderRadius: 4,
            padding: "2px 10px",
            fontSize: 11,
            cursor: "pointer",
            color: "var(--wb-muted)",
          }}
        >
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>
      {!expanded ? (
        <div style={{ fontSize: 13, color: "var(--wb-muted)" }}>
          {fixedBindings.length > 0 && <span>{fixedBindings.length} standard term{fixedBindings.length > 1 ? "s" : ""}</span>}
          {fixedBindings.length > 0 && codeSystemBindings.length > 0 && " · "}
          {codeSystemBindings.length > 0 && <span>{codeSystemBindings.length} code system{codeSystemBindings.length > 1 ? "s" : ""}</span>}
          {(fixedBindings.length > 0 || codeSystemBindings.length > 0) && cohortDims.length > 0 && " · "}
          {cohortDims.length > 0 && <span>{cohortDims.length} cohort dimension{cohortDims.length > 1 ? "s" : ""}</span>}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {fixedBindings.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1565c0", marginBottom: 6 }}>
                Standard Terms ({fixedBindings.length})
              </div>
              {fixedBindings.map((b) => (
                <div key={b.col} style={{ fontSize: 12, padding: "3px 0", display: "flex", gap: 8 }}>
                  <span style={{ ...cbStyle, background: "#e3f2fd", color: "#1565c0" }}>
                    {b.system}:{b.code}
                  </span>
                  <span style={{ color: "var(--wb-text)" }}>{b.display}</span>
                  <span style={{ color: "var(--wb-muted)" }}>→ {b.col}</span>
                </div>
              ))}
            </div>
          )}

          {codeSystemBindings.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#e65100", marginBottom: 6 }}>
                Code Systems ({codeSystemBindings.length})
              </div>
              {codeSystemBindings.map((b) => (
                <div key={b.col} style={{ fontSize: 12, padding: "3px 0", display: "flex", gap: 8 }}>
                  <span style={{ ...cbStyle, background: "#fff3e0", color: "#e65100" }}>
                    {b.system}
                  </span>
                  <span style={{ color: "var(--wb-text)" }}>{b.display}</span>
                  <span style={{ color: "var(--wb-muted)" }}>→ {b.col}</span>
                </div>
              ))}
            </div>
          )}

          {cohortDims.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#283593", marginBottom: 6 }}>
                Cohort Dimensions ({cohortDims.length})
              </div>
              {cohortDims.map((cd) => (
                <div key={cd.col} style={{ fontSize: 12, padding: "3px 0" }}>
                  <span style={{ fontWeight: 500 }}>{cd.col}</span>
                  {cd.values.length > 0 && (
                    <span style={{ color: "var(--wb-muted)", marginLeft: 8 }}>
                      {cd.values.slice(0, 6).join(", ")}
                      {cd.values.length > 6 ? ` +${cd.values.length - 6} more` : ""}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ── P3-6: Structural Links Display ─────────────────────────────────────────

function StructuralLinksPanel(props: { links?: SemProfile["structural_links"] }) {
  if (!props.links || props.links.length === 0) return null;

  const linkTypeColors: Record<string, { bg: string; fg: string }> = {
    entity_key: { bg: "#e3f2fd", fg: "#1565c0" },
    foreign_key: { bg: "#f3e5f5", fg: "#7b1fa2" },
    shared_dimension: { bg: "#fff3e0", fg: "#e65100" },
    temporal: { bg: "#e0f7fa", fg: "#00695c" },
  };

  return (
    <Card title={`Structural Links (${props.links.length})`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {props.links.map((sl, i) => {
          const colors = linkTypeColors[sl.link_type] || { bg: "#f5f5f5", fg: "#616161" };
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, padding: "4px 0" }}>
              <span style={{ fontWeight: 500, minWidth: 100 }}>{sl.source_column}</span>
              <span style={{ color: "var(--wb-muted)" }}>→</span>
              <span style={{ fontFamily: "monospace", fontSize: 11 }}>
                {sl.target_table}.{sl.target_column}
              </span>
              <span style={{ ...cbStyle, background: colors.bg, color: colors.fg }}>
                {sl.link_type}
              </span>
              <span style={{ fontSize: 11, color: "var(--wb-muted)" }}>
                {sl.cardinality}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ── Inline edit helpers ────────────────────────────────────────────────────

const METHODS = ["", "self-reported", "clinician-reported", "lab-measured", "device-collected", "derived", "administrative"];
const SENSITIVITIES = ["", "PHI", "PII", "UID"];
const CONFIDENCES = ["high", "medium", "low"];

const cellSelect: React.CSSProperties = {
  padding: "4px 6px",
  borderRadius: 4,
  border: "1px solid var(--wb-border)",
  fontSize: 12,
  fontFamily: "var(--wb-font)",
  background: "#fff",
  width: "100%",
};

const cellInput: React.CSSProperties = {
  ...cellSelect,
  outline: "none",
};

// ── Main Component ─────────────────────────────────────────────────────────

export function SemProfileView(props: {
  data: SemProfile | null;
  loading?: boolean;
  onSave?: (columns: SemColumn[]) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editCols, setEditCols] = useState<SemColumn[]>([]);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const startEdit = useCallback(() => {
    if (!props.data) return;
    setEditCols(props.data.columns.map((c) => ({ ...c })));
    setEditing(true);
    setSaveErr(null);
  }, [props.data]);

  const cancelEdit = useCallback(() => {
    setEditing(false);
    setEditCols([]);
    setSaveErr(null);
  }, []);

  const updateCol = useCallback((idx: number, field: keyof SemColumn, value: string) => {
    setEditCols((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
  }, []);

  const handleSave = useCallback(async () => {
    if (!props.onSave) return;
    setSaving(true);
    setSaveErr(null);
    try {
      await props.onSave(editCols);
      setEditing(false);
      setEditCols([]);
    } catch (e) {
      setSaveErr(String(e));
    } finally {
      setSaving(false);
    }
  }, [props.onSave, editCols]);

  if (props.loading) return <p>Loading semantic profile...</p>;
  if (!props.data) return <p style={{ color: "var(--wb-muted)" }}>No semantic profile yet.</p>;

  const d = props.data;
  const cohortSet = new Set(d.cohort_dimensions || []);
  const rows = editing ? editCols : d.columns;

  return (
    <Stack gap={16}>
      <Card title="Semantic profile">
        <div style={{ display: "flex", flexWrap: "wrap", gap: "12px 40px", marginBottom: 16 }}>
          <StatPair label="Table" value={d.table} />
          <StatPair label="Profiled at" value={d.profiled_at ? new Date(d.profiled_at).toLocaleString() : "—"} />
          <StatPair label="Model" value={d.model_used || "—"} />
          <StatPair label="Columns" value={d.columns.length} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 }}>
          <StatPair label="Primary Key" value={<PrimaryKeyDisplay pk={d.primary_key} />} />
          <StatPair label="Granularity" value={d.granularity || <span style={{ color: "var(--wb-muted)" }}>Not determined</span>} />
          <StatPair label="Semantic Domain" value={<DomainBadge domain={d.semantic_domain} />} />
          <StatPair label="Entity Anchor" value={<EntityDisplay anchor={d.entity_anchor} type={d.entity_type} />} />
        </div>

        <ValidationBanner validation={d.validation} />
      </Card>

      <ConceptsSummaryPanel data={d} />

      <StructuralLinksPanel links={d.structural_links} />

      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "var(--wb-text)" }}>Column semantics</h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {saveErr && <span style={{ fontSize: 12, color: "var(--wb-danger)" }}>Save failed</span>}
            {editing ? (
              <>
                <Button size="sm" variant="ghost" onClick={cancelEdit} disabled={saving}>Cancel</Button>
                <Button size="sm" variant="primary" onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Save"}
                </Button>
              </>
            ) : (
              props.onSave && <Button size="sm" onClick={startEdit}>Edit</Button>
            )}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                {["Column", "Definition", "Terminology", "Method", "Unit", "Sensitivity", "Cohort", "Confidence"].map((h) => (
                  <th key={h} style={th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={c.name}>
                  <td style={{ ...td, fontWeight: 600, whiteSpace: "nowrap" }}>{c.name}</td>

                  {/* Definition */}
                  <td style={{ ...td, minWidth: 200 }}>
                    {editing ? (
                      <textarea
                        value={c.definition}
                        onChange={(e) => updateCol(i, "definition", e.target.value)}
                        rows={2}
                        style={{ ...cellInput, resize: "vertical", minHeight: 40, width: "100%" }}
                      />
                    ) : (
                      <span style={{ lineHeight: 1.5 }}>{c.definition}</span>
                    )}
                  </td>

                  {/* Terminology — always read-only */}
                  <td style={{ ...td, minWidth: 160 }}>
                    <ConceptBindingBadge col={c} />
                  </td>

                  {/* Method */}
                  <td style={td}>
                    {editing ? (
                      <select
                        value={c.measurement_method || ""}
                        onChange={(e) => updateCol(i, "measurement_method", e.target.value)}
                        style={cellSelect}
                      >
                        {METHODS.map((m) => (
                          <option key={m} value={m}>{m || "—"}</option>
                        ))}
                      </select>
                    ) : (
                      <MeasurementMethodBadge method={c.measurement_method} />
                    )}
                  </td>

                  {/* Unit */}
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    {editing ? (
                      <input
                        value={c.unit_of_measure || ""}
                        onChange={(e) => updateCol(i, "unit_of_measure", e.target.value)}
                        style={{ ...cellInput, width: 80 }}
                      />
                    ) : c.unit_of_measure ? (
                      <Badge tone="info">{c.unit_of_measure}</Badge>
                    ) : (
                      <span style={{ color: "var(--wb-muted)" }}>—</span>
                    )}
                  </td>

                  {/* Sensitivity */}
                  <td style={td}>
                    {editing ? (
                      <select
                        value={c.sensitivity || ""}
                        onChange={(e) => updateCol(i, "sensitivity", e.target.value)}
                        style={cellSelect}
                      >
                        {SENSITIVITIES.map((s) => (
                          <option key={s} value={s}>{s || "—"}</option>
                        ))}
                      </select>
                    ) : c.sensitivity ? (
                      <Badge tone={sensTone(c.sensitivity)}>{c.sensitivity}</Badge>
                    ) : (
                      "—"
                    )}
                  </td>

                  {/* Cohort — always read-only */}
                  <td style={td}>
                    {cohortSet.has(c.name) ? (
                      <ValueSetTag values={c.value_set_binding || []} columnName={c.name} />
                    ) : "—"}
                  </td>

                  {/* Confidence */}
                  <td style={td}>
                    {editing ? (
                      <select
                        value={c.confidence}
                        onChange={(e) => updateCol(i, "confidence", e.target.value)}
                        style={cellSelect}
                      >
                        {CONFIDENCES.map((v) => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>
                    ) : (
                      <Badge tone={confTone(c.confidence)}>{c.confidence}</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </Stack>
  );
}
