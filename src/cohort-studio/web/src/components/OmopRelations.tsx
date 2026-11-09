import { useEffect, useState } from "react";
import { api } from "../api";
import type { OmopRelations as Relations, SourceRef } from "../types";

export function OmopRelations({ source }: { source: Extract<SourceRef, { kind: "omop_cohort" }> }) {
  const [data, setData] = useState<Relations | null>(null);
  const [error, setError] = useState("");
  const key = JSON.stringify(source);

  useEffect(() => {
    let current = true;
    setData(null); setError("");
    api.omopRelations(JSON.parse(key) as Extract<SourceRef, { kind: "omop_cohort" }>)
      .then((result) => { if (current) setData(result); })
      .catch((e) => { if (current) setError((e as Error).message); });
    return () => { current = false; };
  }, [key]);

  return <section className="jc-omop-relations" role="region" aria-label="OMOP cohort relations">
    <div className="jc-omop-relations-head"><strong>OMOP cohort relations</strong><span>Read-only · defined by cohort criteria</span></div>
    {error ? <p role="alert">Could not load relations: {error}</p> : !data ? <p role="status">Loading relations…</p> :
      <div className="jc-omop-relations-list">
        <div className="jc-omop-start">Start: <strong>{data.start}</strong></div>
        {data.relations.map((relation, index) => <div className="jc-omop-relation" key={index}>
          <span className="jc-omop-table">{relation.left}</span>
          <span className="jc-omop-edge"><strong>{relation.operation} →</strong><span>{relation.condition}</span></span>
          <span className="jc-omop-table">{relation.right}{relation.detail && <small>{relation.detail}</small>}</span>
        </div>)}
      </div>}
  </section>;
}
