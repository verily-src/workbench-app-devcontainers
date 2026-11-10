import type { SVGProps } from "react";

// Shared by every icon in this directory, so a single default (24x24 viewBox, round line caps,
// currentColor stroke) doesn't need repeating in each one. `size` sets width/height together,
// since none of our icons are ever non-square; anything else (className, strokeWidth,
// aria-hidden, etc.) passes straight through to the <svg>. See README.md for the drawing rules.
export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "viewBox" | "fill" | "width" | "height"> {
  size?: number;
}

/**
 * The stroke weight for an icon drawn `size` px wide. A 2-unit stroke on the 24 grid is 1.3px at
 * 16px and under 1px at 11px, so small icons take a heavier stroke to hold their colour. Pass
 * `strokeWidth` only to break this on purpose.
 */
export function strokeWidthFor(size: number): number {
  return size <= 12 ? 2.5 : size <= 15 ? 2.25 : 2;
}

export function baseIconProps({ size = 16, strokeWidth = strokeWidthFor(size), ...rest }: IconProps): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    ...rest,
  };
}
