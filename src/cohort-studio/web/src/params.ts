import type { Filter, Parameter } from "./types";

export const PARAM_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,39}$/;

/** Put each bound parameter's current value into the filters that follow it. */
export function applyParameters(filters: Filter[], parameters: Parameter[]): Filter[] {
  const byName = new Map(parameters.map((p) => [p.name, p]));
  const one = (f: Filter): Filter => {
    if (f.kind === "any") return { ...f, groups: (f.groups ?? []).map((g) => g.map(one)) };
    if (!f.param) return f;
    const next: Filter = { ...f };
    for (const bound of ["min", "max", "start", "end"] as const) {
      const name = f.param[bound];
      const p = name ? byName.get(name) : undefined;
      if (!p) continue;
      if (bound === "min" || bound === "max") next[bound] = Number(p.value);
      else next[bound] = String(p.value);
    }
    return next;
  };
  return filters.map(one);
}

/** Drop bindings to a removed parameter (the filters keep their last values). */
export function unbindParameter(filters: Filter[], name: string): Filter[] {
  const one = (f: Filter): Filter => {
    if (f.kind === "any") return { ...f, groups: (f.groups ?? []).map((g) => g.map(one)) };
    if (!f.param) return f;
    const param = Object.fromEntries(Object.entries(f.param).filter(([, v]) => v !== name));
    const { param: _drop, ...rest } = f;
    return Object.keys(param).length ? { ...rest, param } : rest;
  };
  return filters.map(one);
}
