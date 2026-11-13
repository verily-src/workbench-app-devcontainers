import { Input, Select, Stack } from "./rds";

export function FilterBar(props: {
  search: string;
  onSearch: (v: string) => void;
  stateFilter: "all" | "none" | "tech" | "full";
  onStateFilter: (v: "all" | "none" | "tech" | "full") => void;
}) {
  return (
    <Stack gap={8}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
        <Input placeholder="Search tables…" value={props.search} onChange={props.onSearch} />
        <Select
          value={props.stateFilter}
          onChange={(v) => props.onStateFilter(v as "all" | "none" | "tech" | "full")}
          options={[
            { value: "all", label: "Profiling: All" },
            { value: "none", label: "Not profiled" },
            { value: "tech", label: "Technical only" },
            { value: "full", label: "Technical + Semantic" },
          ]}
        />
      </div>
    </Stack>
  );
}
