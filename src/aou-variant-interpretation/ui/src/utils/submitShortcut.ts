// Ctrl/⌘+Enter runs a search from anywhere in a search form -- the entry page's card and the
// results page's edit-search popover. Handled on the form rather than on one field, so it works
// whichever field has focus.

import type { KeyboardEvent } from "react";

/** For the keyboard hint: ⌘ on Apple platforms, Ctrl elsewhere. */
export const SUBMIT_SHORTCUT_LABEL =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ Enter" : "Ctrl Enter";

/**
 * Whether a keydown bubbling up to a search form is the submit shortcut. Skips one a field
 * already handled -- the condition field's Enter on a highlighted option picks that option, and
 * searching at the same time would search without it.
 */
export function isSubmitShortcut(event: KeyboardEvent): boolean {
  return event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.defaultPrevented;
}
