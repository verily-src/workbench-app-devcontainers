import type { Dataset } from "./types";

/** The database table behind a tab, when an extract could live there
 *  (extracts are written to the public schema of Aurora/PostgreSQL). */
export function extractTarget(dataset: Dataset): { kind: string; resource_id: string; table: string } | null {
  const ref = dataset.sourceRef as { kind?: string; resource_id?: string; table?: string; schema?: string } | undefined;
  if (!ref || (ref.kind !== "aurora" && ref.kind !== "postgres") || !ref.resource_id || !ref.table) return null;
  if (ref.schema && ref.schema !== "public") return null;
  return { kind: ref.kind, resource_id: ref.resource_id, table: ref.table };
}
