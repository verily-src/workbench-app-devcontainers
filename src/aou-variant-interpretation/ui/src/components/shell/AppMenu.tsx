import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import colors from "../../libs/colors";
import * as Style from "../../libs/style";
import Clickable from "../common/Clickable";
import { MenuIcon } from "../icons";
import AppDrawer from "./AppDrawer";

const styles = {
  // A 28px hit area in a 41px bar, like the brand's hover fill beside it.
  button: {
    ...Style.buttons.icon,
    padding: 5,
    margin: "-5px 0",
    borderRadius: 6,
    color: colors.textPrimary,
  },
  buttonOpen: {
    ...Style.buttons.iconHover,
  },
} as const satisfies Record<string, CSSProperties>;

/** The bar's hamburger, and the sidebar it opens. Focus comes back to the button when the sidebar closes. */
export default function AppMenu() {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (wasOpen.current && !open) buttonRef.current?.focus();
    wasOpen.current = open;
  }, [open]);

  return (
    <>
      <Clickable
        ref={buttonRef}
        style={{ ...styles.button, ...(open ? styles.buttonOpen : undefined) }}
        hoverStyle={Style.buttons.iconHover}
        onClick={() => setOpen(true)}
        aria-label="Menu"
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Menu"
      >
        <MenuIcon size={18} aria-hidden="true" />
      </Clickable>
      <AppDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
