// State hooks standing in for the CSS features an inline style object can't express.

import { useEffect, useLayoutEffect, useState, type RefObject } from "react";

/** Tracks ":hover" as state, so a hovered style can be merged over the base one. */
export function useHover() {
  const [hovered, setHovered] = useState(false);
  return {
    hovered,
    hoverProps: {
      onMouseEnter: () => setHovered(true),
      onMouseLeave: () => setHovered(false),
    },
  };
}

/**
 * useHover for a list, where a hook per item isn't possible: table rows, footer links.
 *
 * Only one item can be hovered at a time, so one piece of state holds whichever key that is.
 */
export function useHoveredKey<K>() {
  const [hoveredKey, setHoveredKey] = useState<K | null>(null);
  return {
    hoveredKey,
    hoverProps: (key: K) => ({
      onMouseEnter: () => setHoveredKey(key),
      // Guarded against a leave firing after the pointer has already entered the next item,
      // which would otherwise clear that one's hover.
      onMouseLeave: () => setHoveredKey((current) => (current === key ? null : current)),
    }),
  };
}

/** Tracks ":focus" as state, for fields that change border/background while focused. */
export function useFocus() {
  const [focused, setFocused] = useState(false);
  return {
    focused,
    focusProps: {
      onFocus: () => setFocused(true),
      onBlur: () => setFocused(false),
    },
  };
}

/** Watches a "@media" breakpoint, for layouts that have to restructure rather than just restyle. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const handleChange = () => setMatches(mediaQuery.matches);
    // Re-read on subscribe as well as on change: the viewport may have crossed the breakpoint
    // between the initial render and this effect.
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [query]);

  return matches;
}

/**
 * Centres an element in whatever part of its parent is on screen when it first appears, for content
 * in a tall container that would otherwise sit at its top, or below the fold. It then stays put
 * while the page scrolls. The element moves by a transform and never leaves the parent's box: a
 * parent that later shrinks pulls it back inside.
 *
 * `topInset` is the height of anything pinned over the top of the window, like the top bar.
 */
export function useCenterAboveFold(ref: RefObject<HTMLElement | null>, topInset = 0) {
  useLayoutEffect(() => {
    const element = ref.current;
    const parent = element?.parentElement;
    if (!element || !parent) return;
    const slackOf = () => Math.max(0, parent.getBoundingClientRect().height - element.offsetHeight);
    const place = (offset: number) => {
      element.style.transform = `translateY(${Math.round(Math.min(slackOf(), Math.max(0, offset)))}px)`;
    };

    const box = parent.getBoundingClientRect();
    const top = Math.max(box.top, topInset);
    const bottom = Math.min(box.bottom, window.innerHeight);
    const offset =
      bottom > top
        ? (top + bottom) / 2 - box.top - element.offsetHeight / 2
        : box.top >= window.innerHeight
          ? 0
          : slackOf();
    place(offset);

    // The parent grows and shrinks with the table (rows expanding, sorting); keep the chosen spot
    // where it still fits.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => place(offset));
    observer?.observe(parent);
    return () => observer?.disconnect();
  }, [ref, topInset]);
}

/**
 * The element's current width, re-read as it resizes, for layout choices an inline style can't
 * make from a container query. Undefined before the first measurement, and in browsers (and
 * jsdom) without ResizeObserver, so callers should treat that as "wide enough".
 */
export function useElementWidth(ref: RefObject<HTMLElement | null>): number | undefined {
  const [width, setWidth] = useState<number>();
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const measure = () => setWidth(element.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/**
 * Whether the browser would draw a focus ring here: keyboard focus, not a click. Inline styles
 * can't use :focus-visible, so it's asked of the element instead. Browsers too old to know the
 * selector throw, and get the ring on every focus.
 */
export function isFocusVisible(element: Element): boolean {
  try {
    return element.matches(":focus-visible");
  } catch {
    return true;
  }
}

type Handler = (...args: never[]) => void;

/**
 * Two sets of event handlers as one, calling both where they share a name (`base` first). For
 * laying an element's own handlers over a hook's, e.g. a tooltip's anchor props plus the hover
 * highlight of the group it belongs to.
 */
export function composeHandlers<A extends object, B extends object>(base: A, extra: B): A & B {
  const merged = { ...base } as Record<string, Handler | undefined>;
  for (const [name, handler] of Object.entries(extra) as [string, Handler | undefined][]) {
    const existing = merged[name];
    merged[name] =
      existing && handler
        ? (...args: never[]) => {
            existing(...args);
            handler(...args);
          }
        : (handler ?? existing);
  }
  return merged as A & B;
}
