import type { ButtonHTMLAttributes, CSSProperties, Ref } from "react";
import { useHover } from "../../libs/hooks";

interface ClickableProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "style"> {
  style?: CSSProperties;
  /** Merged over `style` while hovered, in place of a ":hover" rule. Suppressed when disabled. */
  hoverStyle?: CSSProperties;
  /** Merged over `style` while disabled, in place of a ":disabled" rule. */
  disabledStyle?: CSSProperties;
  ref?: Ref<HTMLButtonElement>;
}

/**
 * A button that takes its hover and disabled appearance as style objects.
 *
 * Every hoverable button in the app goes through this, which is what keeps the ":hover"-as-state
 * bookkeeping out of the components themselves -- they just pass the two styles. Pair it with the
 * `buttons` groups in libs/style.ts (`style={Style.buttons.primary}
 * hoverStyle={Style.buttons.primaryHover}`).
 */
export default function Clickable({
  style,
  hoverStyle,
  disabledStyle,
  disabled,
  onMouseEnter,
  onMouseLeave,
  ...props
}: ClickableProps) {
  const { hovered, hoverProps } = useHover();

  return (
    <button
      type="button"
      disabled={disabled}
      style={{
        ...style,
        ...(hovered && !disabled ? hoverStyle : undefined),
        ...(disabled ? disabledStyle : undefined),
      }}
      onMouseEnter={(event) => {
        hoverProps.onMouseEnter();
        onMouseEnter?.(event);
      }}
      onMouseLeave={(event) => {
        hoverProps.onMouseLeave();
        onMouseLeave?.(event);
      }}
      {...props}
    />
  );
}
