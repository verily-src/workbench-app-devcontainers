import { useMemo } from "react";
import { Box, Tooltip, Typography } from "@mui/material";
import type { SampleRow } from "../../types";

interface Props {
  rows: SampleRow[];
  xField: string;
  yField: string;
  xLabel: string;
  yLabel: string;
  onCellClick?: (xValue: string, yValue: string) => void;
}

function interpolateColor(ratio: number): string {
  const r = Math.round(255 - (255 - 8) * ratio);
  const g = Math.round(255 - (255 - 122) * ratio);
  const b = Math.round(255 - (255 - 106) * ratio);
  return `rgb(${r},${g},${b})`;
}

export default function HeatmapChart({ rows, xField, yField, xLabel, yLabel, onCellClick }: Props) {
  const { xCategories, yCategories, grid, maxCount } = useMemo(() => {
    const xKey = xField as keyof SampleRow;
    const yKey = yField as keyof SampleRow;

    const counts = new Map<string, number>();
    const xSet = new Set<string>();
    const ySet = new Set<string>();

    for (const r of rows) {
      const xVal = r[xKey] as string | null;
      const yVal = r[yKey] as string | null;
      if (xVal === null || yVal === null) continue;
      xSet.add(xVal);
      ySet.add(yVal);
      const key = `${xVal}\0${yVal}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }

    const xCats = [...xSet].sort();
    const yCats = [...ySet].sort();
    let max = 0;

    const g: number[][] = yCats.map((y) =>
      xCats.map((x) => {
        const c = counts.get(`${x}\0${y}`) ?? 0;
        if (c > max) max = c;
        return c;
      }),
    );

    return { xCategories: xCats, yCategories: yCats, grid: g, maxCount: max };
  }, [rows, xField, yField]);

  if (xCategories.length === 0 || yCategories.length === 0) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        No data
      </Box>
    );
  }

  const cellSize = Math.max(16, Math.min(40, 400 / Math.max(xCategories.length, yCategories.length)));

  return (
    <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", p: 1.5 }}>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
        {yLabel} vs {xLabel}
      </Typography>
      <Box sx={{ display: "inline-block" }}>
        <Box sx={{ display: "flex" }}>
          <Box sx={{ width: 100, flexShrink: 0 }} />
          {xCategories.map((x) => (
            <Box
              key={x}
              sx={{
                width: cellSize,
                fontSize: 9,
                textAlign: "center",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                transform: "rotate(-45deg)",
                transformOrigin: "bottom left",
                height: 60,
                display: "flex",
                alignItems: "flex-end",
              }}
              title={x}
            >
              {x}
            </Box>
          ))}
        </Box>
        {yCategories.map((y, yi) => (
          <Box key={y} sx={{ display: "flex", alignItems: "center" }}>
            <Typography
              variant="caption"
              sx={{
                width: 100,
                flexShrink: 0,
                textAlign: "right",
                pr: 0.5,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                fontSize: 10,
              }}
              title={y}
            >
              {y}
            </Typography>
            {xCategories.map((x, xi) => {
              const count = grid[yi][xi];
              const ratio = maxCount > 0 ? count / maxCount : 0;
              return (
                <Tooltip key={x} title={`${y} × ${x}: ${count}`} arrow>
                  <Box
                    onClick={() => onCellClick?.(x, y)}
                    sx={{
                      width: cellSize,
                      height: cellSize,
                      bgcolor: count > 0 ? interpolateColor(ratio) : "#f5f5f5",
                      border: "1px solid white",
                      cursor: onCellClick ? "pointer" : "default",
                      fontSize: 9,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: ratio > 0.5 ? "white" : "#333",
                    }}
                  >
                    {count > 0 ? count : ""}
                  </Box>
                </Tooltip>
              );
            })}
          </Box>
        ))}
      </Box>
    </Box>
  );
}
