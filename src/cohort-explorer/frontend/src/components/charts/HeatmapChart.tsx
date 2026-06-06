import { useCallback, useMemo, useRef, useState } from "react";
import { Box, Tooltip, Typography } from "@mui/material";
import type { SampleRow } from "../../types";
import { FIELD_META } from "../../types";

interface Props {
  rows: SampleRow[];
  xField: string;
  yField: string;
  xLabel: string;
  yLabel: string;
  onCellClick?: (xValue: string, yValue: string) => void;
  onRangeSelect?: (xValues: string[], yValues: string[]) => void;
}

function interpolateColor(ratio: number): string {
  const r = Math.round(255 - (255 - 8) * ratio);
  const g = Math.round(255 - (255 - 122) * ratio);
  const b = Math.round(255 - (255 - 106) * ratio);
  return `rgb(${r},${g},${b})`;
}

function binNumericValues(values: (number | null)[], binCount = 10): { labels: string[]; assign: (v: number) => string } {
  const valid = values.filter((v): v is number => v !== null);
  if (valid.length === 0) return { labels: [], assign: () => "" };
  const sorted = [...valid].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  if (min === max) return { labels: [String(min)], assign: () => String(min) };
  const width = (max - min) / binCount;
  const labels = Array.from({ length: binCount }, (_, i) =>
    `${(min + i * width).toFixed(1)}–${(min + (i + 1) * width).toFixed(1)}`,
  );
  return {
    labels,
    assign: (v: number) => {
      const idx = Math.min(Math.floor((v - min) / width), binCount - 1);
      return labels[idx];
    },
  };
}

export default function HeatmapChart({ rows, xField, yField, xLabel, yLabel, onCellClick, onRangeSelect }: Props) {
  const [dragStart, setDragStart] = useState<{ xi: number; yi: number } | null>(null);
  const [dragEnd, setDragEnd] = useState<{ xi: number; yi: number } | null>(null);
  const isDragging = useRef(false);

  const xMeta = FIELD_META.find((f) => f.key === xField);
  const yMeta = FIELD_META.find((f) => f.key === yField);
  const xIsNumeric = xMeta?.dataType === "numeric";
  const yIsNumeric = yMeta?.dataType === "numeric";

  const { xCategories, yCategories, grid, maxCount } = useMemo(() => {
    const xKey = xField as keyof SampleRow;
    const yKey = yField as keyof SampleRow;

    const xBinner = xIsNumeric ? binNumericValues(rows.map((r) => r[xKey] as number | null)) : null;
    const yBinner = yIsNumeric ? binNumericValues(rows.map((r) => r[yKey] as number | null)) : null;

    const counts = new Map<string, number>();
    const xSet = new Set<string>();
    const ySet = new Set<string>();

    for (const r of rows) {
      const rawX = r[xKey];
      const rawY = r[yKey];
      if (rawX === null || rawY === null) continue;
      const xVal = xBinner ? xBinner.assign(rawX as number) : String(rawX);
      const yVal = yBinner ? yBinner.assign(rawY as number) : String(rawY);
      if (!xVal || !yVal) continue;
      xSet.add(xVal);
      ySet.add(yVal);
      const key = `${xVal}\0${yVal}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }

    const xCats = xBinner ? xBinner.labels.filter((l) => xSet.has(l)) : [...xSet].sort();
    const yCats = yBinner ? yBinner.labels.filter((l) => ySet.has(l)) : [...ySet].sort();
    let max = 0;

    const g: number[][] = yCats.map((y) =>
      xCats.map((x) => {
        const c = counts.get(`${x}\0${y}`) ?? 0;
        if (c > max) max = c;
        return c;
      }),
    );

    return { xCategories: xCats, yCategories: yCats, grid: g, maxCount: max };
  }, [rows, xField, yField, xIsNumeric, yIsNumeric]);

  const selMinX = dragStart && dragEnd ? Math.min(dragStart.xi, dragEnd.xi) : -1;
  const selMaxX = dragStart && dragEnd ? Math.max(dragStart.xi, dragEnd.xi) : -1;
  const selMinY = dragStart && dragEnd ? Math.min(dragStart.yi, dragEnd.yi) : -1;
  const selMaxY = dragStart && dragEnd ? Math.max(dragStart.yi, dragEnd.yi) : -1;

  const handleMouseUp = useCallback(() => {
    if (isDragging.current && dragStart && dragEnd && onRangeSelect) {
      const x0 = Math.min(dragStart.xi, dragEnd.xi);
      const x1 = Math.max(dragStart.xi, dragEnd.xi);
      const y0 = Math.min(dragStart.yi, dragEnd.yi);
      const y1 = Math.max(dragStart.yi, dragEnd.yi);
      const xVals = xCategories.slice(x0, x1 + 1);
      const yVals = yCategories.slice(y0, y1 + 1);
      onRangeSelect(xVals, yVals);
    }
    isDragging.current = false;
    setDragStart(null);
    setDragEnd(null);
  }, [dragStart, dragEnd, xCategories, yCategories, onRangeSelect]);

  if (xCategories.length === 0 || yCategories.length === 0) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        No data
      </Box>
    );
  }

  const cellSize = Math.max(16, Math.min(40, 400 / Math.max(xCategories.length, yCategories.length)));

  return (
    <Box
      sx={{ flex: 1, minHeight: 0, overflow: "auto", p: 1.5, userSelect: "none" }}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
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
              const inSelection = xi >= selMinX && xi <= selMaxX && yi >= selMinY && yi <= selMaxY;
              return (
                <Tooltip key={x} title={`${y} × ${x}: ${count}`} arrow>
                  <Box
                    onMouseDown={() => {
                      isDragging.current = true;
                      setDragStart({ xi, yi });
                      setDragEnd({ xi, yi });
                    }}
                    onMouseEnter={() => {
                      if (isDragging.current) setDragEnd({ xi, yi });
                    }}
                    onClick={() => onCellClick?.(x, y)}
                    sx={{
                      width: cellSize,
                      height: cellSize,
                      bgcolor: count > 0 ? interpolateColor(ratio) : "#f5f5f5",
                      border: inSelection ? "2px solid #054f45" : "1px solid white",
                      cursor: "crosshair",
                      fontSize: 9,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: ratio > 0.5 ? "white" : "#333",
                      opacity: dragStart && !inSelection ? 0.5 : 1,
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
