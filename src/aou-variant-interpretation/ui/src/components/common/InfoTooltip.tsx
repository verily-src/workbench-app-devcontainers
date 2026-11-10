import { useId, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import * as Style from "../../libs/style";
import { InfoIcon } from "../icons";
import { useTooltip } from "./useTooltip";

const styles = {
  icon: {
    ...Style.elements.tooltipIcon,
    position: "relative",
  },
} as const satisfies Record<string, CSSProperties>;

interface InfoTooltipProps {
  /**
   * The explanation, shown on hover or focus and announced as the icon's description. Line
   * breaks are kept, so "\n\n" separates paragraphs -- pass it as a JS string (text={"..."}),
   * since a plain JSX attribute string doesn't turn \n into a newline.
   */
  text: ReactNode;
  /** Merged over the icon button's own style, e.g. InfoLabel's alignment margins. */
  style?: CSSProperties;
}

/**
 * A circled "i" that explains the thing beside it, e.g. a column header, in the app's tooltip
 * (see useTooltip) rather than the browser's native title text.
 *
 * Shows on hover (after a short delay), keyboard focus or a tap. Clicks on it don't reach the
 * header underneath, so it never sorts the column.
 */
export default function InfoTooltip({ text, style }: InfoTooltipProps) {
  const iconRef = useRef<HTMLButtonElement>(null);
  const descriptionId = useId();
  const tooltip = useTooltip(iconRef, text);

  return (
    <>
      <button
        ref={iconRef}
        type="button"
        style={{
          ...styles.icon,
          ...style,
          ...(tooltip.hovered || tooltip.open ? Style.elements.tooltipIconActive : undefined),
          ...(tooltip.keyboardFocused ? Style.elements.tooltipIconFocusRing : undefined),
        }}
        aria-label="More information"
        aria-describedby={descriptionId}
        {...tooltip.anchorProps}
        onClick={(event) => {
          // A header underneath would otherwise sort on this click.
          event.stopPropagation();
          tooltip.anchorProps.onClick();
        }}
      >
        <InfoIcon size={16} aria-hidden="true" />
        {/* Always present, so screen readers get the explanation without hovering. */}
        <span id={descriptionId} style={Style.elements.visuallyHidden}>
          {text}
        </span>
      </button>
      {tooltip.bubble}
    </>
  );
}
