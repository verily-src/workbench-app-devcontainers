import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import colors from "../libs/colors";
import { useHover, useHoveredKey } from "../libs/hooks";
import * as Style from "../libs/style";
import { ChevronDownIcon } from "./icons";

// A link that opens a small context menu of things to fill the form with i.e. the curated examples

const styles = {
  wrap: {
    position: "relative",
    flexShrink: 0,
  },
  trigger: {
    display: "inline-flex",
    alignItems: "center",
    gap: 3,
    padding: 0,
    border: "none",
    background: "none",
    color: colors.textAccent,
    fontSize: 11.5,
    fontWeight: 600,
    cursor: "pointer",
  },
  triggerHover: {
    textDecoration: "underline",
  },
  menu: {
    position: "absolute",
    top: "calc(100% + 6px)",
    right: 0,
    zIndex: 10,
    width: 300,
    margin: 0,
    padding: 4,
    listStyle: "none",
    background: colors.surface2,
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    boxShadow: Style.shadows.raised,
  },
  item: {
    display: "block",
    width: "100%",
    padding: "8px 10px",
    border: "none",
    borderRadius: 6,
    background: "none",
    textAlign: "left",
    cursor: "pointer",
  },
  itemActive: {
    background: colors.surface1,
  },
  itemTitleRow: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 10,
  },
  itemTitle: {
    overflow: "hidden",
    color: colors.textPrimary,
    fontSize: 12.5,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  itemMeta: {
    flexShrink: 0,
    color: colors.textMuted,
    fontSize: 11,
  },
  itemDescription: {
    display: "block",
    marginTop: 2,
    color: colors.textSecondary,
    fontSize: 11.5,
    lineHeight: 1.4,
  },
} as const satisfies Record<string, CSSProperties>;

export interface LinkMenuItem {
  key: string;
  title: ReactNode;
  /** At the right of the title, e.g. when a search was run. */
  meta?: ReactNode;
  description?: ReactNode;
  onPick: () => void;
}

interface LinkMenuProps {
  /** The link's text. */
  label: string;
  /** The menu's accessible name. */
  menuLabel: string;
  items: LinkMenuItem[];
  width?: number;
}

export default function LinkMenu({ label, menuLabel, items, width = 300 }: LinkMenuProps) {
  const [open, setOpen] = useState(false);
  const { hovered, hoverProps } = useHover();
  const { hoveredKey, hoverProps: itemHoverProps } = useHoveredKey<string>();
  // Highlighted for keyboard focus too, not just the pointer, so arrowing through shows where you are.
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const menuId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Into the menu when it opens, so the arrow keys work straight away.
  useEffect(() => {
    if (open) itemRefs.current[0]?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePress = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsidePress);
    return () => document.removeEventListener("mousedown", closeOnOutsidePress);
  }, [open]);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function handleMenuKeyDown(event: KeyboardEvent) {
    const items = itemRefs.current.filter((item) => item !== null);
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const focusAt = (i: number) => items[(i + items.length) % items.length]?.focus();
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusAt(index + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusAt(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusAt(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusAt(items.length - 1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div ref={wrapRef} style={styles.wrap}>
      <button
        ref={triggerRef}
        type="button"
        style={{ ...styles.trigger, ...(hovered || open ? styles.triggerHover : undefined) }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((current) => !current)}
        {...hoverProps}
      >
        {label}
        <ChevronDownIcon size={11} aria-hidden="true" />
      </button>
      {open && (
        <ul id={menuId} role="menu" aria-label={menuLabel} style={{ ...styles.menu, width }} onKeyDown={handleMenuKeyDown}>
          {items.map((item, index) => (
            <li key={item.key} role="none">
              <button
                ref={(element) => {
                  itemRefs.current[index] = element;
                }}
                type="button"
                role="menuitem"
                style={{
                  ...styles.item,
                  ...(hoveredKey === item.key || focusedKey === item.key ? styles.itemActive : undefined),
                }}
                onFocus={() => setFocusedKey(item.key)}
                onBlur={() => setFocusedKey(null)}
                onClick={() => {
                  setOpen(false);
                  item.onPick();
                }}
                {...itemHoverProps(item.key)}
              >
                <span style={styles.itemTitleRow}>
                  <span style={styles.itemTitle}>{item.title}</span>
                  {item.meta !== undefined && <span style={styles.itemMeta}>{item.meta}</span>}
                </span>
                {item.description !== undefined && <span style={styles.itemDescription}>{item.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
