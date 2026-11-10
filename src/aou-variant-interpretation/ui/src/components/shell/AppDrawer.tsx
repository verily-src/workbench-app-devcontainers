import { useEffect, useMemo, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import colors, { alpha } from "../../libs/colors";
import { useHoveredKey } from "../../libs/hooks";
import * as Style from "../../libs/style";
import { describeSearchedAt, loadRecentSearches, type RecentSearch } from "../../utils/recentSearches";
import { describeAlternatives } from "../../utils/phenotypes";
import { resultsPath } from "../../utils/variants";
import Clickable from "../common/Clickable";
import AppVersion from "../elements/AppVersion";
import { ActivityIcon, ClockIcon, CloseIcon, DatabaseIcon, GaugeIcon, GearIcon, SearchIcon } from "../icons";
import type { IconProps } from "../icons";
import { FOOTER_HEIGHT } from "../results/Footer";
import { TOP_BAR_HEIGHT } from "../results/TopBar";

/** Where the drawer goes: the search, then each workspace page. Add new pages here. */
export const APP_MENU_ITEMS: { path: string; label: string; icon: (props: IconProps) => ReactNode }[] = [
  { path: "/", label: "New search", icon: SearchIcon },
  { path: "/data-sources", label: "Sources", icon: DatabaseIcon },
  { path: "/system-status", label: "Status", icon: ActivityIcon },
  { path: "/usage", label: "Usage", icon: GaugeIcon },
  { path: "/settings", label: "Settings", icon: GearIcon },
];

/** How many recent searches the drawer lists; the search page shows them all. */
const RECENT_LIMIT = 5;

/** Variant IDs shown before the rest are summarised as "+N". */
const PREVIEW_VARIANTS = 2;

const DRAWER_WIDTH = 300;

const styles = {
  scrim: {
    position: "fixed",
    inset: 0,
    zIndex: 100,
    background: alpha(colors.brandNavy, 0.28),
  },
  drawer: {
    position: "fixed",
    top: 0,
    left: 0,
    bottom: 0,
    zIndex: 101,
    display: "flex",
    flexDirection: "column",
    width: DRAWER_WIDTH,
    maxWidth: "calc(100vw - 48px)",
    background: colors.surface2,
    boxShadow: `12px 0 32px ${alpha(colors.brandNavy, 0.18)}`,
    outline: "none",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    flexShrink: 0,
    padding: "0 20px",
    borderBottom: `1px solid ${colors.border}`,
  },
  close: {
    ...Style.buttons.icon,
    padding: 5,
    margin: "-5px 0",
    borderRadius: 6,
    color: colors.textPrimary,
  },
  brand: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: 800,
    letterSpacing: 0.3,
    textDecoration: "none",
  },
  nav: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
    padding: "10px 0",
  },
  list: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    margin: 0,
    padding: 0,
    listStyle: "none",
  },
  section: {
    ...Style.elements.eyebrow,
    padding: "12px 20px 4px",
    color: colors.textSecondary,
  },
  item: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    margin: "0 8px",
    padding: "9px 12px",
    borderRadius: 8,
    color: colors.textBody,
    fontSize: 13,
    fontWeight: 500,
    textDecoration: "none",
  },
  itemHovered: {
    background: colors.surface0,
    color: colors.textAccent,
  },
  itemCurrent: {
    background: colors.bgAccent,
    color: colors.textAccent,
    fontWeight: 600,
  },
  itemIcon: {
    flexShrink: 0,
    color: colors.textAccent,
  },
  recentText: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    minWidth: 0,
  },
  recentVariants: {
    ...Style.elements.mono,
    overflow: "hidden",
    color: colors.textAccent,
    fontSize: 12,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  recentSub: {
    overflow: "hidden",
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: 400,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  footer: {
    display: "flex",
    alignItems: "center",
    flexShrink: 0,
    height: FOOTER_HEIGHT,
    padding: "0 20px",
    borderTop: `1px solid ${colors.border}`,
  },
} as const satisfies Record<string, CSSProperties>;

function describeVariants(variants: string[]): string {
  const shown = variants.slice(0, PREVIEW_VARIANTS).join(", ");
  const rest = variants.length - PREVIEW_VARIANTS;
  return rest > 0 ? `${shown} +${rest}` : shown;
}

function recentSub(search: RecentSearch): string {
  const who = search.conditions.length > 0 ? describeAlternatives(search.conditions.map((c) => c.name)) : "No phenotype";
  return `${who} · ${describeSearchedAt(search.searchedAt)}`;
}

interface AppDrawerProps {
  open: boolean;
  onClose: () => void;
}

export default function AppDrawer({ open, onClose }: AppDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const { hoveredKey, hoverProps } = useHoveredKey<string>();
  const { pathname } = useLocation();
  // Read when opened, so a search run since last time shows up.
  const recent = useMemo(() => (open ? loadRecentSearches().slice(0, RECENT_LIMIT) : []), [open]);

  useEffect(() => {
    if (!open) return;
    drawerRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const item = (key: string, to: string, current: boolean, children: ReactNode, label?: string) => (
    <Link
      to={to}
      aria-current={current ? "page" : undefined}
      aria-label={label}
      onClick={onClose}
      style={{
        ...styles.item,
        ...(hoveredKey === key ? styles.itemHovered : undefined),
        ...(current ? styles.itemCurrent : undefined),
      }}
      {...hoverProps(key)}
    >
      {children}
    </Link>
  );

  return (
    <>
      <div style={styles.scrim} onClick={onClose} aria-hidden="true" data-testid="appDrawerScrim" />
      <div ref={drawerRef} role="dialog" aria-modal="true" aria-label="Menu" tabIndex={-1} style={styles.drawer}>
        <div style={{ ...styles.header, height: TOP_BAR_HEIGHT }}>
          <Clickable
            style={styles.close}
            hoverStyle={Style.buttons.iconHover}
            onClick={onClose}
            aria-label="Close menu"
            title="Close"
          >
            <CloseIcon size={18} aria-hidden="true" />
          </Clickable>
          <Link to="/" style={styles.brand} onClick={onClose} aria-label="VIA home, new search">
            <img src="/favicon.svg" alt="" width={22} height={22} style={{ display: "block" }} />
            VIA
          </Link>
        </div>
        <nav style={styles.nav} aria-label="Menu">
          <ul style={styles.list}>
            {APP_MENU_ITEMS.map((entry, index) => {
              const Icon = entry.icon;
              return (
                <li key={entry.path}>
                  {index === 1 && <div style={styles.section}>Workspace</div>}
                  {item(
                    entry.path,
                    entry.path,
                    pathname === entry.path,
                    <>
                      <Icon size={16} style={styles.itemIcon} aria-hidden="true" />
                      {entry.label}
                    </>,
                  )}
                </li>
              );
            })}
          </ul>
          {recent.length > 0 && (
            <>
              <div style={styles.section}>Recent</div>
              <ul style={styles.list} aria-label="Recent searches">
                {recent.map((search) => (
                  <li key={search.searchedAt}>
                    {item(
                      `recent-${search.searchedAt}`,
                      resultsPath(
                        search.variants,
                        search.conditions.map((condition) => condition.conceptId),
                      ),
                      false,
                      <>
                        <ClockIcon size={16} style={styles.itemIcon} aria-hidden="true" />
                        <span style={styles.recentText}>
                          <span style={styles.recentVariants}>{describeVariants(search.variants)}</span>
                          <span style={styles.recentSub}>{recentSub(search)}</span>
                        </span>
                      </>,
                      `Run again: ${search.variants.length} variant${search.variants.length === 1 ? "" : "s"}, ${recentSub(search)}`,
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </nav>
        <div style={styles.footer}>
          <AppVersion />
        </div>
      </div>
    </>
  );
}
