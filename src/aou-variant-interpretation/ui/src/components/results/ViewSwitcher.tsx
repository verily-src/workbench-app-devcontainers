import { useId, useRef } from "react";
import type { CSSProperties } from "react";
import colors from "../../libs/colors";
import * as Style from "../../libs/style";
import Clickable from "../common/Clickable";
import { useTooltip } from "../common/useTooltip";
import { CompareIcon, TableIcon } from "../icons";

export type ResultsView = "table" | "review";

// The one control that decides what the page shows beneath the summary strip, so it carries more
// weight than the small Ancestry/Age toggle: a taller pill, a stronger border, and the selected
// option filled in the accent with white type rather than lifted on a shadow.
const styles = {
  group: {
    display: "inline-flex",
    gap: 3,
    padding: 3,
    background: colors.surface1,
    border: `1px solid ${colors.borderStrong}`,
    borderRadius: 999,
  },
  option: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    padding: "6px 16px",
    border: "none",
    borderRadius: 999,
    background: "none",
    color: colors.textSecondary,
    fontSize: 12.5,
    fontWeight: 600,
    lineHeight: 1.2,
    whiteSpace: "nowrap",
    cursor: "pointer",
    // No eased colour change: mid-fade, the option losing selection shows white text on a
    // near-white fill for a few frames, which reads as a flicker.
  },
  optionHover: {
    background: colors.surface0,
    color: colors.textPrimary,
  },
  optionSelected: {
    background: colors.textAccent,
    color: colors.white,
    boxShadow: Style.shadows.pill,
  },
  // An unavailable option is aria-disabled rather than natively disabled, so it stays in the tab
  // order and keeps receiving pointer events: the reason it can't be chosen is a tooltip shown on
  // hover and on focus, which a natively disabled button (no focus, no pointer events) can't do.
  optionUnavailable: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
} as const satisfies Record<string, CSSProperties>;

const OPTIONS: { value: ResultsView; label: string; icon: typeof TableIcon }[] = [
  { value: "table", label: "Table", icon: TableIcon },
  { value: "review", label: "Review", icon: CompareIcon },
];

interface ViewSwitcherProps {
  value: ResultsView;
  onChange: (view: ResultsView) => void;
  /** Why Review can't be chosen right now, e.g. no phenotype filter; disables that option. */
  reviewUnavailableReason?: string;
}

interface OptionProps {
  label: string;
  icon: typeof TableIcon;
  selected: boolean;
  /** Given, the option can't be chosen; this says why, as its tooltip and its accessible description. */
  disabledReason?: string;
  onSelect: () => void;
}

function Option({ label, icon: Icon, selected, disabledReason, onSelect }: OptionProps) {
  const unavailable = disabledReason !== undefined;
  const ref = useRef<HTMLButtonElement>(null);
  const reasonId = useId();
  const tooltip = useTooltip(ref, disabledReason ?? "", "top");

  return (
    <>
      <Clickable
        ref={ref}
        aria-pressed={selected}
        aria-disabled={unavailable || undefined}
        aria-describedby={unavailable ? reasonId : undefined}
        style={{
          ...styles.option,
          ...(selected ? styles.optionSelected : undefined),
          ...(unavailable ? styles.optionUnavailable : undefined),
        }}
        hoverStyle={selected || unavailable ? undefined : styles.optionHover}
        // Activation is guarded here rather than by `disabled`, which would drop the option from
        // the tab order. The tooltip's own click handler still shows the reason.
        onClick={unavailable ? undefined : onSelect}
        {...(unavailable ? tooltip.anchorProps : undefined)}
      >
        <Icon size={16} aria-hidden="true" />
        {label}
      </Clickable>
      {/* Beside the button, not inside it, so the reason is its description and not part of its name. */}
      {unavailable && (
        <>
          <span id={reasonId} style={Style.elements.visuallyHidden}>
            {disabledReason}
          </span>
          {tooltip.bubble}
        </>
      )}
    </>
  );
}

export default function ViewSwitcher({ value, onChange, reviewUnavailableReason }: ViewSwitcherProps) {
  return (
    // A group of toggle buttons, not tabs: there are no tab panels or arrow-key moves, so the
    // tab pattern would promise what isn't there. Pressed state says which view is showing.
    <div role="group" aria-label="Results view" style={styles.group}>
      {OPTIONS.map(({ value: option, label, icon }) => (
        <Option
          key={option}
          label={label}
          icon={icon}
          selected={value === option}
          disabledReason={option === "review" ? reviewUnavailableReason : undefined}
          onSelect={() => onChange(option)}
        />
      ))}
    </div>
  );
}
