import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, FocusEvent, ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";
import colors from "../../libs/colors";
import { isFocusVisible } from "../../libs/hooks";
import * as Style from "../../libs/style";

// The app's one tooltip: a dark bubble with an arrow, fixed and portalled into <body> so the
// scroll containers it's used in can't clip it. InfoTooltip puts it on its circled "i"; other
// elements -- a breakdown token, say -- attach it through this hook. Spreading `anchorProps` is
// the whole wiring: hover, keyboard focus and click all show it, so no anchor can forget one.

/** Long enough that sweeping the pointer across a row of anchors doesn't flash every tooltip. */
const SHOW_DELAY_MS = 120;
/** Between the anchor and the tooltip, where the arrow sits. */
const GAP = 8;
/** Closest the tooltip comes to the window's edges. */
const EDGE = 8;
const ARROW_SIZE = 8;

const styles = {
  tooltip: {
    position: "fixed",
    zIndex: 200,
    maxWidth: 260,
    padding: "8px 10px",
    borderRadius: 6,
    background: colors.textPrimary,
    boxShadow: Style.shadows.raised,
    color: colors.white,
    fontSize: 11.5,
    fontWeight: 400,
    lineHeight: 1.45,
    textAlign: "left",
    letterSpacing: "normal",
    // Honours line breaks in the text ("\\n", or "\\n\\n" for a gap between paragraphs), while
    // still wrapping long lines to the max width.
    whiteSpace: "pre-line",
    // Hover text is only ever read, and letting the pointer land on it would count as leaving
    // the anchor anyway.
    pointerEvents: "none",
  },
  arrow: {
    position: "absolute",
    width: ARROW_SIZE,
    height: ARROW_SIZE,
    background: colors.textPrimary,
    transform: "rotate(45deg)",
  },
} as const satisfies Record<string, CSSProperties>;

/** Which side of the anchor the tooltip sits on. */
export type TooltipPlacement = "top" | "bottom" | "left" | "right";

const OPPOSITE: Record<TooltipPlacement, TooltipPlacement> = { top: "bottom", bottom: "top", left: "right", right: "left" };

interface Position {
  top: number;
  left: number;
  /** The side it ended up on: the one asked for, or the opposite when that had no room. */
  side: TooltipPlacement;
  /**
   * The arrow's offset along the anchor's edge -- from the tooltip's left edge for top and
   * bottom, from its top edge for left and right -- so it points at the anchor even when the
   * tooltip has been pushed in from a window edge.
   */
  arrowOffset: number;
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/** The arrow on the tooltip's edge that faces the anchor, half outside it. */
function arrowStyle({ side, arrowOffset }: Position): CSSProperties {
  switch (side) {
    case "top":
      return { left: arrowOffset, bottom: -ARROW_SIZE / 2 };
    case "bottom":
      return { left: arrowOffset, top: -ARROW_SIZE / 2 };
    case "left":
      return { top: arrowOffset, right: -ARROW_SIZE / 2 };
    case "right":
      return { top: arrowOffset, left: -ARROW_SIZE / 2 };
  }
}

/** Where a tooltip of this size would go on this side of the anchor, kept inside the window
 * along the anchor's edge, and whether it has room on that side. */
function place(side: TooltipPlacement, anchor: DOMRect, tooltip: DOMRect): { top: number; left: number; fits: boolean } {
  const centreX = anchor.left + anchor.width / 2;
  const centreY = anchor.top + anchor.height / 2;
  switch (side) {
    case "top": {
      const top = anchor.top - GAP - tooltip.height;
      return { top, left: clamp(centreX - tooltip.width / 2, EDGE, window.innerWidth - tooltip.width - EDGE), fits: top >= EDGE };
    }
    case "bottom": {
      const top = anchor.bottom + GAP;
      return {
        top,
        left: clamp(centreX - tooltip.width / 2, EDGE, window.innerWidth - tooltip.width - EDGE),
        fits: top + tooltip.height <= window.innerHeight - EDGE,
      };
    }
    case "left": {
      const left = anchor.left - GAP - tooltip.width;
      return { top: clamp(centreY - tooltip.height / 2, EDGE, window.innerHeight - tooltip.height - EDGE), left, fits: left >= EDGE };
    }
    case "right": {
      const left = anchor.right + GAP;
      return {
        top: clamp(centreY - tooltip.height / 2, EDGE, window.innerHeight - tooltip.height - EDGE),
        left,
        fits: left + tooltip.width <= window.innerWidth - EDGE,
      };
    }
  }
}

export interface TooltipAnchorProps {
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onFocus: (event: FocusEvent<HTMLElement>) => void;
  onBlur: () => void;
  onClick: () => void;
}

export interface TooltipHandle {
  /** Whether the bubble is showing. */
  open: boolean;
  /** Whether the pointer is over the anchor, for an anchor that changes colour while it is. */
  hovered: boolean;
  /** Whether the anchor has keyboard focus (not a click), for drawing a focus ring. */
  keyboardFocused: boolean;
  /** Show after the hover delay (or at once with 0). */
  show: (delay?: number) => void;
  hide: () => void;
  /**
   * Spread onto the anchor: shows on hover (after the delay), on focus and on click. Hides once
   * nothing keeps it open: the pointer leaving hides it unless the anchor has keyboard focus, and
   * blur hides it unless the pointer is still over it. (Focus from a mouse click doesn't pin it,
   * so clicking an icon and moving away still closes it.) An anchor with handlers of its own lays
   * them over these with composeHandlers, or overrides one by setting it after the spread.
   */
  anchorProps: TooltipAnchorProps;
  /** Render this once, anywhere in the anchor's tree; it portals itself to <body>. */
  bubble: ReactNode;
}

/**
 * The tooltip's behaviour, for an anchor the caller renders and refs. Shows on the given side of
 * the anchor (above by default), or the opposite side when there's no room, kept inside the
 * window; hides on Escape or any scroll, since a fixed tooltip would otherwise stay behind while
 * its anchor scrolls away.
 */
export function useTooltip(
  anchorRef: RefObject<HTMLElement | null>,
  text: ReactNode,
  placement: TooltipPlacement = "top",
): TooltipHandle {
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [keyboardFocused, setKeyboardFocused] = useState(false);
  const [position, setPosition] = useState<Position | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const showTimer = useRef<number | undefined>(undefined);

  function show(delay = SHOW_DELAY_MS) {
    window.clearTimeout(showTimer.current);
    showTimer.current = window.setTimeout(() => setOpen(true), delay);
  }

  function hide() {
    window.clearTimeout(showTimer.current);
    setOpen(false);
    setPosition(null);
  }

  useEffect(() => () => window.clearTimeout(showTimer.current), []);

  // Measured once it's rendered (hidden) at its natural size, then placed before it paints.
  useLayoutEffect(() => {
    if (!open || !anchorRef.current || !tooltipRef.current) return;
    const anchor = anchorRef.current.getBoundingClientRect();
    const tooltip = tooltipRef.current.getBoundingClientRect();
    const preferred = place(placement, anchor, tooltip);
    const side = preferred.fits ? placement : OPPOSITE[placement];
    const { top, left } = preferred.fits ? preferred : place(side, anchor, tooltip);
    const vertical = side === "top" || side === "bottom";
    const arrowOffset = vertical
      ? clamp(anchor.left + anchor.width / 2 - left - ARROW_SIZE / 2, 10, tooltip.width - 10 - ARROW_SIZE)
      : clamp(anchor.top + anchor.height / 2 - top - ARROW_SIZE / 2, 10, tooltip.height - 10 - ARROW_SIZE);
    setPosition({ top, left, side, arrowOffset });
  }, [open, anchorRef, placement]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    // Capture, so a scroll inside a table's own scroll container counts too.
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const bubble =
    open &&
    createPortal(
      <div
        ref={tooltipRef}
        // The caller exposes the text to assistive tech through the anchor; this is the visible copy.
        aria-hidden="true"
        data-testid="infoTooltip"
        className={position ? "animate-tooltip-in" : undefined}
        style={{
          ...styles.tooltip,
          top: position?.top ?? 0,
          left: position?.left ?? 0,
          visibility: position ? "visible" : "hidden",
        }}
      >
        {text}
        {position && <span style={{ ...styles.arrow, ...arrowStyle(position) }} />}
      </div>,
      document.body,
    );

  return {
    open,
    hovered,
    keyboardFocused,
    show,
    hide,
    anchorProps: {
      onMouseEnter: () => {
        setHovered(true);
        show();
      },
      onMouseLeave: () => {
        setHovered(false);
        // A keyboard user who has tabbed to the anchor keeps the tooltip while the pointer wanders.
        if (!keyboardFocused) hide();
      },
      onFocus: (event) => {
        setKeyboardFocused(isFocusVisible(event.currentTarget));
        show(0);
      },
      onBlur: () => {
        setKeyboardFocused(false);
        if (!hovered) hide();
      },
      onClick: () => show(0),
    },
    bubble,
  };
}
