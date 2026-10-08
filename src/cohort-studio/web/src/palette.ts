// Chart palettes. Each is single-hue: the full cohort renders in the muted
// tint, the filtered cohort in the accent, and heatmaps use the 4-step ramp.
// Accents are dark enough to clear 3:1 on the light chart surface.
export interface Palette {
  accent: string;
  muted: string;
  ramp: [string, string, string, string];
}

export const PALETTES: Record<string, Palette> = {
  verily: { accent: "#087a6a", muted: "#cfe0dc",
            ramp: ["#e4f0ed", "#9fc9c0", "#087a6a", "#054f45"] },
  indigo: { accent: "#4a3aa7", muted: "#d7d3ec",
            ramp: ["#ece9f6", "#b3a9df", "#4a3aa7", "#2e2470"] },
  amber:  { accent: "#b06a00", muted: "#f0dcbd",
            ramp: ["#fbeed6", "#e6c389", "#b06a00", "#7a4900"] },
  crimson:{ accent: "#b23a48", muted: "#eccdd1",
            ramp: ["#f7e3e6", "#dca3ab", "#b23a48", "#7d2832"] },
  slate:  { accent: "#3f5a73", muted: "#d2dae2",
            ramp: ["#e8edf1", "#a7b8c7", "#3f5a73", "#293b4d"] },
};

export const PALETTE_NAMES = Object.keys(PALETTES);

export const getPalette = (name: string): Palette =>
  PALETTES[name] ?? PALETTES.verily;
