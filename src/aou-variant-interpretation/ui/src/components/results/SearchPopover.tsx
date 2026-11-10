import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import colors, { alpha } from "../../libs/colors";
import * as Style from "../../libs/style";
import type { ConditionConcept } from "../../api/conditions";
import { isSubmitShortcut } from "../../utils/submitShortcut";
import { overLimitMessage, variantEntryStatus } from "../../utils/variants";
import Clickable from "../common/Clickable";
import { SearchIcon } from "../icons";
import PhenotypeStep from "../PhenotypeStep";
import SearchSteps from "../SearchSteps";
import VariantsStep from "../VariantsStep";
import { TOP_BAR_HEIGHT } from "./TopBar";

const styles = {
  backdrop: {
    position: "fixed",
    top: TOP_BAR_HEIGHT,
    left: 0,
    right: 0,
    bottom: 0,
    background: alpha(colors.textPrimary, 0.18),
  },
  // Width and left offset come from placePopover, which keeps it inside the viewport.
  popover: {
    position: "absolute",
    top: "calc(100% + 6px)",
    zIndex: 1,
    padding: 16,
    background: colors.surface2,
    border: `1px solid ${colors.border}`,
    borderRadius: `0 0 ${Style.panelRadius}px ${Style.panelRadius}px`,
    boxShadow: Style.shadows.raised,
    cursor: "auto",
  },
  actions: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 8,
    marginTop: 16,
    paddingTop: 12,
    borderTop: `1px solid ${colors.border}`,
  },
  error: {
    marginRight: "auto",
    color: colors.textDanger,
    fontSize: 12.5,
    fontWeight: 600,
  },
} as const satisfies Record<string, CSSProperties>;

const POPOVER_WIDTH = 760;
/** Kept clear on either side, matching the top bar's own padding. */
const VIEWPORT_MARGIN = 20;

/**
 * The popover's width and left offset from the search box, for a box `anchorLeft` px into a
 * `viewportWidth` px viewport. It hangs from the box's left edge when it fits; otherwise it
 * narrows to the viewport and slides left as far as needed to keep the right margin.
 */
export function placePopover(anchorLeft: number, viewportWidth: number) {
  const width = Math.min(POPOVER_WIDTH, viewportWidth - 2 * VIEWPORT_MARGIN);
  const left = Math.min(0, viewportWidth - VIEWPORT_MARGIN - width - anchorLeft);
  return { width, left };
}

/** What Tab can land on inside the popover, for keeping focus there while it's open. */
const FOCUSABLE = 'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

interface SearchPopoverProps {
  open: boolean;
  variantsText: string;
  /** The phenotypes to filter by, starting as the ones the page was searched with. */
  phenotypes: ConditionConcept[];
  variantsLimit: number;
  onVariantsChange: (value: string) => void;
  onPhenotypesChange: (phenotypes: ConditionConcept[]) => void;
  /** Also fired by Escape and by clicking the backdrop. */
  onCancel: () => void;
  onSearch: () => void;
}

/**
 * The results page's edit-search form, as a popover hanging from the top bar's search box.
 * Rendered by TopBar inside its anchor. Stays mounted while closed (hidden), so the fields
 * keep their state between openings; the page remounts it to reset them.
 */
export default function SearchPopover({
  open,
  variantsText,
  phenotypes,
  variantsLimit,
  onVariantsChange,
  onPhenotypesChange,
  onCancel,
  onSearch,
}: SearchPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState({ width: POPOVER_WIDTH, left: 0 });
  const { count: enteredCount, overLimit, canSearch } = variantEntryStatus(variantsText, variantsLimit);

  // Locks page scrolling while open
  useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    const previous = { overflow: root.style.overflow, paddingRight: root.style.paddingRight };
    const scrollbarWidth = window.innerWidth - root.clientWidth;
    root.style.overflow = "hidden";
    if (scrollbarWidth > 0) root.style.paddingRight = `${scrollbarWidth}px`;
    return () => {
      root.style.overflow = previous.overflow;
      root.style.paddingRight = previous.paddingRight;
    };
  }, [open]);

  // Measured before paint, so it never shows overflowing first. The box's own position is the
  // popover's, less the offset already applied.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const popover = popoverRef.current;
      if (!popover) return;
      const anchorLeft = popover.getBoundingClientRect().left - (parseFloat(popover.style.left) || 0);
      setPlacement(placePopover(anchorLeft, document.documentElement.clientWidth));
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open]);

  // Starts you in the variants field.
  useEffect(() => {
    if (open) popoverRef.current?.querySelector("textarea")?.focus();
  }, [open]);

  // On the document so it works wherever focus is. Tab wraps between the popover's first and last
  // controls rather than reaching the page behind the backdrop.
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) onCancel();
      if (event.key !== "Tab" || !popoverRef.current) return;
      const focusable = [...popoverRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const inside = popoverRef.current.contains(document.activeElement);
      if (event.shiftKey && (!inside || document.activeElement === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || document.activeElement === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onCancel]);

  return (
    <div style={{ display: open ? "block" : "none" }}>
      <div style={styles.backdrop} onClick={onCancel} aria-hidden="true" data-testid="searchPopoverBackdrop" />
      <div
        ref={popoverRef}
        role="dialog"
        aria-modal="true"
        aria-label="Edit search"
        style={{ ...styles.popover, ...placement }}
        onKeyDown={(event) => {
          if (!isSubmitShortcut(event)) return;
          event.preventDefault();
          if (canSearch) onSearch();
        }}
      >
        <SearchSteps>
          <VariantsStep
            value={variantsText}
            onChange={onVariantsChange}
            limit={variantsLimit}
            minHeight={120}
            appearance="plain"
          />
          <PhenotypeStep
            id="editSearchCondition"
            picked={phenotypes}
            onPick={(concept) => onPhenotypesChange([...phenotypes, concept])}
            onRemove={(conceptId) => onPhenotypesChange(phenotypes.filter((concept) => concept.conceptId !== conceptId))}
            appearance="plain"
          />
        </SearchSteps>

        <div style={styles.actions}>
          {overLimit && (
            <p style={styles.error} aria-live="polite">
              {overLimitMessage(enteredCount, variantsLimit)}
            </p>
          )}
          <Clickable style={Style.buttons.secondary} hoverStyle={Style.buttons.secondaryHover} onClick={onCancel}>
            Cancel
          </Clickable>
          <Clickable
            style={Style.buttons.primary}
            hoverStyle={Style.buttons.primaryHover}
            disabledStyle={Style.buttons.disabled}
            disabled={!canSearch}
            onClick={onSearch}
          >
            <SearchIcon size={14} aria-hidden="true" />
            Search
          </Clickable>
        </div>
      </div>
    </div>
  );
}
