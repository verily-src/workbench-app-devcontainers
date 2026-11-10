import { useState } from "react";
import type { CSSProperties } from "react";
import colors from "../../libs/colors";
import * as Style from "../../libs/style";
import { usePreference, type Preferences } from "../../utils/preferences";
import { clearRecentSearches, loadRecentSearches } from "../../utils/recentSearches";
import Clickable from "../common/Clickable";
import { TrashIcon } from "../icons";

// The app's switches, one row each: a checkbox, its name, and a line on what it does; then the
// search history, with the button that clears it. All kept per browser (see utils/preferences
// and utils/recentSearches); nothing here reaches the backend (yet).
const styles = {
  list: {
    display: "flex",
    flexDirection: "column",
    margin: 0,
    padding: 0,
    listStyle: "none",
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    overflow: "hidden",
  },
  option: {
    display: "grid",
    gridTemplateColumns: "auto minmax(0, 1fr)",
    alignItems: "center",
    columnGap: 10,
    rowGap: 2,
    padding: "10px 12px",
    cursor: "pointer",
  },
  optionBox: {
    margin: 0,
    accentColor: colors.textAccent,
    cursor: "pointer",
  },
  optionAbout: {
    gridColumn: 2,
  },
  text: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
  },
  name: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: 600,
  },
  about: {
    color: colors.textSecondary,
    fontSize: 11.5,
    lineHeight: 1.4,
  },
  action: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    marginTop: 12,
    padding: "10px 12px",
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
  },
  button: {
    ...Style.buttons.danger,
    flexShrink: 0,
  },
} as const satisfies Record<string, CSSProperties>;

/** A switch: the preference it sets, and what to call it. */
const OPTIONS: { key: keyof Preferences; name: string; about: string }[] = [
  {
    key: "demoMode",
    name: "Demo mode",
    about: "Shows the curated example searches under the variants box.",
  },
  {
    key: "showUsageMeter",
    name: "Show usage in the top bar",
    about: "A running readout of this session\u2019s BigQuery spend in the top bar.",
  },
];

function Option({ option, first }: { option: (typeof OPTIONS)[number]; first: boolean }) {
  const [on, setOn] = usePreference(option.key);
  return (
    <li style={{ borderTop: first ? undefined : `1px solid ${colors.border}` }}>
      <label style={styles.option}>
        <input type="checkbox" style={styles.optionBox} checked={on} onChange={(event) => setOn(event.target.checked)} />
        <span style={styles.name}>{option.name}</span>
        <span style={{ ...styles.about, ...styles.optionAbout }}>{option.about}</span>
      </label>
    </li>
  );
}

/** i.e. "0 searches", "1 search", "12 searches". */
function describeHistory(count: number) {
  return `${count} search${count === 1 ? "" : "es"}`;
}

export default function SettingsPanel() {
  const [history, setHistory] = useState(() => loadRecentSearches().length);
  return (
    <>
      <p style={Style.elements.panelIntro}>These preferences are only remembered in this browser.</p>
      <ul style={styles.list}>
        {OPTIONS.map((option, index) => (
          <Option key={option.key} option={option} first={index === 0} />
        ))}
      </ul>
      <div style={styles.action}>
        <span style={styles.text}>
          <span style={styles.name}>Recent searches</span>
          <span style={styles.about}>
            This will remove {describeHistory(history)} from your history.
          </span>
        </span>
        <Clickable
          style={styles.button}
          hoverStyle={Style.buttons.dangerHover}
          disabledStyle={Style.buttons.disabled}
          disabled={history === 0}
          onClick={() => {
            clearRecentSearches();
            setHistory(0);
          }}
        >
          <TrashIcon size={14} aria-hidden="true" />
          Clear recent searches
        </Clickable>
      </div>
    </>
  );
}
