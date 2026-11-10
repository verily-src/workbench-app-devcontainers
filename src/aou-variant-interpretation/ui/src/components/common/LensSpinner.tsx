import { useId, useState, type SVGProps } from "react";
import colors from "../../libs/colors";
import { useMediaQuery } from "../../libs/hooks";

/**
 * VIA's logo, scanning: the rungs under the lens scroll up through the glass as if the lens were
 * reading along a strand. Every fourth rung is green, and each green one rests at the centre for a
 * moment, as if the lens had found the variant, before the scan moves on.
 *
 * At rest (first paint, and whenever the user prefers reduced motion) it is exactly the logo in
 * public/favicon.svg: three rungs under the glass, the green one in the middle.
 *
 * The motion is a CSS animation (animate-lens-scan in style.css), so it runs off the compositor and
 * never re-renders React. Every spinner's animation is offset to the same wall clock, so spinners
 * mounted at different moments still scan in step.
 */

// Geometry in the logo's 64-unit box: the lens centred at (27, 27), its glass a radius-12 circle
// inside the ring.
const CX = 27;
const CY = 27;
const GLASS = 12;
const RUNG_GAP = 6;
/** One scan step: the distance from one green rung to the next. Must match via-lens-scan's travel. */
const GREEN_EVERY = 4;
/** Half-widths as in the logo: the green rung spans more of the glass than the white ones. */
const GREEN_HALF = 9;
const WHITE_HALF = 7;
// Enough rungs to fill the glass from the start of a step to its end: two above the centre, and the
// rest down to one full step below the glass's bottom edge.
const RUNG_INDEXES = Array.from({ length: 9 }, (_, i) => i - 2);

export interface LensSpinnerProps extends Omit<SVGProps<SVGSVGElement>, "width" | "height" | "children"> {
  /** Rendered width and height in px. Default 48. */
  size?: number;
  /** Milliseconds per scan step, from one green rung to the next. Default 1800. */
  duration?: number;
  /** Announced by screen readers. Default "Loading". */
  label?: string;
}

export default function LensSpinner({ size = 48, duration = 1800, label = "Loading", ...rest }: LensSpinnerProps) {
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  // Offset into the cycle by the wall clock, so every spinner on the page shares one phase.
  const [delay] = useState(() => -(performance.now() % duration));
  const clipId = `lens-glass-${useId().replace(/:/g, "")}`;

  return (
    <svg
      role="status"
      aria-label={label}
      viewBox="0 0 64 64"
      width={size}
      height={size}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...rest}
    >
      <defs>
        <clipPath id={clipId}>
          <circle cx={CX} cy={CY} r={GLASS} />
        </clipPath>
      </defs>
      <rect width="64" height="64" rx="15" fill={colors.brandNavy} />
      <g clipPath={`url(#${clipId})`}>
        <g
          data-part="rungs"
          className={reduceMotion ? undefined : "animate-lens-scan"}
          style={reduceMotion ? undefined : { animationDuration: `${duration}ms`, animationDelay: `${delay}ms` }}
        >
          {RUNG_INDEXES.map((k) => {
            const green = k % GREEN_EVERY === 0;
            const half = green ? GREEN_HALF : WHITE_HALF;
            const y = CY + k * RUNG_GAP;
            return (
              <line
                key={k}
                data-green={green || undefined}
                x1={CX - half}
                y1={y}
                x2={CX + half}
                y2={y}
                stroke={green ? colors.brandGreen : colors.white}
                strokeWidth={green ? 3.8 : 2.4}
                strokeOpacity={green ? 1 : 0.7}
                strokeLinecap="round"
              />
            );
          })}
        </g>
      </g>
      <circle cx={CX} cy={CY} r={14} stroke={colors.white} strokeWidth={4} />
      <line x1="37.5" y1="37.5" x2="50" y2="50" stroke={colors.white} strokeWidth={5.5} strokeLinecap="round" />
    </svg>
  );
}
