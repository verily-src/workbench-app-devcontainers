export interface ChartSuggestion {
  chart_type: string;
  columns: string[];
  title: string;
  rationale: string;
}

export interface ChartsSuggestResponse {
  charts: ChartSuggestion[];
}
