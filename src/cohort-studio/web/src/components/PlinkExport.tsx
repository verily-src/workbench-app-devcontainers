import { useState } from "react";
import type { Dataset } from "../types";

type Field = "sample_id" | "variant_id" | "chromosome" | "position" | "reference_allele" | "alternate_allele" | "alternate_allele_count";
const FIELDS: { key: Field; label: string }[] = [
  { key: "sample_id", label: "Sample ID" }, { key: "variant_id", label: "Variant ID" },
  { key: "chromosome", label: "Chromosome" }, { key: "position", label: "Position" },
  { key: "reference_allele", label: "REF allele" }, { key: "alternate_allele", label: "ALT allele" },
  { key: "alternate_allele_count", label: "ALT hard-call count" },
];

export function PlinkExport({ dataset }: { dataset: Dataset }) {
  const [visible, setVisible] = useState(false);
  const isVcf = dataset.sourceInfo?.format === "vcf";
  const [filterPolicy, setFilterPolicy] = useState<"" | "pass_only" | "include_all">("");
  const [mapping, setMapping] = useState<Record<Field, string>>(() => Object.fromEntries(
    FIELDS.map(({key}) => [key, dataset.sourceInfo?.format === "vcf" && dataset.columns.some(c => c.name === key) ? key : ""])
  ) as Record<Field, string>);
  const [reference, setReference] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const start = async () => {
    setError(""); setBusy(true);
    try {
      const response = await fetch(`/api/datasets/${encodeURIComponent(dataset.id)}/export/plink2`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mapping: { ...mapping, genotype_encoding: "unphased_diploid_alt_hardcall", reference_build: reference },
          confirm_hardcalls: confirmed, filters: dataset.filters, ...(isVcf ? { vcf_filter_policy: filterPolicy } : {}) }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : "Check the mapping, reference build, and filters.");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "cohort.plink2.zip"; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "PLINK 2 export failed."); }
    finally { setBusy(false); }
  };
  const complete = FIELDS.every(({ key }) => mapping[key]) && reference.trim() && confirmed && (!isVcf || filterPolicy);
  return <>
    <button type="button" onClick={() => setVisible(!visible)}>{visible ? "Hide PLINK 2" : "Export PLINK 2"}</button>
    {visible && <section className="studio-agent-card" aria-label="PLINK 2 export">
      <strong>PLINK 2 archive</strong>
      <p>Disk-backed data only. Up to 100,000 calls; complete sample-by-variant matrix. Human autosomes 1–22, unphased diploid biallelic SNP hard calls only. Missing calls must be null.</p>
      <p>{isVcf ? "VCF column mappings are fixed and genotype calls are checked against ALT counts. " : "Review all mapped fields before exporting. "}Family IDs are omitted and PLINK treats them as 0. REF is provisional and not checked against a reference genome. QUAL, INFO, FILTER and phenotypes are not exported.</p>
      {FIELDS.map(({key,label}) => <label key={key}>{label} <select aria-label={label} disabled={isVcf} value={mapping[key]} onChange={e => setMapping({ ...mapping, [key]: e.target.value })}>
        <option value="">Choose a column…</option>{dataset.columns.map(c => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
      </select></label>)}
      {isVcf && <label>VCF FILTER policy <select aria-label="VCF FILTER policy" value={filterPolicy} onChange={e => setFilterPolicy(e.target.value as "" | "pass_only" | "include_all")}>
        <option value="">Choose which variants…</option><option value="pass_only">PASS variants only</option><option value="include_all">Include all, including failed and unfiltered</option>
      </select></label>}
      {isVcf && <p>VCF reference header: {dataset.sourceInfo?.reference || "not specified"}. This header and the declared build are not verified.</p>}
      <label>Reference build <input aria-label="Reference build" value={reference} onChange={e => setReference(e.target.value)} placeholder="e.g. GRCh38" /></label>
      <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> I confirm the count is unphased diploid ALT hard calls 0, 1, 2 or null.</label>
      <button type="button" className="primary" disabled={!complete || busy} onClick={() => void start()}>{busy ? "Preparing…" : "Download PLINK 2 zip"}</button>
      {error && <div role="alert">{error}</div>}
    </section>}
  </>;
}
